"""Fuzzing de los formularios con token CSRF válido (spec infraestructura/0011).

ZAP y schemathesis no pasan la protección CSRF, así que no prueban el interior de los
manejadores. Aquí hypothesis genera contenido arbitrario (caracteres nulos, unicode,
fragmentos SQL o HTML, textos enormes) con un token válido: nunca debe haber un error 500
ni reflejarse una entrada sin escapar.
"""

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.ayudas import cliente, csrf, enviar_clave
from tests.conftest import correr

PERMITIDOS = {200, 303, 400, 403, 429, 503}

texto = st.one_of(
    st.text(max_size=300),
    st.sampled_from(
        [
            "\x00",
            "admin@lab-a.test\x00",
            "' OR '1'='1",
            "admin@lab-a.test'; DROP TABLE lab.usuarios; --",
            "<script>alert(1)</script>",
            '"><img src=x onerror=alert(1)>',
            "{{7*7}}",
            "${7*7}",
            "%00",
            "‮\u0000﻿",
            "a" * 5000,
        ]
    ),
)

AJUSTES = settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])


def _sin_reflejo_peligroso(html: str) -> None:
    assert "<script>alert(1)</script>" not in html
    assert "<img src=x onerror=alert(1)>" not in html
    assert ">49<" not in html  # sin evaluación de plantillas


@AJUSTES
@given(email=texto, clave=texto)
def test_ingresar_con_entradas_arbitrarias(email, clave):
    c = cliente()
    respuesta = c.post("/ingresar", data={"email": email, "clave": clave, "csrf": csrf(c)})
    assert respuesta.status_code in PERMITIDOS, (repr(email)[:80], respuesta.status_code)
    _sin_reflejo_peligroso(respuesta.text)


@pytest.fixture
def cliente_pendiente():
    """Cliente con contraseña verificada y segundo factor pendiente."""
    c = cliente()
    assert enviar_clave(c, "admin@lab-a.test").status_code == 303
    return c


@AJUSTES
@given(codigo=texto)
def test_verificar_con_entradas_arbitrarias(cliente_pendiente, codigo):
    c = cliente_pendiente
    respuesta = c.post("/verificar", data={"codigo": codigo, "csrf": csrf(c, "/verificar")})
    assert respuesta.status_code in PERMITIDOS, (repr(codigo)[:80], respuesta.status_code)
    _sin_reflejo_peligroso(respuesta.text)


@AJUSTES
@given(codigo=texto)
def test_inscripcion_totp_con_entradas_arbitrarias(codigo):
    from tests.ayudas import autenticar

    buzon = []
    from app.core import correo

    original = correo._enviar_sync
    correo._enviar_sync = buzon.append
    try:
        correr(_reiniciar_limites())
        c = autenticar(cliente(), "nuevo@lab-a.test", buzon)
        respuesta = c.post("/seguridad/totp", data={"codigo": codigo, "csrf": csrf(c, "/seguridad/totp")})
    finally:
        correo._enviar_sync = original
    assert respuesta.status_code in PERMITIDOS, (repr(codigo)[:80], respuesta.status_code)


@AJUSTES
@given(campo=st.sampled_from(["email", "clave", "csrf", "codigo", "otro"]), valor=texto)
def test_campos_inesperados_y_csrf_arbitrario(campo, valor):
    c = cliente()
    csrf(c)
    respuesta = c.post("/ingresar", data={campo: valor})
    assert respuesta.status_code in PERMITIDOS


async def _reiniciar_limites():
    from sqlalchemy import text

    from tests.conftest import engine_de

    owner = engine_de("owner")
    async with owner.begin() as conexion:
        await conexion.execute(text("TRUNCATE lab.limites, lab.codigos_verificacion"))
    await owner.dispose()


# --- Formularios de la etapa 4 ---

CAMPOS_ALTA = [
    "nombre",
    "subdominio",
    "identificador_fiscal",
    "pais",
    "plan",
    "sede",
    "ciudad",
    "admin_email",
    "admin_nombre",
]


@pytest.fixture
def maestro():
    """Personal de la plataforma con sesión completa (una por prueba: el TOTP no se puede reutilizar)."""
    from tests.ayudas import autenticar

    return autenticar(cliente("admin"), "maestro@plataforma.test", [], laboratorio="plataforma")


@pytest.fixture
def admin_lab_a():
    from tests.ayudas import autenticar

    return autenticar(cliente(), "admin@lab-a.test", [])


@AJUSTES
@given(datos=st.fixed_dictionaries({campo: texto for campo in CAMPOS_ALTA}))
def test_alta_de_laboratorio_con_entradas_arbitrarias(maestro, datos):
    c = maestro
    respuesta = c.post("/laboratorios/nuevo", data={**datos, "csrf": csrf(c, "/laboratorios/nuevo")})
    assert respuesta.status_code in PERMITIDOS, respuesta.status_code
    _sin_reflejo_peligroso(respuesta.text)


@AJUSTES
@given(codigo=texto, nombre=texto, maximo=texto, modulos=st.lists(texto, max_size=5))
def test_plan_con_entradas_arbitrarias(maestro, codigo, nombre, maximo, modulos):
    c = maestro
    datos = {"codigo": codigo, "nombre": nombre, "max_usuarios": maximo, "modulos": modulos}
    respuesta = c.post("/planes/nuevo", data={**datos, "csrf": csrf(c, "/planes/nuevo")})
    assert respuesta.status_code in PERMITIDOS, respuesta.status_code
    _sin_reflejo_peligroso(respuesta.text)


@AJUSTES
@given(email=texto, nombre=texto, tipo=texto, roles=st.lists(texto, max_size=4))
def test_invitar_usuario_con_entradas_arbitrarias(admin_lab_a, email, nombre, tipo, roles):
    c = admin_lab_a
    datos = {"email": email, "nombre": nombre, "tipo": tipo, "roles": roles}
    respuesta = c.post(
        "/configuracion/usuarios/nuevo", data={**datos, "csrf": csrf(c, "/configuracion/usuarios/nuevo")}
    )
    assert respuesta.status_code in PERMITIDOS, respuesta.status_code
    _sin_reflejo_peligroso(respuesta.text)


@AJUSTES
@given(
    token=st.text(alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_", max_size=200),
    clave=texto,
    confirmacion=texto,
)
def test_activar_con_entradas_arbitrarias(token, clave, confirmacion):
    c = cliente()
    ruta = f"/activar/{token}" if token else "/activar/x"
    respuesta = c.post(ruta, data={"clave": clave, "confirmacion": confirmacion, "csrf": csrf(c)})
    assert respuesta.status_code in PERMITIDOS | {404}, respuesta.status_code


# --- Formularios de la etapa 5 ---


@pytest.fixture(scope="module")
def factura_para_fuzzing():
    """Una factura pendiente de un laboratorio sintético (valor de lista 100.000 COP)."""
    from sqlalchemy import text

    from app.admin import facturacion
    from tests.ayudas import nuevo_laboratorio
    from tests.conftest import ejecutar_en_plataforma

    lab = nuevo_laboratorio("MENSUAL")

    async def generar(sesion):
        await sesion.execute(
            text(
                "INSERT INTO plataforma.precios (pais, plan_id, tipo_licencia, moneda, valor, vigente_desde)"
                " SELECT 'COL', id, 'MENSUAL', 'COP', 100000, DATE '2026-01-01' FROM plataforma.planes"
                " WHERE codigo = 'COMPLETO' ON CONFLICT DO NOTHING"
            )
        )
        return await facturacion.generar_factura(sesion, lab["uuid"], "MENSUAL")

    return lab, correr(ejecutar_en_plataforma(generar))


@AJUSTES
@given(valor=texto, medio=texto, referencia=texto, recibido=texto)
def test_pago_con_entradas_arbitrarias(maestro, factura_para_fuzzing, valor, medio, referencia, recibido):
    _, factura = factura_para_fuzzing
    c, ruta = maestro, f"/facturas/{factura}"
    datos = {"valor": valor, "medio": medio, "referencia": referencia, "recibido_en": recibido}
    respuesta = c.post(f"{ruta}/pagos", data={**datos, "csrf": csrf(c, ruta)})
    assert respuesta.status_code in PERMITIDOS, respuesta.status_code
    _sin_reflejo_peligroso(respuesta.text)


@AJUSTES
@given(
    datos=st.fixed_dictionaries(
        {c: texto for c in ("pais", "plan", "tipo_licencia", "moneda", "valor", "vigente_desde")}
    )
)
def test_precio_con_entradas_arbitrarias(maestro, datos):
    respuesta = maestro.post("/precios", data={**datos, "csrf": csrf(maestro, "/precios")})
    assert respuesta.status_code in PERMITIDOS, respuesta.status_code
    _sin_reflejo_peligroso(respuesta.text)


@AJUSTES
@given(datos=st.fixed_dictionaries({c: texto for c in ("nombre", "porcentaje", "tipo_licencia", "desde", "hasta")}))
def test_campana_con_entradas_arbitrarias(maestro, datos):
    respuesta = maestro.post("/campanas", data={**datos, "csrf": csrf(maestro, "/precios")})
    assert respuesta.status_code in PERMITIDOS, respuesta.status_code
    _sin_reflejo_peligroso(respuesta.text)


@AJUSTES
@given(accion=texto, motivo=texto, licencia=texto)
def test_suscripcion_con_entradas_arbitrarias(maestro, factura_para_fuzzing, accion, motivo, licencia):
    lab, _ = factura_para_fuzzing
    ruta = f"/laboratorios/{lab['uuid']}"
    datos = {"accion": accion, "motivo": motivo, "tipo_licencia": licencia}
    respuesta = maestro.post(f"{ruta}/suscripcion", data={**datos, "csrf": csrf(maestro, ruta)})
    assert respuesta.status_code in PERMITIDOS, respuesta.status_code


@AJUSTES
@given(horas=texto, motivo=texto)
def test_autorizar_soporte_con_entradas_arbitrarias(admin_lab_a, horas, motivo):
    c = admin_lab_a
    respuesta = c.post(
        "/configuracion/soporte", data={"horas": horas, "motivo": motivo, "csrf": csrf(c, "/configuracion/soporte")}
    )
    assert respuesta.status_code in PERMITIDOS, respuesta.status_code
    _sin_reflejo_peligroso(respuesta.text)


# --- Formularios de la etapa 6 (catálogo) ---


@AJUSTES
@given(
    datos=st.fixed_dictionaries(
        {c: texto for c in ("codigo", "nombre", "seccion", "tecnica", "codigo_nacional", "loinc")}
    )
)
def test_examen_nuevo_con_entradas_arbitrarias(admin_lab_a, datos):
    c = admin_lab_a
    respuesta = c.post("/catalogo/examenes/nuevo", data={**datos, "csrf": csrf(c, "/catalogo/examenes/nuevo")})
    assert respuesta.status_code in PERMITIDOS, respuesta.status_code
    _sin_reflejo_peligroso(respuesta.text)


@AJUSTES
@given(
    tipo=st.sampled_from(
        ["secciones", "unidades", "tipos_muestra", "tipos_tubo", "tecnicas", "tarifas", "tipos_codigo"]
    ),
    datos=st.fixed_dictionaries({c: texto for c in ("codigo", "nombre", "extra", "aditivo", "capacidad")}),
)
def test_maestros_con_entradas_arbitrarias(admin_lab_a, tipo, datos):
    c = admin_lab_a
    respuesta = c.post(f"/catalogo/maestros/{tipo}", data={**datos, "csrf": csrf(c, "/catalogo/maestros")})
    assert respuesta.status_code in PERMITIDOS, respuesta.status_code
    _sin_reflejo_peligroso(respuesta.text)


@pytest.fixture
def parametro_lab_a(admin_lab_a):
    """Un examen con un parámetro numérico en lab-a para recibir rangos, precios y requisitos arbitrarios."""
    import uuid

    c = admin_lab_a
    s = uuid.uuid4().hex[:6]
    c.post(
        "/catalogo/maestros/secciones",
        data={"codigo": f"F{s}", "nombre": "Fuzz", "csrf": csrf(c, "/catalogo/maestros")},
    )
    examen = c.post(
        "/catalogo/examenes/nuevo",
        data={
            "codigo": f"F{s}",
            "nombre": f"Fuzz {s}",
            "seccion": f"F{s}",
            "csrf": csrf(c, "/catalogo/examenes/nuevo"),
        },
    ).headers["location"]
    parametro = c.post(
        f"{examen}/parametros", data={"nombre": "P", "tipo": "NUMERICO", "orden": "1", "csrf": csrf(c, examen)}
    ).headers["location"]
    return examen, parametro


@AJUSTES
@given(
    datos=st.fixed_dictionaries(
        {
            c: texto
            for c in (
                "sexo",
                "edad_min",
                "unidad_min",
                "edad_max",
                "unidad_max",
                "minimo",
                "maximo",
                "critico_min",
                "critico_max",
                "valor_esperado",
                "texto_impreso",
            )
        }  # fmt: skip
    )
)
def test_rango_con_entradas_arbitrarias(admin_lab_a, parametro_lab_a, datos):
    c, (_, parametro) = admin_lab_a, parametro_lab_a
    respuesta = c.post(f"{parametro}/rangos", data={**datos, "csrf": csrf(c, parametro)})
    assert respuesta.status_code in PERMITIDOS, respuesta.status_code
    _sin_reflejo_peligroso(respuesta.text)


@AJUSTES
@given(tarifa=texto, valor=texto, muestra=texto, tubo=texto, volumen=texto)
def test_precio_y_requisito_con_entradas_arbitrarias(
    admin_lab_a, parametro_lab_a, tarifa, valor, muestra, tubo, volumen
):
    c, (examen, _) = admin_lab_a, parametro_lab_a
    token = csrf(c, examen)
    for ruta, datos in (
        (f"{examen}/precios", {"tarifa": tarifa, "valor": valor}),
        (f"{examen}/requisitos", {"tipo_muestra": muestra, "tipo_tubo": tubo, "volumen_ml": volumen}),
    ):
        respuesta = c.post(ruta, data={**datos, "csrf": token})
        assert respuesta.status_code in PERMITIDOS | {404}, respuesta.status_code


# --- Pacientes (etapa 7) ---

CAMPOS_PACIENTE = (
    "tipo_documento",
    "numero_documento",
    "nombres",
    "apellidos",
    "sexo",
    "fecha_nacimiento",
    "pais",
    "email",
    "telefono",
    "direccion",
    "medio",
    "acepto",
    "representante_nombre",
    "representante_documento",
    "representante_parentesco",
    "texto_version",
)


@pytest.fixture
def paciente_lab_a(admin_lab_a):
    """Texto de autorización publicado y un paciente sintético de lab-a para los formularios de su ficha."""
    import uuid

    from sqlalchemy import text

    from tests.conftest import ejecutar_en_tenant

    async def preparar(sesion):
        if not await sesion.scalar(text("SELECT count(*) FROM lab.textos_autorizacion")):
            await sesion.execute(
                text("INSERT INTO lab.textos_autorizacion (version, contenido) VALUES (1, :c)"),
                {"c": "Texto sintético de autorización de tratamiento de datos para las pruebas de fuzzing."},
            )

    correr(ejecutar_en_tenant("app", "lab_a", preparar))
    datos = {
        "tipo_documento": "CC",
        "numero_documento": "97" + str(uuid.uuid4().int)[:8],
        "nombres": "Fuzz",
        "apellidos": "Sintético",
        "sexo": "F",
        "fecha_nacimiento": "1990-01-01",
        "pais": "COL",
        "medio": "FORMATO_FIRMADO",
        "acepto": "si",
    }
    c = admin_lab_a
    respuesta = c.post("/pacientes/nuevo", data={**datos, "csrf": csrf(c, "/pacientes/nuevo")})
    assert respuesta.status_code == 303, respuesta.text[-500:]
    return respuesta.headers["location"]


@AJUSTES
@given(datos=st.fixed_dictionaries({c: texto for c in CAMPOS_PACIENTE}))
def test_paciente_nuevo_con_entradas_arbitrarias(admin_lab_a, paciente_lab_a, datos):
    c = admin_lab_a
    respuesta = c.post("/pacientes/nuevo", data={**datos, "csrf": csrf(c, "/pacientes/nuevo")})
    assert respuesta.status_code in PERMITIDOS, respuesta.status_code
    _sin_reflejo_peligroso(respuesta.text)


@AJUSTES
@given(consulta=texto, datos=st.fixed_dictionaries({c: texto for c in (*CAMPOS_PACIENTE[:10], "solicitud")}))
def test_busqueda_y_edicion_con_entradas_arbitrarias(admin_lab_a, paciente_lab_a, consulta, datos):
    c = admin_lab_a
    token = csrf(c, paciente_lab_a)
    for ruta, cuerpo in (("/pacientes/buscar", {"consulta": consulta}), (f"{paciente_lab_a}/editar", datos)):
        respuesta = c.post(ruta, data={**cuerpo, "csrf": token})
        assert respuesta.status_code in PERMITIDOS, (ruta, respuesta.status_code)
        _sin_reflejo_peligroso(respuesta.text)


@AJUSTES
@given(tipo=texto, canal=texto, descripcion=texto, motivo=texto, estado=texto, solicitud=texto, confirmacion=texto)
def test_solicitudes_revocacion_y_supresion_con_entradas_arbitrarias(
    admin_lab_a, paciente_lab_a, tipo, canal, descripcion, motivo, estado, solicitud, confirmacion
):
    c = admin_lab_a
    token = csrf(c, paciente_lab_a)
    for ruta, cuerpo in (
        (f"{paciente_lab_a}/solicitudes", {"tipo": tipo, "canal": canal, "descripcion": descripcion}),
        (f"{paciente_lab_a}/revocar", {"canal": canal, "motivo": motivo}),
        (f"{paciente_lab_a}/autorizacion", {"medio": tipo, "acepto": estado, "representante_nombre": motivo}),
        (f"{paciente_lab_a}/suprimir", {"solicitud": solicitud, "confirmacion": confirmacion}),
        ("/configuracion/autorizacion", {"contenido": descripcion}),
    ):
        respuesta = c.post(ruta, data={**cuerpo, "csrf": token})
        assert respuesta.status_code in PERMITIDOS, (ruta, respuesta.status_code)
        _sin_reflejo_peligroso(respuesta.text)
