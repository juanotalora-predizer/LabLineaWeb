"""Siembra datos sintéticos en la base de DESARROLLO (nunca en producción). Idempotente.

- Laboratorios lab-a y lab-b (rol de la plataforma, como lo hará el Admin Hub).
- Roles del sistema y usuarios de prueba en cada laboratorio (rol de la aplicación, con RLS).
  Contraseña y secreto TOTP salen de DEV_CLAVE_USUARIOS y DEV_TOTP_SECRETO del .env.
- Pacientes sintéticos (scripts/sinteticos.py) como usuarios del portal en cada laboratorio.
- Admin Hub: roles de la plataforma y admin@admin.test (ADMIN_MAESTRO), con la misma clave y TOTP.
- Suscripciones ad honorem vigentes y precios de ejemplo (plan completo, Colombia).
- Catálogo sintético de Lablinea en lab-a, si aún no tiene exámenes (scripts/lablinea_sintetico.py).

    .venv/bin/python scripts/sembrar_desarrollo.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.admin.roles import crear_roles_plataforma  # noqa: E402
from app.auth import repositorio  # noqa: E402
from app.auth.roles_sistema import crear_roles_sistema  # noqa: E402
from app.catalogo import importador  # noqa: E402
from app.core import db  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from scripts.lablinea_sintetico import generar as generar_catalogo  # noqa: E402
from scripts.sinteticos import generar_personas  # noqa: E402

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

PACIENTES_POR_LABORATORIO = 10


async def _existe_y_reactivar(sesion, email: str) -> bool:
    """Idempotencia: el usuario ya existe (activo o no). Un escaneo activo de ZAP puede haberlo desactivado."""
    return (
        await sesion.scalar(text("UPDATE usuarios SET estado = 'ACTIVO' WHERE email = :e RETURNING true"), {"e": email})
    ) is not None


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
                    " (tenant_id, subdominio, nombre_comercial, identificador_fiscal, pais, plan_id)"
                    " VALUES (:t, :s, :n, :nit, 'COL', (SELECT id FROM plataforma.planes WHERE codigo = 'COMPLETO'))"
                    # Un escaneo activo pudo cambiarle el plan: vuelve al completo.
                    " ON CONFLICT (tenant_id) DO UPDATE SET plan_id = EXCLUDED.plan_id"
                ),
                {"t": tenant_id, "s": subdominio, "n": nombre, "nit": nit},
            )
            # Suscripción ad honorem vigente (un escaneo activo pudo suspenderla, cancelarla o vencerla).
            await conexion.execute(
                text(
                    "INSERT INTO plataforma.suscripciones (laboratorio_id, tipo_licencia)"
                    " SELECT id, 'AD_HONOREM' FROM plataforma.laboratorios WHERE tenant_id = :t"
                    " ON CONFLICT (laboratorio_id) DO UPDATE SET tipo_licencia = 'AD_HONOREM', estado = 'ACTIVA',"
                    " fin = NULL, motivo_suspension = NULL, renovacion_automatica = false"
                ),
                {"t": tenant_id},
            )
        # Precios de ejemplo del plan completo en Colombia (datos sintéticos).
        await conexion.execute(
            text(
                "INSERT INTO plataforma.precios (pais, plan_id, tipo_licencia, moneda, valor, vigente_desde)"
                " SELECT 'COL', p.id, v.tipo, 'COP', v.valor, DATE '2026-01-01' FROM plataforma.planes p,"
                " (VALUES ('MENSUAL', 450000), ('ANUAL', 4500000)) AS v (tipo, valor)"
                " WHERE p.codigo = 'COMPLETO' ON CONFLICT DO NOTHING"
            )
        )
    await engine.dispose()

    clave = settings.dev_clave_usuarios.get_secret_value()
    secreto = settings.dev_totp_secreto.get_secret_value()
    for tenant_id, subdominio, _, _ in LABORATORIOS:
        async with db.sesion_tenant(tenant_id) as sesion:
            await crear_roles_sistema(sesion)
            for local, nombre, tipo, roles, totp in USUARIOS:
                email = f"{local}@{subdominio}.test"
                if await _existe_y_reactivar(sesion, email):
                    continue
                usuario_id = await repositorio.crear_usuario(
                    sesion, email=email, nombre=nombre, tipo=tipo, clave=clave, roles=roles
                )
                if totp:
                    usuario = await repositorio.buscar_usuario(sesion, usuario_id)
                    await repositorio.guardar_totp(sesion, usuario, secreto)
                    await repositorio.confirmar_totp(sesion, usuario_id, 0)
            # Tipos de documento del país del laboratorio: el generador no conoce ningún país.
            tipos = tuple(
                (
                    await sesion.execute(
                        text(
                            'SELECT codigo FROM "global".tipos_documento'
                            " WHERE pais = 'COL' AND aplica_a = 'PERSONA' AND activo ORDER BY codigo"
                        )
                    )
                ).scalars()
            )
            semilla = sum(map(ord, tenant_id))
            for persona in generar_personas(PACIENTES_POR_LABORATORIO, semilla=semilla, tipos_documento=tipos):
                if not await _existe_y_reactivar(sesion, persona.email):
                    await repositorio.crear_usuario(
                        sesion, email=persona.email, nombre=persona.nombre_completo, tipo="PACIENTE", clave=clave
                    )
    async with db.sesion_tenant("lab_a") as sesion:
        if not await sesion.scalar(text("SELECT count(*) FROM lab.examenes")):
            plan = importador.analizar(
                importador.leer_paquete(generar_catalogo()), await importador.existentes(sesion), "COP"
            )
            await importador.cargar(sesion, plan)
    async with db.sesion_plataforma() as sesion:
        await crear_roles_plataforma(sesion)
        if not await _existe_y_reactivar(sesion, "admin@admin.test"):
            usuario_id = await repositorio.crear_usuario(
                sesion,
                email="admin@admin.test",
                nombre="Administración Sintética",
                tipo="PERSONAL",
                clave=clave,
                roles=("ADMIN_MAESTRO",),
            )
            usuario = await repositorio.buscar_usuario(sesion, usuario_id)
            await repositorio.guardar_totp(sesion, usuario, secreto)
            await repositorio.confirmar_totp(sesion, usuario_id, 0)
    await db.cerrar()
    print("Datos sintéticos en", settings.db_name, "· usuarios:", ", ".join(f"{u[0]}@<lab>.test" for u in USUARIOS))


if __name__ == "__main__":
    asyncio.run(sembrar())
