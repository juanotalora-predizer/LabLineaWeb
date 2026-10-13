"""Sesiones, CSRF y permisos en la capa web (spec infraestructura/0008).

- Cookies con prefijo __Host-: solo HTTPS, sin atributo Domain y con Path=/. Un subdominio
  hermano (otro laboratorio u otro sitio de cionetworks.com) no puede leerlas ni plantarlas.
- CSRF de doble envío: el formulario lleva el mismo token que la cookie __Host-csrf, y además
  se exige que Origin (si viene) sea el propio sitio.
"""

import ipaddress
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import AfterValidator
from sqlalchemy import text

from app.auth import repositorio
from app.auth.repositorio import Permisos, Usuario
from app.core import cripto
from app.core.auditoria import registrar_acceso
from app.core.config import get_settings
from app.core.db import sesion_plataforma, sesion_tenant
from app.core.i18n import t
from app.core.plantillas import templates
from app.core.tenancy import Laboratorio, Sitio, laboratorio_actual, sitio_actual

COOKIE_SESION = "__Host-sesion"
COOKIE_CSRF = "__Host-csrf"


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
        raise HTTPException(status_code=403, detail=t("error.origen_no_permitido"))
    if request.headers.get("sec-fetch-site") not in (None, "same-origin", "none"):
        raise HTTPException(status_code=403, detail=t("error.origen_no_permitido"))
    cookie = request.cookies.get(COOKIE_CSRF, "")
    if not cookie or not csrf or not cripto.comparar(cookie, csrf):
        raise HTTPException(status_code=403, detail=t("error.csrf_invalido"))


Csrf = Annotated[None, Depends(verificar_csrf)]


def _sin_caracteres_de_control(valor: str) -> str:
    """Rechaza caracteres de control (incluido el nulo, que PostgreSQL no admite en texto)."""
    if any(ord(c) < 32 or ord(c) == 127 for c in valor):
        raise ValueError("caracteres no permitidos")
    return valor


# Texto de formulario apto para la base de datos; si no lo es, la petición termina en 400 genérico.
TextoSeguro = Annotated[str, AfterValidator(_sin_caracteres_de_control)]
LaboratorioActual = Annotated[Laboratorio, Depends(laboratorio_actual)]
SitioActual = Annotated[Sitio, Depends(sitio_actual)]


def sesion_del_sitio(sitio: Sitio, *, usuario_id: str | None = None, ip: str | None = None):
    """Transacción del sitio: el laboratorio (rol de la aplicación, bajo RLS) o el Admin Hub (rol de plataforma)."""
    if sitio.tenant_id:
        return sesion_tenant(sitio.tenant_id, usuario_id=usuario_id, ip=ip)
    return sesion_plataforma(usuario_id=usuario_id, ip=ip)


# --- Sesión del usuario ---


@dataclass(frozen=True)
class SesionActiva:
    sesion_id: int
    usuario: Usuario
    permisos: Permisos
    segundo_factor_ok: bool


def _limitar_al_plan(permisos: Permisos, sitio: Sitio) -> Permisos:
    """En un laboratorio, los módulos fuera de su plan no otorgan ningún permiso (403 y fuera del menú)."""
    if not isinstance(sitio, Laboratorio):
        return permisos
    modulos = {m: ops for m, ops in permisos.modulos.items() if m in sitio.modulos}
    return Permisos(permisos.roles, modulos, permisos.acciones)


async def _cargar_sesion(request: Request, sitio: Sitio) -> SesionActiva | None:
    if hasattr(request.state, "sesion_activa"):
        return request.state.sesion_activa
    token = request.cookies.get(COOKIE_SESION)
    activa = None
    if token and len(token) <= 128:
        settings = get_settings()
        async with sesion_del_sitio(sitio, ip=ip_cliente(request)) as sesion:
            fila = await repositorio.obtener_sesion(sesion, token, settings.sesion_inactividad_min)
            if fila:
                usuario = await repositorio.buscar_usuario(sesion, fila.usuario_id)
                permisos = _limitar_al_plan(await repositorio.cargar_permisos(sesion, fila.usuario_id), sitio)
                activa = SesionActiva(fila.id, usuario, permisos, fila.segundo_factor_ok)
    request.state.sesion_activa = activa
    return activa


async def sesion_pendiente(request: Request, sitio: SitioActual) -> SesionActiva:
    """Sesión con contraseña verificada y segundo factor pendiente."""
    activa = await _cargar_sesion(request, sitio)
    if activa is None or activa.segundo_factor_ok:
        raise NoAutenticado
    return activa


async def sesion_completa(request: Request, sitio: SitioActual) -> SesionActiva:
    """Sesión con ambos factores, sin exigir inscripción de TOTP (la usa la propia inscripción)."""
    activa = await _cargar_sesion(request, sitio)
    if activa is None:
        raise NoAutenticado
    if not activa.segundo_factor_ok:
        raise SegundoFactorPendiente
    return activa


_SQL_SOPORTE_VIGENTE = text(
    "SELECT EXISTS (SELECT 1 FROM lab.accesos_soporte WHERE revocado_en IS NULL AND inicio <= now() AND fin > now())"
)


async def usuario_actual(
    request: Request, sitio: SitioActual, activa: Annotated[SesionActiva, Depends(sesion_completa)]
) -> SesionActiva:
    """Usuario autenticado y en regla: el personal debe tener su app autenticadora inscrita.

    Cada petición del soporte de la plataforma dentro de un laboratorio queda en su auditoría.
    """
    if activa.usuario.debe_inscribir_totp:
        raise InscripcionTotpPendiente
    if activa.usuario.tipo == "SOPORTE":
        async with sesion_del_sitio(sitio, usuario_id=activa.usuario.uuid, ip=ip_cliente(request)) as sesion:
            # Defensa adicional: la sesión vence con la autorización, pero se verifica en cada petición.
            vigente = await sesion.scalar(_SQL_SOPORTE_VIGENTE)
            if not vigente:
                await repositorio.revocar_sesion(sesion, activa.sesion_id)
            await registrar_acceso(
                sesion,
                "soporte",
                operacion="ACCESO",
                denegado=not vigente,
                detalle={"metodo": request.method, "ruta": request.url.path},
            )
        if not vigente:
            raise NoAutenticado
    return activa


UsuarioActual = Annotated[SesionActiva, Depends(usuario_actual)]


async def _denegar(request: Request, sitio: Sitio, activa: SesionActiva, recurso: str, permiso: str) -> HTTPException:
    """Registra el acceso denegado en la auditoría (HIPAA: también se auditan los intentos) y devuelve el 403."""
    async with sesion_del_sitio(sitio, usuario_id=activa.usuario.uuid, ip=ip_cliente(request)) as sesion:
        await registrar_acceso(sesion, recurso, operacion="ACCESO", denegado=True, detalle={"permiso": permiso})
    return HTTPException(status_code=403)


def requiere_permiso(modulo: str, operacion: str) -> Callable:
    async def dependencia(request: Request, sitio: SitioActual, activa: UsuarioActual) -> SesionActiva:
        if not activa.permisos.puede(modulo, operacion):
            raise await _denegar(request, sitio, activa, f"modulo:{modulo}", f"{modulo}.{operacion}")
        return activa

    return dependencia


async def requiere_suscripcion_vigente(request: Request, laboratorio: LaboratorioActual, activa: UsuarioActual) -> None:
    """Para crear órdenes nuevas (y toda operación que la spec funcional/0005 condicione a la suscripción).

    Nunca se usa en la consulta de resultados ni en la exportación de datos: esas siguen disponibles.
    """
    if not laboratorio.suscripcion_vigente:
        raise await _denegar(request, laboratorio, activa, "suscripcion", laboratorio.suscripcion_estado)


SuscripcionVigente = Annotated[None, Depends(requiere_suscripcion_vigente)]


def requiere_accion(accion: str) -> Callable:
    async def dependencia(request: Request, sitio: SitioActual, activa: UsuarioActual) -> SesionActiva:
        # Validar resultados exige además tarjeta profesional registrada (spec infraestructura/0008).
        sin_tarjeta = accion == "VALIDAR_RESULTADOS" and not activa.usuario.tarjeta_profesional
        if accion not in activa.permisos.acciones or sin_tarjeta:
            raise await _denegar(request, sitio, activa, f"accion:{accion}", accion)
        return activa

    return dependencia
