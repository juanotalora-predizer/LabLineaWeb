TablasMaestras SaaS

-- Países soportados por la plataforma SaaS (Multi-país)
CREATE TABLE saas_paises (
codigo VARCHAR(3) PRIMARY KEY, -- Ej: COL, USA, MEX
nombre VARCHAR(50) NOT NULL,
moneda_base VARCHAR(3) NOT NULL, -- Referencia a monedas(codigo)
impuesto_porcentaje NUMERIC(5,2) DEFAULT 0.00 -- IVA o impuesto local
);

-- Tipos de Licencia y Modelo de Negocio
CREATE TABLE saas_tipos_licencia (
id SERIAL PRIMARY KEY,
codigo VARCHAR(20) UNIQUE NOT NULL, -- DEMO, AD_HOREM, MENSUAL, ANUAL, GRATUITO_BASICO
nombre VARCHAR(50) NOT NULL,
descripcion TEXT,
es_gratuito BOOLEAN DEFAULT FALSE,
duracion_dias INTEGER, -- Null si es indefinida (ej. Ad Honorem o pago recurrente)
max_usuarios SMALLINT DEFAULT 1
);

-- Campañas de Marketing y Precios Especiales
CREATE TABLE saas_campanas_marketing (
id SERIAL PRIMARY KEY,
codigo VARCHAR(30) UNIQUE NOT NULL,
nombre VARCHAR(100) NOT NULL,
fecha_inicio DATE,
fecha_fin DATE,
descuento_porcentaje NUMERIC(5,2) DEFAULT 0.00,
activa BOOLEAN DEFAULT TRUE
);

-- Listas de Precios por País y Tipo de Licencia
CREATE TABLE saas_listas_precios (
id SERIAL PRIMARY KEY,
pais_codigo VARCHAR(3) NOT NULL,
tipo_licencia_id INTEGER NOT NULL,
moneda_codigo VARCHAR(3) NOT NULL,
precio NUMERIC(12,2) NOT NULL,
campana_id INTEGER, -- Opcional si aplica descuento de campaña
CONSTRAINT fk_lp_pais FOREIGN KEY (pais_codigo) REFERENCES saas_paises(codigo),
CONSTRAINT fk_lp_licencia FOREIGN KEY (tipo_licencia_id) REFERENCES saas_tipos_licencia(id),
CONSTRAINT fk_lp_moneda FOREIGN KEY (moneda_codigo) REFERENCES monedas(codigo),
CONSTRAINT fk_lp_campana FOREIGN KEY (campana_id) REFERENCES saas_campanas_marketing(id)
);
