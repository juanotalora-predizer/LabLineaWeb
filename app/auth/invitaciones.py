"""Invitaciones: el usuario crea su propia contraseña con un enlace de un solo uso (spec infraestructura/0008).

Así nadie más (ni el personal de la plataforma que da de alta el laboratorio, ni el administrador que
invita a su equipo) conoce la contraseña. Flujo:

1. Se crea el usuario sin contraseña y se encola la tarea `auth.invitacion` (solo con el UUID del
   usuario y el subdominio del laboratorio).
2. La tarea genera el token, guarda su SHA-256 (vigencia 72 horas; invalida las invitaciones previas) y
   envía el enlace por correo. Si el correo falla, la transacción se revierte y la tarea se reintenta.
3. /activar/<token>: el usuario fija su contraseña; luego ingresa con ella y su segundo factor.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import contrasenas, repositorio
from app.auth.web import Csrf, LaboratorioActual, TextoSeguro, ip_cliente, redirigir, render, rotar_csrf
from app.core import correo, cripto
from app.core.config import get_settings
from app.core.db import sesion_tenant
from app.core.i18n import t
from app.core.tareas import ErrorPermanente, tarea
from app.core.tenancy import buscar_laboratorio

router = APIRouter(default_response_class=HTMLResponse)
log = logging.getLogger(__name__)

VIGENCIA_HORAS = 72
TIPO_TAREA = "auth.invitacion"

_SQL_PENDIENTE = text(
    "SELECT id, email::text AS email FROM lab.usuarios"
    " WHERE uuid = CAST(:u AS uuid) AND estado = 'ACTIVO' AND password_hash IS NULL"
)
_SQL_INVITACION_VIGENTE = text(
    "SELECT i.id AS invitacion_id, u.id AS usuario_id, u.email::text AS email"
    " FROM lab.invitaciones i JOIN lab.usuarios u ON u.id = i.usuario_id"
    " WHERE i.token_hash = :h AND i.usada_en IS NULL AND i.expira_en > now()"
    "   AND u.estado = 'ACTIVO' AND u.password_hash IS NULL"
)


@tarea(TIPO_TAREA)
async def enviar_invitacion(sesion: AsyncSession, datos: dict) -> None:
    laboratorio = await buscar_laboratorio(str(datos.get("subdominio", "")))
    tenant = await sesion.scalar(text("SELECT lab.tenant_actual()"))
    # El enlace usa el subdominio de los datos: debe ser el del laboratorio de la tarea.
    if laboratorio is None or laboratorio.tenant_id != tenant:
        raise ErrorPermanente("el subdominio no corresponde al laboratorio de la tarea")
    usuario = (await sesion.execute(_SQL_PENDIENTE, {"u": str(datos.get("usuario", ""))})).mappings().first()
    if usuario is None:
        raise ErrorPermanente("el usuario no existe o ya activó su cuenta")

    await sesion.execute(
        text("UPDATE lab.invitaciones SET usada_en = now() WHERE usuario_id = :u AND usada_en IS NULL"),
        {"u": usuario["id"]},
    )
    token = cripto.token_aleatorio()
    await sesion.execute(
        text(
            "INSERT INTO lab.invitaciones (usuario_id, token_hash, expira_en)"
            " VALUES (:u, :h, now() + make_interval(hours => :horas))"
        ),
        {"u": usuario["id"], "h": cripto.hash_token(token), "horas": VIGENCIA_HORAS},
    )
    enlace = f"{get_settings().url_sitio(laboratorio.subdominio)}/activar/{token}"
    idioma = laboratorio.idioma
    await correo.enviar(
        usuario["email"],
        t("invitacion.asunto", idioma, laboratorio=laboratorio.nombre_comercial),
        t("invitacion.cuerpo", idioma, laboratorio=laboratorio.nombre_comercial, enlace=enlace, horas=VIGENCIA_HORAS),
    )


def _token_valido(token: str) -> bool:
    return 32 <= len(token) <= 128


@router.get("/activar/{token}")
async def activar_formulario(request: Request, laboratorio: LaboratorioActual, token: str):
    vigente = None
    if _token_valido(token):
        async with sesion_tenant(laboratorio.tenant_id) as sesion:
            vigente = (await sesion.execute(_SQL_INVITACION_VIGENTE, {"h": cripto.hash_token(token)})).first()
    if vigente is None:
        return render(request, "auth/activar.html", {"sitio": laboratorio, "invalido": True}, 404)
    return render(request, "auth/activar.html", {"sitio": laboratorio, "token": token})


@router.post("/activar/{token}")
async def activar(
    request: Request,
    laboratorio: LaboratorioActual,
    _csrf: Csrf,
    token: str,
    clave: Annotated[TextoSeguro, Form(max_length=1024)] = "",
    confirmacion: Annotated[TextoSeguro, Form(max_length=1024)] = "",
):
    idioma = laboratorio.idioma
    errores: list[str] = []
    activada = False
    if _token_valido(token):
        async with sesion_tenant(laboratorio.tenant_id, ip=ip_cliente(request)) as sesion:
            vigente = (
                (await sesion.execute(_SQL_INVITACION_VIGENTE, {"h": cripto.hash_token(token)})).mappings().first()
            )
            if vigente is not None:
                errores = contrasenas.validar_politica(clave, vigente["email"], idioma)
                if clave != confirmacion:
                    errores.append(t("contrasena.no_coinciden", idioma))
                if not errores:
                    await repositorio.actualizar_hash(sesion, vigente["usuario_id"], contrasenas.hashear(clave))
                    await sesion.execute(
                        text("UPDATE lab.invitaciones SET usada_en = now() WHERE id = :i"),
                        {"i": vigente["invitacion_id"]},
                    )
                    await repositorio.registrar_evento(
                        sesion, "CUENTA_ACTIVADA", usuario_id=vigente["usuario_id"], ip=ip_cliente(request)
                    )
                    activada = True
    if activada:
        rotar_csrf(request)
        return redirigir(request, "/ingresar?activada=1")
    if not errores:
        return render(request, "auth/activar.html", {"sitio": laboratorio, "invalido": True}, 404)
    contexto = {"sitio": laboratorio, "token": token, "errores": errores}
    return render(request, "auth/activar.html", contexto, 400)
