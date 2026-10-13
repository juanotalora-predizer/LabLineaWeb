#!/usr/bin/env bash
# Levanta la aplicación en HTTPS local (spec infraestructura/0011), solo en la interfaz de loopback.
#   https://lab-a.lablinea.localhost:8443 · https://lab-b.lablinea.localhost:8443 · https://admin.lablinea.localhost:8443
# Requiere certs/local.pem y certs/local-key.pem (mkcert). Para que el navegador confíe: `mkcert -install` (una vez).
set -euo pipefail
cd "$(dirname "$0")/.."

PUERTO="${PUERTO:-8443}"

if [[ ! -f certs/local.pem || ! -f certs/local-key.pem ]]; then
  echo "Faltan los certificados. Generarlos con:" >&2
  echo "  mkcert -cert-file certs/local.pem -key-file certs/local-key.pem lab-a.lablinea.localhost lab-b.lablinea.localhost admin.lablinea.localhost localhost 127.0.0.1 ::1" >&2
  exit 1
fi

exec .venv/bin/uvicorn app.main:app \
  --host 127.0.0.1 --port "$PUERTO" \
  --ssl-certfile certs/local.pem --ssl-keyfile certs/local-key.pem \
  --no-server-header "$@"
