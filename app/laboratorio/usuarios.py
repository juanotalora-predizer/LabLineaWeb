"""Usuarios del laboratorio: lista, invitación y desactivación (spec infraestructura/0008).

- Invitar crea el usuario sin contraseña con sus roles y encola la invitación (app/auth/invitaciones.py).
- El plan del laboratorio limita el número de usuarios activos de personal y médicos.
- Desactivar revoca las sesiones del usuario. Nadie se desactiva a sí mismo.
- Los usuarios se identifican por UUID; uno de otro laboratorio no existe para este (RLS → 404).
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.auth import repositorio
from app.auth.invitaciones import TIPO_TAREA
from app.auth.web import (
    Csrf,
    LaboratorioActual,
    SesionActiva,
    TextoSeguro,
    ip_cliente,
    redirigir,
    render,
    requiere_permiso,
)
from app.core.auditoria import registrar_acceso
from app.core.db import sesion_tenant
from app.core.i18n import t
from app.core.tareas import encolar

router = APIRouter(default_response_class=HTMLResponse)

TIPOS_INVITABLES = ("PERSONAL", "MEDICO")

_SQL_LISTA = text(
    "SELECT u.uuid::text AS uuid, u.nombre, u.email::text AS email, u.tipo, u.estado,"
    " u.password_hash IS NULL AS pendiente,"
    " coalesce(string_agg(r.codigo, ', ' ORDER BY r.codigo), '') AS roles"
    " FROM lab.usuarios u LEFT JOIN lab.usuario_roles ur ON ur.usuario_id = u.id"
    " LEFT JOIN lab.roles r ON r.id = ur.rol_id"
    " GROUP BY u.id ORDER BY u.nombre"
)
# El rol de soporte es solo para el personal de la plataforma con autorización (app/laboratorio/soporte.py).
_SQL_ROLES = text("SELECT codigo, nombre FROM lab.roles WHERE codigo <> 'SOPORTE' ORDER BY nombre")
_SQL_CUENTA_PERSONAL = text(
    "SELECT count(*) FROM lab.usuarios WHERE estado = 'ACTIVO' AND tipo IN ('PERSONAL', 'MEDICO')"
)


@router.get("/configuracion/usuarios")
async def lista_usuarios(
    request: Request,
    laboratorio: LaboratorioActual,
    activa: Annotated[SesionActiva, Depends(requiere_permiso("usuarios", "consultar"))],
):
    async with sesion_tenant(laboratorio.tenant_id, usuario_id=activa.usuario.uuid, ip=ip_cliente(request)) as sesion:
        usuarios = (await sesion.execute(_SQL_LISTA)).mappings().all()
        # Datos personales del personal y de pacientes: la consulta queda auditada.
        await registrar_acceso(sesion, "usuarios", detalle={"vista": "lista_usuarios", "filas": len(usuarios)})
    contexto = {"sitio": laboratorio, "activa": activa, "usuarios": usuarios}
    return render(request, "laboratorio/usuarios.html", contexto)


async def _formulario(request, laboratorio, activa, *, errores=(), datos=None, estado=200):
    async with sesion_tenant(laboratorio.tenant_id, usuario_id=activa.usuario.uuid) as sesion:
        roles = (await sesion.execute(_SQL_ROLES)).mappings().all()
    contexto = {
        "sitio": laboratorio,
        "activa": activa,
        "roles": roles,
        "tipos": TIPOS_INVITABLES,
        "errores": list(errores),
        "datos": datos or {},
    }
    return render(request, "laboratorio/usuario_nuevo.html", contexto, estado)


@router.get("/configuracion/usuarios/nuevo")
async def nuevo_usuario_formulario(
    request: Request,
    laboratorio: LaboratorioActual,
    activa: Annotated[SesionActiva, Depends(requiere_permiso("usuarios", "crear"))],
):
    return await _formulario(request, laboratorio, activa)


@router.post("/configuracion/usuarios/nuevo")
async def invitar_usuario(
    request: Request,
    laboratorio: LaboratorioActual,
    _csrf: Csrf,
    activa: Annotated[SesionActiva, Depends(requiere_permiso("usuarios", "crear"))],
    email: Annotated[TextoSeguro, Form(max_length=254)] = "",
    nombre: Annotated[TextoSeguro, Form(max_length=120)] = "",
    tipo: Annotated[TextoSeguro, Form(max_length=20)] = "PERSONAL",
    roles: Annotated[list[TextoSeguro], Form(max_length=20)] = [],  # noqa: B006 — FastAPI copia el valor por defecto
):
    idioma = laboratorio.idioma
    email, nombre = email.strip().lower(), nombre.strip()
    datos = {"email": email, "nombre": nombre, "tipo": tipo, "roles": roles}
    errores = []
    if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        errores.append(t("usuarios.error_correo", idioma))
    if not 2 <= len(nombre) <= 120:
        errores.append(t("usuarios.error_nombre", idioma))
    if tipo not in TIPOS_INVITABLES:
        errores.append(t("usuarios.error_tipo", idioma))
    if errores:
        return await _formulario(request, laboratorio, activa, errores=errores, datos=datos, estado=400)

    try:
        async with sesion_tenant(
            laboratorio.tenant_id, usuario_id=activa.usuario.uuid, ip=ip_cliente(request)
        ) as sesion:
            disponibles = {r["codigo"] for r in (await sesion.execute(_SQL_ROLES)).mappings()}
            if not set(roles) <= disponibles:
                errores.append(t("usuarios.error_roles", idioma))
            elif laboratorio.max_usuarios is not None and (
                await sesion.scalar(_SQL_CUENTA_PERSONAL) >= laboratorio.max_usuarios
            ):
                errores.append(t("usuarios.error_limite", idioma, maximo=laboratorio.max_usuarios))
            else:
                usuario_id = await repositorio.crear_usuario(
                    sesion, email=email, nombre=nombre, tipo=tipo, clave=None, roles=tuple(roles)
                )
                usuario_uuid = await sesion.scalar(
                    text("SELECT uuid::text FROM lab.usuarios WHERE id = :i"), {"i": usuario_id}
                )
                await encolar(sesion, TIPO_TAREA, {"usuario": usuario_uuid, "subdominio": laboratorio.subdominio})
    except IntegrityError:
        errores.append(t("usuarios.error_existe", idioma))
    if errores:
        return await _formulario(request, laboratorio, activa, errores=errores, datos=datos, estado=400)
    return redirigir(request, "/configuracion/usuarios")


@router.post("/configuracion/usuarios/{usuario_uuid}/desactivar")
async def desactivar_usuario(
    request: Request,
    laboratorio: LaboratorioActual,
    _csrf: Csrf,
    usuario_uuid: UUID,
    activa: Annotated[SesionActiva, Depends(requiere_permiso("usuarios", "modificar"))],
):
    if str(usuario_uuid) == activa.usuario.uuid:
        raise HTTPException(status_code=400)
    async with sesion_tenant(laboratorio.tenant_id, usuario_id=activa.usuario.uuid, ip=ip_cliente(request)) as sesion:
        usuario_id = await sesion.scalar(
            text("UPDATE lab.usuarios SET estado = 'INACTIVO' WHERE uuid = :u AND estado = 'ACTIVO' RETURNING id"),
            {"u": usuario_uuid},
        )
        if usuario_id is None:
            raise HTTPException(status_code=404)
        await repositorio.revocar_sesiones_de(sesion, usuario_id)
    return redirigir(request, "/configuracion/usuarios")
