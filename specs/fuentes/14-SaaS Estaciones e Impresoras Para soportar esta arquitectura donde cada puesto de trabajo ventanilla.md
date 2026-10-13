SaaS Estaciones e Impresoras
Para soportar esta arquitectura donde cada puesto de trabajo, ventanilla POS o módulo de toma de muestras tiene asignada su propia impresora física de etiquetas, necesitamos resolver un reto clásico en aplicaciones web: cómo hacer que la nube (tu backend en FastAPI y frontend en React) ordene imprimir en un dispositivo conectado por USB o red local en un consultorio físico.
Aquí tienes la solución técnica completa de diseño e implementación para cubrir la configuración por estación y el flujo operativo de la cola de trabajo de toma de muestras.
Extensión del DDL en PostgreSQL: Configuración de Estaciones e Impresoras
Cada sede del laboratorio puede tener múltiples puestos de trabajo (ventanillas POS, escritorios de recepción, cubículos de toma de muestras), y cada uno de estos puestos tiene asociada una impresora configurada.
-- Catálogo de Puestos de Trabajo / Estaciones por Sede CREATE TABLE saas_estaciones_trabajo ( id SERIAL PRIMARY KEY, tenant_id VARCHAR(50) NOT NULL, codigo_sede VARCHAR(2) NOT NULL, codigo_estacion VARCHAR(20) NOT NULL, -- Ej: POS-VENTANILLA-1, TOMA-MUESTRAS-02 nombre_estacion VARCHAR(50) NOT NULL, tipo_estacion VARCHAR(20) NOT NULL, -- 'RECEPCION_POS' o 'TOMA_MUESTRAS' impresora_nombre VARCHAR(100), -- Nombre exacto del driver o IP de la impresora térmica impresora_tipo_conexion VARCHAR(20) DEFAULT 'LOCAL_USB', -- 'LOCAL_USB', 'RED_IP' impresora_ip VARCHAR(50), -- Si está conectada a la red local del laboratorio activo BOOLEAN DEFAULT TRUE, CONSTRAINT uk_tenant_estacion UNIQUE (tenant_id, codigo_estacion), CONSTRAINT fk_estacion_sede FOREIGN KEY (tenant_id, codigo_sede) REFERENCES sedes(tenant_id, codigo_sede) ON UPDATE CASCADE );
¿Cómo se resuelve la impresión desde el navegador web (React) hacia la impresora física?
Existen dos enfoques profesionales para manejar impresoras térmicas (Zebra/TSC con ZPL) en aplicaciones web SaaS:
⚬ Opción 1: Servicio Puente Local (QZ Tray o PrintNode - Altamente Recomendado): Se instala una pequeña aplicación de escritorio ligera en el PC de la ventanilla o toma de muestras. React se comunica con este servicio local mediante WebSockets seguros (localhost), y el servicio local envía los comandos ZPL directamente a la impresora USB o de red conectada a ese computador. Evita el diálogo de impresión clásico del navegador. ⚬ Opción 2: Impresión Directa por Red (IP): Si las impresoras térmicas tienen tarjeta de red Ethernet/Wi-Fi, el backend en FastAPI puede enviar el código ZPL directamente por socket TCP (port 9100) a la IP de la impresora configurada en saas_estaciones_trabajo.
Módulo de Recepción de Muestras y Cola de Trabajo (Backend FastAPI)
Cuando el paciente llega al cubículo de toma de muestras, el flebotomista selecciona su estación de trabajo y el sistema le muestra la cola de pacientes pendientes de toma.
Aquí tienes el diseño del endpoint en FastAPI que gestiona la cola de trabajo y dispara la impresión de etiquetas hacia la impresora asociada a la estación:
from fastapi import APIRouter, Depends, HTTPException, status from pydantic import BaseModel
import socket # Para impresoras en red IP
router = APIRouter(prefix="/api/v1/muestras", tags=["Toma de Muestras e Impresión"])
class SolicitudImpresionDTO(BaseModel.Config): pass
class SolicitudImpresion(BaseModel): numero_orden: int estacion_trabajo_id: int
@get_path = "/cola-trabajo" @router.get("/cola-trabajo/{codigo_sede}") async def obtener_cola_toma_muestras(codigo_sede: str, tenant_id: str): """ Retorna la lista de pacientes/órdenes que ya pasaron por el POS y cuyas muestras están pendientes de ser recolectadas y rotuladas. """ query = """ SELECT o.numero_de_la_orden, o.fecha, p.nombres, p.apellidos, p.cc, m.consecutivo as muestra_id, m.codigo_barras_tubo, m.secuencia_tubo, m.total_tubos_requeridos, m.tubo_descripcion, m.estado FROM orden o JOIN paciente p ON o.paciente = p.consecutivo JOIN muestra_x_orden m ON o.numero_de_la_orden = m.numero_de_orden AND o.tenant_id = m.tenant_id WHERE o.tenant_id = :tenant_id AND o.codigo_sede = :sede AND m.estado = 'PENDIENTE_TOMA' ORDER BY o.fecha ASC; """ # Ejecución asíncrona en base de datos... return {"cola": []}
@router.post("/imprimir-etiqueta-tubo") async def imprimir_etiqueta_tubo(datos: SolicitudImpresion): """ Busca la impresora asociada a la estación de trabajo y envía la trama ZPL """ # 1. Consultar la estación de trabajo para saber qué impresora tiene asociada y su IP/Nombre # estacion = await db.fetch_one("SELECT * FROM saas_estaciones_trabajo WHERE id = :id", {"id": datos.estacion_trabajo_id})
```
# 2. Consultar los datos de la muestra y el paciente para armar el ZPL
# muestra = await db.fetch_one("SELECT * FROM muestra_x_orden WHERE numero_de_orden = :ord", {"ord": datos.numero_orden})

# 3. Generar Código ZPL de la etiqueta
zpl_code = f"""
^XA
^PW400
^LL200
^FO20,15^A0N,22,22^FD{estacion_trabajo_id} - LAB SYSTEM^FS
^FO20,45^A0N,18,18^FDPaciente: JUAN PEREZ (CC: 123456)^FS
^FO20,70^A0N,18,18^FDORDEN: #{datos.numero_orden} - TUBO 1 DE 1^FS
^FO20,95^A0N,16,16^FDTUBO TAPA LILA (EDTA) - 3.0 mL^FS
^FO20,125^BY2,2,35^BCN,35,N,N,N^FDORD{datos.numero_orden}-SANG-1^FS
^XZ
"""

# 4. Enviar a la impresora física (Ejemplo vía red IP si es impresora de red)
# try:
#     s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
#     s.connect((estacion["impresora_ip"], 9100))
#     s.sendall(zpl_code.encode('utf-8'))
#     s.close()
# except Exception as e:
#     raise HTTPException(status_code=500, detail=f"Error imprimiendo en la estación: {str(e)}")

return {"status": "success", "message": "Comando de impresión enviado a la impresora configurada."}
```
Experiencia de Usuario en el Frontend (React)
Configuración Inicial del Puesto (Settings de Estación): ⚬ Cuando el usuario abre la aplicación por primera vez en un computador de la ventanilla POS o del cubículo de toma de muestras, la aplicación le muestra un modal: "Seleccione su Estación de Trabajo actual" (ej. Toma de Muestras - Cubículo 2). Esta selección se guarda en el almacenamiento local del navegador (localStorage) o sesión del usuario.
Pantalla de Cola de Trabajo (Toma de Muestras): ⚬ Una interfaz limpia en React + Tailwind CSS que muestra tarjetas en tiempo real con los pacientes en espera. ⚬ Al hacer clic en el paciente, despliega los tubos requeridos (ej. Tubo 1 y Tubo 2). ⚬ Al presionar el botón "🖨️ Imprimir Tubo 1", React envía el ID de la estación y la orden al backend de FastAPI, el cual redirige instantáneamente el ZPL a la impresora física vinculada a ese cubículo exacto. ⚬ Una vez rotulado, el flebotomista hace clic en "✓ Confirmar Toma", el paciente sale de la cola de pendientes y la orden avanza en el flujo clínico del laboratorio.