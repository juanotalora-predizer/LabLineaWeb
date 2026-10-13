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

scripts/servidor_https.sh > "$ZAP_REPORTES/servidor.log" 2>&1 &
PID_SERVIDOR=$!
trap 'kill $PID_SERVIDOR 2>/dev/null || true; rm -rf "$ZAP_HOME_TMP"' EXIT

for _ in $(seq 1 40); do
  curl -sk "$ZAP_OBJETIVO/health" >/dev/null && break
  sleep 0.5
done
curl -skf "$ZAP_OBJETIVO/health" >/dev/null || { echo "El servidor no arrancó; ver $ZAP_REPORTES/servidor.log" >&2; exit 1; }

echo "== ZAP contra $ZAP_OBJETIVO"
"$ZAP_DIR/zap.sh" -cmd -dir "$ZAP_HOME_TMP" -autorun "$PWD/scripts/zap/plan.yaml" > "$ZAP_REPORTES/zap.log" 2>&1 || {
  echo "ZAP terminó con error; ver $ZAP_REPORTES/zap.log" >&2
  tail -20 "$ZAP_REPORTES/zap.log" >&2
  exit 1
}

.venv/bin/python -I scripts/zap/resumen.py "$ZAP_REPORTES/zap-reporte.json"
