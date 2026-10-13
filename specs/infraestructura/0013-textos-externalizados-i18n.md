# 0013. Textos externalizados (i18n) y fechas locales

- **Estado:** Aceptada
- **Fecha:** 2026-10-13
- **Responsable:** Juan Otálora

## Contexto

La spec [0004](0004-normativa-colombia-latam.md) exige textos de plantillas externalizados (`es-CO` por defecto), nada específico de un país en el código, fechas en UTC en la base y zona local solo al mostrarlas. Hasta la etapa 2 los textos estaban escritos en el HTML y en las rutas.

## Decisión

### Textos

- Un catálogo por idioma en **TOML**: `app/locales/<idioma>.toml` (hoy `es-CO.toml`), con claves por sección (`auth.ingresar.titulo`). Se lee con `tomllib` de la biblioteca estándar: **sin dependencias nuevas**.
- En Python: `t("clave", idioma, **parámetros)`; en Jinja2: `{{ t("clave", nombre=...) }}`. Los marcadores `{nombre}` se reemplazan con `str.format`; el resultado se escapa en la plantilla como cualquier otro valor.
- **Idioma:** el del país del laboratorio (`global.paises.idioma`). Búsqueda en cadena: idioma del laboratorio (`es-MX`) → idioma base (`es`) → `es-CO`. Un país nuevo solo necesita su archivo con las claves que cambian.
- **Clave inexistente = error**, no un texto vacío: las pruebas lo detectan antes de publicar.
- Mensajes fuera de un laboratorio (404 de subdominio, 400 genérico, errores de CSRF) usan el idioma por defecto.
- El atributo `lang` del HTML sale del laboratorio.

### Fechas y zonas horarias

- La conexión a PostgreSQL fija `timezone = UTC`: la base y la aplicación trabajan en UTC sin depender de la configuración del servidor.
- Al mostrar: filtro `{{ instante | fecha }}` (o `fecha_local()` en Python) con la zona del laboratorio (`global.paises.zona_horaria`) y el formato del catálogo (`formato.fecha`, `formato.fecha_hora`). Un `datetime` sin zona se rechaza.

### Guardianes (pruebas)

- Ninguna plantilla tiene texto visible escrito directamente, incluidos `title`, `alt`, `placeholder` y `aria-label` (`tests/test_i18n.py`).
- Toda clave usada en `app/` existe en el catálogo por defecto.

## Alternativas consideradas

- **gettext con Babel** (`.po`/`.mo` y la extensión i18n de Jinja2): el estándar para traductores, pero agrega Babel y un paso de compilación. Si más adelante se contratan traductores, los catálogos TOML se convierten a `.po` sin cambiar las plantillas, porque todas pasan por `t()`.
- **Textos en diccionarios de Python:** sin dependencias, pero mezcla textos con código y complica la revisión por personas no técnicas.

## Consecuencias

- Toda plantilla y todo mensaje nuevo para el usuario se agregan al catálogo.
- Los nombres de módulos y operaciones de permisos (`pacientes`, `consultar`) todavía se muestran como códigos; se traducen cuando exista la administración de roles en la interfaz (etapa 4).
- Formatos de número y moneda por país se agregan al catálogo con el POS (etapa 8).
