SaaS Muestras DDL

-- Configuración de Muestras Requeridas por Examen (Volúmenes mínimos)
CREATE TABLE muestras_x_analisis (
consecutivo SERIAL PRIMARY KEY,
tenant_id VARCHAR(50) NOT NULL,
analisis INTEGER NOT NULL,
tipo_muestra VARCHAR(5) NOT NULL, -- Ej: SANG, ORIN, SUERO
volumen_minimo_ml NUMERIC(6,2) DEFAULT 1.00 NOT NULL, -- Volumen requerido en ml
tubo_sugerido VARCHAR(50) NOT NULL, -- Ej: Tubo Tapa Roja, Tubo Tapa Lila (EDTA)
CONSTRAINT fk_mx_analisis FOREIGN KEY (analisis) REFERENCES analisis(consecutivo) ON DELETE CASCADE,
CONSTRAINT fk_mx_tipo_muestra FOREIGN KEY (tenant_id, tipo_muestra) REFERENCES tipo_muestra(tenant_id, tipo)
);
CREATE INDEX idx_mx_analisis_tenant ON muestras_x_analisis(tenant_id);

-- Registro de Muestras Físicas Generadas por Orden (Tramos de tubos / Contenedores)
CREATE TABLE muestra_x_orden (
consecutivo SERIAL PRIMARY KEY,
tenant_id VARCHAR(50) NOT NULL,
numero_de_orden INTEGER NOT NULL,
tipo_muestra VARCHAR(5) NOT NULL,
codigo_barras_tubo VARCHAR(50) UNIQUE NOT NULL, -- Código único de la etiqueta física (Ej: LAB1-ORD1025-SANG-1)
secuencia_tubo SMALLINT DEFAULT 1 NOT NULL, -- Número de tubo (Tubo 1 de 2, Tubo 2 de 2)
total_tubos_requeridos SMALLINT DEFAULT 1 NOT NULL,
tubo_descripcion VARCHAR(50) NOT NULL, -- Ej: "Tubo Tapa Lila - EDTA"
volumen_total_ml NUMERIC(6,2) NOT NULL,
estado VARCHAR(20) DEFAULT 'RECOLECTADA', -- RECOLECTADA, EN_PROCESO, MUESTRA_RECHAZADA
observaciones VARCHAR(200),
usuario_toma VARCHAR(50) NOT NULL,
fecha_toma TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
CONSTRAINT fk_mo_orden FOREIGN KEY (tenant_id, numero_de_orden) REFERENCES orden(tenant_id, numero_de_la_orden) ON DELETE CASCADE
);
CREATE INDEX idx_mo_tenant_orden ON muestra_x_orden(tenant_id, numero_de_orden);

-- Tabla intermedia: Relaciona qué exámenes específicos van dentro de este tubo/código de barras
CREATE TABLE detalle_muestra_examenes (
muestra_orden_id INTEGER NOT NULL,
analisis_por_orden_id INTEGER NOT NULL,
PRIMARY KEY (muestra_orden_id, analisis_por_orden_id),
CONSTRAINT fk_dme_muestra FOREIGN KEY (muestra_orden_id) REFERENCES muestra_x_orden(consecutivo) ON DELETE CASCADE,
CONSTRAINT fk_dme_apo FOREIGN KEY (analisis_por_orden_id) REFERENCES analisis_por_orden(consecutivo) ON DELETE CASCADE
);

