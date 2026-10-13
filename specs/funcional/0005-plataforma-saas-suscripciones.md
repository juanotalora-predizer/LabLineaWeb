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

Lo pendiente de la etapa 4 se construyó en la etapa 5 (abajo).

## Implementación (etapa 5, 2026-10-13)

Ver [informe de la etapa 5](../etapas/etapa-05.md). Migración `0006`.

- **Licencias:**

  | Licencia | Duración | Cobro | Máx. usuarios |
  |---|---|---|---|
  | `DEMO` | 30 días | No | 3 |
  | `AD_HONOREM` | Indefinida | No | Sin límite |
  | `GRATUITO_BASICO` | Indefinida | No | 2 |
  | `MENSUAL` | 1 mes | Sí | Sin límite |
  | `ANUAL` | 1 año | Sí | Sin límite |

  El límite efectivo de usuarios es el menor entre el del plan y el de la licencia.
- **Suscripción:** una por laboratorio.
  - El alta la crea con la licencia elegida. Las facturables tienen 7 días para pagar la primera factura.
  - **Estado efectivo:** una suscripción activa con fecha de fin pasada ya cuenta como vencida, aunque el trabajador todavía no la haya marcado.
  - Desde el Admin Hub se puede suspender (con motivo), reactivar, cancelar, activar o quitar la renovación automática y cambiar a una licencia sin cobro. Las licencias con cobro se activan pagando.
- **Bloqueo:** sin suscripción vigente, la dependencia `SuscripcionVigente` responde 403 y lo audita. **La usarán las rutas que crean órdenes (etapa 8)**. El ingreso, la consulta y la exportación nunca la usan. El laboratorio ve un aviso en todas sus páginas.
- **Avisos de renovación:** el trabajador marca las suscripciones vencidas y encola un correo a la administración del laboratorio 7 días y 1 día antes del vencimiento, una sola vez por umbral. La fecha se muestra en la zona horaria del laboratorio.
- **Precios y campañas:**
  - El precio depende de país, plan, licencia y moneda, y tiene fecha de vigencia.
  - Las campañas son un porcentaje de descuento con vigencia, para todas las licencias o para una sola. Si aplican varias, se usa la de mayor descuento.
  - El impuesto sale de la configuración del país (`global.paises.impuesto_servicios`). Colombia: 19 %, **por validar con el asesor tributario**.
- **Facturas:**
  - Numeración `PLT-000001`. Cada factura cubre el siguiente periodo de la suscripción y vence a los 15 días.
  - Montos en `NUMERIC`, con redondeo al medio hacia arriba en los decimales de la moneda.
  - **Inmutables:** la plataforma no puede actualizar ni borrar facturas ni pagos; solo crearlos y anularlos con funciones que verifican las reglas. Ni el dueño de la base puede cambiar los montos.
- **Pagos:**
  - Medios: transferencia, consignación, efectivo, tarjeta u otro, con referencia.
  - Un pago nunca supera el saldo; esto se mantiene también con pagos simultáneos, porque la base bloquea la factura.
  - El saldo y el estado (`PENDIENTE`, `PAGADA_PARCIAL`, `PAGADA`) se recalculan con cada pago o anulación.
  - **Al quedar pagada, la suscripción se activa y se extiende hasta el final del periodo facturado.**
  - Un pago se anula con motivo. Una factura solo se anula si no tiene pagos vigentes.
- **Renovación automática:** si está activada y la suscripción vence en 7 días o menos, el trabajador genera la factura del siguiente periodo, una sola vez.
- Es un documento interno de cobro. La factura electrónica ante la DIAN llega en la etapa 11 ([infraestructura/0009](../infraestructura/0009-facturacion-electronica.md)).
