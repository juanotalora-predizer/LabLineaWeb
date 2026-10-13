"""Acceso de soporte de la plataforma, autorizado por el laboratorio (spec infraestructura/0005).

- El laboratorio (acción AUTORIZAR_SOPORTE) autoriza el soporte por un tiempo limitado (máximo 72 horas)
  y con un motivo; puede revocarlo en cualquier momento, lo que cierra las sesiones de soporte.
- Con una autorización vigente, la plataforma emite un tiquete de un solo uso (2 minutos;
  plataforma.iniciar_soporte). En /soporte/entrar/<tiquete> la persona de soporte confirma y recibe una
  sesión del laboratorio con el rol SOPORTE (solo lectura) que vence con la autorización.
- La persona de soporte ya pasó su segundo factor en el Admin Hub. Cada petición suya queda auditada en
  el laboratorio (app.auth.web.usuario_actual).
"""

import math
import re
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import text

from app.auth import repositorio
from app.auth.web import (
    Csrf,
    LaboratorioActual,
    SesionActiva,
    TextoSeguro,
    ip_cliente,
    poner_cookie_sesion,
    redirigir,
    render,
    requiere_accion,
    rotar_csrf,
)
from app.core import cripto
from app.core.auditoria import registrar_acceso
from app.core.config import get_settings
from app.core.db import sesion_tenant
from app.core.i18n import t

router = APIRouter(default_response_class=HTMLResponse)
Autoriza = Annotated[SesionActiva, Depends(requiere_accion("AUTORIZAR_SOPORTE"))]
HORAS_MAXIMAS = 72

_SQL_ACCESOS = text(
    "SELECT a.uuid::text AS uuid, a.motivo, a.inicio, a.fin, a.revocado_en, u.nombre AS autorizado_por,"
    " (a.revocado_en IS NULL AND a.fin > now()) AS vigente"
    " FROM lab.accesos_soporte a JOIN lab.usuarios u ON u.id = a.autorizado_por ORDER BY a.inicio DESC LIMIT 50"
)
_SQL_TIQUETE = text(
    "SELECT t.id, t.usuario_id, u.uuid::text AS usuario_uuid, a.fin FROM lab.tickets_soporte t"
    " JOIN lab.accesos_soporte a ON a.id = t.acceso_id"
    " JOIN lab.usuarios u ON u.id = t.usuario_id"
    " WHERE t.token_hash = :h AND t.usado_en IS NULL AND t.expira_en > now()"
    "   AND a.revocado_en IS NULL AND a.fin > now() AND u.tipo = 'SOPORTE' AND u.estado = 'ACTIVO'"
    " FOR UPDATE OF t"
)


async def _pagina(request, laboratorio, activa, *, errores=(), datos=None, estado=200):
    async with sesion_tenant(laboratorio.tenant_id, usuario_id=activa.usuario.uuid) as sesion:
        accesos = (await sesion.execute(_SQL_ACCESOS)).mappings().all()
    contexto = {
        "sitio": laboratorio,
        "activa": activa,
        "accesos": accesos,
        "errores": list(errores),
        "datos": datos or {},
        "horas_maximas": HORAS_MAXIMAS,
    }
    return render(request, "laboratorio/soporte.html", contexto, estado)


@router.get("/configuracion/soporte")
async def soporte(request: Request, laboratorio: LaboratorioActual, activa: Autoriza):
    return await _pagina(request, laboratorio, activa)


@router.post("/configuracion/soporte")
async def autorizar(
    request: Request,
    laboratorio: LaboratorioActual,
    _csrf: Csrf,
    activa: Autoriza,
    horas: Annotated[TextoSeguro, Form(max_length=3)] = "",
    motivo: Annotated[TextoSeguro, Form(max_length=300)] = "",
):
    motivo = motivo.strip()
    errores = []
    # Solo dígitos ASCII: str.isdigit() acepta "²", que int() rechaza (lo encontró el fuzzing).
    if not re.fullmatch(r"[0-9]{1,2}", horas) or not 1 <= int(horas) <= HORAS_MAXIMAS:
        errores.append(t("soporte.error_horas", laboratorio.idioma, maximo=HORAS_MAXIMAS))
    if not 5 <= len(motivo) <= 300:
        errores.append(t("soporte.error_motivo", laboratorio.idioma))
    if errores:
        datos = {"horas": horas, "motivo": motivo}
        return await _pagina(request, laboratorio, activa, errores=errores, datos=datos, estado=400)
    async with sesion_tenant(laboratorio.tenant_id, usuario_id=activa.usuario.uuid, ip=ip_cliente(request)) as sesion:
        await sesion.execute(
            text(
                "INSERT INTO lab.accesos_soporte (autorizado_por, motivo, fin)"
                " VALUES (:u, :m, now() + make_interval(hours => :h))"
            ),
            {"u": activa.usuario.id, "m": motivo, "h": int(horas)},
        )
        await repositorio.registrar_evento(
            sesion, "SOPORTE_AUTORIZADO", usuario_id=activa.usuario.id, ip=ip_cliente(request)
        )
    return redirigir(request, "/configuracion/soporte")


@router.post("/configuracion/soporte/{acceso_uuid}/revocar")
async def revocar(request: Request, laboratorio: LaboratorioActual, _csrf: Csrf, acceso_uuid: UUID, activa: Autoriza):
    async with sesion_tenant(laboratorio.tenant_id, usuario_id=activa.usuario.uuid, ip=ip_cliente(request)) as sesion:
        revocado = await sesion.scalar(
            text(
                "UPDATE lab.accesos_soporte SET revocado_en = now(), revocado_por = :u"
                " WHERE uuid = :a AND revocado_en IS NULL RETURNING id"
            ),
            {"u": activa.usuario.id, "a": acceso_uuid},
        )
        if revocado is None:
            raise HTTPException(status_code=404)
        # Sin autorización, nadie de soporte sigue dentro: se cierran sus sesiones y se anulan los tiquetes.
        await sesion.execute(
            text(
                "UPDATE lab.sesiones SET revocada_en = now() WHERE revocada_en IS NULL"
                " AND usuario_id IN (SELECT id FROM lab.usuarios WHERE tipo = 'SOPORTE')"
            )
        )
        await sesion.execute(
            text("UPDATE lab.tickets_soporte SET usado_en = now() WHERE acceso_id = :a AND usado_en IS NULL"),
            {"a": revocado},
        )
        await repositorio.registrar_evento(
            sesion, "SOPORTE_REVOCADO", usuario_id=activa.usuario.id, ip=ip_cliente(request)
        )
    return redirigir(request, "/configuracion/soporte")


def _tiquete_valido(token: str) -> bool:
    return 32 <= len(token) <= 128


@router.get("/soporte/entrar/{token}")
async def entrar_formulario(request: Request, laboratorio: LaboratorioActual, token: str):
    """Confirmación con un botón: el tiquete se consume con un POST protegido por CSRF, no con un enlace."""
    contexto = {"sitio": laboratorio, "token": token, "invalido": not _tiquete_valido(token)}
    return render(request, "laboratorio/soporte_entrar.html", contexto, 404 if contexto["invalido"] else 200)


@router.post("/soporte/entrar/{token}")
async def entrar(request: Request, laboratorio: LaboratorioActual, _csrf: Csrf, token: str):
    sesion_token = None
    if _tiquete_valido(token):
        ip = ip_cliente(request)
        async with sesion_tenant(laboratorio.tenant_id, ip=ip) as sesion:
            tiquete = (await sesion.execute(_SQL_TIQUETE, {"h": cripto.hash_token(token)})).mappings().first()
            if tiquete is not None:
                # Desde aquí la auditoría de la transacción queda a nombre de la persona de soporte.
                await sesion.execute(
                    text("SELECT set_config('app.current_user_id', :u, true)"), {"u": tiquete["usuario_uuid"]}
                )
                await sesion.execute(
                    text("UPDATE lab.tickets_soporte SET usado_en = now() WHERE id = :i"), {"i": tiquete["id"]}
                )
                restante = (tiquete["fin"] - datetime.now(UTC)).total_seconds() / 60
                minutos = max(1, min(math.floor(restante), get_settings().sesion_maxima_horas * 60))
                sesion_token = await repositorio.crear_sesion(
                    sesion,
                    tiquete["usuario_id"],
                    segundo_factor_ok=True,  # ya lo pasó en el Admin Hub
                    minutos=minutos,
                    ip=ip,
                    agente=request.headers.get("user-agent", "")[:300],
                )
                await repositorio.registrar_evento(sesion, "SOPORTE_INICIO", usuario_id=tiquete["usuario_id"], ip=ip)
                await registrar_acceso(sesion, "soporte", operacion="ACCESO", detalle={"evento": "inicio_sesion"})
    if sesion_token is None:
        contexto = {"sitio": laboratorio, "token": token, "invalido": True}
        return render(request, "laboratorio/soporte_entrar.html", contexto, 404)
    rotar_csrf(request)
    respuesta = redirigir(request, "/panel")
    poner_cookie_sesion(respuesta, sesion_token)
    return respuesta
