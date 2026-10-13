# 0012. Cola de tareas en segundo plano sobre PostgreSQL

- **Estado:** Aceptada
- **Fecha:** 2026-10-13
- **Responsable:** Juan Otálora

## Contexto

El [plan](../plan-desarrollo.md) prevé tareas en segundo plano: PDF de resultados, correos de aviso, envíos a la DIAN con reintentos ([0009](0009-facturacion-electronica.md)) y transformaciones de la bodega ([0010](0010-analitica-bodega-datos.md)). Decidió además usar PostgreSQL (`SELECT … FOR UPDATE SKIP LOCKED`) para no agregar Redis, y dejó la librería para la etapa 3.

Requisitos propios del producto:

- **La cola no mezcla laboratorios:** cada tarea corre con el laboratorio con que se encoló, bajo el mismo RLS que las peticiones.
- **Una tarea no se ejecuta dos veces**, ni con varios trabajadores ni si uno se cuelga.
- **Reintentos** con espera para servicios externos (DIAN, correo).
- **Sin datos de salud** en la cola ni en los logs del trabajador.

## Decisión

**Implementación propia, sin dependencias nuevas** (`app/core/tareas.py`, migración `0004`), unas 150 líneas sobre SQLAlchemy y asyncpg, que ya están en el proyecto.

### Modelo

- Tabla `cola.tareas` en un esquema propio. El rol de la aplicación **no tiene acceso directo** a la tabla; solo a cuatro funciones `SECURITY DEFINER`:

  | Función | Qué hace |
  |---|---|
  | `cola.encolar` | Inserta la tarea con `tenant_id = lab.tenant_actual()`; falla sin laboratorio. Con `clave_unica` es idempotente por laboratorio. |
  | `cola.tomar` | Toma una tarea disponible con `FOR UPDATE SKIP LOCKED`, le da un **plazo** (`bloqueada_hasta`) y una **ficha** nueva (UUID). |
  | `cola.completar` | Marca `COMPLETADA` solo si la ficha es la vigente **y** el laboratorio de la transacción es el de la tarea. |
  | `cola.fallar` | Programa el reintento (`PENDIENTE` con espera) o la marca `FALLIDA` al agotar los intentos. |

- Estados: `PENDIENTE` → `EN_CURSO` → `COMPLETADA` | `FALLIDA`. Por defecto 5 intentos.

### Ejecución

1. El trabajador toma la tarea (transacción corta, confirmada).
2. Abre `sesion_tenant(tarea.tenant_id, usuario_id="tarea:<uuid>")`, ejecuta el manejador y llama a `cola.completar` **en la misma transacción**. Si la ficha ya no es la vigente (el plazo venció y otro trabajador tomó la tarea), se revierte todo lo que hizo el manejador. Así los efectos en la base ocurren **exactamente una vez**.
3. Si el manejador falla, la tarea se reintenta con espera exponencial (30 s, 1 min, 2 min… hasta 1 hora). `ErrorPermanente` y los tipos sin manejador no se reintentan.
4. Si un trabajador muere, la tarea vuelve a estar disponible al vencer el plazo (5 minutos por defecto); si ya no le quedan intentos, queda `FALLIDA`.

Los efectos **externos** (correo, DIAN) son *al menos una vez*: el manejador usa una clave de idempotencia del servicio externo cuando exista (en la DIAN, el CUFE).

### Reglas

- `encolar` se llama dentro de `sesion_tenant`: si la transacción de la petición se revierte, la tarea no existe.
- Los datos de una tarea son **solo identificadores**: claves de texto, valores de texto corto (≤ 200), enteros, booleanos o nulos; máximo 4 KB. Nunca nombres, documentos ni resultados.
- Errores: en la cola y en el log solo se guarda el **nombre de la excepción**, nunca su mensaje (podría llevar datos del registro).
- Las escrituras de una tarea quedan auditadas con el usuario `tarea:<uuid>`.
- Proceso: `trabajador.py`. Además mantiene las particiones mensuales de la auditoría (al arrancar y cada 24 horas).

## Alternativas consideradas

- **Procrastinate:** madura, sobre PostgreSQL. Usa psycopg 3, un segundo controlador junto a asyncpg, y sus tablas no conocen el laboratorio: habría que reconstruir el aislamiento por encima.
- **PgQueuer:** usa asyncpg, pero es un proyecto pequeño y tampoco resuelve el laboratorio ni la ejecución única con la transacción del manejador.
- **Celery / RQ / Dramatiq con Redis:** agrega un servicio más que asegurar, cifrar y cubrir con BAA; el plan lo descartó.

## Consecuencias

- Sin dependencias ni servicios nuevos; el aislamiento por laboratorio y la ejecución única quedan probados (`tests/test_tareas.py`).
- El trabajador usa el rol `lablinea_app`, que puede llamar a `cola.tomar`. Como la cola no guarda datos de salud y la tarea siempre corre bajo el RLS de su laboratorio, el riesgo es bajo. Un rol separado para el trabajador se evalúa en la etapa 20 (requiere crearlo con el superusuario).
- Las tareas terminadas se acumulan; su purga (p. ej. completadas con más de 90 días) se agrega cuando haya volumen real.
- Sin `LISTEN/NOTIFY`: el trabajador consulta cada segundo cuando no hay tareas. Suficiente para el MVP.
