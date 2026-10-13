# 0005. Arquitectura SaaS multi-tenant

- **Estado:** Aceptada
- **Fecha:** 2026-10-12
- **Responsable:** Juan Otálora

## Contexto

LabLineaWeb es un LIS en modalidad SaaS ([funcional/0001](../funcional/0001-producto-lis-saas.md)). Varios laboratorios comparten la plataforma y cada uno guarda datos de salud de sus pacientes. La filtración de datos de un laboratorio a otro es el riesgo más grave del producto. Además, la expansión a Latinoamérica puede exigir que los datos de cada país se alojen en una región específica ([0004](0004-normativa-colombia-latam.md)).

## Decisión

### Tenant

- **Tenant = laboratorio cliente.** Un tenant puede tener varias **sedes**.
- Cada tenant tiene un **país** fijo, del que salen su configuración regulatoria, idioma, zona horaria, terminologías y región de alojamiento.
- Acceso por subdominio propio del tenant (p. ej. `<laboratorio>.<dominio>`). El tenant se resuelve en el servidor a partir del subdominio y la sesión, nunca a partir de un parámetro que envíe el cliente.
- **Dominio (decidido el 2026-10-12):** `lablinea.cionetworks.com`. Laboratorios en `<laboratorio>.lablinea.cionetworks.com` y Admin Hub en `admin.lablinea.cionetworks.com`. Requiere DNS comodín (`*.lablinea.cionetworks.com`) y un certificado TLS comodín para ese nivel.
- Como `cionetworks.com` aloja otros sitios, las cookies de sesión usan el prefijo `__Host-` (solo para el host exacto, sin atributo `Domain`): ningún otro sitio de `cionetworks.com` puede leerlas ni sobrescribirlas.

### Aislamiento de datos (doble barrera)

1. **Base de datos compartida con `tenant_id` en toda tabla con datos del laboratorio**, y aislamiento forzado en el motor con **seguridad a nivel de fila** (*row-level security*). Una consulta sin tenant definido no devuelve filas.
2. **Capa de aplicación:** todo acceso a datos pasa por un repositorio que aplica el tenant del contexto de la petición. No se escriben consultas que omitan ese filtro.

Si un cliente grande o una ley local lo exige, el tenant puede moverse a una **base de datos dedicada** sin cambiar el código, porque el código ya trabaja siempre con un tenant explícito.

### Despliegue por región (celdas)

- La plataforma se despliega en **celdas regionales**: cada celda tiene su aplicación y su base de datos. La primera celda atiende a Colombia.
- Un tenant vive en una sola celda; sus datos clínicos no salen de ella.
- Lo global (catálogo de planes, directorio de tenants y en qué celda vive cada uno) se guarda aparte y sin datos clínicos.

### Seguridad entre tenants

- Usuarios, sesiones y tokens pertenecen a un tenant; un token de un tenant es rechazado en otro.
- Identificadores públicos no secuenciales (UUID) en URLs y API, para no revelar volumen ni permitir enumeración.
- Archivos (PDF, adjuntos) en almacenamiento separado por tenant, con la misma verificación de acceso que los datos.
- El personal de la plataforma no accede a datos clínicos de un tenant salvo soporte autorizado por el laboratorio, con tiempo limitado y auditado.
- Límites de uso por tenant, para que un laboratorio no degrade el servicio de los demás.

### Requisitos que esto impone a decisiones pendientes

- **Base de datos:** debe soportar seguridad a nivel de fila (p. ej. PostgreSQL).
- **Hosting:** debe permitir desplegar celdas en distintas regiones, con cifrado y BAA ([0003](0003-seguridad-hipaa.md)).

## Alternativas consideradas

- **Base de datos por tenant desde el inicio:** máximo aislamiento, pero multiplica migraciones, costos y operación con cada cliente nuevo. Queda como opción para casos puntuales.
- **Esquema por tenant:** aislamiento intermedio, pero las migraciones se vuelven lentas y frágiles con cientos de tenants.
- **Solo filtro en la aplicación, sin seguridad en el motor:** un único olvido en una consulta expone datos de otro laboratorio. Inaceptable con datos de salud.

## Consecuencias

- Toda tabla nueva con datos de laboratorio lleva `tenant_id` y su política de seguridad a nivel de fila.
- Las pruebas de cada funcionalidad incluyen un caso de aislamiento: un usuario del tenant A no puede leer, modificar ni inferir datos del tenant B.
- El registro de auditoría incluye el tenant.
- Hay que construir el módulo de alta de laboratorios y la resolución de tenant por subdominio antes que cualquier funcionalidad clínica.
