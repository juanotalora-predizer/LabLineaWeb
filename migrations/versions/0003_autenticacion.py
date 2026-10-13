"""Autenticación y autorización (spec infraestructura/0008, etapa 2).

global: catálogos de módulos y acciones especiales.
lab (todas con tenant_id y RLS forzado):
- usuarios: credenciales (Argon2id), segundo factor y bloqueo temporal (bloqueado_hasta).
- roles, usuario_roles, rol_permisos (CRUD por módulo), rol_acciones (acciones especiales).
- sesiones: solo el hash SHA-256 del token; inactividad y duración máxima.
- codigos_verificacion: códigos de un solo uso por correo, guardados como HMAC.
- limites: contadores por ventana para frenar fuerza bruta (por IP y por correo).
- eventos_seguridad: inicios de sesión, fallos, bloqueos; solo inserción.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP = "lablinea_app"

MODULOS = (
    ("usuarios", "Usuarios y roles"),
    ("configuracion", "Configuración del laboratorio"),
    ("pacientes", "Pacientes"),
    ("ordenes", "Órdenes"),
    ("caja", "Caja"),
    ("muestras", "Muestras"),
    ("resultados", "Resultados"),
    ("reportes", "Reportes"),
)

ACCIONES = (
    ("PRECERRAR_ORDEN", "Pre-cerrar órdenes"),
    ("ANULAR_ORDEN", "Anular órdenes"),
    ("AUTORIZAR_DESCUENTO", "Autorizar descuentos sobre el tope del convenio"),
    ("ABRIR_CAJA", "Abrir caja"),
    ("CERRAR_CAJA", "Cerrar caja"),
    ("VALIDAR_RESULTADOS", "Validar resultados (requiere tarjeta profesional)"),
    ("REGISTRAR_VALOR_CRITICO", "Registrar comunicación de valores críticos"),
    ("LIBERAR_CON_EXCEPCION", "Liberar resultados con excepción"),
    ("AUTORIZAR_SOPORTE", "Autorizar acceso de soporte de la plataforma"),
)

TABLAS_LAB = (
    "usuarios",
    "roles",
    "usuario_roles",
    "rol_permisos",
    "rol_acciones",
    "sesiones",
    "codigos_verificacion",
    "limites",
    "eventos_seguridad",
)


def upgrade() -> None:
    # ------------------------------------------------------------------ global
    op.execute('CREATE TABLE "global".modulos (codigo TEXT PRIMARY KEY, nombre TEXT NOT NULL)')
    op.execute('CREATE TABLE "global".acciones (codigo TEXT PRIMARY KEY, nombre TEXT NOT NULL)')
    op.execute(
        'INSERT INTO "global".modulos (codigo, nombre) VALUES '  # noqa: S608
        + ", ".join(f"('{c}', '{n}')" for c, n in MODULOS)
    )
    op.execute(
        'INSERT INTO "global".acciones (codigo, nombre) VALUES '  # noqa: S608
        + ", ".join(f"('{c}', '{n}')" for c, n in ACCIONES)
    )

    # -------------------------------------------------------------------- lab
    op.execute(
        """
        CREATE TABLE lab.usuarios (
            id                   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            uuid                 UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
            tenant_id            TEXT NOT NULL,
            email                CITEXT NOT NULL CHECK (email ~ '^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$'),
            nombre               TEXT NOT NULL CHECK (length(nombre) BETWEEN 2 AND 120),
            tipo                 TEXT NOT NULL CHECK (tipo IN ('PERSONAL', 'PACIENTE', 'MEDICO')),
            password_hash        TEXT NOT NULL CHECK (password_hash LIKE '$argon2id$%'),
            totp_secreto_cifrado BYTEA,
            totp_confirmado      BOOLEAN NOT NULL DEFAULT false,
            totp_ultimo_contador BIGINT,
            tarjeta_profesional  TEXT,
            estado               TEXT NOT NULL DEFAULT 'ACTIVO' CHECK (estado IN ('ACTIVO', 'INACTIVO')),
            bloqueado_hasta      TIMESTAMPTZ,
            creado_en            TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, email),
            UNIQUE (tenant_id, id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE lab.roles (
            id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            codigo    TEXT NOT NULL CHECK (codigo ~ '^[A-Z][A-Z0-9_]{1,39}$'),
            nombre    TEXT NOT NULL,
            sistema   BOOLEAN NOT NULL DEFAULT false,
            UNIQUE (tenant_id, codigo),
            UNIQUE (tenant_id, id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE lab.usuario_roles (
            tenant_id  TEXT NOT NULL,
            usuario_id BIGINT NOT NULL,
            rol_id     BIGINT NOT NULL,
            PRIMARY KEY (tenant_id, usuario_id, rol_id),
            FOREIGN KEY (tenant_id, usuario_id) REFERENCES lab.usuarios (tenant_id, id),
            FOREIGN KEY (tenant_id, rol_id) REFERENCES lab.roles (tenant_id, id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE lab.rol_permisos (
            tenant_id TEXT NOT NULL,
            rol_id    BIGINT NOT NULL,
            modulo    TEXT NOT NULL REFERENCES "global".modulos (codigo),
            consultar BOOLEAN NOT NULL DEFAULT false,
            crear     BOOLEAN NOT NULL DEFAULT false,
            modificar BOOLEAN NOT NULL DEFAULT false,
            eliminar  BOOLEAN NOT NULL DEFAULT false,
            PRIMARY KEY (tenant_id, rol_id, modulo),
            FOREIGN KEY (tenant_id, rol_id) REFERENCES lab.roles (tenant_id, id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE lab.rol_acciones (
            tenant_id TEXT NOT NULL,
            rol_id    BIGINT NOT NULL,
            accion    TEXT NOT NULL REFERENCES "global".acciones (codigo),
            PRIMARY KEY (tenant_id, rol_id, accion),
            FOREIGN KEY (tenant_id, rol_id) REFERENCES lab.roles (tenant_id, id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE lab.sesiones (
            id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            tenant_id         TEXT NOT NULL,
            usuario_id        BIGINT NOT NULL,
            token_hash        BYTEA NOT NULL UNIQUE CHECK (length(token_hash) = 32),
            segundo_factor_ok BOOLEAN NOT NULL DEFAULT false,
            creada_en         TIMESTAMPTZ NOT NULL DEFAULT now(),
            ultima_actividad  TIMESTAMPTZ NOT NULL DEFAULT now(),
            expira_en         TIMESTAMPTZ NOT NULL,
            revocada_en       TIMESTAMPTZ,
            ip                INET,
            agente            TEXT,
            FOREIGN KEY (tenant_id, usuario_id) REFERENCES lab.usuarios (tenant_id, id)
        )
        """
    )
    op.execute("CREATE INDEX ON lab.sesiones (tenant_id, usuario_id)")
    op.execute(
        """
        CREATE TABLE lab.codigos_verificacion (
            id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            tenant_id   TEXT NOT NULL,
            usuario_id  BIGINT NOT NULL,
            codigo_hmac BYTEA NOT NULL,
            creado_en   TIMESTAMPTZ NOT NULL DEFAULT now(),
            expira_en   TIMESTAMPTZ NOT NULL,
            usado_en    TIMESTAMPTZ,
            intentos    SMALLINT NOT NULL DEFAULT 0,
            FOREIGN KEY (tenant_id, usuario_id) REFERENCES lab.usuarios (tenant_id, id)
        )
        """
    )
    op.execute("CREATE INDEX ON lab.codigos_verificacion (tenant_id, usuario_id, creado_en)")
    op.execute(
        """
        CREATE TABLE lab.limites (
            tenant_id     TEXT NOT NULL,
            clave         TEXT NOT NULL,
            ventana_desde TIMESTAMPTZ NOT NULL,
            contador      INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (tenant_id, clave)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE lab.eventos_seguridad (
            id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            tenant_id  TEXT NOT NULL,
            tipo       TEXT NOT NULL,
            usuario_id BIGINT,
            email      CITEXT,
            ip         INET,
            ocurrido_en TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ON lab.eventos_seguridad (tenant_id, ocurrido_en)")

    # RLS estándar en todas las tablas nuevas de lab (spec infraestructura/0007).
    for tabla in TABLAS_LAB:
        op.execute(f"ALTER TABLE lab.{tabla} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE lab.{tabla} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY aislamiento_tenant ON lab.{tabla}"
            " USING (tenant_id = lab.tenant_actual()) WITH CHECK (tenant_id = lab.tenant_actual())"
        )

    # Eventos de seguridad: solo inserción, por permisos y por trigger.
    op.execute(f"REVOKE UPDATE, DELETE ON lab.eventos_seguridad FROM {APP}")
    op.execute(
        """
        CREATE FUNCTION lab.rechazar_modificacion() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'La tabla % es de solo inserción', TG_TABLE_NAME;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER eventos_seguridad_inmutables BEFORE UPDATE OR DELETE ON lab.eventos_seguridad"
        " FOR EACH ROW EXECUTE FUNCTION lab.rechazar_modificacion()"
    )
    # Las asignaciones de roles y permisos se pueden retirar.
    op.execute(f"GRANT DELETE ON lab.usuario_roles, lab.rol_permisos, lab.rol_acciones TO {APP}")
    op.execute(f'GRANT SELECT ON "global".modulos, "global".acciones TO {APP}')


def downgrade() -> None:
    for tabla in reversed(TABLAS_LAB):
        op.execute(f"DROP TABLE lab.{tabla}")
    op.execute("DROP FUNCTION lab.rechazar_modificacion()")
    op.execute('DROP TABLE "global".acciones')
    op.execute('DROP TABLE "global".modulos')
