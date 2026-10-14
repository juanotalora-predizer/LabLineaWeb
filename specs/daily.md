# Daily

Bitácora diaria de avances y decisiones. La entrada más reciente va arriba.

Las decisiones relevantes se formalizan después como spec en `infraestructura/` o `funcional/`.

<!--
Plantilla:

## AAAA-MM-DD

**Avances**
-

**Decisiones**
-

**Bloqueos / pendientes**
- Validar el IVA de la suscripción con el asesor tributario.
-
-->

## 2026-10-14

**Avances**
- **Etapa 7 cerrada** ([informe](etapas/etapa-07.md), [funcional/0010](funcional/0010-pacientes-ley-1581.md)): commit `0beeb6c`, CI verde.
  - Pacientes por tipo y número de documento (expresión válida por país) y país de residencia.
  - Autorización de tratamiento de datos versionada: la base no guarda un paciente sin ella, permite una sola vigente y solo deja revocarla.
  - Representante legal obligatorio para menores.
  - Solicitudes del titular con vencimiento en días hábiles (festivos de Colombia como configuración), informe *Datos del titular* auditado y supresión por anonimización.
  - Búsqueda por POST, documento exacto, tope de 20 y límite de 60 por 5 minutos.
  - La auditoría marca los datos personales como protegidos: tras una supresión no queda nada del paciente en ninguna tabla.
  - 966 pruebas, cobertura 99%, ZAP sin hallazgos altos ni medios en los dos sitios, 15/15 pruebas manuales.
- Hallazgo: el log de acceso guarda toda URL que mande un cliente; se suma al pendiente de la etapa 20 (logs sin cadena de consulta).

**Decisiones**
- **Bodega de datos separada** aprobada ([infraestructura/0010](infraestructura/0010-analitica-bodega-datos.md) pasa a Aceptada).
- **Inventarios y equipos entran al MVP** ([funcional/0011](funcional/0011-inventarios-equipos-proveedores.md), nueva etapa 14b): insumos (reactivos, jeringas, gasa, tapabocas…) con unidades de compra, costo total, fecha de adquisición y costo unitario calculado con ajuste manual; equipos con proveedor, fecha de compra, factura, valor y mantenimientos preventivos, correctivos y predictivos (entrega, devolución, fotos, razón y proveedor). Proveedores en una tabla propia por laboratorio, con contactos e histórico; convenios en tablas aparte.
- El consumo de insumos se registra a mano; el descuento automático por examen y el costeo por actividad con nómina ligera quedan para después del MVP.
- Los proveedores son de compra de ítems (reactivos, consumibles, equipos, otros) y de mantenimiento de equipos; el laboratorio no vende ítems.
- Supresión = anonimización irreversible (no borrado) para no romper la auditoría ni las solicitudes; con historia clínica se rechaza por el deber de conservarla. Por validar con el asesor legal.

## 2026-10-13

**Avances**
- **Etapa 6 cerrada** ([informe](etapas/etapa-06.md), [funcional/0009](funcional/0009-catalogo-e-importador.md)): commit `c19fed6`, CI verde.
  - Catálogo por laboratorio: maestros, exámenes con CUPS y LOINC, parámetros, listas, requisitos de muestra, precios por tarifa y códigos alternos. Exámenes y parámetros no se borran, se desactivan.
  - Rangos por sexo y edad en días con críticos; advertencias de huecos y solapes (propiedad con hypothesis).
  - Importador de Lablinea: ZIP con las tablas del catálogo en CSV (nunca el `.mdb`), límites estrictos, rechazo de tablas que no son del catálogo, vista previa, carga atómica y rangos importados marcados por revisar.
  - Exportación CSV que neutraliza fórmulas y queda auditada.
  - 846 pruebas, cobertura 99,1%, ZAP sin hallazgos altos ni medios en los dos sitios, 17/17 pruebas manuales.
- Hallazgos: ZAP encontró un error 500 con un byte NUL en la búsqueda del catálogo (corregido con `TextoSeguro`) y un falso positivo de inyección SQL en los formularios del catálogo, verificado en la base y filtrado solo para esa regla y esas rutas. Las pruebas con hypothesis mostraron que `csv.Sniffer` no era confiable para el separador.
- **Sistema de diseño** ([funcional/0008](funcional/0008-sistema-de-diseno.md)), a partir de tres referencias del usuario (HMLR, Datacapt, eMedico).
  - Menú lateral azul noche, tarjetas blancas sobre fondo gris azulado, azul primario para la acción e insignias de estado con punto y texto.
  - Inter e íconos Lucide servidos como estáticos propios.
  - Todas las pantallas rediseñadas, incluida la vista móvil. Patrones definidos para la ficha de paciente y las colas de trabajo.
  - Guardianes: colores solo como tokens, contraste AA, sin estilos en línea y todo ícono existe en el sprite.
  - El guardián de contraste detectó que el gris secundario de las referencias (`#64748B`) no cumple AA sobre el fondo de la aplicación (4,40:1); se usa `#5F6F86`.
- **Etapa 5 cerrada** ([informe](etapas/etapa-05.md)): commit `cc0e1d3`, CI verde.
  - Licencias y suscripciones: el estado efectivo vence en el instante exacto; suspensión, cancelación, renovación automática y avisos de renovación 7 días y 1 día antes.
  - Facturas de la plataforma inmutables, con precios por país y plan, campañas e IVA del país; pagos parciales cuyo saldo y estado calcula la base, sin sobrepagos ni con pagos simultáneos; al pagarse extienden la suscripción.
  - Soporte autorizado por el laboratorio (máximo 72 horas, revocable): tiquete de un solo uso, sesión de solo lectura, cada petición auditada y la autorización verificada en cada petición.
  - 571 pruebas (136 nuevas, incluidas pruebas con hypothesis de saldo y facturas contra la base real), cobertura 99%, ZAP sin hallazgos en los dos sitios, 12/12 pruebas manuales.
- Hallazgos: el E2E mostró que la CSP bloqueaba la redirección del Admin Hub al laboratorio (ahora es un enlace); el fuzzing encontró un error 500 con "²" (`str.isdigit()`), corregido también en los planes de la etapa 4.
- **Etapa 4 cerrada** ([informe](etapas/etapa-04.md)): commit `14bc0d3`, CI verde.
  - Admin Hub en `admin.<dominio>` con su propio esquema, rol de base de datos, usuarios, roles y auditoría; mismo código de ingreso que los laboratorios (el `search_path` de la transacción decide el esquema).
  - Alta de laboratorio atómica (laboratorio, sede, roles, administrador e invitación); el administrador crea su propia contraseña con un enlace de un solo uso.
  - Planes con módulos y máximo de usuarios; fuera del plan, 403 y fuera del menú.
  - Invitar y desactivar usuarios desde el laboratorio.
  - 435 pruebas (129 nuevas), cobertura 99,5%, ZAP sin hallazgos altos, medios ni bajos en lab-a y en el Admin Hub, 14/14 pruebas manuales con el trabajador real.
- **Etapa 3 cerrada** ([informe](etapas/etapa-03.md)): commit `77a82ea`, CI verde.
- Migración `0004`: auditoría `lab.auditoria` particionada por mes, de solo inserción, con trigger genérico (antes y después, usuario, IP, secretos protegidos) y registro de lecturas y accesos denegados desde la aplicación. Esquema `cola` para tareas.
- Cola de tareas propia (`app/core/tareas.py`, `trabajador.py`): reintentos con espera exponencial, ejecución única aunque un trabajador muera (probado con `SIGKILL`), cada tarea con el laboratorio con que se encoló.
- Textos externalizados en `app/locales/es-CO.toml` con `t()`; zona horaria del país al mostrar fechas; conexión a la base en UTC.
- Generador de personas sintéticas (`scripts/sinteticos.py`) y búsqueda automática de sus datos en todos los logs de la corrida de pruebas.
- 305 pruebas (79 nuevas), cobertura 99,3%, ZAP autenticado sin hallazgos altos, medios ni bajos, 11/11 pruebas manuales.

**Decisiones**
- Separación de sitios por dependencia de host con guardián, en lugar de dos sub-aplicaciones montadas ([infraestructura/0005](infraestructura/0005-arquitectura-saas-multitenant.md)).
- Ningún usuario recibe una contraseña de otra persona: todos la crean con una invitación ([infraestructura/0008](infraestructura/0008-autenticacion-autorizacion.md)).
- Cola de tareas propia sobre PostgreSQL, sin librería externa ([infraestructura/0012](infraestructura/0012-cola-de-tareas.md)).
- Catálogos de textos en TOML con la biblioteca estándar, sin Babel ([infraestructura/0013](infraestructura/0013-textos-externalizados-i18n.md)).
- Las particiones de la auditoría se crean sin privilegios para la aplicación: consultadas directamente no aplican el RLS de la tabla madre.

**Bloqueos / pendientes**
- Riesgo bajo documentado: el token de invitación queda en la URL (un solo uso, 72 horas); en la etapa 20 el log del proxy no debe guardar esa ruta.
- Hallazgo: la configuración de logs de Alembic deshabilitaba los loggers de la aplicación durante las pruebas, así que las pruebas de logs de la etapa 2 no veían nada. Corregido; ahora las pruebas exigen que haya registros.

## 2026-10-12

**Avances**
- Carpeta local conectada al repositorio `juanotalora-predizer/LabLineaWeb` (rama `main`).
- Creada la carpeta `specs/` con subcarpetas `infraestructura/` y `funcional/`, plantilla de decisiones, `backlog.md` y `daily.md`.
- Estructura base de la aplicación: `app/main.py`, plantillas `base.html` e `index.html`, CSS, endpoint `/health` y 3 pruebas con pytest (pasan).

- **Sprint 0 completado:** `app/core/config.py` (settings desde `.env`), `app/core/db.py` (`sesion_tenant` fija tenant, usuario e IP con `set_config(..., true)`), Alembic asíncrono con la migración `0001` (aplicada en `lablinea_dev` y `lablinea_test`, downgrade probado), CI en GitHub Actions con PostgreSQL 18. 11 pruebas pasan, incluida la que demuestra que el tenant no se filtra al reutilizar una conexión del pool.
- Se comprobó a mano que el guardián de RLS falla con una tabla sin RLS y con RLS sin `FORCE`.

- **Etapa 0 cerrada** ([informe](etapas/etapa-00.md)): herramientas de calidad y seguridad (ruff, bandit, pip-audit, gitleaks, schemathesis, ZAP 2.17 sobre OpenJDK 21), HTTPS local con mkcert en `*.lablinea.localhost`, cabeceras de seguridad, `scripts/verificar.sh` en local y CI. 45 pruebas, cobertura 100%, ZAP 0 altos/medios/bajos.
- Hallazgo de seguridad en pruebas manuales: cabecera `Host` ajena reflejada en redirecciones; corregido con `TrustedHostMiddleware` y pruebas de regresión.

- **Etapa 1 cerrada** ([informe](etapas/etapa-01.md)): rol `lablinea_plataforma`, migración 0002 (monedas, países, tipos de documento, laboratorios, `acceso.resolver_laboratorio`), resolución del laboratorio por subdominio. 122 pruebas, cobertura 100%, ZAP sin hallazgos; 600 peticiones concurrentes entre laboratorios sin cruces.
- El rol `lablinea_metricas` (con `BYPASSRLS`) se pospone a las etapas 15–16 por mínimo privilegio.

- **Etapa 2 cerrada** ([informe](etapas/etapa-02.md)): autenticación en dos pasos (Argon2id + TOTP o código por correo), sesiones `__Host-` con rotación y vencimientos, CSRF de doble envío, bloqueos sin enumeración, roles y permisos. 226 pruebas (5 en Chromium), cobertura 99%, ZAP autenticado 0 altos/medios/bajos, 11/11 pruebas manuales.
- Las pruebas encontraron 3 errores, ya corregidos: `Referrer-Policy: no-referrer` bloqueaba todos los formularios en el navegador; el carácter nulo daba 500; un fallo del correo daba 500. También se detectó que el primer escaneo ZAP no estaba realmente autenticado.

- Prueba manual del usuario: el ingreso funciona; se aclaró que en desarrollo los códigos aparecen en la terminal del SMTP de captura. `servidor_https.sh` ahora avisa si el puerto 8443 está ocupado.

**Decisiones**
- Las decisiones de infraestructura y funcionales se registran en `specs/`, un archivo por decisión.
- Stack base: FastAPI + Jinja2 con renderizado en servidor ([infraestructura/0001](infraestructura/0001-stack-fastapi-jinja2.md)).
- `CLAUDE.md` en la raíz con las reglas para cumplir las specs.
- Los datos reales de pacientes no se versionan; `Synlab_resultados.pdf` queda en `.gitignore`.
- Interoperabilidad con HL7 FHIR R4, terminologías LOINC/UCUM ([infraestructura/0002](infraestructura/0002-interoperabilidad-hl7-fhir.md)).
- Seguridad de la información según HIPAA Security Rule, con todos los controles técnicos como obligatorios ([infraestructura/0003](infraestructura/0003-seguridad-hipaa.md)).

- Operación en Colombia con alcance Latinoamérica: Ley 1581 de 2012 e IHCE (Ley 2015 de 2020, Res. 866 de 2021) como obligación legal; HIPAA como marco de controles; configuración por país para la expansión ([infraestructura/0004](infraestructura/0004-normativa-colombia-latam.md)).

- Cambio de alcance: LabLineaWeb es un **LIS en modalidad SaaS**, multi-laboratorio, que inicia en Colombia con alcance Latinoamérica ([funcional/0001](funcional/0001-producto-lis-saas.md)).
- Arquitectura multi-tenant: tenant = laboratorio, base compartida con `tenant_id` y seguridad a nivel de fila, celdas regionales ([infraestructura/0005](infraestructura/0005-arquitectura-saas-multitenant.md)).
- Integración: FHIR como modelo interno, HL7 v2.5.1 soportado para HIS de clientes, conector local para equipos de análisis ([infraestructura/0006](infraestructura/0006-integracion-his-equipos.md), modifica el punto 8 de 0002).
- Rol legal: el laboratorio es Responsable del tratamiento y LabLineaWeb es Encargado (Ley 1581) y *Business Associate* (HIPAA).

- La descripción funcional del sistema está en cuadernos de NotebookLM; sus fuentes se copiarán a `specs/fuentes/` para convertirlas en specs funcionales.

- Se leyeron las 27 fuentes de NotebookLM (descripción de la migración de Lablinea, en Access, a SaaS) y se convirtieron en specs funcionales 0002 a 0007 e infraestructura 0007 (PostgreSQL con RLS) y 0008 (autenticación).
- Conflictos con las fuentes resueltos: se mantiene **Jinja2 + htmx + Chart.js** (no React); el correo **solo avisa y enlaza al portal**, sin PDF adjunto.
- Migración desde Lablinea: **solo el catálogo**; no pacientes ni resultados históricos.
- **MVP = fases 1 a 5** del plan de desarrollo + cumplimiento; inventarios, costeo y dashboard después ([funcional/0007](funcional/0007-alcance-mvp.md)).
- Ajustes técnicos a las fuentes: RLS con `FORCE`, `WITH CHECK` y `SET LOCAL`; UUID públicos; auditoría con antes y después protegida como dato clínico; agrupación de tubos también por tipo de tubo; impresión con QZ Tray (no por IP desde la nube); valores críticos comunicados aunque haya saldo pendiente.

- Plan de desarrollo ([plan-desarrollo.md](plan-desarrollo.md)): Tenant App y Admin Hub como dos sub-aplicaciones por host en un solo despliegue; 4 roles de base de datos; métricas del Admin Hub por agregados sin datos clínicos; 15 sprints en 4 fases; arquitectura de plantillas PDF.
- Preparado `scripts/crear_bd_local.sql`, `.env.example` y `.env` local para PostgreSQL 18 (EDB).
- **Decisiones del usuario:** dominio `lablinea.cionetworks.com` (laboratorios en `<lab>.lablinea.cionetworks.com`, cookies `__Host-`); sin comisiones en el Admin Hub; facturación electrónica directa con la DIAN y tercero por país si no hay API ([infraestructura/0009](infraestructura/0009-facturacion-electronica.md)); marca H/L opcional en el PDF; dashboard interactivo completo en el MVP.
- Propuesta de bodega analítica separada con replicación lógica, datamarts de laboratorio (RLS), país y plataforma, y pacientes seudonimizados ([infraestructura/0010](infraestructura/0010-analitica-bodega-datos.md), pendiente de aprobación).
- La hoja de ruta pasa de 15 a 20 sprints.
- **Bluehost descartado como hosting de la aplicación:** no firma BAA y sus términos prohíben alojar información de salud protegida.

- Comparación de costos Google Cloud vs Azure (≈ USD 575 vs 600–700/mes en producción; diferencia principal: WAF).
- **Decisión:** construir y probar todo en local; el hosting se decide antes de publicar.
- Plan reescrito como plan paso a paso de 21 etapas (0 a 20); ninguna etapa se cierra sin la compuerta de calidad funcional, de seguridad interna y externa, y su informe ([infraestructura/0011](infraestructura/0011-calidad-pruebas-entorno-local.md)). La etapa 0 queda abierta hasta pasar esa compuerta.

**Bloqueos / pendientes**
- Elegir hosting con BAA (antes de la etapa 20).
- Aprobar la spec 0010 y decidir si inventarios y costeo entran al MVP.
- Validar la spec 0004 con asesoría legal.
