"""Rutas de autenticación del laboratorio (spec infraestructura/0008).

Flujo: /ingresar (correo + contraseña) → /verificar (TOTP o código por correo) → /panel.
El personal sin app autenticadora la inscribe en /seguridad/totp antes de continuar.
"""

import logging
import time
from typing import Annotated

import pyotp
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import text

from app.auth import contrasenas, repositorio
from app.auth.web import (
    COOKIE_SESION,
    Csrf,
    LaboratorioActual,
    SesionActiva,
    TextoSeguro,
    UsuarioActual,
    _cargar_sesion,
    borrar_cookie_sesion,
    ip_cliente,
    poner_cookie_sesion,
    redirigir,
    render,
    requiere_permiso,
    rotar_csrf,
    sesion_completa,
    sesion_pendiente,
)
from app.core import correo, cripto
from app.core.auditoria import registrar_acceso
from app.core.config import get_settings
from app.core.db import sesion_tenant
from app.core.i18n import t

# Todas las rutas responden HTML (o redirecciones).
router = APIRouter(default_response_class=HTMLResponse)
log = logging.getLogger(__name__)

VENTANA_MIN = 15
MAX_INTENTOS_POR_IP = 100  # todo el personal de un laboratorio suele compartir IP
MAX_FALLOS_POR_CORREO = 5
MAX_FALLOS_SEGUNDO_FACTOR = 5


def _clave_limite(tipo: str, valor: str) -> str:
    # Las claves de límites no guardan correos ni IP en claro.
    return f"{tipo}:{cripto.hmac_valor(valor, 'limite:' + tipo).hex()}"


async def _enviar_codigo(laboratorio, usuario, codigo: str) -> bool:
    """Envía el código; si el correo falla devuelve False (nunca un error 500). El log no lleva el código."""
    try:
        await _enviar(laboratorio, usuario, codigo)
    except OSError:
        log.warning("Fallo al enviar código de verificación (laboratorio %s)", laboratorio.tenant_id)
        return False
    return True


async def _enviar(laboratorio, usuario, codigo: str) -> None:
    idioma = laboratorio.idioma
    await correo.enviar(
        usuario.email,
        t("auth.correo_codigo.asunto", idioma),
        t(
            "auth.correo_codigo.cuerpo",
            idioma,
            laboratorio=laboratorio.nombre_comercial,
            codigo=codigo,
            minutos=repositorio.CODIGO_VIGENCIA_MIN,
        ),
    )


def _verificar_totp(usuario, codigo: str) -> int | None:
    """Devuelve el contador del intervalo que coincide (±1 intervalo de 30 s), o None."""
    if not usuario.totp_secreto_cifrado or not codigo.isdigit():
        return None
    secreto = cripto.descifrar(bytes(usuario.totp_secreto_cifrado), usuario.contexto_totp()).decode()
    totp = pyotp.TOTP(secreto)
    ahora = time.time()
    for desfase in (-30, 0, 30):
        if cripto.comparar(totp.at(ahora + desfase), codigo):
            return int((ahora + desfase) // totp.interval)
    return None


# --- Ingreso ---


@router.get("/ingresar")
async def ingresar_formulario(request: Request, laboratorio: LaboratorioActual):
    return render(request, "auth/ingresar.html", {"laboratorio": laboratorio})


@router.post("/ingresar")
async def ingresar(
    request: Request,
    laboratorio: LaboratorioActual,
    _csrf: Csrf,
    email: Annotated[TextoSeguro, Form(max_length=254)] = "",
    clave: Annotated[TextoSeguro, Form(max_length=1024)] = "",
):
    settings = get_settings()
    ip = ip_cliente(request)
    email = email.strip().lower()
    error, estado, token, codigo, usuario = None, 400, None, None, None

    async with sesion_tenant(laboratorio.tenant_id, ip=ip) as sesion:
        if await repositorio.limite_sumar(sesion, _clave_limite("ingreso-ip", ip or ""), VENTANA_MIN) > (
            MAX_INTENTOS_POR_IP
        ):
            await repositorio.registrar_evento(sesion, "INGRESO_LIMITADO_IP", email=email or None, ip=ip)
            error, estado = t("auth.error_demasiados", laboratorio.idioma), 429
        else:
            clave_correo = _clave_limite("ingreso-correo", email)
            bloqueado = await repositorio.limite_contar(sesion, clave_correo, VENTANA_MIN) >= MAX_FALLOS_POR_CORREO
            usuario = await repositorio.buscar_usuario_por_email(sesion, email)
            correcta = contrasenas.verificar(usuario.password_hash if usuario else None, clave)
            if bloqueado or not correcta:
                fallos = await repositorio.limite_sumar(sesion, clave_correo, VENTANA_MIN)
                usuario_id = usuario.id if usuario else None
                await repositorio.registrar_evento(
                    sesion, "INGRESO_FALLIDO", usuario_id=usuario_id, email=email or None, ip=ip
                )
                if fallos == MAX_FALLOS_POR_CORREO and usuario:
                    await repositorio.marcar_bloqueo(sesion, usuario.id, VENTANA_MIN)
                    await repositorio.registrar_evento(sesion, "CUENTA_BLOQUEADA", usuario_id=usuario.id, ip=ip)
                # Mismo mensaje si el correo no existe, la contraseña falla o la cuenta está bloqueada.
                error = t("auth.error_credenciales", laboratorio.idioma)
            else:
                await repositorio.limite_reiniciar(sesion, clave_correo)
                if contrasenas.necesita_rehash(usuario.password_hash):
                    await repositorio.actualizar_hash(sesion, usuario.id, contrasenas.hashear(clave))
                token = await repositorio.crear_sesion(
                    sesion,
                    usuario.id,
                    segundo_factor_ok=False,
                    minutos=settings.sesion_pendiente_min,
                    ip=ip,
                    agente=request.headers.get("user-agent", "")[:300],
                )
                if not usuario.usa_totp:
                    codigo = await repositorio.crear_codigo(sesion, usuario)
                await repositorio.registrar_evento(sesion, "CONTRASENA_CORRECTA", usuario_id=usuario.id, ip=ip)

    if error:
        return render(
            request, "auth/ingresar.html", {"laboratorio": laboratorio, "error": error, "email": email}, estado
        )
    if codigo:
        await _enviar_codigo(laboratorio, usuario, codigo)
    rotar_csrf(request)
    respuesta = redirigir(request, "/verificar")
    poner_cookie_sesion(respuesta, token)
    return respuesta


# --- Segundo factor ---


def _contexto_verificar(laboratorio, usuario) -> dict:
    return {
        "laboratorio": laboratorio,
        "usa_totp": usuario.usa_totp,
        "vigencia_min": repositorio.CODIGO_VIGENCIA_MIN,
    }


@router.get("/verificar")
async def verificar_formulario(
    request: Request, laboratorio: LaboratorioActual, pendiente: Annotated[SesionActiva, Depends(sesion_pendiente)]
):
    return render(request, "auth/verificar.html", _contexto_verificar(laboratorio, pendiente.usuario))


@router.post("/verificar")
async def verificar(
    request: Request,
    laboratorio: LaboratorioActual,
    _csrf: Csrf,
    pendiente: Annotated[SesionActiva, Depends(sesion_pendiente)],
    codigo: Annotated[TextoSeguro, Form(max_length=12)] = "",
):
    settings = get_settings()
    ip = ip_cliente(request)
    usuario = pendiente.usuario
    codigo = codigo.strip()
    token, error, estado = None, t("auth.error_codigo", laboratorio.idioma), 400

    async with sesion_tenant(laboratorio.tenant_id, usuario_id=usuario.uuid, ip=ip) as sesion:
        intentos = await repositorio.limite_sumar(sesion, f"segundo-factor:{usuario.id}", VENTANA_MIN)
        correcto = False
        if intentos > MAX_FALLOS_SEGUNDO_FACTOR:
            error, estado = t("auth.error_demasiados", laboratorio.idioma), 429
        else:
            contador = _verificar_totp(usuario, codigo) if usuario.usa_totp else None
            if contador is not None:
                correcto = await repositorio.registrar_contador_totp(sesion, usuario.id, contador)
            else:
                # Código por correo: método principal de pacientes y médicos, respaldo del personal.
                correcto = await repositorio.verificar_codigo(sesion, usuario, codigo)
        if correcto:
            await repositorio.limite_reiniciar(sesion, f"segundo-factor:{usuario.id}")
            # Token nuevo al completar el ingreso: un token conocido antes del ingreso no sirve (fijación de sesión).
            await repositorio.revocar_sesion(sesion, pendiente.sesion_id)
            token = await repositorio.crear_sesion(
                sesion,
                usuario.id,
                segundo_factor_ok=True,
                minutos=settings.sesion_maxima_horas * 60,
                ip=ip,
                agente=request.headers.get("user-agent", "")[:300],
            )
            await repositorio.registrar_evento(sesion, "INGRESO_EXITOSO", usuario_id=usuario.id, ip=ip)
        else:
            await repositorio.registrar_evento(sesion, "SEGUNDO_FACTOR_FALLIDO", usuario_id=usuario.id, ip=ip)

    if token is None:
        contexto = {**_contexto_verificar(laboratorio, usuario), "error": error}
        return render(request, "auth/verificar.html", contexto, estado)
    rotar_csrf(request)
    respuesta = redirigir(request, "/seguridad/totp" if usuario.debe_inscribir_totp else "/panel")
    poner_cookie_sesion(respuesta, token)
    return respuesta


@router.post("/verificar/reenviar")
async def reenviar_codigo(
    request: Request,
    laboratorio: LaboratorioActual,
    _csrf: Csrf,
    pendiente: Annotated[SesionActiva, Depends(sesion_pendiente)],
):
    async with sesion_tenant(laboratorio.tenant_id, usuario_id=pendiente.usuario.uuid) as sesion:
        codigo = await repositorio.crear_codigo(sesion, pendiente.usuario)
    contexto = _contexto_verificar(laboratorio, pendiente.usuario)
    idioma = laboratorio.idioma
    if codigo is None:
        return render(request, "auth/verificar.html", {**contexto, "error": t("auth.error_demasiados", idioma)}, 429)
    if not await _enviar_codigo(laboratorio, pendiente.usuario, codigo):
        return render(request, "auth/verificar.html", {**contexto, "error": t("auth.error_correo", idioma)}, 503)
    return render(request, "auth/verificar.html", {**contexto, "aviso": t("auth.aviso_codigo_nuevo", idioma)})


# --- Inscripción de la app autenticadora (personal) ---


@router.get("/seguridad/totp")
async def totp_formulario(
    request: Request, laboratorio: LaboratorioActual, activa: Annotated[SesionActiva, Depends(sesion_completa)]
):
    usuario = activa.usuario
    if usuario.totp_confirmado:
        return redirigir(request, "/panel")
    if usuario.totp_secreto_cifrado:
        secreto = cripto.descifrar(bytes(usuario.totp_secreto_cifrado), usuario.contexto_totp()).decode()
    else:
        secreto = pyotp.random_base32()
        async with sesion_tenant(laboratorio.tenant_id, usuario_id=usuario.uuid) as sesion:
            await repositorio.guardar_totp(sesion, usuario, secreto)
    uri = pyotp.TOTP(secreto).provisioning_uri(
        name=usuario.email, issuer_name=f"LabLineaWeb {laboratorio.nombre_comercial}"
    )
    return render(request, "auth/totp.html", {"laboratorio": laboratorio, "secreto": secreto, "uri": uri})


@router.post("/seguridad/totp")
async def totp_confirmar(
    request: Request,
    laboratorio: LaboratorioActual,
    _csrf: Csrf,
    activa: Annotated[SesionActiva, Depends(sesion_completa)],
    codigo: Annotated[TextoSeguro, Form(max_length=12)] = "",
):
    # La sesión cargada al inicio de la petición puede no tener aún el secreto recién guardado.
    async with sesion_tenant(laboratorio.tenant_id, usuario_id=activa.usuario.uuid) as sesion:
        usuario = await repositorio.buscar_usuario(sesion, activa.usuario.id)
        contador = _verificar_totp(usuario, codigo.strip()) if usuario and not usuario.totp_confirmado else None
        if contador is not None:
            await repositorio.confirmar_totp(sesion, usuario.id, contador)
            await repositorio.registrar_evento(sesion, "TOTP_INSCRITO", usuario_id=usuario.id, ip=ip_cliente(request))
    if contador is None:
        return redirigir(request, "/seguridad/totp?error=1")
    return redirigir(request, "/panel")


# --- Salida ---


@router.post("/salir")
async def salir(request: Request, laboratorio: LaboratorioActual, _csrf: Csrf):
    activa = await _cargar_sesion(request, laboratorio)
    if activa:
        async with sesion_tenant(laboratorio.tenant_id, usuario_id=activa.usuario.uuid) as sesion:
            await repositorio.revocar_sesion(sesion, activa.sesion_id)
            await repositorio.registrar_evento(sesion, "SALIDA", usuario_id=activa.usuario.id, ip=ip_cliente(request))
    rotar_csrf(request)
    respuesta = redirigir(request, "/ingresar")
    borrar_cookie_sesion(respuesta)
    return respuesta


# --- Páginas autenticadas ---


@router.get("/panel")
async def panel(request: Request, laboratorio: LaboratorioActual, activa: UsuarioActual):
    return render(request, "panel/panel.html", {"laboratorio": laboratorio, "activa": activa})


@router.get("/configuracion/usuarios")
async def lista_usuarios(
    request: Request,
    laboratorio: LaboratorioActual,
    activa: Annotated[SesionActiva, Depends(requiere_permiso("usuarios", "consultar"))],
):
    async with sesion_tenant(laboratorio.tenant_id, usuario_id=activa.usuario.uuid, ip=ip_cliente(request)) as sesion:
        usuarios = (
            (
                await sesion.execute(
                    text(
                        "SELECT u.nombre, u.email::text AS email, u.tipo, u.estado,"
                        " coalesce(string_agg(r.codigo, ', ' ORDER BY r.codigo), '') AS roles"
                        " FROM lab.usuarios u LEFT JOIN lab.usuario_roles ur ON ur.usuario_id = u.id"
                        " LEFT JOIN lab.roles r ON r.id = ur.rol_id"
                        " GROUP BY u.id ORDER BY u.nombre"
                    )
                )
            )
            .mappings()
            .all()
        )
        # Datos personales del personal y de pacientes: la consulta queda auditada.
        await registrar_acceso(sesion, "usuarios", detalle={"vista": "lista_usuarios", "filas": len(usuarios)})
    contexto = {"laboratorio": laboratorio, "activa": activa, "usuarios": usuarios}
    return render(request, "panel/usuarios.html", contexto)


__all__ = ["COOKIE_SESION", "router"]
