# Informe de cierre — Etapa 6: Catálogo e importador de Lablinea

- **Fecha de cierre:** 2026-10-13
- **Commit verificado:** `c19fed6`
- **CI:** ejecución [38496107468](https://github.com/juanotalora-predizer/LabLineaWeb/actions/runs/38496107468), exitosa (incluye las pruebas en Chromium)
- **Estado:** Cerrada

## Alcance entregado

Decisiones en [funcional/0009](../funcional/0009-catalogo-e-importador.md).

- **Migración `0007`:** catálogo por laboratorio en `lab`, con RLS forzada y auditoría por trigger en todas las tablas.
  - Maestros: secciones, unidades (con código UCUM), tipos de muestra, tipos de tubo (con capacidad), técnicas, tarifas (con moneda) y tipos de código alterno.
  - Exámenes con código nacional (CUPS en Colombia, según `global.paises.terminologia_procedimientos`), LOINC validado por la base y días de procesamiento.
  - Parámetros numéricos, de texto, de lista o títulos, con valores de lista.
  - Rangos de referencia por sexo y edad en días (0 a 150 años), con mínimo, máximo y críticos; la base rechaza rangos incoherentes.
  - Requisitos de muestra (tipo, tubo, volumen), precios por tarifa y códigos alternos.
  - Exámenes, parámetros y maestros no se borran (se desactivan): el rol de la aplicación no tiene `DELETE` sobre ellos.
- **Interfaz** (permiso `configuracion`): lista con búsqueda y filtro por sección, ficha del examen, parámetros con sus rangos y valores, maestros, revisión de lo importado y exportación a CSV.
- **Rangos:** advertencias de huecos y solapes por sexo en todo el intervalo de edad, y edad legible (años, meses o días).
- **Importador de Lablinea:**
  - Recibe un ZIP con las tablas del catálogo exportadas a CSV desde Access; nunca el `.mdb`.
  - Límites estrictos de tamaño, entradas, filas, longitud de campo y proporción de compresión. Rechaza rutas, cifrado, archivos que no son CSV y cualquier tabla que no sea del catálogo (protege contra subir pacientes por error).
  - Detecta la codificación (UTF-8 o Windows-1252) y el separador.
  - Vista previa con errores (bloquean) y advertencias (no bloquean).
  - Carga atómica: se vuelve a analizar contra el catálogo actual y se verifica el hash del archivo; si el catálogo cambió, se detiene.
  - Los rangos y requisitos importados quedan marcados "por revisar". El archivo se borra de la base al cargar.
- **Exportación CSV:** neutraliza fórmulas (celdas que empiezan con `=`, `+`, `-`, `@`, tabulador o retorno) y queda auditada.
- **Herramientas:** `scripts/lablinea_sintetico.py` genera una exportación sintética de Lablinea (Windows-1252, `;`). `sembrar_desarrollo.py` la carga en lab-a.

## Compuerta de calidad ([infraestructura/0011](../infraestructura/0011-calidad-pruebas-entorno-local.md))

| # | Criterio | Resultado | Evidencia |
|---|----------|-----------|-----------|
| 1 | Pruebas en verde (local y CI) | ✅ | 846 pruebas (114 del catálogo y el importador, más fuzzing y diseño), local y CI |
| 2 | Cobertura ≥ 85% | ✅ | 99,1% de líneas y ramas; importador 99%, rutas del catálogo 99% |
| 3 | E2E de flujos nuevos | ✅ | Chromium: subir la exportación → vista previa con "por revisar" → cargar → el catálogo aparece → rango por sexo y edad en la hemoglobina → marcar revisado el importado. Los flujos anteriores siguen en verde |
| 4 | Migraciones upgrade/downgrade | ✅ | 0007 baja y sube en limpio, también con datos (catálogo importado y datos del escaneo ZAP) |
| 5 | Aislamiento | ✅ | Ver detalle abajo |
| 6 | Autorización | ✅ | Ver detalle abajo |
| 7 | Auditoría | ✅ | Las 15 tablas nuevas tienen trigger (guardián de la auditoría); el contenido del archivo importado no se copia a la auditoría. La exportación CSV registra `EXPORT` con conteos |
| 8 | Sin datos de salud en logs, errores ni URLs | ✅ | Búsqueda automática de la corrida completa sin coincidencias. Los errores del importador dicen tabla, fila y columna, nunca el contenido. 0 errores 500 en los logs del servidor (ZAP en los dos sitios y pruebas manuales), tras corregir el hallazgo de ZAP |
| 9 | ruff / bandit / pip-audit / gitleaks | ✅ | Limpios |
| 10 | ZAP pasivo + activo autenticado | ✅ | **lab-a:** 0 altos · 0 medios · 0 bajos · 6 informativos · 1 falso positivo verificado (ver hallazgos). **Admin Hub:** 0 altos · 0 medios · 0 bajos · 6 informativos, 7050 peticiones autenticadas |
| 11 | Fuzzing sin errores 500 | ✅ | schemathesis en los dos hosts; fuzzing con CSRF válido de los formularios nuevos (examen, maestros, rango, precio y requisito); hypothesis con bytes y CSV arbitrarios sobre el lector y el análisis, y subidas arbitrarias por HTTP |
| 12 | Pruebas manuales dirigidas | ✅ | 17 de 17 (ver abajo) |
| 13 | Rendimiento | N/A | Sin endpoints críticos de operación |

### Aislamiento (criterio 5)

- Un examen y un parámetro de lab-a no existen en lab-b (404), ni para leer ni para desactivar, agregar parámetros, rangos, valores, precios o requisitos. Tampoco aparecen en su lista ni en su exportación.
- Una importación de lab-b no existe en lab-a (404), ni para ver ni para cargar.
- RLS: insertar en el catálogo con el `tenant_id` de otro laboratorio → *row-level security*.
- Los códigos de los exámenes son únicos por laboratorio: lab-a y lab-b importan el mismo catálogo sin chocar.

### Autorización (criterio 6)

- Catálogo: solo quien tiene `configuracion` (administrador). Recepción, auditor, validador y paciente → 403.
- Importar exige `configuracion.crear`: recepción y auditor → 403.
- Base de datos: el rol de la aplicación no puede borrar exámenes, parámetros ni secciones (*permission denied*); solo borra filas dependientes (rangos, valores de lista, requisitos, precios y códigos alternos).

## Pruebas específicas del plan

- **Archivos malformados, enormes o con codificaciones raras:** ZIP truncado o corrupto, vacío, de más de 10 MB, bomba ZIP, tabla enorme descomprimida, demasiadas filas o entradas, entradas con rutas o cifradas, UTF-16, bytes NUL y caracteres de control. Se rechazan con 400 y no guardan nada. Una falla de la base a mitad de la carga no deja nada cargado (prueba con la carga interrumpida en los precios).
- **Archivos que no corresponden:** ejecutable de Windows y script renombrados a `.zip`, ZIP con una tabla de pacientes → rechazados.
- **Inyección CSV:** `celda_segura` con todos los prefijos peligrosos; la exportación real no tiene ninguna celda que empiece como fórmula.
- **Rangos solapados o con huecos:** advertencias por sexo; propiedad con hypothesis: las advertencias describen exactamente la cobertura real de cualquier conjunto de rangos.

## Pruebas manuales dirigidas

Script reproducible `scripts/pruebas_manuales/catalogo.py`, contra el servidor HTTPS real.

| Prueba | Resultado |
|--------|-----------|
| Rechazo de ejecutable y script renombrados, ruta `../`, tabla de pacientes, bomba ZIP, ZIP truncado, 11 MB y UTF-16 (400 sin error 500) | ✅ (8) |
| Importación válida en lab-b: la vista previa no carga nada; luego la carga queda completa | ✅ |
| IDOR desde lab-a: ver y desactivar un examen de lab-b, ver una importación de lab-b → 404 | ✅ (3) |
| HTML en el nombre del examen se muestra escapado | ✅ |
| La exportación CSV no tiene celdas que empiecen como fórmula (el código `=M…` sale como `'=M…`) | ✅ |
| SQL en la búsqueda: 200 y el catálogo sigue intacto | ✅ |
| Maestro desde otro origen (CSRF) → 403; `Host` ajeno → 400 | ✅ (2) |

## Hallazgos y resolución

| Hallazgo | Severidad | Detectado por | Resolución |
|----------|-----------|---------------|------------|
| **Error 500 con un byte NUL en la búsqueda del catálogo** (`/catalogo?q=%00`): PostgreSQL rechaza el NUL en un texto | Media (disponibilidad) | **ZAP activo** | El parámetro `q` usa `TextoSeguro` (400 con caracteres de control); prueba de regresión con `%00` y `%1b`. Es el único parámetro de texto libre en la URL de toda la aplicación |
| **ZAP 40018 "SQL Injection" (alto) en los formularios del catálogo:** falso positivo | — | ZAP activo | Verificado en la base: las 77 cargas de ZAP quedaron guardadas como texto literal (p. ej. una técnica llamada `ZAP AND 1=1 --`) y el examen editado conservó su código. Cada POST guarda una fila nueva que aparece en el listado, y ZAP lo interpreta como "más datos". Todo el SQL de `app/catalogo` es texto con parámetros (bandit B608 lo exige). Prueba de regresión `test_maestros_guardan_inyeccion_sql_como_texto_literal`. Filtro en `scripts/zap/plan.yaml` acotado a la regla 40018 y a `/catalogo/(maestros\|examenes\|parametros\|rangos\|requisitos)/`; la búsqueda y el importador quedan fuera del filtro. `scripts/zap/resumen.py` lista aparte los falsos positivos verificados |
| `csv.Sniffer` detectaba mal el separador en tablas de una columna y aceptaba comillas mal cerradas | Media (integridad) | Pruebas con hypothesis | Separador por el encabezado (el más frecuente entre `,`, `;` y tabulador) y lector estricto |
| Nombre de columna mal normalizado (`normaledereferencia`): las referencias de Lablinea no se habrían importado | Media (funcional) | Prueba con la exportación sintética | Corregido; la prueba de la exportación completa verifica los 12 rangos |
| Textos `LOINC`, `UCUM` y `mL` escritos en las plantillas | Baja | Guardián de i18n | Llevados al catálogo de textos |
| La plantilla parcial `_campos_examen.html` no hereda de `base.html` | Baja (herramientas) | Guardián de diseño | Los parciales (prefijo `_`) quedan fuera de esa regla |
| Prueba de aislamiento que contaba las importaciones de lab-a, donde el E2E deja una | Baja (pruebas) | Compuerta completa | La prueba busca la importación específica de lab-b |
| Informativos ZAP (10029, 10058, 10015, 10112, 10104, 10031) | Informativo | ZAP | Los mismos de etapas anteriores. 10031 en lab-a: el filtro `seccion` solo se refleja como opción seleccionada si es un UUID |

## Riesgos bajos documentados

- **Rangos importados sin sexo ni edad:** Lablinea no los tiene. Se importan para ambos sexos y todas las edades, marcados "por revisar", y la pantalla de revisión los lista hasta que alguien los confirma.
- **LOINC vacío en lo importado:** Lablinea no lo guarda; se asigna a mano (pendiente en el backlog antes de la interoperabilidad FHIR).

## Pendientes (fuera del alcance de la etapa)

- Asignación asistida de LOINC y UCUM al catálogo importado.
- Paquetes de exámenes (etapa 8).
- Agrupación de tubos usando requisitos y tipos de tubo (etapa 12).

## Riesgos aceptados por el usuario

Ninguno.
