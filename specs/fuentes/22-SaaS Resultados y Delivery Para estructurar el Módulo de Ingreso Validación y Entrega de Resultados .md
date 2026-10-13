SaaS Resultados y Delivery
Para estructurar el Módulo de Ingreso, Validación y Entrega de Resultados (Result Management & Delivery) cumpliendo con todas las estrictas reglas de negocio, financieras y de personalización que has definido, dividiremos la solución en tres partes clave: la base de datos (DDL), la lógica de negocio (reglas de cartera y autorizaciones en FastAPI) y la personalización gráfica de los reportes.
Extensión del Esquema DDL en PostgreSQL
Necesitamos almacenar los parámetros de personalización gráfica por laboratorio (Tenant), los estados de validación del bacteriólogo, y el control de firmas y marcas de agua.
-- Configuración de Parámetros de Reportes e Impresión por Tenant (Laboratorio) CREATE TABLE saas_configuracion_reportes ( tenant_id VARCHAR(50) PRIMARY KEY, logo_url TEXT, firma_default_bacteriologo_url TEXT, nombre_bacteriologo_default VARCHAR(100), tarjeta_profesional VARCHAR(50), marca_agua_texto VARCHAR(50) DEFAULT 'CONFIDENCIAL', pie_de_pagina TEXT, email_remitente VARCHAR(100), plantilla_cuerpo_email TEXT, -- HTML parametrizable para el correo CONSTRAINT fk_conf_rep_tenant FOREIGN KEY (tenant_id) REFERENCES saas_laboratorios(tenant_id) ON DELETE CASCADE );
-- Extensión en la tabla de Órdenes para control de validación y despacho de resultados ALTER TABLE orden ADD COLUMN resultados_validados BOOLEAN DEFAULT FALSE, ADD COLUMN usuario_validador VARCHAR(50), ADD COLUMN fecha_validacion TIMESTAMP, ADD COLUMN resultados_enviados_email BOOLEAN DEFAULT FALSE, ADD COLUMN fecha_envio_email TIMESTAMP;
Flujo de Negocio para el Ingreso y Revisión de Resultados
El módulo de resultados en el Frontend (React) y Backend (FastAPI) operará en dos fases:
Digitación y Revisión: ⚬ Digitación Manual / Externa: Los bacteriólogos o auxiliares ingresan los valores de exámenes que llegan impresos o desde equipos semiautomatizados a la tabla inmutable diagnostico (asociada a analisis_por_orden). ⚬ Revisión y Aprobación: El bacteriólogo jefe o autorizado accede a un panel de control donde visualiza los resultados digitados, puede editarlos (o generar una adición si ya se guardaron) y, una vez verifica que todo es correcto, hace clic en "Aprobar y Validar Resultados". Esto cambia el estado de la orden a resultados_validados = TRUE.
Reglas de Negocio Estrictas para el Envío Automático por Email
El sistema no permitirá enviar o liberar los resultados por correo electrónico a menos que cumpla estrictamente con la matriz financiera que especificaste:
from fastapi import APIRouter, HTTPException, BackgroundTasks
import aiosmtplib # Para envío de correos asíncronos
from email.message import EmailMessage
router = APIRouter(prefix="/api/v1/resultados", tags=["Resultados y Envío"])
async def verificar_condiciones_despacho(tenant_id: str, numero_orden: int) -> bool: """ Evalúa si el paciente cumple con la regla de negocio para recibir sus resultados por email: 1. Si es PARTICULAR: Saldo pendiente en la orden / factura debe ser 0. 2. Si es EMPRESARIAL / CONVENIO: Debe tener un código de autorización registrado. """ # Consulta unificada a base de datos para evaluar orden, empresa y pagos query = """ SELECT o.consecutivo, o.tipo_tarifa, o.empresa_a_cobrar, o.vlr_usuario, o.num_autoriz_adic, COALESCE((SELECT SUM(valor_abonado) FROM abonos WHERE numero de orden = o.numero_de_la_orden), 0) as total_abonado, o.valor_a_cobrar FROM orden o WHERE o.tenant_id = :tenant AND o.numero_de_la_orden = :ord; """ # [Simulación de ejecución de consulta...] # Supongamos que obtenemos los datos de la orden: es_particular = True # Lógica basada en tipo_tarifa o empresa_a_cobrar == 0 saldo_pendiente = 0.0 # valor_a_cobrar - total_abonado tiene_autorizacion = "AUT-998877" # o.num_autoriz_adic
```
if es_particular and saldo_pendiente > 0:
    return False # Bloqueado: Paciente particular con saldo pendiente
    
if not es_particular and not tiene_autorizacion:
    return False # Bloqueado: Empresa/Convenio sin código de autorización registrado
    
return True # Cumple las reglas, apto para envío
```
@router.post("/enviar-resultados/{numero_orden}") async def disparar_envio_resultados(numero_orden: int, tenant_id: str, background_tasks: BackgroundTasks): """ Valida las reglas financieras y despacha el correo electrónico con los resultados en PDF y HTML. """ apto_para_envio = await verificar_condiciones_despacho(tenant_id, numero_orden)
```
if not apto_para_envio:
    raise HTTPException(
        status_code=400, 
        detail="No se pueden enviar los resultados. El paciente particular presenta saldo pendiente o la orden empresarial carece de código de autorización."
    )

# Programar el envío de correo en segundo plano para no congelar la API
background_tasks.add_task(enviar_correo_resultados_task, tenant_id, numero_orden)

return {"status": "success", "message": "Validación superada. El correo con los resultados está siendo procesado y enviado."}
```
async def enviar_correo_resultados_task(tenant_id: str, numero_orden: int): """ Construye el PDF con el formato parametrizado del laboratorio (Logo, Marca de Agua, Firma) y lo envía al email del paciente. """ # 1. Obtener parámetros gráficos del tenant (saas_configuracion_reportes) # 2. Generar PDF de resultados (usando librerías como ReportLab en Python) # 3. Enviar correo usando la plantilla HTML personalizada print(f"[BACKGROUND] Resultados de la orden #{numero_orden} enviados exitosamente por email para el tenant {tenant_id}.")
Personalización Gráfica Parametrizable por el Laboratorio
Desde el panel de administración del SaaS o la configuración del laboratorio, el usuario administrador podrá configurar los elementos visuales que se inyectarán de forma dinámica en la generación del PDF de los resultados:
⚬ Encabezado y Logotipo: Se toma la URL de saas_configuracion_reportes.logo_url para ubicar el logo corporativo en la parte superior del informe clínico. ⚬ Marca de Agua: El sistema renderiza de manera traslúcida el texto configurado en marca_agua_texto (ej. CONFIDENCIAL o el nombre del laboratorio) en el fondo de la página de resultados. ⚬ Firma del Bacteriólogo: Se imprime la imagen de la firma digitalizada (firma_default_bacteriologo_url) acompañada del nombre y su respectivo número de tarjeta profesional. ⚬ Cuerpo del Email: El sistema toma la plantilla en HTML guardada en plantilla_cuerpo_email, reemplaza variables automáticas como {nombre_paciente} y {numero_orden}, y genera un mensaje corporativo impecable para el cliente.