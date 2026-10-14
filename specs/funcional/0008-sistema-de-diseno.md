# 0008. Sistema de diseño de la interfaz

- **Estado:** Aceptada
- **Fecha:** 2026-10-13
- **Responsable:** Juan Otálora
- **Referencias:** tres capturas compartidas por el usuario el 2026-10-13: ficha de paciente de HMLR (sistema hospitalario), base de pacientes de Datacapt (web y móvil) y eMedico ERP (Colombia: admisiones con triage, agenda y facturas DIAN).

## Contexto

Hasta la etapa 5 la interfaz tenía estilos mínimos. El usuario definió el aspecto del producto a partir de tres referencias de software clínico. Esta spec convierte esas referencias en reglas que aplican a **todas** las pantallas: Tenant App, Admin Hub, portal de pacientes y médicos, y las que vengan.

Qué se tomó de cada referencia:

| Referencia | Qué aporta |
|---|---|
| **HMLR** (base principal) | Menú lateral azul noche con el ítem activo en azul primario; contenido en tarjetas blancas sobre fondo gris azulado; ficha de paciente con encabezado (foto o iniciales, identificación, contacto) y datos críticos a la derecha (tipo de sangre, alergias, seguro, estado) con íconos de color; pestañas subrayadas; pares etiqueta y valor en dos columnas; íconos de línea; franja azul noche de "información segura" |
| **Datacapt** | Indicadores (KPI) grandes en tarjetas; tablas limpias con encabezados en mayúsculas pequeñas y grises; nombre en negrita con un dato secundario gris debajo; estados como punto de color más texto; buscador con ícono; botón primario sólido con ícono; vista móvil |
| **eMedico** (Colombia) | Estados clínicos con color fuerte y texto (Sin triage, En atención, En observación); tiempo de espera resaltado por urgencia; selector de sede; estados de facturas ante la DIAN |

## Decisión

### 1. Principios

1. **Claridad clínica primero:** lo que puede dañar a un paciente (alergias, valores críticos, triage) se ve primero y en rojo, siempre con ícono y texto.
2. **El color nunca es la única señal:** todo estado lleva texto (y si aplica, ícono). Contraste mínimo WCAG 2.1 AA (4,5:1 para texto; 3:1 para controles e íconos).
3. **Densa pero ordenada:** el personal trabaja muchas horas con datos tabulares. Se usan tarjetas, tablas y pares etiqueta y valor, sin decoración.
4. **Sobria y confiable:** azul noche y azul primario. Nada de degradados llamativos, ilustraciones ni animaciones.

### 2. Color (tokens)

Todos los colores viven como variables CSS en `:root` de `app/static/css/styles.css`. **Ninguna regla de estilo usa un color escrito directamente** (lo verifica una prueba). Solo hay tema claro: es el estándar en entornos clínicos y en las tres referencias.

| Token | Valor | Uso |
|---|---|---|
| `--color-marca-900` | `#0B1B3D` | Menú lateral, franjas institucionales |
| `--color-marca-800` | `#12295A` | Hover en el menú lateral |
| `--color-primario` | `#2563EB` | Acciones, enlaces, ítem activo, pestaña activa, foco |
| `--color-primario-oscuro` | `#1D4ED8` | Hover y presionado |
| `--color-primario-suave` | `#EFF4FF` | Fondos de selección y de información |
| `--color-texto` | `#0F172A` | Texto principal y títulos |
| `--color-texto-2` | `#475569` | Etiquetas |
| `--color-texto-3` | `#5F6F86` | Datos secundarios y ayudas (el gris de las referencias, `#64748B`, se oscureció: daba 4,40:1 sobre el fondo y no cumplía AA) |
| `--color-fondo` | `#F4F6FB` | Fondo de la aplicación |
| `--color-superficie` | `#FFFFFF` | Tarjetas, tablas y formularios |
| `--color-borde` | `#E2E8F0` | Bordes y separadores |

**Estados semánticos.** Cada uno tiene texto, fondo y punto; en el texto se usa el tono oscuro para cumplir el contraste.

| Estado | Texto | Fondo | Punto | Ejemplos |
|---|---|---|---|---|
| Éxito | `#15803D` | `#DCFCE7` | `#22C55E` | Activo, pagada, validado, completado |
| Alerta | `#B45309` | `#FEF3C7` | `#F59E0B` | Pendiente, pago parcial, en observación, por vencer |
| Peligro | `#B91C1C` | `#FEE2E2` | `#EF4444` | Valor crítico, alergia, vencida, suspendida, anulada, sin triage |
| Información | `#1D4ED8` | `#DBEAFE` | `#3B82F6` | En atención, en proceso |
| Neutro | `#475569` | `#F1F5F9` | `#94A3B8` | Inactivo, cancelado, borrador |

**Datos clínicos con color fijo** (ficha de paciente, etapa 7 en adelante):

- Alergias: peligro, con ícono de alerta.
- Tipo de sangre: peligro.
- Condiciones crónicas: información.
- Seguro o convenio: primario.
- Estado del paciente: éxito o neutro.

### 3. Tipografía

- **Inter** (variable, SIL OFL 1.1), servida desde `app/static/fonts/` (sin CDN, [infraestructura/0001](../infraestructura/0001-stack-fastapi-jinja2.md)). Respaldo: `system-ui`.
- **Escala:**

  | Tamaño | Uso |
  |---|---|
  | 12 px | Encabezados de tabla, insignias, ayudas |
  | 13 px | Datos secundarios |
  | 14 px | Base: texto, tablas, formularios |
  | 16 px | Títulos de tarjeta |
  | 18 px | Subtítulos |
  | 22 px | Título de página |
  | 28 px | Cifras de indicadores |

- **Pesos:** 400 (texto), 500 (etiquetas y menú), 600 (títulos y nombres) y 700 (cifras y título de página).
- **Cifras alineadas** (`font-variant-numeric: tabular-nums`) en dinero, resultados, documentos, fechas y tablas.
- **Mayúsculas** solo en encabezados de tabla (12 px, espaciado 0,04 em). Títulos y botones en mayúscula inicial ("Nuevo laboratorio", no "NUEVO LABORATORIO").

### 4. Espacio, forma y elevación

- **Espaciado:** retícula de 4 px (`--e-1` = 4 px … `--e-8` = 32 px). Relleno de tarjeta: 24 px; 16 px en móvil.
- **Esquinas redondeadas:**
  - 8 px: controles y botones.
  - 12 px: tarjetas y tablas.
  - Píldora: insignias y avatar de iniciales.
- **Sombra:** sutil en tarjetas (`--sombra`) y elevada solo en elementos flotantes. El borde de 1 px separa más que la sombra.

### 5. Iconografía

- **Lucide** (ISC): íconos de línea, trazo 2, tamaño 18 o 20 px y color `currentColor`. Se sirven en un *sprite* propio (`app/static/img/iconos.svg`) construido con `scripts/construir_iconos.py`, que solo copia figuras geométricas.
- En las plantillas, `{{ icono("nombre") }}`. Los íconos son decorativos (`aria-hidden`): el texto siempre acompaña.
- Un ícono nuevo se agrega al *sprite* con el script. Una prueba verifica que todo ícono usado exista.

### 6. Disposición (layout)

- **Con sesión:**
  - Menú lateral fijo (248 px) azul noche con la marca arriba, ítems con ícono y texto, el activo en azul primario y "Salir" al pie.
  - Barra superior blanca con el nombre del sitio (laboratorio o Admin Hub) y el usuario (avatar de iniciales, nombre y tipo).
  - Contenido sobre `--color-fondo`, con ancho máximo de 1280 px.
- **Sin sesión** (ingreso, verificación, activación): tarjeta centrada sobre el fondo, con la marca encima.
- **Franjas:** avisos de cuenta o sistema a todo el ancho, bajo la barra superior.
  - Suscripción vencida: peligro.
  - Sesión de soporte: alerta.
  - Información de seguridad: marca.
- **Móvil** (< 900 px): el menú lateral pasa a una barra superior con los ítems desplazables en horizontal (sin JavaScript); las tablas se desplazan dentro de su tarjeta; los formularios ocupan todo el ancho. Tamaño mínimo de toque: 40 px.

### 7. Componentes

| Componente | Regla |
|---|---|
| **Tarjeta** (`.tarjeta`) | Superficie blanca, borde, radio 12 px, relleno 24 px; título de 16 px semibold. Es el contenedor de toda información |
| **Ficha** (`.ficha`) | Pares etiqueta y valor en dos columnas: etiqueta en `--color-texto-2`, valor en `--color-texto`; con ícono opcional a la izquierda |
| **Tabla** (`.tabla` en `table`) | Dentro de una tarjeta; encabezado de 12 px en mayúsculas y `--color-texto-3`; filas de al menos 48 px con separador; primera columna en semibold; dato secundario gris debajo del principal; acciones a la derecha |
| **Insignia** (`|insignia`) | Píldora con el fondo y el texto del estado, más un punto de color. El filtro elige el tono según el código de estado |
| **Botón** | Primario: sólido azul. Secundario: borde y fondo blanco. Terciario: texto azul. Peligro: rojo, solo para acciones destructivas. Alto mínimo de 40 px y radio de 8 px. El ícono va a la izquierda del texto |
| **Formulario** | Etiqueta arriba (14 px, 500); campo de 40 px de alto, borde y radio de 8 px; foco con anillo azul de 3 px; ayuda debajo (13 px, gris); errores en un bloque de peligro arriba del formulario, con `role="alert"` |
| **Pestañas** | Texto e ícono; la activa en azul primario y subrayada con 2 px |
| **Indicador (KPI)** | Tarjeta con etiqueta pequeña, cifra de 28 px en negrita y variación o contexto debajo; estado con punto de color |
| **Encabezado de página** | Título de 22 px a la izquierda y la acción principal (botón primario) a la derecha |
| **Estado vacío** | Texto gris centrado en la tarjeta, con la acción para empezar si existe |
| **Avatar** | Foto o iniciales sobre `--color-primario-suave`, circular |

### 8. Patrones del dominio (para las próximas etapas)

- **Ficha del paciente** (patrón HMLR):
  - Encabezado con avatar, nombre (22 px), documento (tipo y número), edad calculada y contacto.
  - Columna derecha separada con los datos críticos: alergias, tipo de sangre, convenio y estado.
  - Debajo, pestañas: Datos, Historial, Documentos, Servicios.
  - Las notas internas del laboratorio **nunca** aparecen en las vistas del paciente ([funcional/0004](0004-resultados-validacion-entrega.md)).
- **Colas de trabajo** (patrón eMedico: admisión, toma de muestras, validación):
  - Tabla con la hora y el tiempo transcurrido.
  - La espera se resalta en alerta o peligro según los umbrales de la configuración del laboratorio.
  - Estado clínico como insignia con texto.
  - Selector de sede arriba cuando el usuario tiene varias.
- **Listados con indicadores** (patrón Datacapt): fila de indicadores arriba, buscador y filtros, y tabla.
- **Valores críticos y resultados fuera de rango:** insignia de peligro con ícono y texto. En el portal y el PDF solo la marca H o L, si el laboratorio la activó ([funcional/0004](0004-resultados-validacion-entrega.md)).
- **Dinero:** filtro `|dinero(moneda)` con cifras alineadas a la derecha en las tablas.

### 9. Accesibilidad y textos

- Contraste AA verificado por una prueba para los pares de tokens de texto.
- Foco visible en todo control (anillo azul); navegación completa con teclado; `aria-current="page"` en el ítem activo del menú.
- Textos en español con mayúscula inicial; los textos van en el catálogo de i18n ([infraestructura/0013](../infraestructura/0013-textos-externalizados-i18n.md)).

### 10. Reglas técnicas

- Un solo archivo de estilos propio (`app/static/css/styles.css`), sin frameworks CSS. Sin estilos ni scripts en línea (la CSP lo impide).
- Las plantillas usan las clases de los componentes de esta spec; no inventan colores ni tamaños.
- Las capturas de referencia son solo inspiración visual: no se copian marcas, logotipos ni textos de esos productos.

## Alternativas consideradas

- **Framework CSS (Tailwind, Bootstrap):** acelera el inicio, pero agrega una dependencia y un paso de compilación, o un CDN que la CSP prohíbe. Para el tamaño de la interfaz bastan tokens propios.
- **Tipografía del sistema:** sin archivos que servir, pero el aspecto cambia entre equipos. Inter es la tipografía de las referencias y pesa unos 120 KB en caché.
- **Tema oscuro:** ninguna referencia lo usa y en entornos clínicos prima la lectura en pantallas compartidas. Se puede agregar más adelante sobre los mismos tokens.

## Consecuencias

- Las pantallas existentes (ingreso, panel, usuarios, Admin Hub, facturas, soporte) se rediseñaron con estas reglas en la misma entrega.
- Guardianes automáticos: colores solo como tokens; contraste AA de los tokens de texto; sin estilos en línea en las plantillas; todo ícono usado existe en el *sprite*.
- Las pantallas nuevas (pacientes, órdenes, caja, muestras, resultados, dashboard) siguen los patrones de la sección 8.
