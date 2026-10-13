-- Crea las bases y los roles de desarrollo local de LabLineaWeb.
-- Se ejecuta UNA vez con un superusuario (ver README.md, sección "Base de datos local").
-- Las contraseñas llegan como variables de psql: -v owner_pw=... -v app_pw=... -v plataforma_pw=...
--
-- Roles (spec infraestructura/0007):
--   lablinea_owner: dueño de los esquemas; solo para migraciones (Alembic).
--   lablinea_app:   rol de la aplicación; sin privilegios de dueño ni BYPASSRLS,
--                   para que las políticas RLS siempre se apliquen.
--   lablinea_plataforma: rol del Admin Hub; solo el esquema plataforma, sin acceso a lab.

\set ON_ERROR_STOP on

SELECT format('CREATE ROLE lablinea_owner LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS', :'owner_pw')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'lablinea_owner')
\gexec

SELECT format('CREATE ROLE lablinea_app LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS', :'app_pw')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'lablinea_app')
\gexec

SELECT format('CREATE ROLE lablinea_plataforma LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS', :'plataforma_pw')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'lablinea_plataforma')
\gexec

-- Si los roles ya existían, se alinean las contraseñas con el .env actual.
ALTER ROLE lablinea_owner PASSWORD :'owner_pw';
ALTER ROLE lablinea_app PASSWORD :'app_pw';
ALTER ROLE lablinea_plataforma PASSWORD :'plataforma_pw';

SELECT 'CREATE DATABASE lablinea_dev OWNER lablinea_owner ENCODING ''UTF8'' TEMPLATE template0'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'lablinea_dev')
\gexec

SELECT 'CREATE DATABASE lablinea_test OWNER lablinea_owner ENCODING ''UTF8'' TEMPLATE template0'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'lablinea_test')
\gexec

-- La aplicación solo puede conectarse; los permisos sobre tablas los otorgan las migraciones.
REVOKE ALL ON DATABASE lablinea_dev FROM PUBLIC;
REVOKE ALL ON DATABASE lablinea_test FROM PUBLIC;
GRANT CONNECT ON DATABASE lablinea_dev TO lablinea_app;
GRANT CONNECT ON DATABASE lablinea_test TO lablinea_app;
GRANT CONNECT ON DATABASE lablinea_dev TO lablinea_plataforma;
GRANT CONNECT ON DATABASE lablinea_test TO lablinea_plataforma;

\echo 'Listo: roles lablinea_owner, lablinea_app y lablinea_plataforma; bases lablinea_dev y lablinea_test.'
