"""Acceso a la base de datos con el tenant fijado por transacción.

Toda operación sobre datos de un laboratorio pasa por `sesion_tenant`, que abre una
transacción y fija `app.current_tenant` con alcance LOCAL. Al terminar la transacción
el valor desaparece, así que una conexión reutilizada del pool nunca hereda el tenant
de otra petición (spec infraestructura/0007, sección 3).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

# Fechas en UTC en la base (spec infraestructura/0004): la sesión no depende de la zona del servidor.
# La zona del laboratorio solo se aplica al mostrar (app/core/i18n.py).
CONEXION_UTC = {"server_settings": {"timezone": "UTC"}}

_engine: AsyncEngine | None = None
_sesiones: async_sessionmaker[AsyncSession] | None = None


def configurar(engine: AsyncEngine) -> None:
    """Fija el engine de la aplicación (rol lablinea_app). Las pruebas lo usan para apuntar a la base de prueba."""
    global _engine, _sesiones
    _engine = engine
    _sesiones = async_sessionmaker(engine, expire_on_commit=False)


def engine_app() -> AsyncEngine:
    if _engine is None:
        settings = get_settings()
        # En pruebas cada TestClient corre en su propio bucle de eventos y las conexiones de
        # asyncpg no pueden pasar de un bucle a otro: sin pool. La reutilización de conexiones
        # (y que el tenant no se filtre entre peticiones) se prueba aparte en tests/test_db.py.
        opciones = {"poolclass": NullPool} if settings.entorno == "pruebas" else {"pool_pre_ping": True}
        configurar(create_async_engine(settings.url_app(), connect_args=CONEXION_UTC, **opciones))
    return _engine


async def cerrar() -> None:
    global _engine, _sesiones
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sesiones = None


@asynccontextmanager
async def sesion_tenant(
    tenant_id: str,
    *,
    usuario_id: str | None = None,
    ip: str | None = None,
) -> AsyncIterator[AsyncSession]:
    """Sesión dentro de una transacción con el tenant, el usuario y la IP fijados con alcance LOCAL.

    `tenant_id` debe venir de la resolución del servidor (subdominio + sesión), nunca de la petición.
    Hace commit al salir sin errores y rollback si hay una excepción.
    """
    if not tenant_id:
        raise ValueError("Se requiere un tenant para acceder a datos del laboratorio")
    engine_app()
    async with _sesiones() as sesion, sesion.begin():
        # set_config(..., true) equivale a SET LOCAL y acepta parámetros enlazados.
        await sesion.execute(
            text(
                "SELECT set_config('app.current_tenant', :tenant, true),"
                " set_config('app.current_user_id', :usuario, true),"
                " set_config('app.client_ip', :ip, true)"
            ),
            {"tenant": tenant_id, "usuario": usuario_id or "", "ip": ip or ""},
        )
        yield sesion
