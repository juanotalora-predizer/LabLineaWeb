"""Contraseñas con Argon2id (spec infraestructura/0008)."""

import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.i18n import t

# Parámetros por defecto de argon2-cffi: perfil "low memory" de RFC 9106 (Argon2id, t=3, m=64 MiB, p=4).
_hasher = PasswordHasher()

LONGITUD_MINIMA = 12
LONGITUD_MAXIMA = 128  # limita el costo de calcular el hash de entradas enormes

# Hash de una contraseña aleatoria: se verifica contra él cuando el usuario no existe,
# para que el tiempo de respuesta no revele si un correo está registrado.
_HASH_FICTICIO = _hasher.hash(secrets.token_urlsafe(16))


def validar_politica(clave: str, email: str = "", idioma: str | None = None) -> list[str]:
    """Mensajes (en el idioma del sitio) de las reglas que la contraseña no cumple."""
    errores = []
    if len(clave) < LONGITUD_MINIMA:
        errores.append(t("contrasena.corta", idioma, minimo=LONGITUD_MINIMA))
    if len(clave) > LONGITUD_MAXIMA:
        errores.append(t("contrasena.larga", idioma, maximo=LONGITUD_MAXIMA))
    if len(set(clave)) < 5:
        errores.append(t("contrasena.variedad", idioma))
    usuario = email.split("@", 1)[0].lower()
    if len(usuario) >= 4 and usuario in clave.lower():
        errores.append(t("contrasena.correo", idioma))
    return errores


def hashear(clave: str, email: str = "") -> str:
    errores = validar_politica(clave, email)
    if errores:
        raise ValueError(" ".join(errores))
    return _hasher.hash(clave)


def verificar(hash_guardado: str | None, clave: str) -> bool:
    """Siempre calcula un Argon2 (también si el usuario no existe o la clave es demasiado larga)."""
    real = hash_guardado is not None and len(clave) <= LONGITUD_MAXIMA
    try:
        coincide = _hasher.verify(hash_guardado if real else _HASH_FICTICIO, clave[:LONGITUD_MAXIMA])
    except VerifyMismatchError, VerificationError, InvalidHashError:
        coincide = False
    return real and coincide


def necesita_rehash(hash_guardado: str) -> bool:
    return _hasher.check_needs_rehash(hash_guardado)
