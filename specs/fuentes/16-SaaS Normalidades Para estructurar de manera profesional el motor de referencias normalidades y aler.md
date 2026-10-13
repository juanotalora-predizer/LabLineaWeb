SaaS Normalidades
Para estructurar de manera profesional el motor de referencias, normalidades y alertas clínicas en el laboratorio, actualizaremos el diseño del DDL y la lógica de validación. Esto permitirá configurar rangos altamente específicos (cruzando sexo y edad), separar valores numéricos de interpretaciones textuales, generar alertas internas automáticas para los bacteriólogos y controlar estrictamente qué información ve el paciente en su reporte final.
Extensión del Esquema DDL en PostgreSQL para Biomarcadores y Normalidades Avanzadas
Modificaremos la tabla de detalle o parámetros del examen (detalle analisis) para soportar la segmentación por sexo, rangos de edad (en años, meses o días), separación de tipos de datos (numérico vs texto) y el control de alertas.
-- Tabla avanzada de Rangos de Normalidad y Referencia por Biomarcador (Detalle Análisis) CREATE TABLE detalle_analisis_referencias ( consecutivo SERIAL PRIMARY KEY, tenant_id VARCHAR(50) NOT NULL, detalle_analisis_id INTEGER NOT NULL, -- Referencia al parámetro o biomarcador
```
-- Criterios demográficos de aplicabilidad
sexo_aplicable VARCHAR(1) DEFAULT 'T', -- 'M' (Masculino), 'F' (Femenino), 'T' (Todos)
edad_minima_dias INTEGER DEFAULT 0, -- Rango de edad inferior en días
edad_maxima_dias INTEGER DEFAULT 99999, -- Rango de edad superior en días (ej. 120 años * 365)

-- Tipo de Resultado y Valores de Referencia Normal
tipo_resultado VARCHAR(10) DEFAULT 'NUMERICO', -- 'NUMERICO' o 'TEXTO'

-- Si es Numérico
rango_minimo NUMERIC(12,4),
rango_maximo NUMERIC(12,4),

-- Si es Texto (Ej: "Negativo", "No Reactivo", "Ligeramente turbio")
valor_texto_referencia VARCHAR(255), 

-- Texto descriptivo de la normalidad para el reporte impreso
texto_referencia_impreso VARCHAR(255), 

CONSTRAINT fk_dar_detalle FOREIGN KEY (detalle_analisis_id) REFERENCES [detalle analisis](consecutivo) ON DELETE CASCADE
```
); CREATE INDEX idx_dar_analisis_criterios ON detalle_analisis_referencias(tenant_id, detalle_analisis_id, sexo_aplicable);
-- Actualización de la tabla 'diagnostico' (Resultados) para soportar almacenamiento estructurado ALTER TABLE diagnostico ADD COLUMN resultado_numerico NUMERIC(12,4), ADD COLUMN resultado_texto TEXT, ADD COLUMN bandera_anormalidad VARCHAR(20) DEFAULT 'NORMAL', -- 'NORMAL', 'ALTO_PANIC', 'BAJO', 'ANORMAL' ADD COLUMN nota_alerta_interna TEXT; -- Visible exclusivamente para el personal del laboratorio
Lógica de Evaluación Automática y Alertas en FastAPI
Cuando el bacteriólogo o transcriptor ingresa los resultados en el sistema, FastAPI ejecuta en tiempo real el motor de validación cruzando la edad exacta del paciente (al momento de la toma) y su género con la tabla de referencias:
from fastapi import APIRouter, HTTPException from pydantic import BaseModel from typing import Optional
router = APIRouter(prefix="/api/v1/resultados", tags=["Validación y Alertas de Resultados"])
class IngresoResultadoDTO(BaseModel): tenant_id: str analisis_por_orden_id: int detalle_analisis_id: int paciente_edad_dias: int paciente_genero: str # 'M' o 'F' valor_ingresado_numerico: Optional[float] = None valor_ingresado_texto: Optional[str] = None
@router.post("/evaluar-parametro") async def evaluar_resultado_biomarcador(datos: IngresoResultadoDTO): """ Evalúa el resultado ingresado frente a las normalidades por Sexo y Rango de Edad, genera la bandera correspondiente y emite una nota de alerta interna si está fuera de rango. """ # 1. Buscar la referencia activa que aplique para el biomarcador, género y rango de edad del paciente query = """ SELECT * FROM detalle_analisis_referencias WHERE tenant_id = :tenant AND detalle_analisis_id = :detalle_id AND (sexo_aplicable = :genero OR sexo_aplicable = 'T') AND :edad_dias BETWEEN edad_minima_dias AND edad_maxima_dias LIMIT 1; """ # [Simulación de consulta a base de datos...] # Supongamos que encontramos el registro de referencia: referencia = { "tipo_resultado": "NUMERICO", "rango_minimo": 70.0, "rango_maximo": 100.0, "texto_referencia_impreso": "70.0 - 100.0 mg/dL" }
```
bandera = "NORMAL"
nota_alerta = None

# 2. Evaluar si es Numérico
if referencia["tipo_resultado"] == "NUMERICO" and datos.valor_ingresado_numerico is not None:
    val = datos.valor_ingresado_numerico
    min_ref = referencia["rango_minimo"]
    max_ref = referencia["rango_maximo"]
    
    if val < min_ref:
        bandera = "BAJO"
        nota_alerta = f"ALERTA INTERNA: El valor numérico ({val}) está por debajo del límite inferior ({min_ref}) para género {datos.paciente_genero} y rango de edad."
    elif val > max_ref:
        bandera = "ALTO"
        nota_alerta = f"ALERTA INTERNA: El valor numérico ({val}) supera el límite superior ({max_ref}) para género {datos.paciente_genero} y rango de edad."
        
# 3. Evaluar si es Texto (Ej: Comparar contra patrón esperado)
elif referencia["tipo_resultado"] == "TEXTO" and datos.valor_ingresado_texto is not None:
    # Lógica de comparación de texto si aplica
    pass

# 4. Guardar en la tabla 'diagnostico' con su bandera y nota interna
"""
INSERT INTO diagnostico (tenant_id, analisis_por_orden, pregunta_por_analisis, resultado_numerico, resultado_texto, bandera_anormalidad, nota_alerta_interna, usuario_digitacion)
VALUES (...)
"""

return {
    "status": "success",
    "bandera": bandera,
    "alerta_generada": nota_alerta is not None,
    "nota_interna": nota_alerta # Se muestra en pantalla al bacteriólogo en rojo/amarillo
}
```
Reglas de Privacidad y Visualización para el Paciente
Para cumplir estrictamente con el principio de que el paciente jamás ve las alertas técnicas internas:
Panel del Personal del Laboratorio (Bacteriólogo / Patólogo): ⚬ Al visualizar los resultados en React, los biomarcadores alterados se resaltan con colores (ej. rojo para valores altos/bajos). ⚬ La Nota de Alerta Interna (nota_alerta_interna) se muestra como un tooltip o cuadro de advertencia exclusivo para el equipo clínico, permitiéndoles tomar decisiones o solicitar repeticiones de la muestra si es necesario.
Reporte Impreso y Vista del Paciente (Portal / Email): ⚬ El PDF generado y el correo electrónico enviado al paciente muestran únicamente: ⚬ El nombre del biomarcador y su unidad de medida. ⚬ El valor obtenido por el paciente (numérico o texto). ⚬ El rango de referencia normal correspondiente a su edad y sexo (ej. 70.0 - 100.0 mg/dL). ⚬ El campo general de Observaciones redactado y autorizado explícitamente por el patólogo o bacteriólogo transcriptor. ⚬ Cero rastros de las banderas internas de alerta computarizadas o notas de advertencia automatizadas del sistema en el documento que recibe el paciente, garantizando una comunicación clínica sobria, profesional y sin alarmas innecesarias.