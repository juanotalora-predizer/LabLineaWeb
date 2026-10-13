"""Alta de laboratorios (spec funcional/0005, sección 2; plan, etapa 4).

El alta completa ocurre en UNA transacción, dentro de `plataforma.alta_laboratorio` (SECURITY DEFINER):
el laboratorio, su suscripción inicial, su sede, los roles del sistema y el administrador sin contraseña, más la
tarea que le envía la invitación. Si algo falla, no queda nada creado. Es la única escritura de la
plataforma en el esquema lab.
"""

import json
import re
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.roles_sistema import ROLES
from app.core.i18n import t

SUBDOMINIO = re.compile(r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$")
IDENTIFICADOR_FISCAL = re.compile(r"^[0-9A-Za-z.-]{5,20}$")
CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
UNICIDAD = "23505"  # unique_violation de PostgreSQL


@dataclass(frozen=True)
class DatosAlta:
    nombre: str
    subdominio: str
    identificador_fiscal: str
    pais: str
    plan: str
    sede: str
    ciudad: str
    admin_email: str
    admin_nombre: str
    tipo_licencia: str = "DEMO"

    @property
    def tenant_id(self) -> str:
        """Código interno inmutable derivado del subdominio (siempre empieza con letra)."""
        return "lab_" + self.subdominio.replace("-", "_")


def roles_iniciales() -> str:
    """Roles del sistema en JSON para la función de alta."""
    return json.dumps(
        [
            {
                "codigo": codigo,
                "nombre": nombre,
                "modulos": {m: list(ops) for m, ops in modulos.items()},
                "acciones": list(acciones),
            }
            for codigo, (nombre, modulos, acciones) in ROLES.items()
        ]
    )


def validar(datos: DatosAlta, idioma: str | None = None) -> list[str]:
    errores = []
    if not 2 <= len(datos.nombre) <= 120:
        errores.append(t("alta.error_nombre", idioma))
    if not SUBDOMINIO.match(datos.subdominio) or "--" in datos.subdominio:
        errores.append(t("alta.error_subdominio", idioma))
    if not IDENTIFICADOR_FISCAL.match(datos.identificador_fiscal):
        errores.append(t("alta.error_identificador", idioma))
    if not (2 <= len(datos.sede) <= 120 and 2 <= len(datos.ciudad) <= 80):
        errores.append(t("alta.error_sede", idioma))
    if not CORREO.match(datos.admin_email) or not 2 <= len(datos.admin_nombre) <= 120:
        errores.append(t("alta.error_administrador", idioma))
    return errores


async def dar_de_alta(
    sesion: AsyncSession, datos: DatosAlta, idioma: str | None = None
) -> tuple[str | None, list[str]]:
    """Devuelve (uuid del laboratorio, errores). Usa una `sesion_plataforma`."""
    errores = validar(datos, idioma)
    if errores:
        return None, errores
    try:
        async with sesion.begin_nested():
            uuid = await sesion.scalar(
                text(
                    "SELECT plataforma.alta_laboratorio(:tenant, :sub, :nombre, :nit, :pais, CAST(:plan AS uuid),"
                    " :sede, :ciudad, :email, :admin, CAST(:roles AS jsonb), :licencia)::text"
                ),
                {
                    "tenant": datos.tenant_id,
                    "sub": datos.subdominio,
                    "nombre": datos.nombre,
                    "nit": datos.identificador_fiscal,
                    "pais": datos.pais,
                    "plan": datos.plan,
                    "sede": datos.sede,
                    "ciudad": datos.ciudad,
                    "email": datos.admin_email,
                    "admin": datos.admin_nombre,
                    "roles": roles_iniciales(),
                    "licencia": datos.tipo_licencia,
                },
            )
    except IntegrityError as error:
        if getattr(error.orig, "sqlstate", None) == UNICIDAD:
            return None, [t("alta.error_existe", idioma)]
        return None, [t("alta.error_rechazada", idioma)]  # CHECK: p. ej. subdominio reservado
    except DBAPIError:
        # Subdominio reservado, país no habilitado, plan inactivo o UUID mal formado: sin detalles internos.
        return None, [t("alta.error_rechazada", idioma)]
    return uuid, []
