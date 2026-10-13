NUEVO DDL LabLineaWeb

-- =========================================================================
-- EXTENSIONES Y CONFIGURACIÓN INICIAL
-- =========================================================================
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =========================================================================
-- 1. TABLAS MAESTRAS GLOBALES O COMPARTIDAS
-- =========================================================================

-- Tabla de Monedas (Soporte Multimoneda)
CREATE TABLE monedas (
codigo VARCHAR(3) PRIMARY KEY, -- Ej: COP, USD, EUR
nombre VARCHAR(50) NOT NULL,
simbolo VARCHAR(5) NOT NULL,
es_base BOOLEAN DEFAULT FALSE -- Indica si es la moneda contable principal del sistema
);

-- =========================================================================
-- 2. TABLAS MAESTRAS CON MULTI-TENANCY (tenant_id)
-- =========================================================================

-- Sedes del Laboratorio
CREATE TABLE sedes (
id SERIAL PRIMARY KEY,
tenant_id VARCHAR(50) NOT NULL, -- Identificador único del laboratorio cliente
codigo_sede VARCHAR(2) NOT NULL,
nombre_sede VARCHAR(50) NOT NULL,
direccion_sede VARCHAR(50),
telefono_sede VARCHAR(20),
CONSTRAINT uk_tenant_sede UNIQUE (tenant_id, codigo_sede)
);

-- Tipos de Tarifa por Laboratorio
CREATE TABLE tipo_tarifa (
id SERIAL PRIMARY KEY,
tenant_id VARCHAR(50) NOT NULL,
codigo VARCHAR(15) NOT NULL,
descripcion VARCHAR(50) NOT NULL,
CONSTRAINT uk_tenant_tarifa UNIQUE (tenant_id, codigo)
);

-- Empresas / Clientes Corporativos
CREATE TABLE empresa (
consecutivo SERIAL PRIMARY KEY,
tenant_id VARCHAR(50) NOT NULL,
nit VARCHAR(50),
descripcion VARCHAR(50) NOT NULL,
tel VARCHAR(50),
dir VARCHAR(50),
descuento NUMERIC(5,2) DEFAULT 0.10 NOT NULL,
codigo_sgss VARCHAR(10),
contrato VARCHAR(10),
plan_beneficios VARCHAR(30),
poliza VARCHAR(10),
need_copago BOOLEAN DEFAULT FALSE,
usuario_digitacion VARCHAR(50),
fecha_digitacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
usuario_last_update VARCHAR(50),
fecha_last_update TIMESTAMP
);
CREATE INDEX idx_empresa_tenant ON empresa(tenant_id);

-- Pacientes
CREATE TABLE paciente (
consecutivo SERIAL PRIMARY KEY,
tenant_id VARCHAR(50) NOT NULL,
tipo_id VARCHAR(3) DEFAULT 'CC',
cc VARCHAR(50),
apellidos VARCHAR(30) NOT NULL,
nombres VARCHAR(25) NOT NULL,
segundo_apellido VARCHAR(20),
segundo_nombre VARCHAR(20),
tel VARCHAR(50),
dir VARCHAR(50),
sexo VARCHAR(1) NOT NULL,
fecha_nacimiento DATE,
edad VARCHAR(50),
unidad_edad VARCHAR(1) DEFAULT 'A',
nom_titular VARCHAR(50),
prntsco_titular VARCHAR(50),
tipo_usuario VARCHAR(1) DEFAULT 'P',
zona_residencia VARCHAR(1) DEFAULT 'U',
tipo_afiliado VARCHAR(1) DEFAULT 'C',
ocupacion VARCHAR(3),
grp_ant_esp VARCHAR(1) DEFAULT 'O',
res_habitual VARCHAR(5) DEFAULT '76001',
condicion_usuaria VARCHAR(1),
usuario_digitacion VARCHAR(50),
fecha_digitacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
usuario_last_update VARCHAR(50),
fecha_last_update TIMESTAMP
);
CREATE INDEX idx_paciente_tenant ON paciente(tenant_id);
CREATE INDEX idx_paciente_apellidos ON paciente(tenant_id, apellidos);

-- Secciones de Laboratorio
CREATE TABLE seccion (
codigo VARCHAR(50) NOT NULL,
tenant_id VARCHAR(50) NOT NULL,
descripcion VARCHAR(50) NOT NULL,
PRIMARY KEY (tenant_id, codigo)
);

-- Catálogo de Análisis (Exámenes)
CREATE TABLE analisis (
consecutivo SERIAL PRIMARY KEY,
tenant_id VARCHAR(50) NOT NULL,
codigo_examen VARCHAR(10),
especimen VARCHAR(20),
descripcion VARCHAR(50) NOT NULL,
seccion VARCHAR(50) NOT NULL,
codigo_sgss VARCHAR(10),
autoriz_adic BOOLEAN DEFAULT FALSE,
dias_montaje VARCHAR(30) DEFAULT 'LU a VI',
usuario_digitacion VARCHAR(50),
fecha_digitacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
usuario_last_update VARCHAR(50),
fecha_last_update TIMESTAMP,
CONSTRAINT fk_analisis_seccion FOREIGN KEY (tenant_id, seccion) REFERENCES seccion(tenant_id, codigo) ON UPDATE CASCADE
);
CREATE INDEX idx_analisis_tenant ON analisis(tenant_id);

-- Costos de Análisis por Tipo de Tarifa y Moneda
CREATE TABLE costo_analisis (
tipo_tarifa VARCHAR(15) NOT NULL,
analisis INTEGER NOT NULL,
tenant_id VARCHAR(50) NOT NULL,
moneda_codigo VARCHAR(3) NOT NULL DEFAULT 'COP',
costo DECIMAL(12,4) NOT NULL,
PRIMARY KEY (tenant_id, tipo_tarifa, analisis),
CONSTRAINT fk_costo_analisis FOREIGN KEY (analisis) REFERENCES analisis(consecutivo) ON DELETE CASCADE,
CONSTRAINT fk_costo_moneda FOREIGN KEY (moneda_codigo) REFERENCES monedas(codigo)
);

-- =========================================================================
-- 3. TABLAS TRANSACCIONALES
-- =========================================================================

-- Órdenes Médicas
CREATE TABLE orden (
consecutivo SERIAL PRIMARY KEY,
tenant_id VARCHAR(50) NOT NULL,
numero_de_la_orden INTEGER NOT NULL,
paciente INTEGER NOT NULL,
fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
cancelada BOOLEAN DEFAULT FALSE,
empresa_a_cobrar INTEGER DEFAULT 0,
tipo_tarifa VARCHAR(15) NOT NULL,
moneda_codigo VARCHAR(3) NOT NULL DEFAULT 'COP',
tasa_cambio DECIMAL(12,4) DEFAULT 1.0000 NOT NULL, -- Para multimoneda histórica
valor_a_cobrar NUMERIC(12,2) DEFAULT 0 NOT NULL,
otros_conceptos NUMERIC(12,2) DEFAULT 0,
dcto_global NUMERIC(12,2) DEFAULT 0,
descuento NUMERIC(12,2) DEFAULT 0,
vlr_copago NUMERIC(12,2) DEFAULT 0,
vlr_usuario NUMERIC(12,2) DEFAULT 0,
doctor VARCHAR(50),
auxiliar VARCHAR(50),
observaciones TEXT,
anulada BOOLEAN DEFAULT FALSE,
atendido_por VARCHAR(50),
voucher VARCHAR(50),
num_poliza VARCHAR(20),
codigo_sede VARCHAR(2) DEFAULT 'N',
num_autoriz_adic VARCHAR(15),
txt_autoriz_adic VARCHAR(50),
usuario_digitacion VARCHAR(50),
fecha_digitacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
usuario_last_update VARCHAR(50),
fecha_last_update TIMESTAMP,
hora_digitacion TIME DEFAULT CURRENT_TIME,
CONSTRAINT fk_orden_paciente FOREIGN KEY (paciente) REFERENCES paciente(consecutivo) ON UPDATE CASCADE,
CONSTRAINT fk_orden_empresa FOREIGN KEY (empresa_a_cobrar) REFERENCES empresa(consecutivo),
CONSTRAINT fk_orden_moneda FOREIGN KEY (moneda_codigo) REFERENCES monedas(codigo),
CONSTRAINT uk_tenant_num_orden UNIQUE (tenant_id, numero_de_la_orden)
);
CREATE INDEX idx_orden_tenant ON orden(tenant_id);
CREATE INDEX idx_orden_paciente ON orden(paciente);

-- Detalle de Análisis por Orden
CREATE TABLE analisis_por_orden (
consecutivo SERIAL PRIMARY KEY,
tenant_id VARCHAR(50) NOT NULL,
analisis INTEGER NOT NULL,
numero_de_orden INTEGER NOT NULL,
tipo_tarifa VARCHAR(15) NOT NULL,
costo_real DECIMAL(12,4),
tipo_procedimiento VARCHAR(1) DEFAULT '1',
clase_procedimiento VARCHAR(1) DEFAULT '1',
cantidad_procedimiento SMALLINT DEFAULT 1,
fecha_procedimiento DATE DEFAULT CURRENT_DATE,
observaciones VARCHAR(255),
usuario_digitacion VARCHAR(50),
fecha_digitacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
hora_digitacion TIME DEFAULT CURRENT_TIME,
first_print TIMESTAMP,
last_print TIMESTAMP,
print_times SMALLINT DEFAULT 0,
CONSTRAINT fk_apo_analisis FOREIGN KEY (analisis) REFERENCES analisis(consecutivo)
);
CREATE INDEX idx_apo_tenant ON analisis_por_orden(tenant_id);
CREATE INDEX idx_apo_orden ON analisis_por_orden(numero_de_orden, analisis);
