SaaS Contabilidad

-- Facturación SaaS generada a los laboratorios
CREATE TABLE saas_facturas (
id SERIAL PRIMARY KEY,
numero_factura VARCHAR(30) UNIQUE NOT NULL,
tenant_id VARCHAR(50) NOT NULL,
suscripcion_id INTEGER NOT NULL,
fecha_emision TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
fecha_vencimiento DATE NOT NULL,
moneda_codigo VARCHAR(3) NOT NULL,
tasa_cambio NUMERIC(12,4) DEFAULT 1.0000,
subtotal NUMERIC(12,2) NOT NULL,
impuestos NUMERIC(12,2) DEFAULT 0.00,
total NUMERIC(12,2) NOT NULL,
saldo_pendiente NUMERIC(12,2) NOT NULL, -- Control de cartera
estado VARCHAR(20) DEFAULT 'PENDIENTE', -- PENDIENTE, PAGADA_PARCIAL, PAGADA, ANULADA
CONSTRAINT fk_fac_tenant FOREIGN KEY (tenant_id) REFERENCES saas_laboratorios(tenant_id),
CONSTRAINT fk_fac_susc FOREIGN KEY (suscripcion_id) REFERENCES saas_suscripciones(id),
CONSTRAINT fk_fac_moneda FOREIGN KEY (moneda_codigo) REFERENCES monedas(codigo)
);
CREATE INDEX idx_facturas_cartera ON saas_facturas(tenant_id, estado);

-- Pagos y Abonos Recibidos por el SaaS
CREATE TABLE saas_pagos (
id SERIAL PRIMARY KEY,
factura_id INTEGER NOT NULL,
numero_recibo VARCHAR(30) UNIQUE NOT NULL,
fecha_pago TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
valor_abonado NUMERIC(12,2) NOT NULL,
forma_pago VARCHAR(30) NOT NULL, -- TRANSFERENCIA, TARJETA_CREDITO, PASARELA (Stripe/Wompi), etc.
referencia_pasarela VARCHAR(100),
banco_origen VARCHAR(50),
usuario_registro VARCHAR(50) NOT NULL,
CONSTRAINT fk_pago_factura FOREIGN KEY (factura_id) REFERENCES saas_facturas(id)
);
CREATE INDEX idx_pagos_factura ON saas_pagos(factura_id);
