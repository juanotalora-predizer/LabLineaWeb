# Informe de cierre — Etapa 1: Base multi-tenant

- **Fecha de cierre:** 2026-10-12
- **Commit verificado:** `a676cea`
- **CI:** ejecución [38338577115](https://github.com/juanotalora-predizer/LabLineaWeb/actions/runs/38338577115), exitosa
- **Estado:** Cerrada

## Alcance entregado

- **Rol `lablinea_plataforma`** (Admin Hub) en `scripts/crear_bd_local.sql` y en la CI: solo el esquema `plataforma` y lectura de `global`; sin acceso a `lab` ni `DELETE`.
- **Migración `0002`:**
  - `global.monedas` (COP, USD), `global.paises` (Colombia, único habilitado: `America/Bogota`, `es-CO`, COP) y `global.tipos_documento` (13 de persona + NIT).
  - `plataforma.laboratorios`: `tenant_id` y subdominio validados con expresiones regulares, subdominios reservados bloqueados, NIT único por país, estados `ACTIVO`/`SUSPENDIDO`/`CANCELADO`, trigger que impide registrar laboratorios en países no habilitados.
  - `acceso.resolver_laboratorio(subdominio)`: `SECURITY DEFINER` con `search_path` fijo; única ventana del rol de la aplicación hacia la plataforma; devuelve solo los datos necesarios (sin NIT); excluye cancelados.
- **Resolución de laboratorio** (`app/core/tenancy.py`):
  - El laboratorio se toma solo del subdominio, y el subdominio se valida como etiqueta DNS antes de consultar la base.
  - `admin` y el dominio base quedan sin laboratorio.
  - Inexistente, cancelado o inválido devuelven el mismo 404.
  - `/static` y `/health` no consultan la base.
- **Orden de middlewares:** cabeceras de seguridad (envuelven también los 400 y 404) → host confiable → resolución de laboratorio.
- **Configuración por país:** moneda, zona horaria, idioma y tipos de documento. Los textos legales quedan para la etapa 7 (pacientes y Ley 1581).
- **Pruebas en la base de prueba:** `ENTORNO=pruebas` hace que la aplicación use `lablinea_test`, sin pool de conexiones.
- **Datos sintéticos:** `scripts/sembrar_desarrollo.py` para la base de desarrollo; laboratorios sintéticos (activos, suspendido y cancelado) en las pruebas.
- **Certificado local** con comodín `*.lablinea.localhost`.

### Desviación del plan

El plan previa crear también `lablinea_metricas` en esta etapa. **Se pospone a las etapas 15 y 16:** ese rol tiene `BYPASSRLS`, y crearlo antes de que exista la bodega dejaría un privilegio alto sin uso (mínimo privilegio). Tampoco hizo falta modificar `/etc/hosts`: macOS resuelve `*.localhost`.

## Compuerta de calidad ([infraestructura/0011](../infraestructura/0011-calidad-pruebas-entorno-local.md))

| # | Criterio | Resultado | Evidencia |
|---|----------|-----------|-----------|
| 1 | Pruebas en verde (local y CI) | ✅ | 122 pruebas (77 nuevas), local y CI |
| 2 | Cobertura ≥ 85% | ✅ | 100% de líneas y ramas |
| 3 | E2E de flujos nuevos | N/A | Sin flujos de usuario (la portada solo muestra el laboratorio); Playwright entra en la etapa 2 |
| 4 | Migraciones upgrade/downgrade | ✅ | 0002 sube y baja en local (desarrollo y prueba) y en la CI |
| 5 | Aislamiento entre laboratorios | ✅ | Cada subdominio ve solo su laboratorio; el laboratorio no se cambia con parámetros, cabeceras ni cookies; 600 peticiones concurrentes sin cruces (ver abajo); guardián de RLS en verde |
| 6 | Autorización | ✅ | Matriz rol × esquema (8 casos) y rol × tabla × privilegio (15 casos), más intentos reales denegados: la aplicación no lee laboratorios ni modifica catálogos; la plataforma no usa `lab` ni borra laboratorios |
| 7 | Auditoría | N/A | Sin datos de salud todavía (etapa 3) |
| 8 | Sin datos sensibles en logs, errores ni URLs | ✅ | El 404 no revela si el laboratorio existe, está cancelado o es inválido; la contraseña del nuevo rol no aparece en `repr` ni logs |
| 9 | ruff / bandit / pip-audit / gitleaks | ✅ | Limpios; gitleaks: 0 secretos en 6 commits y en el árbol de trabajo |
| 10 | ZAP pasivo + activo | ✅ | Altos 0 · Medios 0 · Bajos 0 · Informativos 2 (los mismos de la etapa 0); 364 peticiones, sin 5xx ni excepciones |
| 11 | schemathesis sin errores 500 | ✅ | Todos los endpoints, contra `lab-a` |
| 12 | Pruebas manuales dirigidas | ✅ | Ver abajo |
| 13 | Rendimiento | N/A | Sin endpoints críticos. Referencia: mediana de 60 ms con 50 peticiones concurrentes sobre HTTPS con consulta a la base |

## Pruebas específicas de la etapa

| Prueba | Resultado |
|--------|-----------|
| `Host` en el servidor real: `lab-a`, `LAB-A`, `lab-b` → 200; `no-existe`, `lab-canc`, `admin`, dominio base, `x.lab-a`, `lab-a'--`, etiqueta de 64 caracteres → 404; `lab-a.lablinea.localhost.` (punto final) → 400 | ✅ |
| `X-Forwarded-Host`, `X-Tenant`, `?tenant=`, cookie `tenant` no cambian el laboratorio | ✅ |
| Inyección SQL en la búsqueda del laboratorio (`' OR '1'='1`, `;`, comodines `%` y `_`) | ✅ Sin resultados |
| `hypothesis`: ningún texto arbitrario produce un subdominio con puntos, mayúsculas, caracteres no ASCII o más de 63 caracteres | ✅ |
| **Concurrencia con pool real:** 600 peticiones, 50 simultáneas, mezclando `lab-a`, `lab-b` y un subdominio inexistente (`scripts/pruebas_manuales/concurrencia_tenants.py`) | ✅ 0 errores, 0 respuestas con el laboratorio equivocado |
| Enumeración por tiempos: mediana de 60 ms (existente) frente a 57 ms (inexistente) | ✅ Diferencia no explotable |
| Restricciones de `plataforma.laboratorios`: subdominios reservados, mayúsculas, guion bajo, guion inicial; `tenant_id` inválido; duplicados de subdominio, `tenant_id` y NIT; nombre de 1 carácter | ✅ Todas rechazadas por la base |
| Laboratorio en país no habilitado | ✅ Rechazado por el trigger |
| Función de resolución: `SECURITY DEFINER`, `search_path` fijo, sin `EXECUTE` para `PUBLIC` | ✅ |
| Zonas horarias de los países válidas en PostgreSQL | ✅ |

## Hallazgos y resolución

| Hallazgo | Severidad | Herramienta | Resolución |
|----------|-----------|-------------|------------|
| schemathesis cargaba el esquema desde `lab-a` al recolectar, antes de sembrar los laboratorios, y fallaba con 404 | Error de prueba | pytest | El esquema se carga desde el dominio base; los ataques siguen contra `lab-a` |
| El certificado local no cubría subdominios nuevos (la prueba de concurrencia con `no-existe` fallaba en TLS) | Entorno | Prueba manual | Certificado regenerado con comodín `*.lablinea.localhost` |
| Informativos de ZAP 10015 y 10104 | Informativo | ZAP | Mismos de la etapa 0; aceptables (ver [etapa 0](etapa-00.md)) |

No se encontraron vulnerabilidades en la aplicación en esta etapa.

## Riesgos aceptados por el usuario

Ninguno.
