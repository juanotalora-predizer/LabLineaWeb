"""Catálogo de exámenes (etapa 6; spec funcional/0009, sección 1).

Pruebas específicas del plan:
- Las exportaciones a CSV neutralizan fórmulas (inyección CSV).
- Rangos solapados o con huecos → advertencia.
"""

import csv
import io
import re
import uuid

import pytest
from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.catalogo import rangos
from app.catalogo.rangos import EDAD_MAXIMA_DIAS, Rango
from app.catalogo.rutas import celda_segura
from tests.ayudas import autenticar, cliente, csrf
from tests.conftest import correr, ejecutar_en_tenant

ANIO = 365


# --- Huecos y solapes (lógica pura) ---


def test_cobertura_completa_sin_advertencias():
    assert rangos.analizar([Rango("T", 0, EDAD_MAXIMA_DIAS)]) == []
    assert (
        rangos.analizar(
            [Rango("M", 0, EDAD_MAXIMA_DIAS), Rango("F", 0, 18 * ANIO), Rango("F", 18 * ANIO, EDAD_MAXIMA_DIAS)]
        )
        == []
    )


def test_huecos_y_solapes():
    advertencias = rangos.analizar([Rango("T", 0, 18 * ANIO), Rango("M", 10 * ANIO, 60 * ANIO)])
    tipos = {(a.tipo, a.sexo) for a in advertencias}
    assert ("SOLAPE", "M") in tipos  # T y M se cruzan entre 10 y 18 años
    assert ("HUECO", "F") in tipos  # nadie cubre a las mujeres desde los 18
    assert ("HUECO", "M") in tipos  # ni a los hombres después de los 60
    solape = next(a for a in advertencias if a.tipo == "SOLAPE")
    assert (solape.desde_dias, solape.hasta_dias) == (10 * ANIO, 18 * ANIO)


def test_adultos_solamente_advierte_el_hueco_de_ninos():
    advertencias = rangos.analizar([Rango("T", 18 * ANIO, EDAD_MAXIMA_DIAS)])
    assert {(a.tipo, a.desde_dias, a.hasta_dias) for a in advertencias} == {("HUECO", 0, 18 * ANIO)}


rango_aleatorio = st.builds(
    lambda sexo, a, b: Rango(sexo, min(a, b), max(a, b) + 1),
    st.sampled_from(["M", "F", "T"]),
    st.integers(0, EDAD_MAXIMA_DIAS - 1),
    st.integers(0, EDAD_MAXIMA_DIAS - 1),
)


@given(st.lists(rango_aleatorio, max_size=8))
def test_las_advertencias_describen_la_cobertura_real(lista):
    """Propiedad: una edad sin advertencia de hueco está cubierta; un punto en un solape tiene 2+ rangos."""
    advertencias = rangos.analizar(lista)
    for sexo in ("M", "F"):
        huecos = [a for a in advertencias if a.sexo == sexo and a.tipo == "HUECO"]
        solapes = [a for a in advertencias if a.sexo == sexo and a.tipo == "SOLAPE"]
        for edad in (0, 1, 30, 365, 18 * ANIO, 70 * ANIO, EDAD_MAXIMA_DIAS - 1):
            cubren = len(rangos.aplicable(lista, sexo, edad))
            en_hueco = any(a.desde_dias <= edad < a.hasta_dias for a in huecos)
            assert (cubren == 0) == en_hueco, (sexo, edad)
            if any(a.desde_dias <= edad < a.hasta_dias for a in solapes):
                assert cubren >= 2
        for a in [*huecos, *solapes]:
            assert 0 <= a.desde_dias < a.hasta_dias <= EDAD_MAXIMA_DIAS


def test_edad_legible():
    assert rangos.edad_legible(18 * ANIO) == (18, "anios")
    assert rangos.edad_legible(60) == (2, "meses")
    assert rangos.edad_legible(7) == (7, "dias")
    assert rangos.edad_legible(0) == (0, "dias")


# --- Inyección CSV ---


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        ('=HYPERLINK("http://x")', '\'=HYPERLINK("http://x")'),
        ("+1+1", "'+1+1"),
        ("-2+3", "'-2+3"),
        ("@SUM(A1)", "'@SUM(A1)"),
        ("\tTAB", "'\tTAB"),
        ("\rCR", "'\rCR"),
        ("Glucosa", "Glucosa"),
        (None, ""),
        (125, "125"),
    ],
)
def test_celda_segura(valor, esperado):
    assert celda_segura(valor) == esperado


# --- Interfaz ---


@pytest.fixture
def admin(buzon):
    return autenticar(cliente(), "admin@lab-a.test", buzon)


def _crear_maestros(c, sufijo: str) -> None:
    for tipo, datos in (
        ("secciones", {"codigo": f"S{sufijo}", "nombre": f"Sección {sufijo}", "extra": "1"}),
        ("unidades", {"codigo": f"mg{sufijo}", "nombre": "mg/dL", "extra": "mg/dL"}),
        ("tipos_muestra", {"codigo": f"M{sufijo}"[:10], "nombre": "Suero"}),
        ("tipos_tubo", {"codigo": f"T{sufijo}", "nombre": "Tapa roja", "aditivo": "Sin aditivo", "capacidad": "5"}),
        ("tecnicas", {"nombre": f"Hexoquinasa {sufijo}"}),
        ("tarifas", {"codigo": f"P{sufijo}"[:15], "nombre": "Particular"}),
        ("tipos_codigo", {"codigo": f"C{sufijo}"[:10], "nombre": "SOAT"}),
    ):
        respuesta = c.post(f"/catalogo/maestros/{tipo}", data={**datos, "csrf": csrf(c, "/catalogo/maestros")})
        assert respuesta.status_code == 303, (tipo, respuesta.text[:300])


def _crear_examen(c, sufijo: str) -> str:
    datos = {
        "codigo": f"GLU{sufijo}",
        "nombre": f"Glucosa {sufijo}",
        "seccion": f"S{sufijo}",
        "tecnica": f"Hexoquinasa {sufijo}",
        "codigo_nacional": "903841",
        "loinc": "2345-7",
        "requiere_autorizacion": "si",
        "dias_procesamiento": "LU a VI",
    }
    respuesta = c.post("/catalogo/examenes/nuevo", data={**datos, "csrf": csrf(c, "/catalogo/examenes/nuevo")})
    assert respuesta.status_code == 303, respuesta.text[:500]
    return respuesta.headers["location"]


def test_flujo_de_un_examen_completo(admin):
    s = uuid.uuid4().hex[:5]
    c = admin
    _crear_maestros(c, s)
    examen = _crear_examen(c, s)
    pagina = c.get(examen).text
    assert f"Glucosa {s}" in pagina and "CUPS" in pagina  # el nombre del código sale del país

    # Parámetro numérico, requisito de muestra y precio.
    respuesta = c.post(
        f"{examen}/parametros",
        data={
            "nombre": "Glucosa en ayunas",
            "tipo": "NUMERICO",
            "unidad": f"mg{s}",
            "orden": "1",
            "csrf": csrf(c, examen),
        },
    )
    parametro = respuesta.headers["location"]
    assert (
        c.post(
            f"{examen}/requisitos",
            data={"tipo_muestra": f"M{s}"[:10], "tipo_tubo": f"T{s}", "volumen_ml": "1,5", "csrf": csrf(c, examen)},
        ).status_code
        == 303
    )
    assert (
        c.post(
            f"{examen}/precios", data={"tarifa": f"P{s}"[:15], "valor": "12000.50", "csrf": csrf(c, examen)}
        ).status_code
        == 303
    )
    pagina = c.get(examen).text
    assert "Glucosa en ayunas" in pagina and "1.50" in pagina and "12000.50" in pagina

    # Rangos: adulto ambos sexos con críticos; luego un solape y la advertencia.
    datos_rango = {
        "sexo": "T",
        "edad_min": "18",
        "unidad_min": "anios",
        "edad_max": "150",
        "unidad_max": "anios",
        "minimo": "70",
        "maximo": "100",
        "critico_min": "40",
        "critico_max": "400",
        "texto_impreso": "70 - 100 mg/dL",
    }
    assert c.post(f"{parametro}/rangos", data={**datos_rango, "csrf": csrf(c, parametro)}).status_code == 303
    pagina = c.get(parametro).text
    assert "Sin rango para sexo Femenino entre 0 días y 18 años" in pagina  # hueco de niños
    solapado = {**datos_rango, "sexo": "M", "edad_min": "60"}
    assert c.post(f"{parametro}/rangos", data={**solapado, "csrf": csrf(c, parametro)}).status_code == 303
    assert "Rangos solapados para sexo Masculino" in c.get(parametro).text

    # Validaciones del rango.
    for malo in (
        {"minimo": "100", "maximo": "70"},
        {"critico_min": "80"},
        {"critico_max": "90"},
        {"edad_min": "200"},
        {"edad_min": "10", "edad_max": "5"},
        {"minimo": "uno"},
        {"sexo": "X"},
        {"unidad_min": "siglos"},
        {"minimo": "", "maximo": "", "critico_min": "", "critico_max": "", "texto_impreso": ""},
        {"minimo": "1e20"},
    ):
        respuesta = c.post(f"{parametro}/rangos", data={**datos_rango, **malo, "csrf": csrf(c, parametro)})
        assert respuesta.status_code == 400, malo

    # Quitar un rango y marcar revisado.
    rango = re.search(r"/catalogo/rangos/([0-9a-f-]{36})/eliminar", c.get(parametro).text).group(1)
    assert c.post(f"/catalogo/rangos/{rango}/eliminar", data={"csrf": csrf(c, parametro)}).status_code == 303
    assert c.post(f"/catalogo/rangos/{rango}/eliminar", data={"csrf": csrf(c, parametro)}).status_code == 404

    # Editar el examen y desactivarlo.
    editar = {
        "codigo": f"GLU{s}",
        "nombre": f"Glucosa basal {s}",
        "seccion": f"S{s}",
        "tecnica": "",
        "codigo_nacional": "",
        "loinc": "",
        "dias_procesamiento": "",
        "csrf": csrf(c, examen),
    }
    assert c.post(examen, data=editar).status_code == 303
    assert c.post(f"{examen}/estado", data={"csrf": csrf(c, examen)}).status_code == 303
    assert f"Glucosa basal {s}" in c.get("/catalogo").text
    assert "Inactivo" in c.get(examen).text


def test_parametro_de_lista_y_valores(admin):
    s = uuid.uuid4().hex[:5]
    _crear_maestros(admin, s)
    examen = _crear_examen(admin, s)
    parametro = admin.post(
        f"{examen}/parametros", data={"nombre": "Color", "tipo": "LISTA", "orden": "1", "csrf": csrf(admin, examen)}
    ).headers["location"]
    for valor in ("Amarillo", "Ámbar"):
        assert (
            admin.post(
                f"{parametro}/valores", data={"valor": valor, "es_normal": "si", "csrf": csrf(admin, parametro)}
            ).status_code
            == 303
        )
    assert (
        admin.post(f"{parametro}/valores", data={"valor": "Amarillo", "csrf": csrf(admin, parametro)}).status_code
        == 400
    )
    assert admin.post(f"{parametro}/valores", data={"valor": " ", "csrf": csrf(admin, parametro)}).status_code == 400
    assert (
        admin.post(f"{parametro}/valores/eliminar", data={"valor": "Ámbar", "csrf": csrf(admin, parametro)}).status_code
        == 303
    )
    assert (
        admin.post(f"{parametro}/valores/eliminar", data={"valor": "Ámbar", "csrf": csrf(admin, parametro)}).status_code
        == 404
    )
    pagina = admin.get(parametro).text
    assert "Amarillo" in pagina and "Ámbar" not in pagina
    # Rango de texto con valor esperado.
    datos = {
        "sexo": "T",
        "edad_min": "0",
        "unidad_min": "dias",
        "edad_max": "150",
        "unidad_max": "anios",
        "valor_esperado": "Amarillo",
        "csrf": csrf(admin, parametro),
    }
    assert admin.post(f"{parametro}/rangos", data=datos).status_code == 303
    # Editar el parámetro: tipo inválido, LOINC inválido y uno válido.
    base = {"nombre": "Color", "tipo": "LISTA", "orden": "1", "decimales": "0", "loinc": "", "activo": "si"}
    assert admin.post(parametro, data={**base, "tipo": "OTRO", "csrf": csrf(admin, parametro)}).status_code == 400
    assert admin.post(parametro, data={**base, "loinc": "abc", "csrf": csrf(admin, parametro)}).status_code == 400
    assert admin.post(parametro, data={**base, "loinc": "5778-6", "csrf": csrf(admin, parametro)}).status_code == 303


def test_validaciones_de_examen_y_maestros(admin):
    s = uuid.uuid4().hex[:5]
    _crear_maestros(admin, s)
    _crear_examen(admin, s)
    repetido = {
        "codigo": f"GLU{s}",
        "nombre": f"Otro {s}",
        "seccion": f"S{s}",
        "csrf": csrf(admin, "/catalogo/examenes/nuevo"),
    }
    assert admin.post("/catalogo/examenes/nuevo", data=repetido).status_code == 400
    for malo in ({"codigo": ""}, {"nombre": "x"}, {"loinc": "12"}, {"seccion": "NO_EXISTE"}):
        datos = {
            "codigo": f"N{s}",
            "nombre": f"Nuevo {s}",
            "seccion": f"S{s}",
            **malo,
            "csrf": csrf(admin, "/catalogo/examenes/nuevo"),
        }
        assert admin.post("/catalogo/examenes/nuevo", data=datos).status_code == 400, malo
    for tipo, datos in (
        ("secciones", {"codigo": f"S{s}", "nombre": "Repetida"}),
        ("secciones", {"codigo": "X", "nombre": "X", "extra": "uno"}),
        ("tipos_tubo", {"codigo": "TT", "nombre": "Tubo", "capacidad": "0"}),
        ("tipos_muestra", {"codigo": "MUY_LARGO_PARA_10", "nombre": "x"}),
        ("unidades", {"codigo": "", "nombre": ""}),
    ):
        respuesta = admin.post(f"/catalogo/maestros/{tipo}", data={**datos, "csrf": csrf(admin, "/catalogo/maestros")})
        assert respuesta.status_code == 400, (tipo, datos)
    assert (
        admin.post(
            "/catalogo/maestros/inventado",
            data={"codigo": "x", "nombre": "x", "csrf": csrf(admin, "/catalogo/maestros")},
        ).status_code
        == 404
    )


def test_exportacion_csv_neutraliza_formulas_y_queda_auditada(admin):
    s = uuid.uuid4().hex[:5]
    _crear_maestros(admin, s)
    datos = {
        "codigo": f"=X{s}",
        "nombre": f'=HYPERLINK("http://atacante","{s}")',
        "seccion": f"S{s}",
        "codigo_nacional": "+57",
        "csrf": csrf(admin, "/catalogo/examenes/nuevo"),
    }
    assert admin.post("/catalogo/examenes/nuevo", data=datos).status_code == 303
    respuesta = admin.get("/catalogo/exportar.csv")
    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"].startswith("text/csv")
    assert "attachment" in respuesta.headers["content-disposition"]
    assert respuesta.headers["cache-control"] == "no-store"
    filas = list(csv.reader(io.StringIO(respuesta.text.lstrip("﻿"))))
    fila = next(f for f in filas if s in f[1])
    assert fila[0] == f"'=X{s}" and fila[1].startswith("'=HYPERLINK") and fila[3] == "'+57"
    for celda in (c for f in filas for c in f):
        assert not celda.startswith(("=", "+", "-", "@")), celda

    async def exportaciones(sesion):
        return await sesion.scalar(
            text("SELECT count(*) FROM lab.auditoria WHERE operacion = 'EXPORT' AND tabla = 'examenes'")
        )

    assert correr(ejecutar_en_tenant("app", "lab_a", exportaciones)) >= 1


# --- Autorización y aislamiento ---


@pytest.mark.parametrize(
    ("email", "ruta", "esperado"),
    [
        ("recepcion@lab-a.test", "/catalogo", 403),
        ("auditor@lab-a.test", "/catalogo", 403),
        ("validador@lab-a.test", "/catalogo", 403),
        ("paciente@lab-a.test", "/catalogo", 403),
        ("admin@lab-a.test", "/catalogo", 200),
        ("admin@lab-a.test", "/catalogo/maestros", 200),
        ("admin@lab-a.test", "/catalogo/revision", 200),
    ],
)
def test_permisos_del_catalogo(buzon, email, ruta, esperado):
    assert autenticar(cliente(), email, buzon).get(ruta).status_code == esperado


def test_examen_de_otro_laboratorio_no_existe(admin, buzon):
    s = uuid.uuid4().hex[:5]
    _crear_maestros(admin, s)
    examen = _crear_examen(admin, s)
    parametro = admin.post(
        f"{examen}/parametros", data={"nombre": "P", "tipo": "TEXTO", "orden": "1", "csrf": csrf(admin, examen)}
    ).headers["location"]
    otro = autenticar(cliente("lab-b"), "admin@lab-b.test", buzon, laboratorio="lab_b")
    token = csrf(otro, "/catalogo")
    assert otro.get(examen).status_code == 404
    assert otro.get(parametro).status_code == 404
    for ruta, datos in (
        (f"{examen}/estado", {}),
        (f"{examen}/parametros", {"nombre": "Intruso", "tipo": "TEXTO", "orden": "1"}),
        (f"{parametro}/rangos", {"sexo": "T", "edad_min": "0", "edad_max": "150", "texto_impreso": "x"}),
        (f"{parametro}/valores", {"valor": "Intruso"}),
        (f"{examen}/precios", {"tarifa": "X", "valor": "1"}),
        (f"{examen}/requisitos", {"tipo_muestra": "X"}),
    ):
        assert otro.post(ruta, data={**datos, "csrf": token}).status_code == 404, ruta
    assert f"Glucosa {s}" not in otro.get("/catalogo").text
    assert f"Glucosa {s}" not in otro.get("/catalogo/exportar.csv").text


@pytest.mark.anyio
async def test_rls_impide_escribir_el_catalogo_de_otro_laboratorio(engine_app):
    from app.core.db import sesion_tenant

    with pytest.raises(DBAPIError, match="row-level security"):
        async with sesion_tenant("lab_a") as sesion:
            await sesion.execute(
                text("INSERT INTO lab.secciones (tenant_id, codigo, nombre) VALUES ('lab_b', 'X', 'X')")
            )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "sentencia",
    [
        "INSERT INTO lab.rangos_referencia (parametro_id, minimo, maximo) SELECT id, 10, 5 FROM lab.parametros LIMIT 1",
        "INSERT INTO lab.rangos_referencia (parametro_id, edad_min_dias, edad_max_dias)"
        " SELECT id, 10, 10 FROM lab.parametros LIMIT 1",
        "INSERT INTO lab.rangos_referencia (parametro_id, minimo, critico_min)"
        " SELECT id, 10, 20 FROM lab.parametros LIMIT 1",
        "INSERT INTO lab.tipos_tubo (codigo, nombre, capacidad_ml) VALUES ('Z', 'Z', -1)",
        "INSERT INTO lab.examenes (codigo, nombre, seccion_id, loinc)"
        " SELECT 'Z9', 'Z9', id, 'abc' FROM lab.secciones LIMIT 1",
    ],
)
async def test_la_base_rechaza_datos_incoherentes(engine_app, sentencia):
    from app.core.db import sesion_tenant

    async with sesion_tenant("lab_a") as sesion:
        hay = await sesion.scalar(text("SELECT count(*) FROM lab.parametros"))
    if not hay:  # sin parámetros en esta corrida: se crea uno mínimo
        async with sesion_tenant("lab_a") as sesion:
            seccion = await sesion.scalar(
                text(
                    "INSERT INTO lab.secciones (codigo, nombre) VALUES ('RLS', 'RLS')"
                    " ON CONFLICT DO NOTHING RETURNING id"
                )
            )
            seccion = seccion or await sesion.scalar(text("SELECT id FROM lab.secciones WHERE codigo = 'RLS'"))
            examen = await sesion.scalar(
                text(
                    "INSERT INTO lab.examenes (codigo, nombre, seccion_id) VALUES ('RLS1', 'RLS uno', :s) RETURNING id"
                ),
                {"s": seccion},
            )
            await sesion.execute(
                text("INSERT INTO lab.parametros (examen_id, nombre, tipo) VALUES (:e, 'P', 'NUMERICO')"), {"e": examen}
            )
    with pytest.raises(DBAPIError, match="check"):
        async with sesion_tenant("lab_a") as sesion:
            await sesion.execute(text(sentencia))


@pytest.mark.anyio
async def test_examenes_y_parametros_no_se_borran(engine_app):
    from app.core.db import sesion_tenant

    for tabla in ("examenes", "parametros", "secciones"):
        with pytest.raises(DBAPIError, match="permission denied"):
            async with sesion_tenant("lab_a") as sesion:
                await sesion.execute(text(f"DELETE FROM lab.{tabla}"))  # noqa: S608 — nombres fijos de la prueba


def test_busqueda_y_filtros_no_rompen(admin):
    for consulta in ("?q=%25", "?q=_", "?q=' OR 1=1 --", "?seccion=no-uuid", "?q=" + "x" * 500, "?seccion=" + "0" * 36):
        assert admin.get("/catalogo" + consulta).status_code == 200, consulta
    # Hallazgo de ZAP en la etapa 6: un byte NUL llegaba a PostgreSQL y respondía 500.
    for consulta in ("?q=%00", "?q=%22%3E%00%3Cscript%3E", "?q=%1b"):
        assert admin.get("/catalogo" + consulta).status_code == 400, consulta


def test_mas_validaciones_de_la_interfaz(admin):
    s = uuid.uuid4().hex[:5]
    _crear_maestros(admin, s)
    examen = _crear_examen(admin, s)
    token = csrf(admin, examen)
    largo = {
        "codigo": f"GLU{s}",
        "nombre": f"Glucosa {s}",
        "seccion": f"S{s}",
        "codigo_nacional": "9" * 25,
        "csrf": token,
    }
    assert admin.post(examen, data=largo).status_code == 400
    for datos in (
        {"nombre": "", "tipo": "NUMERICO"},
        {"nombre": "P", "tipo": "OTRO"},
        {"nombre": "P", "tipo": "TEXTO", "orden": "x"},
    ):
        assert admin.post(f"{examen}/parametros", data={**datos, "csrf": token}).status_code == 400, datos
    for volumen in ("0", "abc", "5000"):
        respuesta = admin.post(
            f"{examen}/requisitos", data={"tipo_muestra": f"M{s}"[:10], "volumen_ml": volumen, "csrf": token}
        )
        assert respuesta.status_code == 400, volumen
    requisito = {"tipo_muestra": f"M{s}"[:10], "volumen_ml": "2", "csrf": token}
    assert admin.post(f"{examen}/requisitos", data=requisito).status_code == 303
    assert admin.post(f"{examen}/requisitos", data=requisito).status_code == 400  # repetido
    quitar = re.search(r"/catalogo/requisitos/([0-9a-f-]{36})/eliminar", admin.get(examen).text).group(1)
    assert admin.post(f"/catalogo/requisitos/{quitar}/eliminar", data={"csrf": token}).status_code == 303
    assert admin.post(f"/catalogo/requisitos/{quitar}/eliminar", data={"csrf": token}).status_code == 404
    tarifa = f"P{s}"[:15]
    for valor in ("-1", "1.005", "x"):
        assert (
            admin.post(f"{examen}/precios", data={"tarifa": tarifa, "valor": valor, "csrf": token}).status_code == 400
        )
    assert admin.post(f"{examen}/precios", data={"tarifa": tarifa, "valor": "5000", "csrf": token}).status_code == 303
    assert admin.post(f"{examen}/precios", data={"tarifa": tarifa, "valor": "", "csrf": token}).status_code == 303
    assert admin.post(f"{examen}/precios", data={"tarifa": "NO", "valor": "1", "csrf": token}).status_code == 404
    # Marcar revisado un rango importado.
    parametro = admin.post(
        f"{examen}/parametros", data={"nombre": "Q", "tipo": "NUMERICO", "orden": "2", "csrf": token}
    ).headers["location"]

    async def rango_importado(sesion):
        await sesion.execute(
            text(
                "INSERT INTO lab.rangos_referencia (parametro_id, minimo, maximo, requiere_revision)"
                " SELECT id, 1, 2, true FROM lab.parametros WHERE uuid = :p"
            ),
            {"p": parametro.rsplit("/", 1)[1]},
        )

    correr(ejecutar_en_tenant("app", "lab_a", rango_importado))
    rango = re.search(r"/catalogo/rangos/([0-9a-f-]{36})/revisado", admin.get(parametro).text).group(1)
    assert admin.post(f"/catalogo/rangos/{rango}/revisado", data={"csrf": token}).status_code == 303
    assert "/revisado" not in admin.get(parametro).text
    otro = str(uuid.uuid4())
    assert admin.post(f"/catalogo/rangos/{otro}/revisado", data={"csrf": token}).status_code == 404
    assert admin.get(f"/catalogo/examenes/{otro}").status_code == 404
    assert admin.post(f"/catalogo/examenes/{otro}/estado", data={"csrf": token}).status_code == 404
    assert (
        admin.post(f"/catalogo/parametros/{otro}", data={"nombre": "x", "tipo": "TEXTO", "csrf": token}).status_code
        == 404
    )


def test_maestros_guardan_inyeccion_sql_como_texto_literal(admin):
    """Hallazgo de ZAP en la etapa 6 (regla 40018, falso positivo): el texto se guarda tal cual, sin interpretarse."""
    s = uuid.uuid4().hex[:5]
    cargas = [f"{s} OR 1=1 --", f"{s}' AND '1'='1' --", f"{s}'; DROP TABLE lab.tecnicas; --"]
    token = csrf(admin, "/catalogo/maestros")
    for carga in cargas:
        datos = {"nombre": carga, "csrf": token}
        assert admin.post("/catalogo/maestros/tecnicas", data=datos).status_code == 303

    async def leer(sesion):
        filas = await sesion.execute(text("SELECT nombre FROM lab.tecnicas WHERE nombre LIKE :p"), {"p": f"{s}%"})
        return sorted(filas.scalars())

    assert correr(ejecutar_en_tenant("app", "lab_a", leer)) == sorted(cargas)

    # Edición de un examen: el código con la carga se guarda tal cual y no toca los demás exámenes.
    _crear_maestros(admin, s)
    examen = _crear_examen(admin, s)
    codigo = f"G{s} OR 1=1"
    datos = {"codigo": codigo, "nombre": f"{s}' OR '1'='1", "seccion": f"S{s}", "csrf": token}
    assert admin.post(examen, data=datos).status_code == 303

    async def examenes(sesion):
        return (
            await sesion.execute(text("SELECT codigo, nombre FROM lab.examenes WHERE codigo LIKE :p"), {"p": f"G{s}%"})
        ).all()

    assert correr(ejecutar_en_tenant("app", "lab_a", examenes)) == [(codigo, f"{s}' OR '1'='1")]
