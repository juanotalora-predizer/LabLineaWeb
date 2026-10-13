"""Resolución del laboratorio (tenant) a partir del subdominio (spec infraestructura/0005).

El laboratorio se determina SOLO por la cabecera Host, ya validada por TrustedHostMiddleware.
Ningún parámetro, cookie ni cabecera enviada por el cliente puede cambiarlo.

    lab-a.<dominio>  → laboratorio con subdominio "lab-a"
    admin.<dominio>  → Admin Hub (sin laboratorio)
    <dominio>        → sin laboratorio
    otro subdominio  → 404
"""

import re
from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException, Request
from sqlalchemy import text
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core import db
from app.core.config import get_settings

SUBDOMINIO_ADMIN = "admin"
# Misma regla que el CHECK de plataforma.laboratorios: una etiqueta DNS en minúsculas.
_ETIQUETA = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
# Rutas que no necesitan saber el laboratorio (y no deben consultar la base en cada petición).
_SIN_RESOLUCION = ("/static/", "/health")


@dataclass(frozen=True)
class Laboratorio:
    tenant_id: str
    nombre_comercial: str
    pais: str
    estado: Literal["ACTIVO", "SUSPENDIDO"]
    zona_horaria: str
    idioma: str
    moneda: str


def extraer_subdominio(host: str, dominio_base: str) -> str | None:
    """Devuelve el subdominio de primer nivel, "" para el dominio base o None si no es válido."""
    nombre = host.split(":", 1)[0].lower()
    if nombre == dominio_base:
        return ""
    sufijo = "." + dominio_base
    if not nombre.endswith(sufijo):
        return None
    etiqueta = nombre[: -len(sufijo)]
    # Una sola etiqueta: "x.lab-a.<dominio>" no es un laboratorio.
    if "." in etiqueta or not _ETIQUETA.match(etiqueta):
        return None
    return etiqueta


async def buscar_laboratorio(subdominio: str) -> Laboratorio | None:
    async with db.engine_app().connect() as conexion:
        fila = (
            (await conexion.execute(text("SELECT * FROM acceso.resolver_laboratorio(:s)"), {"s": subdominio}))
            .mappings()
            .first()
        )
    return Laboratorio(**fila) if fila else None


class ResolverLaboratorio:
    """Middleware ASGI: deja en scope["state"] el laboratorio y el tipo de sitio de la petición."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"].startswith(_SIN_RESOLUCION):
            await self.app(scope, receive, send)
            return

        host = dict(scope["headers"]).get(b"host", b"").decode("latin-1")
        subdominio = extraer_subdominio(host, get_settings().dominio_base)
        estado = scope.setdefault("state", {})

        if subdominio is None:
            await _no_encontrado(scope, receive, send)
            return
        if subdominio in ("", SUBDOMINIO_ADMIN):
            estado["sitio"] = "admin" if subdominio else "raiz"
            estado["laboratorio"] = None
        else:
            laboratorio = await buscar_laboratorio(subdominio)
            if laboratorio is None:
                await _no_encontrado(scope, receive, send)
                return
            estado["sitio"] = "laboratorio"
            estado["laboratorio"] = laboratorio

        await self.app(scope, receive, send)


async def _no_encontrado(scope: Scope, receive: Receive, send: Send) -> None:
    # Mismo 404 para subdominio inexistente, cancelado o mal formado: no revela cuáles existen.
    await PlainTextResponse("No encontrado", status_code=404)(scope, receive, send)


def laboratorio_actual(request: Request) -> Laboratorio:
    """Dependencia para rutas del laboratorio: 404 si la petición no es de un laboratorio."""
    laboratorio = getattr(request.state, "laboratorio", None)
    if laboratorio is None:
        raise HTTPException(status_code=404)
    return laboratorio
