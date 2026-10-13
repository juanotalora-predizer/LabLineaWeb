# Informe de cierre — Etapa 0: Herramientas, base de datos y CI

- **Fecha de cierre:** 2026-10-12
- **Commit verificado:** `bd9c2c6`
- **CI:** ejecución [38337219567](https://github.com/juanotalora-predizer/LabLineaWeb/actions/runs/38337219567), exitosa
- **Estado:** Cerrada

## Alcance entregado

- Configuración desde `.env` (`app/core/config.py`) con entorno y dominio base; secretos como `SecretStr`.
- Acceso a datos con tenant por transacción (`app/core/db.py`, `SET LOCAL` vía `set_config`).
- Alembic asíncrono con la migración `0001`: esquemas `plataforma`, `global`, `lab`; función `lab.tenant_actual()`; permisos por defecto del rol de la aplicación.
- Cabeceras de seguridad en toda respuesta (`app/core/seguridad.py`): CSP sin `unsafe-inline`, HSTS sobre HTTPS, `no-store` en respuestas dinámicas, `X-Frame-Options`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, COOP/CORP.
- Validación de la cabecera `Host` (`TrustedHostMiddleware`): solo `lablinea.localhost` y sus subdominios.
- Sin `/docs` ni `/redoc`; `/openapi.json` oculto en producción.
- Herramientas: `pyproject.toml` (ruff, bandit, cobertura, pytest), `scripts/verificar.sh`, `scripts/servidor_https.sh`, `scripts/escaneo_externo.sh` con plan de ZAP, `.gitleaks.toml`.
- HTTPS local con certificados de mkcert para `lab-a`, `lab-b` y `admin.lablinea.localhost`, solo en loopback.
- CI: misma compuerta en GitHub Actions con PostgreSQL 18 y gitleaks verificado por checksum.

## Compuerta de calidad ([infraestructura/0011](../infraestructura/0011-calidad-pruebas-entorno-local.md))

| # | Criterio | Resultado | Evidencia |
|---|----------|-----------|-----------|
| 1 | Pruebas en verde (local y CI) | ✅ | 45 pruebas, local y CI (ejecución 38337219567) |
| 2 | Cobertura ≥ 85% | ✅ | 100% de líneas y ramas de `app/` |
| 3 | E2E de flujos nuevos | N/A | La etapa no tiene flujos de usuario; Playwright entra con la primera interfaz (etapa 2) |
| 4 | Migraciones upgrade/downgrade | ✅ | `verificar.sh` baja a `base` y sube a `head` en cada ejecución, local y CI |
| 5 | Aislamiento entre laboratorios | ✅ | Guardián de RLS (`test_toda_tabla_de_lab_cumple_rls`) verificado a mano: falla sin RLS y sin `FORCE`. El tenant no se filtra entre peticiones que reutilizan conexión. Aún no hay tablas de laboratorio |
| 6 | Autorización | N/A | Sin autenticación todavía (etapa 2). Verificado: el rol de la aplicación no es superusuario, no tiene `BYPASSRLS`, no es dueño de los esquemas y no accede a `plataforma` |
| 7 | Auditoría | N/A | Sin datos de salud todavía (etapa 3) |
| 8 | Sin datos sensibles en logs, errores ni URLs | ✅ | Las contraseñas no aparecen en `repr`, `str` ni logs; las respuestas 405 no exponen trazas |
| 9 | ruff / bandit / pip-audit / gitleaks | ✅ | ruff limpio; bandit sin hallazgos; pip-audit: 0 vulnerabilidades; gitleaks: 0 secretos en historial (4 commits) y árbol de trabajo |
| 10 | ZAP pasivo + activo | ✅ | Altos: 0 · Medios: 0 · Bajos: 0 · Informativos: 2 (ver abajo). 364 peticiones de ataque, cero respuestas 5xx |
| 11 | schemathesis sin errores 500 | ✅ | Todos los endpoints del esquema, con validación de respuestas y cabeceras |
| 12 | Pruebas manuales dirigidas | ✅ | Ver "Pruebas específicas"; 1 hallazgo, corregido |
| 13 | Rendimiento | N/A | Sin endpoints críticos todavía |

## Pruebas específicas de la etapa

| Prueba | Resultado |
|--------|-----------|
| gitleaks sobre todo el historial: el `.env` nunca se subió | ✅ Sin hallazgos |
| gitleaks detecta un secreto puesto en otro archivo (la excepción del `.env` es estrecha) | ✅ Detectado |
| La aplicación no arranca sin contraseñas ni con un entorno inválido | ✅ |
| Cabecera `Host` falsificada (`atacante.example`, dominios parecidos, IP, vacía) | ✅ 400 (antes: aceptada y reflejada; ver hallazgo) |
| `X-Forwarded-Host` inyectada | ✅ Ignorada |
| Path traversal en `/static` (`../`, `%2e%2e`, `..%2f`) | ✅ 404 |
| Métodos TRACE y OPTIONS | ✅ 405 |
| TLS 1.0 y 1.1 | ✅ Rechazados |
| El servidor HTTPS escucha solo en 127.0.0.1 y no envía cabecera `server` | ✅ |
| `/docs`, `/redoc` | ✅ 404; `/openapi.json` 404 en producción |

## Hallazgos y resolución

| Hallazgo | Severidad | Herramienta | Resolución |
|----------|-----------|-------------|------------|
| La aplicación aceptaba cualquier cabecera `Host` y la reflejaba en redirecciones (`location: https://atacante.example/static/`). Riesgo de envenenamiento de caché y de enlaces en correos futuros | Media | Prueba manual (ZAP no lo detectó) | `TrustedHostMiddleware` con `dominio_base`; 11 pruebas de regresión; reverificado a mano y con ZAP |
| Swagger UI cargaba scripts desde un CDN externo y exponía la documentación | Baja | Revisión de la CSP | `/docs` y `/redoc` desactivados; OpenAPI oculto en producción |
| Contraseña ficticia de una prueba detectada por gitleaks | Falso positivo | gitleaks | Marcada con `gitleaks:allow` solo en esa línea |
| Informativo ZAP 10015 "Re-examine Cache-control Directives" en `/openapi.json` y `/` | Informativo | ZAP | Aceptable: la respuesta ya lleva `no-store`, que impide toda caché |
| Informativo ZAP 10104 "User Agent Fuzzer" | Informativo | ZAP | Aceptable: solo informa que se probaron agentes de usuario; mismas respuestas |

## Notas del entorno

- El cask de ZAP en Homebrew está deshabilitado (Gatekeeper); se usa la distribución multiplataforma oficial 2.17.0, con SHA-256 verificado contra el release, sobre OpenJDK 21.
- macOS resuelve `*.localhost` sin tocar `/etc/hosts`.
- Para que el navegador confíe en los certificados locales, el usuario puede ejecutar `mkcert -install` una vez (pide contraseña de administrador). No es necesario para las pruebas automáticas.

## Riesgos aceptados por el usuario

Ninguno.
