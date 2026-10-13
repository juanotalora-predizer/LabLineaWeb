# LabLineaWeb
Laboratorio en Linea Web

Sistema de información de laboratorio clínico (LIS) en modalidad SaaS. Inicia en Colombia con alcance Latinoamérica. Construido con FastAPI y plantillas Jinja2, con interoperabilidad HL7 FHIR y controles de seguridad HIPAA.

## Desarrollo local

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

uvicorn app.main:app --reload   # http://127.0.0.1:8000
pytest                          # pruebas
```

### Base de datos local

Requiere PostgreSQL 16 o superior. Una sola vez:

1. Copiar `.env.example` a `.env` y completar las contraseñas de `DB_OWNER_PASSWORD` y `DB_APP_PASSWORD` (valores aleatorios).
2. Crear roles y bases con un superusuario (pide su contraseña):

```bash
set -a; source .env; set +a
psql -h localhost -U postgres -d postgres \
  -v owner_pw="$DB_OWNER_PASSWORD" -v app_pw="$DB_APP_PASSWORD" \
  -f scripts/crear_bd_local.sql
```

3. Aplicar las migraciones (siempre con el rol dueño, lo toma del `.env`):

```bash
alembic upgrade head                          # base de desarrollo
alembic -x base=lablinea_test upgrade head    # base de prueba (pytest lo hace solo)
```

### Calidad y seguridad (spec infraestructura/0011)

Herramientas del sistema (una vez): `brew install gitleaks mkcert openjdk@21` y OWASP ZAP multiplataforma en `~/herramientas/ZAP_2.17.0` (el cask de Homebrew está deshabilitado).

```bash
scripts/verificar.sh          # ruff, bandit, pip-audit, gitleaks, migraciones, pruebas y cobertura (antes de cada commit)
scripts/servidor_https.sh     # https://lab-a.lablinea.localhost:8443 (también lab-b y admin)
scripts/escaneo_externo.sh    # OWASP ZAP pasivo + activo contra el servidor HTTPS local
```

Certificados locales (una vez; `mkcert -install` hace que el navegador confíe en ellos):

```bash
mkcert -cert-file certs/local.pem -key-file certs/local-key.pem \
  lab-a.lablinea.localhost lab-b.lablinea.localhost admin.lablinea.localhost localhost 127.0.0.1 ::1
```

Las decisiones del proyecto se documentan en [specs/](specs/).
