Saas Muestras Algoritmo de Agrupación Inteligente (Lógica de Negocio en FastAPI)

Cuando el recepcionista crea la orden en el POS o el bacteriólogo en toma de muestras confirma el ingreso del paciente, el sistema ejecuta un motor de cálculo que determina automáticamente cuántos tubos se necesitan:
Recopilación: Lee todos los exámenes seleccionados en la orden.
Cruzar con muestras_x_analisis: Agrupa los exámenes que comparten el mismo tipo de muestra (ej. Sangre total).
Validación de Volumen (mL): Suma los mililitros mínimos requeridos por cada examen.
Ejemplo: Si el Hemograma pide 2 mL y el Perfil Lipídico pide 3 mL, el total requerido para sangre es 5 mL.
Cálculo de Tubos Físicos: Si la capacidad máxima estándar de un tubo de vacío es de 5 mL y se requieren 7 mL en total, el sistema calcula automáticamente que se necesitan 2 tubos, generando la secuencia:
Tubo 1 de 2: Tubo Tapa Lila (Hemograma) - Código de barras: LAB-CALI-ORD5001-SANG-1/2
Tubo 2 de 2: Tubo Tapa Lila (Perfil Lipídico) - Código de barras: LAB-CALI-ORD5001-SANG-2/2
3. Estrategia de Impresión para Impresoras de Etiquetas (Zebra / Termales)
Las impresoras de etiquetas de laboratorio (como marcas tipo Zebra o TSC) no suelen usar controladores web tradicionales, sino comandos de impresión directos (como ZPL - Zebra Programming Language).
Para soportar la impresión tanto en Ventanilla/POS como en Toma de Muestras:
Configuración por Estación de Trabajo: En la interfaz de React, cada equipo (usuario/sede) guarda en su configuración local o perfil la impresora asignada.
Generación ZPL en el Backend (FastAPI): El backend genera una cadena de texto optimizada para la impresora térmica con el formato exacto del código de barras, nombre del paciente, número de orden, tipo de tubo y la secuencia (ej. Tubo 1 de 2).