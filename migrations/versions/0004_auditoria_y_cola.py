"""Auditoría de datos y cola de tareas (etapa 3).

Auditoría (spec infraestructura/0007, sección 5):
- lab.auditoria: particionada por mes, con RLS forzado. Solo inserción: el rol de la aplicación
  solo la lee; escriben los triggers y lab.registrar_acceso (SECURITY DEFINER), y un trigger
  rechaza UPDATE, DELETE y TRUNCATE incluso al dueño.
- lab.auditar(): trigger genérico con el registro antes y después. Los argumentos del trigger
  nombran columnas secretas ("[protegido]") o ignoradas ("-columna").
- Particiones: lab.crear_particion_auditoria(mes) crea el mes con RLS forzado y sin privilegios
  para la aplicación (las particiones se pueden consultar directamente y no heredan el RLS).

Cola de tareas (spec infraestructura/0012):
- cola.tareas: sin acceso directo para la aplicación; solo por funciones SECURITY DEFINER.
  Se encola siempre para el laboratorio de la transacción (lab.tenant_actual()).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP = "lablinea_app"

# Tablas auditadas y argumentos del trigger: columnas secretas o "-ignoradas".
AUDITADAS = {
    "usuarios": ("password_hash", "totp_secreto_cifrado", "-totp_ultimo_contador"),
    "roles": (),
    "usuario_roles": (),
    "rol_permisos": (),
    "rol_acciones": (),
}

# Meses con partición creada por la migración; el trabajador crea los siguientes.
MESES_INICIALES = 12


def upgrade() -> None:
    # ============================================================ auditoría
    op.execute(
        """
        CREATE TABLE lab.auditoria (
            id          BIGINT GENERATED ALWAYS AS IDENTITY,
            tenant_id   TEXT NOT NULL,
            tabla       TEXT NOT NULL CHECK (length(tabla) BETWEEN 1 AND 80),
            operacion   TEXT NOT NULL CHECK (operacion IN ('INSERT', 'UPDATE', 'DELETE', 'READ', 'EXPORT', 'ACCESO')),
            registro_id BIGINT,
            usuario_id  TEXT,
            ip          INET,
            resultado   TEXT NOT NULL DEFAULT 'EXITO' CHECK (resultado IN ('EXITO', 'DENEGADO')),
            antes       JSONB,
            despues     JSONB,
            ocurrido_en TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id, ocurrido_en)
        ) PARTITION BY RANGE (ocurrido_en)
        """
    )
    op.execute("CREATE INDEX ON lab.auditoria (tenant_id, ocurrido_en)")
    op.execute("CREATE INDEX ON lab.auditoria (tenant_id, tabla, registro_id)")
    op.execute("ALTER TABLE lab.auditoria ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE lab.auditoria FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY aislamiento_tenant ON lab.auditoria"
        " USING (tenant_id = lab.tenant_actual()) WITH CHECK (tenant_id = lab.tenant_actual())"
    )
    # La aplicación solo lee (bajo RLS). Escribir: triggers y lab.registrar_acceso.
    op.execute(f"REVOKE ALL ON lab.auditoria FROM {APP}")
    op.execute(f"GRANT SELECT ON lab.auditoria TO {APP}")

    # Segunda barrera: ni siquiera el dueño modifica, borra ni vacía la auditoría.
    op.execute(
        "CREATE TRIGGER auditoria_inmutable BEFORE UPDATE OR DELETE ON lab.auditoria"
        " FOR EACH ROW EXECUTE FUNCTION lab.rechazar_modificacion()"
    )
    op.execute(
        """
        CREATE FUNCTION lab.rechazar_vaciado() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'La tabla % es de solo inserción', TG_TABLE_NAME;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER auditoria_sin_vaciado BEFORE TRUNCATE ON lab.auditoria"
        " FOR EACH STATEMENT EXECUTE FUNCTION lab.rechazar_vaciado()"
    )

    # Particiones mensuales. Cada una con RLS forzado y sin privilegios para la aplicación:
    # una partición consultada directamente aplica SUS políticas, no las de la tabla madre.
    op.execute(
        f"""
        CREATE FUNCTION lab.crear_particion_auditoria(p_mes date) RETURNS text
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE
          v_desde date := date_trunc('month', p_mes)::date;
          v_nombre text := 'auditoria_' || to_char(v_desde, 'YYYY_MM');
        BEGIN
          IF v_desde < date_trunc('month', now())::date - interval '1 month'
             OR v_desde > date_trunc('month', now())::date + interval '24 months' THEN
            RAISE EXCEPTION 'Mes fuera del rango permitido: %', v_desde;
          END IF;
          IF to_regclass('lab.' || v_nombre) IS NOT NULL THEN
            RETURN v_nombre;
          END IF;
          EXECUTE format('CREATE TABLE lab.%I PARTITION OF lab.auditoria FOR VALUES FROM (%L) TO (%L)',
                         v_nombre, v_desde, (v_desde + interval '1 month')::date);
          EXECUTE format('ALTER TABLE lab.%I ENABLE ROW LEVEL SECURITY', v_nombre);
          EXECUTE format('ALTER TABLE lab.%I FORCE ROW LEVEL SECURITY', v_nombre);
          EXECUTE format('CREATE POLICY aislamiento_tenant ON lab.%I USING (tenant_id = lab.tenant_actual())'
                         ' WITH CHECK (tenant_id = lab.tenant_actual())', v_nombre);
          EXECUTE format('REVOKE ALL ON lab.%I FROM PUBLIC, {APP}', v_nombre);
          RETURN v_nombre;
        END $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION lab.crear_particion_auditoria(date) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION lab.crear_particion_auditoria(date) TO {APP}")
    op.execute(
        f"SELECT lab.crear_particion_auditoria((date_trunc('month', now()) + make_interval(months => m))::date)"
        f" FROM generate_series(0, {MESES_INICIALES - 1}) AS m"
    )
    # Red de seguridad: si falta el mes, la fila cae aquí en lugar de perderse la escritura.
    op.execute("CREATE TABLE lab.auditoria_sin_particion PARTITION OF lab.auditoria DEFAULT")
    op.execute("ALTER TABLE lab.auditoria_sin_particion ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE lab.auditoria_sin_particion FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY aislamiento_tenant ON lab.auditoria_sin_particion"
        " USING (tenant_id = lab.tenant_actual()) WITH CHECK (tenant_id = lab.tenant_actual())"
    )
    op.execute(f"REVOKE ALL ON lab.auditoria_sin_particion FROM PUBLIC, {APP}")

    # Trigger genérico de escrituras: registro antes y después, usuario e IP de la transacción.
    op.execute(
        """
        CREATE FUNCTION lab.auditar() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE
          v_antes   jsonb := CASE WHEN TG_OP <> 'INSERT' THEN to_jsonb(OLD) END;
          v_despues jsonb := CASE WHEN TG_OP <> 'DELETE' THEN to_jsonb(NEW) END;
          v_fila    jsonb := coalesce(v_despues, v_antes);
          v_columna text;
        BEGIN
          FOREACH v_columna IN ARRAY coalesce(TG_ARGV, '{}'::text[]) LOOP
            IF left(v_columna, 1) = '-' THEN
              v_antes := v_antes - substr(v_columna, 2);
              v_despues := v_despues - substr(v_columna, 2);
            ELSE
              IF v_despues ? v_columna THEN
                v_despues := jsonb_set(v_despues, ARRAY[v_columna], to_jsonb(
                  CASE WHEN v_antes IS NOT NULL AND v_antes -> v_columna IS DISTINCT FROM v_despues -> v_columna
                       THEN '[protegido, modificado]' ELSE '[protegido]' END));
              END IF;
              IF v_antes ? v_columna THEN
                v_antes := jsonb_set(v_antes, ARRAY[v_columna], to_jsonb('[protegido]'::text));
              END IF;
            END IF;
          END LOOP;
          -- Un UPDATE que solo toca columnas ignoradas no es un cambio auditable.
          IF TG_OP = 'UPDATE' AND v_antes = v_despues THEN
            RETURN NULL;
          END IF;
          INSERT INTO lab.auditoria (tenant_id, tabla, operacion, registro_id, usuario_id, ip, antes, despues)
          VALUES (
            v_fila ->> 'tenant_id', TG_TABLE_NAME, TG_OP,
            CASE WHEN jsonb_typeof(v_fila -> 'id') = 'number' THEN (v_fila ->> 'id')::bigint END,
            NULLIF(current_setting('app.current_user_id', true), ''),
            NULLIF(current_setting('app.client_ip', true), '')::inet,
            v_antes, v_despues);
          RETURN NULL;
        END $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION lab.auditar() FROM PUBLIC")
    for tabla, argumentos in AUDITADAS.items():
        lista = ", ".join(f"'{a}'" for a in argumentos)
        op.execute(
            f"CREATE TRIGGER auditoria AFTER INSERT OR UPDATE OR DELETE ON lab.{tabla}"
            f" FOR EACH ROW EXECUTE FUNCTION lab.auditar({lista})"
        )

    # Accesos que no son escrituras (lecturas, exportaciones, accesos denegados): los registra la
    # aplicación, siempre en el laboratorio, con el usuario y la IP de la transacción.
    op.execute(
        """
        CREATE FUNCTION lab.registrar_acceso(p_tabla text, p_operacion text, p_registro_id bigint,
                                             p_resultado text, p_detalle jsonb) RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
        BEGIN
          IF lab.tenant_actual() IS NULL THEN
            RAISE EXCEPTION 'Acceso sin laboratorio';
          END IF;
          IF p_operacion NOT IN ('READ', 'EXPORT', 'ACCESO') THEN
            RAISE EXCEPTION 'Operación no permitida: %', p_operacion;
          END IF;
          INSERT INTO lab.auditoria (tenant_id, tabla, operacion, registro_id, usuario_id, ip, resultado, despues)
          VALUES (lab.tenant_actual(), p_tabla, p_operacion, p_registro_id,
                  NULLIF(current_setting('app.current_user_id', true), ''),
                  NULLIF(current_setting('app.client_ip', true), '')::inet,
                  p_resultado, p_detalle);
        END $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION lab.registrar_acceso(text, text, bigint, text, jsonb) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION lab.registrar_acceso(text, text, bigint, text, jsonb) TO {APP}")

    # ======================================================= cola de tareas
    op.execute("CREATE SCHEMA cola")
    op.execute(
        """
        CREATE TABLE cola.tareas (
            id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            uuid            UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
            tenant_id       TEXT NOT NULL REFERENCES plataforma.laboratorios (tenant_id),
            tipo            TEXT NOT NULL CHECK (tipo ~ '^[a-z][a-z0-9_.]{2,63}$'),
            datos           JSONB NOT NULL DEFAULT '{}'
                            CHECK (jsonb_typeof(datos) = 'object' AND length(datos::text) <= 4096),
            clave_unica     TEXT CHECK (length(clave_unica) <= 200),
            estado          TEXT NOT NULL DEFAULT 'PENDIENTE'
                            CHECK (estado IN ('PENDIENTE', 'EN_CURSO', 'COMPLETADA', 'FALLIDA')),
            intentos        SMALLINT NOT NULL DEFAULT 0,
            max_intentos    SMALLINT NOT NULL DEFAULT 5 CHECK (max_intentos BETWEEN 1 AND 20),
            disponible_en   TIMESTAMPTZ NOT NULL DEFAULT now(),
            bloqueada_hasta TIMESTAMPTZ,
            ficha           UUID,
            ultimo_error    TEXT CHECK (length(ultimo_error) <= 200),
            creada_en       TIMESTAMPTZ NOT NULL DEFAULT now(),
            terminada_en    TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX tareas_clave_unica ON cola.tareas (tenant_id, tipo, clave_unica)"
        " WHERE clave_unica IS NOT NULL"
    )
    op.execute("CREATE INDEX tareas_por_tomar ON cola.tareas (disponible_en) WHERE estado IN ('PENDIENTE', 'EN_CURSO')")

    # Encolar: siempre para el laboratorio de la transacción. Con clave única es idempotente.
    op.execute(
        """
        CREATE FUNCTION cola.encolar(p_tipo text, p_datos jsonb, p_clave_unica text,
                                     p_en_segundos integer, p_max_intentos integer) RETURNS uuid
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE
          v_tenant text := lab.tenant_actual();
          v_uuid uuid;
        BEGIN
          IF v_tenant IS NULL THEN
            RAISE EXCEPTION 'No se puede encolar sin laboratorio';
          END IF;
          INSERT INTO cola.tareas (tenant_id, tipo, datos, clave_unica, disponible_en, max_intentos)
          VALUES (v_tenant, p_tipo, coalesce(p_datos, '{}'), p_clave_unica,
                  now() + make_interval(secs => greatest(p_en_segundos, 0)), p_max_intentos)
          ON CONFLICT (tenant_id, tipo, clave_unica) WHERE clave_unica IS NOT NULL DO NOTHING
          RETURNING uuid INTO v_uuid;
          IF v_uuid IS NULL THEN
            SELECT uuid INTO v_uuid FROM cola.tareas
            WHERE tenant_id = v_tenant AND tipo = p_tipo AND clave_unica = p_clave_unica;
          END IF;
          RETURN v_uuid;
        END $$
        """
    )

    # Tomar: una tarea disponible, con plazo (bloqueada_hasta) y una ficha nueva. Si el trabajador
    # muere, la tarea vuelve a estar disponible al vencer el plazo; la ficha anterior deja de servir.
    op.execute(
        """
        CREATE FUNCTION cola.tomar(p_plazo_segundos integer)
        RETURNS TABLE (id bigint, uuid uuid, tenant_id text, tipo text, datos jsonb,
                       intentos smallint, max_intentos smallint, ficha uuid)
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
        BEGIN
          -- Plazo vencido sin intentos restantes: falla definitivamente.
          UPDATE cola.tareas t SET estado = 'FALLIDA', ficha = NULL, terminada_en = now(),
                 ultimo_error = 'PlazoVencido'
          WHERE t.estado = 'EN_CURSO' AND t.bloqueada_hasta < now() AND t.intentos >= t.max_intentos;

          RETURN QUERY
          UPDATE cola.tareas t SET estado = 'EN_CURSO', intentos = t.intentos + 1,
                 bloqueada_hasta = now() + make_interval(secs => p_plazo_segundos), ficha = gen_random_uuid()
          WHERE t.id = (
              SELECT c.id FROM cola.tareas c
              WHERE (c.estado = 'PENDIENTE' AND c.disponible_en <= now())
                 OR (c.estado = 'EN_CURSO' AND c.bloqueada_hasta < now())
              ORDER BY c.disponible_en, c.id
              LIMIT 1
              FOR UPDATE SKIP LOCKED)
          RETURNING t.id, t.uuid, t.tenant_id, t.tipo, t.datos, t.intentos, t.max_intentos, t.ficha;
        END $$
        """
    )

    # Completar: dentro de la misma transacción del manejador y con su laboratorio fijado. Si la
    # ficha ya no es la vigente (otro trabajador la tomó), devuelve false y el manejador se revierte.
    op.execute(
        """
        CREATE FUNCTION cola.completar(p_id bigint, p_ficha uuid) RETURNS boolean
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE v_ok boolean;
        BEGIN
          UPDATE cola.tareas t SET estado = 'COMPLETADA', ficha = NULL, bloqueada_hasta = NULL,
                 terminada_en = now(), ultimo_error = NULL
          WHERE t.id = p_id AND t.ficha = p_ficha AND t.estado = 'EN_CURSO'
            AND t.tenant_id = lab.tenant_actual()
          RETURNING true INTO v_ok;
          RETURN coalesce(v_ok, false);
        END $$
        """
    )

    # Fallar: reintento con espera, o FALLIDA si se agotaron los intentos (o no se debe reintentar).
    op.execute(
        """
        CREATE FUNCTION cola.fallar(p_id bigint, p_ficha uuid, p_error text, p_espera_segundos integer,
                                    p_reintentar boolean) RETURNS text
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE v_estado text;
        BEGIN
          UPDATE cola.tareas t SET
                 estado = CASE WHEN p_reintentar AND t.intentos < t.max_intentos THEN 'PENDIENTE' ELSE 'FALLIDA' END,
                 disponible_en = now() + make_interval(secs => greatest(p_espera_segundos, 0)),
                 terminada_en = CASE WHEN p_reintentar AND t.intentos < t.max_intentos THEN NULL ELSE now() END,
                 ficha = NULL, bloqueada_hasta = NULL, ultimo_error = left(p_error, 200)
          WHERE t.id = p_id AND t.ficha = p_ficha AND t.estado = 'EN_CURSO'
          RETURNING t.estado INTO v_estado;
          RETURN v_estado;
        END $$
        """
    )
    op.execute("REVOKE ALL ON SCHEMA cola FROM PUBLIC")
    op.execute(f"REVOKE ALL ON cola.tareas FROM PUBLIC, {APP}")
    op.execute(f"GRANT USAGE ON SCHEMA cola TO {APP}")
    for firma in (
        "cola.encolar(text, jsonb, text, integer, integer)",
        "cola.tomar(integer)",
        "cola.completar(bigint, uuid)",
        "cola.fallar(bigint, uuid, text, integer, boolean)",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {firma} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {firma} TO {APP}")


def downgrade() -> None:
    op.execute("DROP SCHEMA cola CASCADE")
    for tabla in AUDITADAS:
        op.execute(f"DROP TRIGGER auditoria ON lab.{tabla}")
    op.execute("DROP FUNCTION lab.registrar_acceso(text, text, bigint, text, jsonb)")
    op.execute("DROP FUNCTION lab.auditar()")
    op.execute("DROP TABLE lab.auditoria")  # con sus particiones
    op.execute("DROP FUNCTION lab.crear_particion_auditoria(date)")
    op.execute("DROP FUNCTION lab.rechazar_vaciado()")
