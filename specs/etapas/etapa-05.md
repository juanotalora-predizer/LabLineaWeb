# Informe de cierre — Etapa 5: Suscripciones, facturación manual y soporte

- **Fecha de cierre:** 2026-10-13 (pendiente de la CI)
- **Commit verificado:** pendiente
- **CI:** pendiente: se ejecuta al subir los cambios
- **Estado:** Abierta. Toda la compuerta local está en verde; falta que la CI pase después del push (criterio 1)

## Alcance entregado

Detalle en las secciones "Implementación (etapa 5)" de [funcional/0005](../funcional/0005-plataforma-saas-suscripciones.md) y [infraestructura/0005](../infraestructura/0005-arquitectura-saas-multitenant.md).

- **Migración `0006`:** tipos de licencia, suscripciones, precios, campañas, facturas y pagos en `plataforma`; impuesto por país en `global.paises`; `lab.accesos_soporte` y `lab.tickets_soporte`; usuario de tipo `SOPORTE` (nunca con contraseña) y rol `SOPORTE` de solo lectura.
- **Ciclo de la suscripción:**
  - La suscripción inicial depende de la licencia.
  - El estado efectivo vence en el instante exacto.
  - Desde el Admin Hub: suspender con motivo, reactivar, cancelar, renovación automática y cambio a licencia sin cobro.
  - El trabajador marca las vencidas, envía avisos de renovación 7 días y 1 día antes (una vez por umbral) y factura la renovación automática.
- **Bloqueo por suscripción:** la dependencia `SuscripcionVigente` (403 auditado) queda lista para las rutas que crean órdenes (etapa 8). El ingreso y la consulta siguen disponibles, con un aviso en todas las páginas del laboratorio.
- **Facturación:**
  - Precio por país, plan, licencia y moneda; campañas de descuento; impuesto del país.
  - Facturas inmutables, con pagos parciales y anulaciones con motivo.
  - Saldo y estado calculados por trigger; un pago nunca supera el saldo.
  - Al quedar pagada, la factura extiende la suscripción.
  - Pantallas: facturas con filtro por estado, detalle con pagos, precios y campañas.
- **Soporte:** autorización del laboratorio (1 a 72 horas, con motivo, revocable) → tiquete de un solo uso desde el Admin Hub → sesión de solo lectura en el laboratorio. Cada petición queda auditada y en cada una se verifica que la autorización siga vigente.
- **Personal de plataforma:** nuevo rol `SOPORTE_TECNICO`.

## Compuerta de calidad ([infraestructura/0011](../infraestructura/0011-calidad-pruebas-entorno-local.md))

| # | Criterio | Resultado | Evidencia |
|---|----------|-----------|-----------|
| 1 | Pruebas en verde (local y CI) | ⏳ local ✅, CI pendiente | 571 pruebas (136 nuevas) con `scripts/verificar.sh` |
| 2 | Cobertura ≥ 85% | ✅ | 99,0% de líneas y ramas |
| 3 | E2E de flujos nuevos | ✅ | Chromium: el laboratorio autoriza el soporte → el técnico entra desde el Admin Hub → ve la franja de solo lectura → el laboratorio revoca y la sesión termina. Pago completo de una factura desde el Admin Hub. Los 6 flujos anteriores siguen en verde |
| 4 | Migraciones upgrade/downgrade | ✅ | 0006 sube y baja en limpio, también con datos (usuarios de soporte, facturas y pagos) |
| 5 | Aislamiento | ✅ | Ver detalle abajo |
| 6 | Autorización | ✅ | Ver detalle abajo |
| 7 | Auditoría | ✅ | Suscripciones, precios, campañas, facturas y pagos auditados por trigger (guardián de la plataforma). Autorizaciones y tiquetes de soporte auditados en el laboratorio (hash del tiquete protegido). Cada petición del soporte queda registrada con método y ruta. Intentos de soporte sin autorización quedan en la auditoría de la plataforma. 403 por suscripción auditado |
| 8 | Sin datos de salud en logs, errores ni URLs | ✅ | Búsqueda automática de la corrida completa sin coincidencias; los fallos de las tareas periódicas solo registran el tipo de excepción (prueba); 0 errores 500 en los logs del servidor (ZAP y pruebas manuales). El motivo del soporte pide no incluir datos de pacientes |
| 9 | ruff / bandit / pip-audit / gitleaks | ✅ | Limpios |
| 10 | ZAP pasivo + activo autenticado | ✅ | **lab-a:** 0 altos · 0 medios · 0 bajos · 5 informativos. **Admin Hub:** 0 altos · 0 medios · 0 bajos · 6 informativos, 6416 peticiones autenticadas |
| 11 | Fuzzing sin errores 500 | ✅ | schemathesis en los dos hosts; fuzzing con CSRF válido de los 5 formularios nuevos (pago, precio, campaña, suscripción, autorización de soporte). **Encontró un error 500** (ver hallazgos) |
| 12 | Pruebas manuales dirigidas | ✅ | 12 de 12 (ver abajo) |
| 13 | Rendimiento | N/A | Sin endpoints críticos de operación |

### Aislamiento (criterio 5)

- **Soporte:**
  - El tiquete de un laboratorio no sirve en otro.
  - La sesión de soporte de un laboratorio no existe en otro.
  - Un laboratorio no puede revocar la autorización de otro (IDOR → 404).
  - El correo de un técnico que ya pertenece a una persona del laboratorio se rechaza, para no mezclar cuentas.
- **Avisos de renovación:** una tarea con el subdominio de otro laboratorio falla sin enviar nada.
- **Facturación:** un pago debe pertenecer a la factura de la URL (404 si no).

### Autorización (criterio 6)

- **Plataforma:**
  - Facturación: maestro y financiero sí; comercial 403.
  - Suscripciones: maestro, comercial y financiero sí; técnico 403.
  - Soporte: maestro y técnico sí; comercial y financiero 403.
- **Laboratorio:** autorizar soporte exige `AUTORIZAR_SOPORTE` (recepción y auditor 403).
- **Usuario de soporte:** solo consulta (invitar y autorizar soporte → 403).
- **Base de datos:** la plataforma no puede actualizar ni borrar facturas ni pagos (*permission denied*), ni cambiar los tipos de licencia.

## Pruebas con hypothesis (prueba específica del plan)

- Propiedades de los importes con decimales 0 y 2: subtotal, impuesto y total cuadran, y nada es negativo.
- Saldo con pagos parciales de cualquier tamaño: saldo = total − pagado, y el estado corresponde a lo pagado.
- Ningún pago supera el saldo.
- **La base y el modelo coinciden:** secuencias aleatorias de pagos (algunos superan el saldo) contra la base real dejan el mismo saldo y estado que el modelo en Python, y rechazan los mismos pagos.

## Pruebas manuales dirigidas

Script reproducible `scripts/pruebas_manuales/suscripciones_soporte.py`, contra el servidor HTTPS real, con SMTP de captura y el trabajador real.

| Prueba | Resultado |
|--------|-----------|
| Alta real de un laboratorio con licencia mensual y su primera factura; un pago mayor que el saldo → 400 | ✅ |
| Tres pagos simultáneos del saldo completo: uno aceptado y dos rechazados; la factura queda PAGADA | ✅ |
| SQL directo con el rol de la plataforma: actualizar facturas o borrar pagos → *permission denied* | ✅ (2) |
| Suscripción vencida: el administrador ingresa, consulta usuarios y ve el aviso | ✅ |
| El trabajador real envía el aviso de renovación (vence en 20 horas) a la administración del laboratorio | ✅ |
| Soporte sin autorización → 403 | ✅ |
| Tiquete: en otro laboratorio 404, en el suyo entra, reuso 404 | ✅ |
| Soporte en solo lectura: consulta 200, invitar 403; sus peticiones quedan en la auditoría del laboratorio | ✅ (2) |
| IDOR: otro laboratorio no revoca la autorización → 404 | ✅ |
| Revocar termina la sesión de soporte | ✅ |

## Hallazgos y resolución

| Hallazgo | Severidad | Detectado por | Resolución |
|----------|-----------|---------------|------------|
| **La CSP bloqueaba la entrada de soporte en el navegador:** el Admin Hub redirigía, desde un formulario, al subdominio del laboratorio, y `form-action 'self'` también se aplica a las redirecciones | Alta (funcional) | **E2E en Chromium** (TestClient no aplica la CSP) | El Admin Hub muestra un enlace al laboratorio en vez de redirigir; la CSP no se abrió a otros orígenes |
| **Error 500 con `"²"` en la duración del soporte:** `str.isdigit()` acepta dígitos Unicode que `int()` rechaza. El mismo patrón estaba en el máximo de usuarios del plan (etapa 4) | Media (disponibilidad) | **Fuzzing con CSRF válido** | Validación con dígitos ASCII (`[0-9]`) en los dos lugares; pruebas de regresión con `²`, `٣` y `１`; regla en `CLAUDE.md` |
| Un `?error=` arbitrario en el detalle del laboratorio habría armado una clave del catálogo inexistente (error 500) | Media | Revisión del código antes de las pruebas | Lista blanca de errores en la ruta; prueba con `?error=<script>` |
| El trigger que valida pagos bloquea la factura (`FOR UPDATE`), lo que exige `UPDATE` sobre ella, privilegio que la plataforma no tiene a propósito | Alta (funcional) | Pruebas | Trigger `SECURITY DEFINER` con `search_path` fijo; la plataforma sigue sin `UPDATE` |
| Pruebas que dependían de datos dejados por corridas anteriores (precios con la misma fecha, factura ya cubierta) o por otras pruebas (homónimo y usuario de soporte en lab-a) | Baja (pruebas) | Compuerta completa | Fechas únicas por corrida; laboratorios nuevos por prueba; limpieza del homónimo; las aserciones de dominios aceptan al soporte de la plataforma (es un usuario legítimo del laboratorio) |
| El escaneo activo del Admin Hub puede suspender o cancelar suscripciones de desarrollo | Baja (herramientas) | Revisión | `sembrar_desarrollo.py` restablece las suscripciones sintéticas y crea precios de ejemplo |
| Informativos ZAP (10029, 10058, 10015, 10112, 10104, 10031) | Informativo | ZAP | Los mismos de la etapa 4 y con la misma justificación (10031: `?aviso=plan` nunca se refleja) |

## Riesgos bajos documentados

- **Tiquete de soporte en la URL** (`/soporte/entrar/<tiquete>`): queda en el log de acceso.
  - **Mitigación:** un solo uso, 2 minutos, solo en su laboratorio, se consume con un POST con CSRF y se anula al revocar la autorización.
  - Va con el pendiente de la etapa 20 sobre el log del proxy.
- **IVA del 19 % configurado para Colombia:** pendiente de validar con el asesor tributario (backlog).

## Pendientes (fuera del alcance de la etapa)

- Usar `SuscripcionVigente` en las rutas que crean órdenes (etapa 8).
- Factura electrónica de la plataforma ante la DIAN (etapa 11).
- Pasarela de pagos (después del MVP).

## Riesgos aceptados por el usuario

Ninguno.
