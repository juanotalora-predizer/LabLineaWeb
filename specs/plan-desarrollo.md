# Plan de desarrollo de LabLineaWeb

- **Fecha:** 2026-10-12
- **Base:** specs aceptadas en [specs/](README.md). Este plan organiza su construcción; si algo aquí difiere de una spec, prevalece la spec.

LabLineaWeb son dos sistemas en una misma plataforma:

| | **Proyecto 1 — Tenant App** | **Proyecto 2 — Admin Hub** |
|---|---|---|
| Usuarios | Personal del laboratorio, pacientes, médicos | Dueños y operadores del SaaS |
| Acceso | `<laboratorio>.<dominio>` | `admin.<dominio>` |
| Datos | Clínicos y financieros de **un** laboratorio (esquema `lab`, con RLS) | Laboratorios, licencias, facturación del SaaS (esquema `plataforma`); **métricas agregadas, nunca datos clínicos** |
| Specs | [funcional/0002](funcional/0002-pos-ordenes-caja.md), [0003](funcional/0003-muestras-impresion.md), [0004](funcional/0004-resultados-validacion-entrega.md) | [funcional/0005](funcional/0005-plataforma-saas-suscripciones.md) |

---

## 1. Arquitectura y topología

```mermaid
flowchart LR
    subgraph Laboratorio["Sede del laboratorio"]
        PC["Navegador del personal<br/>(POS, toma de muestras, validación)"]
        QZ["QZ Tray"]
        IMP["Impresora térmica ZPL"]
        PC -- "WebSocket localhost" --> QZ --> IMP
    end

    PAC["Paciente / médico<br/>(portal)"]
    ADM["Administradores del SaaS"]

    subgraph Nube["Celda regional Colombia"]
        LB["Balanceador<br/>TLS 1.2+ (1.3 preferido), HSTS"]
        subgraph APP["Aplicación FastAPI (Uvicorn)"]
            HOST{"Ruteo por host"}
            T["Proyecto 1<br/>Tenant App"]
            A["Proyecto 2<br/>Admin Hub"]
            CORE["Núcleo compartido<br/>tenancy · sesiones · RBAC · auditoría · i18n"]
            HOST --> T & A
            T & A --> CORE
        end
        W["Trabajador de tareas<br/>PDF · correos · métricas agregadas"]
        PG[("PostgreSQL 16+<br/>plataforma · global · lab (RLS)")]
        OBJ[("Almacenamiento de objetos<br/>privado, cifrado, por tenant")]
        LB --> HOST
        CORE -- "rol lablinea_app" --> PG
        A -- "rol lablinea_plataforma" --> PG
        W -- "rol lablinea_metricas<br/>(solo columnas sin PHI)" --> PG
        CORE --> OBJ
        W --> OBJ
    end

    MAIL["Proveedor de correo con BAA<br/>(avisos sin datos clínicos, códigos OTP)"]

    PC --> LB
    PAC --> LB
    ADM --> LB
    W --> MAIL

    subgraph Futuro["Después del MVP"]
        CON["Conector local<br/>(equipos ASTM / HL7 v2)"]
        HIS["HIS de clientes<br/>(FHIR R4 / HL7 v2)"]
        PAY["Pasarela de pagos"]
    end
    CON -. "HTTPS saliente" .-> LB
    HIS -. "API FHIR" .-> LB
    PAY -. "webhooks firmados" .-> LB
```

### Decisiones de topología

- **Un solo código y un solo despliegue**, con dos sub-aplicaciones FastAPI montadas por host (`Host` de Starlette). Comparten el núcleo, pero cada una tiene sus rutas, plantillas y permisos. Separarlas en dos servicios se evalúa solo si la carga lo exige.
- **Cuatro roles de base de datos**, cada uno con lo mínimo necesario:

  | Rol | Uso | Puede |
  |-----|-----|-------|
  | `lablinea_owner` | Migraciones (Alembic) | Dueño de los esquemas; nunca lo usa la aplicación |
  | `lablinea_app` | Tenant App | Esquema `lab` bajo RLS; lectura de `global` |
  | `lablinea_plataforma` | Admin Hub | Esquema `plataforma`; lectura de `global`; **sin acceso a `lab`** |
  | `lablinea_metricas` | Trabajador de métricas | `BYPASSRLS`, pero `SELECT` solo sobre columnas no clínicas (`tenant_id`, fechas, estados, montos); escribe en `plataforma.metricas_diarias` |

- **Cómo ve el Admin Hub los indicadores de todos los laboratorios** (pacientes activos, volumen de órdenes): no consulta `lab`. Un trabajador calcula agregados por laboratorio y día y los guarda en `plataforma`. Así se cumple que la plataforma no accede a datos clínicos ([infraestructura/0005](infraestructura/0005-arquitectura-saas-multitenant.md)).
- **Tareas en segundo plano** (PDF, correos, métricas): cola de trabajos sobre PostgreSQL (`SELECT … FOR UPDATE SKIP LOCKED`), con reintentos. Evita agregar Redis. *La librería se fija en una spec antes del Sprint 3.*

---

## 2. Esquema de base de datos

Núcleo del modelo, aplicando [infraestructura/0007](infraestructura/0007-base-de-datos.md). Se muestran las tablas centrales; el resto (convenios, paquetes, caja, estaciones, rangos) sigue el mismo patrón.

### 2.1 Relaciones

```mermaid
erDiagram
    LABORATORIOS ||--o{ SUSCRIPCIONES : tiene
    PLANES ||--o{ SUSCRIPCIONES : define
    LABORATORIOS ||--o{ SEDES : tiene
    LABORATORIOS ||--o{ USUARIOS : tiene
    USUARIOS }o--o{ ROLES : "usuario_roles"
    PACIENTES ||--o{ ORDENES : solicita
    ORDENES ||--|{ ORDEN_EXAMENES : contiene
    EXAMENES ||--o{ ORDEN_EXAMENES : "precio congelado"
    EXAMENES ||--|{ PARAMETROS : tiene
    PARAMETROS ||--o{ RANGOS_REFERENCIA : "por sexo y edad"
    ORDEN_EXAMENES ||--o{ RESULTADOS : "versiones (solo inserción)"
    PARAMETROS ||--o{ RESULTADOS : mide
    ORDENES ||--o{ MUESTRAS : "tubos"
    ORDENES ||--o{ PAGOS : recibe
```

### 2.2 DDL núcleo

```sql
-- =====================================================================
-- Esquemas y función de contexto
-- =====================================================================
CREATE EXTENSION IF NOT EXISTS citext;           -- correos sin distinguir mayúsculas

CREATE SCHEMA plataforma AUTHORIZATION lablinea_owner;
CREATE SCHEMA global     AUTHORIZATION lablinea_owner;
CREATE SCHEMA lab        AUTHORIZATION lablinea_owner;

-- Tenant de la transacción. La aplicación ejecuta en cada transacción:
--   SET LOCAL app.current_tenant = '<tenant_id>';
--   SET LOCAL app.current_user_id = '<uuid>';  SET LOCAL app.client_ip = '<ip>';
-- Sin tenant definido devuelve NULL o '' y ninguna política deja pasar filas.
CREATE FUNCTION lab.tenant_actual() RETURNS text
LANGUAGE sql STABLE AS $$ SELECT current_setting('app.current_tenant', true) $$;

-- =====================================================================
-- plataforma (Admin Hub) — sin RLS, solo accesible por lablinea_plataforma
-- =====================================================================
CREATE TABLE plataforma.laboratorios (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    uuid            UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    tenant_id       TEXT NOT NULL UNIQUE CHECK (tenant_id ~ '^[a-z0-9_]{3,50}$'),
    nombre_comercial TEXT NOT NULL,
    identificador_fiscal TEXT NOT NULL,
    pais_codigo     CHAR(3) NOT NULL REFERENCES global.paises(codigo),
    subdominio      TEXT NOT NULL UNIQUE,
    dominio_propio  TEXT UNIQUE,                       -- opcional, después del MVP
    estado          TEXT NOT NULL DEFAULT 'ACTIVO'
                    CHECK (estado IN ('ACTIVO','SUSPENDIDO','CANCELADO')),
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE plataforma.planes (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    codigo          TEXT NOT NULL UNIQUE,              -- DEMO, MENSUAL, ANUAL, AD_HONOREM…
    nombre          TEXT NOT NULL,
    duracion_dias   INTEGER,                           -- NULL = indefinida
    max_usuarios    INTEGER,
    funcionalidades JSONB NOT NULL DEFAULT '{}'        -- activación de módulos por plan
);

CREATE TABLE plataforma.suscripciones (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    laboratorio_id  BIGINT NOT NULL REFERENCES plataforma.laboratorios(id),
    plan_id         BIGINT NOT NULL REFERENCES plataforma.planes(id),
    inicia_en       TIMESTAMPTZ NOT NULL DEFAULT now(),
    vence_en        TIMESTAMPTZ,
    estado          TEXT NOT NULL DEFAULT 'ACTIVA'
                    CHECK (estado IN ('ACTIVA','SUSPENDIDA','VENCIDA','CANCELADA')),
    renovacion_automatica BOOLEAN NOT NULL DEFAULT true
);

-- Agregados diarios sin datos clínicos, calculados por lablinea_metricas.
CREATE TABLE plataforma.metricas_diarias (
    laboratorio_id  BIGINT NOT NULL REFERENCES plataforma.laboratorios(id),
    dia             DATE NOT NULL,
    ordenes         INTEGER NOT NULL DEFAULT 0,
    pacientes_activos INTEGER NOT NULL DEFAULT 0,
    resultados_entregados INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (laboratorio_id, dia)
);

-- =====================================================================
-- lab (Tenant App) — RLS en TODAS las tablas
-- =====================================================================
CREATE TABLE lab.usuarios (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    uuid            UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    tenant_id       TEXT NOT NULL,
    email           CITEXT NOT NULL,
    password_hash   TEXT NOT NULL,                     -- Argon2id
    totp_secreto_cifrado BYTEA,
    tarjeta_profesional TEXT,                          -- obligatoria para validar resultados
    tipo            TEXT NOT NULL CHECK (tipo IN ('PERSONAL','PACIENTE','MEDICO')),
    estado          TEXT NOT NULL DEFAULT 'ACTIVO',
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, email),
    UNIQUE (tenant_id, id)                             -- destino de FK compuestas
);
-- Roles y permisos (lab.roles, lab.usuario_roles, lab.rol_permisos con CRUD
-- por módulo + acciones especiales) siguen el mismo patrón; ver infraestructura/0008.

CREATE TABLE lab.pacientes (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    uuid            UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    tenant_id       TEXT NOT NULL,
    tipo_documento  TEXT NOT NULL,                     -- de la configuración del país
    numero_documento TEXT NOT NULL,
    nombres         TEXT NOT NULL,
    apellidos       TEXT NOT NULL,
    sexo            CHAR(1) NOT NULL CHECK (sexo IN ('M','F')),
    fecha_nacimiento DATE NOT NULL,
    email           CITEXT,
    telefono        TEXT,
    usuario_id      BIGINT,                            -- acceso al portal
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, tipo_documento, numero_documento),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, usuario_id) REFERENCES lab.usuarios (tenant_id, id)
);

-- Autorización de tratamiento de datos (Ley 1581): versión del texto aceptado y revocación.
CREATE TABLE lab.autorizaciones_datos (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id       TEXT NOT NULL,
    paciente_id     BIGINT NOT NULL,
    version_texto   TEXT NOT NULL,
    otorgada_en     TIMESTAMPTZ NOT NULL DEFAULT now(),
    revocada_en     TIMESTAMPTZ,
    FOREIGN KEY (tenant_id, paciente_id) REFERENCES lab.pacientes (tenant_id, id)
);

CREATE TABLE lab.examenes (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id       TEXT NOT NULL,
    codigo          TEXT NOT NULL,
    nombre          TEXT NOT NULL,
    seccion         TEXT NOT NULL,
    tecnica_defecto TEXT,
    codigo_cups     TEXT,
    codigo_loinc    TEXT,
    activo          BOOLEAN NOT NULL DEFAULT true,
    UNIQUE (tenant_id, codigo),
    UNIQUE (tenant_id, id)
);
-- lab.parametros, lab.rangos_referencia (sexo, edad_min_dias, edad_max_dias,
-- normal y crítico) y lab.tarifas siguen el mismo patrón; ver funcional/0004.

CREATE TABLE lab.ordenes (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    uuid            UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    tenant_id       TEXT NOT NULL,
    numero          BIGINT NOT NULL,                   -- consecutivo visible, por tenant
    paciente_id     BIGINT NOT NULL,
    sede_id         BIGINT NOT NULL,
    estado          TEXT NOT NULL DEFAULT 'BORRADOR'
                    CHECK (estado IN ('BORRADOR','PRE_CERRADA','PAGADA','ANULADA')),
    moneda          CHAR(3) NOT NULL,
    tasa_cambio     NUMERIC(14,6) NOT NULL DEFAULT 1,
    total           NUMERIC(14,2) NOT NULL DEFAULT 0,
    precerrada_en   TIMESTAMPTZ,
    precerrada_por  BIGINT,
    creada_en       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, numero),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, paciente_id) REFERENCES lab.pacientes (tenant_id, id)
);
CREATE INDEX ON lab.ordenes (tenant_id, creada_en);
CREATE INDEX ON lab.ordenes (tenant_id, estado);
CREATE INDEX ON lab.ordenes (tenant_id, paciente_id);

CREATE TABLE lab.orden_examenes (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id       TEXT NOT NULL,
    orden_id        BIGINT NOT NULL,
    examen_id       BIGINT NOT NULL,
    valor_unitario_historico NUMERIC(14,2) NOT NULL,   -- congelado al pre-cerrar
    cantidad        SMALLINT NOT NULL DEFAULT 1,
    validado_en     TIMESTAMPTZ,
    validado_por    BIGINT,                            -- usuario con tarjeta profesional
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, orden_id)  REFERENCES lab.ordenes  (tenant_id, id),
    FOREIGN KEY (tenant_id, examen_id) REFERENCES lab.examenes (tenant_id, id)
);

-- Resultados: solo inserción. Cada corrección es una fila nueva que apunta a la anterior.
CREATE TABLE lab.resultados (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id       TEXT NOT NULL,
    orden_examen_id BIGINT NOT NULL,
    parametro_id    BIGINT NOT NULL,
    version         INTEGER NOT NULL DEFAULT 1,
    reemplaza_a     BIGINT REFERENCES lab.resultados(id),
    motivo_correccion TEXT,
    valor_numerico  NUMERIC(18,6),
    valor_texto     TEXT,
    bandera         TEXT NOT NULL DEFAULT 'NORMAL'     -- INTERNA: nunca al paciente
                    CHECK (bandera IN ('NORMAL','BAJO','ALTO','CRITICO_BAJO','CRITICO_ALTO','ANORMAL')),
    nota_interna    TEXT,                              -- INTERNA: nunca al paciente
    ingresado_por   BIGINT NOT NULL,
    ingresado_en    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, orden_examen_id, parametro_id, version),
    FOREIGN KEY (tenant_id, orden_examen_id) REFERENCES lab.orden_examenes (tenant_id, id)
);
CREATE INDEX ON lab.resultados (tenant_id, parametro_id, ingresado_en);  -- tendencias

-- Auditoría: solo inserción, particionada por mes, protegida como dato clínico.
CREATE TABLE lab.auditoria (
    id              BIGINT GENERATED ALWAYS AS IDENTITY,
    tenant_id       TEXT NOT NULL,
    tabla           TEXT NOT NULL,
    operacion       TEXT NOT NULL,                     -- INSERT, UPDATE, DELETE, READ
    registro_id     BIGINT,
    usuario_id      TEXT,
    ip              INET,
    antes           JSONB,
    despues         JSONB,
    ocurrido_en     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, ocurrido_en)
) PARTITION BY RANGE (ocurrido_en);
```

### 2.3 RLS, inmutabilidad y permisos

```sql
-- Política estándar, aplicada por migración a cada tabla de lab.
DO $$
DECLARE t text;
BEGIN
  FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'lab' LOOP
    EXECUTE format('ALTER TABLE lab.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE lab.%I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format($p$
      CREATE POLICY aislamiento_tenant ON lab.%I
        USING      (tenant_id = lab.tenant_actual())
        WITH CHECK (tenant_id = lab.tenant_actual())
    $p$, t);
  END LOOP;
END $$;

GRANT USAGE ON SCHEMA lab TO lablinea_app;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA lab TO lablinea_app;
-- Resultados y auditoría: solo inserción y lectura, también a nivel de permisos.
REVOKE UPDATE, DELETE ON lab.resultados, lab.auditoria FROM lablinea_app;

-- Segunda barrera: trigger que rechaza cambios aunque alguien otorgue el permiso.
CREATE FUNCTION lab.rechazar_modificacion() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'La tabla % es de solo inserción', TG_TABLE_NAME;
END $$;
CREATE TRIGGER resultados_inmutables BEFORE UPDATE OR DELETE ON lab.resultados
  FOR EACH ROW EXECUTE FUNCTION lab.rechazar_modificacion();

-- Orden congelada: fuera de BORRADOR solo se permite avanzar de estado.
CREATE FUNCTION lab.proteger_orden() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.estado <> 'BORRADOR' AND (
       NEW.total IS DISTINCT FROM OLD.total OR
       NEW.paciente_id IS DISTINCT FROM OLD.paciente_id OR
       NEW.moneda IS DISTINCT FROM OLD.moneda) THEN
    RAISE EXCEPTION 'La orden % está %, no se puede modificar', OLD.numero, OLD.estado;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER ordenes_congeladas BEFORE UPDATE ON lab.ordenes
  FOR EACH ROW EXECUTE FUNCTION lab.proteger_orden();
```

**Prueba obligatoria** (Sprint 1): recorre `pg_class` y falla si alguna tabla de `lab` no tiene `relrowsecurity` y `relforcerowsecurity` activos o le falta la política `aislamiento_tenant`.

---

## 3. Estructura del proyecto

```
LabLineaWeb/
├── app/
│   ├── main.py                    # crea la app y monta tenant/ y admin/ por host
│   ├── core/                      # núcleo compartido
│   │   ├── config.py              # settings desde .env
│   │   ├── db.py                  # engines por rol; sesión con SET LOCAL de tenant, usuario e IP
│   │   ├── tenancy.py             # resuelve el tenant desde el subdominio (nunca desde la petición)
│   │   ├── seguridad.py           # Argon2id, TOTP, OTP por correo, sesiones, CSRF, cabeceras
│   │   ├── permisos.py            # RBAC: CRUD por módulo + acciones especiales
│   │   ├── auditoria.py           # auditoría de lecturas
│   │   ├── i18n.py                # textos externalizados, zonas horarias
│   │   └── tareas.py              # cola de trabajos en PostgreSQL
│   ├── modelos/
│   │   ├── plataforma.py          # SQLAlchemy: laboratorios, planes, suscripciones…
│   │   ├── global_.py             # países, monedas, tipos de documento
│   │   └── lab/                   # pacientes, órdenes, muestras, resultados…
│   ├── tenant/                    # PROYECTO 1 — Tenant App
│   │   ├── rutas/                 # pacientes, ordenes, caja, muestras, resultados, portal, configuracion
│   │   ├── servicios/             # reglas de negocio (precierre, agrupación de tubos, banderas…)
│   │   └── templates/tenant/
│   ├── admin/                     # PROYECTO 2 — Admin Hub
│   │   ├── rutas/                 # laboratorios, planes, suscripciones, facturacion, metricas, salud
│   │   ├── servicios/             # alta de laboratorios, ciclo de suscripción
│   │   └── templates/admin/
│   ├── informes/                  # generación de PDF
│   │   ├── generador.py
│   │   ├── vistas.py              # modelos de vista SIN campos internos
│   │   └── plantillas/            # base_informe.html, resultados.html, informe.css
│   ├── fhir/                      # mapeo del modelo a recursos FHIR R4
│   ├── importador/                # catálogo de Lablinea (Access)
│   ├── templates/                 # base.html y componentes compartidos (tablas, formularios, gráficas)
│   └── static/                    # css/, js/ (htmx, Chart.js, qz-tray), img/
├── migrations/                    # Alembic (rol lablinea_owner)
├── trabajador.py                  # proceso de tareas en segundo plano
├── scripts/                       # crear_bd_local.sql, datos sintéticos
├── tests/
│   ├── unit/                      # reglas de negocio puras
│   ├── integracion/               # con PostgreSQL de prueba
│   ├── aislamiento/               # tenant A vs tenant B, por cada módulo
│   └── seguridad/                 # permisos, cabeceras, CSRF, auditoría
├── specs/
└── CLAUDE.md
```

**Regla de dependencias:** `tenant/` y `admin/` dependen de `core/` y `modelos/`, nunca entre sí. `admin/` no importa modelos de `lab/` (salvo para el alta de un laboratorio, que crea su configuración inicial con el tenant fijado).

---

## 4. Hoja de ruta por sprints

Sprints de 2 semanas. La duración real depende del tamaño del equipo. Las 4 fases de este plan agrupan las 5 fases del [MVP](funcional/0007-alcance-mvp.md):

| Fase del plan | Fases del MVP |
|---|---|
| 1. Infraestructura, base multi-tenant y autenticación | 1 (base) y 2 (seguridad) |
| 2. Admin Hub | 1 (laboratorios, licencias, suscripciones) |
| 3. Tenant App | 3 (POS y caja), 4 (muestras), 5 (resultados) |
| 4. Dashboards, auditoría de seguridad y despliegue | Cierre del MVP |

### Fase 1 — Infraestructura, base multi-tenant y autenticación

| Sprint | Entregable | Criterio de terminado |
|---|---|---|
| **0** | Herramientas: CI en GitHub Actions (pytest con PostgreSQL de servicio, linter), configuración por `.env`, conexión a la base, Alembic | Cada push corre pruebas contra PostgreSQL real |
| **1** | Esquemas `plataforma`/`global`/`lab`, los 4 roles, RLS estándar, resolución de tenant por subdominio, sesión con `SET LOCAL`; catálogos globales (países, monedas, tipos de documento) | Prueba que recorre el catálogo y prueba de aislamiento A/B pasan |
| **2** | Autenticación: Argon2id, sesiones en servidor, TOTP, OTP por correo, bloqueo y límites; RBAC con acciones especiales; CSRF y cabeceras de seguridad | Pruebas de cada acción especial y de cabeceras |
| **3** | Auditoría (triggers + lecturas, particiones), cola de tareas, i18n base, generador de datos sintéticos | Toda escritura en tablas sensibles deja rastro verificable |

### Fase 2 — Admin Hub (Proyecto 2)

| Sprint | Entregable | Criterio de terminado |
|---|---|---|
| **4** | Usuarios y roles de plataforma; **alta de laboratorio** (crea tenant, subdominio, configuración de país, sede inicial y administrador); planes con activación de módulos | Un laboratorio nuevo opera de inmediato y aislado |
| **5** | Suscripciones y su ciclo (vencimiento, suspensión, alertas de renovación); facturas con pagos manuales; acceso de soporte autorizado y auditado; métricas diarias agregadas | Suscripción vencida bloquea órdenes nuevas pero no la consulta de resultados |

### Fase 3 — Tenant App (Proyecto 1)

| Sprint | Entregable | Specs |
|---|---|---|
| **6** | Catálogo: exámenes, parámetros, rangos por sexo y edad, tarifas; **importador de Lablinea** | [funcional/0004](funcional/0004-resultados-validacion-entrega.md), [0007](funcional/0007-alcance-mvp.md) |
| **7** | Pacientes con autorización de datos (Ley 1581) y derechos del titular | [infraestructura/0004](infraestructura/0004-normativa-colombia-latam.md) |
| **8** | Órdenes y POS: pre-cierre, convenios con tope y evidencia, paquetes | [funcional/0002](funcional/0002-pos-ordenes-caja.md) |
| **9** | Caja: apertura, pagos, abonos, arqueo y cierre | [funcional/0002](funcional/0002-pos-ordenes-caja.md) |
| **10** | Muestras: agrupación de tubos, códigos de barras, cola de toma, ZPL con QZ Tray | [funcional/0003](funcional/0003-muestras-impresion.md) |
| **11** | Resultados: ingreso, banderas internas, valores críticos, versiones, validación con tarjeta profesional | [funcional/0004](funcional/0004-resultados-validacion-entrega.md) |
| **12** | Informe PDF (WeasyPrint), firma electrónica, regla de liberación, portal de pacientes y médicos, aviso por correo, gráficas de tendencia, mapeo FHIR | [funcional/0004](funcional/0004-resultados-validacion-entrega.md), [infraestructura/0002](infraestructura/0002-interoperabilidad-hl7-fhir.md) |

### Fase 4 — Dashboards, auditoría de seguridad y despliegue

| Sprint | Entregable |
|---|---|
| **13** | Dashboard del Admin Hub (laboratorios activos y suspendidos, MRR/ARR, volumen agregado, salud del sistema). Dashboard operativo básico del laboratorio *(pendiente de decisión, ver abajo)* |
| **14** | Auditoría de seguridad: revisión contra OWASP ASVS, prueba de penetración externa, revisión de aislamiento; despliegue en el hosting elegido con staging, copias de seguridad cifradas y **restauración probada**; piloto con un laboratorio |

**Antes del Sprint 4** debe estar decidido el hosting, para tener un entorno de staging desde la fase 2 y no dejar el primer despliegue para el final.

---

## 5. Arquitectura de plantillas PDF

Tres principios:

1. **La plantilla no puede filtrar lo que no recibe.** El generador recibe un modelo de vista que **no tiene** bandera ni nota interna ([funcional/0004](funcional/0004-resultados-validacion-entrega.md)). No depende de que la plantilla "se acuerde" de no mostrarlas.
2. **WeasyPrint no descarga nada de internet.** Logos y firmas se leen del almacenamiento del tenant y se pasan embebidos; un `url_fetcher` propio rechaza cualquier otra URL (evita SSRF desde una plantilla configurada por un laboratorio).
3. **Autoescape siempre activo**: un nombre de paciente o una nota no puede inyectar HTML en el informe.

### `app/informes/vistas.py`

```python
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ParametroInforme:
    nombre: str
    valor: str                 # ya formateado; sin bandera ni nota interna
    unidad: str | None
    referencia: str | None     # rango aplicable a la edad y sexo del paciente
    es_titulo: bool = False


@dataclass(frozen=True)
class ExamenInforme:
    nombre: str
    tecnica: str | None
    parametros: list[ParametroInforme]
    validador_nombre: str
    validador_tarjeta: str
    validado_en: datetime
    notas: str | None          # notas aprobadas por el profesional
    corregido: bool = False    # muestra nota de corrección


@dataclass(frozen=True)
class MarcaLaboratorio:
    nombre: str
    logo_data_uri: str | None
    color_primario: str
    color_secundario: str
    marca_agua: str | None
    pie_de_pagina: str | None


@dataclass(frozen=True)
class InformeResultados:
    laboratorio: MarcaLaboratorio
    paciente_nombre: str
    paciente_documento: str
    paciente_edad: str
    paciente_sexo: str
    orden_numero: int
    fecha_toma: datetime
    medico: str | None
    examenes: list[ExamenInforme]
    codigo_verificacion: str   # permite verificar el informe en el portal
```

### `app/informes/generador.py`

```python
import hashlib
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML, default_url_fetcher

from app.informes.vistas import InformeResultados

PLANTILLAS = Path(__file__).parent / "plantillas"

entorno = Environment(
    loader=FileSystemLoader(PLANTILLAS),
    autoescape=select_autoescape(["html"]),
)


def _solo_recursos_locales(url: str):
    # Logos y firmas llegan como data: URI; los estilos, desde la carpeta de plantillas.
    if url.startswith("data:") or url.startswith(PLANTILLAS.as_uri()):
        return default_url_fetcher(url)
    raise ValueError(f"Recurso externo no permitido en el informe: {url}")


def generar_pdf(informe: InformeResultados, idioma: str = "es") -> tuple[bytes, str]:
    """Devuelve el PDF y su hash SHA-256 (se guarda para verificar integridad)."""
    html = entorno.get_template("resultados.html").render(informe=informe, idioma=idioma)
    pdf = HTML(
        string=html,
        base_url=PLANTILLAS.as_uri() + "/",
        url_fetcher=_solo_recursos_locales,
    ).write_pdf()
    return pdf, hashlib.sha256(pdf).hexdigest()
```

### `app/informes/plantillas/base_informe.html`

```html
<!doctype html>
<html lang="{{ idioma }}">
<head>
  <meta charset="utf-8">
  <link rel="stylesheet" href="informe.css">
  <style>
    :root {
      --primario: {{ informe.laboratorio.color_primario }};
      --secundario: {{ informe.laboratorio.color_secundario }};
    }
  </style>
</head>
<body>
  <header class="encabezado">
    {% if informe.laboratorio.logo_data_uri %}
      <img class="logo" src="{{ informe.laboratorio.logo_data_uri }}" alt="">
    {% endif %}
    <div class="laboratorio">{{ informe.laboratorio.nombre }}</div>
    {% block datos_paciente %}{% endblock %}
  </header>

  <footer class="pie">
    {{ informe.laboratorio.pie_de_pagina or "" }}
    <span class="verificacion">Verificación: {{ informe.codigo_verificacion }}</span>
    <span class="paginas"></span>
  </footer>

  {% if informe.laboratorio.marca_agua %}
    <div class="marca-agua">{{ informe.laboratorio.marca_agua }}</div>
  {% endif %}

  <main>{% block contenido %}{% endblock %}</main>
</body>
</html>
```

### `app/informes/plantillas/resultados.html`

```html
{% extends "base_informe.html" %}

{% block datos_paciente %}
<table class="paciente">
  <tr>
    <th>Paciente</th><td>{{ informe.paciente_nombre }}</td>
    <th>Documento</th><td>{{ informe.paciente_documento }}</td>
  </tr>
  <tr>
    <th>Edad / Sexo</th><td>{{ informe.paciente_edad }} / {{ informe.paciente_sexo }}</td>
    <th>Orden</th><td>{{ informe.orden_numero }}</td>
  </tr>
  <tr>
    <th>Toma</th><td>{{ informe.fecha_toma.strftime("%d/%m/%Y %H:%M") }}</td>
    <th>Médico</th><td>{{ informe.medico or "—" }}</td>
  </tr>
</table>
{% endblock %}

{% block contenido %}
{% for examen in informe.examenes %}
<section class="examen">
  <h2>{{ examen.nombre }}</h2>
  {% if examen.tecnica %}<p class="tecnica">Técnica: {{ examen.tecnica }}</p>{% endif %}
  {% if examen.corregido %}
    <p class="correccion">Este resultado reemplaza a una versión anterior.</p>
  {% endif %}

  <table class="resultados">
    <thead>
      <tr><th>Parámetro</th><th>Resultado</th><th>Unidad</th><th>Valor de referencia</th></tr>
    </thead>
    <tbody>
      {% for p in examen.parametros %}
        {% if p.es_titulo %}
          <tr class="titulo"><td colspan="4">{{ p.nombre }}</td></tr>
        {% else %}
          <tr>
            <td>{{ p.nombre }}</td>
            <td class="valor">{{ p.valor }}</td>
            <td>{{ p.unidad or "" }}</td>
            <td>{{ p.referencia or "" }}</td>
          </tr>
        {% endif %}
      {% endfor %}
    </tbody>
  </table>

  {% if examen.notas %}<p class="notas">{{ examen.notas }}</p>{% endif %}

  <p class="validacion">
    Validado por {{ examen.validador_nombre }} — T.P. {{ examen.validador_tarjeta }}
    — {{ examen.validado_en.strftime("%d/%m/%Y %H:%M") }}
  </p>
</section>
{% endfor %}
{% endblock %}
```

### `app/informes/plantillas/informe.css`

```css
@page {
  size: letter;
  margin: 3.2cm 1.8cm 2.2cm;
  @top-center { content: element(encabezado); }
  @bottom-center { content: element(pie); }
}
.encabezado { position: running(encabezado); border-bottom: 2px solid var(--primario); }
.pie { position: running(pie); font-size: 8pt; color: #555; }
.paginas::after { content: "Página " counter(page) " de " counter(pages); }
.logo { height: 1.4cm; }
.marca-agua {
  position: fixed; top: 45%; left: 0; right: 0; text-align: center;
  font-size: 64pt; color: var(--secundario); opacity: .08; transform: rotate(-30deg);
}
.examen { break-inside: avoid; margin-top: .6cm; }
.examen h2 { color: var(--primario); font-size: 12pt; }
.resultados { width: 100%; border-collapse: collapse; font-size: 9.5pt; }
.resultados th { text-align: left; border-bottom: 1px solid var(--primario); }
.resultados tr.titulo td { font-weight: bold; padding-top: .3cm; }
.valor { font-weight: 600; }
.correccion { color: #8a5a00; font-style: italic; }
.validacion { font-size: 8.5pt; color: #333; }
```

---

## 6. Diferencias con el documento de requisitos de este plan

| Requisito recibido | Cómo queda | Por qué |
|---|---|---|
| RLS **o** esquema por laboratorio | RLS | [infraestructura/0005](infraestructura/0005-arquitectura-saas-multitenant.md) |
| JWT **o** sesión | Sesión en servidor con cookie; tokens solo para la API FHIR | [infraestructura/0008](infraestructura/0008-autenticacion-autorizacion.md) |
| `users.role` con SUPER_ADMIN, LAB_ADMIN, TECH, PATIENT | Usuarios de plataforma separados de los del laboratorio; roles configurables con permisos por módulo | [infraestructura/0008](infraestructura/0008-autenticacion-autorizacion.md); un SUPER_ADMIN dentro de la tabla del laboratorio rompería el aislamiento |
| `tenants.id` UUID | `tenant_id` legible + `uuid` público | [infraestructura/0007](infraestructura/0007-base-de-datos.md) |
| TLS 1.3 | TLS 1.2 mínimo, 1.3 preferido | Compatibilidad con equipos antiguos de laboratorios |
| Logs de actividad entre laboratorios en el Admin Hub | Solo metadatos y agregados, sin datos clínicos | [infraestructura/0005](infraestructura/0005-arquitectura-saas-multitenant.md) |
| Pipeline de despliegue en la fase 4 | CI desde el Sprint 0; staging desde la fase 2 | Detectar fallos de aislamiento y despliegue temprano |
| **Indicadores de estado y resaltado de rangos en el PDF** | **Pendiente de decisión** | Contradice [funcional/0004](funcional/0004-resultados-validacion-entrega.md) |
| **Dashboard ejecutivo del laboratorio** | **Pendiente de decisión** | [funcional/0007](funcional/0007-alcance-mvp.md) lo deja fuera del MVP |
| **Distribución de comisiones** en el Admin Hub | **Pendiente de definir** | No aparece en ninguna spec ni fuente |
