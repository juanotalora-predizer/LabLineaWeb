"""Inicia sesión como el administrador sintético de lab-a (contraseña + TOTP) y escribe en la
salida estándar la cabecera Cookie para que ZAP escanee las páginas autenticadas.

    .venv/bin/python scripts/zap/sesion_zap.py https://lab-a.lablinea.localhost:8443 <ca.pem>
"""

import re
import sys
import time
from pathlib import Path

import httpx
import pyotp

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.core.config import get_settings  # noqa: E402

CSRF = re.compile(r'name="csrf" value="([^"]+)"')


def main(base: str, ca: str) -> None:
    settings = get_settings()
    host = base.split("://", 1)[1].split(":", 1)[0]
    email = "admin@" + host.split(".", 1)[0] + ".test"
    with httpx.Client(base_url=base, verify=ca, follow_redirects=False, timeout=20) as c:
        token = CSRF.search(c.get("/ingresar").text).group(1)
        r = c.post(
            "/ingresar", data={"email": email, "clave": settings.dev_clave_usuarios.get_secret_value(), "csrf": token}
        )
        if r.status_code != 303:
            raise SystemExit(f"Ingreso fallido ({r.status_code})")
        totp = pyotp.TOTP(settings.dev_totp_secreto.get_secret_value())
        for intento in range(2):
            token = CSRF.search(c.get("/verificar").text).group(1)
            r = c.post("/verificar", data={"codigo": totp.now(), "csrf": token})
            if r.status_code == 303:
                break
            # El código de esta ventana ya se usó (protección contra reutilización): esperar la siguiente.
            time.sleep(totp.interval - time.time() % totp.interval + 1) if intento == 0 else None
        if r.status_code != 303 or c.get("/panel").status_code != 200:
            raise SystemExit("Segundo factor fallido")
        print("; ".join(f"{k}={v}" for k, v in c.cookies.items()))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
