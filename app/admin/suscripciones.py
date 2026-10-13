"""Admin Hub: suscripciones, facturas y pagos, precios, campañas y soporte (etapa 5).

Todas las rutas exigen el host del Admin Hub y el permiso del módulo correspondiente. Los recursos se
identifican por UUID. Las reglas de dinero viven en app/admin/facturacion.py y en la base.
"""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.admin import facturacion
from app.admin.facturacion import ErrorFacturacion
from app.auth.web import Csrf, SesionActiva, TextoSeguro, ip_cliente, redirigir, render, requiere_permiso
from app.core import cripto
from app.core.auditoria import registrar_acceso
from app.core.config import get_settings
from app.core.db import sesion_plataforma
from app.core.i18n import t
from app.core.tenancy import SitioAdmin, sitio_admin

router = APIRouter(default_response_class=HTMLResponse, dependencies=[Depends(sitio_admin)])
AdminActual = Annotated[SitioAdmin, Depends(sitio_admin)]


def _sesion(request: Request, activa: SesionActiva):
    return sesion_plataforma(usuario_id=activa.usuario.uuid, ip=ip_cliente(request))


def _fecha(texto: str) -> date | None:
    try:
        return date.fromisoformat(texto.strip())
    except ValueError:
        return None


# --- Suscripción de un laboratorio ---

ACCIONES_SUSCRIPCION = ("suspender", "reactivar", "cancelar", "renovacion_si", "renovacion_no", "licencia")


@router.post("/laboratorios/{laboratorio_uuid}/suscripcion")
async def cambiar_suscripcion(
    request: Request,
    sitio: AdminActual,
    _csrf: Csrf,
    laboratorio_uuid: UUID,
    activa: Annotated[SesionActiva, Depends(requiere_permiso("suscripciones", "modificar"))],
    accion: Annotated[TextoSeguro, Form(max_length=20)] = "",
    motivo: Annotated[TextoSeguro, Form(max_length=300)] = "",
    tipo_licencia: Annotated[TextoSeguro, Form(max_length=20)] = "",
):
    if accion not in ACCIONES_SUSCRIPCION:
        raise HTTPException(status_code=400)
    motivo = motivo.strip()
    if accion == "suspender" and not 5 <= len(motivo) <= 300:
        return redirigir(request, f"/laboratorios/{laboratorio_uuid}?error=motivo")
    sentencias = {
        "suspender": "UPDATE plataforma.suscripciones SET estado = 'SUSPENDIDA', motivo_suspension = :m,"
        " actualizada_en = now() WHERE laboratorio_id = :l AND estado IN ('ACTIVA', 'VENCIDA') RETURNING id",
        "reactivar": "UPDATE plataforma.suscripciones SET estado = 'ACTIVA', motivo_suspension = NULL,"
        " actualizada_en = now() WHERE laboratorio_id = :l AND estado = 'SUSPENDIDA' RETURNING id",
        "cancelar": "UPDATE plataforma.suscripciones SET estado = 'CANCELADA', motivo_suspension = NULL,"
        " renovacion_automatica = false, actualizada_en = now()"
        " WHERE laboratorio_id = :l AND estado <> 'CANCELADA' RETURNING id",
        "renovacion_si": "UPDATE plataforma.suscripciones SET renovacion_automatica = true, actualizada_en = now()"
        " WHERE laboratorio_id = :l AND estado <> 'CANCELADA' RETURNING id",
        "renovacion_no": "UPDATE plataforma.suscripciones SET renovacion_automatica = false, actualizada_en = now()"
        " WHERE laboratorio_id = :l RETURNING id",
        # Licencias sin cobro (demostración, ad honorem, gratuita): las facturables se activan pagando.
        "licencia": "UPDATE plataforma.suscripciones s SET tipo_licencia = tl.codigo, estado = 'ACTIVA',"
        " motivo_suspension = NULL, inicio = now(), actualizada_en = now(),"
        " fin = CASE WHEN tl.duracion IS NULL THEN NULL ELSE now() + tl.duracion END"
        " FROM plataforma.tipos_licencia tl"
        " WHERE s.laboratorio_id = :l AND tl.codigo = :t AND NOT tl.facturable AND s.estado <> 'CANCELADA'"
        " RETURNING s.id",
    }
    async with _sesion(request, activa) as sesion:
        laboratorio_id = await sesion.scalar(
            text("SELECT id FROM plataforma.laboratorios WHERE uuid = :u"), {"u": laboratorio_uuid}
        )
        if laboratorio_id is None:
            raise HTTPException(status_code=404)
        cambiada = await sesion.scalar(
            text(sentencias[accion]), {"l": laboratorio_id, "m": motivo or None, "t": tipo_licencia}
        )
    if cambiada is None:
        return redirigir(request, f"/laboratorios/{laboratorio_uuid}?error=suscripcion")
    return redirigir(request, f"/laboratorios/{laboratorio_uuid}?aviso=suscripcion")


# --- Facturas y pagos ---


@router.post("/laboratorios/{laboratorio_uuid}/facturas")
async def facturar(
    request: Request,
    sitio: AdminActual,
    _csrf: Csrf,
    laboratorio_uuid: UUID,
    activa: Annotated[SesionActiva, Depends(requiere_permiso("facturacion", "crear"))],
    tipo_licencia: Annotated[TextoSeguro, Form(max_length=20)] = "",
):
    try:
        async with _sesion(request, activa) as sesion:
            factura = await facturacion.generar_factura(sesion, str(laboratorio_uuid), tipo_licencia)
    except ErrorFacturacion as error:
        return redirigir(
            request, f"/laboratorios/{laboratorio_uuid}?error={error.clave.removeprefix('facturas.error_')}"
        )
    return redirigir(request, f"/facturas/{factura}")


_SQL_FACTURAS = text(
    "SELECT f.uuid::text AS uuid, f.numero, l.nombre_comercial AS laboratorio, f.tipo_licencia, f.total, f.saldo,"
    " f.moneda, f.estado, f.emitida_en, f.vence_en"
    " FROM plataforma.facturas f JOIN plataforma.laboratorios l ON l.id = f.laboratorio_id"
    " WHERE (CAST(:estado AS text) IS NULL OR f.estado = :estado)"
    " ORDER BY f.emitida_en DESC LIMIT 200"
)
ESTADOS_FACTURA = ("PENDIENTE", "PAGADA_PARCIAL", "PAGADA", "ANULADA")


@router.get("/facturas")
async def facturas(
    request: Request,
    sitio: AdminActual,
    activa: Annotated[SesionActiva, Depends(requiere_permiso("facturacion", "consultar"))],
    estado: str | None = None,
):
    filtro = estado if estado in ESTADOS_FACTURA else None
    async with _sesion(request, activa) as sesion:
        filas = (await sesion.execute(_SQL_FACTURAS, {"estado": filtro})).mappings().all()
    contexto = {"sitio": sitio, "activa": activa, "facturas": filas, "estados": ESTADOS_FACTURA, "filtro": filtro}
    return render(request, "admin/facturas.html", contexto)


async def _detalle_factura(request, sitio, activa, factura_uuid: UUID, *, error: str | None = None, estado=200):
    async with _sesion(request, activa) as sesion:
        factura = (
            (
                await sesion.execute(
                    text(
                        "SELECT f.*, f.uuid::text AS uuid, l.nombre_comercial AS laboratorio,"
                        " l.uuid::text AS laboratorio_uuid, c.nombre AS campana"
                        " FROM plataforma.facturas f JOIN plataforma.laboratorios l ON l.id = f.laboratorio_id"
                        " LEFT JOIN plataforma.campanas c ON c.id = f.campana_id WHERE f.uuid = :f"
                    ),
                    {"f": factura_uuid},
                )
            )
            .mappings()
            .first()
        )
        if factura is None:
            raise HTTPException(status_code=404)
        pagos = (
            (
                await sesion.execute(
                    text(
                        "SELECT uuid::text AS uuid, valor, recibido_en, medio, referencia, anulado_en, motivo_anulacion"
                        " FROM plataforma.pagos WHERE factura_id = :f ORDER BY registrado_en"
                    ),
                    {"f": factura["id"]},
                )
            )
            .mappings()
            .all()
        )
    contexto = {
        "sitio": sitio,
        "activa": activa,
        "factura": factura,
        "pagos": pagos,
        "medios": facturacion.MEDIOS_DE_PAGO,
        "error": t(error, sitio.idioma) if error else None,
        "hoy": date.today().isoformat(),
    }
    return render(request, "admin/factura.html", contexto, estado)


@router.get("/facturas/{factura_uuid}")
async def factura(
    request: Request,
    sitio: AdminActual,
    factura_uuid: UUID,
    activa: Annotated[SesionActiva, Depends(requiere_permiso("facturacion", "consultar"))],
):
    return await _detalle_factura(request, sitio, activa, factura_uuid)


@router.post("/facturas/{factura_uuid}/pagos")
async def pagar(
    request: Request,
    sitio: AdminActual,
    _csrf: Csrf,
    factura_uuid: UUID,
    activa: Annotated[SesionActiva, Depends(requiere_permiso("facturacion", "crear"))],
    valor: Annotated[TextoSeguro, Form(max_length=20)] = "",
    medio: Annotated[TextoSeguro, Form(max_length=20)] = "",
    referencia: Annotated[TextoSeguro, Form(max_length=100)] = "",
    recibido_en: Annotated[TextoSeguro, Form(max_length=10)] = "",
):
    cantidad, fecha = facturacion.leer_valor(valor), _fecha(recibido_en)
    error = None
    if cantidad is None:
        error = "facturas.error_valor"
    elif fecha is None:
        error = "facturas.error_fecha"
    else:
        try:
            async with _sesion(request, activa) as sesion:
                await facturacion.registrar_pago(sesion, str(factura_uuid), cantidad, medio, referencia.strip(), fecha)
        except ErrorFacturacion as e:
            error = e.clave
    if error:
        return await _detalle_factura(request, sitio, activa, factura_uuid, error=error, estado=400)
    return redirigir(request, f"/facturas/{factura_uuid}")


@router.post("/facturas/{factura_uuid}/pagos/{pago_uuid}/anular")
async def anular_pago(
    request: Request,
    sitio: AdminActual,
    _csrf: Csrf,
    factura_uuid: UUID,
    pago_uuid: UUID,
    activa: Annotated[SesionActiva, Depends(requiere_permiso("facturacion", "eliminar"))],
    motivo: Annotated[TextoSeguro, Form(max_length=300)] = "",
):
    try:
        async with _sesion(request, activa) as sesion:
            pertenece = await sesion.scalar(
                text(
                    "SELECT true FROM plataforma.pagos p JOIN plataforma.facturas f ON f.id = p.factura_id"
                    " WHERE p.uuid = :p AND f.uuid = :f"
                ),
                {"p": pago_uuid, "f": factura_uuid},
            )
            if not pertenece:
                raise HTTPException(status_code=404)
            await facturacion.anular_pago(sesion, str(pago_uuid), motivo.strip())
    except ErrorFacturacion as error:
        return await _detalle_factura(request, sitio, activa, factura_uuid, error=error.clave, estado=400)
    return redirigir(request, f"/facturas/{factura_uuid}")


@router.post("/facturas/{factura_uuid}/anular")
async def anular_factura(
    request: Request,
    sitio: AdminActual,
    _csrf: Csrf,
    factura_uuid: UUID,
    activa: Annotated[SesionActiva, Depends(requiere_permiso("facturacion", "eliminar"))],
    motivo: Annotated[TextoSeguro, Form(max_length=300)] = "",
):
    try:
        async with _sesion(request, activa) as sesion:
            await facturacion.anular_factura(sesion, str(factura_uuid), motivo.strip())
    except ErrorFacturacion as error:
        return await _detalle_factura(request, sitio, activa, factura_uuid, error=error.clave, estado=400)
    return redirigir(request, f"/facturas/{factura_uuid}")


# --- Precios y campañas ---


async def _pagina_precios(request, sitio, activa, *, errores=(), estado=200):
    async with _sesion(request, activa) as sesion:
        precios = (
            (
                await sesion.execute(
                    text(
                        "SELECT pr.pais, p.nombre AS plan, pr.tipo_licencia, pr.moneda, pr.valor, pr.vigente_desde"
                        " FROM plataforma.precios pr JOIN plataforma.planes p ON p.id = pr.plan_id"
                        " ORDER BY pr.pais, p.nombre, pr.tipo_licencia, pr.vigente_desde DESC"
                    )
                )
            )
            .mappings()
            .all()
        )
        campanas = (
            (
                await sesion.execute(
                    text(
                        "SELECT uuid::text AS uuid, nombre, porcentaje, tipo_licencia, desde, hasta, activa"
                        " FROM plataforma.campanas ORDER BY desde DESC"
                    )
                )
            )
            .mappings()
            .all()
        )
        opciones = {
            "paises": (await sesion.execute(text('SELECT codigo, nombre FROM "global".paises WHERE habilitado'))).all(),
            "planes": (
                await sesion.execute(text("SELECT uuid::text, nombre FROM plataforma.planes WHERE activo"))
            ).all(),
            "monedas": (await sesion.execute(text('SELECT codigo FROM "global".monedas ORDER BY codigo')))
            .scalars()
            .all(),
            "licencias": (
                await sesion.execute(text("SELECT codigo, nombre FROM plataforma.tipos_licencia ORDER BY codigo"))
            ).all(),
        }
    contexto = {
        "sitio": sitio,
        "activa": activa,
        "precios": precios,
        "campanas": campanas,
        "errores": list(errores),
        **opciones,
    }
    return render(request, "admin/precios.html", contexto, estado)


@router.get("/precios")
async def precios(
    request: Request,
    sitio: AdminActual,
    activa: Annotated[SesionActiva, Depends(requiere_permiso("facturacion", "consultar"))],
):
    return await _pagina_precios(request, sitio, activa)


@router.post("/precios")
async def precio_nuevo(
    request: Request,
    sitio: AdminActual,
    _csrf: Csrf,
    activa: Annotated[SesionActiva, Depends(requiere_permiso("facturacion", "crear"))],
    pais: Annotated[TextoSeguro, Form(max_length=3)] = "",
    plan: Annotated[TextoSeguro, Form(max_length=36)] = "",
    tipo_licencia: Annotated[TextoSeguro, Form(max_length=20)] = "",
    moneda: Annotated[TextoSeguro, Form(max_length=3)] = "",
    valor: Annotated[TextoSeguro, Form(max_length=20)] = "",
    vigente_desde: Annotated[TextoSeguro, Form(max_length=10)] = "",
):
    cantidad, desde = facturacion.leer_valor(valor), _fecha(vigente_desde)
    if cantidad is None or desde is None:
        return await _pagina_precios(
            request, sitio, activa, errores=[t("precios.error_datos", sitio.idioma)], estado=400
        )
    try:
        async with _sesion(request, activa) as sesion:
            await sesion.execute(
                text(
                    "INSERT INTO plataforma.precios (pais, plan_id, tipo_licencia, moneda, valor, vigente_desde)"
                    " SELECT :pais, p.id, :t, :m, :v, :d FROM plataforma.planes p"
                    " WHERE p.uuid = CAST(:plan AS uuid) AND p.activo"
                ),
                {"pais": pais, "t": tipo_licencia, "m": moneda, "v": cantidad, "d": desde, "plan": plan},
            )
    except IntegrityError:
        return await _pagina_precios(
            request, sitio, activa, errores=[t("precios.error_repetido", sitio.idioma)], estado=400
        )
    except DBAPIError:
        return await _pagina_precios(
            request, sitio, activa, errores=[t("precios.error_datos", sitio.idioma)], estado=400
        )
    return redirigir(request, "/precios")


@router.post("/campanas")
async def campana_nueva(
    request: Request,
    sitio: AdminActual,
    _csrf: Csrf,
    activa: Annotated[SesionActiva, Depends(requiere_permiso("facturacion", "crear"))],
    nombre: Annotated[TextoSeguro, Form(max_length=120)] = "",
    porcentaje: Annotated[TextoSeguro, Form(max_length=6)] = "",
    tipo_licencia: Annotated[TextoSeguro, Form(max_length=20)] = "",
    desde: Annotated[TextoSeguro, Form(max_length=10)] = "",
    hasta: Annotated[TextoSeguro, Form(max_length=10)] = "",
):
    pct, inicio, fin = facturacion.leer_valor(porcentaje), _fecha(desde), _fecha(hasta)
    valido = pct is not None and pct < 100 and inicio and fin and fin >= inicio and 2 <= len(nombre.strip()) <= 120
    if not valido:
        return await _pagina_precios(
            request, sitio, activa, errores=[t("campanas.error_datos", sitio.idioma)], estado=400
        )
    try:
        async with _sesion(request, activa) as sesion:
            await sesion.execute(
                text(
                    "INSERT INTO plataforma.campanas (nombre, porcentaje, tipo_licencia, desde, hasta)"
                    " VALUES (:n, :p, NULLIF(:t, ''), :d, :h)"
                ),
                {"n": nombre.strip(), "p": pct, "t": tipo_licencia, "d": inicio, "h": fin},
            )
    except DBAPIError:
        return await _pagina_precios(
            request, sitio, activa, errores=[t("campanas.error_datos", sitio.idioma)], estado=400
        )
    return redirigir(request, "/precios")


@router.post("/campanas/{campana_uuid}/desactivar")
async def campana_desactivar(
    request: Request,
    sitio: AdminActual,
    _csrf: Csrf,
    campana_uuid: UUID,
    activa: Annotated[SesionActiva, Depends(requiere_permiso("facturacion", "modificar"))],
):
    async with _sesion(request, activa) as sesion:
        cambiada = await sesion.scalar(
            text("UPDATE plataforma.campanas SET activa = false WHERE uuid = :c RETURNING id"), {"c": campana_uuid}
        )
    if cambiada is None:
        raise HTTPException(status_code=404)
    return redirigir(request, "/precios")


# --- Soporte ---


@router.get("/soporte")
async def soporte(
    request: Request,
    sitio: AdminActual,
    activa: Annotated[SesionActiva, Depends(requiere_permiso("soporte", "consultar"))],
):
    async with _sesion(request, activa) as sesion:
        autorizaciones = (
            (await sesion.execute(text("SELECT * FROM plataforma.autorizaciones_soporte()"))).mappings().all()
        )
    contexto = {
        "sitio": sitio,
        "activa": activa,
        "autorizaciones": autorizaciones,
        "error": request.query_params.get("error"),
    }
    return render(request, "admin/soporte.html", contexto)


@router.post("/soporte/{laboratorio_uuid}/iniciar")
async def iniciar_soporte(
    request: Request,
    sitio: AdminActual,
    _csrf: Csrf,
    laboratorio_uuid: UUID,
    activa: Annotated[SesionActiva, Depends(requiere_permiso("soporte", "crear"))],
):
    """Emite el tiquete de un solo uso (2 minutos) y muestra el enlace al laboratorio. Sin autorización → 403.

    No redirige: la CSP (form-action 'self') impide que un formulario termine en otro origen, y abrirla a
    otros subdominios debilitaría la protección de todos los formularios.
    """
    token = cripto.token_aleatorio()
    try:
        async with _sesion(request, activa) as sesion:
            subdominio = await sesion.scalar(
                text("SELECT plataforma.iniciar_soporte(:l, :e, :n, :h)"),
                {
                    "l": laboratorio_uuid,
                    "e": activa.usuario.email,
                    "n": activa.usuario.nombre,
                    "h": cripto.hash_token(token),
                },
            )
            await registrar_acceso(
                sesion,
                "soporte",
                operacion="ACCESO",
                detalle={"laboratorio": str(laboratorio_uuid), "evento": "tiquete"},
            )
    except DBAPIError:
        async with _sesion(request, activa) as sesion:
            await registrar_acceso(
                sesion, "soporte", operacion="ACCESO", denegado=True, detalle={"laboratorio": str(laboratorio_uuid)}
            )
        raise HTTPException(status_code=403) from None
    enlace = f"{get_settings().url_sitio(subdominio)}/soporte/entrar/{token}"
    return render(request, "admin/soporte_tiquete.html", {"sitio": sitio, "activa": activa, "enlace": enlace})
