"""Suscripciones y facturación de la plataforma (spec funcional/0005, secciones 3 y 4; etapa 5).

- Dinero siempre en `Decimal` y redondeo al medio hacia arriba con los decimales de la moneda.
- El saldo y el estado de una factura los recalcula la base con cada pago (trigger); aquí está el mismo
  cálculo como función pura (`estado_por_pagos`) para probarlo con hypothesis y compararlo con la base.
- Al quedar pagada, la base extiende la suscripción hasta el final del periodo facturado.
- Mantenimiento periódico del trabajador: vence suscripciones, encola avisos de renovación y genera la
  factura del siguiente periodo de las suscripciones con renovación automática.
"""

import logging
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import db
from app.core.tareas import mantenimiento

log = logging.getLogger(__name__)

DIAS_PARA_PAGAR = 15
DIAS_ANTES_RENOVACION = 7
MEDIOS_DE_PAGO = ("TRANSFERENCIA", "CONSIGNACION", "EFECTIVO", "TARJETA", "OTRO")
_VALOR = re.compile(r"^\d{1,12}(\.\d{1,2})?$")
CIEN = Decimal(100)


class ErrorFacturacion(Exception):  # noqa: N818
    """Regla de negocio incumplida; `clave` es el texto del catálogo que ve el usuario."""

    def __init__(self, clave: str) -> None:
        super().__init__(clave)
        self.clave = clave


# --- Cálculos puros ---


@dataclass(frozen=True)
class Importes:
    valor_lista: Decimal
    descuento: Decimal
    subtotal: Decimal
    impuesto: Decimal
    total: Decimal


def _redondear(valor: Decimal, decimales: int) -> Decimal:
    return valor.quantize(Decimal(10) ** -decimales, rounding=ROUND_HALF_UP)


def calcular_importes(
    valor_lista: Decimal, descuento_porcentaje: Decimal, impuesto_porcentaje: Decimal, decimales: int = 2
) -> Importes:
    """Descuento sobre el valor de lista y luego el impuesto sobre el subtotal, cada uno redondeado."""
    valor_lista = _redondear(valor_lista, decimales)
    descuento = _redondear(valor_lista * descuento_porcentaje / CIEN, decimales)
    subtotal = valor_lista - descuento
    impuesto = _redondear(subtotal * impuesto_porcentaje / CIEN, decimales)
    return Importes(valor_lista, descuento, subtotal, impuesto, subtotal + impuesto)


def estado_por_pagos(total: Decimal, pagos: list[Decimal]) -> tuple[Decimal, str]:
    """(saldo, estado) de una factura con los pagos vigentes. Un pago que supere el saldo es un error."""
    pagado = Decimal(0)
    for valor in pagos:
        if valor <= 0 or pagado + valor > total:
            raise ErrorFacturacion("facturas.error_pago_excede")
        pagado += valor
    if pagado == 0:
        return total, "PENDIENTE"
    return total - pagado, ("PAGADA" if pagado == total else "PAGADA_PARCIAL")


def leer_valor(texto: str) -> Decimal | None:
    """Valor positivo con hasta dos decimales (punto decimal, sin separador de miles); None si no es válido."""
    texto = texto.strip()
    if not _VALOR.match(texto):
        return None
    try:
        valor = Decimal(texto)
    except InvalidOperation:  # pragma: no cover — la expresión regular ya lo garantiza
        return None
    return valor if valor > 0 else None


# --- Servicios (con una sesion_plataforma) ---

_SQL_LABORATORIO = text(
    "SELECT l.id, l.pais, l.plan_id, s.id AS suscripcion_id, s.fin, s.estado, p.impuesto_servicios"
    " FROM plataforma.laboratorios l JOIN plataforma.suscripciones s ON s.laboratorio_id = l.id"
    ' JOIN "global".paises p ON p.codigo = l.pais WHERE l.uuid = :l'
)


async def generar_factura(sesion: AsyncSession, laboratorio_uuid: str, tipo_licencia: str) -> str:
    """Factura del siguiente periodo de la suscripción. Devuelve su UUID o lanza ErrorFacturacion."""
    lab = (await sesion.execute(_SQL_LABORATORIO, {"l": laboratorio_uuid})).mappings().first()
    if lab is None:
        raise ErrorFacturacion("facturas.error_laboratorio")
    if lab["estado"] == "CANCELADA":
        raise ErrorFacturacion("facturas.error_cancelada")
    licencia = (
        (
            await sesion.execute(
                text("SELECT duracion FROM plataforma.tipos_licencia WHERE codigo = :t AND facturable"),
                {"t": tipo_licencia},
            )
        )
        .mappings()
        .first()
    )
    if licencia is None:
        raise ErrorFacturacion("facturas.error_licencia")
    hoy = datetime.now(UTC).date()
    precio = (
        (
            await sesion.execute(
                text(
                    "SELECT pr.valor, pr.moneda, m.decimales FROM plataforma.precios pr"
                    ' JOIN "global".monedas m ON m.codigo = pr.moneda'
                    " WHERE pr.pais = :pais AND pr.plan_id = :plan AND pr.tipo_licencia = :t"
                    "   AND pr.vigente_desde <= :hoy"
                    " ORDER BY pr.vigente_desde DESC LIMIT 1"
                ),
                {"pais": lab["pais"], "plan": lab["plan_id"], "t": tipo_licencia, "hoy": hoy},
            )
        )
        .mappings()
        .first()
    )
    if precio is None:
        raise ErrorFacturacion("facturas.error_sin_precio")
    campana = (
        (
            await sesion.execute(
                text(
                    "SELECT id, porcentaje FROM plataforma.campanas WHERE activa AND desde <= :hoy AND hasta >= :hoy"
                    " AND (tipo_licencia IS NULL OR tipo_licencia = :t) ORDER BY porcentaje DESC, id LIMIT 1"
                ),
                {"hoy": hoy, "t": tipo_licencia},
            )
        )
        .mappings()
        .first()
    )
    # El periodo empieza donde termina el vigente (o ahora, si ya terminó o es indefinida).
    ahora = datetime.now(UTC)
    desde = lab["fin"] if lab["fin"] and lab["fin"] > ahora else ahora
    pendiente = await sesion.scalar(
        text(
            "SELECT count(*) FROM plataforma.facturas WHERE suscripcion_id = :s AND estado <> 'ANULADA'"
            " AND periodo_hasta > :desde"
        ),
        {"s": lab["suscripcion_id"], "desde": desde},
    )
    if pendiente:
        raise ErrorFacturacion("facturas.error_periodo_facturado")
    importes = calcular_importes(
        precio["valor"],
        campana["porcentaje"] if campana else Decimal(0),
        lab["impuesto_servicios"],
        precio["decimales"],
    )
    return await sesion.scalar(
        text(
            "INSERT INTO plataforma.facturas (laboratorio_id, suscripcion_id, tipo_licencia, periodo_desde,"
            " periodo_hasta, moneda, valor_lista, campana_id, descuento_porcentaje, descuento, subtotal,"
            " impuesto_porcentaje, impuesto, total, saldo, vence_en)"
            " SELECT :lab, :susc, :t, CAST(:desde AS timestamptz), CAST(:desde AS timestamptz) + tl.duracion, :moneda,"
            " :lista, :campana, :dpct, :descuento, :subtotal, :ipct, :impuesto, :total, :total,"
            " now() + make_interval(days => :dias)"
            " FROM plataforma.tipos_licencia tl WHERE tl.codigo = :t RETURNING uuid::text"
        ),
        {
            "lab": lab["id"],
            "susc": lab["suscripcion_id"],
            "t": tipo_licencia,
            "desde": desde,
            "moneda": precio["moneda"],
            "lista": importes.valor_lista,
            "campana": campana["id"] if campana else None,
            "dpct": campana["porcentaje"] if campana else Decimal(0),
            "descuento": importes.descuento,
            "subtotal": importes.subtotal,
            "ipct": lab["impuesto_servicios"],
            "impuesto": importes.impuesto,
            "total": importes.total,
            "dias": DIAS_PARA_PAGAR,
        },
    )


async def registrar_pago(
    sesion: AsyncSession, factura_uuid: str, valor: Decimal, medio: str, referencia: str, recibido_en: date
) -> None:
    if medio not in MEDIOS_DE_PAGO:
        raise ErrorFacturacion("facturas.error_medio")
    if recibido_en > datetime.now(UTC).date() + timedelta(days=1):
        raise ErrorFacturacion("facturas.error_fecha")
    factura_id = await sesion.scalar(text("SELECT id FROM plataforma.facturas WHERE uuid = :f"), {"f": factura_uuid})
    if factura_id is None:
        raise ErrorFacturacion("facturas.error_factura")
    try:
        async with sesion.begin_nested():
            await sesion.execute(
                text(
                    "INSERT INTO plataforma.pagos (factura_id, valor, recibido_en, medio, referencia)"
                    " VALUES (:f, :v, :r, :m, NULLIF(:ref, ''))"
                ),
                {"f": factura_id, "v": valor, "r": recibido_en, "m": medio, "ref": referencia},
            )
    except DBAPIError as error:
        mensaje = str(error.orig)
        if "supera el saldo" in mensaje:
            raise ErrorFacturacion("facturas.error_pago_excede") from None
        if "anulada" in mensaje:
            raise ErrorFacturacion("facturas.error_anulada") from None
        raise


async def _anular(sesion: AsyncSession, funcion: str, uuid: str, motivo: str, error_clave: str) -> None:
    if not 5 <= len(motivo) <= 300:
        raise ErrorFacturacion("facturas.error_motivo")
    sql = {
        "pago": text("SELECT plataforma.anular_pago(CAST(:u AS uuid), :m)"),
        "factura": text("SELECT plataforma.anular_factura(CAST(:u AS uuid), :m)"),
    }[funcion]
    try:
        async with sesion.begin_nested():
            await sesion.execute(sql, {"u": uuid, "m": motivo})
    except DBAPIError:
        raise ErrorFacturacion(error_clave) from None


async def anular_pago(sesion: AsyncSession, pago_uuid: str, motivo: str) -> None:
    await _anular(sesion, "pago", pago_uuid, motivo, "facturas.error_anular_pago")


async def anular_factura(sesion: AsyncSession, factura_uuid: str, motivo: str) -> None:
    await _anular(sesion, "factura", factura_uuid, motivo, "facturas.error_anular_factura")


# --- Mantenimiento periódico ---


async def renovar_automaticamente(sesion: AsyncSession) -> int:
    """Factura el siguiente periodo de las suscripciones con renovación automática que vencen pronto."""
    candidatas = (
        await sesion.execute(
            text(
                "SELECT l.uuid::text AS laboratorio, s.tipo_licencia FROM plataforma.suscripciones s"
                " JOIN plataforma.laboratorios l ON l.id = s.laboratorio_id"
                " JOIN plataforma.tipos_licencia tl ON tl.codigo = s.tipo_licencia AND tl.facturable"
                " WHERE s.renovacion_automatica AND s.estado = 'ACTIVA' AND l.estado <> 'CANCELADO'"
                "   AND s.fin IS NOT NULL AND s.fin <= now() + make_interval(days => :dias)"
            ),
            {"dias": DIAS_ANTES_RENOVACION},
        )
    ).all()
    generadas = 0
    for laboratorio, tipo in candidatas:
        try:
            async with sesion.begin_nested():
                await generar_factura(sesion, laboratorio, tipo)
            generadas += 1
        except ErrorFacturacion as error:
            # Ya facturada o sin precio: lo verá el equipo en el Admin Hub.
            log.info("Renovación automática omitida (%s): %s", laboratorio, error.clave)
    return generadas


@mantenimiento
async def mantener_suscripciones() -> None:
    async with db.sesion_plataforma(usuario_id="trabajador") as sesion:
        avisos = await sesion.scalar(text("SELECT plataforma.mantener_suscripciones()"))
        facturas = await renovar_automaticamente(sesion)
    log.info("Suscripciones: %d avisos de renovación, %d facturas automáticas", avisos, facturas)
