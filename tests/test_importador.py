"""Importador del catálogo de Lablinea (etapa 6; spec funcional/0009, sección 2).

Pruebas específicas del plan:
- Archivos malformados, enormes o con codificaciones raras: rechazados sin caerse ni cargar datos a medias.
- Archivos que no corresponden (ejecutables renombrados) → rechazados.
"""

import asyncio
import contextlib
import io
import re
import secrets
import zipfile
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import text

from app.catalogo import importador
from app.catalogo.importador import ArchivoRechazado, Existentes, analizar, leer_paquete
from tests.ayudas import autenticar, cliente, csrf
from tests.conftest import correr, ejecutar_en_tenant

# Exportación sintética de Lablinea (nombres de tabla y columnas como en el DDL original, fuente 02).
CATALOGO = {
    "seccion.csv": "codigo;descripcion\nHEM;Hematología\nQUI;Química sanguínea\nURO;Uroanálisis\n",
    "unidad.csv": "codigo;descripcion\nmg/dL;mg/dL\ng/dL;g/dL\n",
    "analisis.csv": (
        "consecutivo;codigo examen;especimen;descripcion;seccion;CodigoSGSS;AutorizAdic;DiasMontaje\n"
        "1;HEMO;Sangre;Hemograma;HEM;902210;False;LU a VI\n"
        "2;GLU;Suero;Glucosa;QUI;903841;0;LU a SA\n"
        "3;;Orina;Parcial de orina;URO;907106;Sí;\n"
    ),
    "detalle analisis.csv": (
        "consecutivo;analisis;descripcion;unidad;orden de presentacion;normal de referencia;Es titulo ?;grafica;"
        "RangoMinimo;RangoMaximo\n"
        "10;1;Serie roja;;1;;True;False;;\n"
        "11;1;Hemoglobina;g/dL;2;12 - 16 g/dL;False;True;12;16\n"
        "20;2;Glucosa;mg/dL;1;70 - 100 mg/dL;False;True;;\n"
        "30;3;Color;;1;Amarillo;False;False;;\n"
        "31;3;Proteínas;mg/dL;2;< 15;0;0;;\n"
    ),
    "lista de valores.csv": "consecutivo;pregunta por analisis;valor\n1;30;Amarillo\n2;30;Ámbar\n3;30;Rojizo\n",
    "tipo muestra.csv": "tipo;descripcion\nSANG;Sangre total\nSUER;Suero\nORIN;Orina\n",
    "muestras x analisis.csv": (
        "consecutivo;analisis;descripcion;tipo de muestra\n1;1;Sangre EDTA;SANG\n2;2;Suero;SUER\n3;3;Orina;ORIN\n"
    ),
    "tipo tarifa.csv": "codigo;descripcion\nPART;Particular\nEPS1;Convenio EPS\n",
    "costo analisis.csv": "tipo tarifa;analisis;costo\nPART;1;25000,0000\nPART;2;12000\nEPS1;1;18000.5\n",
    "Tipo Codigo Alterno.csv": "codigo;descripcion\nSOAT;SOAT\n",
    "Codigo Analisis x Empresa.csv": "tipo codigo alterno;analisis;codigo alterno\nSOAT;1;H-100\n",
}


def zip_de(archivos: dict[str, str | bytes], codificacion: str = "utf-8") -> bytes:
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as z:
        for nombre, contenido in archivos.items():
            z.writestr(nombre, contenido if isinstance(contenido, bytes) else contenido.encode(codificacion))
    return salida.getvalue()


# --- Lectura segura del archivo ---


def test_lee_la_exportacion_de_lablinea():
    tablas = leer_paquete(zip_de(CATALOGO))
    assert set(tablas) == set(importador.TABLAS)
    assert tablas["analisis"][0]["codigoexamen"] == "HEMO"
    assert tablas["detalleanalisis"][1]["normaldereferencia"] == "12 - 16 g/dL"


@pytest.mark.parametrize("codificacion", ["utf-8", "utf-8-sig", "cp1252"])
def test_codificaciones_de_access(codificacion):
    tablas = leer_paquete(zip_de(CATALOGO, codificacion))
    assert tablas["seccion"][0]["descripcion"] == "Hematología"


@pytest.mark.parametrize("separador", [",", ";", "\t"])
def test_separadores(separador):
    archivos = {k: v.replace(";", separador) for k, v in CATALOGO.items()}
    archivos["costo analisis.csv"] = (
        f"tipo tarifa{separador}analisis{separador}costo\nPART{separador}1{separador}25000\n"
    )
    assert leer_paquete(zip_de(archivos))["seccion"][1]["codigo"] == "QUI"


def _rechazo(datos: bytes) -> str:
    with pytest.raises(ArchivoRechazado) as error:
        leer_paquete(datos)
    return error.value.clave


EJECUTABLES = {
    "pe": b"MZ\x90\x00\x03" + b"\x00" * 200,
    "elf": b"\x7fELF\x02\x01\x01" + b"\x00" * 200,
    "macho": b"\xcf\xfa\xed\xfe" + b"\x00" * 200,
    "pdf": b"%PDF-1.7\n" + b"x" * 200,
    "access": b"\x00\x01\x00\x00Standard Jet DB" + b"\x00" * 200,
    "texto": b"codigo;descripcion\nHEM;Hematologia\n",
}


@pytest.mark.parametrize("tipo", sorted(EJECUTABLES))
def test_archivos_que_no_son_zip_se_rechazan(tipo):
    assert _rechazo(EJECUTABLES[tipo]) == "no_zip"


def test_zip_truncado_o_corrupto():
    datos = zip_de(CATALOGO)
    assert _rechazo(datos[: len(datos) // 2]) == "no_zip"
    assert _rechazo(b"PK\x03\x04" + b"\xff" * 100) == "no_zip"


def test_vacio_y_enorme():
    assert _rechazo(b"") == "vacio"
    assert _rechazo(b"PK\x03\x04" + b"0" * (importador.MAX_ZIP + 1)) == "grande"


def test_bomba_zip():
    assert _rechazo(zip_de({**CATALOGO, "seccion.csv": "codigo;descripcion\n" + "0" * 5_000_000})) == "bomba"


def test_tabla_enorme_descomprimida():
    grande = "codigo;descripcion\n" + "".join(f"S{i};{'x' * 50}{i}\n" for i in range(400_000))
    assert _rechazo(zip_de({**CATALOGO, "seccion.csv": grande})) == "grande"


def test_demasiadas_filas(monkeypatch):
    monkeypatch.setattr(importador, "MAX_FILAS", 2)
    assert _rechazo(zip_de(CATALOGO)) == "demasiadas_filas"


@pytest.mark.parametrize(
    ("nombre", "clave"),
    [
        ("../seccion.csv", "ruta"),
        ("carpeta/seccion.csv", "ruta"),
        (".oculto.csv", "ruta"),
        ("seccion.exe", "no_csv"),
        ("paciente.csv", "tabla_desconocida"),
        ("orden.csv", "tabla_desconocida"),
        ("diagnostico.csv", "tabla_desconocida"),
    ],
)
def test_entradas_no_permitidas(nombre, clave):
    assert _rechazo(zip_de({**CATALOGO, nombre: "a;b\n1;2\n"})) == clave


def test_zip_cifrado():
    """Se marca el bit de cifrado en los encabezados (zipfile no escribe ZIP cifrados)."""
    datos = bytearray(zip_de({"seccion.csv": "codigo;descripcion\n"}))
    for firma, desplazamiento in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        posicion = datos.find(firma) + desplazamiento
        datos[posicion] |= 0x1
    assert _rechazo(bytes(datos)) == "cifrado"


def test_demasiadas_entradas():
    archivos = {f"seccion{'_' * i}.csv": "codigo;descripcion\n" for i in range(importador.MAX_ENTRADAS + 1)}
    assert _rechazo(zip_de(archivos)) == "demasiadas_entradas"


def test_tabla_repetida_con_otro_nombre():
    assert _rechazo(zip_de({**CATALOGO, "SECCION.csv": CATALOGO["seccion.csv"], "seccion.csv": "x"})) in (
        "tabla_repetida",
    )


@pytest.mark.parametrize(
    ("contenido", "clave"),
    [
        (b"codigo;descripcion\nHEM;Hema\x00tologia\n", "codificacion"),  # nulo
        ("codigo;descripcion\nHEM;Hema".encode("utf-16"), "codificacion"),  # UTF-16
        (b"codigo;descripcion\nHEM;\x81\x8d\x8f\x90\x9d\n", "codificacion"),  # bytes sin definir en cp1252
        (b"codigo;descripcion\nHEM;Hema\x07tologia\n", "caracteres"),  # caracter de control
        (b'codigo;descripcion\nHEM;"sin cerrar\n', "csv_malformado"),
        (b"codigo;descripcion\nHEM;Hema;extra\n", "csv_malformado"),
        (b"codigo;descripcion\nHEM;" + secrets.token_hex(2500).encode() + b"\n", "campo_largo"),
    ],
)
def test_contenido_malformado(contenido, clave):
    assert _rechazo(zip_de({**CATALOGO, "seccion.csv": contenido})) == clave


@settings(max_examples=200, deadline=None)
@given(datos=st.binary(max_size=2000))
def test_bytes_arbitrarios_nunca_rompen_el_lector(datos):
    with contextlib.suppress(ArchivoRechazado):
        leer_paquete(datos)


@settings(max_examples=150, deadline=None)
@given(contenido=st.text(max_size=500), nombre=st.sampled_from(["seccion.csv", "analisis.csv", "detalle analisis.csv"]))
def test_csv_arbitrario_nunca_rompe_lector_ni_analisis(contenido, nombre):
    try:
        tablas = leer_paquete(zip_de({**CATALOGO, nombre: contenido}))
    except ArchivoRechazado:
        return
    plan = analizar(tablas, Existentes(), "COP")  # nunca lanza: errores y advertencias van al plan
    assert isinstance(plan.errores, list)


# --- Análisis ---


def _plan(archivos=None, existentes=None):
    return analizar(leer_paquete(zip_de(archivos or CATALOGO)), existentes or Existentes(), "COP")


def test_analisis_de_la_exportacion_completa():
    plan = _plan()
    assert plan.errores == []
    assert plan.conteos() == {
        "secciones": 3,
        "unidades": 2,
        "tipos_muestra": 3,
        "tarifas": 2,
        "tipos_codigo": 1,
        "examenes": 3,
        "parametros": 5,
        "valores": 3,
        "rangos": 4,
        "requisitos": 3,
        "precios": 3,
        "codigos": 1,
    }
    tipos = {p["nombre"]: p["tipo"] for p in plan.parametros}
    assert tipos == {
        "Serie roja": "TITULO",
        "Hemoglobina": "NUMERICO",
        "Glucosa": "NUMERICO",
        "Color": "LISTA",
        "Proteínas": "NUMERICO",
    }
    rangos = {r["parametro"]: r for r in plan.rangos}
    assert (rangos[11]["minimo"], rangos[11]["maximo"]) == (Decimal("12"), Decimal("16"))
    assert (rangos[20]["minimo"], rangos[20]["maximo"]) == (Decimal("70"), Decimal("100"))  # del texto
    assert (rangos[31]["minimo"], rangos[31]["maximo"]) == (None, Decimal("15"))  # "< 15"
    assert rangos[30]["valor_esperado"] == "Amarillo"
    assert {a["clave"] for a in plan.advertencias} >= {"rangos_revision", "requisitos_sin_tubo"}
    examen_sin_codigo = next(e for e in plan.examenes if e["lablinea"] == 3)
    assert examen_sin_codigo["codigo"] == "3" and examen_sin_codigo["requiere_autorizacion"] is True
    assert {p["valor"] for p in plan.precios} == {Decimal("25000.00"), Decimal("12000.00"), Decimal("18000.50")}


@pytest.mark.parametrize(
    ("cambios", "clave"),
    [
        ({"seccion.csv": None}, "falta_tabla"),
        ({"analisis.csv": "consecutivo;descripcion\n1;Hemograma\n"}, "falta_columna"),
        ({"analisis.csv": "consecutivo;descripcion;seccion\n1;Hemograma;XXX\n"}, "seccion_inexistente"),
        ({"analisis.csv": "consecutivo;descripcion;seccion\nuno;Hemograma;HEM\n"}, "numero_invalido"),
        ({"analisis.csv": "consecutivo;descripcion;seccion\n1;Hemograma;HEM\n2;hemograma;HEM\n"}, "repetido"),
        ({"analisis.csv": "consecutivo;descripcion;seccion\n1;" + "x" * 200 + ";HEM\n"}, "campo_largo"),
        ({"detalle analisis.csv": "consecutivo;analisis;descripcion\n1;99;Hemoglobina\n"}, "examen_inexistente"),
        ({"lista de valores.csv": "consecutivo;pregunta por analisis;valor\n1;999;Rojo\n"}, "parametro_inexistente"),
        (
            {"muestras x analisis.csv": "consecutivo;analisis;descripcion;tipo de muestra\n1;1;x;LCR\n"},
            "tipo_muestra_inexistente",
        ),
        ({"costo analisis.csv": "tipo tarifa;analisis;costo\nPART;1;mil\n"}, "numero_invalido"),
        ({"costo analisis.csv": "tipo tarifa;analisis;costo\nVIP;1;1000\n"}, "tarifa_inexistente"),
        (
            {"Codigo Analisis x Empresa.csv": "tipo codigo alterno;analisis;codigo alterno\nXX;1;A\n"},
            "tipo_codigo_inexistente",
        ),
    ],
)
def test_errores_del_analisis(cambios, clave):
    archivos = {**CATALOGO}
    for nombre, contenido in cambios.items():
        if contenido is None:
            archivos.pop(nombre)
        else:
            archivos[nombre] = contenido
    plan = _plan(archivos)
    assert clave in {e["clave"] for e in plan.errores}


def test_existentes_chocan_o_se_reutilizan():
    existentes = Existentes(secciones={"HEM"}, nombres_examen={"glucosa"}, lablinea_examen={3})
    plan = _plan(existentes=existentes)
    # El examen existente choca; sus parámetros y valores quedan sin examen (también son errores).
    assert {e["clave"] for e in plan.errores} >= {"examen_existe"}
    assert sum(e["clave"] == "examen_existe" for e in plan.errores) == 2
    assert "HEM" not in {s["codigo"] for s in plan.secciones}  # la sección existente se reutiliza


def test_advertencias_de_datos_dudosos():
    archivos = {
        **CATALOGO,
        "detalle analisis.csv": (
            "consecutivo;analisis;descripcion;unidad;orden de presentacion;normal de referencia;"
            "RangoMinimo;RangoMaximo\n"
            "11;1;Hemoglobina;g/dL;dos;;16;12\n"
            "20;2;Glucosa;mg/dL;1;;abc;100\n"
        ),
        "costo analisis.csv": "tipo tarifa;analisis;costo\nPART;1;100,555\n",
        "lista de valores.csv": "consecutivo;pregunta por analisis;valor\n",
    }
    plan = _plan(archivos)
    assert plan.errores == []
    claves = {a["clave"] for a in plan.advertencias}
    assert {"rango_invertido", "numero_ignorado", "precio_redondeado", "examen_sin_parametros"} <= claves


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("70 - 100", (Decimal("70"), Decimal("100"))),
        ("3,5 a 5,1 mmol/L", (Decimal("3.5"), Decimal("5.1"))),
        ("< 200", (None, Decimal("200"))),
        ("Menor de 5", (None, Decimal("5"))),
        ("> 40", (Decimal("40"), None)),
        ("Negativo", (None, None)),
    ],
)
def test_interpretar_texto_de_referencia(texto, esperado):
    assert importador.interpretar_referencia(texto) == esperado


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [("1.234,56", Decimal("1234.56")), ("1,234.56", Decimal("1234.56")), ("25000,0000", Decimal("25000")), ("", None)],
)
def test_leer_decimal(texto, esperado):
    assert importador.leer_decimal(texto) == esperado


# --- Carga por la interfaz ---


def _subir(c, datos: bytes, nombre: str = "lablinea.zip"):
    return c.post(
        "/catalogo/importar",
        data={"csrf": csrf(c, "/catalogo/importar")},
        files={"archivo": (nombre, datos, "application/zip")},
    )


def _conteo(tenant: str, tabla: str) -> int:
    async def contar(sesion):
        return await sesion.scalar(text(f"SELECT count(*) FROM lab.{tabla}"))  # noqa: S608 — nombre fijo de la prueba

    return correr(ejecutar_en_tenant("app", tenant, contar))


@pytest.fixture
def lab_b_limpio():
    """lab_b sin catálogo antes y después de la prueba (el catálogo no se borra desde la app)."""

    async def vaciar(sesion):
        for tabla in (
            "codigos_alternos", "tipos_codigo_alterno", "precios_examen", "tarifas", "requisitos_muestra",
            "rangos_referencia", "valores_lista", "parametros", "examenes", "tecnicas", "tipos_tubo",
            "tipos_muestra", "unidades", "secciones", "importaciones",
        ):  # fmt: skip
            await sesion.execute(text(f"DELETE FROM lab.{tabla}"))  # noqa: S608 — nombres fijos de la prueba

    correr(ejecutar_en_tenant("owner", "lab_b", vaciar))
    yield
    correr(ejecutar_en_tenant("owner", "lab_b", vaciar))


def admin_b(buzon):
    return autenticar(cliente("lab-b"), "admin@lab-b.test", buzon, laboratorio="lab_b")


def test_flujo_completo_de_importacion(buzon, lab_b_limpio):
    c = admin_b(buzon)
    respuesta = _subir(c, zip_de(CATALOGO), "C:\\exportes\\lablinea\u202e.zip")
    assert respuesta.status_code == 303
    vista = respuesta.headers["location"]
    pagina = c.get(vista).text
    assert "Cargar el catálogo" in pagina and "por revisar" in pagina
    assert "\u202e" not in pagina and "exportes" not in pagina  # nombre del archivo saneado
    assert _conteo("lab_b", "examenes") == 0  # la vista previa no carga nada

    assert c.post(f"{vista}/cargar", data={"csrf": csrf(c, vista)}).status_code == 303
    assert _conteo("lab_b", "examenes") == 3 and _conteo("lab_b", "rangos_referencia") == 4
    assert "quedó cargado" in c.get(vista).text
    # No se carga dos veces.
    assert c.post(f"{vista}/cargar", data={"csrf": csrf(c, vista)}).status_code == 404

    # El catálogo cargado se ve en la interfaz, con los rangos por revisar.
    catalogo = c.get("/catalogo").text
    assert "Hemograma" in catalogo and "rangos o requisitos de muestra por revisar" in catalogo
    assert "Hemoglobina" in c.get("/catalogo/revision").text

    # Una segunda importación del mismo archivo choca con lo existente.
    segunda = c.get(_subir(c, zip_de(CATALOGO)).headers["location"]).text
    assert "ya existe en el catálogo" in segunda and "Cargar el catálogo" not in segunda

    # El contenido del archivo se borra al cargar; queda el resumen.
    async def contenido(sesion):
        return (await sesion.execute(text("SELECT estado, contenido IS NULL FROM lab.importaciones"))).all()

    estados = correr(ejecutar_en_tenant("app", "lab_b", contenido))
    assert ("CARGADA", True) in estados


def test_rechazo_no_guarda_nada(buzon, lab_b_limpio):
    c = admin_b(buzon)
    respuesta = _subir(c, EJECUTABLES["pe"], "catalogo.zip")
    assert respuesta.status_code == 400 and "no es un ZIP válido" in respuesta.text
    respuesta = _subir(c, zip_de({**CATALOGO, "paciente.csv": "consecutivo;apellidos\n1;Pérez\n"}))
    assert respuesta.status_code == 400 and "pacientes" in respuesta.text
    assert "Pérez" not in respuesta.text
    assert _conteo("lab_b", "importaciones") == 0


def test_carga_atomica_si_algo_falla_a_mitad(buzon, lab_b_limpio, monkeypatch):
    c = admin_b(buzon)
    vista = _subir(c, zip_de(CATALOGO)).headers["location"]
    original = importador._INSERTS["precios"]
    monkeypatch.setitem(importador._INSERTS, "precios", "INSERT INTO lab.no_existe VALUES (1)")
    with pytest.raises(Exception):  # noqa: B017 — cualquier error de la base a mitad de la carga
        c.post(f"{vista}/cargar", data={"csrf": csrf(c, vista)})
    monkeypatch.setitem(importador._INSERTS, "precios", original)
    assert _conteo("lab_b", "examenes") == 0 and _conteo("lab_b", "secciones") == 0
    # La importación sigue prevista y se puede cargar después.
    assert c.post(f"{vista}/cargar", data={"csrf": csrf(c, vista)}).status_code == 303
    assert _conteo("lab_b", "precios_examen") == 3


def test_si_el_catalogo_cambia_la_carga_se_detiene(buzon, lab_b_limpio):
    c = admin_b(buzon)
    vista = _subir(c, zip_de(CATALOGO)).headers["location"]

    async def crear_choque(sesion):
        seccion = await sesion.scalar(text("INSERT INTO lab.secciones (codigo, nombre) VALUES ('X', 'X') RETURNING id"))
        await sesion.execute(
            text("INSERT INTO lab.examenes (codigo, nombre, seccion_id) VALUES ('GLU2', 'Glucosa', :s)"), {"s": seccion}
        )

    correr(ejecutar_en_tenant("app", "lab_b", crear_choque))
    respuesta = c.post(f"{vista}/cargar", data={"csrf": csrf(c, vista)})
    assert respuesta.headers["location"].endswith("?error=cambio")
    assert "cambió desde la vista previa" in c.get(respuesta.headers["location"]).text
    assert _conteo("lab_b", "examenes") == 1


def test_descartar(buzon, lab_b_limpio):
    c = admin_b(buzon)
    vista = _subir(c, zip_de(CATALOGO)).headers["location"]
    assert c.post(f"{vista}/descartar", data={"csrf": csrf(c, vista)}).status_code == 303
    assert c.post(f"{vista}/descartar", data={"csrf": csrf(c, vista)}).status_code == 404
    assert c.post(f"{vista}/cargar", data={"csrf": csrf(c, vista)}).status_code == 404


def test_importacion_de_otro_laboratorio_no_existe(buzon, lab_b_limpio):
    vista = _subir(admin_b(buzon), zip_de(CATALOGO)).headers["location"]
    otro = autenticar(cliente(), "admin@lab-a.test", buzon)
    assert otro.get(vista).status_code == 404
    assert otro.post(f"{vista}/cargar", data={"csrf": csrf(otro, "/panel")}).status_code == 404
    importacion = vista.rsplit("/", 1)[1]

    async def en_lab_a(sesion):
        return await sesion.scalar(text("SELECT count(*) FROM lab.importaciones WHERE uuid = :u"), {"u": importacion})

    assert correr(ejecutar_en_tenant("app", "lab_a", en_lab_a)) == 0


@pytest.mark.parametrize("email", ["recepcion@lab-a.test", "auditor@lab-a.test"])
def test_importar_exige_crear_en_configuracion(buzon, email):
    c = autenticar(cliente(), email, buzon)
    assert c.get("/catalogo/importar").status_code == 403


def test_sin_archivo(buzon):
    c = autenticar(cliente(), "admin@lab-a.test", buzon)
    respuesta = c.post("/catalogo/importar", data={"csrf": csrf(c, "/catalogo/importar")})
    assert respuesta.status_code == 400 and "vacío" in respuesta.text


@pytest.fixture
def admin_a(buzon):
    """Una sesión por prueba (el TOTP no se reutiliza en la misma ventana)."""
    return autenticar(cliente(), "admin@lab-a.test", buzon)


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(datos=st.binary(max_size=3000))
def test_subidas_arbitrarias_sin_errores_500(admin_a, datos):
    assert _subir(admin_a, datos).status_code in (303, 400)


def test_nombre_de_tabla_normalizado():
    assert importador.normalizar("Es titulo ?") == "estitulo"
    assert importador.normalizar("Codigo_Analisis x Empresa") == "codigoanalisisxempresa"
    assert re.fullmatch(r"[a-z0-9]*", importador.normalizar("¿Cualquier cosa?"))


def test_cargar_rechaza_un_plan_con_errores():
    plan = _plan({**CATALOGO, "seccion.csv": "codigo;descripcion\n"})
    with pytest.raises(ValueError):
        asyncio.run(importador.cargar(None, plan))


def test_filas_desordenadas_generan_errores_y_advertencias_sin_romperse():
    """Una exportación con datos sucios en todas las tablas: cada fila mala se reporta, nada lanza."""
    archivos = {
        "seccion.csv": "codigo;descripcion\nHEM;Hematología\nHEM;Repetida\nSIN;\n",
        "analisis.csv": "consecutivo;descripcion;seccion\n1;Hemograma;HEM\n2;X;HEM\n",
        "detalle analisis.csv": (
            "consecutivo;analisis;descripcion;unidad;RangoMinimo;RangoMaximo\n"
            "10;1;Hemoglobina;g/L;1e5;99999999999\n"
            "x;1;Malo;;;\n"
            "11;1;;;;\n"
            "10;1;Repetido;;;\n"
            "12;1;Color;;;\n"
        ),
        "lista de valores.csv": "consecutivo;pregunta por analisis;valor\n1;abc;Rojo\n2;12;\n3;12;Rojo\n4;12;rojo\n",
        "tipo muestra.csv": "tipo;descripcion\nSANG;Sangre\n",
        "muestras x analisis.csv": (
            "consecutivo;analisis;descripcion;tipo de muestra\n1;x;a;SANG\n2;1;a;\n3;1;a;SANG\n4;1;a;SANG\n"
        ),
        "tipo tarifa.csv": "codigo;descripcion\nPART;Particular\n",
        "costo analisis.csv": "tipo tarifa;analisis;costo\nPART;1;-5\n;1;10\nPART;1;10\nPART;1;20\n",
        "Tipo Codigo Alterno.csv": "codigo;descripcion\nSOAT;SOAT\n",
        "Codigo Analisis x Empresa.csv": (
            "tipo codigo alterno;analisis;codigo alterno\nSOAT;x;A\nSOAT;1;\nSOAT;1;A\nSOAT;1;B\n"
        ),
    }
    plan = analizar(leer_paquete(zip_de(archivos)), Existentes(), "COP")
    errores = {e["clave"] for e in plan.errores}
    advertencias = {a["clave"] for a in plan.advertencias}
    assert {"repetido", "campo_invalido", "numero_invalido"} <= errores
    assert {"numero_ignorado", "valor_repetido", "requisito_repetido"} <= advertencias
    assert "g/L" in {u["codigo"] for u in plan.unidades}  # unidad usada sin estar en la tabla: se crea


def test_solo_las_tablas_obligatorias():
    obligatorias = {k: CATALOGO[k] for k in ("seccion.csv", "analisis.csv")}
    obligatorias["detalle analisis.csv"] = "consecutivo;analisis;descripcion\n1;1;Hemoglobina\n2;2;Glucosa\n3;3;Color\n"
    plan = analizar(leer_paquete(zip_de(obligatorias)), Existentes(), "COP")
    assert plan.errores == [] and plan.conteos()["examenes"] == 3 and plan.precios == []


def test_total_descomprimido_limitado(monkeypatch):
    monkeypatch.setattr(importador, "MAX_TOTAL", 500)
    assert _rechazo(zip_de(CATALOGO)) == "grande"
