# Daily

Bitácora diaria de avances y decisiones. La entrada más reciente va arriba.

Las decisiones relevantes se formalizan después como spec en `infraestructura/` o `funcional/`.

<!--
Plantilla:

## AAAA-MM-DD

**Avances**
-

**Decisiones**
-

**Bloqueos / pendientes**
-
-->

## 2026-10-12

**Avances**
- Carpeta local conectada al repositorio `juanotalora-predizer/LabLineaWeb` (rama `main`).
- Creada la carpeta `specs/` con subcarpetas `infraestructura/` y `funcional/`, plantilla de decisiones, `backlog.md` y `daily.md`.
- Estructura base de la aplicación: `app/main.py`, plantillas `base.html` e `index.html`, CSS, endpoint `/health` y 3 pruebas con pytest (pasan).

- **Sprint 0 completado:** `app/core/config.py` (settings desde `.env`), `app/core/db.py` (`sesion_tenant` fija tenant, usuario e IP con `set_config(..., true)`), Alembic asíncrono con la migración `0001` (aplicada en `lablinea_dev` y `lablinea_test`, downgrade probado), CI en GitHub Actions con PostgreSQL 18. 11 pruebas pasan, incluida la que demuestra que el tenant no se filtra al reutilizar una conexión del pool.
- Se comprobó a mano que el guardián de RLS falla con una tabla sin RLS y con RLS sin `FORCE`.

- **Etapa 0 cerrada** ([informe](etapas/etapa-00.md)): herramientas de calidad y seguridad (ruff, bandit, pip-audit, gitleaks, schemathesis, ZAP 2.17 sobre OpenJDK 21), HTTPS local con mkcert en `*.lablinea.localhost`, cabeceras de seguridad, `scripts/verificar.sh` en local y CI. 45 pruebas, cobertura 100%, ZAP 0 altos/medios/bajos.
- Hallazgo de seguridad en pruebas manuales: cabecera `Host` ajena reflejada en redirecciones; corregido con `TrustedHostMiddleware` y pruebas de regresión.

- **Etapa 1 cerrada** ([informe](etapas/etapa-01.md)): rol `lablinea_plataforma`, migración 0002 (monedas, países, tipos de documento, laboratorios, `acceso.resolver_laboratorio`), resolución del laboratorio por subdominio. 122 pruebas, cobertura 100%, ZAP sin hallazgos; 600 peticiones concurrentes entre laboratorios sin cruces.
- El rol `lablinea_metricas` (con `BYPASSRLS`) se pospone a las etapas 15–16 por mínimo privilegio.

**Decisiones**
- Las decisiones de infraestructura y funcionales se registran en `specs/`, un archivo por decisión.
- Stack base: FastAPI + Jinja2 con renderizado en servidor ([infraestructura/0001](infraestructura/0001-stack-fastapi-jinja2.md)).
- `CLAUDE.md` en la raíz con las reglas para cumplir las specs.
- Los datos reales de pacientes no se versionan; `Synlab_resultados.pdf` queda en `.gitignore`.
- Interoperabilidad con HL7 FHIR R4, terminologías LOINC/UCUM ([infraestructura/0002](infraestructura/0002-interoperabilidad-hl7-fhir.md)).
- Seguridad de la información según HIPAA Security Rule, con todos los controles técnicos como obligatorios ([infraestructura/0003](infraestructura/0003-seguridad-hipaa.md)).

- Operación en Colombia con alcance Latinoamérica: Ley 1581 de 2012 e IHCE (Ley 2015 de 2020, Res. 866 de 2021) como obligación legal; HIPAA como marco de controles; configuración por país para la expansión ([infraestructura/0004](infraestructura/0004-normativa-colombia-latam.md)).

- Cambio de alcance: LabLineaWeb es un **LIS en modalidad SaaS**, multi-laboratorio, que inicia en Colombia con alcance Latinoamérica ([funcional/0001](funcional/0001-producto-lis-saas.md)).
- Arquitectura multi-tenant: tenant = laboratorio, base compartida con `tenant_id` y seguridad a nivel de fila, celdas regionales ([infraestructura/0005](infraestructura/0005-arquitectura-saas-multitenant.md)).
- Integración: FHIR como modelo interno, HL7 v2.5.1 soportado para HIS de clientes, conector local para equipos de análisis ([infraestructura/0006](infraestructura/0006-integracion-his-equipos.md), modifica el punto 8 de 0002).
- Rol legal: el laboratorio es Responsable del tratamiento y LabLineaWeb es Encargado (Ley 1581) y *Business Associate* (HIPAA).

- La descripción funcional del sistema está en cuadernos de NotebookLM; sus fuentes se copiarán a `specs/fuentes/` para convertirlas en specs funcionales.

- Se leyeron las 27 fuentes de NotebookLM (descripción de la migración de Lablinea, en Access, a SaaS) y se convirtieron en specs funcionales 0002 a 0007 e infraestructura 0007 (PostgreSQL con RLS) y 0008 (autenticación).
- Conflictos con las fuentes resueltos: se mantiene **Jinja2 + htmx + Chart.js** (no React); el correo **solo avisa y enlaza al portal**, sin PDF adjunto.
- Migración desde Lablinea: **solo el catálogo**; no pacientes ni resultados históricos.
- **MVP = fases 1 a 5** del plan de desarrollo + cumplimiento; inventarios, costeo y dashboard después ([funcional/0007](funcional/0007-alcance-mvp.md)).
- Ajustes técnicos a las fuentes: RLS con `FORCE`, `WITH CHECK` y `SET LOCAL`; UUID públicos; auditoría con antes y después protegida como dato clínico; agrupación de tubos también por tipo de tubo; impresión con QZ Tray (no por IP desde la nube); valores críticos comunicados aunque haya saldo pendiente.

- Plan de desarrollo ([plan-desarrollo.md](plan-desarrollo.md)): Tenant App y Admin Hub como dos sub-aplicaciones por host en un solo despliegue; 4 roles de base de datos; métricas del Admin Hub por agregados sin datos clínicos; 15 sprints en 4 fases; arquitectura de plantillas PDF.
- Preparado `scripts/crear_bd_local.sql`, `.env.example` y `.env` local para PostgreSQL 18 (EDB).
- **Decisiones del usuario:** dominio `lablinea.cionetworks.com` (laboratorios en `<lab>.lablinea.cionetworks.com`, cookies `__Host-`); sin comisiones en el Admin Hub; facturación electrónica directa con la DIAN y tercero por país si no hay API ([infraestructura/0009](infraestructura/0009-facturacion-electronica.md)); marca H/L opcional en el PDF; dashboard interactivo completo en el MVP.
- Propuesta de bodega analítica separada con replicación lógica, datamarts de laboratorio (RLS), país y plataforma, y pacientes seudonimizados ([infraestructura/0010](infraestructura/0010-analitica-bodega-datos.md), pendiente de aprobación).
- La hoja de ruta pasa de 15 a 20 sprints.
- **Bluehost descartado como hosting de la aplicación:** no firma BAA y sus términos prohíben alojar información de salud protegida.

- Comparación de costos Google Cloud vs Azure (≈ USD 575 vs 600–700/mes en producción; diferencia principal: WAF).
- **Decisión:** construir y probar todo en local; el hosting se decide antes de publicar.
- Plan reescrito como plan paso a paso de 21 etapas (0 a 20); ninguna etapa se cierra sin la compuerta de calidad funcional, de seguridad interna y externa, y su informe ([infraestructura/0011](infraestructura/0011-calidad-pruebas-entorno-local.md)). La etapa 0 queda abierta hasta pasar esa compuerta.

**Bloqueos / pendientes**
- Elegir hosting con BAA (antes de la etapa 20).
- Aprobar la spec 0010 y decidir si inventarios y costeo entran al MVP.
- Validar la spec 0004 con asesoría legal.
