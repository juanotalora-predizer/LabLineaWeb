"""Base multi-tenant: catálogos globales, laboratorios y resolución por subdominio.

Specs infraestructura/0004 (configuración por país), 0005 (tenant = laboratorio, subdominio)
y 0007 (esquemas y roles).

- global: monedas, países y tipos de documento. Solo Colombia queda habilitado: ningún país
  se habilita sin su spec de normativa (infraestructura/0004).
- plataforma.laboratorios: los tenants. Solo el rol de la plataforma los administra.
- acceso.resolver_laboratorio(subdominio): única ventana del rol de la aplicación hacia la
  plataforma. SECURITY DEFINER, devuelve solo lo necesario para atender la petición.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP = "lablinea_app"
PLATAFORMA = "lablinea_plataforma"

# Subdominios que nunca pueden pertenecer a un laboratorio.
RESERVADOS = ("admin", "www", "api", "static", "mail", "smtp", "soporte", "status", "app")

# Tipos de documento de personas en Colombia. Por validar contra la tabla vigente de RIPS
# antes de la etapa 7 (pacientes).
TIPOS_DOCUMENTO_COL = (
    ("CC", "Cédula de ciudadanía"),
    ("CE", "Cédula de extranjería"),
    ("TI", "Tarjeta de identidad"),
    ("RC", "Registro civil de nacimiento"),
    ("PA", "Pasaporte"),
    ("CD", "Carné diplomático"),
    ("SC", "Salvoconducto de permanencia"),
    ("PE", "Permiso especial de permanencia"),
    ("PT", "Permiso por protección temporal"),
    ("CN", "Certificado de nacido vivo"),
    ("DE", "Documento extranjero"),
    ("AS", "Adulto sin identificación"),
    ("MS", "Menor sin identificación"),
)


def upgrade() -> None:
    # ------------------------------------------------------------------ global
    op.execute(
        """
        CREATE TABLE "global".monedas (
            codigo    CHAR(3) PRIMARY KEY CHECK (codigo ~ '^[A-Z]{3}$'),
            nombre    TEXT NOT NULL,
            decimales SMALLINT NOT NULL DEFAULT 2 CHECK (decimales BETWEEN 0 AND 4)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE "global".paises (
            codigo       CHAR(3) PRIMARY KEY CHECK (codigo ~ '^[A-Z]{3}$'),   -- ISO 3166-1 alfa-3
            codigo_iso2  CHAR(2) NOT NULL UNIQUE CHECK (codigo_iso2 ~ '^[A-Z]{2}$'),
            nombre       TEXT NOT NULL,
            moneda       CHAR(3) NOT NULL REFERENCES "global".monedas (codigo),
            zona_horaria TEXT NOT NULL,
            idioma       TEXT NOT NULL CHECK (idioma ~ '^[a-z]{2}-[A-Z]{2}$'),
            habilitado   BOOLEAN NOT NULL DEFAULT false
        )
        """
    )
    op.execute(
        """
        CREATE TABLE "global".tipos_documento (
            pais    CHAR(3) NOT NULL REFERENCES "global".paises (codigo),
            codigo  TEXT NOT NULL CHECK (codigo ~ '^[A-Z]{2,4}$'),
            nombre  TEXT NOT NULL,
            aplica_a TEXT NOT NULL DEFAULT 'PERSONA' CHECK (aplica_a IN ('PERSONA', 'EMPRESA')),
            activo  BOOLEAN NOT NULL DEFAULT true,
            PRIMARY KEY (pais, codigo)
        )
        """
    )

    op.execute(
        """
        INSERT INTO "global".monedas (codigo, nombre, decimales) VALUES
            ('COP', 'Peso colombiano', 2),
            ('USD', 'Dólar estadounidense', 2)
        """
    )
    op.execute(
        """
        INSERT INTO "global".paises (codigo, codigo_iso2, nombre, moneda, zona_horaria, idioma, habilitado)
        VALUES ('COL', 'CO', 'Colombia', 'COP', 'America/Bogota', 'es-CO', true)
        """
    )
    valores = ", ".join(f"('COL', '{codigo}', '{nombre}')" for codigo, nombre in TIPOS_DOCUMENTO_COL)
    op.execute(f'INSERT INTO "global".tipos_documento (pais, codigo, nombre) VALUES {valores}')  # noqa: S608
    op.execute(
        "INSERT INTO \"global\".tipos_documento (pais, codigo, nombre, aplica_a) VALUES ('COL', 'NIT', 'NIT', 'EMPRESA')"
    )

    # -------------------------------------------------------------- plataforma
    reservados = ", ".join(f"'{r}'" for r in RESERVADOS)
    op.execute(
        f"""
        CREATE TABLE plataforma.laboratorios (
            id                   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            uuid                 UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
            tenant_id            TEXT NOT NULL UNIQUE CHECK (tenant_id ~ '^[a-z][a-z0-9_]{{2,49}}$'),
            subdominio           TEXT NOT NULL UNIQUE
                                 CHECK (subdominio ~ '^[a-z0-9]([a-z0-9-]{{0,61}}[a-z0-9])?$')
                                 CHECK (subdominio NOT IN ({reservados})),
            nombre_comercial     TEXT NOT NULL CHECK (length(nombre_comercial) BETWEEN 2 AND 120),
            identificador_fiscal TEXT NOT NULL,
            pais                 CHAR(3) NOT NULL REFERENCES "global".paises (codigo),
            estado               TEXT NOT NULL DEFAULT 'ACTIVO'
                                 CHECK (estado IN ('ACTIVO', 'SUSPENDIDO', 'CANCELADO')),
            creado_en            TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (pais, identificador_fiscal)
        )
        """
    )

    # Un laboratorio solo puede registrarse en un país habilitado (infraestructura/0004).
    op.execute(
        """
        CREATE FUNCTION plataforma.validar_pais_habilitado() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM "global".paises WHERE codigo = NEW.pais AND habilitado) THEN
            RAISE EXCEPTION 'El país % no está habilitado', NEW.pais;
          END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER laboratorios_pais_habilitado
        BEFORE INSERT OR UPDATE OF pais ON plataforma.laboratorios
        FOR EACH ROW EXECUTE FUNCTION plataforma.validar_pais_habilitado()
        """
    )

    # ------------------------------------------------------------------ acceso
    op.execute("CREATE SCHEMA acceso")
    op.execute(
        """
        CREATE FUNCTION acceso.resolver_laboratorio(p_subdominio text)
        RETURNS TABLE (tenant_id text, nombre_comercial text, pais char(3), estado text,
                       zona_horaria text, idioma text, moneda char(3))
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
          SELECT l.tenant_id, l.nombre_comercial, l.pais, l.estado,
                 p.zona_horaria, p.idioma, p.moneda
          FROM plataforma.laboratorios l
          JOIN "global".paises p ON p.codigo = l.pais
          WHERE l.subdominio = lower(p_subdominio)
            AND l.estado <> 'CANCELADO'
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION acceso.resolver_laboratorio(text) FROM PUBLIC")
    op.execute(f"GRANT USAGE ON SCHEMA acceso TO {APP}")
    op.execute(f"GRANT EXECUTE ON FUNCTION acceso.resolver_laboratorio(text) TO {APP}")

    # ---------------------------------------------------------------- permisos
    # global: la aplicación ya lee por los privilegios por defecto de 0001; se reafirma.
    op.execute(f'GRANT SELECT ON ALL TABLES IN SCHEMA "global" TO {APP}')
    # Admin Hub: administra plataforma y lee global. Sin DELETE: los laboratorios se cancelan.
    op.execute(f'GRANT USAGE ON SCHEMA plataforma, "global" TO {PLATAFORMA}')
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON plataforma.laboratorios TO {PLATAFORMA}")
    op.execute(f'GRANT SELECT ON ALL TABLES IN SCHEMA "global" TO {PLATAFORMA}')
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA plataforma GRANT SELECT, INSERT, UPDATE ON TABLES TO {PLATAFORMA}")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA plataforma GRANT USAGE ON SEQUENCES TO {PLATAFORMA}")
    op.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA "global" GRANT SELECT ON TABLES TO {PLATAFORMA}')


def downgrade() -> None:
    op.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA "global" REVOKE SELECT ON TABLES FROM {PLATAFORMA}')
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA plataforma REVOKE USAGE ON SEQUENCES FROM {PLATAFORMA}")
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA plataforma REVOKE SELECT, INSERT, UPDATE ON TABLES FROM {PLATAFORMA}"
    )
    op.execute(f'REVOKE ALL ON SCHEMA plataforma, "global" FROM {PLATAFORMA}')
    op.execute("DROP SCHEMA acceso CASCADE")
    op.execute("DROP TABLE plataforma.laboratorios")
    op.execute("DROP FUNCTION plataforma.validar_pais_habilitado()")
    op.execute('DROP TABLE "global".tipos_documento')
    op.execute('DROP TABLE "global".paises')
    op.execute('DROP TABLE "global".monedas')
