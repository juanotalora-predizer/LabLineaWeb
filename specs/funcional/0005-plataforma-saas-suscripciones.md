# 0005. Plataforma SaaS: laboratorios, licencias y facturación

- **Estado:** Aceptada
- **Fecha:** 2026-10-12
- **Responsable:** Juan Otálora
- **Fuentes:** [01 Clientes SaaS](../fuentes/), [10 Contabilidad SaaS](../fuentes/), [19 y 20 Pasarela de pagos](../fuentes/), [23 Roles SaaS](../fuentes/), [27 Tablas maestras](../fuentes/), [09 Auditoría SaaS](../fuentes/)

## Contexto

Además del LIS que usa cada laboratorio, la plataforma necesita su propia administración: registrar laboratorios clientes, venderles licencias, facturarles y cobrarles.

## Decisión

### 1. Administración de la plataforma

- Usuarios de la plataforma (nosotros) separados de los usuarios de los laboratorios, con sus propios roles (p. ej. administrador maestro, soporte financiero, gerente comercial) y permisos por módulo.
- Estas cuentas **no acceden a datos clínicos** de los laboratorios, salvo el acceso de soporte autorizado y auditado de [infraestructura/0005](../infraestructura/0005-arquitectura-saas-multitenant.md).
- Auditoría propia de las tablas de la plataforma (facturas, pagos, listas de precios).

### 2. Laboratorios (tenants)

Registro con nombre comercial, NIT o identificador fiscal, país, contacto y estado. Al crearse, el laboratorio recibe su subdominio, su configuración por país y un usuario administrador inicial.

### 3. Licencias y suscripciones

- **Tipos de licencia:** `DEMO`, `AD_HONOREM`, `GRATUITO_BASICO`, `MENSUAL`, `ANUAL`, con duración y límites (p. ej. número máximo de usuarios).
- **Listas de precios** por país, tipo de licencia y moneda, con **campañas** de descuento con vigencia.
- **Suscripción** por laboratorio: estados `ACTIVA`, `SUSPENDIDA`, `VENCIDA`, `CANCELADA`, con renovación automática opcional.
- Una suscripción vencida o suspendida bloquea crear órdenes nuevas, pero **nunca bloquea consultar resultados ya emitidos** ni la exportación de datos del laboratorio ([infraestructura/0004](../infraestructura/0004-normativa-colombia-latam.md)).

### 4. Facturación y cartera

- Facturas de la plataforma al laboratorio por suscripción, con moneda, tasa de cambio, impuestos según el país y saldo pendiente.
- Pagos y abonos parciales; el saldo y el estado de la factura (`PENDIENTE`, `PAGADA_PARCIAL`, `PAGADA`, `ANULADA`) se recalculan con cada pago.
- Al quedar pagada, la suscripción se activa o extiende automáticamente.

### 5. Pasarela de pagos

- Integración por **webhooks**: se valida la firma criptográfica de cada notificación y se procesa de forma **idempotente** (la misma notificación dos veces no registra dos pagos).
- **Colombia:** pasarela local (Wompi, ePayco o PayU) para cobrar en COP con tarjeta, PSE y Nequi.
- **Internacional:** Stripe requiere una entidad legal en EE. UU.; se evalúa al expandirse.

## Alternativas consideradas

- **Cobro manual por transferencia:** suficiente con pocos clientes, pero no escala; queda como mecanismo de respaldo.
- **Stripe desde el inicio vía LLC en EE. UU.:** simplifica la facturación recurrente internacional, pero agrega una estructura legal antes de tener clientes fuera de Colombia.

## Consecuencias

- En el MVP: laboratorios, licencias, suscripciones y facturación con registro manual de pagos. La pasarela automática va después del MVP ([0007](0007-alcance-mvp.md)).
- Las facturas de la plataforma a laboratorios colombianos se emiten como factura electrónica con la misma integración directa con la DIAN ([infraestructura/0009](../infraestructura/0009-facturacion-electronica.md)).
- **Sin comisiones** en el Admin Hub por ahora (decidido el 2026-10-12).
- **Pendiente:** elegir la pasarela de pagos para Colombia.

## Implementación (etapa 4, 2026-10-13)

Ver [informe de la etapa 4](../etapas/etapa-04.md). Migración `0005`.

- **Admin Hub** en `admin.<dominio>`, con el mismo ingreso que los laboratorios (contraseña, TOTP obligatorio, sesiones `__Host-`), pero con sus propias tablas en el esquema `plataforma` y su propio rol de base de datos, sin acceso a `lab`. Una sesión, un usuario o una cookie de un sitio no sirven en el otro.
- **Roles de la plataforma** (`app/admin/roles.py`): `ADMIN_MAESTRO` (todo), `GERENTE_COMERCIAL` (laboratorios, consulta de planes, suscripciones) y `SOPORTE_FINANCIERO` (consulta de laboratorios, suscripciones, facturación). El personal se crea con `scripts/crear_usuario_plataforma.py`; la contraseña se pide por consola.
- **Alta de laboratorio en una transacción** (`plataforma.alta_laboratorio`):
  - Crea el laboratorio con su subdominio y plan, la sede principal, los roles del sistema y el administrador.
  - El `tenant_id` sale del subdominio (`lab_<subdominio>`).
  - Si algo falla, no queda nada.
  - El administrador **no recibe contraseña de la plataforma**: le llega un enlace de activación de un solo uso (72 horas) y crea la suya ([infraestructura/0008](../infraestructura/0008-autenticacion-autorizacion.md)).
  - La auditoría del laboratorio registra al usuario de la plataforma que lo creó (`plataforma:<uuid>`).
- **Planes:**
  - Código, nombre, máximo de usuarios (personal y médicos activos; vacío = sin límite) y módulos incluidos.
  - `usuarios` y `configuracion` están siempre activos.
  - Fuera del plan, los permisos del módulo no aplican: 403 y el módulo sale del menú.
  - El plan `COMPLETO` incluye todos los módulos; los laboratorios existentes quedaron en él.
- **Auditoría de la plataforma** (`plataforma.auditoria`): las escrituras en laboratorios, planes, módulos de plan, usuarios, roles y permisos quedan registradas por trigger. Lecturas y accesos denegados quedan registrados desde la aplicación. Es de solo inserción.

**Pendiente para la etapa 5:** tipos de licencia, suscripciones con vencimiento y suspensión, facturas con pagos manuales y acceso de soporte autorizado.
