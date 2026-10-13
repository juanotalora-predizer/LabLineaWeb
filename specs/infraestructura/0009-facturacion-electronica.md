# 0009. Facturación electrónica por país

- **Estado:** Aceptada
- **Fecha:** 2026-10-12
- **Responsable:** Juan Otálora
- **Resuelve:** pendientes de [funcional/0002](../funcional/0002-pos-ordenes-caja.md) (ventas del POS) y [funcional/0005](../funcional/0005-plataforma-saas-suscripciones.md) (facturas de la plataforma)

## Contexto

En Colombia, las ventas de los laboratorios (a particulares, empresas y aseguradoras) y las facturas de la plataforma a los laboratorios deben expedirse como documentos electrónicos validados por la DIAN. En otros países de la región hay esquemas propios, y en algunos la ley exige pasar por un intermediario autorizado.

## Decisión

### 1. Interfaz única por país

El LIS define una interfaz `FacturadorElectronico` (emitir factura, documento equivalente POS, nota crédito, nota débito; consultar estado; obtener representación gráfica). Cada país tiene su implementación, elegida por la configuración del país del tenant ([0004](0004-normativa-colombia-latam.md)):

| País | Implementación |
|------|---------------|
| **Colombia** | **Integración directa con los servicios web de la DIAN** |
| Otros | Conector a un tercero autorizado del país cuando no haya API directa disponible o la ley exija intermediario (p. ej. en México los CFDI se timbran a través de un PAC). Se define en la spec de cada país |

### 2. Colombia: integración directa con la DIAN

- Generación de documentos en el formato XML **UBL 2.1** según el anexo técnico vigente de la DIAN, con su código único (CUFE o CUDE), código QR y representación gráfica en PDF.
- **Firma digital** de cada documento con el certificado del **emisor**: cada laboratorio necesita su propio certificado digital de una entidad acreditada por la ONAC. La plataforma usa el suyo para sus propias facturas.
- Envío al servicio web de la DIAN, procesamiento de la respuesta y reintentos con la cola de tareas. El documento no se entrega al cliente hasta que la DIAN lo valida.
- Documentos: factura electrónica de venta, **documento equivalente electrónico POS** (ventas en ventanilla a consumidores), notas crédito y débito.
- **Habilitación:** cada laboratorio pasa el proceso de habilitación ante la DIAN con el software de LabLineaWeb asociado a su NIT (Resolución 165 de 2023). El LIS guía al laboratorio con el set de pruebas.
- **Sector salud:** las facturas a aseguradoras y entidades del sistema de salud deben ir acompañadas de los **RIPS** en el formato vigente. El modelo de datos lo prevé desde el inicio (CUPS por examen, autorización, convenio).
- Numeración: rangos autorizados por la DIAN por laboratorio, con alerta antes de agotarse o vencer.

### 3. Seguridad

- Los certificados digitales (archivos `.p12` y sus claves) se guardan en un **gestor de secretos**, nunca en la base de datos ni en el repositorio, y solo los usa el trabajador de tareas.
- Toda emisión, rechazo y nota queda en la auditoría.
- Una factura validada por la DIAN es inmutable; las correcciones se hacen con notas crédito o débito.

## Alternativas consideradas

- **Proveedor tecnológico en Colombia (Siigo, Alegra, Carvajal…):** menos desarrollo y sin habilitación propia, pero con costo por documento, dependencia de un tercero y sin control del flujo.
- **Que cada laboratorio facture con su propio sistema:** reduce el alcance, pero rompe el flujo del POS y deja al LIS sin la información financiera completa para el dashboard.

## Consecuencias

- La facturación electrónica entra al MVP y agrega dos sprints (ver [plan](../plan-desarrollo.md)).
- **Pendiente de verificar antes de construir:** versión vigente del anexo técnico de la DIAN (caja de herramientas de la DIAN) y del formato RIPS; si la plataforma debe además habilitarse como proveedor tecnológico al emitir en nombre de varios laboratorios. Lo confirma el asesor tributario.
- Cada laboratorio debe tramitar su certificado digital y su habilitación antes de facturar desde el LIS: es un paso del alta del laboratorio.
