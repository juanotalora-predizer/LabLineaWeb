"""Proceso de tareas en segundo plano (spec infraestructura/0012).

    .venv/bin/python trabajador.py

Se detiene limpiamente con Ctrl+C o SIGTERM: termina la tarea en curso y sale.
"""

import asyncio
import logging
import signal

import app.auth.invitaciones  # noqa: F401 — registra el manejador de invitaciones
from app.core import db, tareas


async def main() -> None:
    parar = asyncio.Event()
    bucle = asyncio.get_running_loop()
    for senal in (signal.SIGINT, signal.SIGTERM):
        bucle.add_signal_handler(senal, parar.set)
    try:
        await tareas.trabajar(parar)
    finally:
        await db.cerrar()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(main())
