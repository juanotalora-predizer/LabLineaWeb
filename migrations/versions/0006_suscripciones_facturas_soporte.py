"""Suscripciones, facturación de la plataforma y acceso de soporte (etapa 5).

Spec funcional/0005 (secciones 3 y 4) e infraestructura/0005 (soporte autorizado).

- plataforma.tipos_licencia: DEMO, AD_HONOREM, GRATUITO_BASICO, MENSUAL, ANUAL, con duración y límite de usuarios.
- plataforma.suscripciones: una por laboratorio. El estado efectivo lo calcula el resolvedor (una ACTIVA con
  fin pasado ya está VENCIDA aunque el trabajador no la haya marcado).
- plataforma.precios y plataforma.campanas: precio por país, plan, licencia y moneda; descuentos con vigencia.
- plataforma.facturas y plataforma.pagos: el saldo y el estado los recalcula un trigger con cada pago. La
  plataforma no puede actualizar ni borrar facturas o pagos: solo crearlos y anularlos con funciones que
  validan las reglas. Un pago no puede superar el saldo. Al quedar pagada, la suscripción se extiende.
- lab.accesos_soporte y lab.tickets_soporte: el laboratorio autoriza el soporte (máximo 72 horas); la
  plataforma emite un tiquete de un solo uso que abre una sesión de solo lectura en el laboratorio.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP = "lablinea_app"
PLATAFORMA = "lablinea_plataforma"

ALTA_ANTERIOR = "plataforma.alta_laboratorio(text, text, text, text, char, uuid, text, text, text, text, jsonb)"
ALTA_NUEVA = "plataforma.alta_laboratorio(text, text, text, text, char, uuid, text, text, text, text, jsonb, text)"

AUDITADAS = ("suscripciones", "precios", "campanas", "facturas", "pagos")

# Cuerpo común del alta (0005) con la suscripción inicial. %s: firma y bloque de suscripción.
ALTA = """
CREATE FUNCTION plataforma.alta_laboratorio(
    p_tenant text, p_subdominio text, p_nombre text, p_identificador_fiscal text, p_pais char(3),
    p_plan uuid, p_sede text, p_ciudad text, p_admin_email text, p_admin_nombre text, p_roles jsonb{parametro}
) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
  v_laboratorio uuid; v_laboratorio_id bigint; v_plan bigint; v_rol record; v_rol_id bigint;
  v_admin_rol bigint; v_usuario bigint;{declaraciones}
BEGIN
  SELECT id INTO v_plan FROM plataforma.planes WHERE uuid = p_plan AND activo;
  IF v_plan IS NULL THEN
    RAISE EXCEPTION 'Plan no disponible';
  END IF;
  INSERT INTO plataforma.laboratorios (tenant_id, subdominio, nombre_comercial, identificador_fiscal, pais, plan_id)
  VALUES (p_tenant, p_subdominio, p_nombre, p_identificador_fiscal, p_pais, v_plan)
  RETURNING id, uuid INTO v_laboratorio_id, v_laboratorio;
{suscripcion}
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

SUSCRIPCION_INICIAL = """
  -- Licencia facturable: 7 días para pagar la primera factura. Las demás: su duración (o indefinida).
  SELECT duracion, facturable INTO v_duracion, v_facturable FROM plataforma.tipos_licencia WHERE codigo = p_tipo_licencia;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Tipo de licencia no válido';
  END IF;
  INSERT INTO plataforma.suscripciones (laboratorio_id, tipo_licencia, fin)
  VALUES (v_laboratorio_id, p_tipo_licencia,
          CASE WHEN v_facturable THEN now() + interval '7 days'
               WHEN v_duracion IS NULL THEN NULL ELSE now() + v_duracion END);
"""

RESOLVEDOR = """
CREATE FUNCTION acceso.resolver_laboratorio(p_subdominio text)
RETURNS TABLE (tenant_id text, nombre_comercial text, pais char(3), estado text,
               zona_horaria text, idioma text, moneda char(3), subdominio text,
               modulos text[], max_usuarios integer{columnas})
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
  SELECT l.tenant_id, l.nombre_comercial, l.pais, l.estado,
         p.zona_horaria, p.idioma, p.moneda, l.subdominio,
         ARRAY(SELECT pm.modulo FROM plataforma.plan_modulos pm WHERE pm.plan_id = l.plan_id
               UNION SELECT m.codigo FROM "global".modulos m WHERE m.siempre_activo
               ORDER BY 1),
         {max_usuarios}{valores}
  FROM plataforma.laboratorios l
  JOIN "global".paises p ON p.codigo = l.pais
  JOIN plataforma.planes pl ON pl.id = l.plan_id
  {uniones}
  WHERE l.subdominio = lower(p_subdominio)
    AND l.estado <> 'CANCELADO'
$$
"""


def _resolvedor(con_suscripcion: bool) -> str:
    if not con_suscripcion:
        return RESOLVEDOR.format(columnas="", max_usuarios="pl.max_usuarios", valores="", uniones="")
    return RESOLVEDOR.format(
        columnas=", suscripcion_estado text, suscripcion_fin timestamptz",
        # LEAST ignora los nulos: el menor límite entre el plan y la licencia.
        max_usuarios="LEAST(pl.max_usuarios, tl.max_usuarios)",
        valores=""",
         CASE WHEN s.id IS NULL THEN 'SIN_SUSCRIPCION'
              WHEN s.estado = 'ACTIVA' AND s.fin IS NOT NULL AND s.fin <= now() THEN 'VENCIDA'
              ELSE s.estado END,
         s.fin""",
        uniones="LEFT JOIN plataforma.suscripciones s ON s.laboratorio_id = l.id\n"
        "  LEFT JOIN plataforma.tipos_licencia tl ON tl.codigo = s.tipo_licencia",
    )


def upgrade() -> None:
    # ============================================================ global
    op.execute(
        'ALTER TABLE "global".paises ADD COLUMN impuesto_servicios NUMERIC(5,2) NOT NULL DEFAULT 0'
        " CHECK (impuesto_servicios >= 0 AND impuesto_servicios < 100)"
    )
    # IVA general de Colombia sobre servicios. Por validar con el asesor tributario (backlog).
    op.execute("UPDATE \"global\".paises SET impuesto_servicios = 19 WHERE codigo = 'COL'")

    # ======================================================== licencias
    op.execute(
        """
        CREATE TABLE plataforma.tipos_licencia (
            codigo       TEXT PRIMARY KEY CHECK (codigo IN ('DEMO', 'AD_HONOREM', 'GRATUITO_BASICO', 'MENSUAL', 'ANUAL')),
            nombre       TEXT NOT NULL,
            duracion     INTERVAL,              -- NULL: indefinida
            facturable   BOOLEAN NOT NULL,
            max_usuarios INTEGER CHECK (max_usuarios > 0)
        )
        """
    )
    op.execute(
        """
        INSERT INTO plataforma.tipos_licencia (codigo, nombre, duracion, facturable, max_usuarios) VALUES
            ('DEMO', 'Demostración', interval '30 days', false, 3),
            ('AD_HONOREM', 'Ad honorem', NULL, false, NULL),
            ('GRATUITO_BASICO', 'Gratuito básico', NULL, false, 2),
            ('MENSUAL', 'Mensual', interval '1 month', true, NULL),
            ('ANUAL', 'Anual', interval '1 year', true, NULL)
        """
    )
    op.execute(
        """
        CREATE TABLE plataforma.suscripciones (
            id                    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            uuid                  UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
            laboratorio_id        BIGINT NOT NULL UNIQUE REFERENCES plataforma.laboratorios (id),
            tipo_licencia         TEXT NOT NULL REFERENCES plataforma.tipos_licencia (codigo),
            estado                TEXT NOT NULL DEFAULT 'ACTIVA'
                                  CHECK (estado IN ('ACTIVA', 'SUSPENDIDA', 'VENCIDA', 'CANCELADA')),
            inicio                TIMESTAMPTZ NOT NULL DEFAULT now(),
            fin                   TIMESTAMPTZ CHECK (fin IS NULL OR fin > inicio),
            renovacion_automatica BOOLEAN NOT NULL DEFAULT false,
            motivo_suspension     TEXT CHECK (length(motivo_suspension) BETWEEN 5 AND 300),
            actualizada_en        TIMESTAMPTZ NOT NULL DEFAULT now(),
            CHECK ((estado = 'SUSPENDIDA') = (motivo_suspension IS NOT NULL))
        )
        """
    )
    # Laboratorios existentes: ad honorem, indefinida.
    op.execute(
        "INSERT INTO plataforma.suscripciones (laboratorio_id, tipo_licencia)"
        " SELECT id, 'AD_HONOREM' FROM plataforma.laboratorios"
    )

    # ========================================================== precios
    op.execute(
        """
        CREATE TABLE plataforma.precios (
            id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            uuid          UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
            pais          CHAR(3) NOT NULL REFERENCES "global".paises (codigo),
            plan_id       BIGINT NOT NULL REFERENCES plataforma.planes (id),
            tipo_licencia TEXT NOT NULL REFERENCES plataforma.tipos_licencia (codigo),
            moneda        CHAR(3) NOT NULL REFERENCES "global".monedas (codigo),
            valor         NUMERIC(14,2) NOT NULL CHECK (valor > 0),
            vigente_desde DATE NOT NULL,
            creado_en     TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (pais, plan_id, tipo_licencia, moneda, vigente_desde)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE plataforma.campanas (
            id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            uuid          UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
            nombre        TEXT NOT NULL CHECK (length(nombre) BETWEEN 2 AND 120),
            porcentaje    NUMERIC(5,2) NOT NULL CHECK (porcentaje > 0 AND porcentaje < 100),
            tipo_licencia TEXT REFERENCES plataforma.tipos_licencia (codigo),  -- NULL: todas
            desde         DATE NOT NULL,
            hasta         DATE NOT NULL CHECK (hasta >= desde),
            activa        BOOLEAN NOT NULL DEFAULT true,
            creada_en     TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    # ========================================================= facturas
    op.execute("CREATE SEQUENCE plataforma.facturas_numero")
    op.execute(
        """
        CREATE TABLE plataforma.facturas (
            id                   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            uuid                 UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
            numero               TEXT NOT NULL UNIQUE
                                 DEFAULT 'PLT-' || lpad(nextval('plataforma.facturas_numero')::text, 6, '0'),
            laboratorio_id       BIGINT NOT NULL REFERENCES plataforma.laboratorios (id),
            suscripcion_id       BIGINT NOT NULL REFERENCES plataforma.suscripciones (id),
            tipo_licencia        TEXT NOT NULL REFERENCES plataforma.tipos_licencia (codigo),
            periodo_desde        TIMESTAMPTZ NOT NULL,
            periodo_hasta        TIMESTAMPTZ NOT NULL CHECK (periodo_hasta > periodo_desde),
            moneda               CHAR(3) NOT NULL REFERENCES "global".monedas (codigo),
            tasa_cambio          NUMERIC(18,6) NOT NULL DEFAULT 1 CHECK (tasa_cambio > 0),
            valor_lista          NUMERIC(14,2) NOT NULL CHECK (valor_lista > 0),
            campana_id           BIGINT REFERENCES plataforma.campanas (id),
            descuento_porcentaje NUMERIC(5,2) NOT NULL DEFAULT 0 CHECK (descuento_porcentaje >= 0 AND descuento_porcentaje < 100),
            descuento            NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (descuento >= 0),
            subtotal             NUMERIC(14,2) NOT NULL,
            impuesto_porcentaje  NUMERIC(5,2) NOT NULL CHECK (impuesto_porcentaje >= 0 AND impuesto_porcentaje < 100),
            impuesto             NUMERIC(14,2) NOT NULL CHECK (impuesto >= 0),
            total                NUMERIC(14,2) NOT NULL CHECK (total > 0),
            saldo                NUMERIC(14,2) NOT NULL CHECK (saldo >= 0 AND saldo <= total),
            estado               TEXT NOT NULL DEFAULT 'PENDIENTE'
                                 CHECK (estado IN ('PENDIENTE', 'PAGADA_PARCIAL', 'PAGADA', 'ANULADA')),
            emitida_en           TIMESTAMPTZ NOT NULL DEFAULT now(),
            vence_en             TIMESTAMPTZ NOT NULL,
            anulada_en           TIMESTAMPTZ,
            motivo_anulacion     TEXT CHECK (length(motivo_anulacion) BETWEEN 5 AND 300),
            CHECK (subtotal = valor_lista - descuento),
            CHECK (total = subtotal + impuesto),
            CHECK ((estado = 'ANULADA') = (anulada_en IS NOT NULL))
        )
        """
    )
    op.execute("CREATE INDEX ON plataforma.facturas (laboratorio_id, estado)")
    op.execute(
        """
        CREATE TABLE plataforma.pagos (
            id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            uuid             UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
            factura_id       BIGINT NOT NULL REFERENCES plataforma.facturas (id),
            valor            NUMERIC(14,2) NOT NULL CHECK (valor > 0),
            recibido_en      DATE NOT NULL,
            medio            TEXT NOT NULL CHECK (medio IN ('TRANSFERENCIA', 'CONSIGNACION', 'EFECTIVO', 'TARJETA', 'OTRO')),
            referencia       TEXT CHECK (length(referencia) <= 100),
            registrado_en    TIMESTAMPTZ NOT NULL DEFAULT now(),
            anulado_en       TIMESTAMPTZ,
            motivo_anulacion TEXT CHECK (length(motivo_anulacion) BETWEEN 5 AND 300),
            CHECK ((anulado_en IS NULL) = (motivo_anulacion IS NULL))
        )
        """
    )
    op.execute("CREATE INDEX ON plataforma.pagos (factura_id)")

    # Factura nueva: siempre pendiente y con saldo igual al total.
    op.execute(
        """
        CREATE FUNCTION plataforma.nueva_factura() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          NEW.saldo := NEW.total;
          NEW.estado := 'PENDIENTE';
          NEW.anulada_en := NULL;
          NEW.motivo_anulacion := NULL;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER factura_nueva BEFORE INSERT ON plataforma.facturas"
        " FOR EACH ROW EXECUTE FUNCTION plataforma.nueva_factura()"
    )
    # Montos, periodo y laboratorio inmutables; una factura anulada no cambia más (incluso para el dueño).
    op.execute(
        """
        CREATE FUNCTION plataforma.proteger_factura() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF OLD.estado = 'ANULADA' THEN
            RAISE EXCEPTION 'La factura % está anulada', OLD.numero;
          END IF;
          IF (NEW.numero, NEW.laboratorio_id, NEW.suscripcion_id, NEW.tipo_licencia, NEW.periodo_desde,
              NEW.periodo_hasta, NEW.moneda, NEW.tasa_cambio, NEW.valor_lista, NEW.descuento, NEW.subtotal,
              NEW.impuesto, NEW.total, NEW.emitida_en)
             IS DISTINCT FROM
             (OLD.numero, OLD.laboratorio_id, OLD.suscripcion_id, OLD.tipo_licencia, OLD.periodo_desde,
              OLD.periodo_hasta, OLD.moneda, OLD.tasa_cambio, OLD.valor_lista, OLD.descuento, OLD.subtotal,
              OLD.impuesto, OLD.total, OLD.emitida_en) THEN
            RAISE EXCEPTION 'Los valores de la factura % no se modifican', OLD.numero;
          END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER factura_protegida BEFORE UPDATE ON plataforma.facturas"
        " FOR EACH ROW EXECUTE FUNCTION plataforma.proteger_factura()"
    )
    op.execute(
        "CREATE TRIGGER facturas_sin_borrado BEFORE DELETE ON plataforma.facturas"
        " FOR EACH ROW EXECUTE FUNCTION plataforma.rechazar_modificacion()"
    )
    # Pago: no supera el saldo, no va a una factura anulada; después solo se puede anular.
    # SECURITY DEFINER: bloquea la factura (FOR UPDATE) sin que la plataforma tenga UPDATE sobre ella.
    op.execute(
        """
        CREATE FUNCTION plataforma.validar_pago() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE v_estado text; v_saldo numeric;
        BEGIN
          IF TG_OP = 'INSERT' THEN
            SELECT estado, saldo INTO v_estado, v_saldo FROM plataforma.facturas WHERE id = NEW.factura_id FOR UPDATE;
            IF v_estado = 'ANULADA' THEN
              RAISE EXCEPTION 'La factura está anulada';
            END IF;
            IF NEW.valor > v_saldo THEN
              RAISE EXCEPTION 'El pago supera el saldo de la factura';
            END IF;
            NEW.anulado_en := NULL;
            NEW.motivo_anulacion := NULL;
            RETURN NEW;
          END IF;
          IF OLD.anulado_en IS NOT NULL THEN
            RAISE EXCEPTION 'El pago ya está anulado';
          END IF;
          IF (NEW.factura_id, NEW.valor, NEW.recibido_en, NEW.medio, NEW.referencia, NEW.registrado_en)
             IS DISTINCT FROM (OLD.factura_id, OLD.valor, OLD.recibido_en, OLD.medio, OLD.referencia, OLD.registrado_en)
             OR NEW.anulado_en IS NULL THEN
            RAISE EXCEPTION 'Un pago registrado solo se puede anular';
          END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER pago_valido BEFORE INSERT OR UPDATE ON plataforma.pagos"
        " FOR EACH ROW EXECUTE FUNCTION plataforma.validar_pago()"
    )
    op.execute(
        "CREATE TRIGGER pagos_sin_borrado BEFORE DELETE ON plataforma.pagos"
        " FOR EACH ROW EXECUTE FUNCTION plataforma.rechazar_modificacion()"
    )
    # Saldo y estado con cada pago o anulación; al quedar pagada, la suscripción se extiende hasta el periodo.
    op.execute(
        """
        CREATE FUNCTION plataforma.recalcular_factura() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE f record; v_pagado numeric; v_estado text;
        BEGIN
          SELECT * INTO f FROM plataforma.facturas WHERE id = NEW.factura_id FOR UPDATE;
          SELECT coalesce(sum(valor), 0) INTO v_pagado FROM plataforma.pagos
          WHERE factura_id = f.id AND anulado_en IS NULL;
          v_estado := CASE WHEN v_pagado = 0 THEN 'PENDIENTE'
                           WHEN v_pagado < f.total THEN 'PAGADA_PARCIAL' ELSE 'PAGADA' END;
          UPDATE plataforma.facturas SET saldo = f.total - v_pagado, estado = v_estado WHERE id = f.id;
          IF v_estado = 'PAGADA' AND f.estado <> 'PAGADA' THEN
            UPDATE plataforma.suscripciones
            SET fin = greatest(coalesce(fin, f.periodo_hasta), f.periodo_hasta),
                estado = 'ACTIVA', motivo_suspension = NULL, tipo_licencia = f.tipo_licencia, actualizada_en = now()
            WHERE id = f.suscripcion_id AND estado <> 'CANCELADA';
          END IF;
          RETURN NULL;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER pago_recalcula AFTER INSERT OR UPDATE ON plataforma.pagos"
        " FOR EACH ROW EXECUTE FUNCTION plataforma.recalcular_factura()"
    )
    op.execute(
        """
        CREATE FUNCTION plataforma.anular_pago(p_pago uuid, p_motivo text) RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
        BEGIN
          UPDATE plataforma.pagos SET anulado_en = now(), motivo_anulacion = p_motivo
          WHERE uuid = p_pago AND anulado_en IS NULL;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'Pago no encontrado o ya anulado';
          END IF;
        END $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION plataforma.anular_factura(p_factura uuid, p_motivo text) RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE v_id bigint;
        BEGIN
          SELECT id INTO v_id FROM plataforma.facturas WHERE uuid = p_factura AND estado <> 'ANULADA' FOR UPDATE;
          IF v_id IS NULL THEN
            RAISE EXCEPTION 'Factura no encontrada o ya anulada';
          END IF;
          IF EXISTS (SELECT 1 FROM plataforma.pagos WHERE factura_id = v_id AND anulado_en IS NULL) THEN
            RAISE EXCEPTION 'La factura tiene pagos: anúlelos primero';
          END IF;
          UPDATE plataforma.facturas SET estado = 'ANULADA', saldo = 0, anulada_en = now(), motivo_anulacion = p_motivo
          WHERE id = v_id;
        END $$
        """
    )

    # ========================================================= soporte
    op.execute("ALTER TABLE lab.usuarios DROP CONSTRAINT usuarios_tipo_check")
    op.execute(
        "ALTER TABLE lab.usuarios ADD CONSTRAINT usuarios_tipo_check"
        " CHECK (tipo IN ('PERSONAL', 'PACIENTE', 'MEDICO', 'SOPORTE'))"
    )
    # Soporte: sin contraseña nunca; ingresa solo con un tiquete de la plataforma.
    op.execute(
        "ALTER TABLE lab.usuarios ADD CONSTRAINT soporte_sin_contrasena"
        " CHECK (tipo <> 'SOPORTE' OR password_hash IS NULL)"
    )
    op.execute(
        """
        CREATE TABLE lab.accesos_soporte (
            id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            uuid           UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
            tenant_id      TEXT NOT NULL DEFAULT lab.tenant_actual(),
            autorizado_por BIGINT NOT NULL,
            motivo         TEXT NOT NULL CHECK (length(motivo) BETWEEN 5 AND 300),
            inicio         TIMESTAMPTZ NOT NULL DEFAULT now(),
            fin            TIMESTAMPTZ NOT NULL,
            revocado_en    TIMESTAMPTZ,
            revocado_por   BIGINT,
            CHECK (fin > inicio AND fin <= inicio + interval '72 hours'),
            UNIQUE (tenant_id, id),
            FOREIGN KEY (tenant_id, autorizado_por) REFERENCES lab.usuarios (tenant_id, id),
            FOREIGN KEY (tenant_id, revocado_por) REFERENCES lab.usuarios (tenant_id, id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE lab.tickets_soporte (
            id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            tenant_id  TEXT NOT NULL DEFAULT lab.tenant_actual(),
            acceso_id  BIGINT NOT NULL,
            usuario_id BIGINT NOT NULL,
            token_hash BYTEA NOT NULL UNIQUE CHECK (length(token_hash) = 32),
            creado_en  TIMESTAMPTZ NOT NULL DEFAULT now(),
            expira_en  TIMESTAMPTZ NOT NULL,
            usado_en   TIMESTAMPTZ,
            FOREIGN KEY (tenant_id, acceso_id) REFERENCES lab.accesos_soporte (tenant_id, id),
            FOREIGN KEY (tenant_id, usuario_id) REFERENCES lab.usuarios (tenant_id, id)
        )
        """
    )
    for tabla, argumentos in (("accesos_soporte", ""), ("tickets_soporte", "'token_hash'")):
        op.execute(f"ALTER TABLE lab.{tabla} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE lab.{tabla} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY aislamiento_tenant ON lab.{tabla}"
            " USING (tenant_id = lab.tenant_actual()) WITH CHECK (tenant_id = lab.tenant_actual())"
        )
        op.execute(
            f"CREATE TRIGGER auditoria AFTER INSERT OR UPDATE OR DELETE ON lab.{tabla}"
            f" FOR EACH ROW EXECUTE FUNCTION lab.auditar({argumentos})"
        )

    # Rol de solo lectura del soporte en cada laboratorio existente (los nuevos lo reciben en el alta).
    op.execute(
        """
        DO $$
        DECLARE v_tenant text; v_rol bigint;
        BEGIN
          FOR v_tenant IN SELECT tenant_id FROM plataforma.laboratorios LOOP
            PERFORM set_config('app.current_tenant', v_tenant, true);
            IF EXISTS (SELECT 1 FROM lab.roles WHERE codigo = 'ADMINISTRADOR') THEN
              INSERT INTO lab.roles (tenant_id, codigo, nombre, sistema)
              VALUES (v_tenant, 'SOPORTE', 'Soporte de la plataforma (solo lectura)', true)
              ON CONFLICT (tenant_id, codigo) DO NOTHING RETURNING id INTO v_rol;
              IF v_rol IS NOT NULL THEN
                INSERT INTO lab.rol_permisos (tenant_id, rol_id, modulo, consultar)
                SELECT v_tenant, v_rol, codigo, true FROM "global".modulos;
              END IF;
            END IF;
          END LOOP;
          PERFORM set_config('app.current_tenant', '', true);
        END $$
        """
    )

    # La plataforma emite el tiquete solo si hay una autorización vigente del laboratorio.
    op.execute(
        """
        CREATE FUNCTION plataforma.iniciar_soporte(p_laboratorio uuid, p_email text, p_nombre text, p_token_hash bytea)
        RETURNS text
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE
          v_tenant text; v_subdominio text; v_acceso bigint; v_usuario bigint; v_tipo text; v_rol bigint;
        BEGIN
          SELECT tenant_id, subdominio INTO v_tenant, v_subdominio
          FROM plataforma.laboratorios WHERE uuid = p_laboratorio AND estado <> 'CANCELADO';
          IF v_tenant IS NULL THEN
            RAISE EXCEPTION 'Laboratorio no encontrado';
          END IF;
          PERFORM set_config('app.current_tenant', v_tenant, true);
          SELECT id INTO v_acceso FROM lab.accesos_soporte
          WHERE revocado_en IS NULL AND inicio <= now() AND fin > now() ORDER BY fin DESC LIMIT 1;
          IF v_acceso IS NULL THEN
            RAISE EXCEPTION 'Sin autorización de soporte vigente';
          END IF;
          SELECT id, tipo INTO v_usuario, v_tipo FROM lab.usuarios WHERE lower(email::text) = lower(p_email);
          IF v_usuario IS NULL THEN
            INSERT INTO lab.usuarios (tenant_id, email, nombre, tipo) VALUES (v_tenant, lower(p_email), p_nombre, 'SOPORTE')
            RETURNING id INTO v_usuario;
          ELSIF v_tipo <> 'SOPORTE' THEN
            RAISE EXCEPTION 'El correo pertenece a un usuario del laboratorio';
          ELSE
            UPDATE lab.usuarios SET estado = 'ACTIVO', nombre = p_nombre WHERE id = v_usuario;
          END IF;
          SELECT id INTO v_rol FROM lab.roles WHERE codigo = 'SOPORTE';
          IF v_rol IS NULL THEN
            RAISE EXCEPTION 'El laboratorio no tiene el rol SOPORTE';
          END IF;
          INSERT INTO lab.usuario_roles (tenant_id, usuario_id, rol_id) VALUES (v_tenant, v_usuario, v_rol)
          ON CONFLICT DO NOTHING;
          INSERT INTO lab.tickets_soporte (tenant_id, acceso_id, usuario_id, token_hash, expira_en)
          VALUES (v_tenant, v_acceso, v_usuario, p_token_hash, now() + interval '2 minutes');
          INSERT INTO lab.eventos_seguridad (tenant_id, tipo, usuario_id) VALUES (v_tenant, 'SOPORTE_TIQUETE', v_usuario);
          PERFORM set_config('app.current_tenant', '', true);
          RETURN v_subdominio;
        END $$
        """
    )
    # Laboratorios con autorización vigente (para el Admin Hub): sin datos del laboratorio más allá del motivo.
    op.execute(
        """
        CREATE FUNCTION plataforma.autorizaciones_soporte()
        RETURNS TABLE (laboratorio uuid, nombre text, fin timestamptz, motivo text)
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
        #variable_conflict use_column
        DECLARE v record;
        BEGIN
          FOR v IN SELECT l.uuid, l.tenant_id, l.nombre_comercial FROM plataforma.laboratorios l
                   WHERE l.estado <> 'CANCELADO' ORDER BY l.nombre_comercial LOOP
            PERFORM set_config('app.current_tenant', v.tenant_id, true);
            RETURN QUERY
              SELECT v.uuid, v.nombre_comercial, a.fin, a.motivo FROM lab.accesos_soporte a
              WHERE a.revocado_en IS NULL AND a.inicio <= now() AND a.fin > now()
              ORDER BY a.fin DESC LIMIT 1;
          END LOOP;
          PERFORM set_config('app.current_tenant', '', true);
        END $$
        """
    )

    # ================================================ ciclo de suscripción
    # Marca vencidas y encola los avisos de renovación (7 días y 1 día antes), una vez por umbral.
    op.execute(
        """
        CREATE FUNCTION plataforma.mantener_suscripciones() RETURNS integer
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE v record; v_avisos integer := 0;
        BEGIN
          UPDATE plataforma.suscripciones SET estado = 'VENCIDA', actualizada_en = now()
          WHERE estado = 'ACTIVA' AND fin IS NOT NULL AND fin <= now();
          FOR v IN
            SELECT l.tenant_id, l.subdominio, s.fin,
                   CASE WHEN s.fin <= now() + interval '1 day' THEN 1 ELSE 7 END AS dias
            FROM plataforma.suscripciones s JOIN plataforma.laboratorios l ON l.id = s.laboratorio_id
            WHERE s.estado = 'ACTIVA' AND s.fin > now() AND s.fin <= now() + interval '7 days'
              AND l.estado <> 'CANCELADO'
          LOOP
            PERFORM set_config('app.current_tenant', v.tenant_id, true);
            PERFORM cola.encolar('suscripcion.aviso',
                                 jsonb_build_object('subdominio', v.subdominio, 'dias', v.dias,
                                                    'fin', to_char(v.fin AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')),
                                 'renovacion:' || to_char(v.fin AT TIME ZONE 'UTC', 'YYYYMMDDHH24MI') || ':' || v.dias,
                                 0, 5);
            v_avisos := v_avisos + 1;
          END LOOP;
          PERFORM set_config('app.current_tenant', '', true);
          RETURN v_avisos;
        END $$
        """
    )

    # ================================================ alta y resolvedor
    op.execute(f"DROP FUNCTION {ALTA_ANTERIOR}")
    op.execute(
        ALTA.format(
            parametro=", p_tipo_licencia text",
            declaraciones=" v_duracion interval; v_facturable boolean;",
            suscripcion=SUSCRIPCION_INICIAL,
        )
    )
    op.execute("DROP FUNCTION acceso.resolver_laboratorio(text)")
    op.execute(_resolvedor(con_suscripcion=True))

    # ========================================================= permisos
    for tabla in AUDITADAS:
        op.execute(
            f"CREATE TRIGGER auditoria AFTER INSERT OR UPDATE OR DELETE ON plataforma.{tabla}"
            f" FOR EACH ROW EXECUTE FUNCTION plataforma.auditar()"
        )
    # Facturas y pagos: la plataforma crea y consulta; cambia solo con las funciones de anulación.
    op.execute(f"REVOKE UPDATE, DELETE ON plataforma.facturas, plataforma.pagos FROM {PLATAFORMA}")
    op.execute(f"REVOKE INSERT, UPDATE, DELETE ON plataforma.tipos_licencia FROM {PLATAFORMA}")
    op.execute(f"GRANT USAGE ON SEQUENCE plataforma.facturas_numero TO {PLATAFORMA}")
    op.execute(f"REVOKE ALL ON FUNCTION acceso.resolver_laboratorio(text) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION acceso.resolver_laboratorio(text) TO {APP}")
    for firma in (
        ALTA_NUEVA,
        "plataforma.anular_pago(uuid, text)",
        "plataforma.anular_factura(uuid, text)",
        "plataforma.iniciar_soporte(uuid, text, text, bytea)",
        "plataforma.autorizaciones_soporte()",
        "plataforma.mantener_suscripciones()",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {firma} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {firma} TO {PLATAFORMA}")
    for funcion in ("recalcular_factura()", "validar_pago()"):
        op.execute(f"REVOKE ALL ON FUNCTION plataforma.{funcion} FROM PUBLIC")


def downgrade() -> None:
    op.execute("DROP FUNCTION acceso.resolver_laboratorio(text)")
    op.execute(_resolvedor(con_suscripcion=False))
    op.execute("REVOKE ALL ON FUNCTION acceso.resolver_laboratorio(text) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION acceso.resolver_laboratorio(text) TO {APP}")
    op.execute(f"DROP FUNCTION {ALTA_NUEVA}")
    op.execute(ALTA.format(parametro="", declaraciones="", suscripcion=""))
    op.execute(f"REVOKE ALL ON FUNCTION {ALTA_ANTERIOR} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {ALTA_ANTERIOR} TO {PLATAFORMA}")

    op.execute("DROP FUNCTION plataforma.mantener_suscripciones()")
    op.execute("DROP FUNCTION plataforma.autorizaciones_soporte()")
    op.execute("DROP FUNCTION plataforma.iniciar_soporte(uuid, text, text, bytea)")
    op.execute("DROP TABLE lab.tickets_soporte")
    op.execute("DROP TABLE lab.accesos_soporte")
    # Usuarios y rol de soporte: se quitan (no pueden existir con el CHECK anterior).
    op.execute(
        """
        DO $$
        DECLARE v_tenant text;
        BEGIN
          FOR v_tenant IN SELECT tenant_id FROM plataforma.laboratorios LOOP
            PERFORM set_config('app.current_tenant', v_tenant, true);
            DELETE FROM lab.sesiones WHERE usuario_id IN (SELECT id FROM lab.usuarios WHERE tipo = 'SOPORTE');
            DELETE FROM lab.usuario_roles WHERE rol_id IN (SELECT id FROM lab.roles WHERE codigo = 'SOPORTE')
               OR usuario_id IN (SELECT id FROM lab.usuarios WHERE tipo = 'SOPORTE');
            DELETE FROM lab.rol_permisos WHERE rol_id IN (SELECT id FROM lab.roles WHERE codigo = 'SOPORTE');
            DELETE FROM lab.rol_acciones WHERE rol_id IN (SELECT id FROM lab.roles WHERE codigo = 'SOPORTE');
            DELETE FROM lab.roles WHERE codigo = 'SOPORTE';
            DELETE FROM lab.invitaciones WHERE usuario_id IN (SELECT id FROM lab.usuarios WHERE tipo = 'SOPORTE');
            DELETE FROM lab.codigos_verificacion WHERE usuario_id IN (SELECT id FROM lab.usuarios WHERE tipo = 'SOPORTE');
            DELETE FROM lab.usuarios WHERE tipo = 'SOPORTE';
          END LOOP;
          PERFORM set_config('app.current_tenant', '', true);
        END $$
        """
    )
    op.execute("ALTER TABLE lab.usuarios DROP CONSTRAINT soporte_sin_contrasena")
    op.execute("ALTER TABLE lab.usuarios DROP CONSTRAINT usuarios_tipo_check")
    op.execute(
        "ALTER TABLE lab.usuarios ADD CONSTRAINT usuarios_tipo_check CHECK (tipo IN ('PERSONAL', 'PACIENTE', 'MEDICO'))"
    )

    op.execute("DROP TABLE plataforma.pagos")
    op.execute("DROP TABLE plataforma.facturas")
    op.execute("DROP SEQUENCE plataforma.facturas_numero")
    op.execute("DROP FUNCTION plataforma.anular_pago(uuid, text)")
    op.execute("DROP FUNCTION plataforma.anular_factura(uuid, text)")
    op.execute("DROP FUNCTION plataforma.recalcular_factura()")
    op.execute("DROP FUNCTION plataforma.validar_pago()")
    op.execute("DROP FUNCTION plataforma.proteger_factura()")
    op.execute("DROP FUNCTION plataforma.nueva_factura()")
    op.execute("DROP TABLE plataforma.campanas")
    op.execute("DROP TABLE plataforma.precios")
    op.execute("DROP TABLE plataforma.suscripciones")
    op.execute("DROP TABLE plataforma.tipos_licencia")
    op.execute('ALTER TABLE "global".paises DROP COLUMN impuesto_servicios')
