"""Roles del personal de la plataforma (spec funcional/0005, sección 1). Ninguno da acceso a datos clínicos."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

TODAS = ("consultar", "crear", "modificar", "eliminar")
LECTURA = ("consultar",)
ESCRITURA = ("consultar", "crear", "modificar")

# codigo: (nombre, {modulo: operaciones})
ROLES_PLATAFORMA = {
    "ADMIN_MAESTRO": (
        "Administrador maestro",
        {m: TODAS for m in ("laboratorios", "planes", "suscripciones", "facturacion", "usuarios", "soporte")},
    ),
    "GERENTE_COMERCIAL": (
        "Gerente comercial",
        {"laboratorios": ESCRITURA, "planes": LECTURA, "suscripciones": ESCRITURA},
    ),
    "SOPORTE_FINANCIERO": (
        "Soporte financiero",
        {"laboratorios": LECTURA, "suscripciones": ESCRITURA, "facturacion": ESCRITURA},
    ),
    # Entra a un laboratorio solo con su autorización vigente, en modo de solo lectura (etapa 5).
    "SOPORTE_TECNICO": ("Soporte técnico", {"laboratorios": LECTURA, "soporte": ESCRITURA}),
}


async def crear_roles_plataforma(sesion: AsyncSession) -> None:
    """Crea (o completa) los roles de la plataforma. Idempotente. Requiere una `sesion_plataforma`."""
    for codigo, (nombre, modulos) in ROLES_PLATAFORMA.items():
        rol_id = await sesion.scalar(
            text(
                "INSERT INTO plataforma.roles (codigo, nombre, sistema) VALUES (:c, :n, true)"
                " ON CONFLICT (codigo) DO UPDATE SET nombre = EXCLUDED.nombre RETURNING id"
            ),
            {"c": codigo, "n": nombre},
        )
        for modulo, operaciones in modulos.items():
            await sesion.execute(
                text(
                    "INSERT INTO plataforma.rol_permisos (rol_id, modulo, consultar, crear, modificar, eliminar)"
                    " VALUES (:r, :m, :c1, :c2, :c3, :c4)"
                    " ON CONFLICT (rol_id, modulo) DO UPDATE SET consultar = EXCLUDED.consultar,"
                    " crear = EXCLUDED.crear, modificar = EXCLUDED.modificar, eliminar = EXCLUDED.eliminar"
                ),
                {"r": rol_id, "m": modulo, **{f"c{i + 1}": op in operaciones for i, op in enumerate(TODAS)}},
            )
