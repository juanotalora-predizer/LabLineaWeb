"""Catálogo de exámenes del laboratorio e importaciones desde Lablinea (etapa 6).

Specs funcional/0003 (requisitos de muestra), 0004 (exámenes, parámetros, rangos) y 0009 (importador).

Todas las tablas en lab: tenant_id con RLS forzado, auditadas, UUID público en las entidades que
aparecen en URLs. Dinero en NUMERIC(14,2). Los exámenes y parámetros no se borran (se desactivan):
las órdenes futuras los referencian. Rangos, valores de lista, requisitos, precios y códigos sí.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP = "lablinea_app"

# (tabla, DDL) en orden de creación; el downgrade las borra al revés.
TABLAS = [
    (
        "secciones",
        """
        id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        uuid      UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
        tenant_id TEXT NOT NULL DEFAULT lab.tenant_actual(),
        codigo    TEXT NOT NULL CHECK (length(codigo) BETWEEN 1 AND 50),
        nombre    TEXT NOT NULL CHECK (length(nombre) BETWEEN 1 AND 120),
        orden     INTEGER NOT NULL DEFAULT 0,
        activa    BOOLEAN NOT NULL DEFAULT true,
        UNIQUE (tenant_id, codigo),
        UNIQUE (tenant_id, id)
        """,
    ),
    (
        "unidades",
        """
        id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        tenant_id TEXT NOT NULL DEFAULT lab.tenant_actual(),
        codigo    TEXT NOT NULL CHECK (length(codigo) BETWEEN 1 AND 50),
        nombre    TEXT NOT NULL CHECK (length(nombre) BETWEEN 1 AND 60),
        ucum      TEXT CHECK (length(ucum) <= 40),
        UNIQUE (tenant_id, codigo),
        UNIQUE (tenant_id, id)
        """,
    ),
    (
        "tipos_muestra",
        """
        id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        tenant_id TEXT NOT NULL DEFAULT lab.tenant_actual(),
        codigo    TEXT NOT NULL CHECK (length(codigo) BETWEEN 1 AND 10),
        nombre    TEXT NOT NULL CHECK (length(nombre) BETWEEN 1 AND 60),
        UNIQUE (tenant_id, codigo),
        UNIQUE (tenant_id, id)
        """,
    ),
    (
        "tipos_tubo",
        """
        id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        tenant_id    TEXT NOT NULL DEFAULT lab.tenant_actual(),
        codigo       TEXT NOT NULL CHECK (length(codigo) BETWEEN 1 AND 20),
        nombre       TEXT NOT NULL CHECK (length(nombre) BETWEEN 1 AND 60),
        aditivo      TEXT CHECK (length(aditivo) <= 60),
        capacidad_ml NUMERIC(6,2) NOT NULL CHECK (capacidad_ml > 0),
        UNIQUE (tenant_id, codigo),
        UNIQUE (tenant_id, id)
        """,
    ),
    (
        "tecnicas",
        """
        id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        tenant_id TEXT NOT NULL DEFAULT lab.tenant_actual(),
        nombre    TEXT NOT NULL CHECK (length(nombre) BETWEEN 1 AND 120),
        UNIQUE (tenant_id, nombre),
        UNIQUE (tenant_id, id)
        """,
    ),
    (
        "examenes",
        """
        id                    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        uuid                  UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
        tenant_id             TEXT NOT NULL DEFAULT lab.tenant_actual(),
        codigo                TEXT NOT NULL CHECK (length(codigo) BETWEEN 1 AND 20),
        nombre                TEXT NOT NULL CHECK (length(nombre) BETWEEN 2 AND 120),
        seccion_id            BIGINT NOT NULL,
        tecnica_id            BIGINT,
        codigo_nacional       TEXT CHECK (length(codigo_nacional) <= 20),  -- CUPS en Colombia
        loinc                 TEXT CHECK (loinc ~ '^[0-9]{1,7}-[0-9]$'),
        requiere_autorizacion BOOLEAN NOT NULL DEFAULT false,
        dias_procesamiento    TEXT CHECK (length(dias_procesamiento) <= 30),
        codigo_lablinea       INTEGER,  -- consecutivo de origen en Lablinea (importación)
        activo                BOOLEAN NOT NULL DEFAULT true,
        creado_en             TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (tenant_id, codigo),
        UNIQUE (tenant_id, nombre),
        UNIQUE (tenant_id, codigo_lablinea),
        UNIQUE (tenant_id, id),
        FOREIGN KEY (tenant_id, seccion_id) REFERENCES lab.secciones (tenant_id, id),
        FOREIGN KEY (tenant_id, tecnica_id) REFERENCES lab.tecnicas (tenant_id, id)
        """,
    ),
    (
        "parametros",
        """
        id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        uuid            UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
        tenant_id       TEXT NOT NULL DEFAULT lab.tenant_actual(),
        examen_id       BIGINT NOT NULL,
        nombre          TEXT NOT NULL CHECK (length(nombre) BETWEEN 1 AND 120),
        orden           INTEGER NOT NULL DEFAULT 0,
        tipo            TEXT NOT NULL CHECK (tipo IN ('NUMERICO', 'TEXTO', 'LISTA', 'TITULO')),
        unidad_id       BIGINT,
        decimales       SMALLINT NOT NULL DEFAULT 2 CHECK (decimales BETWEEN 0 AND 6),
        loinc           TEXT CHECK (loinc ~ '^[0-9]{1,7}-[0-9]$'),
        grafica         BOOLEAN NOT NULL DEFAULT false,
        codigo_lablinea INTEGER,
        activo          BOOLEAN NOT NULL DEFAULT true,
        UNIQUE (tenant_id, codigo_lablinea),
        UNIQUE (tenant_id, id),
        FOREIGN KEY (tenant_id, examen_id) REFERENCES lab.examenes (tenant_id, id),
        FOREIGN KEY (tenant_id, unidad_id) REFERENCES lab.unidades (tenant_id, id)
        """,
    ),
    (
        "valores_lista",
        """
        id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        tenant_id    TEXT NOT NULL DEFAULT lab.tenant_actual(),
        parametro_id BIGINT NOT NULL,
        valor        TEXT NOT NULL CHECK (length(valor) BETWEEN 1 AND 120),
        orden        INTEGER NOT NULL DEFAULT 0,
        es_normal    BOOLEAN NOT NULL DEFAULT false,
        UNIQUE (tenant_id, parametro_id, valor),
        FOREIGN KEY (tenant_id, parametro_id) REFERENCES lab.parametros (tenant_id, id)
        """,
    ),
    (
        "rangos_referencia",
        """
        id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        uuid              UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
        tenant_id         TEXT NOT NULL DEFAULT lab.tenant_actual(),
        parametro_id      BIGINT NOT NULL,
        sexo              TEXT NOT NULL DEFAULT 'T' CHECK (sexo IN ('M', 'F', 'T')),
        edad_min_dias     INTEGER NOT NULL DEFAULT 0 CHECK (edad_min_dias >= 0),
        edad_max_dias     INTEGER NOT NULL DEFAULT 54750 CHECK (edad_max_dias <= 54750),  -- 150 años
        minimo            NUMERIC(14,4),
        maximo            NUMERIC(14,4),
        critico_min       NUMERIC(14,4),
        critico_max       NUMERIC(14,4),
        valor_esperado    TEXT CHECK (length(valor_esperado) <= 120),
        texto_impreso     TEXT CHECK (length(texto_impreso) <= 255),
        requiere_revision BOOLEAN NOT NULL DEFAULT false,
        CHECK (edad_min_dias < edad_max_dias),
        CHECK (minimo IS NULL OR maximo IS NULL OR minimo <= maximo),
        CHECK (critico_min IS NULL OR minimo IS NULL OR critico_min <= minimo),
        CHECK (critico_max IS NULL OR maximo IS NULL OR critico_max >= maximo),
        FOREIGN KEY (tenant_id, parametro_id) REFERENCES lab.parametros (tenant_id, id)
        """,
    ),
    (
        "requisitos_muestra",
        """
        id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        uuid              UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
        tenant_id         TEXT NOT NULL DEFAULT lab.tenant_actual(),
        examen_id         BIGINT NOT NULL,
        tipo_muestra_id   BIGINT NOT NULL,
        tipo_tubo_id      BIGINT,
        volumen_ml        NUMERIC(6,2) CHECK (volumen_ml > 0),
        requiere_revision BOOLEAN NOT NULL DEFAULT false,
        UNIQUE (tenant_id, examen_id, tipo_muestra_id),
        FOREIGN KEY (tenant_id, examen_id) REFERENCES lab.examenes (tenant_id, id),
        FOREIGN KEY (tenant_id, tipo_muestra_id) REFERENCES lab.tipos_muestra (tenant_id, id),
        FOREIGN KEY (tenant_id, tipo_tubo_id) REFERENCES lab.tipos_tubo (tenant_id, id)
        """,
    ),
    (
        "tarifas",
        """
        id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        uuid      UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
        tenant_id TEXT NOT NULL DEFAULT lab.tenant_actual(),
        codigo    TEXT NOT NULL CHECK (length(codigo) BETWEEN 1 AND 15),
        nombre    TEXT NOT NULL CHECK (length(nombre) BETWEEN 1 AND 60),
        moneda    CHAR(3) NOT NULL REFERENCES "global".monedas (codigo),
        activa    BOOLEAN NOT NULL DEFAULT true,
        UNIQUE (tenant_id, codigo),
        UNIQUE (tenant_id, id)
        """,
    ),
    (
        "precios_examen",
        """
        tenant_id TEXT NOT NULL DEFAULT lab.tenant_actual(),
        tarifa_id BIGINT NOT NULL,
        examen_id BIGINT NOT NULL,
        valor     NUMERIC(14,2) NOT NULL CHECK (valor >= 0),
        PRIMARY KEY (tenant_id, tarifa_id, examen_id),
        FOREIGN KEY (tenant_id, tarifa_id) REFERENCES lab.tarifas (tenant_id, id),
        FOREIGN KEY (tenant_id, examen_id) REFERENCES lab.examenes (tenant_id, id)
        """,
    ),
    (
        "tipos_codigo_alterno",
        """
        id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        tenant_id TEXT NOT NULL DEFAULT lab.tenant_actual(),
        codigo    TEXT NOT NULL CHECK (length(codigo) BETWEEN 1 AND 10),
        nombre    TEXT NOT NULL CHECK (length(nombre) BETWEEN 1 AND 60),
        UNIQUE (tenant_id, codigo),
        UNIQUE (tenant_id, id)
        """,
    ),
    (
        "codigos_alternos",
        """
        tenant_id TEXT NOT NULL DEFAULT lab.tenant_actual(),
        tipo_id   BIGINT NOT NULL,
        examen_id BIGINT NOT NULL,
        codigo    TEXT NOT NULL CHECK (length(codigo) BETWEEN 1 AND 20),
        PRIMARY KEY (tenant_id, tipo_id, examen_id),
        FOREIGN KEY (tenant_id, tipo_id) REFERENCES lab.tipos_codigo_alterno (tenant_id, id),
        FOREIGN KEY (tenant_id, examen_id) REFERENCES lab.examenes (tenant_id, id)
        """,
    ),
    (
        "importaciones",
        """
        id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        uuid             UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
        tenant_id        TEXT NOT NULL DEFAULT lab.tenant_actual(),
        usuario_id       BIGINT NOT NULL,
        nombre_archivo   TEXT NOT NULL CHECK (length(nombre_archivo) BETWEEN 1 AND 120),
        sha256           BYTEA NOT NULL CHECK (length(sha256) = 32),
        tamano           INTEGER NOT NULL CHECK (tamano > 0),
        contenido        BYTEA CHECK (length(contenido) <= 10485760),  -- se borra al cargar o descartar
        estado           TEXT NOT NULL DEFAULT 'PREVISTA' CHECK (estado IN ('PREVISTA', 'CARGADA', 'DESCARTADA')),
        resumen          JSONB NOT NULL,
        creada_en        TIMESTAMPTZ NOT NULL DEFAULT now(),
        terminada_en     TIMESTAMPTZ,
        FOREIGN KEY (tenant_id, usuario_id) REFERENCES lab.usuarios (tenant_id, id)
        """,
    ),
]

# Columnas que la auditoría no copia (el archivo importado es grande; queda su hash).
AUDITORIA_IGNORA = {"importaciones": "'-contenido'"}
# Tablas de las que la aplicación puede borrar filas (las demás se desactivan).
CON_BORRADO = ("valores_lista", "rangos_referencia", "requisitos_muestra", "precios_examen", "codigos_alternos")


def upgrade() -> None:
    # Nombre del sistema de códigos de procedimientos de cada país (nada de un país escrito en el código).
    op.execute('ALTER TABLE "global".paises ADD COLUMN terminologia_procedimientos TEXT')
    op.execute("UPDATE \"global\".paises SET terminologia_procedimientos = 'CUPS' WHERE codigo = 'COL'")

    for tabla, ddl in TABLAS:
        op.execute(f"CREATE TABLE lab.{tabla} ({ddl})")
        op.execute(f"ALTER TABLE lab.{tabla} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE lab.{tabla} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY aislamiento_tenant ON lab.{tabla}"
            " USING (tenant_id = lab.tenant_actual()) WITH CHECK (tenant_id = lab.tenant_actual())"
        )
        op.execute(
            f"CREATE TRIGGER auditoria AFTER INSERT OR UPDATE OR DELETE ON lab.{tabla}"
            f" FOR EACH ROW EXECUTE FUNCTION lab.auditar({AUDITORIA_IGNORA.get(tabla, '')})"
        )
    op.execute("CREATE INDEX ON lab.examenes (tenant_id, seccion_id)")
    op.execute("CREATE INDEX ON lab.parametros (tenant_id, examen_id, orden)")
    op.execute("CREATE INDEX ON lab.rangos_referencia (tenant_id, parametro_id)")
    op.execute(f"GRANT DELETE ON {', '.join('lab.' + t for t in CON_BORRADO)} TO {APP}")


def downgrade() -> None:
    for tabla, _ in reversed(TABLAS):
        op.execute(f"DROP TABLE lab.{tabla}")
    op.execute('ALTER TABLE "global".paises DROP COLUMN terminologia_procedimientos')
