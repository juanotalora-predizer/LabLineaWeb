"""Pacientes, autorización de tratamiento de datos y solicitudes del titular (etapa 7).

Spec funcional/0010 (Ley 1581). En global: expresión válida por tipo de documento, mayoría de edad y
plazos por país, festivos y el texto modelo de la autorización. En lab: pacientes, textos de
autorización versionados, autorizaciones y solicitudes del titular, todas con RLS forzado y
auditadas sin copiar los datos personales (columnas protegidas del trigger lab.auditar).

Reglas que impone la base:
- un paciente no se guarda sin su autorización (trigger diferido, al confirmar la transacción);
- una sola autorización vigente por paciente; una autorización solo se revoca, nunca se modifica;
- los textos de autorización no se modifican ni se borran (nueva versión);
- nada de esto se borra desde la aplicación (sin DELETE).

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP = "lablinea_app"

# Expresión válida del número por tipo de documento de Colombia. Por validar contra RIPS (backlog).
NUMERICOS_COL = ("CC", "TI", "RC", "CN")
PATRON_NUMERICO = "^[0-9]{3,12}$"
PATRON_ALFANUMERICO = "^[A-Z0-9-]{3,20}$"

# Festivos de Colombia (Ley 51 de 1983 y fiestas móviles según la Pascua). Datos del país, no código.
FESTIVOS_COL = (
    "2026-01-01", "2026-01-12", "2026-03-23", "2026-04-02", "2026-04-03", "2026-05-01", "2026-05-18",
    "2026-06-08", "2026-06-15", "2026-06-29", "2026-07-20", "2026-08-07", "2026-08-17", "2026-10-12",
    "2026-11-02", "2026-11-16", "2026-12-08", "2026-12-25",
    "2027-01-01", "2027-01-11", "2027-03-22", "2027-03-25", "2027-03-26", "2027-05-01", "2027-05-10",
    "2027-05-31", "2027-06-07", "2027-07-05", "2027-07-20", "2027-08-07", "2027-08-16", "2027-10-18",
    "2027-11-01", "2027-11-15", "2027-12-08", "2027-12-25",
)  # fmt: skip

# Texto modelo de Colombia; el laboratorio lo completa antes de publicarlo. Por validar con el asesor legal.
MODELO_AUTORIZACION_COL = """\
AUTORIZACIÓN PARA EL TRATAMIENTO DE DATOS PERSONALES Y DATOS SENSIBLES DE SALUD

Como titular (o representante legal del titular), autorizo de manera previa, expresa e informada a \
{laboratorio}, como Responsable del tratamiento, para recolectar, almacenar, usar y circular mis datos \
personales y mis datos de salud, que son datos sensibles, con las siguientes finalidades: prestar los \
servicios de laboratorio clínico solicitados, identificarme, tomar y procesar mis muestras, entregarme \
los resultados, facturar a mí o a mi entidad, y cumplir las obligaciones legales del laboratorio.

Se me informó que: (1) no estoy obligado a autorizar el tratamiento de datos sensibles, aunque sin \
ellos no es posible prestar el servicio de laboratorio; (2) mis datos se tratan en una plataforma \
tecnológica contratada por el laboratorio, que actúa como Encargado bajo contrato de transmisión de \
datos; (3) tengo derecho a conocer, actualizar, rectificar y suprimir mis datos, a pedir prueba de \
esta autorización, a ser informado del uso de mis datos, a revocar esta autorización y a presentar \
quejas ante la Superintendencia de Industria y Comercio (Ley 1581 de 2012); (4) la revocación y la \
supresión no proceden respecto de los datos que el laboratorio debe conservar por ley, como la \
historia clínica.

Canales para ejercer mis derechos: [correo electrónico, teléfono y dirección del laboratorio].
Política de tratamiento de datos: [dónde consultarla].
"""

TABLAS = [
    (
        "textos_autorizacion",
        """
        id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        uuid          UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
        tenant_id     TEXT NOT NULL DEFAULT lab.tenant_actual(),
        version       INTEGER NOT NULL CHECK (version >= 1),
        contenido     TEXT NOT NULL CHECK (length(contenido) BETWEEN 50 AND 20000),
        publicado_en  TIMESTAMPTZ NOT NULL DEFAULT now(),
        publicado_por UUID DEFAULT NULLIF(current_setting('app.current_user_id', true), '')::uuid,
        UNIQUE (tenant_id, version),
        UNIQUE (tenant_id, id)
        """,
    ),
    (
        "pacientes",
        """
        id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        uuid             UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
        tenant_id        TEXT NOT NULL DEFAULT lab.tenant_actual(),
        tipo_documento   TEXT NOT NULL CHECK (tipo_documento ~ '^[A-Z]{2,4}$'),
        numero_documento TEXT NOT NULL CHECK (length(numero_documento) BETWEEN 3 AND 60),
        nombres          TEXT NOT NULL CHECK (length(nombres) BETWEEN 1 AND 80),
        apellidos        TEXT NOT NULL CHECK (length(apellidos) BETWEEN 1 AND 80),
        sexo             CHAR(1) NOT NULL CHECK (sexo IN ('F', 'M', 'I')),
        fecha_nacimiento DATE CHECK (fecha_nacimiento >= DATE '1880-01-01'),
        pais             CHAR(3) NOT NULL REFERENCES "global".paises (codigo),
        email            TEXT CHECK (length(email) <= 254),
        telefono         TEXT CHECK (length(telefono) <= 30),
        direccion        TEXT CHECK (length(direccion) <= 200),
        estado           TEXT NOT NULL DEFAULT 'ACTIVO' CHECK (estado IN ('ACTIVO', 'SUPRIMIDO')),
        suprimido_en     TIMESTAMPTZ,
        creado_en        TIMESTAMPTZ NOT NULL DEFAULT now(),
        actualizado_en   TIMESTAMPTZ NOT NULL DEFAULT now(),
        CHECK (estado = 'SUPRIMIDO' OR fecha_nacimiento IS NOT NULL),
        CHECK ((estado = 'SUPRIMIDO') = (suprimido_en IS NOT NULL)),
        UNIQUE (tenant_id, tipo_documento, numero_documento),
        UNIQUE (tenant_id, id)
        """,
    ),
    (
        "autorizaciones_datos",
        """
        id                       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        uuid                     UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
        tenant_id                TEXT NOT NULL DEFAULT lab.tenant_actual(),
        paciente_id              BIGINT NOT NULL,
        texto_id                 BIGINT NOT NULL,
        medio                    TEXT NOT NULL CHECK (medio IN ('FORMATO_FIRMADO', 'ACEPTACION_EN_PANTALLA')),
        otorgada_en              TIMESTAMPTZ NOT NULL DEFAULT now(),
        registrada_por           UUID DEFAULT NULLIF(current_setting('app.current_user_id', true), '')::uuid,
        representante_nombre     TEXT CHECK (length(representante_nombre) BETWEEN 1 AND 120),
        representante_documento  TEXT CHECK (length(representante_documento) BETWEEN 1 AND 40),
        representante_parentesco TEXT CHECK (length(representante_parentesco) BETWEEN 1 AND 40),
        revocada_en              TIMESTAMPTZ,
        revocada_por             UUID,
        motivo_revocacion        TEXT CHECK (length(motivo_revocacion) BETWEEN 1 AND 500),
        CHECK (revocada_en IS NOT NULL OR (revocada_por IS NULL AND motivo_revocacion IS NULL)),
        CHECK (revocada_en IS NULL OR motivo_revocacion IS NOT NULL),
        UNIQUE (tenant_id, id),
        FOREIGN KEY (tenant_id, paciente_id) REFERENCES lab.pacientes (tenant_id, id),
        FOREIGN KEY (tenant_id, texto_id) REFERENCES lab.textos_autorizacion (tenant_id, id)
        """,
    ),
    (
        "solicitudes_titular",
        """
        id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        uuid         UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
        tenant_id    TEXT NOT NULL DEFAULT lab.tenant_actual(),
        paciente_id  BIGINT NOT NULL,
        tipo         TEXT NOT NULL
                     CHECK (tipo IN ('CONSULTA', 'ACTUALIZACION', 'RECTIFICACION', 'SUPRESION', 'REVOCACION')),
        canal        TEXT NOT NULL CHECK (canal IN ('PRESENCIAL', 'CORREO', 'TELEFONO', 'PORTAL')),
        descripcion  TEXT CHECK (length(descripcion) <= 2000),
        recibida_en  TIMESTAMPTZ NOT NULL DEFAULT now(),
        vence_en     DATE NOT NULL,
        estado       TEXT NOT NULL DEFAULT 'ABIERTA' CHECK (estado IN ('ABIERTA', 'RESUELTA', 'RECHAZADA')),
        respuesta    TEXT CHECK (length(respuesta) <= 2000),
        resuelta_en  TIMESTAMPTZ,
        resuelta_por UUID,
        registrada_por UUID DEFAULT NULLIF(current_setting('app.current_user_id', true), '')::uuid,
        CHECK ((estado = 'ABIERTA') = (resuelta_en IS NULL)),
        UNIQUE (tenant_id, id),
        FOREIGN KEY (tenant_id, paciente_id) REFERENCES lab.pacientes (tenant_id, id)
        """,
    ),
]

# Argumentos del trigger de auditoría: columnas personales protegidas (se registra que cambiaron, no el valor).
AUDITORIA = {
    "textos_autorizacion": "'-contenido'",
    "pacientes": "'nombres', 'apellidos', 'numero_documento', 'fecha_nacimiento', 'email', 'telefono', 'direccion'",
    "autorizaciones_datos": "'representante_nombre', 'representante_documento'",
    "solicitudes_titular": "'descripcion', 'respuesta'",
}


def upgrade() -> None:
    # ------------------------------------------------------------- global (configuración por país)
    op.execute('ALTER TABLE "global".tipos_documento ADD COLUMN patron TEXT')
    op.execute(
        f"UPDATE \"global\".tipos_documento SET patron = CASE WHEN codigo IN ({', '.join(f"'{c}'" for c in NUMERICOS_COL)})"
        f" THEN '{PATRON_NUMERICO}' ELSE '{PATRON_ALFANUMERICO}' END WHERE pais = 'COL'"  # noqa: S608 — constantes
    )
    op.execute(
        'ALTER TABLE "global".paises'
        " ADD COLUMN mayoria_edad SMALLINT NOT NULL DEFAULT 18 CHECK (mayoria_edad BETWEEN 14 AND 21),"
        " ADD COLUMN plazo_consulta_dias SMALLINT NOT NULL DEFAULT 10 CHECK (plazo_consulta_dias BETWEEN 1 AND 60),"
        " ADD COLUMN plazo_reclamo_dias SMALLINT NOT NULL DEFAULT 15 CHECK (plazo_reclamo_dias BETWEEN 1 AND 60)"
    )
    op.execute(
        'CREATE TABLE "global".festivos ('
        ' pais CHAR(3) NOT NULL REFERENCES "global".paises (codigo), fecha DATE NOT NULL, PRIMARY KEY (pais, fecha))'
    )
    valores = ", ".join(f"('COL', DATE '{f}')" for f in FESTIVOS_COL)
    op.execute(f'INSERT INTO "global".festivos (pais, fecha) VALUES {valores}')  # noqa: S608 — constantes
    op.execute(
        'CREATE TABLE "global".textos_legales ('
        ' pais CHAR(3) NOT NULL REFERENCES "global".paises (codigo),'
        " tipo TEXT NOT NULL CHECK (tipo IN ('AUTORIZACION_DATOS')),"
        " contenido TEXT NOT NULL, PRIMARY KEY (pais, tipo))"
    )
    op.execute(
        "INSERT INTO \"global\".textos_legales (pais, tipo, contenido) VALUES ('COL', 'AUTORIZACION_DATOS', $texto$"
        + MODELO_AUTORIZACION_COL
        + "$texto$)"
    )
    # Fecha de vencimiento: `dias` hábiles después de `desde` (sin fines de semana ni festivos del país).
    op.execute(
        """
        CREATE FUNCTION "global".sumar_dias_habiles(p_pais char(3), p_desde date, p_dias integer) RETURNS date
        LANGUAGE plpgsql STABLE
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE
          v_fecha date := p_desde;
          v_contados integer := 0;
        BEGIN
          IF p_dias < 0 OR p_dias > 365 THEN
            RAISE EXCEPTION 'Días fuera de rango: %', p_dias;
          END IF;
          WHILE v_contados < p_dias LOOP
            v_fecha := v_fecha + 1;
            IF extract(isodow FROM v_fecha) < 6
               AND NOT EXISTS (SELECT 1 FROM "global".festivos f WHERE f.pais = p_pais AND f.fecha = v_fecha) THEN
              v_contados := v_contados + 1;
            END IF;
          END LOOP;
          RETURN v_fecha;
        END $$
        """
    )

    # ------------------------------------------------------------------------------------ lab
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
            f" FOR EACH ROW EXECUTE FUNCTION lab.auditar({AUDITORIA[tabla]})"
        )
    op.execute("CREATE INDEX ON lab.pacientes (tenant_id, apellidos)")
    op.execute("CREATE INDEX ON lab.autorizaciones_datos (tenant_id, paciente_id)")
    op.execute("CREATE INDEX ON lab.solicitudes_titular (tenant_id, paciente_id)")
    op.execute("CREATE INDEX ON lab.solicitudes_titular (tenant_id, vence_en) WHERE estado = 'ABIERTA'")
    op.execute(
        "CREATE UNIQUE INDEX autorizacion_vigente_unica ON lab.autorizaciones_datos (tenant_id, paciente_id)"
        " WHERE revocada_en IS NULL"
    )
    # Los textos publicados no cambian: una corrección es una versión nueva.
    op.execute(f"REVOKE UPDATE ON lab.textos_autorizacion FROM {APP}")

    # Un paciente no existe sin su autorización: se verifica al confirmar la transacción que lo crea.
    op.execute(
        """
        CREATE FUNCTION lab.exigir_autorizacion() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM lab.autorizaciones_datos a
                         WHERE a.tenant_id = NEW.tenant_id AND a.paciente_id = NEW.id) THEN
            RAISE EXCEPTION 'Paciente sin autorización de tratamiento de datos' USING ERRCODE = 'check_violation';
          END IF;
          RETURN NULL;
        END $$
        """
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER exige_autorizacion AFTER INSERT ON lab.pacientes"
        " DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION lab.exigir_autorizacion()"
    )

    # Una autorización solo se revoca (una vez). La supresión borra los datos del representante.
    op.execute(
        """
        CREATE FUNCTION lab.proteger_autorizacion() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        BEGIN
          IF (NEW.id, NEW.uuid, NEW.tenant_id, NEW.paciente_id, NEW.texto_id, NEW.medio, NEW.otorgada_en,
              NEW.registrada_por)
             IS DISTINCT FROM
             (OLD.id, OLD.uuid, OLD.tenant_id, OLD.paciente_id, OLD.texto_id, OLD.medio, OLD.otorgada_en,
              OLD.registrada_por) THEN
            RAISE EXCEPTION 'Una autorización no se modifica' USING ERRCODE = 'check_violation';
          END IF;
          IF OLD.revocada_en IS NOT NULL AND (NEW.revocada_en, NEW.revocada_por, NEW.motivo_revocacion)
             IS DISTINCT FROM (OLD.revocada_en, OLD.revocada_por, OLD.motivo_revocacion) THEN
            RAISE EXCEPTION 'La autorización ya fue revocada' USING ERRCODE = 'check_violation';
          END IF;
          IF (NEW.representante_nombre IS DISTINCT FROM OLD.representante_nombre
              AND NEW.representante_nombre IS NOT NULL)
             OR (NEW.representante_documento IS DISTINCT FROM OLD.representante_documento
                 AND NEW.representante_documento IS NOT NULL)
             OR (NEW.representante_parentesco IS DISTINCT FROM OLD.representante_parentesco
                 AND NEW.representante_parentesco IS NOT NULL) THEN
            RAISE EXCEPTION 'El representante no se modifica' USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER proteger BEFORE UPDATE ON lab.autorizaciones_datos"
        " FOR EACH ROW EXECUTE FUNCTION lab.proteger_autorizacion()"
    )

    # Funciones para las etapas siguientes: las órdenes exigen autorización vigente (etapa 8).
    op.execute(
        """
        CREATE FUNCTION lab.autorizacion_vigente(p_paciente bigint) RETURNS boolean
        LANGUAGE sql STABLE
        SET search_path = pg_catalog, pg_temp
        AS $$
          SELECT EXISTS (SELECT 1 FROM lab.autorizaciones_datos a JOIN lab.pacientes p ON p.id = a.paciente_id
                         WHERE a.paciente_id = p_paciente AND a.revocada_en IS NULL AND p.estado = 'ACTIVO')
        $$
        """
    )
    # Historia clínica que impide suprimir; la etapa 8 la redefine con las órdenes del paciente.
    op.execute(
        """
        CREATE FUNCTION lab.paciente_tiene_historia(p_paciente bigint) RETURNS boolean
        LANGUAGE sql STABLE
        SET search_path = pg_catalog, pg_temp
        AS $$ SELECT false $$
        """
    )
    for funcion in ("lab.autorizacion_vigente(bigint)", "lab.paciente_tiene_historia(bigint)"):
        op.execute(f"REVOKE ALL ON FUNCTION {funcion} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {funcion} TO {APP}")


def downgrade() -> None:
    op.execute("DROP FUNCTION lab.paciente_tiene_historia(bigint)")
    op.execute("DROP FUNCTION lab.autorizacion_vigente(bigint)")
    for tabla, _ in reversed(TABLAS):
        op.execute(f"DROP TABLE lab.{tabla}")
    op.execute("DROP FUNCTION lab.proteger_autorizacion()")
    op.execute("DROP FUNCTION lab.exigir_autorizacion()")
    op.execute('DROP FUNCTION "global".sumar_dias_habiles(char, date, integer)')
    op.execute('DROP TABLE "global".textos_legales')
    op.execute('DROP TABLE "global".festivos')
    op.execute(
        'ALTER TABLE "global".paises DROP COLUMN mayoria_edad, DROP COLUMN plazo_consulta_dias,'
        " DROP COLUMN plazo_reclamo_dias"
    )
    op.execute('ALTER TABLE "global".tipos_documento DROP COLUMN patron')
