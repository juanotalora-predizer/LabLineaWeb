SaaS POS reglas y configuracion
Para blindar financieramente al laboratorio contra fraudes, manipulación de tarifas a última hora y desfalcos en caja, implementaremos dos pilares fundamentales: el Pre-cierre y Congelamiento de Órdenes, y un Módulo de POS / Caja Registradora con Arqueo y Cierre de Turno completo.
Mecanismo de Pre-Cierre e Inmutabilidad de la Orden
Para evitar que una orden sea modificada una vez cotizada y mostrada al paciente, introducimos una máquina de estados estricta en la tabla orden:
⚬ Estado BORRADOR: El recepcionista selecciona exámenes, calcula tarifas y aplica descuentos. La orden aún es editable. ⚬ Estado PRE_CERRADA (El Candado): Al hacer clic en "Cerrar Cuenta / Enviar a Caja", la orden se bloquea por completo. El sistema congela los valores definitivos, el número de exámenes, los descuentos y la tarifa. Ya no se pueden agregar, quitar exámenes ni modificar precios. ⚬ Estado PAGADA: Una vez el cajero recibe el dinero (efectivo, tarjeta, Nequi) o se valida el convenio empresarial, el sistema registra el pago y la orden pasa a estado PAGADA, habilitando la toma de muestras y el laboratorio.
-- Añadir campos de control de estado y pre-cierre en la tabla 'orden' ALTER TABLE orden ADD COLUMN estado_orden VARCHAR(20) DEFAULT 'BORRADOR', -- BORRADOR, PRE_CERRADA, PAGADA, ANULADA ADD COLUMN fecha_precierre TIMESTAMP, ADD COLUMN usuario_precierre VARCHAR(50);
Módulo de POS, Caja, Base, Cuadre y Cierres de Turno
Para que cada ventanilla o puesto de recepción funcione como una caja registradora profesional con control total de efectivo y medios de pago, añadimos el siguiente esquema DDL en PostgreSQL:
-- Aperturas y Cierres de Caja por Turno / Estación CREATE TABLE saas_cajas_sesiones ( id SERIAL PRIMARY KEY, tenant_id VARCHAR(50) NOT NULL, codigo_sede VARCHAR(2) NOT NULL, estacion_trabajo_id INTEGER NOT NULL, usuario_cajero VARCHAR(50) NOT NULL, fecha_apertura TIMESTAMP DEFAULT CURRENT_TIMESTAMP, monto_base_inicial NUMERIC(12,2) NOT NULL DEFAULT 0.00, -- Dinero base con el que abre la caja fecha_cierre TIMESTAMP, monto_total_esperado_cierre NUMERIC(12,2), -- Calculado por el sistema (Base + Efectivo de órdenes) monto_real_declarado NUMERIC(12,2), -- Lo que el cajero cuenta físicamente al cerrar diferencia_cuadre NUMERIC(12,2) DEFAULT 0.00, -- Sobrante (+) o Faltante (-) estado_caja VARCHAR(20) DEFAULT 'ABIERTA', -- ABIERTA, CERRADA, ARQUEADA observaciones_cierre TEXT, CONSTRAINT fk_sesion_estacion FOREIGN KEY (estacion_trabajo_id) REFERENCES saas_estaciones_trabajo(id) ); CREATE INDEX idx_caja_tenant_usuario ON saas_cajas_sesiones(tenant_id, usuario_cajero);
-- Detalle de Transacciones de Pago por Sesión de Caja (Para el Cuadre Diario) CREATE TABLE saas_caja_transacciones ( id SERIAL PRIMARY KEY, sesion_caja_id INTEGER NOT NULL, orden_id INTEGER NOT NULL, fecha_pago TIMESTAMP DEFAULT CURRENT_TIMESTAMP, forma_pago VARCHAR(30) NOT NULL, -- EFECTIVO, TARJETA, TRANSFERENCIA, NEQUI valor_pagado NUMERIC(12,2) NOT NULL, referencia_externa VARCHAR(100), -- Voucher o código de pasarela CONSTRAINT fk_trans_sesion FOREIGN KEY (sesion_caja_id) REFERENCES saas_cajas_sesiones(id), CONSTRAINT fk_trans_orden FOREIGN KEY (orden_id) REFERENCES orden(consecutivo) );
Lógica del POS y Flujo de Caja en FastAPI
from fastapi import APIRouter, HTTPException, status from pydantic import BaseModel
router = APIRouter(prefix="/api/v1/caja", tags=["POS y Control de Caja"])
class AperturaCajaDTO(BaseModel): tenant_id: str codigo_sede: str estacion_trabajo_id: int usuario_cajero: str monto_base_inicial: float
class CierreCajaDTO(BaseModel): sesion_caja_id: int monto_real_declarado: float observaciones: str
@router.post("/abrir-turno") async def abrir_turno_caja(datos: AperturaCajaDTO): """ Abre una nueva sesión de caja registradora asignando el dinero base inicial. """ # Validar que el usuario no tenga otra caja abierta simultáneamente # INSERT INTO saas_cajas_sesiones (...) VALUES (...) return {"status": "success", "message": "Turno de caja abierto correctamente con base inicial."}
@router.post("/precerrar-orden/{numero_orden}") async def precerrar_orden(numero_orden: int, tenant_id: str, usuario: str): """ Aplica el 'candado' de seguridad. Congela los precios y pasa la orden a PRE_CERRADA para evitar modificaciones fraudulentas antes de pasar a caja a pagar. """ query = """ UPDATE orden SET estado_orden = 'PRE_CERRADA', fecha_precierre = CURRENT_TIMESTAMP, usuario_precierre = :usuario WHERE tenant_id = :tenant AND numero_de_la_orden = :ord AND estado_orden = 'BORRADOR'; """ # Si no se actualizó filas, significa que ya estaba pagada o pre-cerrada return {"status": "success", "message": "Orden pre-cerrada con éxito. Ya no puede ser modificada."}
@router.post("/cerrar-turno") async def cuadre_y_cierre_turno(datos: CierreCajaDTO): """ Realiza el arqueo de caja al finalizar el turno: Calcula el dinero esperado (Base inicial + Total recaudado en efectivo) y lo compara con el dinero real contado por el cajero para detectar sobrantes o faltantes. """ # 1. Sumar la base inicial de la sesión # 2. Sumar todos los pagos en EFECTIVO registrados en saas_caja_transacciones para esta sesión total_efectivo_recaudado = 1505000.00 # Ejemplo calculado de la BD monto_base = 100000.00 # Ejemplo de base inicial
```
monto_esperado = monto_base + total_efectivo_recaudado
diferencia = datos.monto_real_declarado - monto_esperado # Si es negativo es faltante, si es positivo es sobrante

# 3. Actualizar la sesión de caja a CERRADA
"""
UPDATE saas_cajas_sesiones
SET fecha_cierre = CURRENT_TIMESTAMP,
    monto_total_esperado_cierre = :esperado,
    monto_real_declarado = :real,
    diferencia_cuadre = :dif,
    estado_caja = 'CERRADA',
    observaciones_cierre = :obs
WHERE id = :sesion_id;
"""

return {
    "status": "success",
    "monto_esperado": monto_esperado,
    "monto_declarado": datos.monto_real_declarado,
    "diferencia": diferencia,
    "mensaje": "Cierre de caja procesado. Cuadrado correctamente." if diferencia == 0 else f"Atención: Se registra una diferencia de {diferencia}"
}
```
Controles Clave Logrados:
Bloqueo Total del Fraude: Al ejecutar el Pre-Cierre, se congela la orden. Ningún empleado puede alterar tarifas por debajo de cuerda tras cobrarle al paciente.
Arqueo Transparente: Al entregar turno, el sistema exige declarar el efectivo contado, lo cruza automáticamente con las ventas en efectivo del día y la base inicial, generando alertas inmediatas si hay diferencias de cartera o desfalcos.