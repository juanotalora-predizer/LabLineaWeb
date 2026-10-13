"""Primitivas criptográficas (spec infraestructura/0003).

Una sola clave maestra (CLAVE_CIFRADO, 32 bytes) de la que se derivan subclaves por propósito
con HKDF: nunca se usa la misma clave para cifrar y para HMAC.
"""

import base64
import hashlib
import hmac
import os
import secrets
from functools import lru_cache

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import get_settings

_NONCE = 12


def _clave_maestra() -> bytes:
    clave = base64.b64decode(get_settings().clave_cifrado.get_secret_value(), validate=True)
    if len(clave) != 32:
        raise ValueError("CLAVE_CIFRADO debe tener 32 bytes en base64")
    return clave


@lru_cache
def _subclave(proposito: str) -> bytes:
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=f"lablinea:{proposito}".encode())
    return hkdf.derive(_clave_maestra())


def limpiar_cache() -> None:
    _subclave.cache_clear()


def cifrar(datos: bytes, contexto: str) -> bytes:
    """AES-256-GCM. El contexto (p. ej. tenant y usuario) va como dato asociado: un texto
    cifrado no se puede mover a otro usuario sin que falle el descifrado."""
    nonce = os.urandom(_NONCE)
    return nonce + AESGCM(_subclave("cifrado")).encrypt(nonce, datos, contexto.encode())


def descifrar(blob: bytes, contexto: str) -> bytes:
    return AESGCM(_subclave("cifrado")).decrypt(blob[:_NONCE], blob[_NONCE:], contexto.encode())


def hmac_valor(valor: str, contexto: str) -> bytes:
    """HMAC-SHA256 para guardar códigos y claves de límites sin poder revertirlos."""
    return hmac.new(_subclave("hmac"), f"{contexto}\x00{valor}".encode(), hashlib.sha256).digest()


def token_aleatorio() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> bytes:
    """Las sesiones se guardan por el SHA-256 del token: una copia de la base no da sesiones válidas."""
    return hashlib.sha256(token.encode()).digest()


def comparar(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
