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
