"""Admin Hub: usuarios de la plataforma, planes, alta de laboratorios e invitaciones (etapa 4).

Specs funcional/0005, infraestructura/0005, 0007 y 0008.

- plataforma: mismas tablas de autenticación que lab (sin tenant_id), con su propia auditoría.
  El código de autenticación es el mismo para los dos sitios: cada transacción fija su
  search_path (lab o plataforma) y los nombres de tabla no llevan esquema. Como cada rol de base
  de datos solo puede usar su esquema, un search_path equivocado falla; nunca mezcla datos.
- ambito_actual(): en lab, el laboratorio de la transacción; en plataforma, 'plataforma'.
  Liga los secretos cifrados (TOTP) al ámbito y al usuario.
- lab: tenant_id con valor por defecto lab.tenant_actual() (las inserciones no lo repiten; el
  WITH CHECK de RLS sigue aplicando). Contraseña opcional: los usuarios invitados la crean con un
  enlace de un solo uso (lab.invitaciones). Sedes.
- Planes con módulos; los módulos siempre activos (usuarios, configuración) no dependen del plan.
- plataforma.alta_laboratorio: única escritura de la plataforma en lab, en una sola transacción.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP = "lablinea_app"
PLATAFORMA = "lablinea_plataforma"

TABLAS_LAB_CON_TENANT = (
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

MODULOS_PLATAFORMA = (
    ("laboratorios", "Laboratorios"),
    ("planes", "Planes"),
    ("suscripciones", "Suscripciones"),
    ("facturacion", "Facturación de la plataforma"),
    ("usuarios", "Usuarios de la plataforma"),
    ("soporte", "Soporte a laboratorios"),
)

TABLAS_PLATAFORMA_AUTH = (
    "eventos_seguridad",
    "limites",
    "codigos_verificacion",
    "sesiones",
    "rol_acciones",
    "rol_permisos",
    "usuario_roles",
    "roles",
    "usuarios",
)

# Tablas de la plataforma auditadas y sus columnas secretas (ver lab.auditar en 0004).
AUDITADAS_PLATAFORMA = {
    "usuarios": ("password_hash", "totp_secreto_cifrado", "-totp_ultimo_contador"),
    "roles": (),
    "usuario_roles": (),
    "rol_permisos": (),
    "rol_acciones": (),
    "planes": (),
    "plan_modulos": (),
    "laboratorios": (),
}


def _lista(argumentos: tuple[str, ...]) -> str:
    return ", ".join(f"'{a}'" for a in argumentos)


def upgrade() -> None:
    # ============================================================== ámbito
    op.execute(
        "CREATE FUNCTION lab.ambito_actual() RETURNS text LANGUAGE sql STABLE AS $$ SELECT lab.tenant_actual() $$"
    )
    op.execute(
        "CREATE FUNCTION plataforma.ambito_actual() RETURNS text LANGUAGE sql IMMUTABLE AS $$ SELECT 'plataforma' $$"
    )
    op.execute(f"GRANT EXECUTE ON FUNCTION lab.ambito_actual() TO {APP}")
    op.execute(f"GRANT EXECUTE ON FUNCTION plataforma.ambito_actual() TO {PLATAFORMA}")

    # ================================================================= lab
    for tabla in TABLAS_LAB_CON_TENANT:
        op.execute(f"ALTER TABLE lab.{tabla} ALTER COLUMN tenant_id SET DEFAULT lab.tenant_actual()")
    op.execute("ALTER TABLE lab.usuarios ALTER COLUMN password_hash DROP NOT NULL")

    op.execute(
        """
        CREATE TABLE lab.sedes (
            id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            uuid      UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
            tenant_id TEXT NOT NULL DEFAULT lab.tenant_actual(),
            nombre    TEXT NOT NULL CHECK (length(nombre) BETWEEN 2 AND 120),
            ciudad    TEXT NOT NULL CHECK (length(ciudad) BETWEEN 2 AND 80),
            activa    BOOLEAN NOT NULL DEFAULT true,
            creada_en TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, nombre),
            UNIQUE (tenant_id, id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE lab.invitaciones (
            id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            tenant_id  TEXT NOT NULL DEFAULT lab.tenant_actual(),
            usuario_id BIGINT NOT NULL,
            token_hash BYTEA NOT NULL UNIQUE CHECK (length(token_hash) = 32),
            creada_en  TIMESTAMPTZ NOT NULL DEFAULT now(),
            expira_en  TIMESTAMPTZ NOT NULL,
            usada_en   TIMESTAMPTZ,
            FOREIGN KEY (tenant_id, usuario_id) REFERENCES lab.usuarios (tenant_id, id)
        )
        """
    )
    for tabla in ("sedes", "invitaciones"):
        op.execute(f"ALTER TABLE lab.{tabla} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE lab.{tabla} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY aislamiento_tenant ON lab.{tabla}"
            " USING (tenant_id = lab.tenant_actual()) WITH CHECK (tenant_id = lab.tenant_actual())"
        )
    op.execute(
        "CREATE TRIGGER auditoria AFTER INSERT OR UPDATE OR DELETE ON lab.sedes"
        " FOR EACH ROW EXECUTE FUNCTION lab.auditar()"
    )
    op.execute(
        "CREATE TRIGGER auditoria AFTER INSERT OR UPDATE OR DELETE ON lab.invitaciones"
        " FOR EACH ROW EXECUTE FUNCTION lab.auditar('token_hash')"
    )

    # ============================================================== global
    op.execute('ALTER TABLE "global".modulos ADD COLUMN siempre_activo BOOLEAN NOT NULL DEFAULT false')
    op.execute("UPDATE \"global\".modulos SET siempre_activo = true WHERE codigo IN ('usuarios', 'configuracion')")
    op.execute(f'GRANT SELECT ON "global".modulos, "global".acciones TO {PLATAFORMA}')

    # ========================================================== plataforma
    op.execute("CREATE TABLE plataforma.modulos (codigo TEXT PRIMARY KEY, nombre TEXT NOT NULL)")
    op.execute("CREATE TABLE plataforma.acciones (codigo TEXT PRIMARY KEY, nombre TEXT NOT NULL)")
    op.execute(
        "INSERT INTO plataforma.modulos (codigo, nombre) VALUES "  # noqa: S608
        + ", ".join(f"('{c}', '{n}')" for c, n in MODULOS_PLATAFORMA)
    )

    op.execute(
        """
        CREATE TABLE plataforma.usuarios (
            id                   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            uuid                 UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
            email                CITEXT NOT NULL UNIQUE CHECK (email ~ '^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$'),
            nombre               TEXT NOT NULL CHECK (length(nombre) BETWEEN 2 AND 120),
            tipo                 TEXT NOT NULL DEFAULT 'PERSONAL' CHECK (tipo = 'PERSONAL'),
            password_hash        TEXT CHECK (password_hash LIKE '$argon2id$%'),
            totp_secreto_cifrado BYTEA,
            totp_confirmado      BOOLEAN NOT NULL DEFAULT false,
            totp_ultimo_contador BIGINT,
            tarjeta_profesional  TEXT CHECK (tarjeta_profesional IS NULL),
            estado               TEXT NOT NULL DEFAULT 'ACTIVO' CHECK (estado IN ('ACTIVO', 'INACTIVO')),
            bloqueado_hasta      TIMESTAMPTZ,
            creado_en            TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE plataforma.roles (
            id      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            codigo  TEXT NOT NULL UNIQUE CHECK (codigo ~ '^[A-Z][A-Z0-9_]{1,39}$'),
            nombre  TEXT NOT NULL,
            sistema BOOLEAN NOT NULL DEFAULT false
        )
        """
    )
    op.execute(
        """
        CREATE TABLE plataforma.usuario_roles (
            usuario_id BIGINT NOT NULL REFERENCES plataforma.usuarios (id),
            rol_id     BIGINT NOT NULL REFERENCES plataforma.roles (id),
            PRIMARY KEY (usuario_id, rol_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE plataforma.rol_permisos (
            rol_id    BIGINT NOT NULL REFERENCES plataforma.roles (id),
            modulo    TEXT NOT NULL REFERENCES plataforma.modulos (codigo),
            consultar BOOLEAN NOT NULL DEFAULT false,
            crear     BOOLEAN NOT NULL DEFAULT false,
            modificar BOOLEAN NOT NULL DEFAULT false,
            eliminar  BOOLEAN NOT NULL DEFAULT false,
            PRIMARY KEY (rol_id, modulo)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE plataforma.rol_acciones (
            rol_id BIGINT NOT NULL REFERENCES plataforma.roles (id),
            accion TEXT NOT NULL REFERENCES plataforma.acciones (codigo),
            PRIMARY KEY (rol_id, accion)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE plataforma.sesiones (
            id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            usuario_id        BIGINT NOT NULL REFERENCES plataforma.usuarios (id),
            token_hash        BYTEA NOT NULL UNIQUE CHECK (length(token_hash) = 32),
            segundo_factor_ok BOOLEAN NOT NULL DEFAULT false,
            creada_en         TIMESTAMPTZ NOT NULL DEFAULT now(),
            ultima_actividad  TIMESTAMPTZ NOT NULL DEFAULT now(),
            expira_en         TIMESTAMPTZ NOT NULL,
            revocada_en       TIMESTAMPTZ,
            ip                INET,
            agente            TEXT
        )
        """
    )
    op.execute(
        """
        CREATE TABLE plataforma.codigos_verificacion (
            id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            usuario_id  BIGINT NOT NULL REFERENCES plataforma.usuarios (id),
            codigo_hmac BYTEA NOT NULL,
            creado_en   TIMESTAMPTZ NOT NULL DEFAULT now(),
            expira_en   TIMESTAMPTZ NOT NULL,
            usado_en    TIMESTAMPTZ,
            intentos    SMALLINT NOT NULL DEFAULT 0
        )
        """
    )
    # Mismo nombre de restricción que lab.limites: el upsert usa ON CONFLICT ON CONSTRAINT limites_pkey.
    op.execute(
        """
        CREATE TABLE plataforma.limites (
            clave         TEXT NOT NULL,
            ventana_desde TIMESTAMPTZ NOT NULL,
            contador      INTEGER NOT NULL DEFAULT 0,
            CONSTRAINT limites_pkey PRIMARY KEY (clave)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE plataforma.eventos_seguridad (
            id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            tipo        TEXT NOT NULL,
            usuario_id  BIGINT,
            email       CITEXT,
            ip          INET,
            ocurrido_en TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    # Planes y módulos por plan. Los laboratorios existentes quedan en el plan completo.
    op.execute(
        """
        CREATE TABLE plataforma.planes (
            id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            uuid         UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
            codigo       TEXT NOT NULL UNIQUE CHECK (codigo ~ '^[A-Z][A-Z0-9_]{1,39}$'),
            nombre       TEXT NOT NULL CHECK (length(nombre) BETWEEN 2 AND 120),
            max_usuarios INTEGER CHECK (max_usuarios > 0),
            activo       BOOLEAN NOT NULL DEFAULT true,
            creado_en    TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE plataforma.plan_modulos (
            plan_id BIGINT NOT NULL REFERENCES plataforma.planes (id),
            modulo  TEXT NOT NULL REFERENCES "global".modulos (codigo),
            PRIMARY KEY (plan_id, modulo)
        )
        """
    )
    op.execute("INSERT INTO plataforma.planes (codigo, nombre) VALUES ('COMPLETO', 'Completo')")
    op.execute(
        "INSERT INTO plataforma.plan_modulos (plan_id, modulo)"
        " SELECT p.id, m.codigo FROM plataforma.planes p, \"global\".modulos m"
        " WHERE p.codigo = 'COMPLETO' AND NOT m.siempre_activo"
    )
    op.execute("ALTER TABLE plataforma.laboratorios ADD COLUMN plan_id BIGINT REFERENCES plataforma.planes (id)")
    op.execute("UPDATE plataforma.laboratorios SET plan_id = (SELECT id FROM plataforma.planes WHERE codigo = 'COMPLETO')")
    op.execute("ALTER TABLE plataforma.laboratorios ALTER COLUMN plan_id SET NOT NULL")

    # Auditoría de la plataforma: solo inserción, escriben los triggers y registrar_acceso.
    op.execute(
        """
        CREATE TABLE plataforma.auditoria (
            id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            tabla       TEXT NOT NULL CHECK (length(tabla) BETWEEN 1 AND 80),
            operacion   TEXT NOT NULL CHECK (operacion IN ('INSERT', 'UPDATE', 'DELETE', 'READ', 'EXPORT', 'ACCESO')),
            registro_id BIGINT,
            usuario_id  TEXT,
            ip          INET,
            resultado   TEXT NOT NULL DEFAULT 'EXITO' CHECK (resultado IN ('EXITO', 'DENEGADO')),
            antes       JSONB,
            despues     JSONB,
            ocurrido_en TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ON plataforma.auditoria (ocurrido_en)")
    op.execute(
        """
        CREATE FUNCTION plataforma.auditar() RETURNS trigger
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
          IF TG_OP = 'UPDATE' AND v_antes = v_despues THEN
            RETURN NULL;
          END IF;
          INSERT INTO plataforma.auditoria (tabla, operacion, registro_id, usuario_id, ip, antes, despues)
          VALUES (
            TG_TABLE_NAME, TG_OP,
            CASE WHEN jsonb_typeof(v_fila -> 'id') = 'number' THEN (v_fila ->> 'id')::bigint END,
            NULLIF(current_setting('app.current_user_id', true), ''),
            NULLIF(current_setting('app.client_ip', true), '')::inet,
            v_antes, v_despues);
          RETURN NULL;
        END $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION plataforma.auditar() FROM PUBLIC")
    for tabla, argumentos in AUDITADAS_PLATAFORMA.items():
        op.execute(
            f"CREATE TRIGGER auditoria AFTER INSERT OR UPDATE OR DELETE ON plataforma.{tabla}"
            f" FOR EACH ROW EXECUTE FUNCTION plataforma.auditar({_lista(argumentos)})"
        )
    op.execute(
        """
        CREATE FUNCTION plataforma.registrar_acceso(p_tabla text, p_operacion text, p_registro_id bigint,
                                                    p_resultado text, p_detalle jsonb) RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
        BEGIN
          IF p_operacion NOT IN ('READ', 'EXPORT', 'ACCESO') THEN
            RAISE EXCEPTION 'Operación no permitida: %', p_operacion;
          END IF;
          INSERT INTO plataforma.auditoria (tabla, operacion, registro_id, usuario_id, ip, resultado, despues)
          VALUES (p_tabla, p_operacion, p_registro_id,
                  NULLIF(current_setting('app.current_user_id', true), ''),
                  NULLIF(current_setting('app.client_ip', true), '')::inet,
                  p_resultado, p_detalle);
        END $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION plataforma.registrar_acceso(text, text, bigint, text, jsonb) FROM PUBLIC")
    op.execute(
        f"GRANT EXECUTE ON FUNCTION plataforma.registrar_acceso(text, text, bigint, text, jsonb) TO {PLATAFORMA}"
    )
    # Propia del esquema: el rol de la plataforma no tiene acceso a las funciones de lab.
    op.execute(
        """
        CREATE FUNCTION plataforma.rechazar_modificacion() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'La tabla % es de solo inserción', TG_TABLE_NAME;
        END $$
        """
    )
    for tabla in ("auditoria", "eventos_seguridad"):
        op.execute(
            f"CREATE TRIGGER {tabla}_inmutable BEFORE UPDATE OR DELETE ON plataforma.{tabla}"
            " FOR EACH ROW EXECUTE FUNCTION plataforma.rechazar_modificacion()"
        )
        op.execute(
            f"CREATE TRIGGER {tabla}_sin_vaciado BEFORE TRUNCATE ON plataforma.{tabla}"
            " FOR EACH STATEMENT EXECUTE FUNCTION plataforma.rechazar_modificacion()"
        )

    # Privilegios del Admin Hub: los por defecto (SELECT, INSERT, UPDATE) más los borrados necesarios.
    op.execute(f"REVOKE ALL ON plataforma.auditoria FROM {PLATAFORMA}")
    op.execute(f"GRANT SELECT ON plataforma.auditoria TO {PLATAFORMA}")
    op.execute(f"REVOKE UPDATE ON plataforma.eventos_seguridad, plataforma.modulos, plataforma.acciones FROM {PLATAFORMA}")
    op.execute(f"REVOKE INSERT ON plataforma.modulos, plataforma.acciones FROM {PLATAFORMA}")
    op.execute(
        f"GRANT DELETE ON plataforma.usuario_roles, plataforma.rol_permisos, plataforma.rol_acciones,"
        f" plataforma.plan_modulos TO {PLATAFORMA}"
    )

    # ===================================================== acceso del laboratorio
    # El resolvedor ahora entrega los módulos efectivos (plan + siempre activos) y el límite de usuarios.
    op.execute("DROP FUNCTION acceso.resolver_laboratorio(text)")
    op.execute(
        """
        CREATE FUNCTION acceso.resolver_laboratorio(p_subdominio text)
        RETURNS TABLE (tenant_id text, nombre_comercial text, pais char(3), estado text,
                       zona_horaria text, idioma text, moneda char(3), subdominio text,
                       modulos text[], max_usuarios integer)
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
          SELECT l.tenant_id, l.nombre_comercial, l.pais, l.estado,
                 p.zona_horaria, p.idioma, p.moneda, l.subdominio,
                 ARRAY(SELECT pm.modulo FROM plataforma.plan_modulos pm WHERE pm.plan_id = l.plan_id
                       UNION SELECT m.codigo FROM "global".modulos m WHERE m.siempre_activo
                       ORDER BY 1),
                 pl.max_usuarios
          FROM plataforma.laboratorios l
          JOIN "global".paises p ON p.codigo = l.pais
          JOIN plataforma.planes pl ON pl.id = l.plan_id
          WHERE l.subdominio = lower(p_subdominio)
            AND l.estado <> 'CANCELADO'
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION acceso.resolver_laboratorio(text) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION acceso.resolver_laboratorio(text) TO {APP}")

    # ================================================== alta e invitaciones
    # Invitación al administrador pendiente (sin contraseña) de un laboratorio: encola el correo.
    op.execute(
        """
        CREATE FUNCTION plataforma.invitar_administrador(p_laboratorio uuid) RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE
          v_tenant text; v_subdominio text; v_usuario uuid;
        BEGIN
          SELECT tenant_id, subdominio INTO v_tenant, v_subdominio
          FROM plataforma.laboratorios WHERE uuid = p_laboratorio AND estado <> 'CANCELADO';
          IF v_tenant IS NULL THEN
            RAISE EXCEPTION 'Laboratorio no encontrado';
          END IF;
          PERFORM set_config('app.current_tenant', v_tenant, true);
          SELECT u.uuid INTO v_usuario FROM lab.usuarios u
          JOIN lab.usuario_roles ur ON ur.usuario_id = u.id
          JOIN lab.roles r ON r.id = ur.rol_id
          WHERE r.codigo = 'ADMINISTRADOR' AND u.password_hash IS NULL AND u.estado = 'ACTIVO'
          ORDER BY u.id LIMIT 1;
          IF v_usuario IS NULL THEN
            RAISE EXCEPTION 'El laboratorio no tiene un administrador pendiente de activar';
          END IF;
          PERFORM cola.encolar('auth.invitacion',
                               jsonb_build_object('usuario', v_usuario::text, 'subdominio', v_subdominio),
                               NULL, 0, 5);
          PERFORM set_config('app.current_tenant', '', true);
        END $$
        """
    )
    # Alta completa en una transacción: si algo falla, no queda nada creado.
    op.execute(
        """
        CREATE FUNCTION plataforma.alta_laboratorio(
            p_tenant text, p_subdominio text, p_nombre text, p_identificador_fiscal text, p_pais char(3),
            p_plan uuid, p_sede text, p_ciudad text, p_admin_email text, p_admin_nombre text, p_roles jsonb
        ) RETURNS uuid
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE
          v_laboratorio uuid; v_plan bigint; v_rol record; v_rol_id bigint; v_admin_rol bigint; v_usuario bigint;
        BEGIN
          SELECT id INTO v_plan FROM plataforma.planes WHERE uuid = p_plan AND activo;
          IF v_plan IS NULL THEN
            RAISE EXCEPTION 'Plan no disponible';
          END IF;
          INSERT INTO plataforma.laboratorios (tenant_id, subdominio, nombre_comercial, identificador_fiscal, pais, plan_id)
          VALUES (p_tenant, p_subdominio, p_nombre, p_identificador_fiscal, p_pais, v_plan)
          RETURNING uuid INTO v_laboratorio;

          PERFORM set_config('app.current_tenant', p_tenant, true);
          INSERT INTO lab.sedes (tenant_id, nombre, ciudad) VALUES (p_tenant, p_sede, p_ciudad);
          FOR v_rol IN SELECT * FROM jsonb_to_recordset(p_roles) AS r(codigo text, nombre text, modulos jsonb, acciones jsonb)
          LOOP
            INSERT INTO lab.roles (tenant_id, codigo, nombre, sistema) VALUES (p_tenant, v_rol.codigo, v_rol.nombre, true)
            RETURNING id INTO v_rol_id;
            INSERT INTO lab.rol_permisos (tenant_id, rol_id, modulo, consultar, crear, modificar, eliminar)
            SELECT p_tenant, v_rol_id, m.key, m.value ? 'consultar', m.value ? 'crear', m.value ? 'modificar',
                   m.value ? 'eliminar'
            FROM jsonb_each(v_rol.modulos) m;
            INSERT INTO lab.rol_acciones (tenant_id, rol_id, accion)
            SELECT p_tenant, v_rol_id, a FROM jsonb_array_elements_text(v_rol.acciones) a;
            IF v_rol.codigo = 'ADMINISTRADOR' THEN
              v_admin_rol := v_rol_id;
            END IF;
          END LOOP;
          IF v_admin_rol IS NULL THEN
            RAISE EXCEPTION 'Falta el rol ADMINISTRADOR';
          END IF;
          INSERT INTO lab.usuarios (tenant_id, email, nombre, tipo) VALUES (p_tenant, p_admin_email, p_admin_nombre, 'PERSONAL')
          RETURNING id INTO v_usuario;
          INSERT INTO lab.usuario_roles (tenant_id, usuario_id, rol_id) VALUES (p_tenant, v_usuario, v_admin_rol);
          PERFORM set_config('app.current_tenant', '', true);

          PERFORM plataforma.invitar_administrador(v_laboratorio);
          RETURN v_laboratorio;
        END $$
        """
    )
    for firma in (
        "plataforma.alta_laboratorio(text, text, text, text, char, uuid, text, text, text, text, jsonb)",
        "plataforma.invitar_administrador(uuid)",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {firma} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {firma} TO {PLATAFORMA}")


def downgrade() -> None:
    op.execute("DROP FUNCTION plataforma.alta_laboratorio(text, text, text, text, char, uuid, text, text, text, text, jsonb)")
    op.execute("DROP FUNCTION plataforma.invitar_administrador(uuid)")
    op.execute("DROP FUNCTION acceso.resolver_laboratorio(text)")
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
    op.execute(f"GRANT EXECUTE ON FUNCTION acceso.resolver_laboratorio(text) TO {APP}")

    op.execute("DROP TRIGGER auditoria ON plataforma.laboratorios")
    op.execute("DROP TABLE plataforma.auditoria")
    op.execute("DROP FUNCTION plataforma.registrar_acceso(text, text, bigint, text, jsonb)")
    op.execute("ALTER TABLE plataforma.laboratorios DROP COLUMN plan_id")
    op.execute("DROP TABLE plataforma.plan_modulos")
    op.execute("DROP TABLE plataforma.planes")
    for tabla in TABLAS_PLATAFORMA_AUTH:
        op.execute(f"DROP TABLE plataforma.{tabla}")
    op.execute("DROP FUNCTION plataforma.auditar()")
    op.execute("DROP FUNCTION plataforma.rechazar_modificacion()")
    op.execute("DROP TABLE plataforma.acciones")
    op.execute("DROP TABLE plataforma.modulos")
    op.execute('ALTER TABLE "global".modulos DROP COLUMN siempre_activo')

    op.execute("DROP TABLE lab.invitaciones")
    op.execute("DROP TABLE lab.sedes")
    # Usuarios invitados sin contraseña: un hash que no corresponde a ninguna clave (no pueden ingresar,
    # igual que antes de activar). Sin tenant fijado el RLS forzado ocultaría las filas.
    op.execute(
        """
        DO $$
        DECLARE v_tenant text;
        BEGIN
          FOR v_tenant IN SELECT tenant_id FROM plataforma.laboratorios LOOP
            PERFORM set_config('app.current_tenant', v_tenant, true);
            UPDATE lab.usuarios SET password_hash = '$argon2id$sin-contrasena' WHERE password_hash IS NULL;
          END LOOP;
          PERFORM set_config('app.current_tenant', '', true);
        END $$
        """
    )
    op.execute("ALTER TABLE lab.usuarios ALTER COLUMN password_hash SET NOT NULL")
    for tabla in TABLAS_LAB_CON_TENANT:
        op.execute(f"ALTER TABLE lab.{tabla} ALTER COLUMN tenant_id DROP DEFAULT")
    op.execute("DROP FUNCTION plataforma.ambito_actual()")
    op.execute("DROP FUNCTION lab.ambito_actual()")
