# 0008. Autenticación y autorización

- **Estado:** Aceptada
- **Fecha:** 2026-10-12
- **Responsable:** Juan Otálora
- **Fuentes:** [07 Roles y usuarios](../fuentes/), [21 Plan de desarrollo](../fuentes/), [23 Roles SaaS](../fuentes/)

## Contexto

La spec [0003](0003-seguridad-hipaa.md) exige cuentas únicas, MFA, Argon2id, bloqueo y cierre de sesión por inactividad. Las fuentes proponen contraseña + código OTP en cada inicio de sesión y roles con permisos CRUD por módulo.

## Decisión

### 1. Autenticación

1. Correo y contraseña. Contraseñas con hash **Argon2id**.
2. **Segundo factor obligatorio en cada inicio de sesión, para todos los usuarios** (personal, administradores y pacientes), más estricto que [0003](0003-seguridad-hipaa.md):
   - **Personal y administradores:** app autenticadora (TOTP) como método principal; código por correo como respaldo.
   - **Pacientes y médicos externos:** código de 6 dígitos por correo, válido 5 minutos y de un solo uso (fuente 21).
   - SMS no se usa como único segundo factor: es vulnerable a la portabilidad fraudulenta de líneas.
3. Bloqueo temporal tras intentos fallidos de contraseña o de código; límite de envíos de código por hora.
4. Recuperación de contraseña por enlace de un solo uso con expiración corta.

### 2. Sesiones

- **Interfaz web (Jinja2):** sesión en el servidor con cookie `Secure`, `HttpOnly`, `SameSite=Lax`. Se usa cookie y no JWT porque la aplicación se renderiza en el servidor, y una cookie `HttpOnly` no la puede leer un script malicioso.
- Expira tras **15 minutos de inactividad** y con duración máxima absoluta; se invalida al cerrar sesión o cambiar la contraseña.
- La sesión pertenece a un tenant; no es válida en otro subdominio ([0005](0005-arquitectura-saas-multitenant.md)).
- **API para sistemas externos (FHIR):** tokens OAuth 2.0 / SMART on FHIR ([0002](0002-interoperabilidad-hl7-fhir.md)), fuera del MVP.

### 3. Autorización

- **Roles por laboratorio** (p. ej. administrador, recepcionista o cajero, flebotomista, bacteriólogo, validador, auditor), configurables por cada laboratorio.
- **Permisos por módulo** de consultar, crear, modificar y eliminar (fuente 07), **más acciones especiales** que no son CRUD y requieren permiso explícito:
  - pre-cerrar y anular órdenes;
  - autorizar descuentos sobre el tope;
  - abrir y cerrar caja;
  - validar resultados y registrar valores críticos;
  - liberar resultados con excepción;
  - autorizar acceso de soporte de la plataforma.
- **Validar resultados** exige además que el usuario tenga registrada su tarjeta profesional.
- **Pacientes:** ven solo sus propias órdenes y resultados liberados. **Médicos remitentes:** solo los de los pacientes que remitieron.
- **Roles de plataforma** separados ([funcional/0005](../funcional/0005-plataforma-saas-suscripciones.md)).
- Todo permiso se verifica en el servidor, en cada petición, además del filtro por tenant.

## Alternativas consideradas

- **JWT en el navegador (fuentes):** pensado para un frontend React; con renderizado en servidor añade riesgo (robo del token por XSS) sin beneficio.
- **OTP solo por correo para todos:** más simple, pero si se compromete el correo del personal se compromete el acceso a datos de muchos pacientes.
- **Proveedor externo de identidad:** reduce desarrollo, pero debe firmar BAA y soportar tenants por laboratorio; se puede reevaluar.

## Consecuencias

- Se necesita un servicio de envío de correo con BAA para los códigos y avisos ([0003](0003-seguridad-hipaa.md)).
- Todos los inicios de sesión, fallos, bloqueos y cambios de permisos quedan en la auditoría.
- Cada acción especial tiene su prueba de autorización.
