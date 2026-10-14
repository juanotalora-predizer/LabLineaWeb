# Informe de cierre — Etapa 7: Pacientes y Ley 1581

- **Fecha de cierre:** 2026-10-14
- **Commit verificado:** `0beeb6c`
- **CI:** ejecución [38586377836](https://github.com/juanotalora-predizer/LabLineaWeb/actions/runs/38586377836), exitosa (incluye las pruebas en Chromium)
- **Estado:** Cerrada

## Alcance entregado

Decisiones en [funcional/0010](../funcional/0010-pacientes-ley-1581.md).

- **Migración `0008`:**
  - En `global` (configuración por país): expresión válida por tipo de documento, mayoría de edad, plazos de consulta y reclamo, festivos de Colombia 2026–2027, texto modelo de la autorización y la función `sumar_dias_habiles`.
  - En `lab`: pacientes, textos de autorización versionados, autorizaciones y solicitudes del titular. Todas con RLS forzada y auditadas; las columnas personales quedan protegidas en la auditoría (se registra qué cambió, no el valor).
- **Reglas que impone la base:**
  - Un paciente no se guarda sin su autorización (trigger diferido al confirmar).
  - Una sola autorización vigente por paciente.
  - Una autorización solo se revoca, una vez; nada más de ella se modifica.
  - Los textos publicados no se modifican.
  - La aplicación no borra pacientes, autorizaciones, solicitudes ni textos.
- **Registro:** documento validado con la expresión del país, país de residencia, contacto opcional y autorización con medio y versión del texto. Para menores de edad el representante legal es obligatorio.
- **Búsqueda sin enumeración:**
  - Por POST, nunca en la URL.
  - Documento solo exacto; nombre con al menos 3 caracteres.
  - Máximo 20 resultados sin revelar el total.
  - 60 búsquedas por usuario cada 5 minutos.
  - Auditada sin el texto buscado.
- **Derechos del titular:**
  - Solicitudes de consulta, actualización, rectificación, supresión y revocación, con vencimiento en días hábiles del país (10 y 15 en Colombia) y lista de abiertas por vencimiento.
  - Informe *Datos del titular* imprimible, auditado como `EXPORT`.
  - Revocación con motivo, que queda como solicitud resuelta.
  - Sin autorización vigente, los datos solo se editan para atender una solicitud.
  - **Supresión** con solicitud abierta y confirmación escrita: anonimización irreversible si no hay historia clínica; rechazo con el motivo legal si la hay.
- **Preparado para la etapa 8:** `lab.autorizacion_vigente()` (exigirla al crear órdenes) y `lab.paciente_tiene_historia()` (redefinirla con las órdenes).
- **Configuración:** *Autorización de datos* para publicar versiones del texto, a partir del modelo del país con el nombre del laboratorio.
- **Herramientas:** `sembrar_desarrollo.py` publica un texto sintético y registra 10 pacientes sintéticos con autorización en cada laboratorio.

## Compuerta de calidad ([infraestructura/0011](../infraestructura/0011-calidad-pruebas-entorno-local.md))

| # | Criterio | Resultado | Evidencia |
|---|----------|-----------|-----------|
| 1 | Pruebas en verde (local y CI) | ✅ | 966 pruebas (60 de pacientes y 3 de fuzzing nuevas), local y CI |
| 2 | Cobertura ≥ 85% | ✅ | 99,0% de líneas y ramas; rutas de pacientes 98%, reglas 100% |
| 3 | E2E de flujos nuevos | ✅ | Chromium: publicar el texto → registrar con autorización firmada → buscar por documento (no queda en la URL) → abrir la ficha → registrar una solicitud → revocar. Los flujos anteriores siguen en verde |
| 4 | Migraciones upgrade/downgrade | ✅ | 0008 baja y sube en limpio y con datos (pacientes, autorizaciones y textos sintéticos) |
| 5 | Aislamiento | ✅ | Ver detalle abajo |
| 6 | Autorización | ✅ | Ver detalle abajo |
| 7 | Auditoría | ✅ | Las 4 tablas nuevas con trigger (guardián). Creación de pacientes registrada con `[protegido]` en nombres, documento, nacimiento y contacto (prueba: ningún dato del paciente aparece en la auditoría). Ficha y búsqueda (`READ`, sin el texto buscado) e informe del titular (`EXPORT`) auditados |
| 8 | Sin datos de salud en logs, errores ni URLs | ✅ | Búsqueda automática de la corrida completa sin coincidencias (las pruebas usan los pacientes sintéticos vigilados). Búsqueda por POST. Prueba manual: ningún documento usado aparece en el log del servidor. 0 errores 500 en ZAP y pruebas manuales |
| 9 | ruff / bandit / pip-audit / gitleaks | ✅ | Limpios |
| 10 | ZAP pasivo + activo autenticado | ✅ | **lab-a:** 0 altos · 0 medios · 0 bajos · 6 informativos · el falso positivo verificado de la etapa 6 (filtro acotado al catálogo; ninguna ruta de pacientes queda filtrada). Unas 14.400 peticiones a rutas de pacientes, sin errores 500. **Admin Hub:** 0 altos · 0 medios · 0 bajos · 6 informativos, 7055 peticiones autenticadas |
| 11 | Fuzzing sin errores 500 | ✅ | schemathesis en los dos hosts; fuzzing con CSRF válido de registro, búsqueda, edición, solicitudes, revocación, autorización, supresión y publicación del texto |
| 12 | Pruebas manuales dirigidas | ✅ | 15 de 15 (ver abajo) |
| 13 | Rendimiento | N/A | La búsqueda está limitada a 20 filas con índice por apellidos; la carga se mide con Locust sobre el POS (etapa 8) |

### Aislamiento (criterio 5)

- Un paciente de lab-a no existe en lab-b (404): ficha, edición, informe, revocar, autorizar, solicitudes y suprimir.
- Una solicitud de lab-a no se resuelve desde lab-b (404) ni aparece en sus solicitudes abiertas.
- La búsqueda por el documento de un paciente de lab-b no encuentra nada en lab-a (prueba manual).
- RLS: insertar un paciente con el `tenant_id` de otro laboratorio → *row-level security*.

### Autorización (criterio 6)

- Recepción registra, busca y registra solicitudes; no suprime (403, y no ve el formulario).
- El auditor y el validador consultan; registrar → 403.
- El paciente del portal no entra a pacientes (403).
- El texto de la autorización: recepción no lo ve (403); el auditor no lo publica (403).
- Base de datos: borrar pacientes, autorizaciones, solicitudes o textos y modificar textos → *permission denied*.

## Pruebas específicas del plan

- **Sin autorización vigente no se procesan datos:** la base rechaza un paciente sin autorización. `lab.autorizacion_vigente()` responde falso tras la revocación (la usará la creación de órdenes en la etapa 8). Sin autorización, editar exige una solicitud del titular.
- **IDOR:** UUID de un paciente de otro laboratorio → 404 en todas las rutas.
- **Supresión:** anonimiza y queda auditada. La prueba revisa el paciente, sus autorizaciones, sus solicitudes y toda la auditoría, y no encuentra nombre, documento, nacimiento, contacto, representante ni el texto de la solicitud. Con historia clínica se rechaza y se revoca la autorización.
- **Búsqueda sin inyección ni enumeración:** comodines (`%`, `_`, `\`), SQL y NUL sin efecto; un prefijo del documento no encuentra nada; tope de 20 sin total; 429 tras 60 búsquedas.

## Pruebas manuales dirigidas

Script reproducible `scripts/pruebas_manuales/pacientes.py`, contra el servidor HTTPS real con los datos sintéticos sembrados.

| Prueba | Resultado |
|--------|-----------|
| Documento exacto encuentra; un prefijo no; SQL en la búsqueda sin resultados | ✅ (3) |
| El documento de un paciente de lab-b no aparece en lab-a | ✅ |
| IDOR: ficha, informe, edición y revocación de un paciente de lab-b desde lab-a → 404 | ✅ (2) |
| HTML en el nombre se muestra escapado | ✅ |
| Revocación deja la ficha sin autorización | ✅ |
| Recepción no suprime (403); el administrador suprime y el documento ya no se encuentra | ✅ (2) |
| Más de 60 búsquedas en 5 minutos → 429 | ✅ |
| Búsqueda desde otro origen (CSRF) → 403; la búsqueda no acepta GET | ✅ (2) |
| Ningún documento usado aparece en el log del servidor; 0 errores 500 | ✅ (2) |

## Hallazgos y resolución

| Hallazgo | Severidad | Detectado por | Resolución |
|----------|-----------|---------------|------------|
| **El log de acceso del servidor registra la URL completa:** la prueba manual que verifica que la búsqueda no acepta GET mandaba un documento en la URL, y quedó en el log aunque la aplicación respondió 400 sin buscar | Baja (la aplicación nunca pone datos en URLs; solo pasa si el cliente los envía) | **Prueba manual** (búsqueda en el log) | La sonda usa un valor sin datos personales. Se amplía el pendiente de la etapa 20: el log del proxy y del servidor no guarda la cadena de consulta |
| Un texto con dígitos se interpreta como documento (p. ej. un apellido con números) | Ninguna (diseño) | Pruebas | Esperado: los nombres no llevan dígitos. Así un documento nunca se busca por partes como si fuera un nombre |
| El fuzzing publica versiones nuevas del texto de autorización, y una prueba posterior suponía un texto fijo | Baja (pruebas) | Compuerta completa | La prueba verifica la versión aceptada, no un texto fijo |
| Informativos ZAP (10029, 10058, 10015, 10112, 10104, 10031) | Informativo | ZAP | Los mismos de etapas anteriores |

## Riesgos bajos documentados

- **Validación legal pendiente** (backlog): texto modelo, plazos, supresión con historia clínica y expresiones de los tipos de documento contra RIPS.
- **Festivos cargados solo para 2026 y 2027** (backlog).
- **Búsqueda por nombre sin normalizar tildes:** "Gomez" no encuentra "Gómez". El documento exacto sí funciona.

## Pendientes (fuera del alcance de la etapa)

- Etapa 8: exigir `lab.autorizacion_vigente()` al crear órdenes y redefinir `lab.paciente_tiene_historia()`.
- Portal del paciente (etapa 14): solicitudes y autorización en pantalla.
- Mapeo a FHIR `Patient` con los perfiles de la IHCE (etapa de interoperabilidad).

## Riesgos aceptados por el usuario

Ninguno.
