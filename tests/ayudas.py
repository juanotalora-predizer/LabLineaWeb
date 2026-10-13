"""Utilidades para las pruebas de autenticación."""

import re
import time

import pyotp
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import CLAVE, SECRETOS_TOTP

_CSRF = re.compile(r'name="csrf" value="([^"]+)"')
_CODIGO = re.compile(r"\b(\d{6})\b")


def cliente(subdominio: str = "lab-a") -> TestClient:
    # HTTPS: las cookies __Host- solo viajan por conexiones seguras.
    return TestClient(app, base_url=f"https://{subdominio}.lablinea.localhost", follow_redirects=False)


def csrf(c: TestClient, ruta: str = "/ingresar") -> str:
    respuesta = c.get(ruta)
    encontrado = _CSRF.search(respuesta.text)
    assert encontrado, f"sin token CSRF en {ruta} ({respuesta.status_code})"
    return encontrado.group(1)


def enviar_clave(c: TestClient, email: str, clave: str = CLAVE):
    return c.post("/ingresar", data={"email": email, "clave": clave, "csrf": csrf(c)})


def codigo_en_buzon(buzon: list, email: str) -> str:
    for mensaje in reversed(buzon):
        if mensaje["To"] == email:
            return _CODIGO.search(mensaje.get_content()).group(1)
    raise AssertionError(f"no llegó ningún correo a {email}")


def totp_actual(laboratorio: str, email: str, desfase: int = 0) -> str:
    return pyotp.TOTP(SECRETOS_TOTP[(laboratorio, email)]).at(time.time() + desfase)


def enviar_codigo(c: TestClient, codigo: str):
    return c.post("/verificar", data={"codigo": codigo, "csrf": csrf(c, "/verificar")})


def autenticar(c: TestClient, email: str, buzon: list, laboratorio: str = "lab_a") -> TestClient:
    """Completa el ingreso (contraseña + segundo factor) y devuelve el cliente con su sesión."""
    respuesta = enviar_clave(c, email)
    assert respuesta.status_code == 303, respuesta.text
    con_totp = (laboratorio, email) in SECRETOS_TOTP
    codigo = totp_actual(laboratorio, email) if con_totp else codigo_en_buzon(buzon, email)
    respuesta = enviar_codigo(c, codigo)
    if con_totp and respuesta.status_code == 400:
        # Segundo ingreso del mismo usuario en la ventana de 30 s: el código ya se usó (anti-repetición);
        # el servidor acepta el del intervalo siguiente.
        respuesta = enviar_codigo(c, totp_actual(laboratorio, email, desfase=30))
    assert respuesta.status_code == 303, respuesta.text
    return c
