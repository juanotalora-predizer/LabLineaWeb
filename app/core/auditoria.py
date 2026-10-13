"""Auditoría de accesos desde la aplicación (spec infraestructura/0007, sección 5).

Las escrituras las registran los triggers de la base (lab.auditar). Aquí se registra lo que un
trigger no ve: lecturas y exportaciones de datos personales o de salud, y accesos denegados.
El usuario y la IP salen de la transacción (`sesion_tenant`), no de los argumentos.

`detalle` describe el acceso con identificadores y conteos, nunca con contenido clínico.
"""

import json
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

Operacion = Literal["READ", "EXPORT", "ACCESO"]

_SQL_REGISTRAR = text("SELECT lab.registrar_acceso(:tabla, :operacion, :registro, :resultado, CAST(:detalle AS jsonb))")


async def registrar_acceso(
    sesion: AsyncSession,
    tabla: str,
    *,
    operacion: Operacion = "READ",
    registro_id: int | None = None,
    denegado: bool = False,
    detalle: dict | None = None,
) -> None:
    await sesion.execute(
        _SQL_REGISTRAR,
        {
            "tabla": tabla,
            "operacion": operacion,
            "registro": registro_id,
            "resultado": "DENEGADO" if denegado else "EXITO",
            "detalle": json.dumps(detalle) if detalle is not None else None,
        },
    )
