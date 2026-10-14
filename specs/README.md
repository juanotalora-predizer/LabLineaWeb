# Specs

Registro de decisiones del proyecto LabLineaWeb.

## Estructura

- [infraestructura/](infraestructura/): hosting, base de datos, despliegue, seguridad, servicios externos.
- [funcional/](funcional/): funcionalidades, flujos de usuario, reglas de negocio.
- [fuentes/](fuentes/): documentos originales de la descripción funcional (exportados de NotebookLM).
- [plan-desarrollo.md](plan-desarrollo.md): arquitectura, esquema de base de datos, estructura del proyecto y hoja de ruta por sprints.
- [etapas/](etapas/): informes de cierre de cada etapa, con la evidencia de sus pruebas.
- [backlog.md](backlog.md): tareas en curso, pendientes y hechas.
- [daily.md](daily.md): bitácora diaria de avances y decisiones.

## Convenciones

- Un archivo por decisión: `NNNN-titulo-corto.md` (ej. `0001-hosting.md`). La numeración es independiente en cada carpeta.
- Se parte de [plantilla.md](plantilla.md).
- Las decisiones no se borran. Si una cambia, se crea una nueva y la anterior pasa a estado `Reemplazada por NNNN`. Si solo cambia una parte, la nueva spec indica `Modifica: punto X de NNNN` y la anterior marca ese punto como modificado.

## Índice

### Infraestructura

| # | Decisión | Estado | Fecha |
|---|----------|--------|-------|
| 0001 | [Stack base: FastAPI + Jinja2](infraestructura/0001-stack-fastapi-jinja2.md) | Aceptada | 2026-10-12 |
| 0002 | [Interoperabilidad: HL7 FHIR R4](infraestructura/0002-interoperabilidad-hl7-fhir.md) | Aceptada | 2026-10-12 |
| 0003 | [Seguridad de la información: HIPAA](infraestructura/0003-seguridad-hipaa.md) | Aceptada | 2026-10-12 |
| 0004 | [Normativa: Colombia como base, alcance Latinoamérica](infraestructura/0004-normativa-colombia-latam.md) | Aceptada | 2026-10-12 |
| 0005 | [Arquitectura SaaS multi-tenant](infraestructura/0005-arquitectura-saas-multitenant.md) | Aceptada | 2026-10-12 |
| 0006 | [Integración con sistemas clínicos y equipos](infraestructura/0006-integracion-his-equipos.md) | Aceptada | 2026-10-12 |
| 0007 | [Base de datos: PostgreSQL con RLS](infraestructura/0007-base-de-datos.md) | Aceptada | 2026-10-12 |
| 0008 | [Autenticación y autorización](infraestructura/0008-autenticacion-autorizacion.md) | Aceptada | 2026-10-12 |
| 0009 | [Facturación electrónica por país](infraestructura/0009-facturacion-electronica.md) | Aceptada | 2026-10-12 |
| 0010 | [Analítica: bodega de datos separada](infraestructura/0010-analitica-bodega-datos.md) | Propuesta | 2026-10-12 |
| 0011 | [Calidad, pruebas y entorno local](infraestructura/0011-calidad-pruebas-entorno-local.md) | Aceptada | 2026-10-12 |
| 0012 | [Cola de tareas en segundo plano sobre PostgreSQL](infraestructura/0012-cola-de-tareas.md) | Aceptada | 2026-10-13 |
| 0013 | [Textos externalizados (i18n) y fechas locales](infraestructura/0013-textos-externalizados-i18n.md) | Aceptada | 2026-10-13 |

### Funcional

| # | Decisión | Estado | Fecha |
|---|----------|--------|-------|
| 0001 | [Producto: LIS en modalidad SaaS](funcional/0001-producto-lis-saas.md) | Aceptada | 2026-10-12 |
| 0002 | [POS, órdenes y caja](funcional/0002-pos-ordenes-caja.md) | Aceptada | 2026-10-12 |
| 0003 | [Muestras, códigos de barras e impresión](funcional/0003-muestras-impresion.md) | Aceptada | 2026-10-12 |
| 0004 | [Resultados: referencias, validación y entrega](funcional/0004-resultados-validacion-entrega.md) | Aceptada | 2026-10-12 |
| 0005 | [Plataforma SaaS: laboratorios, licencias y facturación](funcional/0005-plataforma-saas-suscripciones.md) | Aceptada | 2026-10-12 |
| 0006 | [Gestión: inventarios, costeo y dashboard](funcional/0006-gestion-inventarios-costos-dashboard.md) | Aceptada (dashboard en el MVP) | 2026-10-12 |
| 0007 | [Alcance del MVP](funcional/0007-alcance-mvp.md) | Aceptada | 2026-10-12 |
| 0008 | [Sistema de diseño de la interfaz](funcional/0008-sistema-de-diseno.md) | Aceptada | 2026-10-13 |
| 0009 | [Catálogo de exámenes e importador de Lablinea](funcional/0009-catalogo-e-importador.md) | Aceptada | 2026-10-13 |
| 0010 | [Pacientes, autorización de datos y derechos del titular (Ley 1581)](funcional/0010-pacientes-ley-1581.md) | Aceptada | 2026-10-14 |
