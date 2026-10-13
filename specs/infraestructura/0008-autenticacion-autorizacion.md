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

## Implementación (etapa 2, 2026-10-12)

Detalles fijados al construir; ver [informe de la etapa 2](../etapas/etapa-02.md).

- **Dependencias:** `argon2-cffi` (Argon2id, perfil RFC 9106 de baja memoria), `pyotp` (TOTP), `cryptography` (AES-256-GCM para el secreto TOTP, ligado al laboratorio y al usuario; subclaves por HKDF desde `CLAVE_CIFRADO`).
- **Sesiones:** en `lab.sesiones` solo se guarda el SHA-256 del token. Una sesión pendiente (contraseña correcta, segundo factor por completar) dura 5 minutos; al completar el ingreso se emite un token nuevo y el anterior se revoca (fijación de sesión). Duración máxima: 12 horas.
- **Cookies:** `__Host-sesion` (`SameSite=Lax`) y `__Host-csrf` (`SameSite=Strict`), ambas `Secure` y `HttpOnly`, sin `Domain`.
- **CSRF:** doble envío (campo `csrf` igual a la cookie `__Host-csrf`), más verificación de `Origin` y `Sec-Fetch-Site`. Una prueba falla si alguna ruta POST/PUT/PATCH/DELETE no exige CSRF.
- **Límites:** 5 fallos por correo en 15 minutos bloquean el acceso con el mismo mensaje genérico, exista o no la cuenta. 100 intentos por IP en 15 minutos, porque todo el personal de un laboratorio suele compartir IP. 5 intentos de segundo factor y 5 códigos por correo por hora. Las claves de límites guardan un HMAC, no el correo ni la IP.
- **Enumeración:** si el correo no existe se calcula igual un Argon2, y todos los fallos dan el mismo mensaje y estado.
- **Códigos por correo:** 6 dígitos, 5 minutos, un solo uso, guardados como HMAC. El personal con TOTP puede pedir uno como respaldo.
- **Entradas:** los campos de formulario rechazan caracteres de control (`TextoSeguro`), y los errores de validación responden un 400 genérico sin repetir la entrada.
- **Eventos de seguridad:** `lab.eventos_seguridad`, solo inserción (permisos más trigger).
- **Roles del sistema:** ADMINISTRADOR, RECEPCION, FLEBOTOMIA, BACTERIOLOGO, VALIDADOR, AUDITOR (`app/auth/roles_sistema.py`). El administrador no tiene acciones clínicas (validar resultados, valores críticos).

**Pendiente:** recuperación de contraseña por enlace, código QR para inscribir el TOTP, administración de usuarios y roles desde la interfaz (con el alta de laboratorios, etapa 4), y transporte cifrado del correo e IP real detrás del proxy (etapa 20).

## Implementación (etapa 4, 2026-10-13)

- **Dos sitios, un mismo mecanismo:** el personal de la plataforma ingresa en el Admin Hub con el mismo código (Argon2id, TOTP obligatorio, sesiones `__Host-`, CSRF, límites). Sus datos viven en `plataforma` (tablas gemelas, sin `tenant_id`). Los secretos TOTP se ligan al ámbito (`plataforma` o el laboratorio) y al usuario.
- **Invitaciones** (`app/auth/invitaciones.py`):
  - El usuario se crea sin contraseña.
  - La tarea `auth.invitacion` genera un token de 32 bytes, guarda su SHA-256 (`lab.invitaciones`, 72 horas, una invitación nueva anula las anteriores) y envía el enlace `https://<subdominio>/activar/<token>`.
  - El enlace solo funciona en su laboratorio y una sola vez. Activar exige la política de contraseñas y confirmación.
  - Luego el usuario ingresa con su contraseña y su segundo factor (y el personal inscribe su app).
- **Usuarios del laboratorio** (`/configuracion/usuarios`):
  - Invitar exige `usuarios.crear`; acepta personal y médicos, con roles del laboratorio, hasta el máximo del plan.
  - Desactivar exige `usuarios.modificar` y revoca las sesiones; nadie puede desactivarse a sí mismo.
- **Mensajes de la política de contraseñas** externalizados en el catálogo de textos.

**Pendiente:** recuperación de contraseña por enlace (reutilizará las invitaciones), código QR del TOTP, edición de roles propios del laboratorio.
