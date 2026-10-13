from argparse import Namespace
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine

from app.core import db
from app.core.config import get_settings

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session", autouse=True)
def base_de_prueba_migrada():
    """Lleva la base de prueba a la última migración antes de correr las pruebas."""
    settings = get_settings()
    cfg = Config(str(RAIZ / "alembic.ini"), cmd_opts=Namespace(x=[f"base={settings.db_name_test}"]))
    command.upgrade(cfg, "head")


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
