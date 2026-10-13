"""Fixtures de las pruebas de punta a punta: servidor HTTPS real, SMTP local y Chromium."""

import datetime
import os
import re
import socket
import subprocess
import sys
import time
from email import message_from_string, policy
from pathlib import Path

import pytest
from aiosmtpd.controller import Controller
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from playwright.sync_api import sync_playwright

from tests.conftest import RAIZ


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _certificado(directorio: Path) -> tuple[Path, Path]:
    """Certificado autofirmado para *.lablinea.localhost (solo para la prueba)."""
    clave = ec.generate_private_key(ec.SECP256R1())
    nombre = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "lablinea.localhost")])
    ahora = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(nombre)
        .issuer_name(nombre)
        .public_key(clave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(ahora - datetime.timedelta(minutes=5))
        .not_valid_after(ahora + datetime.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("*.lablinea.localhost"), x509.DNSName("lablinea.localhost")]),
            critical=False,
        )
        .sign(clave, hashes.SHA256())
    )
    ruta_cert, ruta_clave = directorio / "cert.pem", directorio / "clave.pem"
    ruta_cert.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    ruta_clave.write_bytes(
        clave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    return ruta_cert, ruta_clave


class _Buzon:
    def __init__(self):
        self.mensajes: list[str] = []

    async def handle_DATA(self, server, session, envelope):  # noqa: N802 (API de aiosmtpd)
        self.mensajes.append(envelope.content.decode("utf-8", "replace"))
        return "250 OK"

    def codigo_para(self, email: str) -> str:
        for _ in range(50):
            for crudo in reversed(self.mensajes):
                mensaje = message_from_string(crudo, policy=policy.default)
                if mensaje["To"] == email:
                    return re.search(r"\b(\d{6})\b", mensaje.get_content()).group(1)
            time.sleep(0.1)
        raise AssertionError(f"no llegó correo a {email}")


@pytest.fixture(scope="module")
def buzon_smtp():
    buzon = _Buzon()
    controlador = Controller(buzon, hostname="127.0.0.1", port=_puerto_libre())
    controlador.start()
    yield buzon, controlador.port
    controlador.stop()


@pytest.fixture(scope="module")
def servidor(tmp_path_factory, buzon_smtp):
    _, puerto_smtp = buzon_smtp
    cert, clave = _certificado(tmp_path_factory.mktemp("tls"))
    puerto = _puerto_libre()
    entorno = {**os.environ, "ENTORNO": "pruebas", "SMTP_HOST": "127.0.0.1", "SMTP_PORT": str(puerto_smtp)}
    proceso = subprocess.Popen(  # noqa: S603 (comando fijo, sin entrada externa)
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(puerto),
            "--ssl-certfile",
            str(cert),
            "--ssl-keyfile",
            str(clave),
            "--no-server-header",
            "--log-level",
            "warning",
        ],
        cwd=RAIZ,
        env=entorno,
    )
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", puerto), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    yield puerto
    proceso.terminate()
    proceso.wait(timeout=10)


@pytest.fixture(scope="module")
def navegador():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture
def pagina(navegador):
    contexto = navegador.new_context(ignore_https_errors=True)  # certificado autofirmado de la prueba
    yield contexto.new_page()
    contexto.close()
