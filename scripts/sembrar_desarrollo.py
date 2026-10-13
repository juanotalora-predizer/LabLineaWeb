"""Siembra laboratorios sintéticos en la base de DESARROLLO (nunca en producción).

Usa el rol de la plataforma (el mismo que usará el Admin Hub). Es idempotente.

    .venv/bin/python scripts/sembrar_desarrollo.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.core.config import get_settings  # noqa: E402

# (tenant_id, subdominio, nombre, NIT ficticio)
LABORATORIOS = [
    ("lab_a", "lab-a", "Laboratorio A Sintético", "900000001"),
    ("lab_b", "lab-b", "Laboratorio B Sintético", "900000002"),
]


async def sembrar() -> None:
    settings = get_settings()
    if settings.entorno == "produccion":
        raise SystemExit("Este script no se ejecuta en producción.")
    engine = create_async_engine(settings.url_plataforma(settings.db_name), poolclass=NullPool)
    async with engine.begin() as conexion:
        for tenant_id, subdominio, nombre, nit in LABORATORIOS:
            await conexion.execute(
                text(
                    "INSERT INTO plataforma.laboratorios"
                    " (tenant_id, subdominio, nombre_comercial, identificador_fiscal, pais)"
                    " VALUES (:t, :s, :n, :nit, 'COL') ON CONFLICT (tenant_id) DO NOTHING"
                ),
                {"t": tenant_id, "s": subdominio, "n": nombre, "nit": nit},
            )
    await engine.dispose()
    print(f"Laboratorios sintéticos en {settings.db_name}: " + ", ".join(s for _, s, _, _ in LABORATORIOS))


if __name__ == "__main__":
    asyncio.run(sembrar())
