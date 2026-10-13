# 0007. Base de datos: PostgreSQL con RLS

- **Estado:** Aceptada
- **Fecha:** 2026-10-12
- **Responsable:** Juan Otálora
- **Fuentes:** [03 Nuevo DDL](../fuentes/), [04 Auditoría](../fuentes/), [05 Diagnóstico inmutable](../fuentes/), [06 Resumen técnico](../fuentes/), [08 Row-Level Security](../fuentes/), [02 DDL original](../fuentes/)

## Contexto

Las fuentes proponen PostgreSQL con `tenant_id`, Row-Level Security (RLS), triggers de auditoría e inmutabilidad de resultados. Coincide con [0005](0005-arquitectura-saas-multitenant.md), pero el DDL de las fuentes tiene huecos que dejarían el aislamiento sin efecto. Esta spec fija el motor y las reglas del esquema.

## Decisión

### 1. Motor y acceso

- **PostgreSQL 16 o superior.**
- Acceso desde Python con **SQLAlchemy 2 (async) + asyncpg**; migraciones con **Alembic**. Solo consultas parametrizadas.

### 2. Esquemas

| Esquema | Contenido | RLS |
|---------|-----------|-----|
| `plataforma` | Laboratorios, licencias, suscripciones, facturas y usuarios de la plataforma | No; solo accesible por el rol de administración de la plataforma |
| `global` | Catálogos compartidos de solo lectura: países, monedas, tipos de documento, terminologías | No; la aplicación solo lee |
| `lab` | Todo dato de un laboratorio: pacientes, órdenes, resultados, catálogo propio, caja, muestras… | **Sí, en todas las tablas** |

Las fuentes prefijan con `saas_` tanto tablas de la plataforma como tablas del laboratorio (p. ej. `saas_estaciones_trabajo`, `saas_convenios_descuentos`); se reorganizan por esquema y se elimina el prefijo.

### 3. Aislamiento por tenant (corrige la fuente 08)

- Toda tabla de `lab` tiene `tenant_id NOT NULL` y política RLS con `USING` **y** `WITH CHECK` (sin `WITH CHECK` se podría insertar en otro tenant).
- **`FORCE ROW LEVEL SECURITY`** en todas: sin esto, el dueño de la tabla ignora las políticas.
- La aplicación se conecta con un **rol sin privilegios de dueño** y sin `BYPASSRLS`. Las migraciones usan otro rol.
- El tenant se fija por transacción con `SET LOCAL app.current_tenant` (no `SET`), para que no se filtre entre peticiones que comparten conexión del pool.
- Sin tenant definido, las políticas no devuelven filas.
- Llaves foráneas compuestas con `tenant_id` donde aplique, para que una orden no pueda referenciar un paciente de otro tenant.

### 4. Identificadores

- Llave primaria interna `BIGINT GENERATED ALWAYS AS IDENTITY` con nombre uniforme `id` (las fuentes mezclan `id` y `consecutivo`, lo que rompe el trigger genérico de auditoría).
- Columna `uuid` única para URLs y API ([0005](0005-arquitectura-saas-multitenant.md)). Los consecutivos visibles para el usuario (número de orden) son por tenant.
- `tenant_id` es un código legible (p. ej. `lab_vida_cali`), inmutable.

### 5. Auditoría

- Triggers en las tablas sensibles registran operación, usuario, IP, fecha y **el registro antes y después del cambio** (fuente 04). El usuario y la IP se fijan con `SET LOCAL` en cada transacción.
- La tabla de auditoría es de **solo inserción** (sin `UPDATE` ni `DELETE` para ningún rol de la aplicación), está bajo RLS y se protege igual que los datos clínicos, porque contiene datos de salud. Ajusta [0003](0003-seguridad-hipaa.md).
- Los triggers solo ven escrituras. Las **lecturas** de datos de salud (ver un resultado, descargar un PDF) se auditan desde la aplicación.
- Particionada por mes; conservación mínima de 6 años.

### 6. Inmutabilidad

- Resultados: solo inserción, con trigger que rechaza `UPDATE` y `DELETE` y además sin esos permisos para el rol de la aplicación (fuente 05). Correcciones como nuevas versiones ([funcional/0004](../funcional/0004-resultados-validacion-entrega.md)).
- Órdenes pre-cerradas: un trigger rechaza cambios en precios y exámenes cuando el estado no es `BORRADOR` ([funcional/0002](../funcional/0002-pos-ordenes-caja.md)).

### 7. Tipos de datos

- Dinero en `NUMERIC(14,2)` con código de moneda y tasa de cambio en la transacción; nunca `float`.
- Fechas y horas en `TIMESTAMPTZ` (UTC) ([0004](0004-normativa-colombia-latam.md)). Se reemplazan los pares `fecha_digitacion` + `hora_digitacion` de Lablinea por un solo `TIMESTAMPTZ`.
- Fecha de nacimiento como `DATE`; la edad se calcula, no se guarda.
- Sin valores por defecto específicos de un país en el esquema (p. ej. `res_habitual DEFAULT '76001'`, `tipo_id DEFAULT 'CC'`, `moneda DEFAULT 'COP'`): salen de la configuración del país del tenant.

### 8. Archivos

PDFs de resultados, firmas, logos y evidencias de descuentos en almacenamiento de objetos **privado y cifrado**, con una ruta por tenant, y acceso solo por URL firmada de corta duración. El proveedor debe firmar BAA ([0003](0003-seguridad-hipaa.md)).

## Alternativas consideradas

- **ORM sin RLS, solo filtros en la aplicación:** descartado en [0005](0005-arquitectura-saas-multitenant.md).
- **Mantener el DDL de las fuentes tal cual:** sin `FORCE`, `WITH CHECK` ni `SET LOCAL`, el RLS puede no aplicarse o filtrar datos entre peticiones.

## Consecuencias

- Toda migración nueva de una tabla en `lab` incluye `tenant_id`, sus políticas RLS y `FORCE`. Se agrega una prueba que recorre el catálogo de PostgreSQL y falla si alguna tabla de `lab` no cumple.
- El proveedor de hosting debe ofrecer PostgreSQL 16+ administrado, cifrado y con BAA (decisión pendiente).
