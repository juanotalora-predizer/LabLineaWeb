# 0011. Calidad, pruebas y entorno local

- **Estado:** Aceptada
- **Fecha:** 2026-10-12
- **Responsable:** Juan Otálora

## Contexto

Se decidió construir y probar todo en local; la publicación (hosting) se decide después. Además, ninguna etapa del [plan](../plan-desarrollo.md) se da por terminada sin pruebas rigurosas de funcionamiento y de seguridad interna y externa. Esta spec define el entorno local, las herramientas y la **compuerta de calidad** que toda etapa debe pasar.

## Decisión

### 1. Entorno local

- **PostgreSQL 18 local** (instalado), con las bases `lablinea_dev` y `lablinea_test`. Para la bodega analítica se agrega `lablinea_dw` y se cambia `wal_level` a `logical` (lo hace el usuario con su superusuario, en la etapa de la bodega).
- **HTTPS local** con certificados de `mkcert` para `lab-a.lablinea.localhost`, `lab-b.lablinea.localhost` y `admin.lablinea.localhost`, servidos directamente por Uvicorn. Así se prueban en local las cookies `__Host-`, HSTS y la resolución de laboratorio por subdominio, igual que en producción.
- **Correo local:** servidor SMTP de captura (`aiosmtpd`) que guarda los mensajes para inspeccionarlos en las pruebas; nada sale a internet.
- **Servicios externos** (DIAN): solo sus ambientes de pruebas.
- Datos **exclusivamente sintéticos**.

### 2. Herramientas

| Tipo de prueba | Herramienta | Uso |
|---|---|---|
| Unitarias e integración | `pytest`, `pytest-cov` | Contra PostgreSQL real; cobertura medida |
| Basadas en propiedades | `hypothesis` | Máquinas de estado (orden, caja), cálculos (agrupación de tubos, rangos) |
| De punta a punta (E2E) | `playwright` | Flujos reales en el navegador, incluido htmx |
| Estilo y errores comunes | `ruff` | Lint y formato |
| Análisis estático de seguridad (SAST) | `bandit` | Código Python |
| Vulnerabilidades en dependencias | `pip-audit` | `requirements*.txt` |
| Secretos filtrados | `gitleaks` | Repositorio e historial |
| Seguridad externa (DAST) | OWASP ZAP | Escaneo pasivo y activo contra el servidor local en HTTPS, autenticado |
| Fuzzing de API y formularios | `schemathesis` | A partir del esquema OpenAPI de FastAPI |
| Carga | `locust` | Endpoints críticos (POS, caja, validación, dashboard) |
| Respaldo y restauración | `pg_dump` / `pg_restore` | Restauración verificada |

Las herramientas de Python van en `requirements-dev.txt`; ZAP, gitleaks y mkcert se instalan con Homebrew.

### 3. Compuerta de calidad (aplica a TODA etapa)

Una etapa solo se cierra cuando se cumple todo lo siguiente:

**Funcional**
1. Todas las pruebas pasan, localmente y en la CI.
2. Cobertura ≥ 85% del código de la etapa, y ninguna regla de negocio de las specs sin prueba.
3. Pruebas E2E de cada flujo de usuario nuevo (desde que exista interfaz).
4. Migraciones probadas en ambas direcciones (`upgrade` y `downgrade`).

**Seguridad interna**
5. Prueba de **aislamiento entre laboratorios** para cada tabla, endpoint y archivo nuevos, y el guardián de RLS en verde.
6. Pruebas de **autorización** por cada permiso y acción especial nuevos, incluyendo el caso negativo.
7. Pruebas de **auditoría**: cada escritura y lectura de datos de salud nueva deja rastro.
8. Prueba de que no aparecen datos de salud en logs, mensajes de error ni URLs.
9. `bandit` sin hallazgos de severidad media o alta; `ruff` limpio; `pip-audit` sin vulnerabilidades conocidas; `gitleaks` sin secretos.

**Seguridad externa**
10. Escaneo **ZAP** (pasivo + activo, autenticado) sobre las rutas nuevas en HTTPS local: **cero hallazgos altos o medios**; los bajos se documentan con su justificación.
11. Fuzzing con `schemathesis` de los endpoints nuevos sin errores 500.
12. Pruebas manuales dirigidas de la etapa: manipulación de identificadores (IDOR), cabecera `Host` falsificada, CSRF, inyección (SQL, HTML, ZPL, XML según aplique) y subida de archivos maliciosos.

**Rendimiento** (en etapas con endpoints críticos)
13. Locust: p95 ≤ 300 ms con 50 usuarios concurrentes en los endpoints críticos de la etapa, en la máquina local.

**Cierre**
14. **Informe de cierre de etapa** en `specs/etapas/` con la evidencia: número de pruebas, cobertura, resultados de cada herramienta, hallazgos y cómo se resolvieron.
15. Specs, backlog y daily actualizados.

Si una prueba falla, la etapa sigue abierta. Un hallazgo que no se pueda corregir en la etapa solo se acepta si el usuario lo aprueba explícitamente, y queda registrado en el informe con su plan de corrección.

### 4. Automatización

- `scripts/verificar.sh` ejecuta en orden: ruff, bandit, pip-audit, gitleaks, pytest con cobertura y el guardián de RLS. Se corre antes de cada commit.
- La CI ejecuta lo mismo en cada push.
- `scripts/escaneo_externo.sh` levanta el servidor en HTTPS local con datos sintéticos y corre ZAP y schemathesis; se ejecuta al cerrar cada etapa.

## Alternativas consideradas

- **Publicar staging desde el inicio:** detecta antes los problemas de infraestructura, pero obliga a decidir el hosting ahora.
- **Solo pruebas unitarias hasta el final y una auditoría de seguridad al cierre:** más rápido al principio, pero los fallos de aislamiento o autorización aparecerían cuando hay mucho código encima.

## Consecuencias

- Cada etapa toma más tiempo, a cambio de no acumular deuda de seguridad.
- La etapa de publicación (después de elegir hosting) agrega lo que no se puede probar en local: configuración TLS real, WAF, red, prueba de penetración por un tercero y restauración en la nube.
