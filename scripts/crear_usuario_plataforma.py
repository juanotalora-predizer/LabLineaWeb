"""Crea una persona del personal de la plataforma (Admin Hub). La contraseña se pide por consola.

    .venv/bin/python scripts/crear_usuario_plataforma.py correo@empresa.com "Nombre Apellido" ADMIN_MAESTRO

Al ingresar por primera vez debe inscribir su app autenticadora (segundo factor obligatorio).
Roles: ADMIN_MAESTRO, GERENTE_COMERCIAL, SOPORTE_FINANCIERO (app/admin/roles.py).
"""

import asyncio
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.admin.roles import ROLES_PLATAFORMA, crear_roles_plataforma  # noqa: E402
from app.auth import contrasenas, repositorio  # noqa: E402
from app.core import db  # noqa: E402


async def crear(email: str, nombre: str, rol: str, clave: str) -> None:
    async with db.sesion_plataforma() as sesion:
        await crear_roles_plataforma(sesion)
        if await repositorio.buscar_usuario_por_email(sesion, email):
            raise SystemExit("Ya existe un usuario de la plataforma con ese correo.")
        await repositorio.crear_usuario(sesion, email=email, nombre=nombre, tipo="PERSONAL", clave=clave, roles=(rol,))
    await db.cerrar()


def main(argumentos: list[str]) -> None:
    if len(argumentos) != 3 or argumentos[2] not in ROLES_PLATAFORMA:
        raise SystemExit(__doc__)
    email, nombre, rol = argumentos[0].strip().lower(), argumentos[1].strip(), argumentos[2]
    clave = getpass.getpass("Contraseña: ")
    if clave != getpass.getpass("Repita la contraseña: "):
        raise SystemExit("Las contraseñas no coinciden.")
    errores = contrasenas.validar_politica(clave, email)
    if errores:
        raise SystemExit(" ".join(errores))
    asyncio.run(crear(email, nombre, rol, clave))
    print(f"Creado {email} con el rol {rol}.")


if __name__ == "__main__":
    main(sys.argv[1:])
