# Informe de cierre — Etapa 3: Auditoría, tareas en segundo plano e i18n

- **Fecha de cierre:** 2026-10-13 (pendiente de la CI)
- **Commit verificado:** pendiente
- **CI:** pendiente: se ejecuta al subir los cambios
- **Estado:** Abierta. Toda la compuerta local está en verde. Solo falta que la CI pase después del push (criterio 1)

## Alcance entregado

- **Migración `0004`:**
  - `lab.auditoria`, particionada por mes y con RLS forzado.
  - Trigger genérico `lab.auditar()`.
  - `lab.registrar_acceso()` para lecturas, exportaciones y accesos denegados.
  - `lab.crear_particion_auditoria()`.
  - Esquema `cola` con `cola.tareas` y sus funciones.
- **Auditoría de escrituras** en usuarios, roles y permisos:
  - Guarda el registro antes y después, el usuario y la IP de la transacción.
  - Los secretos (hash de contraseña, secreto TOTP) aparecen como `[protegido]`, y como `[protegido, modificado]` cuando cambian. Las columnas operativas (contador TOTP) no generan registros.
  - Un guardián obliga a auditar toda tabla nueva de `lab`, o a justificar por qué no se audita.
- **Auditoría desde la aplicación:**
  - La lista de usuarios registra la lectura con conteo de filas, sin contenido.
  - Todo 403 de `requiere_permiso` o `requiere_accion` queda registrado como acceso denegado.
- **Auditoría de solo inserción:**
  - El rol de la aplicación solo la lee; no puede insertar, modificar, borrar ni vaciar.
  - El dueño tampoco puede modificar, borrar ni vaciar (triggers de fila y de `TRUNCATE`).
  - Cada partición tiene su propio RLS y no tiene privilegios para la aplicación, porque una partición consultada directamente no aplica las políticas de la tabla madre.
  - Hay particiones para 12 meses, una partición por defecto y mantenimiento automático desde el trabajador.
- **Cola de tareas** ([infraestructura/0012](../infraestructura/0012-cola-de-tareas.md)): implementación propia sobre PostgreSQL, sin dependencias nuevas.
  - Se encola dentro de la transacción del laboratorio.
  - Plazo y ficha por toma; la tarea se completa en la misma transacción del manejador, así que sus efectos en la base ocurren una sola vez.
  - Reintentos con espera exponencial; `ErrorPermanente` no se reintenta.
  - Los errores se guardan solo con el nombre de la excepción.
  - Proceso: `trabajador.py`.
- **i18n** ([infraestructura/0013](../infraestructura/0013-textos-externalizados-i18n.md)):
  - Catálogo `app/locales/es-CO.toml`, `t()` en Python y en Jinja2, y cadena de idiomas (`es-MX` → `es` → `es-CO`).
  - `lang` del HTML según el laboratorio, y filtro `|fecha` con la zona del país.
  - Conexión a PostgreSQL en UTC.
  - Todas las plantillas y mensajes al usuario están externalizados, incluido el correo del código.
- **Datos sintéticos:**
  - `scripts/sinteticos.py` genera personas reproducibles por semilla: documentos con prefijo 99, correos `@sintetico.test` y teléfonos 300000xxxx.
  - Los tipos de documento salen de la configuración del país.
  - `sembrar_desarrollo.py` siembra 10 pacientes sintéticos por laboratorio.

## Compuerta de calidad ([infraestructura/0011](../infraestructura/0011-calidad-pruebas-entorno-local.md))

| # | Criterio | Resultado | Evidencia |
|---|----------|-----------|-----------|
| 1 | Pruebas en verde (local y CI) | ⏳ local ✅, CI pendiente | 305 pruebas (79 nuevas) con `scripts/verificar.sh` |
| 2 | Cobertura ≥ 85% | ✅ | 99,3% de líneas y ramas |
| 3 | E2E de flujos nuevos | ✅ | La etapa no agrega flujos de usuario. Los 5 flujos E2E existentes pasan con las plantillas externalizadas, sin errores de CSP |
| 4 | Migraciones upgrade/downgrade | ✅ | 0004 baja y sube en limpio (`verificar.sh` baja todo y vuelve a subir) |
| 5 | Aislamiento entre laboratorios | ✅ | Auditoría de lab-a invisible desde lab-b (pruebas y servidor real); `registrar_acceso` no escribe en otro laboratorio; cada tarea corre con el laboratorio con que se encoló y solo ve sus filas; `encolar` sin laboratorio falla; la clave única es por laboratorio |
| 6 | Autorización | ✅ | Sin permisos nuevos. Los 403 existentes ahora se auditan (pruebas con recepción → lista de usuarios). Las pruebas unitarias de permisos y acciones siguen cubriendo positivos y negativos |
| 7 | Auditoría | ✅ | INSERT, UPDATE y DELETE con antes y después, usuario e IP; secretos protegidos; lecturas y accesos denegados; guardián de tablas auditadas; las escrituras de las tareas quedan con el usuario `tarea:<uuid>` |
| 8 | Sin datos de salud en logs, errores ni URLs | ✅ | **Búsqueda automática** en todos los logs de la corrida (`pytest_sessionfinish`): ningún nombre, documento, correo ni teléfono de los pacientes sintéticos. Prueba dirigida con ingreso fallido, código, fallo de correo, entrada inválida y tarea que lanza una excepción con datos del paciente. En el servidor real (log de ZAP y pruebas manuales): 0 coincidencias |
| 9 | ruff / bandit / pip-audit / gitleaks | ✅ | Limpios |
| 10 | ZAP pasivo + activo autenticado | ✅ | Altos 0 · Medios 0 · Bajos 0 · Informativos 4 (los mismos de la etapa 2). 58 peticiones autenticadas con 200; la sesión siguió válida; 0 respuestas 500 en el log del servidor |
| 11 | Fuzzing sin errores 500 | ✅ | schemathesis sobre todos los endpoints y fuzzing de formularios con CSRF válido (sin rutas nuevas en la etapa) |
| 12 | Pruebas manuales dirigidas | ✅ | 11 de 11 (ver abajo) |
| 13 | Rendimiento | N/A | Sin endpoints críticos nuevos |

## Pruebas manuales dirigidas

Script reproducible `scripts/pruebas_manuales/auditoria_tareas.py`, ejecutado contra el servidor HTTPS real y la base de desarrollo.

| Prueba | Resultado |
|--------|-----------|
| La lista de usuarios queda auditada con el usuario, la IP real (127.0.0.1) y el conteo de filas | ✅ |
| Un 403 real (recepción → usuarios) queda auditado como `DENEGADO` con el permiso que faltó | ✅ |
| La auditoría de lab-a es invisible desde lab-b | ✅ |
| SQL directo con `lablinea_app`: `UPDATE`, `DELETE`, `TRUNCATE` e `INSERT` sobre la auditoría → *permission denied* | ✅ (4) |
| SQL directo con `lablinea_app`: leer una partición directamente o la tabla `cola.tareas` → *permission denied* | ✅ (2) |
| Un trabajador muerto con `SIGKILL` a mitad de tarea: otro la retoma al vencer el plazo; la tarea queda completada en el intento 2 y su efecto ocurre una sola vez | ✅ |
| El log del servidor no contiene datos de los 20 pacientes sintéticos sembrados | ✅ |

## Hallazgos y resolución

| Hallazgo | Severidad | Detectado por | Resolución |
|----------|-----------|---------------|------------|
| **Las pruebas de logs no veían nada.** `fileConfig` de Alembic (en `migrations/env.py`) deshabilitaba todos los loggers ya creados y quitaba los handlers de la raíz al migrar en el fixture de sesión. Las pruebas de la etapa 2 sobre logs (p. ej. "el log de fallo de correo no lleva el correo") pasaban sin capturar ningún registro | Media (pruebas de seguridad sin efecto) | Prueba nueva de tareas que esperaba un registro y encontró el log vacío | `fileConfig(..., disable_existing_loggers=False)`; el colector de logs de la sesión se reinstala después de migrar. Las pruebas nuevas exigen que haya registros antes de buscar datos en ellos |
| Las particiones de una tabla con RLS **no heredan** sus políticas si se consultan directamente, y los privilegios por defecto del esquema `lab` les daban `SELECT` a la aplicación | Alta (habría permitido leer la auditoría de todos los laboratorios) | Diseño, antes de escribir la migración | Cada partición se crea con RLS forzado, su política y sin privilegios para la aplicación. Prueba y prueba manual |
| Insertar en la auditoría directamente habría permitido a la aplicación forjar escrituras falsas | Media | Diseño | Sin `INSERT` para la aplicación; triggers y `registrar_acceso` (`SECURITY DEFINER`), que solo admite `READ`, `EXPORT` y `ACCESO`. Prueba |
| El trigger de auditoría habría copiado el hash de la contraseña y el secreto TOTP cifrado | Alta | Diseño | Argumentos del trigger: columnas secretas (`[protegido]`) e ignoradas. Prueba |
| `TG_ARGV` es NULL en un trigger sin argumentos: fallaba toda escritura en roles | Alta (funcional) | Pruebas | `coalesce(TG_ARGV, '{}')` |
| Bandit: consulta armada con f-string y `subprocess` en el script manual | Baja | bandit | Nombre de partición literal; `nosec` justificado para `subprocess` |

## Pendientes (fuera del alcance de la etapa)

- Vista de la auditoría para el rol AUDITOR, con filtros y exportación (también auditada).
- Purga de tareas terminadas antiguas; rol de base de datos separado para el trabajador (etapa 20).
- Traducir los códigos de módulos y operaciones de permisos (con la administración de roles, etapa 4).
- Formatos de número y moneda por país en el catálogo (con el POS, etapa 8).

## Riesgos aceptados por el usuario

Ninguno.
