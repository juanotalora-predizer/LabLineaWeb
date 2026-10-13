Clientes SaaS 

-- Registro Maestro de Laboratorios Clientes del SaaS (Tenants)
CREATE TABLE saas_laboratorios (
tenant_id VARCHAR(50) PRIMARY KEY, -- Identificador único (ej: lab_vida_cali)
nombre_comercial VARCHAR(100) NOT NULL,
nit_o_identificador VARCHAR(50) NOT NULL,
pais_codigo VARCHAR(3) NOT NULL,
direccion VARCHAR(100),
telefono VARCHAR(30),
email_contacto VARCHAR(100) NOT NULL,
activo BOOLEAN DEFAULT TRUE,
fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
CONSTRAINT fk_lab_pais FOREIGN KEY (pais_codigo) REFERENCES saas_paises(codigo)
);

-- Suscripciones Activas por Laboratorio (Control de Vigencia y Tipo de Licencia)
CREATE TABLE saas_suscripciones (
id SERIAL PRIMARY KEY,
tenant_id VARCHAR(50) NOT NULL,
tipo_licencia_id INTEGER NOT NULL,
fecha_inicio TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
fecha_vencimiento TIMESTAMP, -- Nulo si es perpetua/ad honorem activa
estado VARCHAR(20) DEFAULT 'ACTIVA', -- ACTIVA, SUSPENDIDA, VENCIDA, CANCELADA
renovacion_automatica BOOLEAN DEFAULT TRUE,
usuario_digitacion VARCHAR(50),
CONSTRAINT fk_susc_tenant FOREIGN KEY (tenant_id) REFERENCES saas_laboratorios(tenant_id),
CONSTRAINT fk_susc_licencia FOREIGN KEY (tipo_licencia_id) REFERENCES saas_tipos_licencia(id)
);
CREATE INDEX idx_susc_tenant ON saas_suscripciones(tenant_id);
