# 0011. Inventarios de insumos, equipos de laboratorio, proveedores y convenios

- **Estado:** Aceptada
- **Fecha:** 2026-10-14
- **Responsable:** Juan Otálora
- **Reemplaza:** las secciones 1 (Inventarios) y 2 (Equipos biomédicos) de [0006](0006-gestion-inventarios-costos-dashboard.md)
- **Base:** [0002](0002-pos-ordenes-caja.md) (convenios), [infraestructura/0010](../infraestructura/0010-analitica-bodega-datos.md) (bodega de datos), fuente 24 (inventarios y costeo)

## Contexto

Decisión del usuario del 2026-10-14: **los inventarios y los equipos entran al MVP**. El laboratorio necesita controlar dos cosas:

- sus insumos: reactivos y consumibles como jeringas, gasa y tapabocas, con lo que realmente le cuestan;
- sus equipos: hoja de vida, compra y mantenimientos.

Los proveedores de cada laboratorio necesitan su propio registro con contactos e histórico. Los convenios (las entidades con las que el laboratorio negocia exámenes para sus afiliados) son otra cosa y van en tablas aparte.

Nada de este módulo es dato de salud: no hay pacientes ni resultados. Igual vive en el esquema `lab`, con RLS, auditoría y permisos, porque son datos financieros y operativos de cada laboratorio.

## Decisión

### 1. Proveedores (por laboratorio)

- **Tabla propia de cada laboratorio**, independiente de los convenios:
  - identificación fiscal (tipo y número de documento, con dígito de verificación cuando el país lo usa);
  - razón social y nombre comercial;
  - dirección, ciudad, país, teléfono, correo y sitio web;
  - condiciones de pago y notas;
  - estado (activo o inactivo).
- **Contactos:** varios por proveedor, con nombre, cargo, teléfono y correo. Son datos personales de terceros: van protegidos en la auditoría (Ley 1581).
- **Roles:** proveedor de ítems de inventario (reactivos, consumibles, equipos y otros) y proveedor de mantenimiento de equipos, o ambos. El laboratorio solo compra: no vende ítems a terceros.
- **Histórico de transacciones:** la ficha del proveedor muestra todas sus compras (insumos y equipos) y sus mantenimientos, con fechas, documentos y valores, y totales por periodo.
- Un proveedor no se borra: se desactiva (el histórico lo referencia).

### 2. Ítems de inventario (insumos)

- **Tipos:** `REACTIVO`, `CONSUMIBLE` (jeringas, gasa, tapabocas, tubos, guantes…) y `OTRO`.
- **Datos del ítem:**
  - código, nombre, tipo y sección (opcional);
  - **unidad de consumo** (unidad, mL, prueba…);
  - stock mínimo para alertas;
  - ubicación;
  - si exige **lote y fecha de vencimiento** (sí por defecto en reactivos).
- **Unidades de compra:** cada ítem tiene una o varias presentaciones de compra con su **factor de conversión** a la unidad de consumo (p. ej. *caja × 100 unidades*, *kit × 96 pruebas*).

### 3. Compras de insumos

- **Documento de compra:** proveedor, número de factura, **fecha de adquisición**, moneda y soporte opcional (PDF o foto de la factura).
- **Cada línea** registra:
  - ítem, presentación de compra y cantidad en unidades de compra;
  - **costo total** de la línea;
  - lote y vencimiento cuando el ítem los exige.
- **Costo unitario calculado:** costo total ÷ (cantidad × factor de conversión), en `NUMERIC`, nunca `float`.
- **Ajuste manual del costo unitario:** opcional. Exige motivo y queda auditado con quién lo hizo y cuándo, junto al valor calculado. El costo que rige es el ajustado si existe; si no, el calculado.
- **Una compra registrada no se modifica:** si hay un error, se anula con motivo y se registra de nuevo, para que el costo del inventario no cambie sin rastro.
- La compra genera la **entrada** al inventario y actualiza el **costo promedio ponderado** del ítem.

### 4. Movimientos y existencias

- Entradas por compra; salidas por consumo, ajuste de conteo, vencimiento o daño, siempre con motivo y usuario.
- **El consumo se registra a mano** (decisión del 2026-10-14). El inventario no se descuenta solo al procesar un examen.
- Existencias por ítem y por lote. Se consume primero lo que vence primero (FEFO).
- **Alertas:** stock por debajo del mínimo y lotes que vencen pronto (días configurables por el laboratorio).

### 5. Equipos de laboratorio

- **Hoja de vida:**
  - código interno de inventario, nombre, marca, modelo, serie, sección y ubicación;
  - foto del equipo;
  - **proveedor**, **fecha de compra**, **número de factura** y soporte, **valor de compra** y moneda;
  - garantía hasta;
  - periodicidad del mantenimiento preventivo (para calcular el próximo).
- **Estado:** `OPERATIVO`, `EN_MANTENIMIENTO`, `FUERA_DE_SERVICIO` o `DADO_DE_BAJA` (con motivo y fecha). Un equipo no se borra.
- **Mantenimientos** de tipo `PREVENTIVO`, `CORRECTIVO` o `PREDICTIVO`:
  - **razón del mantenimiento** y **proveedor de mantenimiento** (de la tabla de proveedores);
  - **fecha de entrega** del equipo al proveedor, quién lo entrega y **foto de entrega** (estado en que sale);
  - **fecha de devolución**, quién lo recibe, foto de devolución y observaciones del resultado;
  - costo, factura y soporte del servicio.
  - Mientras hay un mantenimiento abierto (entregado y sin devolver), el equipo queda `EN_MANTENIMIENTO`.
  - Un mantenimiento cerrado no se modifica; las correcciones quedan auditadas.
- **Alertas:** mantenimiento preventivo vencido o próximo, y garantía por vencer.

### 6. Convenios (tablas aparte de los proveedores)

- Las entidades con las que el laboratorio negocia exámenes para sus afiliados (EPS, aseguradoras, medicina prepagada, empresas) van en **sus propias tablas**:
  - datos fiscales y de contacto, y contactos;
  - contrato (número, vigencia y soporte);
  - tarifa asociada;
  - **cobertura total o parcial**: lo que paga el convenio y lo que paga el afiliado (copago, cuota moderadora, porcentaje o valor);
  - **tope de descuento** y si exige autorización ([0002](0002-pos-ordenes-caja.md)).
- Un mismo NIT puede ser proveedor y convenio a la vez, como registros independientes. No se mezclan: los proveedores son cuentas por pagar, y los convenios, cuentas por cobrar y liquidación de órdenes.
- Se construyen con las órdenes (etapa 8), donde se usan.

### 7. Archivos (fotos y soportes)

- En el almacenamiento privado del laboratorio con URL firmada que vence (el mismo de las evidencias de descuento, [infraestructura/0007](../infraestructura/0007-base-de-datos.md)).
- Solo imágenes JPEG, PNG o WebP y PDF, validados por su contenido (no por la extensión), con tamaño máximo.
- **A las fotos se les quitan los metadatos EXIF** (ubicación GPS, dispositivo) antes de guardarlas.
- Para validar y limpiar imágenes se usa **Pillow**, que ya llega como dependencia de WeasyPrint; se declara explícitamente en `requirements.txt` con rango acotado.

### 8. Permisos, auditoría y bodega

- **Módulos nuevos** en `global.modulos`: `inventario` (ítems, compras, movimientos), `equipos` (hoja de vida y mantenimientos) y `proveedores`. Los planes de la plataforma los habilitan.
- **Roles iniciales:**
  - administrador: todo;
  - bacteriólogo: consulta inventario y equipos, registra consumos y entrega o devolución de mantenimientos;
  - auditor: consulta.
- Todas las tablas auditadas por trigger. Los contactos de proveedores y convenios van protegidos en la auditoría.
- La **bodega de datos** recibe compras, movimientos, costos y mantenimientos (sin datos de contacto) para los indicadores de costos, consumo y disponibilidad de equipos.

## Alternativas consideradas

- **Proveedores y convenios en una sola tabla de "terceros":** menos tablas, pero mezcla cuentas por pagar con cuentas por cobrar y reglas de cobertura. El usuario decidió separarlos.
- **Costo unitario solo calculado, sin ajuste:** más simple, pero no cubre bonificaciones, descuentos fuera de factura ni unidades de cortesía. El ajuste queda permitido con motivo y auditoría.
- **Costo por último precio de compra en vez de promedio ponderado:** sigue mejor la inflación, pero hace saltar los márgenes con cada compra.

## Consecuencias

- **Plan:** nueva etapa 14b, *Inventarios, equipos y proveedores*, antes de la bodega analítica. Los convenios se construyen en la etapa 8.
- El almacenamiento privado de archivos (etapa 8) se reutiliza aquí.
- **Quedan para después del MVP** (decisión del 2026-10-14): el **descuento automático de insumos por examen procesado** y el **costeo por actividad con nómina ligera** (sección 3 de [0006](0006-gestion-inventarios-costos-dashboard.md)). El dashboard del MVP muestra costo de compras, consumo registrado y disponibilidad de equipos, pero no el costo real por examen.
