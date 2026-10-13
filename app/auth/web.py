"""Sesiones, CSRF y permisos en la capa web (spec infraestructura/0008).

- Cookies con prefijo __Host-: solo HTTPS, sin atributo Domain y con Path=/. Un subdominio
  hermano (otro laboratorio u otro sitio de cionetworks.com) no puede leerlas ni plantarlas.
- CSRF de doble envío: el formulario lleva el mismo token que la cookie __Host-csrf, y además
  se exige que Origin (si viene) sea el propio sitio.
"""

import ipaddress
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import AfterValidator

from app.auth import repositorio
from app.auth.repositorio import Permisos, Usuario
from app.core import cripto
from app.core.config import get_settings
from app.core.db import sesion_tenant
from app.core.tenancy import Laboratorio, laboratorio_actual

COOKIE_SESION = "__Host-sesion"
COOKIE_CSRF = "__Host-csrf"

templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")


# --- Excepciones que se convierten en respuestas (ver app/main.py) ---


class NoAutenticado(Exception):  # noqa: N818
    """Sin sesión válida: se redirige a /ingresar."""


class SegundoFactorPendiente(Exception):  # noqa: N818
    """Contraseña correcta pero falta el segundo factor: se redirige a /verificar."""


class InscripcionTotpPendiente(Exception):  # noqa: N818
    """Personal sin app autenticadora: debe inscribirla antes de continuar."""


# --- Utilidades de petición y respuesta ---


def ip_cliente(request: Request) -> str | None:
    """IP del cliente, solo si es una dirección válida (se guarda en columnas inet)."""
    if not request.client:
        return None
    try:
        return str(ipaddress.ip_address(request.client.host))
    except ValueError:
        return None


def poner_cookie_sesion(respuesta, token: str) -> None:
    respuesta.set_cookie(COOKIE_SESION, token, secure=True, httponly=True, samesite="lax", path="/")


def borrar_cookie_sesion(respuesta) -> None:
    respuesta.delete_cookie(COOKIE_SESION, secure=True, httponly=True, samesite="lax", path="/")


def token_csrf(request: Request) -> str:
    """Token CSRF de la petición: el de la cookie o uno nuevo (que `render` pone en la cookie)."""
    if not hasattr(request.state, "csrf"):
        actual = request.cookies.get(COOKIE_CSRF)
        request.state.csrf = actual if actual and len(actual) >= 32 else cripto.token_aleatorio()
    return request.state.csrf


def rotar_csrf(request: Request) -> None:
    request.state.csrf = cripto.token_aleatorio()


def render(request: Request, plantilla: str, contexto: dict[str, Any] | None = None, status_code: int = 200):
    datos = {"csrf": token_csrf(request), **(contexto or {})}
    respuesta = templates.TemplateResponse(request, plantilla, datos, status_code=status_code)
    respuesta.set_cookie(COOKIE_CSRF, request.state.csrf, secure=True, httponly=True, samesite="strict", path="/")
    return respuesta


def redirigir(request: Request, destino: str):
    respuesta = RedirectResponse(destino, status_code=303)
    if hasattr(request.state, "csrf"):
        respuesta.set_cookie(COOKIE_CSRF, request.state.csrf, secure=True, httponly=True, samesite="strict", path="/")
    return respuesta


async def verificar_csrf(request: Request, csrf: Annotated[str, Form(max_length=128)] = "") -> None:
    """Dependencia obligatoria de toda ruta que cambia estado (POST). Ver tests/test_csrf.py."""
    origen = request.headers.get("origin")
    propio = f"{request.url.scheme}://{request.headers.get('host', '')}"
    if origen is not None and origen != propio:
        raise HTTPException(status_code=403, detail="Origen no permitido")
    if request.headers.get("sec-fetch-site") not in (None, "same-origin", "none"):
        raise HTTPException(status_code=403, detail="Origen no permitido")
    cookie = request.cookies.get(COOKIE_CSRF, "")
    if not cookie or not csrf or not cripto.comparar(cookie, csrf):
        raise HTTPException(status_code=403, detail="Token CSRF inválido")


Csrf = Annotated[None, Depends(verificar_csrf)]


def _sin_caracteres_de_control(valor: str) -> str:
    """Rechaza caracteres de control (incluido el nulo, que PostgreSQL no admite en texto)."""
    if any(ord(c) < 32 or ord(c) == 127 for c in valor):
        raise ValueError("caracteres no permitidos")
    return valor


# Texto de formulario apto para la base de datos; si no lo es, la petición termina en 400 genérico.
TextoSeguro = Annotated[str, AfterValidator(_sin_caracteres_de_control)]
LaboratorioActual = Annotated[Laboratorio, Depends(laboratorio_actual)]


# --- Sesión del usuario ---


@dataclass(frozen=True)
class SesionActiva:
    sesion_id: int
    usuario: Usuario
    permisos: Permisos
    segundo_factor_ok: bool


async def _cargar_sesion(request: Request, laboratorio: Laboratorio) -> SesionActiva | None:
    if hasattr(request.state, "sesion_activa"):
        return request.state.sesion_activa
    token = request.cookies.get(COOKIE_SESION)
    activa = None
    if token and len(token) <= 128:
        settings = get_settings()
        async with sesion_tenant(laboratorio.tenant_id, ip=ip_cliente(request)) as sesion:
            fila = await repositorio.obtener_sesion(sesion, token, settings.sesion_inactividad_min)
            if fila:
                usuario = await repositorio.buscar_usuario(sesion, fila.usuario_id)
                permisos = await repositorio.cargar_permisos(sesion, fila.usuario_id)
                activa = SesionActiva(fila.id, usuario, permisos, fila.segundo_factor_ok)
    request.state.sesion_activa = activa
    return activa


async def sesion_pendiente(request: Request, laboratorio: LaboratorioActual) -> SesionActiva:
    """Sesión con contraseña verificada y segundo factor pendiente."""
    activa = await _cargar_sesion(request, laboratorio)
    if activa is None or activa.segundo_factor_ok:
        raise NoAutenticado
    return activa


async def sesion_completa(request: Request, laboratorio: LaboratorioActual) -> SesionActiva:
    """Sesión con ambos factores, sin exigir inscripción de TOTP (la usa la propia inscripción)."""
    activa = await _cargar_sesion(request, laboratorio)
    if activa is None:
        raise NoAutenticado
    if not activa.segundo_factor_ok:
        raise SegundoFactorPendiente
    return activa


async def usuario_actual(activa: Annotated[SesionActiva, Depends(sesion_completa)]) -> SesionActiva:
    """Usuario autenticado y en regla: el personal debe tener su app autenticadora inscrita."""
    if activa.usuario.debe_inscribir_totp:
        raise InscripcionTotpPendiente
    return activa


UsuarioActual = Annotated[SesionActiva, Depends(usuario_actual)]


def requiere_permiso(modulo: str, operacion: str) -> Callable:
    async def dependencia(activa: UsuarioActual) -> SesionActiva:
        if not activa.permisos.puede(modulo, operacion):
            raise HTTPException(status_code=403)
        return activa

    return dependencia


def requiere_accion(accion: str) -> Callable:
    async def dependencia(activa: UsuarioActual) -> SesionActiva:
        if accion not in activa.permisos.acciones:
            raise HTTPException(status_code=403)
        # Validar resultados exige además tarjeta profesional registrada (spec infraestructura/0008).
        if accion == "VALIDAR_RESULTADOS" and not activa.usuario.tarjeta_profesional:
            raise HTTPException(status_code=403)
        return activa

    return dependencia
