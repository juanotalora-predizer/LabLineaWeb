# 0010. Analítica: bodega de datos separada

- **Estado:** Aceptada *(aprobada por el usuario el 2026-10-14: bodega de datos separada)*
- **Fecha:** 2026-10-12
- **Responsable:** Juan Otálora

## Contexto

Se decidió incluir en el MVP un **dashboard interactivo completo** ([funcional/0006](../funcional/0006-gestion-inventarios-costos-dashboard.md)): filtros cruzados por periodo, sede y tipo de cliente, comparativos con años anteriores, mapas de calor, desglose por sección y examen, alertas antifraude, y en el Admin Hub indicadores de todos los laboratorios. La pregunta es si hace falta un proceso ETL y una bodega de datos aparte para no afectar la base transaccional.

## Análisis: ¿es necesaria?

**Sí, conviene una base analítica separada**, por cuatro razones:

1. **Carga:** los comparativos anuales, los mapas de calor y los desgloses recorren todo el historial. Sobre la base transaccional competirían con el POS, la toma de muestras y la validación, que necesitan respuestas inmediatas en horas pico.
2. **Modelo:** el modelo transaccional está normalizado para escribir; un modelo dimensional (estrella) hace las consultas del dashboard simples y rápidas.
3. **Privacidad:** el dashboard no necesita saber quién es el paciente. Una bodega sin nombres, documentos ni contactos reduce el riesgo, cosa que no se logra consultando la base transaccional.
4. **Admin Hub:** los indicadores de todos los laboratorios salen de la bodega, sin que la plataforma toque la base clínica ([0005](0005-arquitectura-saas-multitenant.md)).

**Lo que no hace falta:** un datamart físico por laboratorio. Con cientos de laboratorios serían cientos de copias que mantener. El aislamiento por laboratorio se logra igual que en la base transaccional: `tenant_id` y RLS sobre las mismas tablas de hechos.

## Propuesta

### 1. Topología

```
Celda regional (p. ej. Colombia)
┌──────────────────────────┐   replicación lógica    ┌───────────────────────────────┐
│ PostgreSQL transaccional │ ──(solo columnas sin──▶ │ PostgreSQL analítico          │
│ plataforma · global · lab│     datos personales)    │ staging → bodega → datamarts  │
└──────────────────────────┘                          └───────────────────────────────┘
                                                                  │ agregados sin datos
                                                                  ▼ de pacientes
                                                  Datamart de plataforma (Admin Hub, todas las celdas)
```

- **Instancia PostgreSQL analítica separada** en cada celda regional. Así la bodega de cada país queda en la misma jurisdicción que sus datos.
- **Extracción por replicación lógica nativa de PostgreSQL**, publicando solo las columnas necesarias (PostgreSQL 15+ permite listas de columnas por publicación). No lanza consultas pesadas sobre la base transaccional y llega con segundos de retraso.
- **Transformación** con SQL versionado en el repositorio, ejecutado por el trabajador de tareas cada pocos minutos (incremental), de `staging` al modelo estrella.

### 2. Modelo y datamarts

- **Hechos:** línea de orden (examen vendido, precio congelado, descuento, convenio), pagos, movimientos de caja, eventos de muestra (toma, recepción, rechazo), eventos de resultado (ingreso, validación, entrega), descuentos autorizados y anulaciones.
- **Dimensiones:** tiempo (día, hora, semana, mes, año), laboratorio, sede, estación, examen, sección, convenio, tipo de cliente, usuario del laboratorio, grupo de edad y sexo del paciente.

| Datamart | Usuarios | Contenido |
|----------|----------|-----------|
| **Laboratorio** | Personal autorizado de cada laboratorio | Todo el detalle de su laboratorio, aislado con `tenant_id` + RLS |
| **País** | Administración de la plataforma por país | Agregados por laboratorio y periodo, sin nivel de paciente |
| **Plataforma** | Admin Hub | MRR/ARR, laboratorios activos, volumen y uso; consolidado de todas las celdas, solo agregados |

### 3. Privacidad en la bodega

- Sin nombres, documentos, contactos, direcciones ni valores de resultados clínicos.
- El paciente se representa con un **seudónimo** (HMAC con una clave por laboratorio) para contar pacientes únicos y recurrentes sin identificarlos. Edad en grupos y sexo, no fecha de nacimiento.
- Aun así, los datos seudonimizados siguen siendo datos personales: la bodega se cifra y se audita igual, y una supresión pedida por el titular se propaga a la bodega.

### 4. Frescura

- **Indicadores del día** (cola de muestras, caja abierta, pendientes de validar): consultas livianas e indexadas a la base transaccional.
- **Analítica** (históricos, comparativos, rentabilidad, antifraude): la bodega, con un retraso objetivo de **15 minutos o menos**.

### 5. Interfaz

El dashboard se construye dentro de la aplicación (Jinja2 + htmx + Chart.js, [0001](0001-stack-fastapi-jinja2.md)), con filtros que recargan solo los gráficos afectados.

## Alternativas consideradas

- **Consultar la base transaccional, con índices y vistas materializadas:** lo más simple, pero las consultas pesadas compiten con la operación y los datos personales quedan al alcance del dashboard.
- **Réplica de lectura:** quita la carga a la base principal, pero mantiene el modelo normalizado y todos los datos personales.
- **Herramienta BI externa (Metabase, Superset, Power BI):** rápida de montar, pero el aislamiento por laboratorio y la protección de datos pasan a depender de un tercero.
- **ETL por lotes nocturnos:** más simple que la replicación, pero el dashboard mostraría datos de ayer.

## Consecuencias

- Requiere un hosting con PostgreSQL administrado que permita la replicación lógica (`wal_level = logical`) y una segunda instancia por celda.
- Agrega aproximadamente 4 sprints al MVP (bodega, datamarts, dashboard del laboratorio, dashboard del Admin Hub; ver [plan](../plan-desarrollo.md)).
- Toda tabla nueva que deba aparecer en el dashboard necesita su publicación y su transformación; el diseño de cada módulo debe indicar qué hechos genera.
