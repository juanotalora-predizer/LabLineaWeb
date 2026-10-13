import asyncio
import contextlib
import logging
import os
from concurrent.futures import ThreadPoolExecutor

# La suite corre siempre contra la base de prueba (Settings.base_aplicacion). Debe fijarse
# antes de que cualquier módulo lea la configuración.
os.environ["ENTORNO"] = "pruebas"

from argparse import Namespace  # noqa: E402
from pathlib import Path  # noqa: E402

import pyotp  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import (
    AsyncSession,  # noqa: E402
    create_async_engine,  # noqa: E402
)
from sqlalchemy.pool import NullPool  # noqa: E402

from app.admin.roles import crear_roles_plataforma  # noqa: E402
from app.auth import repositorio  # noqa: E402
from app.auth.roles_sistema import ROLES, crear_roles_sistema  # noqa: E402
from app.core import correo, db  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from scripts.sinteticos import generar_personas  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent

# Envío real de correo, guardado antes de que el fixture `buzon` lo reemplace.
ENVIO_REAL = correo._enviar_sync

# Laboratorios sintéticos: (tenant_id, subdominio, nombre, NIT ficticio, estado)
LABORATORIOS = [
    ("lab_a", "lab-a", "Laboratorio A Sintético", "900000001", "ACTIVO"),
    ("lab_b", "lab-b", "Laboratorio B Sintético", "900000002", "ACTIVO"),
    ("lab_susp", "lab-susp", "Laboratorio Suspendido", "900000003", "SUSPENDIDO"),
    ("lab_canc", "lab-canc", "Laboratorio Cancelado", "900000004", "CANCELADO"),
]


async def _sembrar_laboratorios() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.url_plataforma(settings.db_name_test), poolclass=NullPool)
    async with engine.begin() as conexion:
        for tenant_id, subdominio, nombre, nit, estado in LABORATORIOS:
            await conexion.execute(
                text(
                    "INSERT INTO plataforma.laboratorios"
                    " (tenant_id, subdominio, nombre_comercial, identificador_fiscal, pais, estado, plan_id)"
                    " VALUES (:t, :s, :n, :nit, 'COL', :e,"
                    "         (SELECT id FROM plataforma.planes WHERE codigo = 'COMPLETO'))"
                    " ON CONFLICT (tenant_id) DO UPDATE SET estado = EXCLUDED.estado, plan_id = EXCLUDED.plan_id"
                ),
                {"t": tenant_id, "s": subdominio, "n": nombre, "nit": nit, "e": estado},
            )
    await engine.dispose()


# Contraseña de todos los usuarios sintéticos de las pruebas (no es un secreto real).
CLAVE = "Clave-de-prueba-2026"  # gitleaks:allow

# Usuarios sintéticos: (laboratorio, email, nombre, tipo, roles, tarjeta profesional, con TOTP)
USUARIOS = [
    ("lab_a", "admin@lab-a.test", "Admin A", "PERSONAL", ("ADMINISTRADOR",), None, True),
    ("lab_a", "recepcion@lab-a.test", "Recepción A", "PERSONAL", ("RECEPCION",), None, True),
    ("lab_a", "validador@lab-a.test", "Validador A", "PERSONAL", ("VALIDADOR",), "TP-12345", True),
    ("lab_a", "validador.sintp@lab-a.test", "Validador sin TP", "PERSONAL", ("VALIDADOR",), None, True),
    ("lab_a", "auditor@lab-a.test", "Auditor A", "PERSONAL", ("AUDITOR",), None, True),
    ("lab_a", "nuevo@lab-a.test", "Personal Nuevo A", "PERSONAL", ("FLEBOTOMIA",), None, False),
    ("lab_a", "paciente@lab-a.test", "Paciente A", "PACIENTE", (), None, False),
    ("lab_b", "admin@lab-b.test", "Admin B", "PERSONAL", ("ADMINISTRADOR",), None, True),
    ("lab_b", "paciente@lab-b.test", "Paciente B", "PACIENTE", (), None, False),
    # Mismo correo en dos laboratorios: son cuentas distintas.
    ("lab_b", "paciente@lab-a.test", "Paciente A en B", "PACIENTE", (), None, False),
]
# Pacientes sintéticos (scripts/sinteticos.py), usuarios del portal en lab_a. Sus identificadores no
# pueden aparecer en ningún log de la corrida (ver pytest_sessionfinish).
PACIENTES_SINTETICOS = generar_personas(6, semilla=2026, tipos_documento=("CC", "TI", "CE", "RC"))

# Un secreto TOTP por usuario sintético con app autenticadora.
SECRETOS_TOTP = {(lab, email): pyotp.random_base32() for lab, email, *_, totp in USUARIOS if totp}

TABLAS_AUTH = (
    "lab.eventos_seguridad, lab.limites, lab.codigos_verificacion, lab.sesiones, lab.invitaciones, lab.sedes,"
    " lab.rol_acciones, lab.rol_permisos, lab.usuario_roles, lab.roles, lab.usuarios"
)
# plataforma.eventos_seguridad y plataforma.auditoria no se vacían: un trigger lo impide (solo inserción).
TABLAS_AUTH_PLATAFORMA = (
    "plataforma.limites, plataforma.codigos_verificacion, plataforma.sesiones,"
    " plataforma.rol_acciones, plataforma.rol_permisos, plataforma.usuario_roles, plataforma.roles, plataforma.usuarios"
)

# Personal sintético de la plataforma: (email, nombre, roles). Todos con app autenticadora.
USUARIOS_PLATAFORMA = [
    ("maestro@plataforma.test", "Admin Maestro", ("ADMIN_MAESTRO",)),
    ("comercial@plataforma.test", "Gerente Comercial", ("GERENTE_COMERCIAL",)),
    ("financiero@plataforma.test", "Soporte Financiero", ("SOPORTE_FINANCIERO",)),
]
SECRETOS_TOTP.update({("plataforma", email): pyotp.random_base32() for email, *_ in USUARIOS_PLATAFORMA})


def engine_de(rol: str):
    settings = get_settings()
    url = {"app": settings.url_app, "owner": settings.url_owner, "plataforma": settings.url_plataforma}[rol]
    return create_async_engine(url(settings.db_name_test), poolclass=NullPool)


async def ejecutar_en_tenant(rol: str, tenant_id: str, funcion) -> object:
    """Ejecuta `funcion(sesion)` en una transacción con el laboratorio fijado (como lo hace la app)."""
    engine = engine_de(rol)
    try:
        async with AsyncSession(engine) as sesion, sesion.begin():
            await sesion.execute(
                text(
                    "SELECT set_config('app.current_tenant', :t, true), set_config('search_path', 'lab, public', true)"
                ),
                {"t": tenant_id},
            )
            return await funcion(sesion)
    finally:
        await engine.dispose()


async def ejecutar_en_plataforma(funcion) -> object:
    """Ejecuta `funcion(sesion)` con el rol y el search_path del Admin Hub (como lo hace la app)."""
    engine = engine_de("plataforma")
    try:
        async with AsyncSession(engine) as sesion, sesion.begin():
            await sesion.execute(text("SELECT set_config('search_path', 'plataforma, public', true)"))
            return await funcion(sesion)
    finally:
        await engine.dispose()


async def _sembrar_usuarios() -> None:
    owner = engine_de("owner")
    async with owner.begin() as conexion:
        # TRUNCATE no pasa por RLS ni por los triggers de fila: deja la base limpia en cada corrida.
        await conexion.execute(text(f"TRUNCATE {TABLAS_AUTH}"))
        await conexion.execute(text(f"TRUNCATE {TABLAS_AUTH_PLATAFORMA}"))
    await owner.dispose()

    async def sembrar_plataforma(sesion):
        await crear_roles_plataforma(sesion)
        for email, nombre, roles in USUARIOS_PLATAFORMA:
            usuario_id = await repositorio.crear_usuario(
                sesion, email=email, nombre=nombre, tipo="PERSONAL", clave=CLAVE, roles=roles
            )
            usuario = await repositorio.buscar_usuario(sesion, usuario_id)
            await repositorio.guardar_totp(sesion, usuario, SECRETOS_TOTP[("plataforma", email)])
            await repositorio.confirmar_totp(sesion, usuario_id, 0)

    await ejecutar_en_plataforma(sembrar_plataforma)

    for tenant_id in ("lab_a", "lab_b"):

        async def sembrar(sesion, tenant_id=tenant_id):
            await crear_roles_sistema(sesion)
            for lab, email, nombre, tipo, roles, tarjeta, totp in USUARIOS:
                if lab != tenant_id:
                    continue
                usuario_id = await repositorio.crear_usuario(
                    sesion, email=email, nombre=nombre, tipo=tipo, clave=CLAVE, roles=roles, tarjeta_profesional=tarjeta
                )
                if totp:
                    usuario = await repositorio.buscar_usuario(sesion, usuario_id)
                    await repositorio.guardar_totp(sesion, usuario, SECRETOS_TOTP[(lab, email)])
                    await repositorio.confirmar_totp(sesion, usuario_id, 0)
            if tenant_id == "lab_a":
                for persona in PACIENTES_SINTETICOS:
                    await repositorio.crear_usuario(
                        sesion, email=persona.email, nombre=persona.nombre_completo, tipo="PACIENTE", clave=CLAVE
                    )

        await ejecutar_en_tenant("app", tenant_id, sembrar)


@pytest.fixture(scope="session", autouse=True)
def base_de_prueba_migrada():
    """Lleva la base de prueba a la última migración y siembra laboratorios, roles y usuarios sintéticos."""
    settings = get_settings()
    cfg = Config(str(RAIZ / "alembic.ini"), cmd_opts=Namespace(x=[f"base={settings.db_name_test}"]))
    command.upgrade(cfg, "head")
    instalar_colector_de_logs()
    asyncio.run(_sembrar_laboratorios())
    asyncio.run(_sembrar_usuarios())


async def _limpiar_estado_de_autenticacion() -> None:
    owner = engine_de("owner")
    async with owner.begin() as conexion:
        await conexion.execute(text("TRUNCATE lab.limites, lab.codigos_verificacion, lab.sesiones"))
        await conexion.execute(
            text("TRUNCATE plataforma.limites, plataforma.codigos_verificacion, plataforma.sesiones")
        )
        await conexion.execute(
            text("UPDATE plataforma.usuarios SET bloqueado_hasta = NULL, totp_ultimo_contador = 0, estado = 'ACTIVO'")
        )
        # FORCE RLS aplica también al dueño: se fija cada laboratorio para reiniciar los contadores TOTP.
        for tenant_id in ("lab_a", "lab_b"):
            await conexion.execute(text("SELECT set_config('app.current_tenant', :t, true)"), {"t": tenant_id})
            await conexion.execute(text("UPDATE lab.usuarios SET bloqueado_hasta = NULL"))
            await conexion.execute(text("UPDATE lab.usuarios SET totp_ultimo_contador = 0 WHERE totp_confirmado"))
            # Usuarios sembrados sin app autenticadora: si una prueba la inscribió, vuelven al estado inicial.
            sin_totp = [email for lab, email, *_, totp in USUARIOS if lab == tenant_id and not totp]
            await conexion.execute(
                text(
                    "UPDATE lab.usuarios SET totp_secreto_cifrado = NULL, totp_confirmado = false,"
                    " totp_ultimo_contador = NULL WHERE email = ANY(:correos)"
                ),
                {"correos": sin_totp},
            )
    await owner.dispose()


def correr(corrutina):
    """Ejecuta una corrutina desde código síncrono, aunque haya un bucle activo (Playwright mantiene uno)."""
    with ThreadPoolExecutor(max_workers=1) as hilo:
        return hilo.submit(asyncio.run, corrutina).result()


@pytest.fixture(autouse=True)
def estado_de_autenticacion_limpio():
    """Cada prueba parte sin límites, códigos ni sesiones previas."""
    correr(_limpiar_estado_de_autenticacion())


@pytest.fixture(autouse=True)
def buzon(monkeypatch):
    """Captura los correos en una lista en lugar de enviarlos."""
    mensajes = []
    monkeypatch.setattr(correo, "_enviar_sync", mensajes.append)
    return mensajes


# --- Datos de pacientes en los logs (spec infraestructura/0011, criterio 8) ---


class _ColectorDeLogs(logging.Handler):
    """Guarda todo lo que se registra durante la corrida, incluidas las trazas de excepciones."""

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.textos: list[str] = []

    def emit(self, registro: logging.LogRecord) -> None:
        # Un registro mal formado no debe romper la corrida.
        with contextlib.suppress(Exception):
            self.textos.append(self.format(registro))


COLECTOR_DE_LOGS = _ColectorDeLogs()


def instalar_colector_de_logs() -> None:
    """Idempotente. Se repite después de migrar: la configuración de logs de Alembic reemplaza la raíz."""
    raiz = logging.getLogger()
    if COLECTOR_DE_LOGS not in raiz.handlers:
        raiz.addHandler(COLECTOR_DE_LOGS)
    raiz.setLevel(logging.DEBUG)


def pytest_configure(config):
    instalar_colector_de_logs()


def identificadores_en_logs(textos: list[str]) -> list[str]:
    todo = "\n".join(textos)
    return sorted({v for p in PACIENTES_SINTETICOS for v in p.identificadores() if v in todo})


def pytest_sessionfinish(session, exitstatus):
    """Búsqueda automática: ningún identificador de paciente sintético en los logs de toda la corrida."""
    encontrados = identificadores_en_logs(COLECTOR_DE_LOGS.textos)
    if encontrados:
        reporte = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporte:
            reporte.write_line(f"FALLA: datos de pacientes sintéticos en los logs: {encontrados}", red=True)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


__all__ = ["CLAVE", "PACIENTES_SINTETICOS", "ROLES", "SECRETOS_TOTP", "USUARIOS"]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def engine_app():
    """Engine con el rol de la aplicación sobre la base de prueba.

    Pool de una sola conexión: obliga a que peticiones sucesivas reutilicen la misma
    conexión, que es justo el caso en que un tenant podría filtrarse.
    """
    settings = get_settings()
    engine = create_async_engine(
        settings.url_app(settings.db_name_test), pool_size=1, max_overflow=0, connect_args=db.CONEXION_UTC
    )
    db.configurar(engine)
    yield engine
    await db.cerrar()


@pytest.fixture
async def engine_plataforma():
    settings = get_settings()
    engine = create_async_engine(settings.url_plataforma(settings.db_name_test), poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def engine_owner():
    settings = get_settings()
    engine = create_async_engine(settings.url_owner(settings.db_name_test), poolclass=NullPool)
    yield engine
    await engine.dispose()
