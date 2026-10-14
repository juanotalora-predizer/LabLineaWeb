"""E2E de pacientes en Chromium (etapa 7): texto de autorización, registro, búsqueda, solicitud y revocación."""

import uuid

import pytest

from tests.ayudas import totp_actual
from tests.conftest import CLAVE, PACIENTES_SINTETICOS

pytestmark = pytest.mark.e2e


def _url(puerto: int, ruta: str) -> str:
    return f"https://lab-a.lablinea.localhost:{puerto}{ruta}"


def test_registrar_buscar_y_revocar(pagina, servidor):
    persona = PACIENTES_SINTETICOS[5]
    pagina.goto(_url(servidor, "/ingresar"))
    pagina.fill("#email", "admin@lab-a.test")
    pagina.fill("#clave", CLAVE)
    pagina.click("button[type=submit]")
    pagina.fill("#codigo", totp_actual("lab_a", "admin@lab-a.test"))
    pagina.click("form[action='/verificar'] button")

    # 1. El laboratorio publica su texto de autorización (el modelo del país trae campos por completar).
    pagina.click("nav a[href='/configuracion/autorizacion']")
    pagina.fill(
        "#contenido",
        "Autorizo al Laboratorio A Sintético a tratar mis datos personales y de salud para prestar el servicio.\n"
        f"Canales: correo sintético. Versión E2E {uuid.uuid4().hex[:8]}.",
    )
    pagina.click("form[action='/configuracion/autorizacion'] button[type=submit]")
    assert "Versiones publicadas" in pagina.content()

    # 2. Registro con la autorización firmada.
    pagina.click("nav a[href='/pacientes']")
    pagina.click("text=Registrar paciente")
    pagina.select_option("#tipo_documento", persona.tipo_documento)
    pagina.fill("#numero_documento", persona.numero_documento)
    pagina.fill("#nombres", persona.nombres)
    pagina.fill("#apellidos", persona.apellidos)
    pagina.select_option("#sexo", persona.sexo)
    pagina.fill("#fecha_nacimiento", "1985-04-20")
    pagina.fill("#email", persona.email)
    pagina.select_option("#medio", "FORMATO_FIRMADO")
    pagina.check("input[name=acepto]")
    pagina.click("form[action='/pacientes/nuevo'] button[type=submit]")
    assert "/pacientes/" in pagina.url and "Vigente" in pagina.content()
    ficha = pagina.url

    # 3. Búsqueda por documento: el texto buscado no queda en la URL.
    pagina.goto(_url(servidor, "/pacientes"))
    pagina.fill("#consulta", persona.numero_documento)
    pagina.click("form[action='/pacientes/buscar'] button[type=submit]")
    assert persona.numero_documento not in pagina.url
    pagina.click(f"text={persona.apellidos}")
    assert pagina.url == ficha

    # 4. Solicitud de consulta y revocación de la autorización.
    pagina.select_option("#tipo", "CONSULTA")
    pagina.select_option("#canal", "CORREO")
    pagina.click("form[action$='/solicitudes'] button[type=submit]")
    assert "Abierta" in pagina.content()
    pagina.click("text=Revocar la autorización")
    pagina.fill("#motivo", "El titular lo pidió")
    pagina.click("form[action$='/revocar'] button[type=submit]")
    contenido = pagina.content()
    assert "Sin autorización" in contenido and "Revocada" in contenido
