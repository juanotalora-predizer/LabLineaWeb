# 0002. Interoperabilidad: HL7 FHIR R4

- **Estado:** Aceptada
- **Fecha:** 2026-10-12
- **Responsable:** Juan Otálora

## Contexto

LabLineaWeb debe cumplir la normativa de interoperabilidad HL7, para que los resultados de laboratorio se intercambien con otros sistemas de salud (laboratorios, historias clínicas, aseguradoras) en un formato estándar y no propietario.

HL7 tiene varias familias de estándares. Las dos relevantes para resultados de laboratorio son:

- **HL7 v2** (mensajes `ORU^R01`): el formato más común entre los sistemas de laboratorio (LIS) existentes.
- **HL7 FHIR**: el estándar actual, basado en recursos JSON sobre API REST. Es el que adoptan los marcos regulatorios recientes de interoperabilidad.

## Decisión

1. **Estándar principal: HL7 FHIR R4 (4.0.1).** Todo intercambio de datos clínicos que exponga o consuma la aplicación usa recursos FHIR R4 en JSON (`application/fhir+json`).
2. **API FHIR bajo `/fhir`**, con `CapabilityStatement` en `GET /fhir/metadata` que declare los recursos y operaciones soportados.
3. **Recursos mínimos:**

   | Recurso | Uso |
   |---------|-----|
   | `Patient` | Paciente dueño de los resultados |
   | `Practitioner` / `Organization` | Médico solicitante, laboratorio |
   | `ServiceRequest` | Orden de examen |
   | `Specimen` | Muestra tomada |
   | `Observation` | Cada resultado individual (valor, unidad, rango de referencia, interpretación) |
   | `DiagnosticReport` | Informe que agrupa las observaciones; el PDF firmado va en `presentedForm` |

4. **Terminologías:**
   - **LOINC** para identificar exámenes y analitos (`Observation.code`).
   - **UCUM** para unidades (`Observation.valueQuantity`).
   - **SNOMED CT** para tipo de muestra e interpretaciones cuando aplique.
5. **Modelo interno alineado a FHIR** *(modificado por [0007](0007-base-de-datos.md) y [funcional/0007](../funcional/0007-alcance-mvp.md): se conserva el modelo relacional del dominio de Lablinea, con un mapeo explícito y probado a cada recurso FHIR, en lugar de exigir correspondencia 1 a 1)*: los modelos de datos se diseñan para mapear 1 a 1 con los recursos anteriores; no se crean estructuras propietarias que luego haya que traducir.
6. **Validación:** los recursos se construyen y validan con la librería `fhir.resources` (modelos Pydantic, compatible con FastAPI) antes de exponerse o persistirse.
7. **Seguridad de la API FHIR:** autorización con OAuth 2.0 según SMART on FHIR (scopes por recurso, p. ej. `patient/Observation.read`). Aplica todo lo definido en [0003](0003-seguridad-hipaa.md).
8. **HL7 v2** *(modificado por [0006](0006-integracion-his-equipos.md): LabLineaWeb es el LIS, y HL7 v2 pasa a ser un canal soportado para sistemas de clientes y equipos)*: se recibirá `ORU^R01` solo si el LIS de origen no soporta FHIR. En ese caso se convierte a FHIR en el borde y no se propaga v2 dentro de la aplicación. Queda pendiente hasta conocer el LIS.

## Alternativas consideradas

- **Solo HL7 v2:** compatible con LIS antiguos, pero no es REST, es difícil de exponer a terceros y no es la dirección de la normativa reciente.
- **HL7 CDA:** orientado a documentos clínicos completos; demasiado pesado para resultados individuales y en retirada frente a FHIR.
- **FHIR R5:** más nuevo, pero R4 es la versión con mayor adopción, guías de implementación y soporte en servidores y librerías.

## Consecuencias

- La API FHIR es un requisito funcional: el portal web (Jinja2) y la API FHIR consumen el mismo modelo.
- Cada examen debe tener código LOINC; se necesita una tabla de mapeo de los códigos internos del laboratorio a LOINC.
- Pruebas: cada endpoint FHIR se prueba validando el JSON contra el recurso R4 correspondiente.
- Guía de implementación nacional: resuelto en [0004](0004-normativa-colombia-latam.md). En Colombia aplican la IHCE (Ley 2015 de 2020, Res. 866 de 2021) y sus perfiles FHIR, además de la codificación CUPS. En otros países, los perfiles FHIR nacionales que defina la spec de cada uno.
