# 0006. Gestión: inventarios, costeo y dashboard

- **Estado:** Aceptada. *(Modificado el 2026-10-12: el dashboard completo entra al MVP. Modificado el 2026-10-14: las secciones 1 y 2 quedan **reemplazadas por [0011](0011-inventarios-equipos-proveedores.md)**, inventarios y equipos entran al MVP; el consumo automático por examen y el costeo por actividad (sección 3) quedan para después del MVP.)*
- **Fecha:** 2026-10-12
- **Responsable:** Juan Otálora
- **Fuentes:** [12 Costos de exámenes](../fuentes/), [13 Dashboard](../fuentes/), [24 Inventarios y costeo](../fuentes/)

## Contexto

Los laboratorios necesitan saber qué exámenes y convenios les dejan margen, detectar fugas de dinero y controlar sus insumos. Corresponde a la fase 6 del plan de desarrollo (fuente 21). **El dashboard completo (sección 4) entra al MVP**, alimentado por una bodega de datos separada ([infraestructura/0010](../infraestructura/0010-analitica-bodega-datos.md)). Los indicadores de rentabilidad por costo real dependen de inventarios y costeo (secciones 1 a 3).

## Decisión

### 1. Inventarios

> Reemplazada por [0011](0011-inventarios-equipos-proveedores.md).


- Proveedores; ítems de tipo `REACTIVO`, `CONSUMIBLE` o `EQUIPO`, con unidad, stock actual, stock mínimo y costo promedio.
- Compras como entradas de almacén, que actualizan el costo promedio.
- Consumo por examen: cada examen define los insumos que usa, y al procesarse se descuentan del inventario.
- Alerta de stock mínimo.

### 2. Equipos biomédicos

> Reemplazada por [0011](0011-inventarios-equipos-proveedores.md).


Hoja de vida y mantenimiento: activo fijo, horas de actividad e inactividad por mes, costo por hora de operación (depreciación + mantenimiento), fechas del último y próximo mantenimiento.

### 3. Costeo por actividad (*Activity-Based Costing*)

Costo real por examen = insumos + uso de equipo (prorrateado) + mano de obra (costo hora del personal × tiempo estimado por examen, según su dedicación a cada sección).

- **Nómina ligera:** personal con salario base, cargas prestacionales y horas estándar por mes, y su porcentaje de dedicación por sección. Es solo para costeo; **no liquida nómina**.

### 4. Dashboard gerencial

- **Filtros:** día, semana, mes, año, año corrido, rango libre y comparativo con el periodo anterior; por sede; particulares frente a convenios.
- **Indicadores financieros:** ventas netas, cartera por cobrar, ticket promedio, efectividad de recaudo.
- **Indicadores operativos:** volumen por sección y examen, mapa de calor por hora, tiempo de respuesta (toma → validación), tasa de muestras rechazadas.
- **Rentabilidad:** margen por examen, sección, convenio y tipo de cliente; ranking de más y menos rentables; dispersión volumen frente a margen; alerta de tarifas por debajo del costo.
- **Alertas antifraude:** descuentos excesivos por usuario, órdenes anuladas o reescritas antes del pre-cierre, faltantes repetidos en caja, exámenes procesados sin pago o sin autorización.
- Gráficas con Chart.js ([infraestructura/0001](../infraestructura/0001-stack-fastapi-jinja2.md)), no Recharts como proponían las fuentes.

## Alternativas consideradas

- **Integrar con un ERP o herramienta de BI externa:** menos desarrollo, pero los datos clínicos y financieros saldrían a un tercero y el producto perdería un diferenciador.

## Consecuencias

- El MVP debe guardar desde el inicio los datos que este módulo necesitará: precios históricos congelados, tiempos de cada estado de la muestra y del resultado, y descuentos con su autorización.
- Los indicadores usan solo datos agregados; el dashboard no muestra datos clínicos de pacientes individuales.
