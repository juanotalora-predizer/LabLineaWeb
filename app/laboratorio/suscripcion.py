"""Aviso de renovación de la suscripción a los administradores del laboratorio (spec funcional/0005, sección 3).

La plataforma encola la tarea `suscripcion.aviso` 7 días y 1 día antes del vencimiento
(plataforma.mantener_suscripciones). El correo no lleva datos clínicos.
"""

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import correo
from app.core.i18n import fecha_local, t
from app.core.tareas import ErrorPermanente, tarea
from app.core.tenancy import buscar_laboratorio

TIPO_TAREA = "suscripcion.aviso"

_SQL_ADMINISTRADORES = text(
    "SELECT DISTINCT u.email::text FROM lab.usuarios u"
    " JOIN lab.usuario_roles ur ON ur.usuario_id = u.id JOIN lab.roles r ON r.id = ur.rol_id"
    " WHERE r.codigo = 'ADMINISTRADOR' AND u.estado = 'ACTIVO' AND u.password_hash IS NOT NULL"
)


@tarea(TIPO_TAREA)
async def avisar_renovacion(sesion: AsyncSession, datos: dict) -> None:
    laboratorio = await buscar_laboratorio(str(datos.get("subdominio", "")))
    tenant = await sesion.scalar(text("SELECT lab.tenant_actual()"))
    if laboratorio is None or laboratorio.tenant_id != tenant:
        raise ErrorPermanente("el subdominio no corresponde al laboratorio de la tarea")
    try:
        fin = datetime.fromisoformat(str(datos.get("fin", "")))
    except ValueError:
        raise ErrorPermanente("fecha de vencimiento no válida") from None
    idioma = laboratorio.idioma
    fecha = fecha_local(fin, laboratorio.zona_horaria, idioma)
    for email in (await sesion.execute(_SQL_ADMINISTRADORES)).scalars():
        await correo.enviar(
            email,
            t("suscripcion.aviso_asunto", idioma, laboratorio=laboratorio.nombre_comercial),
            t("suscripcion.aviso_cuerpo", idioma, laboratorio=laboratorio.nombre_comercial, fecha=fecha),
        )
