"""Base de datos: roles, contexto de tenant y cumplimiento de RLS (spec infraestructura/0007)."""

import pytest
from sqlalchemy import text

from app.core.db import sesion_tenant

pytestmark = pytest.mark.anyio


async def test_rol_app_no_es_superusuario_ni_salta_rls(engine_app):
    async with engine_app.connect() as conn:
        fila = (
            await conn.execute(
                text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
            )
        ).one()
    assert fila.rolsuper is False
    assert fila.rolbypassrls is False


async def test_rol_app_no_es_dueno_de_los_esquemas(engine_app):
    async with engine_app.connect() as conn:
        duenos = (
            await conn.execute(
                text(
                    "SELECT nspname, pg_get_userbyid(nspowner) AS dueno FROM pg_namespace"
                    " WHERE nspname IN ('plataforma', 'global', 'lab')"
                )
            )
        ).all()
        actual = (await conn.execute(text("SELECT current_user"))).scalar_one()
    assert len(duenos) == 3
    assert all(d.dueno != actual for d in duenos)


async def test_rol_app_no_accede_al_esquema_plataforma(engine_app):
    async with engine_app.connect() as conn:
        puede = (
            await conn.execute(text("SELECT has_schema_privilege(current_user, 'plataforma', 'USAGE')"))
        ).scalar_one()
    assert puede is False


async def test_tenant_queda_fijado_dentro_de_la_transaccion(engine_app):
    async with sesion_tenant("lab_a", usuario_id="u-1", ip="10.0.0.1") as sesion:
        fila = (
            await sesion.execute(
                text(
                    "SELECT lab.tenant_actual() AS tenant,"
                    " current_setting('app.current_user_id') AS usuario,"
                    " current_setting('app.client_ip') AS ip"
                )
            )
        ).one()
    assert (fila.tenant, fila.usuario, fila.ip) == ("lab_a", "u-1", "10.0.0.1")


async def test_tenant_no_se_filtra_a_la_siguiente_peticion(engine_app):
    async with sesion_tenant("lab_a") as sesion:
        await sesion.execute(text("SELECT 1"))

    # Misma conexión física (pool de 1), nueva transacción sin tenant.
    async with engine_app.connect() as conn:
        tenant = (await conn.execute(text("SELECT lab.tenant_actual()"))).scalar_one()
    assert tenant is None


async def test_peticiones_sucesivas_ven_cada_una_su_tenant(engine_app):
    for esperado in ("lab_a", "lab_b", "lab_a"):
        async with sesion_tenant(esperado) as sesion:
            actual = (await sesion.execute(text("SELECT lab.tenant_actual()"))).scalar_one()
        assert actual == esperado


async def test_sesion_tenant_exige_tenant(engine_app):
    with pytest.raises(ValueError):
        async with sesion_tenant(""):
            pass


async def test_toda_tabla_de_lab_cumple_rls(engine_app):
    """Guardián de la spec 0007: falla si una tabla de `lab` no tiene tenant_id, RLS
    habilitado y forzado, y una política con USING y WITH CHECK."""
    consulta = text(
        """
        SELECT c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'lab'
          AND c.relkind IN ('r', 'p')
          AND NOT c.relispartition
          AND NOT (
                c.relrowsecurity
            AND c.relforcerowsecurity
            AND EXISTS (
                SELECT 1 FROM pg_attribute a
                WHERE a.attrelid = c.oid AND a.attname = 'tenant_id' AND NOT a.attisdropped
            )
            AND EXISTS (
                SELECT 1 FROM pg_policy p
                WHERE p.polrelid = c.oid AND p.polqual IS NOT NULL AND p.polwithcheck IS NOT NULL
            )
          )
        """
    )
    async with engine_app.connect() as conn:
        incumplen = (await conn.execute(consulta)).scalars().all()
    assert incumplen == [], f"Tablas de lab sin RLS completo: {incumplen}"
