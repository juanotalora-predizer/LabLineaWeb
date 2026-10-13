import asyncio
import os

# La suite corre siempre contra la base de prueba (Settings.base_aplicacion). Debe fijarse
# antes de que cualquier módulo lea la configuración.
os.environ["ENTORNO"] = "pruebas"

from argparse import Namespace  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.core import db  # noqa: E402
from app.core.config import get_settings  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent

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
                    " (tenant_id, subdominio, nombre_comercial, identificador_fiscal, pais, estado)"
                    " VALUES (:t, :s, :n, :nit, 'COL', :e)"
                    " ON CONFLICT (tenant_id) DO UPDATE SET estado = EXCLUDED.estado"
                ),
                {"t": tenant_id, "s": subdominio, "n": nombre, "nit": nit, "e": estado},
            )
    await engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def base_de_prueba_migrada():
    """Lleva la base de prueba a la última migración y siembra los laboratorios sintéticos."""
    settings = get_settings()
    cfg = Config(str(RAIZ / "alembic.ini"), cmd_opts=Namespace(x=[f"base={settings.db_name_test}"]))
    command.upgrade(cfg, "head")
    asyncio.run(_sembrar_laboratorios())


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
    engine = create_async_engine(settings.url_app(settings.db_name_test), pool_size=1, max_overflow=0)
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
