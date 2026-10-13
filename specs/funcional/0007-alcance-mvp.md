# 0007. Alcance del MVP

- **Estado:** Aceptada
- **Fecha:** 2026-10-12
- **Responsable:** Juan Otálora
- **Fuentes:** [21 Plan de desarrollo](../fuentes/), [02 DDL original](../fuentes/)

## Contexto

El plan de desarrollo (fuente 21) define seis fases. El producto completo es grande; el MVP debe permitir que un laboratorio opere su flujo diario de punta a punta: recibir al paciente, cobrar, tomar muestras, ingresar y validar resultados, y entregarlos. Además, Lablinea es un sistema heredado en Access cuyo catálogo de exámenes es valioso.

## Decisión

### El MVP incluye las fases 1 a 5 del plan, más el cumplimiento obligatorio

| Fase | Contenido | Specs |
|------|-----------|-------|
| **1. Base multi-tenant** | PostgreSQL con RLS, laboratorios, sedes, estaciones de trabajo, configuración por país, catálogo de exámenes, licencias y suscripciones, **importador del catálogo de Lablinea** | [infra/0005](../infraestructura/0005-arquitectura-saas-multitenant.md), [infra/0007](../infraestructura/0007-base-de-datos.md), [0005](0005-plataforma-saas-suscripciones.md) |
| **2. Seguridad** | Inicio de sesión con segundo factor, roles y permisos, auditoría | [infra/0003](../infraestructura/0003-seguridad-hipaa.md), [infra/0008](../infraestructura/0008-autenticacion-autorizacion.md) |
| **3. POS y caja** | Pacientes, órdenes con pre-cierre, convenios y descuentos, paquetes, caja con arqueo | [0002](0002-pos-ordenes-caja.md) |
| **4. Muestras** | Agrupación de tubos, códigos de barras, cola de toma, impresión ZPL | [0003](0003-muestras-impresion.md) |
| **5. Resultados** | Rangos por sexo y edad, banderas, valores críticos, validación, PDF, portal, aviso por correo | [0004](0004-resultados-validacion-entrega.md) |
| **Facturación electrónica** *(agregado)* | Factura, documento equivalente POS y notas con la DIAN; facturas de la plataforma | [infra/0009](../infraestructura/0009-facturacion-electronica.md) |
| **Dashboard** *(agregado)* | Bodega de datos separada, datamarts y dashboard interactivo completo del laboratorio y del Admin Hub | [0006](0006-gestion-inventarios-costos-dashboard.md), [infra/0010](../infraestructura/0010-analitica-bodega-datos.md) |
| **Cumplimiento** | Autorización de tratamiento de datos (Ley 1581), derechos del titular, cabeceras de seguridad, datos sintéticos | [infra/0003](../infraestructura/0003-seguridad-hipaa.md), [infra/0004](../infraestructura/0004-normativa-colombia-latam.md) |

### Migración: solo el catálogo

Del Lablinea en Access se migra **únicamente el catálogo** de cada laboratorio que lo use. No se migran pacientes, órdenes ni resultados históricos.

| Tabla de Lablinea | Destino |
|-------------------|---------|
| `analisis`, `seccion` | Exámenes y secciones |
| `detalle analisis`, `unidad`, `lista de valores` | Parámetros, unidades y listas de valores |
| `normal de referencia`, `RangoMinimo`, `RangoMaximo` | Rangos de referencia (revisión manual para separarlos por sexo y edad) |
| `tipo muestra`, `muestras x analisis` | Requisitos de muestra (volumen y tubo se completan manualmente) |
| `tipo tarifa`, `costo analisis` | Tipos de tarifa y precios |
| `Codigo Analisis x Empresa`, `CodigoSGSS` | Códigos alternos (CUPS y códigos por convenio) |

- El importador lee una exportación de la base Access, muestra una vista previa con errores y advertencias, y carga en el tenant indicado.
- Los rangos de Lablinea son texto libre o un único mínimo y máximo: el importador los trae como rango "ambos sexos, todas las edades" y los marca para revisión.
- Los códigos LOINC no existen en Lablinea; se asignan después.

### Fuera del MVP

- **Fase 6, salvo el dashboard:** inventarios, equipos, costeo y nómina ligera ([0006](0006-gestion-inventarios-costos-dashboard.md)), pendiente de decisión.
- **Interoperabilidad:** API FHIR pública, mensajería HL7 v2 y conector de equipos ([infra/0002](../infraestructura/0002-interoperabilidad-hl7-fhir.md), [infra/0006](../infraestructura/0006-integracion-his-equipos.md)). El modelo interno sí se diseña desde el MVP con su mapeo a FHIR.
- Control de calidad (Westgard, Levey-Jennings).
- Pasarela de pagos automática del SaaS ([0005](0005-plataforma-saas-suscripciones.md)).
- Reporte a SIVIGILA.

## Alternativas consideradas

- **Plan completo (fases 1 a 6):** retrasa la salida a producción con módulos de gestión que no son necesarios para operar.
- **Solo flujo clínico sin POS:** más pequeño, pero los laboratorios particulares no podrían operar sin cobrar.
- **Migrar también pacientes y resultados históricos:** valioso para los clientes de Lablinea, pero los datos en Access no tienen la calidad ni la estructura necesarias y el riesgo de datos de salud mal migrados es alto.

## Consecuencias

- Orden de construcción: fase 1 → 2 → 3 → 4 → 5; el cumplimiento se construye junto con la fase en la que aparece (p. ej. la autorización de datos con el registro de pacientes).
- *(Modificado el 2026-10-12)* Entran al MVP la facturación electrónica con la DIAN y el dashboard completo con su bodega de datos; la hoja de ruta pasa de 15 a 20 sprints ([plan](../plan-desarrollo.md)).
