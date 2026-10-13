"""Criptografía y correo (spec infraestructura/0003)."""

import socket

import pytest
from aiosmtpd.controller import Controller
from cryptography.exceptions import InvalidTag

from app.core import correo, cripto
from app.core.config import get_settings
from tests.conftest import ENVIO_REAL


def test_cifrado_ida_y_vuelta():
    blob = cripto.cifrar(b"secreto-totp", "lab_a:u1:totp")
    assert b"secreto-totp" not in blob
    assert cripto.descifrar(blob, "lab_a:u1:totp") == b"secreto-totp"


def test_cifrado_ligado_al_contexto():
    blob = cripto.cifrar(b"secreto-totp", "lab_a:u1:totp")
    with pytest.raises(InvalidTag):
        cripto.descifrar(blob, "lab_a:u2:totp")  # otro usuario
    with pytest.raises(InvalidTag):
        cripto.descifrar(blob[:-1] + bytes([blob[-1] ^ 1]), "lab_a:u1:totp")  # alterado


def test_cifrado_no_determinista():
    assert cripto.cifrar(b"x", "c") != cripto.cifrar(b"x", "c")


def test_hmac_depende_del_contexto_y_de_la_subclave():
    assert cripto.hmac_valor("123456", "a") == cripto.hmac_valor("123456", "a")
    assert cripto.hmac_valor("123456", "a") != cripto.hmac_valor("123456", "b")


def test_clave_maestra_invalida(monkeypatch):
    monkeypatch.setenv("CLAVE_CIFRADO", "Y29ydGE=")  # "corta"
    get_settings.cache_clear()
    cripto.limpiar_cache()
    try:
        with pytest.raises(ValueError, match="32 bytes"):
            cripto.cifrar(b"x", "c")
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
        cripto.limpiar_cache()


def test_token_y_hash():
    token = cripto.token_aleatorio()
    assert len(token) >= 43
    assert len(cripto.hash_token(token)) == 32
    assert cripto.comparar("abc", "abc") and not cripto.comparar("abc", "abd")


class _Capturador:
    def __init__(self):
        self.mensajes = []

    async def handle_DATA(self, server, session, envelope):  # noqa: N802 (API de aiosmtpd)
        self.mensajes.append(envelope)
        return "250 OK"


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def smtp_local(monkeypatch):
    capturador = _Capturador()
    controlador = Controller(capturador, hostname="127.0.0.1", port=_puerto_libre())
    controlador.start()
    monkeypatch.setenv("SMTP_PORT", str(controlador.port))
    get_settings.cache_clear()
    yield capturador
    controlador.stop()
    monkeypatch.undo()
    get_settings.cache_clear()


@pytest.mark.anyio
async def test_envio_real_por_smtp(smtp_local, monkeypatch):
    # El conftest reemplaza el envío por una lista; aquí se usa el envío real contra el SMTP local.
    monkeypatch.setattr(correo, "_enviar_sync", ENVIO_REAL)
    await correo.enviar("paciente@lab-a.test", "Código de verificación", "Su código es 123456.")
    assert len(smtp_local.mensajes) == 1
    sobre = smtp_local.mensajes[0]
    assert sobre.rcpt_tos == ["paciente@lab-a.test"]
    assert b"123456" in sobre.content


@pytest.mark.anyio
async def test_sin_inyeccion_de_cabeceras_en_el_destinatario():
    with pytest.raises(ValueError):
        await correo.enviar("paciente@lab-a.test\nBcc: atacante@example.com", "Asunto", "Cuerpo")
