# Informe de cierre — Etapa 4: Alta de laboratorios y planes (Admin Hub)

- **Fecha de cierre:** 2026-10-13 (pendiente de la CI)
- **Commit verificado:** pendiente
- **CI:** pendiente: se ejecuta al subir los cambios
- **Estado:** Abierta. Toda la compuerta local está en verde; falta que la CI pase después del push (criterio 1)

## Alcance entregado

Detalle en las secciones "Implementación (etapa 4)" de [funcional/0005](../funcional/0005-plataforma-saas-suscripciones.md), [infraestructura/0005](../infraestructura/0005-arquitectura-saas-multitenant.md), [0007](../infraestructura/0007-base-de-datos.md) y [0008](../infraestructura/0008-autenticacion-autorizacion.md).

- **Migración `0005`:**
  - En `plataforma`: usuarios, roles, permisos, sesiones, códigos, límites, eventos y auditoría propios; planes y módulos por plan.
  - En `lab`: sedes e invitaciones; `tenant_id` por defecto; contraseña opcional.
  - Funciones `plataforma.alta_laboratorio` e `invitar_administrador`.
  - El resolvedor del laboratorio entrega los módulos efectivos y el límite de usuarios.
- **Admin Hub** en `admin.<dominio>`:
  - Ingreso con TOTP obligatorio.
  - Tres roles de plataforma.
  - Laboratorios: lista, alta, detalle, cambio de plan y reenvío de invitación.
  - Planes: lista, creación y edición de módulos y máximo de usuarios.
  - Lista del personal de la plataforma.
  - Script para crear personal de la plataforma (`scripts/crear_usuario_plataforma.py`).
- **Separación de sitios:** cada ruta declara su sitio (laboratorio, Admin Hub o ambos) y un guardián lo exige. El código de autenticación es uno solo para los dos sitios; el `search_path` de cada transacción decide el esquema.
- **Alta atómica:** laboratorio, sede, roles del sistema y administrador sin contraseña en una transacción, más la tarea de invitación.
- **Invitaciones:**
  - Primera tarea real de la cola: enlace de un solo uso (72 horas) solo válido en su laboratorio.
  - El administrador crea su contraseña, ingresa con código por correo e inscribe su TOTP.
  - Nadie de la plataforma conoce su contraseña.
- **Usuarios del laboratorio:**
  - Invitar personal y médicos con roles, respetando el máximo del plan.
  - Desactivar, lo que revoca las sesiones.
- **Planes en el laboratorio:** los módulos fuera del plan no otorgan permisos (403) y desaparecen del menú. Usuarios y configuración están siempre activos.

## Compuerta de calidad ([infraestructura/0011](../infraestructura/0011-calidad-pruebas-entorno-local.md))

| # | Criterio | Resultado | Evidencia |
|---|----------|-----------|-----------|
| 1 | Pruebas en verde (local y CI) | ⏳ local ✅, CI pendiente | 435 pruebas (129 nuevas) con `scripts/verificar.sh` |
| 2 | Cobertura ≥ 85% | ✅ | 99,5% de líneas y ramas |
| 3 | E2E de flujos nuevos | ✅ | Chromium, servidor HTTPS real: ingreso al Admin Hub con TOTP → alta del laboratorio → invitación (trabajador) → activación en el nuevo subdominio → ingreso con código por correo → inscripción de TOTP → lista de usuarios solo del laboratorio. Los 5 flujos anteriores siguen en verde |
| 4 | Migraciones upgrade/downgrade | ✅ | 0005 sube y baja en limpio, también con datos (usuarios invitados sin contraseña) |
| 5 | Aislamiento entre laboratorios y entre sitios | ✅ | Ver detalle abajo |
| 6 | Autorización | ✅ | Matriz de 10 casos de los roles de plataforma (positivos y negativos); invitar y desactivar usuarios con y sin permiso; módulo fuera del plan → 403 (dependencia y página real); nadie se desactiva a sí mismo |
| 7 | Auditoría | ✅ | Guardián de tablas auditadas también para `plataforma`; secretos protegidos; lecturas y 403 de la plataforma auditados; la auditoría del laboratorio registra al usuario de plataforma que lo creó; `lab.invitaciones` auditada con el hash protegido |
| 8 | Sin datos de salud en logs, errores ni URLs | ✅ | Búsqueda automática de la corrida completa sin coincidencias; 0 errores 500 en los logs del servidor durante ZAP y las pruebas manuales. El token de invitación sí aparece en la URL (ver riesgos bajos) |
| 9 | ruff / bandit / pip-audit / gitleaks | ✅ | Limpios |
| 10 | ZAP pasivo + activo autenticado | ✅ | **lab-a:** 0 altos · 0 medios · 0 bajos · 5 informativos, 306 peticiones autenticadas. **Admin Hub:** 0 altos · 0 medios · 0 bajos · 6 informativos, 2544 peticiones autenticadas |
| 11 | Fuzzing sin errores 500 | ✅ | schemathesis sobre los dos hosts (laboratorio y Admin Hub); fuzzing con CSRF válido de los 4 formularios nuevos (alta, plan, invitación, activación) |
| 12 | Pruebas manuales dirigidas | ✅ | 14 de 14 (ver abajo) |
| 13 | Rendimiento | N/A | Sin endpoints críticos de operación (el alta es ocasional) |

### Aislamiento (criterio 5)

- **Esquemas:**
  - El rol de la plataforma no lee `lab.usuarios` ni `lab.auditoria` (SQL directo, en pruebas y contra la base de desarrollo).
  - La única escritura en `lab` es `alta_laboratorio`, que solo crea un laboratorio nuevo.
- **Sesiones y credenciales:**
  - La cookie de sesión de un sitio no sirve en el otro, ni en pruebas ni con el servidor real.
  - Las credenciales de la plataforma no sirven en un laboratorio, ni al revés.
- **Rutas:**
  - Las rutas del Admin Hub en un laboratorio responden 404, también con `X-Forwarded-Host`, y al revés.
  - Un guardián exige que cada ruta declare su sitio.
- **Invitaciones:**
  - El enlace de lab-a no sirve en lab-b.
  - Una tarea de invitación con el subdominio de otro laboratorio falla sin enviar nada.
- **Identificadores (IDOR):** desactivar desde lab-a un usuario de lab-b responde 404 y el usuario sigue activo.
- **Laboratorio nuevo:** su administrador solo ve sus usuarios (E2E).

## Pruebas manuales dirigidas

Script reproducible `scripts/pruebas_manuales/admin_hub.py`, contra el servidor HTTPS real, con SMTP de captura y el trabajador real (`trabajador.py`).

| Prueba | Resultado |
|--------|-----------|
| La cookie del Admin Hub no sirve en lab-a, y la de lab-a no sirve en el Admin Hub | ✅ (2) |
| Credenciales de un sitio rechazadas en el otro | ✅ (2) |
| Rutas del Admin Hub pedidas en lab-a, también con `X-Forwarded-Host` → 404; `Host` ajeno → 400 | ✅ (2) |
| Alta desde otro origen (CSRF) → 403 | ✅ |
| Inyección SQL en el subdominio y el plan, y `<script>` en el nombre → 400, sin error interno ni reflejo | ✅ |
| IDOR: desactivar un usuario de lab-b desde lab-a → 404 | ✅ |
| Rol de plataforma con SQL directo sobre `lab` y sobre su auditoría → *permission denied* | ✅ (3) |
| Alta real → invitación enviada por el trabajador → activación → reuso del enlace 404 → ingreso en el nuevo subdominio | ✅ |
| El correo de invitación solo lleva el enlace | ✅ |

## Hallazgos y resolución

| Hallazgo | Severidad | Detectado por | Resolución |
|----------|-----------|---------------|------------|
| El downgrade de 0005 fallaba con usuarios invitados sin contraseña (la columna vuelve a ser obligatoria) | Media (reversibilidad) | `verificar.sh` (baja todo con datos) | El downgrade asigna a esos usuarios un hash que no corresponde a ninguna clave: siguen sin poder ingresar |
| Una violación de CHECK (subdominio reservado como `admin`) se mostraba como "ya existe" | Baja | Pruebas | Se distingue la unicidad (código 23505) del resto de rechazos de la base |
| Segundo ingreso del mismo usuario en una ventana de 30 s rechazado por la protección anti-repetición de TOTP (comportamiento correcto) | — | Pruebas | El ayudante de pruebas usa el código del intervalo siguiente; el servidor no cambia |
| El escaneo activo de ZAP desactivó usuarios sintéticos y cambió planes (tenía sesión y CSRF válido, como un usuario real) y la siembra posterior fallaba | Baja (herramientas) | Escaneo externo | `sembrar_desarrollo.py` reactiva los usuarios sintéticos y devuelve los laboratorios al plan completo |
| La prueba del enlace de invitación dependía del `.env` local (puerto) | Baja | `verificar.sh` | Se compara con `url_sitio()`; prueba aparte de la construcción del enlace |
| Informativo ZAP 10058 "GET for POST" | Informativo | ZAP | ZAP repite los POST como GET: ningún GET cambia estado (404/405 o el formulario vacío) |
| Informativo ZAP 10031 "User Controllable HTML Element Attribute" en `?aviso=plan` | Falso positivo | ZAP | El parámetro nunca se refleja: solo se compara con valores fijos. La coincidencia es con `/plan` del atributo `action` |
| Informativos ZAP 10029, 10015, 10112, 10104 | Informativo | ZAP | Los mismos de la etapa 2 |

## Riesgos bajos documentados

- **Token de invitación en la URL** (`/activar/<token>`): queda en el log de acceso del servidor y en el historial del navegador.
  - **Mitigación:** un solo uso, 72 horas, solo en su laboratorio, se anula con una invitación nueva, `Referrer-Policy: same-origin` y la página no carga recursos externos.
  - **Etapa 20:** el log de acceso del proxy no debe guardar la ruta completa de `/activar/`.
- **El trabajador usa el rol de la aplicación** (ver [0012](../infraestructura/0012-cola-de-tareas.md)); sin cambios.

## Pendientes (fuera del alcance de la etapa)

- Etapa 5: tipos de licencia, suscripciones con vencimiento y suspensión, facturas con pagos manuales y acceso de soporte autorizado.
- Recuperación de contraseña (reutilizará las invitaciones), código QR del TOTP, roles propios del laboratorio, edición y desactivación del personal de la plataforma desde la interfaz.

## Riesgos aceptados por el usuario

Ninguno.
