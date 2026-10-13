SaaS Convenios Descuentos
Para garantizar la inmutabilidad financiera histórica (evitar que si el laboratorio cambia sus tarifas mañana, las órdenes pasadas se alteren) y cumplir con un control estricto de auditoría y convenios para descuentos, realizaremos las siguientes incorporaciones clave en la base de datos y la lógica del POS:
Extensión del Esquema DDL en PostgreSQL
Actualizamos el modelo para congelar el valor histórico en la orden de cada examen, estructurar la tabla de convenios/reglas de descuento, y registrar obligatoriamente la evidencia digital (PDF o foto) de cada descuento aplicado.
-- Tabla de Convenios y Límites de Descuentos Configurados por el Área Financiera CREATE TABLE saas_convenios_descuentos ( consecutivo SERIAL PRIMARY KEY, tenant_id VARCHAR(50) NOT NULL, codigo_convenio VARCHAR(30) NOT NULL, nombre_convenio VARCHAR(100) NOT NULL, porcentaje_maximo_permitido NUMERIC(5,2) DEFAULT 0.00 NOT NULL, -- Límite máximo autorizado sin aprobación especial requiere_autorizacion_superior BOOLEAN DEFAULT TRUE, activo BOOLEAN DEFAULT TRUE, CONSTRAINT uk_tenant_convenio UNIQUE (tenant_id, codigo_convenio) );
-- Modificación en 'analisis_por_orden' para CONGELAR el valor histórico al momento del POS ALTER TABLE analisis_por_orden ADD COLUMN valor_unitario_historico NUMERIC(12,2) NOT NULL DEFAULT 0.00, ADD COLUMN valor_total_historico NUMERIC(12,2) NOT NULL DEFAULT 0.00;
-- Modificación en la tabla 'orden' para registrar el convenio y la evidencia obligatoria del descuento ALTER TABLE orden ADD COLUMN convenio_descuento_id INTEGER, ADD COLUMN porcentaje_descuento_aplicado NUMERIC(5,2) DEFAULT 0.00, ADD COLUMN evidencia_descuento_url TEXT, -- URL del PDF o Foto subida al Storage (S3 / Supabase / Google Cloud) ADD COLUMN usuario_autoriza_descuento VARCHAR(50), CONSTRAINT fk_orden_convenio FOREIGN KEY (convenio_descuento_id) REFERENCES saas_convenios_descuentos(consecutivo);
Lógica del POS en FastAPI: Captura Histórica y Reglas de Descuento
Cuando el recepcionista selecciona los exámenes en la interfaz de React del POS, el backend en FastAPI ejecuta la siguiente lógica transaccional:
Búsqueda de Tarifa al Instante: Consulta la tabla costo_analisis usando el tipo de tarifa del paciente y copia inmediatamente ese valor en el campo valor_unitario_historico de la tabla analisis_por_orden. Así, el precio queda grabado en piedra para esa orden específica.
Validación de Límites de Descuento (Control Financiero): ⚬ Si el usuario del POS aplica un descuento que supera el porcentaje_maximo_permitido configurado en el convenio del área financiera, el sistema bloquea la venta a menos que ingrese las credenciales de un rol superior y exija obligatoriamente la subida del archivo de evidencia (PDF o foto de la autorización/justificación médica o corporativa).
from fastapi import APIRouter, HTTPException, UploadFile, File, Form from pydantic import BaseModel from typing import List, Optional
router = APIRouter(prefix="/api/v1/pos", tags=["POS y Órdenes"])
class ItemExamenPOS(BaseModel): analisis_id: int tipo_tarifa: str
class CreacionOrdenPOS(BaseModel): tenant_id: str numero_orden: int paciente_id: int tipo_tarifa: str convenio_id: Optional[int] = None porcentaje_descuento: float = 0.00 examenes: List[ItemExamenPOS]
@router.post("/crear-orden") async def registrar_orden_en_pos( datos_orden: CreacionOrdenPOS, evidencia_archivo: Optional[UploadFile] = None ): """ Registra la orden en el POS, congela los precios históricos de los exámenes y valida los topes de descuentos con su respectiva evidencia obligatoria. """ # 1. Validar si el descuento supera el límite del convenio financiero if datos_orden.porcentaje_descuento > 0: # Consultar el convenio en BD para ver su porcentaje_maximo_permitido porcentaje_maximo_permitido = 15.00 # Ejemplo obtenido de saas_convenios_descuentos
```
    if datos_orden.porcentaje_descuento > porcentaje_maximo_permitido:
        if not evidencia_archivo:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Control Financiero: El descuento aplicado supera el límite permitido "
                    "para este convenio. Es obligatorio adjuntar una foto o PDF como evidencia."
                )
            )
        # Subir archivo al bucket de almacenamiento (S3/Supabase Storage) y obtener URL
        url_evidencia = f"https://storage.saas.com/evidencias/{evidencia_archivo.filename}"
    else:
        url_evidencia = None

# 2. Iterar sobre cada examen, consultar su tarifa actual y CONGELAR el valor histórico
for examen in datos_orden.examenes:
    # SELECT costo FROM costo_analisis WHERE tipo_tarifa = ... AND analisis = ...
    costo_vigente = 50000.00 # Valor simulado de la tabla maestra en ese instante
    
    # INSERT INTO analisis_por_orden (..., valor_unitario_historico, valor_total_historico)
    # VALUES (..., costo_vigente, costo_vigente * cantidad)
    pass

return {
    "status": "success", 
    "message": "Orden creada con éxito. Precios históricos congelados y descuentos auditados."
}
```
Auditoría Financiera de Descuentos Excesivos
Para que el área financiera pueda auditar en cualquier momento si los cajeros o personal de recepción están abusando de los descuentos:
⚬ Se crea una vista o reporte automático en el panel del Super Administrador SaaS / Administrador del Laboratorio que cruza la tabla orden con saas_convenios_descuentos y la auditoria_sensible que diseñamos anteriormente. ⚬ Cualquier orden con descuentos atípicos o que hayan requerido evidencia quedará marcada para revisión gerencial con un enlace directo al PDF o foto de respaldo guardada en la base de datos.