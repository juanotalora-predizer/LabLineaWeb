SaaS Roles

-- Usuarios Administradores del SaaS (Globales)
CREATE TABLE saas_usuarios (
id SERIAL PRIMARY KEY,
email VARCHAR(100) UNIQUE NOT NULL,
password_hash VARCHAR(255) NOT NULL,
nombres VARCHAR(50) NOT NULL,
apellidos VARCHAR(50) NOT NULL,
activo BOOLEAN DEFAULT TRUE,
fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Roles del Super Administrador (Ej: Master Admin, Soporte Financiero, Gerente Comercial)
CREATE TABLE saas_roles (
id SERIAL PRIMARY KEY,
nombre VARCHAR(50) UNIQUE NOT NULL,
descripcion VARCHAR(100)
);

-- Relación Usuarios Admin x Roles
CREATE TABLE saas_usuario_roles (
usuario_id INTEGER NOT NULL,
rol_id INTEGER NOT NULL,
PRIMARY KEY (usuario_id, rol_id),
CONSTRAINT fk_sur_usuario FOREIGN KEY (usuario_id) REFERENCES saas_usuarios(id) ON DELETE CASCADE,
CONSTRAINT fk_sur_rol FOREIGN KEY (rol_id) REFERENCES saas_roles(id) ON DELETE CASCADE
);

-- Módulos del Panel de Administración del SaaS
CREATE TABLE saas_modulos (
codigo VARCHAR(50) PRIMARY KEY,
nombre VARCHAR(50) NOT NULL,
descripcion VARCHAR(100)
);

-- Permisos CRUD por Rol y Módulo SaaS
CREATE TABLE saas_rol_modulos (
rol_id INTEGER NOT NULL,
modulo_codigo VARCHAR(50) NOT NULL,
perm_select BOOLEAN DEFAULT FALSE,
perm_insert BOOLEAN DEFAULT FALSE,
perm_update BOOLEAN DEFAULT FALSE,
perm_delete BOOLEAN DEFAULT FALSE,
PRIMARY KEY (rol_id, modulo_codigo),
CONSTRAINT fk_srm_rol FOREIGN KEY (rol_id) REFERENCES saas_roles(id) ON DELETE CASCADE,
CONSTRAINT fk_srm_modulo FOREIGN KEY (modulo_codigo) REFERENCES saas_modulos(codigo) ON DELETE CASCADE
);
