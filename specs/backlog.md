# Backlog

Tareas pendientes del proyecto LabLineaWeb, organizadas según el [alcance del MVP](funcional/0007-alcance-mvp.md). Se construye en orden de fase; dentro de cada fase, por prioridad.

Formato: `- [ ] Descripción — prioridad (Alta/Media/Baja) — spec relacionada si aplica`

## En curso

- [ ] Etapa 3: auditoría de datos (triggers con antes y después, lecturas), cola de tareas, i18n y generador de datos sintéticos — Alta — [plan](plan-desarrollo.md)

## Pendiente

### Decisiones por tomar

- [ ] **Hosting de la aplicación y las bases** (Bluehost queda descartado para datos de salud: no firma BAA y lo prohíbe en sus términos; el dominio y el DNS pueden seguir en Bluehost) — Media, antes de la etapa 20 (publicación); se construye y prueba en local hasta entonces — [0003](infraestructura/0003-seguridad-hipaa.md), [0007](infraestructura/0007-base-de-datos.md), [0010](infraestructura/0010-analitica-bodega-datos.md)
- [ ] Aprobar la arquitectura analítica propuesta (bodega separada con replicación lógica) — Alta — [0010](infraestructura/0010-analitica-bodega-datos.md)
- [ ] ¿Inventarios, equipos y costeo en el MVP? (sin ellos el dashboard no puede mostrar rentabilidad por costo real) — Media — [funcional/0006](funcional/0006-gestion-inventarios-costos-dashboard.md)
- [ ] Elegir librería de cola de trabajos sobre PostgreSQL (spec en la etapa 3) — Media — [plan](plan-desarrollo.md)
- [ ] Confirmar licencia de QZ Tray para impresión de etiquetas — Media — [funcional/0003](funcional/0003-muestras-impresion.md)
- [ ] Mecanismo de firma electrónica del informe PDF (Ley 527 de 1999) — Media — [funcional/0004](funcional/0004-resultados-validacion-entrega.md)

### Fase 1 — Base multi-tenant

- [ ] RLS en todas las tablas de `lab` con `USING` + `WITH CHECK` + `FORCE`, rol de aplicación sin privilegios, `SET LOCAL` por transacción, y prueba que verifique todas las tablas — Alta — [0007](infraestructura/0007-base-de-datos.md)
- [ ] Laboratorios, sedes y estaciones de trabajo — Alta — [funcional/0005](funcional/0005-plataforma-saas-suscripciones.md), [funcional/0003](funcional/0003-muestras-impresion.md)
- [ ] Configuración por país: impuestos, medios de pago y textos legales (monedas, tipos de documento, idioma y zona horaria ya están, etapa 1) — Alta — [0004](infraestructura/0004-normativa-colombia-latam.md)
- [ ] Catálogo de exámenes: secciones, parámetros, unidades, listas de valores, técnica, requisitos de muestra, tarifas, códigos CUPS y alternos — Alta — [funcional/0004](funcional/0004-resultados-validacion-entrega.md), [funcional/0003](funcional/0003-muestras-impresion.md)
- [ ] Rangos de referencia por sexo y edad en días, con rangos críticos — Alta — [funcional/0004](funcional/0004-resultados-validacion-entrega.md)
- [ ] Importador del catálogo de Lablinea (Access) con vista previa y marcado de rangos para revisión — Alta — [funcional/0007](funcional/0007-alcance-mvp.md)
- [ ] Licencias, listas de precios, campañas y suscripciones; bloqueo de órdenes nuevas con suscripción vencida — Media — [funcional/0005](funcional/0005-plataforma-saas-suscripciones.md)
- [ ] Facturas de la plataforma con registro manual de pagos — Media — [funcional/0005](funcional/0005-plataforma-saas-suscripciones.md)
- [ ] Externalizar textos de plantillas para i18n (`es-CO`) y fechas en UTC — Media — [0004](infraestructura/0004-normativa-colombia-latam.md)
- [ ] Generador de datos sintéticos — Media — [0003](infraestructura/0003-seguridad-hipaa.md)
- [ ] Incorporar htmx y Chart.js como estáticos propios — Baja — [0001](infraestructura/0001-stack-fastapi-jinja2.md)

### Fase 2 — Seguridad

- [ ] Recuperación de contraseña por enlace de un solo uso — Media — [0008](infraestructura/0008-autenticacion-autorizacion.md)
- [ ] Código QR para inscribir la app autenticadora — Baja — [0008](infraestructura/0008-autenticacion-autorizacion.md)
- [ ] Administración de usuarios y roles desde la interfaz del laboratorio — Media — [0008](infraestructura/0008-autenticacion-autorizacion.md)

- [ ] Usuarios y roles de la plataforma; acceso de soporte autorizado y auditado — Media — [funcional/0005](funcional/0005-plataforma-saas-suscripciones.md), [0005](infraestructura/0005-arquitectura-saas-multitenant.md)
- [ ] Auditoría: triggers de escritura con antes y después, auditoría de lecturas desde la aplicación, tabla de solo inserción particionada — Alta — [0007](infraestructura/0007-base-de-datos.md)

### Fase 3 — POS y caja

- [ ] Pacientes con identificación por documento y país, y autorización de tratamiento de datos (Ley 1581) al registrarlos — Alta — [funcional/0002](funcional/0002-pos-ordenes-caja.md), [0004](infraestructura/0004-normativa-colombia-latam.md)
- [ ] Gestión de derechos del titular: consultar, actualizar, rectificar, suprimir y revocar — Alta — [0004](infraestructura/0004-normativa-colombia-latam.md)
- [ ] Órdenes con estados `BORRADOR` → `PRE_CERRADA` → `PAGADA` / `ANULADA`, congelamiento de precios y trigger de protección — Alta — [funcional/0002](funcional/0002-pos-ordenes-caja.md)
- [ ] Convenios con tope de descuento, autorización superior y evidencia obligatoria — Alta — [funcional/0002](funcional/0002-pos-ordenes-caja.md)
- [ ] Paquetes de exámenes con comparativo de ahorro y desglose al pre-cerrar — Media — [funcional/0002](funcional/0002-pos-ordenes-caja.md)
- [ ] Sesiones de caja: apertura con base, pagos por forma de pago, abonos, arqueo y cierre — Alta — [funcional/0002](funcional/0002-pos-ordenes-caja.md)
- [ ] Almacenamiento privado de archivos con URL firmada (evidencias) — Alta — [0007](infraestructura/0007-base-de-datos.md)

### Facturación electrónica (etapas 10 y 11)

- [ ] Interfaz `FacturadorElectronico` por país — Alta — [0009](infraestructura/0009-facturacion-electronica.md)
- [ ] Colombia: UBL 2.1, CUFE/CUDE, QR, firma con certificado del laboratorio desde el gestor de secretos, envío a la DIAN con reintentos — Alta — [0009](infraestructura/0009-facturacion-electronica.md)
- [ ] Factura electrónica, documento equivalente POS, notas crédito y débito — Alta — [0009](infraestructura/0009-facturacion-electronica.md)
- [ ] RIPS para facturas a aseguradoras — Alta — [0009](infraestructura/0009-facturacion-electronica.md)
- [ ] Rangos de numeración con alertas y asistente de habilitación del laboratorio — Media — [0009](infraestructura/0009-facturacion-electronica.md)
- [ ] Facturas de la plataforma a los laboratorios con la misma integración — Media — [0009](infraestructura/0009-facturacion-electronica.md)

### Fase 4 — Muestras

- [ ] Algoritmo de agrupación de tubos por tipo de muestra y tipo de tubo — Alta — [funcional/0003](funcional/0003-muestras-impresion.md)
- [ ] Códigos de barras por tubo y estados de la muestra con trazabilidad — Alta — [funcional/0003](funcional/0003-muestras-impresion.md)
- [ ] Cola de toma de muestras por sede con actualización en vivo — Alta — [funcional/0003](funcional/0003-muestras-impresion.md)
- [ ] Generación de etiquetas ZPL e impresión con QZ Tray — Alta — [funcional/0003](funcional/0003-muestras-impresion.md)

### Fase 5 — Resultados

- [ ] Ingreso de resultados con evaluación automática de banderas y notas internas — Alta — [funcional/0004](funcional/0004-resultados-validacion-entrega.md)
- [ ] Resultados de solo inserción con versiones de corrección — Alta — [funcional/0004](funcional/0004-resultados-validacion-entrega.md), [0007](infraestructura/0007-base-de-datos.md)
- [ ] Valores críticos: aviso inmediato y registro de comunicación, independiente de cartera — Alta — [funcional/0004](funcional/0004-resultados-validacion-entrega.md)
- [ ] Validación por examen con tarjeta profesional — Alta — [funcional/0004](funcional/0004-resultados-validacion-entrega.md)
- [ ] Informe PDF con WeasyPrint, personalizable por laboratorio, con marca H/L opcional y hash SHA-256 — Alta — [funcional/0004](funcional/0004-resultados-validacion-entrega.md)
- [ ] Firma electrónica o digital del informe (Ley 527 de 1999) — Alta — [0004](infraestructura/0004-normativa-colombia-latam.md)
- [ ] Regla de liberación (saldo cero o autorización de convenio) — Alta — [funcional/0004](funcional/0004-resultados-validacion-entrega.md)
- [ ] Portal de pacientes y médicos con descarga del PDF y gráficas de tendencia — Alta — [funcional/0004](funcional/0004-resultados-validacion-entrega.md)
- [ ] Aviso por correo sin datos clínicos con enlace al portal — Alta — [funcional/0004](funcional/0004-resultados-validacion-entrega.md)
- [ ] Mapeo del modelo a recursos FHIR R4 con pruebas de validación — Media — [0002](infraestructura/0002-interoperabilidad-hl7-fhir.md)

### Analítica y dashboards (etapas 15 a 18)

- [ ] Instancia analítica, replicación lógica con columnas sin datos personales, seudónimos de pacientes — Alta — [0010](infraestructura/0010-analitica-bodega-datos.md)
- [ ] Modelo estrella y datamarts de laboratorio (RLS), país y plataforma; transformaciones incrementales — Alta — [0010](infraestructura/0010-analitica-bodega-datos.md)
- [ ] Dashboard interactivo del laboratorio (filtros, comparativos, mapa de calor, desglose, tiempos de respuesta, antifraude) — Alta — [funcional/0006](funcional/0006-gestion-inventarios-costos-dashboard.md)
- [ ] Dashboard del Admin Hub (MRR/ARR, laboratorios, volumen por país, salud del sistema) — Alta — [funcional/0005](funcional/0005-plataforma-saas-suscripciones.md)

### Después del MVP

- [ ] Inventarios, equipos, costeo por actividad y nómina ligera (pendiente de decidir si entran al MVP) — [funcional/0006](funcional/0006-gestion-inventarios-costos-dashboard.md)
- [ ] Pasarela de pagos del SaaS con webhooks firmados e idempotentes — [funcional/0005](funcional/0005-plataforma-saas-suscripciones.md)
- [ ] API FHIR bajo `/fhir` con OAuth 2.0 / SMART on FHIR — [0002](infraestructura/0002-interoperabilidad-hl7-fhir.md)
- [ ] Perfiles FHIR de la IHCE (MinSalud, Res. 866 de 2021) y códigos LOINC del catálogo — [0004](infraestructura/0004-normativa-colombia-latam.md)
- [ ] Mensajería HL7 v2.5.1 con HIS de clientes — [0006](infraestructura/0006-integracion-his-equipos.md)
- [ ] Conector local para equipos de análisis (y evaluar mover la impresión a él) — [0006](infraestructura/0006-integracion-his-equipos.md)
- [ ] Control de calidad (Westgard, Levey-Jennings) — [funcional/0001](funcional/0001-producto-lis-saas.md)
- [ ] Reporte a SIVIGILA — [0004](infraestructura/0004-normativa-colombia-latam.md)
- [ ] Exportación y supresión de datos de un laboratorio al terminar el contrato — [0004](infraestructura/0004-normativa-colombia-latam.md)
- [ ] Límites de uso por tenant — [0005](infraestructura/0005-arquitectura-saas-multitenant.md)
- [ ] Spec de normativa por cada país adicional — [0004](infraestructura/0004-normativa-colombia-latam.md)

### Legal y organizacional

- [ ] Asesoría tributaria: anexo técnico vigente de la DIAN, formato RIPS y si la plataforma debe habilitarse como proveedor tecnológico — Alta — [0009](infraestructura/0009-facturacion-electronica.md)
- [ ] Asesoría legal: validar spec 0004, plazo de conservación, RNBD, país de hosting, dispositivo médico (INVIMA) y **retención de resultados por cartera** — Alta — [0004](infraestructura/0004-normativa-colombia-latam.md), [funcional/0004](funcional/0004-resultados-validacion-entrega.md)
- [ ] Modelos de contrato con laboratorios: contrato de transmisión de datos (Ley 1581) y BAA (HIPAA) — Alta — [0003](infraestructura/0003-seguridad-hipaa.md), [0004](infraestructura/0004-normativa-colombia-latam.md)
- [ ] Análisis de riesgos, políticas, oficial de seguridad, capacitación, notificación de brechas — Media — [0003](infraestructura/0003-seguridad-hipaa.md)

## Hecho

- [x] **Etapa 2 cerrada** — autenticación y autorización: Argon2id, TOTP y código por correo, sesiones `__Host-`, CSRF, bloqueos, roles y permisos; 226 pruebas (5 en Chromium), cobertura 99%, ZAP autenticado sin hallazgos, 3 errores encontrados por las pruebas y corregidos — 2026-10-12 — [informe](etapas/etapa-02.md)

- [x] **Etapa 1 cerrada** — base multi-tenant: rol de plataforma, catálogos globales, laboratorios, resolución por subdominio; 122 pruebas, cobertura 100%, ZAP sin hallazgos, 600 peticiones concurrentes sin cruces — 2026-10-12 — [informe](etapas/etapa-01.md)

- [x] Decisión: construir y probar en local; publicación después. Plan paso a paso con compuerta de calidad por etapa — 2026-10-12 — [0011](infraestructura/0011-calidad-pruebas-entorno-local.md), [plan](plan-desarrollo.md)

- [x] Decisiones: dominio `lablinea.cionetworks.com`, sin comisiones, facturación electrónica directa con la DIAN, marca H/L opcional en el PDF, dashboard completo en el MVP — 2026-10-12 — [0009](infraestructura/0009-facturacion-electronica.md), [0010](infraestructura/0010-analitica-bodega-datos.md)

- [x] **Etapa 0 cerrada** con compuerta completa: 45 pruebas, cobertura 100%, ZAP sin hallazgos altos/medios/bajos, hallazgo de cabecera `Host` corregido — 2026-10-12 — [informe](etapas/etapa-00.md)
- [x] Etapa 0 (código inicial): configuración por `.env`, conexión con tenant por transacción (`SET LOCAL`), Alembic con migración 0001 (esquemas `plataforma`, `global`, `lab`; función `lab.tenant_actual()`; permisos por defecto), guardián de RLS y CI con PostgreSQL 18 — 2026-10-12 — [0007](infraestructura/0007-base-de-datos.md)
- [x] Roles y bases locales creados (PostgreSQL 18.6) — 2026-10-12 — [0007](infraestructura/0007-base-de-datos.md)

- [x] Fuentes de NotebookLM convertidas en specs: funcionales 0002 a 0007 e infraestructura 0007 y 0008; MVP definido — 2026-10-12 — [funcional/0007](funcional/0007-alcance-mvp.md)
- [x] Copiar las fuentes de los cuadernos de NotebookLM a `specs/fuentes/` — 2026-10-12
- [x] Definición del producto como LIS SaaS, arquitectura multi-tenant e integración con HIS y equipos — 2026-10-12 — [funcional/0001](funcional/0001-producto-lis-saas.md), [0005](infraestructura/0005-arquitectura-saas-multitenant.md), [0006](infraestructura/0006-integracion-his-equipos.md)
- [x] Spec de normativa Colombia y estrategia Latinoamérica — 2026-10-12 — [0004](infraestructura/0004-normativa-colombia-latam.md)
- [x] Specs de cumplimiento HL7 FHIR y HIPAA, reglas en `CLAUDE.md` — 2026-10-12 — [0002](infraestructura/0002-interoperabilidad-hl7-fhir.md), [0003](infraestructura/0003-seguridad-hipaa.md)
- [x] Crear `CLAUDE.md` con reglas de cumplimiento de specs — 2026-10-12
- [x] Estructura base de la aplicación con FastAPI + Jinja2 — 2026-10-12 — [infraestructura/0001](infraestructura/0001-stack-fastapi-jinja2.md)
- [x] Conectar carpeta local con el repositorio de GitHub — 2026-10-12
- [x] Crear estructura de `specs/` para registrar decisiones — 2026-10-12
