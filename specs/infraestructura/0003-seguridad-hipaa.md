# 0003. Seguridad de la información: HIPAA

- **Estado:** Aceptada
- **Fecha:** 2026-10-12
- **Responsable:** Juan Otálora

## Contexto

LabLineaWeb maneja resultados de laboratorio, que son información de salud protegida (PHI, *Protected Health Information*). El software debe cumplir la norma HIPAA en seguridad de la información, en particular la **Security Rule** (45 CFR Parte 164, Subparte C), que exige salvaguardas administrativas, físicas y técnicas para la PHI en formato electrónico (ePHI).

El cumplimiento de HIPAA no depende solo del software: también exige políticas, capacitación y contratos de la organización. Esta spec define lo que le corresponde a la aplicación y lista lo organizacional como dependencia.

## Decisión

Se tratan como **obligatorios** todos los controles técnicos de la Security Rule, incluidos los que la norma marca como "addressable" (cifrado, cierre automático de sesión).

### Control de acceso (§164.312(a))

- Cuenta única por usuario; prohibido compartir cuentas.
- Autenticación multifactor (MFA) obligatoria para personal del laboratorio y administradores; disponible para pacientes.
- Contraseñas con hash Argon2id (o bcrypt); nunca en texto plano ni con cifrado reversible.
- Bloqueo temporal tras intentos fallidos repetidos.
- Cierre automático de sesión por inactividad: 15 minutos.
- Autorización por roles (paciente, médico, personal del laboratorio, administrador) y **verificación a nivel de objeto**: un paciente solo accede a sus propios resultados. Toda consulta de PHI filtra por el usuario autenticado en el servidor.
- Principio de mínimo necesario: cada rol ve solo los datos que necesita.
- Procedimiento de acceso de emergencia documentado y auditado.

### Controles de auditoría (§164.312(b))

- Registro de auditoría de todo acceso, creación, modificación, exportación y eliminación de PHI: quién, qué recurso, qué acción, cuándo, desde qué IP y con qué resultado.
- También se registran inicios de sesión (exitosos y fallidos), cambios de permisos y accesos de emergencia.
- Registro de solo escritura (append-only), separado de los logs de aplicación, conservado mínimo 6 años.
- Los logs referencian identificadores, nunca contenido clínico. *(Modificado por [0007](0007-base-de-datos.md): la tabla de auditoría sí guarda el registro antes y después del cambio, y por eso se protege como dato clínico. Los logs de la aplicación siguen sin contenido clínico.)*

### Integridad (§164.312(c))

- Los resultados validados no se sobrescriben: las correcciones generan una nueva versión y conservan la anterior.
- Hash (SHA-256) de cada informe PDF para detectar alteraciones.

### Autenticación de personas y entidades (§164.312(d))

- Sistemas externos (API FHIR) se autentican con OAuth 2.0 / SMART on FHIR; nunca con credenciales compartidas o claves en la URL.

### Seguridad en la transmisión (§164.312(e))

- Solo HTTPS con TLS 1.2 o superior; HSTS activado. Sin endpoints HTTP en producción.
- No enviar PHI por correo electrónico ni SMS: las notificaciones solo avisan que hay un resultado disponible y enlazan al portal.

### Cifrado en reposo

- Base de datos, archivos (PDFs) y copias de seguridad cifrados con AES-256.
- Claves y secretos en variables de entorno o gestor de secretos; nunca en el repositorio.

### Protección de la aplicación web

- Protección CSRF en todos los formularios.
- Cabeceras de seguridad: `Content-Security-Policy`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`.
- `Cache-Control: no-store` en toda respuesta que contenga PHI.
- Cookies de sesión `Secure`, `HttpOnly`, `SameSite=Lax` o `Strict`.
- Sin PHI en URLs, parámetros de consulta, mensajes de error, logs de aplicación ni herramientas de analítica de terceros.
- Plantillas Jinja2 con autoescape activado.

### Datos y entornos

- Desarrollo y pruebas usan **solo datos sintéticos**. Nunca se copian datos reales de producción a otros entornos ni al repositorio.
- Copias de seguridad cifradas, con restauración probada periódicamente.

### Proveedores

- Todo proveedor que almacene o procese PHI (hosting, base de datos, correo, almacenamiento, monitoreo) debe firmar un **BAA** (*Business Associate Agreement*). Un proveedor sin BAA no puede recibir PHI.

## Alternativas consideradas

- **Aplicar solo los controles "required" de HIPAA:** reduce trabajo inicial, pero dejar sin cifrado o sin cierre de sesión es un riesgo inaceptable para datos de salud y difícil de justificar ante una auditoría.
- **Delegar la seguridad por completo a la plataforma de hosting:** la plataforma cubre la infraestructura, pero el control de acceso, la auditoría y la protección de la aplicación son responsabilidad del software.

## Consecuencias

- Restringe las decisiones pendientes: la base de datos y el hosting deben soportar cifrado en reposo y ofrecer BAA; la autenticación debe soportar MFA.
- Cada funcionalidad que toque PHI debe incluir pruebas de autorización (un usuario no puede ver datos de otro) y verificar que genera registro de auditoría.
- **Fuera del software (responsabilidad organizacional):** análisis de riesgos documentado, políticas de seguridad, oficial de seguridad designado, capacitación del personal, procedimiento de notificación de brechas y firma de BAAs.
- **Rol como SaaS** ([funcional/0001](../funcional/0001-producto-lis-saas.md)): los laboratorios clientes son las entidades cubiertas y LabLineaWeb es su *Business Associate*. Se firma un BAA con cada laboratorio cliente que lo requiera, y nuestros propios proveedores firman BAA con nosotros (*subcontractors*). El aislamiento entre laboratorios se define en [0005](0005-arquitectura-saas-multitenant.md).
- Normativa local: resuelto en [0004](0004-normativa-colombia-latam.md). HIPAA es el marco de controles técnicos; la ley local (en Colombia, la Ley 1581 de 2012) es la obligación legal y prevalece cuando es más exigente.
