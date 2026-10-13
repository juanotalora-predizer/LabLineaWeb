"""Acceso a la base de datos con el ámbito fijado por transacción.

Toda operación sobre datos de un laboratorio pasa por `sesion_tenant`, que abre una
transacción y fija `app.current_tenant` con alcance LOCAL. Al terminar la transacción
el valor desaparece, así que una conexión reutilizada del pool nunca hereda el tenant
de otra petición (spec infraestructura/0007, sección 3).

El Admin Hub usa `sesion_plataforma`, con otro rol de base de datos (sin acceso a `lab`).
Ambas fijan el `search_path` de la transacción (`lab` o `plataforma`): el código de
autenticación usa nombres de tabla sin esquema y sirve a los dos sitios. Un rol no puede
usar el esquema del otro, así que un `search_path` equivocado falla en lugar de mezclar datos.
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

# public: allí vive la extensión citext (sus operadores hacen la comparación de correos sin mayúsculas).
_SQL_CONTEXTO = text(
    "SELECT set_config('search_path', :ruta, true),"
    " set_config('app.current_tenant', :tenant, true),"
    " set_config('app.current_user_id', :usuario, true),"
    " set_config('app.client_ip', :ip, true)"
)

_engine: AsyncEngine | None = None
_sesiones: async_sessionmaker[AsyncSession] | None = None
_engine_plataforma: AsyncEngine | None = None
_sesiones_plataforma: async_sessionmaker[AsyncSession] | None = None


def _opciones_engine() -> dict:
    # En pruebas cada TestClient corre en su propio bucle de eventos y las conexiones de
    # asyncpg no pueden pasar de un bucle a otro: sin pool. La reutilización de conexiones
    # (y que el tenant no se filtre entre peticiones) se prueba aparte en tests/test_db.py.
    if get_settings().entorno == "pruebas":
        return {"poolclass": NullPool, "connect_args": CONEXION_UTC}
    return {"pool_pre_ping": True, "connect_args": CONEXION_UTC}


def configurar(engine: AsyncEngine) -> None:
    """Fija el engine de la aplicación (rol lablinea_app). Las pruebas lo usan para apuntar a la base de prueba."""
    global _engine, _sesiones
    _engine = engine
    _sesiones = async_sessionmaker(engine, expire_on_commit=False)


def engine_app() -> AsyncEngine:
    if _engine is None:
        configurar(create_async_engine(get_settings().url_app(), **_opciones_engine()))
    return _engine


def engine_plataforma() -> AsyncEngine:
    """Engine del Admin Hub (rol lablinea_plataforma): esquema plataforma, sin acceso a lab."""
    global _engine_plataforma, _sesiones_plataforma
    if _engine_plataforma is None:
        _engine_plataforma = create_async_engine(get_settings().url_plataforma(), **_opciones_engine())
        _sesiones_plataforma = async_sessionmaker(_engine_plataforma, expire_on_commit=False)
    return _engine_plataforma


async def cerrar() -> None:
    global _engine, _sesiones, _engine_plataforma, _sesiones_plataforma
    for engine in (_engine, _engine_plataforma):
        if engine is not None:
            await engine.dispose()
    _engine = _sesiones = _engine_plataforma = _sesiones_plataforma = None


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
            _SQL_CONTEXTO, {"ruta": "lab, public", "tenant": tenant_id, "usuario": usuario_id or "", "ip": ip or ""}
        )
        yield sesion


@asynccontextmanager
async def sesion_plataforma(*, usuario_id: str | None = None, ip: str | None = None) -> AsyncIterator[AsyncSession]:
    """Sesión del Admin Hub. El usuario queda como `plataforma:<uuid>` en la auditoría, también en la de un
    laboratorio cuando la plataforma lo da de alta."""
    engine_plataforma()
    async with _sesiones_plataforma() as sesion, sesion.begin():
        usuario = f"plataforma:{usuario_id}" if usuario_id else ""
        await sesion.execute(
            _SQL_CONTEXTO, {"ruta": "plataforma, public", "tenant": "", "usuario": usuario, "ip": ip or ""}
        )
        yield sesion
