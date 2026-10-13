# Informe de cierre — Etapa 2: Autenticación y autorización

- **Fecha de cierre:** 2026-10-12
- **Commit verificado:** `967f0cb`
- **CI:** ejecución [38341449632](https://github.com/juanotalora-predizer/LabLineaWeb/actions/runs/38341449632), exitosa (incluye las pruebas en Chromium)
- **Estado:** Cerrada

## Alcance entregado

Detalle técnico en [infraestructura/0008, "Implementación"](../infraestructura/0008-autenticacion-autorizacion.md).

- **Migración `0003`:** `global.modulos` y `global.acciones`; en `lab`, con RLS forzado: `usuarios`, `roles`, `usuario_roles`, `rol_permisos`, `rol_acciones`, `sesiones`, `codigos_verificacion`, `limites` y `eventos_seguridad` (solo inserción).
- **Ingreso en dos pasos:** contraseña con Argon2id, y luego TOTP (personal) o código por correo (pacientes y médicos; respaldo del personal).
  - El personal sin app autenticadora debe inscribirla antes de continuar.
  - El secreto TOTP se guarda cifrado con AES-256-GCM, ligado al laboratorio y al usuario.
- **Sesiones:**
  - Cookie `__Host-sesion`; en la base solo se guarda su hash SHA-256.
  - El token se renueva al completar el ingreso, para impedir la fijación de sesión.
  - Vence a los 15 minutos de inactividad y a las 12 horas como máximo.
  - Salir la revoca en el servidor.
- **CSRF:** doble envío con cookie `__Host-csrf`, más verificación de `Origin` y `Sec-Fetch-Site`, con una prueba que impide crear rutas POST sin esa protección.
- **Límites:**
  - 5 fallos por correo bloquean el acceso 15 minutos, con el mismo mensaje exista o no la cuenta.
  - 100 intentos por IP; 5 de segundo factor; 5 códigos por hora.
  - El tiempo de respuesta es igual para correos existentes e inexistentes.
- **Autorización:** 6 roles del sistema, permisos CRUD por módulo y acciones especiales. Validar resultados exige además tarjeta profesional.
- **Páginas:** ingreso, verificación, inscripción de TOTP, panel y lista de usuarios (requiere permiso `usuarios.consultar`).
- **Correo:** envío por SMTP sin datos clínicos. Si el servidor de correo falla, el usuario ve un mensaje y no un error 500.
- **Herramientas:**
  - Datos de desarrollo con usuarios sintéticos y TOTP.
  - ZAP escanea con sesión autenticada (`ZAP_AUTH_HEADER*`).
  - Pruebas manuales reproducibles en `scripts/pruebas_manuales/autenticacion.py`.

## Compuerta de calidad ([infraestructura/0011](../infraestructura/0011-calidad-pruebas-entorno-local.md))

| # | Criterio | Resultado | Evidencia |
|---|----------|-----------|-----------|
| 1 | Pruebas en verde (local y CI) | ✅ | 226 pruebas (104 nuevas), local y CI |
| 2 | Cobertura ≥ 85% | ✅ | 99,1% de líneas y ramas |
| 3 | E2E de flujos nuevos | ✅ | 5 flujos en Chromium contra el servidor HTTPS real con SMTP local: paciente con código por correo y salida; personal con TOTP y lista de usuarios; cookies seguras y aisladas por laboratorio; mensaje genérico; sin errores de CSP |
| 4 | Migraciones upgrade/downgrade | ✅ | 0003 sube y baja en local y CI |
| 5 | Aislamiento entre laboratorios | ✅ | La sesión de un laboratorio se rechaza en otro (TestClient, navegador y servidor real); mismo correo en dos laboratorios = cuentas distintas; RLS impide insertar usuarios en otro laboratorio; la lista de usuarios solo muestra el propio; concurrencia: 600 peticiones sin cruces |
| 6 | Autorización | ✅ | Permisos cargados = definición de cada rol (5 roles); lista de usuarios por rol (5 casos); acciones especiales y tarjeta profesional; operaciones CRUD por módulo; menú según permisos |
| 7 | Auditoría | ✅ (parcial, por diseño) | Eventos de seguridad (ingresos, fallos, bloqueos, salidas, inscripción TOTP) en tabla de solo inserción; ni la aplicación ni el dueño pueden modificarlos. La auditoría general de datos llega en la etapa 3 |
| 8 | Sin datos sensibles en logs, errores ni URLs | ✅ | Los errores de validación no repiten la entrada (contraseñas); el log de fallo de correo no lleva el correo ni el código; el correo no lleva datos clínicos; los límites guardan HMAC, no correos ni IP |
| 9 | ruff / bandit / pip-audit / gitleaks | ✅ | Limpios (bandit obligó a reescribir dos consultas con SQL literal) |
| 10 | ZAP pasivo + activo autenticado | ✅ | Altos 0 · Medios 0 · Bajos 0 · Informativos 4. 58 peticiones autenticadas a páginas protegidas, todas con 200; la sesión siguió válida al final |
| 11 | Fuzzing sin errores 500 | ✅ | schemathesis en todos los endpoints, más **fuzzing con token CSRF válido**: `hypothesis` con 60 casos por formulario (ingreso, verificación, inscripción TOTP, campos inesperados) |
| 12 | Pruebas manuales dirigidas | ✅ | 11 de 11 (ver abajo) |
| 13 | Rendimiento | N/A | Sin endpoints críticos de operación. Referencia: mediana de 28 ms por intento de ingreso (Argon2 incluido) |

## Pruebas manuales dirigidas (servidor HTTPS real)

| Prueba | Resultado |
|--------|-----------|
| 5 fallos bloquean la cuenta; luego la contraseña correcta también se rechaza, con el mismo mensaje | ✅ |
| Enumeración por tiempo: 28 ms (existe) frente a 29 ms (no existe) | ✅ |
| El correo del código no lleva datos clínicos | ✅ |
| Cookie de sesión real: `Secure`, `HttpOnly`, `SameSite=Lax`, `Path=/`, sin `Domain` | ✅ |
| El token rota al completar el ingreso | ✅ |
| Páginas autenticadas con `no-store` y `X-Frame-Options: DENY` | ✅ |
| Cerrar sesión desde otro origen (CSRF) rechazado y la sesión sigue | ✅ |
| Sesión de lab-a rechazada en lab-b | ✅ |
| Una cookie copiada deja de servir tras salir | ✅ |
| Un código TOTP no se puede reutilizar | ✅ |
| Concurrencia entre laboratorios (600 peticiones) | ✅ 0 cruces |

## Hallazgos y resolución

| Hallazgo | Severidad | Detectado por | Resolución |
|----------|-----------|---------------|------------|
| Un formulario con el carácter nulo (`\x00`) provocaba un error 500: PostgreSQL no admite ese carácter en texto | Media (disponibilidad, información de errores) | **Fuzzing con CSRF válido** (ZAP y schemathesis no pasaban el CSRF) | `TextoSeguro` rechaza caracteres de control en los formularios → 400 genérico. Prueba de regresión |
| `Referrer-Policy: no-referrer` (etapa 0) hace que el navegador envíe `Origin: null` en los POST: **todos los formularios quedaban bloqueados** por la verificación CSRF | Alta (funcional) | **Pruebas E2E en Chromium** (TestClient no reproduce al navegador) | `Referrer-Policy: same-origin` (no envía nada a otros sitios). Spec 0003 actualizada |
| Si el servidor de correo fallaba, el envío del código daba un error 500 | Baja | Revisión de casos de ataque | Mensaje al usuario y 503; el log no expone el correo. Prueba |
| El manejador de validación de FastAPI repetía la entrada en el error (incluidas contraseñas demasiado largas) | Media (exposición) | Revisión | Respuesta genérica "Solicitud inválida". Prueba |
| La IP de las pruebas ("testclient") rompía la columna `inet` | Robustez | Pruebas | `ip_cliente` valida la dirección antes de guardarla |
| Primer escaneo de ZAP no autenticado en la práctica: su regla de reemplazo no inyectaba la cookie (solo 2 de 20 visitas a `/panel` con sesión) | Calidad del escaneo | Revisión del registro del servidor | Se usa el mecanismo `ZAP_AUTH_HEADER*`; el script ahora **falla** si el escaneo no se mantiene autenticado |
| Bandit: consultas armadas con f-string (constantes) | Baja | bandit | SQL literal completo |
| Informativo ZAP 10029 "Cookie Poisoning" en `POST /ingresar`, parámetro `csrf` | Falso positivo | ZAP | Es el CSRF de doble envío: el campo y la cookie coinciden a propósito. La cookie se genera solo en el servidor y nunca se toma del formulario |
| Informativos ZAP 10112, 10015, 10104 | Informativo | ZAP | Identifican la cookie de sesión, `no-store` y pruebas de agente de usuario; aceptables |

## Pendientes (fuera del alcance de la etapa)

- Recuperación de contraseña por enlace de un solo uso.
- Código QR para inscribir el TOTP (hoy se muestra la clave en texto).
- Administración de usuarios y roles desde la interfaz (junto con el alta de laboratorios, etapa 4).
- Transporte cifrado del correo e IP real detrás del proxy (etapa 20).

## Riesgos aceptados por el usuario

Ninguno.
