#!/usr/bin/env bash
# Escaneo de seguridad externo (spec infraestructura/0011, criterios 10 y 11):
# levanta la aplicación en HTTPS local, corre OWASP ZAP (pasivo + activo) y falla si hay
# hallazgos de riesgo alto o medio. Reportes en reportes/zap/ (fuera de git).
set -euo pipefail
cd "$(dirname "$0")/.."

ZAP_DIR="${ZAP_DIR:-$HOME/herramientas/ZAP_2.17.0}"
export JAVA_HOME="${JAVA_HOME:-/opt/homebrew/opt/openjdk@21}"
PUERTO="${PUERTO:-8443}"
export ZAP_OBJETIVO="${ZAP_OBJETIVO:-https://lab-a.lablinea.localhost:$PUERTO}"
export ZAP_REPORTES="$PWD/reportes/zap"
ZAP_HOME_TMP="$(mktemp -d)"   # perfil de ZAP limpio en cada corrida

mkdir -p "$ZAP_REPORTES"
rm -f "$ZAP_REPORTES"/zap-reporte.*

.venv/bin/alembic upgrade head > /dev/null
.venv/bin/python scripts/sembrar_desarrollo.py

scripts/servidor_https.sh > "$ZAP_REPORTES/servidor.log" 2>&1 &
PID_SERVIDOR=$!
trap 'kill $PID_SERVIDOR 2>/dev/null || true; rm -rf "$ZAP_HOME_TMP"' EXIT

for _ in $(seq 1 40); do
  curl -sk "$ZAP_OBJETIVO/health" >/dev/null && break
  sleep 0.5
done
curl -skf "$ZAP_OBJETIVO/health" >/dev/null || { echo "El servidor no arrancó; ver $ZAP_REPORTES/servidor.log" >&2; exit 1; }

CA="$(mkcert -CAROOT)/rootCA.pem"
ZAP_COOKIE="$(.venv/bin/python scripts/zap/sesion_zap.py "$ZAP_OBJETIVO" "$CA")"
# Mecanismo de ZAP para escaneos autenticados: agrega la cabecera a toda petición hacia el sitio.
export ZAP_AUTH_HEADER=Cookie
export ZAP_AUTH_HEADER_VALUE="$ZAP_COOKIE"
export ZAP_AUTH_HEADER_SITE="${ZAP_OBJETIVO#https://}"
export ZAP_AUTH_HEADER_SITE="${ZAP_AUTH_HEADER_SITE%%:*}"

echo "== ZAP contra $ZAP_OBJETIVO"
"$ZAP_DIR/zap.sh" -cmd -dir "$ZAP_HOME_TMP" -autorun "$PWD/scripts/zap/plan.yaml" > "$ZAP_REPORTES/zap.log" 2>&1 || {
  echo "ZAP terminó con error; ver $ZAP_REPORTES/zap.log" >&2
  tail -20 "$ZAP_REPORTES/zap.log" >&2
  exit 1
}

# Evidencia de que el escaneo fue autenticado: la sesión sigue viva y ZAP llegó a páginas protegidas.
codigo_panel=$(curl -s -o /dev/null -w "%{http_code}" --cacert "$CA" -H "Cookie: $ZAP_COOKIE" "$ZAP_OBJETIVO/panel")
autenticadas=$(grep -cE '"GET /(panel|configuracion/usuarios)[^"]*" 200' "$ZAP_REPORTES/servidor.log" || true)
echo "Sesión al terminar: /panel -> $codigo_panel · peticiones autenticadas respondidas con 200: $autenticadas"
[[ "$codigo_panel" == "200" && "$autenticadas" -gt 0 ]] || { echo "FALLA: el escaneo no se mantuvo autenticado." >&2; exit 1; }

.venv/bin/python -I scripts/zap/resumen.py "$ZAP_REPORTES/zap-reporte.json"
