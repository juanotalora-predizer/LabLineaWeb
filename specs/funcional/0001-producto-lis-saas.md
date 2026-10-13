# 0001. Producto: LIS en modalidad SaaS

- **Estado:** Aceptada
- **Fecha:** 2026-10-12
- **Responsable:** Juan Otálora

## Contexto

LabLineaWeb se planteó inicialmente como un portal web para consultar resultados de laboratorio. El alcance real es mayor: construir un **LIS** (*Laboratory Information System*, sistema de información de laboratorio clínico) que se ofrece a los laboratorios como **SaaS** (*Software as a Service*), con suscripción y sin instalación propia. Inicia en Colombia con alcance Latinoamérica.

## Decisión

LabLineaWeb es un LIS multi-laboratorio en modalidad SaaS. Cada laboratorio cliente es un **tenant** aislado (ver [infraestructura/0005](../infraestructura/0005-arquitectura-saas-multitenant.md)).

### Módulos del producto

| Módulo | Qué cubre |
|--------|-----------|
| **Administración del tenant** | Laboratorio, sedes, usuarios y roles, catálogo de exámenes, configuración por país |
| **Pacientes** | Registro e identificación (tipo y número de documento), autorización de tratamiento de datos |
| **Órdenes** | Recepción de órdenes de examen (manual, desde el HIS del cliente o por API) |
| **Toma y trazabilidad de muestras** | Etiquetas con código de barras, recepción, rechazo, cadena de custodia de la muestra |
| **Procesamiento** | Listas de trabajo por área, interfaz con equipos de análisis, captura manual de resultados |
| **Control de calidad** | Controles internos, reglas de Westgard, gráficas de Levey-Jennings |
| **Validación** | Revisión y firma de resultados por el profesional, valores críticos, delta checks, versiones de correcciones |
| **Informes** | Informe PDF firmado, entrega por portal |
| **Portal de pacientes y médicos** | Consulta segura de resultados (el alcance original de LabLineaWeb) |
| **Interoperabilidad** | API FHIR, mensajería HL7 v2, conector de equipos (ver [infraestructura/0006](../infraestructura/0006-integracion-his-equipos.md)) |
| **Auditoría y cumplimiento** | Registro de auditoría, gestión de derechos del titular, reportes regulatorios |
| **Suscripción** | Planes, alta y baja de laboratorios, uso |
| **POS y caja** *(agregado)* | Pre-cierre de órdenes, convenios y descuentos con evidencia, paquetes, sesiones de caja y arqueo ([0002](0002-pos-ordenes-caja.md)) |
| **Gestión** *(agregado, fuera del MVP)* | Inventarios, equipos, costeo por actividad, dashboard y alertas antifraude ([0006](0006-gestion-inventarios-costos-dashboard.md)) |

### Roles

- **Plataforma:** operador del SaaS (nosotros). No accede a datos clínicos de los tenants salvo soporte autorizado y auditado.
- **Laboratorio:** administrador del laboratorio, recepcionista o flebotomista, bacteriólogo o analista, profesional que valida, director de calidad.
- **Externos:** paciente y médico remitente.

### Referentes de calidad

El software debe facilitar que el laboratorio cumpla **ISO 15189** (requisitos de calidad y competencia de laboratorios clínicos): trazabilidad completa de la muestra, control de calidad, registro de quién validó cada resultado y conservación de registros.

## Alternativas consideradas

- **Solo portal de resultados conectado a LIS de terceros:** producto más pequeño, pero depende de cada LIS y no captura el valor del flujo completo del laboratorio.
- **LIS instalado en cada laboratorio (on-premise):** mayor control del cliente, pero eleva costos de implementación y soporte, y dificulta escalar a Latinoamérica.

## Consecuencias

- La arquitectura es multi-tenant desde el primer día ([infraestructura/0005](../infraestructura/0005-arquitectura-saas-multitenant.md)).
- Los equipos de análisis están en la red local de cada laboratorio, por lo que el SaaS necesita un conector local ([infraestructura/0006](../infraestructura/0006-integracion-his-equipos.md)).
- Cambia el rol legal: el laboratorio es el responsable de los datos y nosotros el encargado (ver [infraestructura/0004](../infraestructura/0004-normativa-colombia-latam.md) y [0003](../infraestructura/0003-seguridad-hipaa.md)).
- Alcance del MVP: definido en [0007](0007-alcance-mvp.md). El detalle de cada módulo está en las specs funcionales 0002 a 0006, construidas a partir de los cuadernos de NotebookLM ([fuentes/](../fuentes/)).
