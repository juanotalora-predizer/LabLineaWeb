# 0009. Catálogo de exámenes e importador de Lablinea

- **Estado:** Aceptada
- **Fecha:** 2026-10-13
- **Responsable:** Juan Otálora
- **Base:** [0003](0003-muestras-impresion.md) (requisitos de muestra), [0004](0004-resultados-validacion-entrega.md) (exámenes, parámetros y rangos), [0007](0007-alcance-mvp.md) (migrar solo el catálogo); fuentes 02 (DDL de Lablinea), 15 (muestras) y 16 (normalidades)

## Contexto

Cada laboratorio necesita su catálogo de exámenes antes de recibir órdenes (etapa 8). Los clientes que vienen de Lablinea (Access) quieren traer el suyo, que es valioso. No se migran pacientes ni resultados ([0007](0007-alcance-mvp.md)).

Las tablas de Lablinea mezclan nombres con espacios, guardan los rangos como texto libre o un único mínimo y máximo, y no tienen sexo ni edad, tubo, volumen ni LOINC.

## Decisión

### 1. Modelo del catálogo (por laboratorio, esquema `lab`)

| Entidad | Contenido |
|---|---|
| Secciones | Código, nombre y orden (Hematología, Química…) |
| Unidades | Código, nombre y código UCUM opcional |
| Tipos de muestra | Sangre total, suero, orina… |
| Tipos de tubo | Nombre, aditivo y **capacidad en mL** (la usa la agrupación de tubos, etapa 9) |
| Técnicas | Técnica analítica por defecto del examen |
| **Exámenes** | Código, nombre, sección, técnica, **código nacional** (CUPS en Colombia: el nombre del sistema sale de la configuración del país), LOINC, requiere autorización, días de procesamiento y activo |
| **Parámetros** | Nombre, orden, tipo (`NUMERICO`, `TEXTO`, `LISTA` o `TITULO`), unidad, decimales, LOINC, si se grafica y activo |
| Valores de lista | Valores permitidos de un parámetro de tipo lista; se marca cuál es normal |
| **Rangos de referencia** | Por parámetro: sexo (`M`, `F` o `T`), edad mínima y máxima **en días** con intervalo `[mínimo, máximo)`, mínimo y máximo normales, mínimo y máximo **críticos**, valor esperado (texto), texto impreso y marca **"requiere revisión"** |
| Requisitos de muestra | Por examen: tipo de muestra, tipo de tubo y volumen mínimo en mL |
| Tarifas y precios | Tipos de tarifa del laboratorio (particular, convenios) con su moneda; precio de cada examen por tarifa |
| Códigos alternos | Códigos del examen por convenio o entidad (tabla `Codigo Analisis x Empresa` de Lablinea) |

**Reglas:**

- Los exámenes y parámetros **no se borran**, se desactivan, porque las órdenes los referencian. Rangos, valores de lista, requisitos, precios y códigos alternos sí se borran (con auditoría).
- **Coherencia de rangos en la base:**
  - El mínimo no supera al máximo.
  - El crítico mínimo no supera al mínimo normal, y el crítico máximo no queda por debajo del máximo normal.
  - La edad mínima es menor que la máxima, con tope de 150 años.
- **Huecos y solapes:** para cada sexo (un rango `T` aplica a ambos) se revisa la cobertura de edades de 0 a 150 años. Un hueco o un solape se muestra como **advertencia**, no como error: un laboratorio puede no atender neonatos.
- Todo se edita desde *Configuración → Catálogo* con los permisos del módulo `configuracion`: consultar, crear, modificar y eliminar.

### 2. Importador de Lablinea

**Formato de entrada:** un archivo **ZIP con las tablas de Lablinea exportadas a CSV**, un archivo por tabla y con el nombre de la tabla (por ejemplo `detalle analisis.csv`). Se exportan desde Access (*Datos externos → Archivo de texto*, con encabezados) o con `mdb-export`.

- El servidor nunca abre archivos de Access: el formato binario de Access es complejo, y procesarlo en el servidor sería superficie de ataque innecesaria.
- **Obligatorias:** `seccion`, `analisis` y `detalle analisis`.
- **Opcionales:** `unidad`, `lista de valores`, `tipo muestra`, `muestras x analisis`, `tipo tarifa`, `costo analisis`, `Tipo Codigo Alterno` y `Codigo Analisis x Empresa`.
- Los nombres de tablas y columnas se comparan sin distinguir mayúsculas, espacios ni guiones bajos.
- **Codificación:** UTF-8 (con o sin BOM) o Windows-1252, que es la que usa Access en español. Separador coma, punto y coma o tabulación, detectado automáticamente.
- **Números:** se acepta coma decimal; el último separador del número es el decimal.
- **Booleanos:** `True`/`False`, `1`/`0`, `-1`, `Sí`/`No`, `Verdadero`/`Falso`.

**Seguridad del archivo.** Si algo falla se rechaza **sin guardar nada**.

| Control | Límite o regla |
|---|---|
| Tipo de archivo | Debe ser un ZIP por su contenido (firma `PK`), no por la extensión. Un ejecutable o un PDF renombrado se rechaza |
| Tamaño | 10 MB comprimido; 50 MB descomprimido en total; 20 MB por tabla |
| Bomba ZIP | Proporción de compresión máxima 100:1 por entrada |
| Contenido del ZIP | Máximo 30 entradas, solo `.csv`, sin carpetas, rutas ni entradas cifradas |
| Filas | Máximo 50.000 por tabla y 4.000 caracteres por campo |
| Caracteres | Sin caracteres nulos ni de control. Los textos que se pasan de los límites del catálogo son errores |

**Flujo:**

1. **Subir:** el archivo se analiza y se guarda una **importación prevista** con su SHA-256, el contenido y un resumen.
2. **Vista previa:** muestra lo que se va a crear (conteos por entidad), los **errores** (bloquean la carga) y las **advertencias**.
3. **Cargar:** el administrador confirma. El archivo se vuelve a analizar contra el estado actual del catálogo y se carga **en una sola transacción**: si algo falla, no queda nada. El contenido se borra y se conserva el resumen.
4. Una importación prevista también se puede descartar.

**Qué es error** (no se puede cargar):

- Falta una tabla o una columna obligatoria.
- Un examen apunta a una sección inexistente, o un parámetro a un examen inexistente.
- Hay identificadores repetidos.
- Un nombre o código de examen ya existe en el catálogo del laboratorio.
- Un costo no es un número válido.
- Un texto excede los límites.

**Qué es advertencia** (se carga y se revisa después):

- **Todo rango importado queda "requiere revisión"**: Lablinea no distingue sexo ni edad, así que se carga como "ambos sexos, todas las edades".
- Si el texto de referencia trae números ("70 - 100", "< 200", "> 40") se interpretan como mínimo y máximo; si no, queda como valor esperado y texto impreso.
- Mínimo mayor que el máximo: se descartan los números y se conserva el texto.
- Requisitos de muestra sin tubo ni volumen (Lablinea no los tiene).
- Exámenes sin parámetros.

**Tipo de parámetro inferido:**

| Si el parámetro… | Tipo |
|---|---|
| Está marcado como título | `TITULO` |
| Tiene valores de lista | `LISTA` |
| Tiene rango numérico o unidad | `NUMERICO` |
| No cumple nada de lo anterior | `TEXTO` |

**Otras reglas:**

- Los consecutivos de Lablinea se guardan (`codigo_lablinea`) para trazar el origen y evitar cargar dos veces lo mismo.
- Los LOINC se asignan después (Lablinea no los tiene).
- La importación la hace el personal con el permiso `configuracion.crear` de su propio laboratorio. Queda en la auditoría: importación, vista previa y cada fila creada.

### 3. Exportación del catálogo a CSV

- *Configuración → Catálogo → Exportar* descarga un CSV (UTF-8 con BOM para Excel): exámenes con sección, códigos y precios por tarifa.
- **Inyección CSV:** toda celda de texto que empiece por `=`, `+`, `-`, `@`, tabulación o retorno de carro se antepone con `'`, para que la hoja de cálculo no la ejecute como fórmula.
- La exportación queda auditada (`EXPORT`).

## Alternativas consideradas

- **Leer el `.mdb` o `.accdb` directamente** (mdbtools o una librería de Python): ahorra un paso al cliente, pero agrega una dependencia nativa o poco mantenida que procesaría binarios no confiables en el servidor. Si hace falta, se puede agregar después un convertidor local que produzca el ZIP.
- **Cargar sin vista previa:** más rápido, pero los rangos de Lablinea necesitan revisión y un error a mitad dejaría el catálogo incompleto.
- **Sobrescribir el catálogo existente al reimportar:** los nombres repetidos son error. La importación está pensada para la migración inicial; los cambios posteriores se hacen en la interfaz.

## Consecuencias

- El cliente de Lablinea exporta sus tablas antes de migrar; se le entrega una guía de exportación.
- Los rangos de referencia importados deben revisarse antes de usarlos en resultados (etapa 12). La pantalla *Revisión* del catálogo los lista.
- La agrupación de tubos (etapa 9) usa la capacidad de los tipos de tubo y el volumen de los requisitos; por eso los requisitos importados quedan para revisión.
