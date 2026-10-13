# 0002. POS, órdenes y caja

- **Estado:** Aceptada
- **Fecha:** 2026-10-12
- **Responsable:** Juan Otálora
- **Fuentes:** [11 Convenios y descuentos](../fuentes/), [17 POS reglas y configuración](../fuentes/), [18 Paquetes de exámenes](../fuentes/), [02 DDL original](../fuentes/)

## Contexto

La recepción del laboratorio funciona como un punto de venta: registra al paciente, arma la orden de exámenes, aplica la tarifa y los descuentos del convenio, y cobra. Las fuentes identifican tres riesgos que el sistema debe bloquear: cambiar precios después de cotizar, dar descuentos sin control y faltantes de dinero en caja.

## Decisión

### 1. Ciclo de vida de la orden

| Estado | Qué se puede hacer | Quién pasa al siguiente |
|--------|-------------------|------------------------|
| `BORRADOR` | Agregar o quitar exámenes y paquetes, cambiar tarifa, aplicar descuentos | Recepción: "Cerrar cuenta" |
| `PRE_CERRADA` | Nada: exámenes, tarifas y descuentos quedan congelados | Caja registra el pago, o se valida la autorización del convenio |
| `PAGADA` | Habilita la toma de muestras | Flujo de muestras ([0003](0003-muestras-impresion.md)) |
| `ANULADA` | Ninguna operación | — |

- Al pasar a `PRE_CERRADA` se congela en cada examen de la orden su **valor unitario y total histórico**. Cambios posteriores de tarifas no alteran órdenes existentes.
- Una orden `PRE_CERRADA` o `PAGADA` no se edita: si hay error, se **anula** (rol autorizado + motivo obligatorio) y se crea una nueva. Toda anulación queda auditada.
- En órdenes de convenio, `PAGADA` significa "liquidada": cubierta por el convenio con su número de autorización registrado, más el copago si aplica.

### 2. Tarifas, convenios y descuentos

- Cada examen tiene precio por **tipo de tarifa** y moneda. La tarifa vigente se toma según sus fechas de inicio y fin.
- **Convenios** (empresas, aseguradoras) con tarifa propia, reglas de copago y un **porcentaje máximo de descuento** configurado por el área financiera.
- Si el descuento supera el máximo del convenio, la orden no avanza hasta que:
  1. un usuario con rol superior lo autorice con sus credenciales, y
  2. se adjunte **evidencia obligatoria** (PDF o foto).
- Las órdenes con descuentos que requirieron autorización quedan marcadas para revisión gerencial.

### 3. Paquetes de exámenes

- Combos (p. ej. "Perfil ejecutivo", "Ingreso laboral") con **precio global** por tipo de tarifa y moneda.
- Al seleccionarlo, el POS muestra la suma de precios individuales, el precio del paquete y el ahorro (valor y porcentaje).
- Al pre-cerrar, el paquete se registra **desglosado por examen**, con el precio global distribuido proporcionalmente, para que la rentabilidad por examen sea calculable.

### 4. Caja

- Cada **estación de trabajo** de tipo POS abre una **sesión de caja** con una base inicial. Un cajero no puede tener dos cajas abiertas.
- Cada pago se registra en la sesión con su forma de pago (efectivo, tarjeta, transferencia, Nequi u otras configurables por país) y su referencia externa.
- **Cierre y arqueo:** el cajero declara el efectivo contado; el sistema calcula lo esperado (base + efectivo recibido) y registra la diferencia. El cierre es irreversible.
- Abonos parciales permitidos; el saldo de la orden se calcula siempre a partir de los pagos registrados.

### 5. Reglas técnicas

- El tenant se toma del contexto del servidor, **nunca** del cuerpo de la petición (las fuentes lo envían en el DTO; se corrige según [infraestructura/0005](../infraestructura/0005-arquitectura-saas-multitenant.md)).
- Los archivos de evidencia van al almacenamiento privado del tenant; se accede con URL firmada de corta duración.
- Montos en `NUMERIC`, nunca en `float`. Moneda y tasa de cambio guardadas en cada orden.

## Alternativas consideradas

- **Permitir editar órdenes pagadas con auditoría:** más flexible, pero es exactamente la puerta al fraude que las fuentes buscan cerrar.
- **Precio de paquete como línea única:** más simple, pero impide calcular rentabilidad por examen.

## Consecuencias

- La toma de muestras depende del estado `PAGADA`.
- **Pendiente:** en Colombia la venta a particulares exige factura electrónica o documento equivalente electrónico (DIAN). Hay que decidir si el LIS la emite (integración con proveedor tecnológico) o si el laboratorio usa su propio sistema de facturación.
- Medios de pago y formas de copago son configuración por país ([infraestructura/0004](../infraestructura/0004-normativa-colombia-latam.md)).
