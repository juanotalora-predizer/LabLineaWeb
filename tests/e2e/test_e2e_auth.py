"""Pruebas de punta a punta en Chromium (spec infraestructura/0011): servidor real en HTTPS,
correo capturado por un SMTP local y la base de prueba con los usuarios sintéticos."""

import pytest

from tests.ayudas import totp_actual
from tests.conftest import CLAVE

pytestmark = pytest.mark.e2e


def _url(puerto: int, sub: str, ruta: str = "/") -> str:
    return f"https://{sub}.lablinea.localhost:{puerto}{ruta}"


def _ingresar_con_clave(pagina, puerto, email, sub="lab-a"):
    pagina.goto(_url(puerto, sub, "/ingresar"))
    pagina.fill("#email", email)
    pagina.fill("#clave", CLAVE)
    pagina.click("button[type=submit]")


def test_paciente_ingresa_con_codigo_por_correo_y_sale(pagina, servidor, buzon_smtp):
    buzon, _ = buzon_smtp
    _ingresar_con_clave(pagina, servidor, "paciente@lab-a.test")
    assert pagina.url.endswith("/verificar")
    pagina.fill("#codigo", buzon.codigo_para("paciente@lab-a.test"))
    pagina.click("form[action='/verificar'] button")
    assert pagina.url.endswith("/panel")
    assert pagina.locator("h1").inner_text() == "Hola, Paciente A"

    pagina.click("form[action='/salir'] button")
    assert pagina.url.endswith("/ingresar")
    pagina.goto(_url(servidor, "lab-a", "/panel"))
    assert pagina.url.endswith("/ingresar")


def test_personal_ingresa_con_app_autenticadora(pagina, servidor):
    _ingresar_con_clave(pagina, servidor, "admin@lab-a.test")
    pagina.fill("#codigo", totp_actual("lab_a", "admin@lab-a.test"))
    pagina.click("form[action='/verificar'] button")
    assert pagina.url.endswith("/panel")
    assert "ADMINISTRADOR" in pagina.content()
    pagina.click("text=Usuarios")
    assert pagina.url.endswith("/configuracion/usuarios")
    assert "recepcion@lab-a.test" in pagina.content()


def test_cookies_seguras_y_aisladas_por_laboratorio(pagina, servidor, buzon_smtp):
    buzon, _ = buzon_smtp
    _ingresar_con_clave(pagina, servidor, "paciente@lab-a.test")
    pagina.fill("#codigo", buzon.codigo_para("paciente@lab-a.test"))
    pagina.click("form[action='/verificar'] button")
    cookies = {c["name"]: c for c in pagina.context.cookies()}
    sesion = cookies["__Host-sesion"]
    assert sesion["secure"] and sesion["httpOnly"]
    assert sesion["domain"] == "lab-a.lablinea.localhost"  # sin atributo Domain: solo este host
    assert sesion["sameSite"] == "Lax"
    # El navegador no envía la sesión de lab-a a lab-b.
    pagina.goto(_url(servidor, "lab-b", "/panel"))
    assert pagina.url.endswith("/ingresar")
    assert "Laboratorio B Sintético" in pagina.content()


def test_credenciales_incorrectas_muestran_mensaje_generico(pagina, servidor):
    pagina.goto(_url(servidor, "lab-a", "/ingresar"))
    pagina.fill("#email", "no-existe@lab-a.test")
    pagina.fill("#clave", "Clave-equivocada-1")
    pagina.click("button[type=submit]")
    assert pagina.locator(".error").inner_text() == "Correo o contraseña incorrectos."


def test_sin_errores_de_csp_en_el_navegador(pagina, servidor):
    errores = []
    pagina.on("console", lambda m: errores.append(m.text) if m.type == "error" else None)
    for ruta in ("/", "/ingresar"):
        pagina.goto(_url(servidor, "lab-a", ruta))
    assert not [e for e in errores if "Content Security Policy" in e]
