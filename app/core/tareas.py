"""Cola de tareas en segundo plano sobre PostgreSQL (spec infraestructura/0012).

- `encolar` se llama dentro de `sesion_tenant`: la tarea queda del laboratorio de la transacción
  y se confirma junto con el resto de la transacción (si esta se revierte, la tarea no existe).
- El trabajador toma una tarea con plazo y ficha (`cola.tomar`), ejecuta el manejador en una
  transacción con el laboratorio DE LA TAREA y la completa en esa misma transacción: los efectos
  en la base ocurren una sola vez. Si la ficha ya no es la vigente, todo se revierte.
- Si el manejador falla, la tarea se reintenta con espera exponencial hasta `max_intentos`.
- Los datos de una tarea son solo identificadores (sin datos de salud) y los errores se guardan y
  registran solo con el nombre de la excepción, nunca con su mensaje.
"""

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import db

log = logging.getLogger(__name__)

PLAZO_SEGUNDOS = 300
ESPERA_BASE_SEGUNDOS = 30
ESPERA_MAXIMA_SEGUNDOS = 3600
MESES_DE_PARTICIONES = 3
_TEXTO_MAXIMO = 200

Manejador = Callable[[AsyncSession, dict], Awaitable[None]]
MANEJADORES: dict[str, Manejador] = {}


class ErrorPermanente(Exception):  # noqa: N818
    """El manejador no debe reintentarse (p. ej. el registro ya no existe)."""


class FichaVencida(Exception):  # noqa: N818
    """Otro trabajador tomó la tarea al vencer el plazo: se revierte lo hecho."""


def tarea(tipo: str) -> Callable[[Manejador], Manejador]:
    """Registra el manejador de un tipo de tarea."""

    def registrar(funcion: Manejador) -> Manejador:
        MANEJADORES[tipo] = funcion
        return funcion

    return registrar


def _validar_datos(datos: dict) -> None:
    """Solo valores simples: los datos son identificadores, no documentos ni datos de salud."""
    for clave, valor in datos.items():
        if not isinstance(clave, str) or len(clave) > 64:
            raise ValueError("clave de datos no válida")
        if isinstance(valor, str):
            if len(valor) > _TEXTO_MAXIMO:
                raise ValueError("valor de datos demasiado largo")
        elif valor is not None and not isinstance(valor, bool | int):
            raise ValueError("los datos de una tarea solo admiten texto corto, enteros, booleanos o nulos")


async def encolar(
    sesion: AsyncSession,
    tipo: str,
    datos: dict | None = None,
    *,
    clave_unica: str | None = None,
    en_segundos: int = 0,
    max_intentos: int = 5,
) -> str:
    """Encola una tarea del laboratorio de la sesión y devuelve su UUID.

    Con `clave_unica`, encolar dos veces lo mismo devuelve la tarea existente.
    """
    datos = datos or {}
    _validar_datos(datos)
    return str(
        await sesion.scalar(
            text("SELECT cola.encolar(:tipo, CAST(:datos AS jsonb), :clave, :segundos, :max)"),
            {
                "tipo": tipo,
                "datos": json.dumps(datos),
                "clave": clave_unica,
                "segundos": en_segundos,
                "max": max_intentos,
            },
        )
    )


@dataclass(frozen=True)
class TareaTomada:
    id: int
    uuid: str
    tenant_id: str
    tipo: str
    datos: dict
    intentos: int
    max_intentos: int
    ficha: str


async def _tomar(plazo_segundos: int) -> TareaTomada | None:
    async with db.engine_app().begin() as conexion:
        fila = (
            (
                await conexion.execute(
                    text(
                        "SELECT id, uuid::text AS uuid, tenant_id, tipo, datos, intentos, max_intentos,"
                        " ficha::text AS ficha FROM cola.tomar(:plazo)"
                    ),
                    {"plazo": plazo_segundos},
                )
            )
            .mappings()
            .first()
        )
    return TareaTomada(**fila) if fila else None


async def _fallar(tarea: TareaTomada, error: str, espera: int, reintentar: bool) -> str | None:
    async with db.engine_app().begin() as conexion:
        return await conexion.scalar(
            text("SELECT cola.fallar(:id, CAST(:ficha AS uuid), :error, :espera, :reintentar)"),
            {
                "id": tarea.id,
                "ficha": tarea.ficha,
                "error": error[:_TEXTO_MAXIMO],
                "espera": espera,
                "reintentar": reintentar,
            },
        )


def espera_para(intento: int, base: int = ESPERA_BASE_SEGUNDOS) -> int:
    """Espera exponencial: base, 2·base, 4·base… hasta una hora."""
    return min(base * 2 ** max(intento - 1, 0), ESPERA_MAXIMA_SEGUNDOS)


async def procesar_una(*, plazo_segundos: int = PLAZO_SEGUNDOS, espera_base: int = ESPERA_BASE_SEGUNDOS) -> bool:
    """Toma y ejecuta una tarea. Devuelve False si no había ninguna disponible."""
    tarea_tomada = await _tomar(plazo_segundos)
    if tarea_tomada is None:
        return False
    manejador = MANEJADORES.get(tarea_tomada.tipo)
    try:
        if manejador is None:
            raise ErrorPermanente("tipo de tarea sin manejador")
        # Usuario de auditoría: la propia tarea, para distinguir sus escrituras de las de una persona.
        async with db.sesion_tenant(tarea_tomada.tenant_id, usuario_id=f"tarea:{tarea_tomada.uuid}") as sesion:
            await manejador(sesion, tarea_tomada.datos)
            completada = await sesion.scalar(
                text("SELECT cola.completar(:id, CAST(:ficha AS uuid))"),
                {"id": tarea_tomada.id, "ficha": tarea_tomada.ficha},
            )
            if not completada:
                raise FichaVencida
    except FichaVencida:
        log.warning("Tarea %s (%s): plazo vencido, otro trabajador la tomó", tarea_tomada.uuid, tarea_tomada.tipo)
    except Exception as exc:
        # Solo el nombre de la excepción: su mensaje podría llevar datos del registro.
        nombre = type(exc).__name__
        reintentar = not isinstance(exc, ErrorPermanente)
        estado = await _fallar(tarea_tomada, nombre, espera_para(tarea_tomada.intentos, espera_base), reintentar)
        log.warning(
            "Tarea %s (%s) falló en el intento %d de %d: %s → %s",
            tarea_tomada.uuid,
            tarea_tomada.tipo,
            tarea_tomada.intentos,
            tarea_tomada.max_intentos,
            nombre,
            estado,
        )
    else:
        log.info("Tarea %s (%s) completada", tarea_tomada.uuid, tarea_tomada.tipo)
    return True


async def mantener_particiones(meses: int = MESES_DE_PARTICIONES) -> None:
    """Crea las particiones de auditoría del mes actual y los siguientes (idempotente)."""
    hoy = datetime.now(UTC).date().replace(day=1)
    async with db.engine_app().begin() as conexion:
        for m in range(meses + 1):
            anio, mes = divmod(hoy.month - 1 + m, 12)
            await conexion.execute(
                text("SELECT lab.crear_particion_auditoria(:mes)"),
                {"mes": hoy.replace(year=hoy.year + anio, month=mes + 1)},
            )


async def trabajar(parar: asyncio.Event, *, intervalo: float = 1.0, mantenimiento_cada: float = 86400.0) -> None:
    """Bucle del trabajador: procesa tareas hasta que se active `parar`."""
    proximo_mantenimiento = 0.0
    bucle = asyncio.get_running_loop()
    while not parar.is_set():
        if bucle.time() >= proximo_mantenimiento:
            await mantener_particiones()
            proximo_mantenimiento = bucle.time() + mantenimiento_cada
        if not await procesar_una():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(parar.wait(), intervalo)
