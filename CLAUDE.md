# CLAUDE.md

Guía para trabajar en LabLineaWeb. Las decisiones del proyecto viven en [specs/](specs/) y son de cumplimiento obligatorio.

LabLineaWeb es un **LIS (sistema de información de laboratorio clínico) en modalidad SaaS**, multi-laboratorio, que inicia en Colombia con alcance Latinoamérica (ver [funcional/0001](specs/funcional/0001-producto-lis-saas.md)). Moderniza **Lablinea**, un sistema monousuario heredado en Access.

El alcance actual es el **MVP** ([funcional/0007](specs/funcional/0007-alcance-mvp.md)): fases 1 a 5 (base multi-tenant, seguridad, POS y caja, muestras, resultados). No construir módulos fuera del MVP sin que el usuario lo pida.

Los documentos originales de la descripción funcional están en [specs/fuentes/](specs/fuentes/). Son material de origen: **las specs prevalecen sobre las fuentes** cuando difieren (p. ej. las fuentes usan React, envían PDFs por correo y pasan `tenant_id` en las peticiones; nada de eso aplica).

## Antes de empezar una tarea

1. Leer [specs/README.md](specs/README.md) (índice de decisiones) y las specs relacionadas con la tarea.
2. Revisar [specs/backlog.md](specs/backlog.md) y la última entrada de [specs/daily.md](specs/daily.md) para tener el contexto actual.
3. Si la tarea contradice una spec con estado `Aceptada`, detenerse y consultar al usuario antes de implementar. No cambiar una decisión aceptada de forma implícita.

## Stack (ver [infraestructura/0001](specs/infraestructura/0001-stack-fastapi-jinja2.md))

- FastAPI (Python 3.14) + Uvicorn. Vistas renderizadas en servidor con Jinja2, **htmx** para interactividad y **Chart.js** para gráficas, servidos como estáticos propios (sin CDN).
- PostgreSQL 16+ con SQLAlchemy 2 async + asyncpg; migraciones con Alembic ([infraestructura/0007](specs/infraestructura/0007-base-de-datos.md)).
- PDF de resultados con WeasyPrint desde plantillas Jinja2. Etiquetas en ZPL impresas con QZ Tray.
- Rutas en `app/`, plantillas en `app/templates/` (heredan de `base.html`), estáticos en `app/static/`.
- No introducir frameworks de frontend (React, Vue, etc.), otros frameworks web ni nuevas dependencias sin una spec aceptada que lo respalde.
- Dependencias en `requirements.txt` (producción) y `requirements-dev.txt` (desarrollo), con rango de versión acotado.

## Multi-tenant (obligatorio, ver [infraestructura/0005](specs/infraestructura/0005-arquitectura-saas-multitenant.md))

Filtrar datos de un laboratorio a otro es el fallo más grave posible en este producto.

- Tenant = laboratorio. Toda tabla del esquema `lab` lleva `tenant_id` y política RLS con `USING` + `WITH CHECK`, y `FORCE ROW LEVEL SECURITY`.
- La aplicación usa un rol de base de datos sin privilegios de dueño. El tenant se fija por transacción con `SET LOCAL app.current_tenant`, nunca con `SET`.
- Todo acceso a datos pasa por la capa que aplica el tenant de la petición. Nunca escribir consultas que omitan ese filtro.
- El tenant se resuelve en el servidor (subdominio + sesión), nunca desde un parámetro enviado por el cliente.
- Usuarios, sesiones y tokens pertenecen a un tenant; los de un tenant se rechazan en otro.
- Dominio `lablinea.cionetworks.com`: laboratorios en `<laboratorio>.lablinea.cionetworks.com`, Admin Hub en `admin.lablinea.cionetworks.com`. Cookies con prefijo `__Host-`, sin atributo `Domain`.
- Identificadores públicos no secuenciales (UUID) en URLs y API.
- Toda funcionalidad incluye una prueba de aislamiento: un usuario del tenant A no puede leer, modificar ni inferir datos del tenant B.

## Reglas de negocio que no se pueden romper

- **Órdenes** ([funcional/0002](specs/funcional/0002-pos-ordenes-caja.md)): solo se editan en `BORRADOR`. Al pre-cerrar se congelan precios, exámenes y descuentos; después solo se anulan (con permiso y motivo). Descuentos sobre el tope del convenio exigen autorización superior y evidencia.
- **Caja:** el cierre es irreversible y registra la diferencia entre lo esperado y lo contado.
- **Muestras** ([funcional/0003](specs/funcional/0003-muestras-impresion.md)): solo se toman de órdenes `PAGADA`. Los tubos se agrupan por tipo de muestra **y** tipo de tubo. El servidor nunca imprime directo a una IP del laboratorio.
- **Resultados** ([funcional/0004](specs/funcional/0004-resultados-validacion-entrega.md)): solo inserción; las correcciones son versiones nuevas y exigen revalidar. Banderas y notas internas **nunca** llegan al paciente, al PDF ni al correo. Los valores críticos se comunican aunque haya saldo pendiente.
- **Entrega:** el correo solo avisa y enlaza al portal; nunca adjunta el PDF ni lleva datos clínicos. En el PDF y el portal solo puede aparecer la marca `H`/`L` en valores numéricos, si el laboratorio la activó.
- **Facturación electrónica** ([infraestructura/0009](specs/infraestructura/0009-facturacion-electronica.md)): siempre a través de la interfaz `FacturadorElectronico` del país; nunca llamar a la DIAN ni a un tercero desde las rutas. Certificados digitales solo en el gestor de secretos. Una factura validada no se modifica: se emiten notas.
- **Analítica** ([infraestructura/0010](specs/infraestructura/0010-analitica-bodega-datos.md), propuesta): el dashboard histórico consulta la bodega, no la base transaccional. La bodega nunca recibe nombres, documentos, contactos ni valores de resultados.
- **Dinero** en `NUMERIC` con moneda y tasa de cambio; nunca `float`.

## Integración (ver [infraestructura/0006](specs/infraestructura/0006-integracion-his-equipos.md))

- FHIR R4 es el único modelo interno. HL7 v2.5.1 (sistemas de clientes) y ASTM (equipos) se convierten a FHIR en el borde.
- Los equipos de análisis se integran a través del conector local, que solo hace conexiones HTTPS salientes.
- Los resultados que llegan de equipos nunca se publican sin validación en el LIS.

## Cumplimiento normativo (obligatorio)

El software debe cumplir HL7 en interoperabilidad y HIPAA en seguridad de la información. Ninguna funcionalidad se da por terminada si incumple alguna de estas reglas.

### HL7 FHIR R4 (ver [infraestructura/0002](specs/infraestructura/0002-interoperabilidad-hl7-fhir.md))

- Todo intercambio de datos clínicos usa recursos FHIR R4 en JSON (`application/fhir+json`), validados con `fhir.resources`.
- El modelo relacional (heredado del dominio de Lablinea) tiene un mapeo explícito y probado a `Patient`, `ServiceRequest`, `Specimen`, `Observation` y `DiagnosticReport`.
- Exámenes codificados con LOINC; unidades con UCUM.
- Si llega HL7 v2, se convierte a FHIR en el borde; v2 no circula dentro de la aplicación.

### HIPAA Security Rule (ver [infraestructura/0003](specs/infraestructura/0003-seguridad-hipaa.md))

- **Autorización en el servidor y a nivel de objeto:** toda consulta de PHI filtra por el usuario autenticado. Un paciente solo ve sus propios resultados.
- **Auditoría:** todo acceso, creación, modificación, exportación o eliminación de PHI genera un registro de auditoría (quién, qué, cuándo, desde dónde, resultado). Las escrituras las registran triggers; las lecturas, la aplicación.
- **Sin PHI** en URLs, parámetros de consulta, mensajes de error, logs de aplicación, analítica de terceros, correos ni SMS.
- **Respuestas con PHI:** `Cache-Control: no-store`. Formularios con protección CSRF. Cookies `Secure`, `HttpOnly`, `SameSite`.
- **Cifrado:** TLS 1.2+ en tránsito; AES-256 en reposo (BD, archivos, copias de seguridad).
- **Contraseñas** con Argon2id; segundo factor en **cada** inicio de sesión para todos los usuarios; sesión en servidor con cookie (no JWT en el navegador); cierre a los 15 minutos de inactividad ([infraestructura/0008](specs/infraestructura/0008-autenticacion-autorizacion.md)).
- **Resultados validados no se sobrescriben:** las correcciones crean una versión nueva.
- **Secretos** solo en variables de entorno o gestor de secretos, nunca en el código ni en el repositorio.
- **Solo datos sintéticos** en desarrollo, pruebas y repositorio.
- **Proveedores:** no integrar ningún servicio externo que reciba PHI si no ofrece BAA.

### Colombia y Latinoamérica (ver [infraestructura/0004](specs/infraestructura/0004-normativa-colombia-latam.md))

- Opera en Colombia con alcance Latinoamérica. HIPAA es el marco de controles; la ley local es la obligación legal y prevalece si es más exigente.
- **Ley 1581 de 2012:** los datos de salud son sensibles. No se procesa PHI de un titular sin autorización previa, expresa y registrada; la autorización es revocable, y el titular puede consultar, rectificar y suprimir sus datos.
- **IHCE** (Ley 2015 de 2020, Res. 866 de 2021): usar los perfiles FHIR del Ministerio de Salud. Exámenes con CUPS además de LOINC.
- **Pacientes** identificados con tipo y número de documento; cada paciente, laboratorio y resultado tiene país.
- **Nada específico de un país escrito directamente en el código** (tipos de documento, textos legales, idioma, zona horaria, terminologías): va en configuración por país.
- **Textos de plantillas externalizados** para i18n (`es-CO` por defecto). Fechas en UTC en la base de datos; zona local solo al mostrarlas.
- **Ningún país nuevo** se habilita sin su spec de normativa aceptada.

### Pruebas de cumplimiento

Toda funcionalidad que toque PHI incluye pruebas que verifiquen:
- que un usuario no puede acceder a datos de otro usuario ni de otro tenant (respuesta 403 o 404);
- que se genera el registro de auditoría;
- que la respuesta lleva las cabeceras de seguridad requeridas.

Todo endpoint FHIR incluye una prueba que valide el JSON contra el recurso R4 correspondiente.

## Comandos

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload   # servidor local
pytest                          # pruebas (migra solo la base lablinea_test)
alembic upgrade head            # migrar la base de desarrollo
scripts/verificar.sh            # compuerta automática: correrla antes de cada commit
scripts/servidor_https.sh       # HTTPS local en https://lab-a.lablinea.localhost:8443
scripts/escaneo_externo.sh      # ZAP pasivo + activo; falla con hallazgos altos o medios
python trabajador.py            # tareas en segundo plano
python scripts/crear_usuario_plataforma.py <correo> "<nombre>" ADMIN_MAESTRO   # personal del Admin Hub
```

- **Formularios:** toda ruta POST declara `_csrf: Csrf` (lo verifica `tests/test_csrf.py`) y sus campos de texto usan `TextoSeguro` con `max_length`. Permisos con `requiere_permiso(modulo, operacion)` o `requiere_accion(ACCION)`.
- **SQL:** solo texto literal con parámetros (`:nombre`); nunca f-strings ni concatenación, aunque el valor sea constante (bandit lo bloquea).
- **Pruebas de formularios:** además de TestClient, fuzzing con token CSRF válido (`tests/test_fuzzing_formularios.py`) y flujos en Chromium (`tests/e2e/`).
- Toda petición debe llegar con un `Host` del dominio propio (`TrustedHostMiddleware`): en pruebas, usar `base_url="http://lab-a.lablinea.localhost"`.

- Acceso a datos de un laboratorio **siempre** con `app.core.db.sesion_tenant(tenant_id)`; nunca abrir sesiones sin tenant sobre `lab`. El Admin Hub usa `sesion_plataforma()` (rol sin acceso a `lab`); el código común a los dos sitios usa `sesion_del_sitio(sitio)` y tablas sin esquema.
- **Sitios** ([infraestructura/0005](specs/infraestructura/0005-arquitectura-saas-multitenant.md)): toda ruta declara su sitio con `LaboratorioActual`, `sitio_admin` (router del Admin Hub) o `SitioActual`; `tests/test_admin.py::test_toda_ruta_declara_su_sitio` lo verifica. Las plantillas reciben el sitio como `sitio`.
- **Contraseñas:** nadie fija la contraseña de otra persona; los usuarios nuevos se crean sin ella y reciben una invitación (`app/auth/invitaciones.py`).
- **Suscripción** ([funcional/0005](specs/funcional/0005-plataforma-saas-suscripciones.md)): toda ruta que cree órdenes declara `_suscripcion: SuscripcionVigente`. Nunca en la consulta de resultados ni en la exportación de datos.
- **Dinero:** `Decimal` y `NUMERIC`; formato con el filtro `|dinero(moneda)`. Validar números de formularios con expresiones de dígitos ASCII (`[0-9]`), no con `str.isdigit()` (acepta "²" y rompe `int()`).
- **Parámetros de la URL que eligen un texto** (p. ej. `?error=`) se traducen con una lista blanca: nunca se arma una clave del catálogo con lo que llega del cliente.
- **Auditoría** ([infraestructura/0007](specs/infraestructura/0007-base-de-datos.md)): toda tabla nueva de `lab` lleva el trigger `lab.auditar(...)`, con sus columnas secretas como argumento, o se justifica en `SIN_TRIGGER` de `tests/test_auditoria.py`. Toda lectura o exportación de datos personales o de salud llama a `app.core.auditoria.registrar_acceso()` con identificadores y conteos, nunca contenido.
- **Tareas** ([infraestructura/0012](specs/infraestructura/0012-cola-de-tareas.md)): `app.core.tareas.encolar()` dentro de `sesion_tenant`. Los datos de la tarea son solo identificadores. Nunca registrar el mensaje de una excepción, solo su tipo.
- **Textos** ([infraestructura/0013](specs/infraestructura/0013-textos-externalizados-i18n.md)): todo texto para el usuario va en `app/locales/es-CO.toml` y se usa con `t()`. Fechas con el filtro `|fecha`. `tests/test_i18n.py` falla si una plantilla tiene texto escrito directamente.
- **Datos de prueba** con `scripts/sinteticos.py`. La suite falla si un dato de un paciente sintético aparece en cualquier log.
- Migraciones escritas a mano en `migrations/versions/` (sin autogenerate), con `upgrade` y `downgrade`. Toda tabla nueva en `lab` incluye `tenant_id`, RLS habilitado y forzado, y política con `USING` y `WITH CHECK`; `tests/test_db.py::test_toda_tabla_de_lab_cumple_rls` lo verifica.
- La CI (`.github/workflows/ci.yml`) corre las pruebas contra PostgreSQL 18 en cada push y pull request.

## Reglas de desarrollo

- Toda ruta nueva lleva al menos una prueba en `tests/`. `pytest` debe pasar antes de dar una tarea por terminada.
- Textos de la interfaz, specs y documentación en español. Código (nombres de variables, funciones) puede ir en inglés o español, siguiendo el estilo del archivo.
- Nunca versionar datos reales de pacientes (PDFs, exportaciones, bases de datos). `Synlab_resultados.pdf` no se sube al repositorio.
- No hacer commit ni push sin que el usuario lo pida.

## Al tomar una decisión

Si durante el trabajo se decide algo de infraestructura (base de datos, autenticación, hosting, librerías) o funcional (flujos, reglas de negocio):

1. Crear la spec en `specs/infraestructura/` o `specs/funcional/` a partir de [specs/plantilla.md](specs/plantilla.md), con el siguiente número `NNNN` de esa carpeta.
2. Agregarla al índice de [specs/README.md](specs/README.md).
3. Si reemplaza otra, marcar la anterior como `Reemplazada por NNNN`. Nunca borrar specs.

## Al cerrar una etapa del plan (obligatorio)

Ninguna etapa del [plan](specs/plan-desarrollo.md) se da por terminada sin pasar la **compuerta de calidad** de [infraestructura/0011](specs/infraestructura/0011-calidad-pruebas-entorno-local.md): pruebas funcionales y E2E, cobertura ≥ 85%, aislamiento, autorización, auditoría, ruff, bandit, pip-audit, gitleaks, ZAP activo autenticado (cero hallazgos altos o medios), schemathesis, pruebas manuales dirigidas y rendimiento cuando aplique. La evidencia va en `specs/etapas/etapa-NN.md` (plantilla en `specs/etapas/plantilla-cierre.md`). Si algo falla, la etapa sigue abierta; un riesgo solo se acepta con aprobación explícita del usuario.

Todo se construye y prueba **en local** (HTTPS con mkcert en `*.lablinea.localhost`, SMTP de captura, datos sintéticos); la publicación es la etapa 20.

## Al terminar una tarea

1. Actualizar [specs/backlog.md](specs/backlog.md): mover la tarea a `Hecho` con fecha y spec relacionada, y agregar pendientes nuevos.
2. Agregar o completar la entrada del día en [specs/daily.md](specs/daily.md) (más reciente arriba): avances, decisiones y bloqueos.
