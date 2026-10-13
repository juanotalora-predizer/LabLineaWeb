# 0004. Resultados: referencias, validación y entrega

- **Estado:** Aceptada
- **Fecha:** 2026-10-12
- **Responsable:** Juan Otálora
- **Fuentes:** [16 Normalidades](../fuentes/), [22 Resultados y delivery](../fuentes/), [25 Revisión formato Synlab](../fuentes/), [05 Diagnóstico inmutable](../fuentes/)

## Contexto

El resultado es el producto clínico del laboratorio. Debe evaluarse contra rangos de referencia adecuados al paciente, ser validado por un profesional identificado, no poder alterarse después y entregarse de forma segura.

## Decisión

### 1. Estructura del examen

- Un **examen** (p. ej. Hemograma) tiene **parámetros** o biomarcadores (hemoglobina, leucocitos…), con unidad, orden de presentación y si son títulos de sección.
- Cada examen tiene una **técnica analítica** por defecto (cronométrica, citometría de flujo, hexoquinasa…), que puede cambiarse en la orden.
- Parámetros de tipo **numérico**, **texto libre** o **lista de valores** (p. ej. "Negativo / Positivo").

### 2. Rangos de referencia

- Por parámetro, varios rangos según **sexo** (M, F o ambos) y **edad en días** (cubre neonatos, niños y adultos).
- Numéricos: mínimo y máximo normales, y además **mínimo y máximo críticos** (valores de pánico). Texto: valor esperado.
- Texto de referencia para el informe (p. ej. "70.0 - 100.0 mg/dL").
- La edad se calcula a la **fecha de toma de la muestra**, desde la fecha de nacimiento; no se guarda la edad como texto.

### 3. Evaluación automática

Al ingresar un valor, el sistema asigna una bandera: `NORMAL`, `BAJO`, `ALTO`, `CRITICO_BAJO`, `CRITICO_ALTO` o `ANORMAL` (texto distinto al esperado), y genera una **nota de alerta interna**.

- **Las banderas y notas internas nunca se muestran al paciente** ni aparecen en el PDF o el correo. Solo las ve el personal del laboratorio.
- *(Modificado el 2026-10-12)* **Marca H/L opcional en el informe:** cada laboratorio puede activar que el PDF y el portal muestren `H` o `L` junto a un valor **numérico** fuera de su rango de referencia. Los valores críticos se marcan igual (`H`/`L`), sin la palabra "crítico". Nunca se muestran la bandera interna, la nota interna ni colores de alerta. Desactivada por defecto.
- Las banderas se mapean a `Observation.interpretation` de FHIR (L, H, LL, HH, A) para interoperabilidad con sistemas clínicos ([infraestructura/0002](../infraestructura/0002-interoperabilidad-hl7-fhir.md)).

### 4. Valores críticos

Un valor `CRITICO_*` dispara un aviso inmediato al validador. El laboratorio debe comunicarlo al médico o paciente y **registrar quién lo comunicó, a quién y cuándo**. Esto aplica **aunque la orden tenga saldo pendiente o le falte autorización**: la retención por cartera nunca bloquea un valor crítico.

### 5. Inmutabilidad y versiones

- Los resultados se guardan en una tabla de **solo inserción**: la base de datos bloquea `UPDATE` y `DELETE` (fuente 05).
- Corregir un valor crea una **nueva versión** que referencia la anterior, con motivo. Se muestra la última versión y se conserva el historial.
- Una corrección después de validar exige **nueva validación** y genera una nota de corrección visible en el informe.

### 6. Validación profesional

- La validación es **por examen**: el profesional revisa y aprueba; queda registro de nombre, número de **tarjeta profesional**, fecha y hora.
- La orden está validada cuando todos sus exámenes lo están; se pueden liberar exámenes parciales.
- Notas técnicas por resultado y observaciones generales aprobadas por el profesional, que sí van en el informe.

### 7. Informe PDF

- Generado desde plantillas Jinja2 (mismo motor de la aplicación) con **WeasyPrint**.
- Personalizable por laboratorio: logo, marca de agua, pie de página, firma del profesional.
- Contiene: datos del paciente y la orden, cada parámetro con valor (con marca H/L si el laboratorio la activó), unidad, rango de referencia aplicable a su edad y sexo, técnica, validador con tarjeta profesional, fecha y hora de validación, observaciones y notas aprobadas.
- Hash SHA-256 del PDF guardado para verificar integridad ([infraestructura/0003](../infraestructura/0003-seguridad-hipaa.md)).
- La imagen de la firma no basta como firma electrónica (Ley 527 de 1999): el mecanismo de firma electrónica se define en la tarea correspondiente ([infraestructura/0004](../infraestructura/0004-normativa-colombia-latam.md)).

### 8. Liberación y entrega

**Regla de liberación al paciente** (fuente 22):
- **Particular:** saldo de la orden en cero.
- **Convenio:** número de autorización registrado.

**Canal de entrega:**
- **Portal** de pacientes y médicos, con inicio de sesión ([infraestructura/0008](../infraestructura/0008-autenticacion-autorizacion.md)), donde se ve y descarga el PDF.
- **Correo electrónico solo como aviso**: "sus resultados están disponibles" + enlace al portal. **Sin PDF adjunto y sin datos clínicos en el correo** (decisión del 2026-10-12, mantiene [infraestructura/0003](../infraestructura/0003-seguridad-hipaa.md); la fuente 22 proponía adjuntar el PDF).
- Plantilla del correo personalizable por laboratorio, con variables que no sean datos clínicos.

### 9. Tendencias

En el portal y en la vista del laboratorio, gráfica de evolución de cada parámetro numérico del paciente a lo largo de sus órdenes anteriores dentro del mismo laboratorio (Chart.js).

## Alternativas consideradas

- **Permitir editar resultados antes de validar sin versionar:** más simple, pero pierde la trazabilidad de quién digitó qué valor.
- **Enviar el PDF adjunto por correo:** práctica común, pero expone datos de salud fuera del sistema; descartado.

## Consecuencias

- La configuración de rangos por sexo y edad es la base del catálogo; se importa desde Lablinea ([0007](0007-alcance-mvp.md)).
- **Por confirmar con asesoría legal:** si retener resultados por saldo pendiente es compatible con el derecho del paciente a acceder a su información de salud en Colombia.
- El portal es obligatorio en el MVP porque es el único canal de entrega.
