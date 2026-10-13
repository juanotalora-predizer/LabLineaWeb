"""Pruebas manuales dirigidas de autenticación contra el servidor HTTPS local (etapa 2).

Requiere el servidor corriendo (scripts/servidor_https.sh) y los datos de desarrollo sembrados
(scripts/sembrar_desarrollo.py). Levanta un SMTP de captura en 127.0.0.1:1025.

    .venv/bin/python scripts/pruebas_manuales/autenticacion.py "$(mkcert -CAROOT)/rootCA.pem"
"""

import re
import statistics
import sys
import time
from email import message_from_bytes, policy
from pathlib import Path

import httpx
import pyotp
from aiosmtpd.controller import Controller

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.core.config import get_settings  # noqa: E402

BASE_A = "https://lab-a.lablinea.localhost:8443"
BASE_B = "https://lab-b.lablinea.localhost:8443"
CSRF = re.compile(r'name="csrf" value="([^"]+)"')
resultados: list[tuple[str, bool, str]] = []


def registrar(nombre: str, ok: bool, detalle: str = "") -> None:
    resultados.append((nombre, ok, detalle))
    print(f"[{'OK ' if ok else 'FALLA'}] {nombre} {detalle}")


class Buzon:
    def __init__(self):
        self.mensajes = []

    async def handle_DATA(self, server, session, envelope):  # noqa: N802
        self.mensajes.append(message_from_bytes(envelope.content, policy=policy.default))
        return "250 OK"


def cliente(ca: str, base: str = BASE_A) -> httpx.Client:
    return httpx.Client(base_url=base, verify=ca, follow_redirects=False, timeout=30)


def token(c: httpx.Client, ruta: str = "/ingresar") -> str:
    return CSRF.search(c.get(ruta).text).group(1)


def main(ca: str) -> int:
    settings = get_settings()
    clave = settings.dev_clave_usuarios.get_secret_value()
    totp = pyotp.TOTP(settings.dev_totp_secreto.get_secret_value())
    buzon = Buzon()
    smtp = Controller(buzon, hostname="127.0.0.1", port=settings.smtp_port)
    smtp.start()
    try:
        # 1. Fuerza bruta: 5 fallos bloquean la cuenta; luego ni la clave correcta entra; mismo mensaje.
        with cliente(ca) as c:
            for _ in range(5):
                c.post("/ingresar", data={"email": "recepcion@lab-a.test", "clave": "Mala-clave-123", "csrf": token(c)})
            r = c.post("/ingresar", data={"email": "recepcion@lab-a.test", "clave": clave, "csrf": token(c)})
            registrar(
                "Bloqueo tras 5 fallos (clave correcta rechazada)",
                r.status_code == 400 and "Correo o contraseña incorrectos." in r.text,
                f"({r.status_code})",
            )

        # 2. Enumeración por tiempo: correo existente vs inexistente.
        def mediana(email_fn):
            tiempos = []
            for i in range(8):
                with cliente(ca) as c:
                    t = token(c)
                    inicio = time.perf_counter()
                    c.post("/ingresar", data={"email": email_fn(i), "clave": "Mala-clave-123", "csrf": t})
                    tiempos.append(time.perf_counter() - inicio)
            return statistics.median(tiempos)

        existe = mediana(lambda i: "paciente@lab-b.test" if i % 2 else "admin@lab-b.test")
        no_existe = mediana(lambda i: f"nadie{i}@lab-b.test")
        registrar(
            "Tiempo no revela si el correo existe",
            abs(existe - no_existe) < 0.25 * max(existe, no_existe),
            f"(existe {existe * 1000:.0f} ms · no existe {no_existe * 1000:.0f} ms)",
        )

        # 3. Ingreso completo del paciente con código por correo y cookies reales.
        with cliente(ca) as c:
            r = c.post("/ingresar", data={"email": "paciente@lab-a.test", "clave": clave, "csrf": token(c)})
            cookie_pend = r.headers.get("set-cookie", "")
            time.sleep(0.3)
            mensaje = buzon.mensajes[-1]
            cuerpo = mensaje.get_content()
            codigo = re.search(r"\b(\d{6})\b", cuerpo).group(1)
            registrar(
                "Correo del código sin datos clínicos",
                not any(p in cuerpo.lower() for p in ("resultado", "examen", "diagnóstico")),
            )
            r = c.post("/verificar", data={"codigo": codigo, "csrf": token(c, "/verificar")})
            sesion = [v for v in r.headers.get_list("set-cookie") if v.startswith("__Host-sesion=")][0].lower()
            registrar(
                "Cookie de sesión: Secure, HttpOnly, SameSite=Lax, sin Domain",
                all(a in sesion for a in ("secure", "httponly", "samesite=lax", "path=/")) and "domain=" not in sesion,
            )
            registrar("Token rota al completar el ingreso", cookie_pend.split(";")[0] != sesion.split(";")[0])
            panel = c.get("/panel")
            registrar(
                "Página autenticada no se guarda en caché",
                panel.status_code == 200 and panel.headers.get("cache-control") == "no-store",
            )
            registrar("Página autenticada no se puede enmarcar", panel.headers.get("x-frame-options") == "DENY")

            # 4. CSRF entre orígenes con sesión válida.
            r = c.post("/salir", data={"csrf": token(c, "/panel")}, headers={"origin": "https://atacante.example"})
            registrar(
                "Salir desde otro origen rechazado (CSRF)", r.status_code == 403 and c.get("/panel").status_code == 200
            )

            # 5. La sesión de lab-a no sirve en lab-b.
            with cliente(ca, BASE_B) as b:
                b.cookies.set("__Host-sesion", c.cookies.get("__Host-sesion"), domain="lab-b.lablinea.localhost")
                registrar("Sesión de lab-a rechazada en lab-b", b.get("/panel").status_code == 303)

            # 6. Salir invalida la sesión en el servidor.
            robada = c.cookies.get("__Host-sesion")
            c.post("/salir", data={"csrf": token(c, "/panel")})
            with cliente(ca) as otro:
                otro.cookies.set("__Host-sesion", robada, domain="lab-a.lablinea.localhost")
                registrar("Cookie copiada deja de servir tras salir", otro.get("/panel").status_code == 303)

        # 7. Personal con TOTP: un código no se reutiliza.
        with cliente(ca, BASE_B) as c:
            c.post("/ingresar", data={"email": "admin@lab-b.test", "clave": clave, "csrf": token(c)})
            codigo = totp.now()
            r1 = c.post("/verificar", data={"codigo": codigo, "csrf": token(c, "/verificar")})
        with cliente(ca, BASE_B) as c:
            c.post("/ingresar", data={"email": "admin@lab-b.test", "clave": clave, "csrf": token(c)})
            r2 = c.post("/verificar", data={"codigo": codigo, "csrf": token(c, "/verificar")})
        registrar("Código TOTP reutilizado rechazado", r1.status_code == 303 and r2.status_code == 400)
    finally:
        smtp.stop()

    fallas = [n for n, ok, _ in resultados if not ok]
    print(f"\n{len(resultados) - len(fallas)}/{len(resultados)} pruebas manuales OK")
    return 1 if fallas else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
