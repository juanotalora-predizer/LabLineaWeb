Roles y Usuarios
-- Tabla de Usuarios del SaaS (Multi-tenant por relación)
CREATE TABLE usuarios (
id SERIAL PRIMARY KEY,
tenant_id VARCHAR(50) NOT NULL,
email VARCHAR(100) NOT NULL,
password_hash VARCHAR(255) NOT NULL,
nombres VARCHAR(50) NOT NULL,
apellidos VARCHAR(50) NOT NULL,
activo BOOLEAN DEFAULT TRUE,
usuario_digitacion VARCHAR(50),
fecha_digitacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
CONSTRAINT uk_tenant_user_email UNIQUE (tenant_id, email)
);
CREATE INDEX idx_usuarios_tenant ON usuarios(tenant_id);

-- Tabla de Roles (Ej: Administrador, Bacteriólogo, Recepcionista, Auditor)
CREATE TABLE roles (
id SERIAL PRIMARY KEY,
tenant_id VARCHAR(50) NOT NULL,
nombre VARCHAR(50) NOT NULL,
descripcion VARCHAR(100),
CONSTRAINT uk_tenant_rol UNIQUE (tenant_id, nombre)
);

-- Relación Usuarios x Roles (Muchos a Muchos)
CREATE TABLE usuario_roles (
usuario_id INTEGER NOT NULL,
rol_id INTEGER NOT NULL,
PRIMARY KEY (usuario_id, rol_id),
CONSTRAINT fk_ur_usuario FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE,
CONSTRAINT fk_ur_rol FOREIGN KEY (rol_id) REFERENCES roles(id) ON DELETE CASCADE
);

-- Catálogo de Módulos del Sistema (Ej: Pacientes, Órdenes, Facturación, Configuración)
CREATE TABLE modulos (
codigo VARCHAR(50) PRIMARY KEY,
nombre VARCHAR(50) NOT NULL,
descripcion VARCHAR(100)
);

-- Permisos por Rol y Módulo (Select, Insert, Update, Delete)
CREATE TABLE rol_modulos (
rol_id INTEGER NOT NULL,
modulo_codigo VARCHAR(50) NOT NULL,
perm_select BOOLEAN DEFAULT FALSE,
perm_insert BOOLEAN DEFAULT FALSE,
perm_update BOOLEAN DEFAULT FALSE,
perm_delete BOOLEAN DEFAULT FALSE,
PRIMARY KEY (rol_id, modulo_codigo),
CONSTRAINT fk_rm_rol FOREIGN KEY (rol_id) REFERENCES roles(id) ON DELETE CASCADE,
CONSTRAINT fk_rm_modulo FOREIGN KEY (modulo_codigo) REFERENCES modulos(codigo) ON DELETE CASCADE
);
