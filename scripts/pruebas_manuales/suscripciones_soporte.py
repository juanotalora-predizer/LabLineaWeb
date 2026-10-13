"""Pruebas manuales dirigidas de la etapa 5 contra el servidor HTTPS local y la base de desarrollo.

Requiere el servidor corriendo (scripts/servidor_https.sh) y los datos de desarrollo sembrados
(scripts/sembrar_desarrollo.py). Levanta un SMTP de captura en 127.0.0.1:1025 y ejecuta el trabajador real.

    .venv/bin/python scripts/pruebas_manuales/suscripciones_soporte.py "$(mkcert -CAROOT)/rootCA.pem"
"""

import asyncio
import re
import signal
import subprocess  # nosec B404
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date
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


def token(c: httpx.Client, ruta: str = "/ingresar") -> str:
    return CSRF.search(c.get(ruta).text).group(1)


def ingresar(ca: str, sub: str, email: str) -> httpx.Client:
    settings = get_settings()
    totp = pyotp.TOTP(settings.dev_totp_secreto.get_secret_value())
    c = httpx.Client(base_url=url(sub), verify=ca, follow_redirects=False, timeout=30)
    clave = settings.dev_clave_usuarios.get_secret_value()
    if c.post("/ingresar", data={"email": email, "clave": clave, "csrf": token(c)}).status_code != 303:
        raise SystemExit(f"Ingreso fallido de {email}")
    for _ in range(2):
        if c.post("/verificar", data={"codigo": totp.now(), "csrf": token(c, "/verificar")}).status_code == 303:
            return c
        time.sleep(31 - time.time() % 30)  # código ya usado en esta ventana (anti-repetición)
    raise SystemExit(f"Segundo factor fallido para {email}")


async def sql(rol: str, sentencia: str, parametros: dict | None = None, tenant: str | None = None):
    settings = get_settings()
    url_bd = {"owner": settings.url_owner, "plataforma": settings.url_plataforma}[rol]()
    engine = create_async_engine(url_bd, poolclass=NullPool)
    try:
        async with engine.begin() as conexion:
            if tenant:
                await conexion.execute(text("SELECT set_config('app.current_tenant', :t, true)"), {"t": tenant})
            resultado = await conexion.execute(text(sentencia), parametros or {})
            return resultado.scalar() if resultado.returns_rows else "ejecutada"
    except Exception as exc:  # noqa: BLE001
        return "permission denied" if "permission denied" in str(exc) else type(exc).__name__
    finally:
        await engine.dispose()


def correr_sql(*argumentos, **opciones):
    return asyncio.run(sql(*argumentos, **opciones))


# Suscripción de lab-b: fin relativo a ahora (vencida o por vencer) y restauración.
AJUSTE_LAB_B = (
    "UPDATE plataforma.suscripciones SET estado = 'ACTIVA', inicio = now() - interval '40 days',"
    " fin = now() + make_interval(mins => :minutos)"
    " WHERE laboratorio_id = (SELECT id FROM plataforma.laboratorios WHERE tenant_id = 'lab_b')"
)
RESTAURAR_LAB_B = (
    "UPDATE plataforma.suscripciones SET tipo_licencia = 'AD_HONOREM', estado = 'ACTIVA', fin = NULL"
    " WHERE laboratorio_id = (SELECT id FROM plataforma.laboratorios WHERE tenant_id = 'lab_b')"
)


def main(ca: str) -> int:
    buzon = Buzon()
    smtp = Controller(buzon, hostname="127.0.0.1", port=get_settings().smtp_port)
    smtp.start()
    try:
        admin = ingresar(ca, "admin", "admin@admin.test")
        lab_a = ingresar(ca, "lab-a", "admin@lab-a.test")
        uuid_a = correr_sql("owner", "SELECT uuid::text FROM plataforma.laboratorios WHERE tenant_id = 'lab_a'")

        # 1. Facturación: laboratorio nuevo (licencia mensual) dado de alta por el Admin Hub, su primera factura,
        #    un pago que excede el saldo y pagos concurrentes.
        sub = f"manual-{uuid.uuid4().hex[:6]}"
        formulario = admin.get("/laboratorios/nuevo").text
        plan = re.search(r'name="plan"><option value="([0-9a-f-]{36})"', formulario).group(1)
        alta = {
            "nombre": "Laboratorio Facturación Manual",
            "subdominio": sub,
            "identificador_fiscal": "9" + str(uuid.uuid4().int)[:9],
            "pais": "COL",
            "plan": plan,
            "tipo_licencia": "MENSUAL",
            "sede": "Sede",
            "ciudad": "Cali",
            "admin_email": f"jefe@{sub}.test",
            "admin_nombre": "Jefe Manual",
            "csrf": token(admin, "/laboratorios/nuevo"),
        }
        nuevo = admin.post("/laboratorios/nuevo", data=alta).headers["location"]
        r = admin.post(f"{nuevo}/facturas", data={"tipo_licencia": "MENSUAL", "csrf": token(admin, nuevo)})
        ruta = r.headers["location"]
        saldo = correr_sql(
            "owner", "SELECT saldo::text FROM plataforma.facturas WHERE uuid = :f", {"f": ruta.rsplit("/", 1)[1]}
        )
        datos = {"medio": "TRANSFERENCIA", "referencia": "MANUAL", "recibido_en": date.today().isoformat()}
        r = admin.post(f"{ruta}/pagos", data={**datos, "valor": str(float(saldo) + 1), "csrf": token(admin, ruta)})
        registrar("Pago mayor que el saldo → 400", r.status_code == 400 and "supera el saldo" in r.text)

        csrf_admin = token(admin, ruta)

        def pagar_todo(_):
            # Misma sesión, peticiones simultáneas: la base debe aceptar solo una.
            return admin.post(f"{ruta}/pagos", data={**datos, "valor": saldo, "csrf": csrf_admin}).status_code

        with ThreadPoolExecutor(max_workers=3) as hilos:
            estados = sorted(hilos.map(pagar_todo, range(3)))
        estado_final = correr_sql(
            "owner", "SELECT estado FROM plataforma.facturas WHERE uuid = :f", {"f": ruta.rsplit("/", 1)[1]}
        )
        registrar(
            "Tres pagos simultáneos del saldo: uno aceptado, la factura queda PAGADA",
            estados.count(303) == 1 and estado_final == "PAGADA",
            f"({estados}, {estado_final})",
        )

        # 2. SQL directo con el rol de la plataforma.
        for sentencia in ("UPDATE plataforma.facturas SET saldo = 0", "DELETE FROM plataforma.pagos"):
            estado = correr_sql("plataforma", sentencia)
            registrar(f"Rol de plataforma: {sentencia}", estado == "permission denied", f"({estado})")

        # 3. Suscripción vencida de lab-b: sigue el ingreso y la consulta, con el aviso.
        correr_sql("owner", AJUSTE_LAB_B, {"minutos": -60})
        lab_b = ingresar(ca, "lab-b", "admin@lab-b.test")
        panel = lab_b.get("/panel")
        registrar(
            "Suscripción vencida: ingresa, consulta usuarios y ve el aviso",
            panel.status_code == 200
            and "está vencida" in panel.text
            and lab_b.get("/configuracion/usuarios").status_code == 200,
        )

        # 4. Aviso de renovación por el trabajador real (vence en 20 horas → aviso de 1 día).
        correr_sql("owner", AJUSTE_LAB_B, {"minutos": 20 * 60})
        trabajador = subprocess.Popen([sys.executable, str(RAIZ / "trabajador.py")], cwd=RAIZ)  # noqa: S603 # nosec B603
        limite = time.time() + 20
        aviso = None
        while time.time() < limite and aviso is None:
            aviso = next((m for m in buzon.mensajes if m["To"] == "admin@lab-b.test" and "vence" in m["Subject"]), None)
            time.sleep(0.5)
        trabajador.send_signal(signal.SIGTERM)
        trabajador.wait(timeout=30)
        registrar("El trabajador envía el aviso de renovación a la administración de lab-b", aviso is not None)
        correr_sql("owner", RESTAURAR_LAB_B)

        # 5. Soporte: sin autorización → 403.
        correr_sql(
            "owner", "UPDATE lab.accesos_soporte SET revocado_en = now() WHERE revocado_en IS NULL", tenant="lab_a"
        )
        r = admin.post(f"/soporte/{uuid_a}/iniciar", data={"csrf": token(admin, "/soporte")})
        registrar("Soporte sin autorización del laboratorio → 403", r.status_code == 403)

        # 6. Con autorización: entra en solo lectura, auditado; el tiquete no se reutiliza ni sirve en otro laboratorio.
        lab_a.post(
            "/configuracion/soporte",
            data={"horas": "1", "motivo": "Prueba manual", "csrf": token(lab_a, "/configuracion/soporte")},
        )
        r = admin.post(f"/soporte/{uuid_a}/iniciar", data={"csrf": token(admin, "/soporte")})
        enlace = re.search(r'href="(https://[^"]+/soporte/entrar/[^"]+)"', r.text).group(1)
        tiquete = enlace.rsplit("/", 1)[1]
        ajeno = httpx.Client(base_url=url("lab-b"), verify=ca, follow_redirects=False, timeout=30)
        en_otro = ajeno.post(f"/soporte/entrar/{tiquete}", data={"csrf": token(ajeno)}).status_code
        soporte = httpx.Client(base_url=url("lab-a"), verify=ca, follow_redirects=False, timeout=30)
        entrada = soporte.post(
            f"/soporte/entrar/{tiquete}", data={"csrf": token(soporte, f"/soporte/entrar/{tiquete}")}
        )
        repetida = httpx.Client(base_url=url("lab-a"), verify=ca, follow_redirects=False, timeout=30)
        reuso = repetida.post(f"/soporte/entrar/{tiquete}", data={"csrf": token(repetida)}).status_code
        registrar(
            "Tiquete: en otro laboratorio 404, entra en el suyo, reuso 404",
            (en_otro, entrada.status_code, reuso) == (404, 303, 404),
            f"({en_otro}, {entrada.status_code}, {reuso})",
        )
        consulta = soporte.get("/configuracion/usuarios").status_code
        invitar = soporte.get("/configuracion/usuarios/nuevo").status_code
        registrar("Soporte en solo lectura: consulta 200, invitar 403", (consulta, invitar) == (200, 403))
        auditadas = correr_sql(
            "owner",
            "SELECT count(*) FROM lab.auditoria a JOIN lab.usuarios u ON a.usuario_id = u.uuid::text"
            " WHERE u.tipo = 'SOPORTE' AND a.tabla = 'soporte' AND a.ocurrido_en > now() - interval '5 minutes'",
            tenant="lab_a",
        )
        registrar("Peticiones del soporte en la auditoría del laboratorio", auditadas >= 3, f"({auditadas})")

        # 7. IDOR: lab-b no revoca la autorización de lab-a; lab-a sí, y la sesión de soporte termina.
        acceso = re.search(
            r"/configuracion/soporte/([0-9a-f-]{36})/revocar", lab_a.get("/configuracion/soporte").text
        ).group(1)
        r = lab_b.post(f"/configuracion/soporte/{acceso}/revocar", data={"csrf": token(lab_b, "/panel")})
        registrar("IDOR: lab-b no revoca la autorización de lab-a → 404", r.status_code == 404)
        lab_a.post(f"/configuracion/soporte/{acceso}/revocar", data={"csrf": token(lab_a, "/configuracion/soporte")})
        registrar("Revocar termina la sesión de soporte", soporte.get("/panel").status_code == 303)
    finally:
        smtp.stop()

    fallas = [r for r in resultados if not r[1]]
    print(f"\n{len(resultados) - len(fallas)} de {len(resultados)} pruebas manuales OK")
    return 1 if fallas else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
