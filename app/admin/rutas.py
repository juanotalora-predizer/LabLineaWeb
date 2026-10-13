"""Admin Hub (admin.<dominio>): laboratorios, planes y usuarios de la plataforma (spec funcional/0005, etapa 4).

Todas las rutas exigen el host del Admin Hub (`sitio_admin`, 404 en otro host) y trabajan con el rol de
base de datos de la plataforma, que no tiene acceso a los datos de los laboratorios. Los recursos se
identifican por UUID.
"""

import re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.admin import servicios
from app.auth.web import Csrf, SesionActiva, TextoSeguro, ip_cliente, redirigir, render, requiere_permiso
from app.core.auditoria import registrar_acceso
from app.core.db import sesion_plataforma
from app.core.i18n import t
from app.core.tenancy import SitioAdmin, sitio_admin

router = APIRouter(default_response_class=HTMLResponse, dependencies=[Depends(sitio_admin)])
AdminActual = Annotated[SitioAdmin, Depends(sitio_admin)]
CODIGO_PLAN = re.compile(r"^[A-Z][A-Z0-9_]{1,39}$")
# Errores que llegan por ?error= tras una redirección: solo estos se muestran (lista blanca).
ERRORES_LABORATORIO = {
    "invitacion": "laboratorios.error_invitacion",
    "suscripcion": "suscripcion.error_suscripcion",
    "motivo": "suscripcion.error_motivo",
    **{c: f"facturas.error_{c}" for c in ("laboratorio", "cancelada", "licencia", "sin_precio", "periodo_facturado")},
}


def _sesion(request: Request, activa: SesionActiva):
    return sesion_plataforma(usuario_id=activa.usuario.uuid, ip=ip_cliente(request))


# --- Laboratorios ---

_SQL_LABORATORIOS = text(
    "SELECT l.uuid::text AS uuid, l.nombre_comercial, l.subdominio, l.pais, l.estado, p.nombre AS plan, l.creado_en"
    " FROM plataforma.laboratorios l JOIN plataforma.planes p ON p.id = l.plan_id ORDER BY l.nombre_comercial"
)
_SQL_LABORATORIO = text(
    "SELECT l.id, l.uuid::text AS uuid, l.nombre_comercial, l.subdominio, l.identificador_fiscal, l.pais, l.estado,"
    " l.creado_en, p.uuid::text AS plan_uuid, p.nombre AS plan,"
    " s.tipo_licencia, s.inicio, s.fin, s.renovacion_automatica, s.motivo_suspension,"
    # Estado efectivo: una ACTIVA con fin pasado ya está vencida aunque el trabajador no la haya marcado.
    " CASE WHEN s.estado = 'ACTIVA' AND s.fin IS NOT NULL AND s.fin <= now() THEN 'VENCIDA'"
    "      ELSE s.estado END AS suscripcion_estado"
    " FROM plataforma.laboratorios l JOIN plataforma.planes p ON p.id = l.plan_id"
    " LEFT JOIN plataforma.suscripciones s ON s.laboratorio_id = l.id WHERE l.uuid = :u"
)
_SQL_LICENCIAS = text("SELECT codigo, nombre, facturable FROM plataforma.tipos_licencia ORDER BY codigo")
_SQL_FACTURAS_LAB = text(
    "SELECT uuid::text AS uuid, numero, tipo_licencia, periodo_desde, periodo_hasta, total, saldo, moneda, estado"
    " FROM plataforma.facturas WHERE laboratorio_id = :l ORDER BY emitida_en DESC"
)
_SQL_PAISES = text('SELECT codigo, nombre FROM "global".paises WHERE habilitado ORDER BY nombre')
_SQL_PLANES_ACTIVOS = text("SELECT uuid::text AS uuid, nombre FROM plataforma.planes WHERE activo ORDER BY nombre")


@router.get("/laboratorios")
async def laboratorios(
    request: Request,
    sitio: AdminActual,
    activa: Annotated[SesionActiva, Depends(requiere_permiso("laboratorios", "consultar"))],
):
    async with _sesion(request, activa) as sesion:
        filas = (await sesion.execute(_SQL_LABORATORIOS)).mappings().all()
    return render(request, "admin/laboratorios.html", {"sitio": sitio, "activa": activa, "laboratorios": filas})


async def _formulario_alta(request, sitio, activa, *, errores=(), datos=None, estado=200):
    async with _sesion(request, activa) as sesion:
        paises = (await sesion.execute(_SQL_PAISES)).mappings().all()
        planes = (await sesion.execute(_SQL_PLANES_ACTIVOS)).mappings().all()
        licencias = (await sesion.execute(_SQL_LICENCIAS)).mappings().all()
    contexto = {
        "sitio": sitio,
        "activa": activa,
        "licencias": licencias,
        "paises": paises,
        "planes": planes,
        "errores": list(errores),
        "datos": datos or {},
    }
    return render(request, "admin/laboratorio_nuevo.html", contexto, estado)


@router.get("/laboratorios/nuevo")
async def alta_formulario(
    request: Request,
    sitio: AdminActual,
    activa: Annotated[SesionActiva, Depends(requiere_permiso("laboratorios", "crear"))],
):
    return await _formulario_alta(request, sitio, activa)


@router.post("/laboratorios/nuevo")
async def alta(
    request: Request,
    sitio: AdminActual,
    _csrf: Csrf,
    activa: Annotated[SesionActiva, Depends(requiere_permiso("laboratorios", "crear"))],
    nombre: Annotated[TextoSeguro, Form(max_length=120)] = "",
    subdominio: Annotated[TextoSeguro, Form(max_length=63)] = "",
    identificador_fiscal: Annotated[TextoSeguro, Form(max_length=20)] = "",
    pais: Annotated[TextoSeguro, Form(max_length=3)] = "",
    plan: Annotated[TextoSeguro, Form(max_length=36)] = "",
    sede: Annotated[TextoSeguro, Form(max_length=120)] = "",
    ciudad: Annotated[TextoSeguro, Form(max_length=80)] = "",
    admin_email: Annotated[TextoSeguro, Form(max_length=254)] = "",
    admin_nombre: Annotated[TextoSeguro, Form(max_length=120)] = "",
    tipo_licencia: Annotated[TextoSeguro, Form(max_length=20)] = "DEMO",
):
    datos = servicios.DatosAlta(
        tipo_licencia=tipo_licencia.strip().upper(),
        nombre=nombre.strip(),
        subdominio=subdominio.strip().lower(),
        identificador_fiscal=identificador_fiscal.strip(),
        pais=pais.strip().upper(),
        plan=plan.strip(),
        sede=sede.strip(),
        ciudad=ciudad.strip(),
        admin_email=admin_email.strip().lower(),
        admin_nombre=admin_nombre.strip(),
    )
    async with _sesion(request, activa) as sesion:
        uuid, errores = await servicios.dar_de_alta(sesion, datos, sitio.idioma)
    if errores:
        return await _formulario_alta(request, sitio, activa, errores=errores, datos=datos.__dict__, estado=400)
    return redirigir(request, f"/laboratorios/{uuid}")


@router.get("/laboratorios/{laboratorio_uuid}")
async def laboratorio(
    request: Request,
    sitio: AdminActual,
    laboratorio_uuid: UUID,
    activa: Annotated[SesionActiva, Depends(requiere_permiso("laboratorios", "consultar"))],
):
    async with _sesion(request, activa) as sesion:
        fila = (await sesion.execute(_SQL_LABORATORIO, {"u": laboratorio_uuid})).mappings().first()
        if fila is None:
            raise HTTPException(status_code=404)
        planes = (await sesion.execute(_SQL_PLANES_ACTIVOS)).mappings().all()
        licencias = (await sesion.execute(_SQL_LICENCIAS)).mappings().all()
        facturas = (await sesion.execute(_SQL_FACTURAS_LAB, {"l": fila["id"]})).mappings().all()
    contexto = {
        "sitio": sitio,
        "activa": activa,
        "laboratorio": fila,
        "planes": planes,
        "licencias": licencias,
        "facturas": facturas,
        "aviso": request.query_params.get("aviso"),
        "error": t(clave, sitio.idioma)
        if (clave := ERRORES_LABORATORIO.get(request.query_params.get("error", "")))
        else None,
    }
    return render(request, "admin/laboratorio.html", contexto)


@router.post("/laboratorios/{laboratorio_uuid}/plan")
async def cambiar_plan(
    request: Request,
    sitio: AdminActual,
    _csrf: Csrf,
    laboratorio_uuid: UUID,
    activa: Annotated[SesionActiva, Depends(requiere_permiso("laboratorios", "modificar"))],
    plan: Annotated[TextoSeguro, Form(max_length=36)] = "",
):
    try:
        plan_uuid = UUID(plan)
    except ValueError:
        raise HTTPException(status_code=400) from None
    async with _sesion(request, activa) as sesion:
        cambiado = await sesion.scalar(
            text(
                "UPDATE plataforma.laboratorios SET plan_id = p.id FROM plataforma.planes p"
                " WHERE plataforma.laboratorios.uuid = :l AND p.uuid = :p AND p.activo RETURNING true"
            ),
            {"l": laboratorio_uuid, "p": plan_uuid},
        )
    if not cambiado:
        raise HTTPException(status_code=404)
    return redirigir(request, f"/laboratorios/{laboratorio_uuid}?aviso=plan")


@router.post("/laboratorios/{laboratorio_uuid}/invitacion")
async def reenviar_invitacion(
    request: Request,
    sitio: AdminActual,
    _csrf: Csrf,
    laboratorio_uuid: UUID,
    activa: Annotated[SesionActiva, Depends(requiere_permiso("laboratorios", "modificar"))],
):
    try:
        async with _sesion(request, activa) as sesion:
            await sesion.execute(text("SELECT plataforma.invitar_administrador(:l)"), {"l": laboratorio_uuid})
    except DBAPIError:
        # Laboratorio inexistente o sin administrador pendiente: mismo mensaje, sin detalles internos.
        return redirigir(request, f"/laboratorios/{laboratorio_uuid}?error=invitacion")
    return redirigir(request, f"/laboratorios/{laboratorio_uuid}?aviso=invitacion")


# --- Planes ---

_SQL_PLANES = text(
    "SELECT p.uuid::text AS uuid, p.codigo, p.nombre, p.max_usuarios, p.activo,"
    " coalesce(string_agg(pm.modulo, ', ' ORDER BY pm.modulo), '') AS modulos,"
    " (SELECT count(*) FROM plataforma.laboratorios l WHERE l.plan_id = p.id) AS laboratorios"
    " FROM plataforma.planes p LEFT JOIN plataforma.plan_modulos pm ON pm.plan_id = p.id"
    " GROUP BY p.id ORDER BY p.nombre"
)
_SQL_MODULOS_DE_PLAN = text('SELECT codigo, nombre FROM "global".modulos WHERE NOT siempre_activo ORDER BY nombre')


@router.get("/planes")
async def planes(
    request: Request,
    sitio: AdminActual,
    activa: Annotated[SesionActiva, Depends(requiere_permiso("planes", "consultar"))],
):
    async with _sesion(request, activa) as sesion:
        filas = (await sesion.execute(_SQL_PLANES)).mappings().all()
    return render(request, "admin/planes.html", {"sitio": sitio, "activa": activa, "planes": filas})


async def _formulario_plan(request, sitio, activa, *, plan=None, errores=(), estado=200):
    async with _sesion(request, activa) as sesion:
        modulos = (await sesion.execute(_SQL_MODULOS_DE_PLAN)).mappings().all()
    contexto = {"sitio": sitio, "activa": activa, "plan": plan, "modulos": modulos, "errores": list(errores)}
    return render(request, "admin/plan.html", contexto, estado)


def _validar_plan(nombre: str, max_usuarios: str, modulos: list[str], idioma: str) -> tuple[int | None, list[str]]:
    errores = []
    if not 2 <= len(nombre) <= 120:
        errores.append(t("planes.error_nombre", idioma))
    maximo = None
    if max_usuarios.strip():
        if not re.fullmatch(r"[0-9]{1,6}", max_usuarios.strip()) or not 1 <= int(max_usuarios) <= 100000:
            errores.append(t("planes.error_maximo", idioma))
        else:
            maximo = int(max_usuarios)
    if len(set(modulos)) != len(modulos):
        errores.append(t("planes.error_modulos", idioma))
    return maximo, errores


async def _guardar_modulos(sesion, plan_id: int, modulos: list[str]) -> None:
    await sesion.execute(text("DELETE FROM plataforma.plan_modulos WHERE plan_id = :p"), {"p": plan_id})
    for modulo in modulos:
        await sesion.execute(
            text(
                "INSERT INTO plataforma.plan_modulos (plan_id, modulo)"
                ' SELECT :p, codigo FROM "global".modulos WHERE codigo = :m AND NOT siempre_activo'
            ),
            {"p": plan_id, "m": modulo},
        )


@router.get("/planes/nuevo")
async def plan_nuevo_formulario(
    request: Request,
    sitio: AdminActual,
    activa: Annotated[SesionActiva, Depends(requiere_permiso("planes", "crear"))],
):
    return await _formulario_plan(request, sitio, activa)


@router.post("/planes/nuevo")
async def plan_nuevo(
    request: Request,
    sitio: AdminActual,
    _csrf: Csrf,
    activa: Annotated[SesionActiva, Depends(requiere_permiso("planes", "crear"))],
    codigo: Annotated[TextoSeguro, Form(max_length=40)] = "",
    nombre: Annotated[TextoSeguro, Form(max_length=120)] = "",
    max_usuarios: Annotated[TextoSeguro, Form(max_length=6)] = "",
    modulos: Annotated[list[TextoSeguro], Form(max_length=40)] = [],  # noqa: B006 — FastAPI copia el valor por defecto
):
    codigo, nombre = codigo.strip().upper(), nombre.strip()
    maximo, errores = _validar_plan(nombre, max_usuarios, modulos, sitio.idioma)
    if not CODIGO_PLAN.match(codigo):
        errores.append(t("planes.error_codigo", sitio.idioma))
    borrador = {"codigo": codigo, "nombre": nombre, "max_usuarios": max_usuarios, "activo": True, "modulos": modulos}
    if not errores:
        try:
            async with _sesion(request, activa) as sesion:
                plan_id, plan_uuid = (
                    await sesion.execute(
                        text(
                            "INSERT INTO plataforma.planes (codigo, nombre, max_usuarios) VALUES (:c, :n, :m)"
                            " RETURNING id, uuid::text"
                        ),
                        {"c": codigo, "n": nombre, "m": maximo},
                    )
                ).one()
                await _guardar_modulos(sesion, plan_id, modulos)
            return redirigir(request, f"/planes/{plan_uuid}")
        except IntegrityError:
            errores.append(t("planes.error_existe", sitio.idioma))
    return await _formulario_plan(request, sitio, activa, plan=borrador, errores=errores, estado=400)


async def _cargar_plan(sesion, plan_uuid: UUID) -> dict | None:
    fila = (
        (
            await sesion.execute(
                text(
                    "SELECT id, uuid::text AS uuid, codigo, nombre, max_usuarios, activo"
                    " FROM plataforma.planes WHERE uuid = :u"
                ),
                {"u": plan_uuid},
            )
        )
        .mappings()
        .first()
    )
    if fila is None:
        return None
    modulos = (
        await sesion.execute(text("SELECT modulo FROM plataforma.plan_modulos WHERE plan_id = :p"), {"p": fila["id"]})
    ).scalars()
    return {
        **fila,
        "max_usuarios": "" if fila["max_usuarios"] is None else str(fila["max_usuarios"]),
        "modulos": list(modulos),
    }


@router.get("/planes/{plan_uuid}")
async def plan(
    request: Request,
    sitio: AdminActual,
    plan_uuid: UUID,
    activa: Annotated[SesionActiva, Depends(requiere_permiso("planes", "consultar"))],
):
    async with _sesion(request, activa) as sesion:
        datos = await _cargar_plan(sesion, plan_uuid)
    if datos is None:
        raise HTTPException(status_code=404)
    return await _formulario_plan(request, sitio, activa, plan=datos)


@router.post("/planes/{plan_uuid}")
async def plan_guardar(
    request: Request,
    sitio: AdminActual,
    _csrf: Csrf,
    plan_uuid: UUID,
    activa: Annotated[SesionActiva, Depends(requiere_permiso("planes", "modificar"))],
    nombre: Annotated[TextoSeguro, Form(max_length=120)] = "",
    max_usuarios: Annotated[TextoSeguro, Form(max_length=6)] = "",
    activo: Annotated[TextoSeguro, Form(max_length=5)] = "",
    modulos: Annotated[list[TextoSeguro], Form(max_length=40)] = [],  # noqa: B006 — FastAPI copia el valor por defecto
):
    nombre = nombre.strip()
    maximo, errores = _validar_plan(nombre, max_usuarios, modulos, sitio.idioma)
    async with _sesion(request, activa) as sesion:
        datos = await _cargar_plan(sesion, plan_uuid)
        if datos is None:
            raise HTTPException(status_code=404)
        if not errores:
            await sesion.execute(
                text("UPDATE plataforma.planes SET nombre = :n, max_usuarios = :m, activo = :a WHERE id = :i"),
                {"n": nombre, "m": maximo, "a": activo == "si", "i": datos["id"]},
            )
            await _guardar_modulos(sesion, datos["id"], modulos)
    if errores:
        borrador = {
            **datos,
            "nombre": nombre,
            "max_usuarios": max_usuarios,
            "activo": activo == "si",
            "modulos": modulos,
        }
        return await _formulario_plan(request, sitio, activa, plan=borrador, errores=errores, estado=400)
    return redirigir(request, f"/planes/{plan_uuid}")


# --- Usuarios de la plataforma ---


@router.get("/plataforma/usuarios")
async def usuarios_plataforma(
    request: Request,
    sitio: AdminActual,
    activa: Annotated[SesionActiva, Depends(requiere_permiso("usuarios", "consultar"))],
):
    async with _sesion(request, activa) as sesion:
        filas = (
            (
                await sesion.execute(
                    text(
                        "SELECT u.nombre, u.email::text AS email, u.estado,"
                        " coalesce(string_agg(r.codigo, ', ' ORDER BY r.codigo), '') AS roles"
                        " FROM plataforma.usuarios u LEFT JOIN plataforma.usuario_roles ur ON ur.usuario_id = u.id"
                        " LEFT JOIN plataforma.roles r ON r.id = ur.rol_id GROUP BY u.id ORDER BY u.nombre"
                    )
                )
            )
            .mappings()
            .all()
        )
        await registrar_acceso(sesion, "usuarios", detalle={"vista": "usuarios_plataforma", "filas": len(filas)})
    return render(request, "admin/usuarios.html", {"sitio": sitio, "activa": activa, "usuarios": filas})
