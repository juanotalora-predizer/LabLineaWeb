"""Roles iniciales de cada laboratorio (spec infraestructura/0008). El laboratorio puede crear más."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

TODAS = ("consultar", "crear", "modificar", "eliminar")
ROL_SOPORTE = "SOPORTE"
LECTURA = ("consultar",)
ESCRITURA = ("consultar", "crear", "modificar")

# codigo: (nombre, {modulo: operaciones}, acciones especiales)
ROLES = {
    "ADMINISTRADOR": (
        "Administrador del laboratorio",
        {
            m: TODAS
            for m in ("usuarios", "configuracion", "pacientes", "ordenes", "caja", "muestras", "resultados", "reportes")
        },
        (
            "PRECERRAR_ORDEN",
            "ANULAR_ORDEN",
            "AUTORIZAR_DESCUENTO",
            "ABRIR_CAJA",
            "CERRAR_CAJA",
            "LIBERAR_CON_EXCEPCION",
            "AUTORIZAR_SOPORTE",
        ),
    ),
    "RECEPCION": (
        "Recepción y caja",
        {"pacientes": ESCRITURA, "ordenes": ESCRITURA, "caja": ESCRITURA},
        ("PRECERRAR_ORDEN", "ABRIR_CAJA", "CERRAR_CAJA"),
    ),
    "FLEBOTOMIA": ("Toma de muestras", {"pacientes": LECTURA, "ordenes": LECTURA, "muestras": ESCRITURA}, ()),
    "BACTERIOLOGO": (
        "Bacteriólogo",
        {"pacientes": LECTURA, "ordenes": LECTURA, "muestras": ESCRITURA, "resultados": ESCRITURA},
        (),
    ),
    "VALIDADOR": (
        "Profesional que valida",
        {"pacientes": LECTURA, "ordenes": LECTURA, "muestras": LECTURA, "resultados": ESCRITURA},
        ("VALIDAR_RESULTADOS", "REGISTRAR_VALOR_CRITICO"),
    ),
    "AUDITOR": (
        "Auditoría y calidad",
        {m: LECTURA for m in ("usuarios", "pacientes", "ordenes", "caja", "muestras", "resultados", "reportes")},
        (),
    ),
    # Solo para el personal de la plataforma que entra con una autorización de soporte del laboratorio.
    # No se asigna desde la interfaz del laboratorio.
    ROL_SOPORTE: (
        "Soporte de la plataforma (solo lectura)",
        {
            m: LECTURA
            for m in ("usuarios", "configuracion", "pacientes", "ordenes", "caja", "muestras", "resultados", "reportes")
        },
        (),
    ),
}


async def crear_roles_sistema(sesion: AsyncSession) -> None:
    """Crea (o completa) los roles del sistema en el laboratorio de la sesión. Idempotente."""
    for codigo, (nombre, modulos, acciones) in ROLES.items():
        rol_id = await sesion.scalar(
            text(
                "INSERT INTO lab.roles (tenant_id, codigo, nombre, sistema) VALUES (lab.tenant_actual(), :c, :n, true)"
                " ON CONFLICT (tenant_id, codigo) DO UPDATE SET nombre = EXCLUDED.nombre RETURNING id"
            ),
            {"c": codigo, "n": nombre},
        )
        for modulo, operaciones in modulos.items():
            await sesion.execute(
                text(
                    "INSERT INTO lab.rol_permisos (tenant_id, rol_id, modulo, consultar, crear, modificar, eliminar)"
                    " VALUES (lab.tenant_actual(), :r, :m, :c1, :c2, :c3, :c4)"
                    " ON CONFLICT (tenant_id, rol_id, modulo) DO UPDATE SET consultar = EXCLUDED.consultar,"
                    " crear = EXCLUDED.crear, modificar = EXCLUDED.modificar, eliminar = EXCLUDED.eliminar"
                ),
                {"r": rol_id, "m": modulo, **{f"c{i + 1}": op in operaciones for i, op in enumerate(TODAS)}},
            )
        for accion in acciones:
            await sesion.execute(
                text(
                    "INSERT INTO lab.rol_acciones (tenant_id, rol_id, accion) VALUES (lab.tenant_actual(), :r, :a)"
                    " ON CONFLICT DO NOTHING"
                ),
                {"r": rol_id, "a": accion},
            )
