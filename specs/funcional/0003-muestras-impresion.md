# 0003. Muestras, códigos de barras e impresión

- **Estado:** Aceptada
- **Fecha:** 2026-10-12
- **Responsable:** Juan Otálora
- **Fuentes:** [14 Estaciones e impresoras](../fuentes/), [15 Muestras DDL](../fuentes/), [26 Algoritmo de agrupación](../fuentes/)

## Contexto

Cada orden pagada genera uno o varios tubos o contenedores que deben rotularse con código de barras y seguirse desde la toma hasta el procesamiento. Cada puesto de trabajo tiene su propia impresora térmica de etiquetas (Zebra, TSC) conectada por USB o red local.

## Decisión

### 1. Configuración por examen

Cada examen define sus requisitos de muestra: tipo de muestra (sangre total, suero, orina…), **tipo de tubo o contenedor** (tapa lila EDTA, tapa roja, etc.) y volumen mínimo en mL. La capacidad de cada tipo de tubo es configurable.

### 2. Algoritmo de agrupación de tubos

1. Toma los exámenes de la orden.
2. Agrupa por **tipo de muestra y tipo de tubo** (no solo por tipo de muestra: exámenes que requieren aditivos distintos nunca comparten tubo).
3. Dentro de cada grupo, reparte los exámenes en tubos sin superar la capacidad; un examen no se divide entre tubos.
4. Genera la secuencia "Tubo N de M" y un código de barras único por tubo, p. ej. `LAB-CALI-ORD5001-SANG-1/2`.
5. Registra qué exámenes van en cada tubo.

> Nota sobre la fuente 26: su ejemplo pone hemograma y perfil lipídico en tubo lila, pero el perfil lipídico normalmente usa suero (tapa roja). Por eso el agrupamiento incluye el tipo de tubo.

### 3. Estados de la muestra

`PENDIENTE_TOMA` → `RECOLECTADA` → `RECIBIDA` (en el área técnica) → `EN_PROCESO`, o `RECHAZADA` con motivo obligatorio (hemolizada, insuficiente, mal rotulada…). Cada transición registra usuario, fecha y hora para la trazabilidad y para medir tiempos de respuesta.

### 4. Estaciones de trabajo

- Cada sede tiene estaciones (ventanilla POS, recepción, cubículo de toma de muestras) registradas en el servidor, con su impresora asociada.
- Al iniciar sesión en un equipo, el usuario selecciona su estación; la selección se recuerda en el navegador por comodidad, pero la estación válida la confirma el servidor.

### 5. Cola de toma de muestras

Vista por sede con las órdenes `PAGADA` y tubos `PENDIENTE_TOMA`, en orden de llegada. El flebotomista imprime cada etiqueta y confirma la toma; la orden sale de la cola. Se actualiza sin recargar la página (htmx, ver [infraestructura/0001](../infraestructura/0001-stack-fastapi-jinja2.md)).

### 6. Impresión

- El servidor genera la etiqueta en **ZPL**.
- **MVP:** el navegador la envía a la impresora local mediante **QZ Tray** (servicio puente instalado en el equipo de la estación).
- **Descartado:** que el servidor imprima directamente por IP (puerto 9100), como propone la fuente 14. El servidor está en la nube y no alcanza la red local del laboratorio.
- **Después del MVP:** evaluar mover la impresión al conector local de [infraestructura/0006](../infraestructura/0006-integracion-his-equipos.md), para tener un solo agente instalado por sede.

## Alternativas consideradas

- **Diálogo de impresión del navegador (PDF):** no requiere instalar nada, pero es lento, depende del controlador y suele desajustar las etiquetas.
- **PrintNode:** servicio en la nube equivalente a QZ Tray, pero los datos de la etiqueta (nombre del paciente) pasarían por un tercero sin BAA.

## Consecuencias

- Cada estación de impresión necesita QZ Tray instalado. **Pendiente:** confirmar el costo de licencia de QZ Tray para impresión sin avisos de confirmación.
- La etiqueta lleva nombre y documento del paciente: es un dato personal impreso, y el tubo sale del sistema; no lleva resultados.
- Los estados de la muestra alimentan los indicadores de tiempo de respuesta y de rechazo.
