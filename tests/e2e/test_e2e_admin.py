"""E2E del Admin Hub en Chromium (etapa 4): alta de un laboratorio y activación de su administrador.

Recorre el flujo real de punta a punta: personal de la plataforma ingresa con TOTP, da de alta un
laboratorio, el trabajador envía la invitación, el administrador del laboratorio crea su contraseña,
ingresa con el código por correo e inscribe su app autenticadora.
"""

import re
import uuid

import pyotp
import pytest

from app.core import tareas
from tests.ayudas import totp_actual
from tests.conftest import CLAVE, correr

pytestmark = pytest.mark.e2e

MAESTRO = "maestro@plataforma.test"


def _url(puerto: int, sub: str, ruta: str = "/") -> str:
    return f"https://{sub}.lablinea.localhost:{puerto}{ruta}"


async def _procesar_cola():
    while await tareas.procesar_una():
        pass


def test_alta_de_laboratorio_y_activacion_del_administrador(pagina, servidor, buzon_smtp, buzon):
    smtp, _ = buzon_smtp
    sub = f"e2e-{uuid.uuid4().hex[:6]}"
    jefe = f"jefe@{sub}.test"

    # 1. Personal de la plataforma ingresa al Admin Hub.
    pagina.goto(_url(servidor, "admin", "/ingresar"))
    pagina.fill("#email", MAESTRO)
    pagina.fill("#clave", CLAVE)
    pagina.click("button[type=submit]")
    pagina.fill("#codigo", totp_actual("plataforma", MAESTRO))
    pagina.click("form[action='/verificar'] button")
    assert pagina.url.endswith("/panel")

    # 2. Alta del laboratorio.
    pagina.click("text=Laboratorios")
    pagina.click("text=Nuevo laboratorio")
    pagina.fill("#nombre", "Laboratorio E2E")
    pagina.fill("#subdominio", sub)
    pagina.fill("#identificador_fiscal", "9" + str(uuid.uuid4().int)[:9])
    pagina.fill("#sede", "Sede Norte")
    pagina.fill("#ciudad", "Cali")
    pagina.fill("#admin_nombre", "Jefa del Laboratorio")
    pagina.fill("#admin_email", jefe)
    pagina.click("form[action='/laboratorios/nuevo'] button[type=submit]")
    assert re.search(r"/laboratorios/[0-9a-f-]{36}$", pagina.url)
    assert sub in pagina.content()

    # 3. El trabajador envía la invitación (en este proceso, con el correo capturado por `buzon`).
    correr(_procesar_cola())
    mensaje = next(m for m in buzon if m["To"] == jefe)
    token = re.search(r"/activar/(\S+)", mensaje.get_content()).group(1)

    # 4. La administradora crea su contraseña.
    pagina.goto(_url(servidor, sub, f"/activar/{token}"))
    pagina.fill("#clave", CLAVE)
    pagina.fill("#confirmacion", CLAVE)
    pagina.click("form button[type=submit]")
    assert pagina.url.endswith("/ingresar?activada=1")
    assert "Ya puede ingresar" in pagina.content()

    # 5. Ingresa: aún no tiene app autenticadora, así que recibe un código por correo y luego la inscribe.
    pagina.fill("#email", jefe)
    pagina.fill("#clave", CLAVE)
    pagina.click("button[type=submit]")
    pagina.fill("#codigo", smtp.codigo_para(jefe))
    pagina.click("form[action='/verificar'] button")
    assert pagina.url.endswith("/seguridad/totp")
    secreto = pagina.locator(".secreto").inner_text().strip()
    pagina.fill("#codigo", pyotp.TOTP(secreto).now())
    pagina.click("form[action='/seguridad/totp'] button")
    assert pagina.url.endswith("/panel")
    assert "ADMINISTRADOR" in pagina.content()

    # 6. Ve los usuarios de su laboratorio y solo los suyos.
    pagina.click("text=Usuarios")
    contenido = pagina.content()
    assert jefe in contenido and "lab-a.test" not in contenido
