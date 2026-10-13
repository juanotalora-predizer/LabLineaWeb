"""Pruebas manuales dirigidas de la etapa 4 (Admin Hub) contra el servidor HTTPS local.

Requiere el servidor corriendo (scripts/servidor_https.sh) y los datos de desarrollo sembrados
(scripts/sembrar_desarrollo.py). Levanta un SMTP de captura en 127.0.0.1:1025 y ejecuta el
trabajador de tareas real (trabajador.py) para la invitación.

    .venv/bin/python scripts/pruebas_manuales/admin_hub.py "$(mkcert -CAROOT)/rootCA.pem"
"""

import asyncio
import re
import signal
import subprocess  # nosec B404
import sys
import time
import uuid
from email import message_from_bytes, policy
from pathlib import Path

import httpx
import pyotp
from aiosmtpd.controller import Controller
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
from app.core.config import get_settings  # noqa: E402

PUERTO = 8443
CSRF = re.compile(r'name="csrf" value="([^"]+)"')
resultados: list[tuple[str, bool, str]] = []


def url(sub: str) -> str:
    return f"https://{sub}.lablinea.localhost:{PUERTO}"


def registrar(nombre: str, ok: bool, detalle: str = "") -> None:
    resultados.append((nombre, ok, detalle))
    print(f"[{'OK ' if ok else 'FALLA'}] {nombre} {detalle}")


class Buzon:
    def __init__(self):
        self.mensajes = []

    async def handle_DATA(self, server, session, envelope):  # noqa: N802
        self.mensajes.append(message_from_bytes(envelope.content, policy=policy.default))
        return "250 OK"

    def para(self, email: str, patron: str, espera: float = 20) -> str:
        limite = time.time() + espera
        while time.time() < limite:
            for m in reversed(self.mensajes):
                if m["To"] == email and (hallado := re.search(patron, m.get_content())):
                    return hallado.group(1)
            time.sleep(0.2)
        raise AssertionError(f"no llegó el correo esperado a {email}")


def cliente(ca: str, sub: str) -> httpx.Client:
    return httpx.Client(base_url=url(sub), verify=ca, follow_redirects=False, timeout=30)


def token(c: httpx.Client, ruta: str = "/ingresar") -> str:
    return CSRF.search(c.get(ruta).text).group(1)


def ingresar(ca: str, sub: str, email: str) -> httpx.Client:
    settings = get_settings()
    totp = pyotp.TOTP(settings.dev_totp_secreto.get_secret_value())
    c = cliente(ca, sub)
    r = c.post(
        "/ingresar", data={"email": email, "clave": settings.dev_clave_usuarios.get_secret_value(), "csrf": token(c)}
    )
    if r.status_code != 303:
        raise SystemExit(f"Ingreso fallido de {email}: {r.status_code}")
    for _ in range(2):
        r = c.post("/verificar", data={"codigo": totp.now(), "csrf": token(c, "/verificar")})
        if r.status_code == 303:
            return c
        time.sleep(31 - time.time() % 30)  # código ya usado en esta ventana (anti-repetición)
    raise SystemExit(f"Segundo factor fallido para {email}")


def clave_rechazada(ca: str, sub: str, email: str) -> bool:
    c = cliente(ca, sub)
    clave = get_settings().dev_clave_usuarios.get_secret_value()
    return c.post("/ingresar", data={"email": email, "clave": clave, "csrf": token(c)}).status_code == 400


async def sql_plataforma(sentencia: str) -> str:
    settings = get_settings()
    engine = create_async_engine(settings.url_plataforma(), poolclass=NullPool)
    try:
        async with engine.begin() as conexion:
            await conexion.execute(text(sentencia))
        return "ejecutada"
    except Exception as exc:  # noqa: BLE001
        return "permission denied" if "permission denied" in str(exc) else type(exc).__name__
    finally:
        await engine.dispose()


def main(ca: str) -> int:
    buzon = Buzon()
    smtp = Controller(buzon, hostname="127.0.0.1", port=get_settings().smtp_port)
    smtp.start()
    trabajador = subprocess.Popen([sys.executable, str(RAIZ / "trabajador.py")], cwd=RAIZ)  # noqa: S603 # nosec B603
    try:
        admin = ingresar(ca, "admin", "admin@admin.test")
        lab = ingresar(ca, "lab-a", "admin@lab-a.test")

        # 1. Sesiones cruzadas entre sitios.
        intruso = cliente(ca, "lab-a")
        intruso.cookies.set("__Host-sesion", admin.cookies.get("__Host-sesion"))
        registrar("Cookie de sesión del Admin Hub rechazada en lab-a", intruso.get("/panel").status_code == 303)
        intruso = cliente(ca, "admin")
        intruso.cookies.set("__Host-sesion", lab.cookies.get("__Host-sesion"))
        registrar("Cookie de sesión de lab-a rechazada en el Admin Hub", intruso.get("/panel").status_code == 303)

        # 2. Credenciales de un sitio en el otro.
        registrar("Personal de plataforma no ingresa en lab-a", clave_rechazada(ca, "lab-a", "admin@admin.test"))
        registrar("Administrador de lab-a no ingresa en el Admin Hub", clave_rechazada(ca, "admin", "admin@lab-a.test"))

        # 3. Cabecera Host: rutas del Admin Hub pedidas con el host de un laboratorio.
        r = lab.get("/laboratorios", headers={"X-Forwarded-Host": f"admin.lablinea.localhost:{PUERTO}"})
        registrar("Rutas del Admin Hub en lab-a (también con X-Forwarded-Host) → 404", r.status_code == 404)
        r = httpx.get(f"{url('lab-a')}/laboratorios", headers={"Host": "evil.example"}, verify=ca)
        registrar("Host ajeno → 400", r.status_code == 400)

        # 4. CSRF en el alta: origen ajeno.
        r = admin.post(
            "/laboratorios/nuevo",
            data={"nombre": "Atacante", "csrf": token(admin, "/laboratorios/nuevo")},
            headers={"Origin": "https://evil.example"},
        )
        registrar("Alta desde otro origen (CSRF) → 403", r.status_code == 403)

        # 5. Inyección en el alta y XSS almacenado.
        datos = {
            "nombre": "<script>alert(1)</script>",
            "subdominio": "x'; DROP TABLE plataforma.laboratorios; --",
            "identificador_fiscal": "900111222",
            "pais": "COL",
            "plan": "' OR 1=1 --",
            "sede": "Sede",
            "ciudad": "Cali",
            "admin_email": "a@b.co",
            "admin_nombre": "Nombre",
            "csrf": token(admin, "/laboratorios/nuevo"),
        }
        r = admin.post("/laboratorios/nuevo", data=datos)
        registrar(
            "Inyección SQL en subdominio y plan → 400 sin error interno",
            r.status_code == 400 and "<script>alert(1)</script>" not in r.text,
        )

        # 6. IDOR: desactivar desde lab-a un usuario de lab-b.
        b = ingresar(ca, "lab-b", "admin@lab-b.test")
        b.close()
        uuid_b = asyncio.run(uuid_de_lab_b())
        r = lab.post(
            f"/configuracion/usuarios/{uuid_b}/desactivar", data={"csrf": token(lab, "/configuracion/usuarios")}
        )
        registrar("IDOR: lab-a no desactiva un usuario de lab-b → 404", r.status_code == 404)

        # 7. SQL directo con el rol de la plataforma.
        for sentencia in ("SELECT count(*) FROM lab.usuarios", "SELECT count(*) FROM lab.auditoria"):
            estado = asyncio.run(sql_plataforma(sentencia))
            registrar(f"Rol de plataforma: {sentencia}", estado == "permission denied", f"({estado})")
        estado = asyncio.run(sql_plataforma("UPDATE plataforma.auditoria SET tabla = 'x'"))
        registrar("Rol de plataforma no modifica su auditoría", estado == "permission denied", f"({estado})")

        # 8. Alta real con el trabajador real: invitación, activación e ingreso en el nuevo subdominio.
        sub = f"manual-{uuid.uuid4().hex[:6]}"
        jefe = f"jefe@{sub}.test"
        plan = re.search(r'<option value="([0-9a-f-]{36})"', admin.get("/laboratorios/nuevo").text).group(1)
        datos = {
            "nombre": "Laboratorio Manual",
            "subdominio": sub,
            "identificador_fiscal": "9" + str(uuid.uuid4().int)[:9],
            "pais": "COL",
            "plan": plan,
            "sede": "Sede Centro",
            "ciudad": "Cali",
            "admin_email": jefe,
            "admin_nombre": "Jefe Manual",
            "csrf": token(admin, "/laboratorios/nuevo"),
        }
        r = admin.post("/laboratorios/nuevo", data=datos)
        enlace = buzon.para(jefe, r"(https://\S+/activar/\S+)")
        nuevo = httpx.Client(verify=ca, follow_redirects=False, timeout=30)
        csrf_nuevo = CSRF.search(nuevo.get(enlace).text).group(1)
        clave = "Clave-Manual-Segura-2026"  # gitleaks:allow (cuenta sintética de la prueba)
        r2 = nuevo.post(enlace, data={"clave": clave, "confirmacion": clave, "csrf": csrf_nuevo})
        reuso = nuevo.get(enlace).status_code
        c = cliente(ca, sub)
        r3 = c.post("/ingresar", data={"email": jefe, "clave": clave, "csrf": token(c)})
        registrar(
            "Alta real → invitación por el trabajador → activación → ingreso en el nuevo subdominio",
            r.status_code == 303
            and enlace.startswith(url(sub))
            and r2.status_code == 303
            and reuso == 404
            and r3.headers.get("location") == "/verificar",
            f"(alta {r.status_code}, activación {r2.status_code}, reuso {reuso}, ingreso {r3.status_code})",
        )
        cuerpo = next(m for m in buzon.mensajes if m["To"] == jefe).get_content()
        registrar("El correo de invitación solo lleva el enlace (sin contraseña)", clave not in cuerpo)
    finally:
        trabajador.send_signal(signal.SIGTERM)
        trabajador.wait(timeout=30)
        smtp.stop()

    fallas = [r for r in resultados if not r[1]]
    print(f"\n{len(resultados) - len(fallas)} de {len(resultados)} pruebas manuales OK")
    return 1 if fallas else 0


async def uuid_de_lab_b() -> str:
    settings = get_settings()
    engine = create_async_engine(settings.url_owner(), poolclass=NullPool)
    async with engine.begin() as conexion:
        await conexion.execute(text("SELECT set_config('app.current_tenant', 'lab_b', true)"))
        valor = await conexion.scalar(text("SELECT uuid::text FROM lab.usuarios WHERE email = 'recepcion@lab-b.test'"))
    await engine.dispose()
    return valor


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
