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

Las decisiones del proyecto se documentan en [specs/](specs/).
