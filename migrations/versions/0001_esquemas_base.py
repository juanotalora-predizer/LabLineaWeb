"""Esquemas base, contexto de tenant y permisos por defecto.

Spec infraestructura/0007:
- plataforma: datos del SaaS; sin acceso para el rol de la aplicación.
- global: catálogos compartidos; la aplicación solo lee.
- lab: datos de cada laboratorio; toda tabla con tenant_id y RLS forzado.

Revision ID: 0001
Revises:
Create Date: 2026-10-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP = "lablinea_app"


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    op.execute("CREATE SCHEMA plataforma")
    op.execute('CREATE SCHEMA "global"')
    op.execute("CREATE SCHEMA lab")

    # Tenant de la transacción, fijado por app.core.db.sesion_tenant con alcance LOCAL.
    # Fuera de una transacción con tenant devuelve NULL, y las políticas no dejan pasar filas.
    op.execute(
        """
        CREATE FUNCTION lab.tenant_actual() RETURNS text
        LANGUAGE sql STABLE
        AS $$ SELECT NULLIF(current_setting('app.current_tenant', true), '') $$
        """
    )

    # Rol de la aplicación: usa lab (bajo RLS) y lee global. Nada en plataforma.
    op.execute(f"GRANT USAGE ON SCHEMA lab, \"global\" TO {APP}")
    op.execute(f"GRANT EXECUTE ON FUNCTION lab.tenant_actual() TO {APP}")

    # Permisos de las tablas que creen migraciones futuras. Sin DELETE por defecto:
    # cada tabla que lo necesite lo otorga de forma explícita.
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA lab GRANT SELECT, INSERT, UPDATE ON TABLES TO {APP}"
    )
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA lab GRANT USAGE ON SEQUENCES TO {APP}")
    op.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA "global" GRANT SELECT ON TABLES TO {APP}')


def downgrade() -> None:
    op.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA "global" REVOKE SELECT ON TABLES FROM {APP}')
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA lab REVOKE USAGE ON SEQUENCES FROM {APP}")
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA lab REVOKE SELECT, INSERT, UPDATE ON TABLES FROM {APP}"
    )
    op.execute("DROP SCHEMA lab CASCADE")
    op.execute('DROP SCHEMA "global" CASCADE')
    op.execute("DROP SCHEMA plataforma CASCADE")
