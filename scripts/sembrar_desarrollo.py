"""Siembra datos sintéticos en la base de DESARROLLO (nunca en producción). Idempotente.

- Laboratorios lab-a y lab-b (rol de la plataforma, como lo hará el Admin Hub).
- Roles del sistema y usuarios de prueba en cada laboratorio (rol de la aplicación, con RLS).
  Contraseña y secreto TOTP salen de DEV_CLAVE_USUARIOS y DEV_TOTP_SECRETO del .env.

    .venv/bin/python scripts/sembrar_desarrollo.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.auth import repositorio  # noqa: E402
from app.auth.roles_sistema import crear_roles_sistema  # noqa: E402
from app.core import db  # noqa: E402
from app.core.config import get_settings  # noqa: E402

# (tenant_id, subdominio, nombre, NIT ficticio)
LABORATORIOS = [
    ("lab_a", "lab-a", "Laboratorio A Sintético", "900000001"),
    ("lab_b", "lab-b", "Laboratorio B Sintético", "900000002"),
]

# (email local, nombre, tipo, roles, con TOTP)
USUARIOS = [
    ("admin", "Administrador", "PERSONAL", ("ADMINISTRADOR",), True),
    ("recepcion", "Recepción", "PERSONAL", ("RECEPCION",), True),
    ("paciente", "Paciente Sintético", "PACIENTE", (), False),
]


async def sembrar() -> None:
    settings = get_settings()
    if settings.entorno == "produccion":
        raise SystemExit("Este script no se ejecuta en producción.")
    if not settings.dev_clave_usuarios or not settings.dev_totp_secreto:
        raise SystemExit("Faltan DEV_CLAVE_USUARIOS y DEV_TOTP_SECRETO en el .env.")

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

    clave = settings.dev_clave_usuarios.get_secret_value()
    secreto = settings.dev_totp_secreto.get_secret_value()
    for tenant_id, subdominio, _, _ in LABORATORIOS:
        async with db.sesion_tenant(tenant_id) as sesion:
            await crear_roles_sistema(sesion)
            for local, nombre, tipo, roles, totp in USUARIOS:
                email = f"{local}@{subdominio}.test"
                if await repositorio.buscar_usuario_por_email(sesion, email):
                    continue
                usuario_id = await repositorio.crear_usuario(
                    sesion, email=email, nombre=nombre, tipo=tipo, clave=clave, roles=roles
                )
                if totp:
                    usuario = await repositorio.buscar_usuario(sesion, usuario_id)
                    await repositorio.guardar_totp(sesion, usuario, secreto)
                    await repositorio.confirmar_totp(sesion, usuario_id, 0)
    await db.cerrar()
    print("Datos sintéticos en", settings.db_name, "· usuarios:", ", ".join(f"{u[0]}@<lab>.test" for u in USUARIOS))


if __name__ == "__main__":
    asyncio.run(sembrar())
