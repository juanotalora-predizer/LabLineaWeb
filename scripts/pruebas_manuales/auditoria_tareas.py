"""Pruebas manuales dirigidas de la etapa 3 contra el servidor HTTPS local y la base de desarrollo.

Requiere el servidor corriendo (scripts/servidor_https.sh) y los datos de desarrollo sembrados
(scripts/sembrar_desarrollo.py).

    .venv/bin/python scripts/pruebas_manuales/auditoria_tareas.py "$(mkcert -CAROOT)/rootCA.pem" [servidor.log]

1-2. Lectura y acceso denegado reales quedan auditados, con el usuario y la IP.
3.   La auditoría de lab-a no se ve desde lab-b.
4.   SQL directo con el rol de la aplicación: no modifica, borra ni vacía la auditoría ni lee particiones.
5.   Un trabajador muerto con SIGKILL a mitad de tarea: otro la retoma al vencer el plazo y el efecto
     ocurre una sola vez.
6.   El log del servidor no contiene datos de los pacientes sintéticos sembrados.
"""

import asyncio
import os
import re
import signal
import subprocess  # nosec B404
import sys
import time
from pathlib import Path

import httpx
import pyotp
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
from app.core import db  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from scripts.sembrar_desarrollo import PACIENTES_POR_LABORATORIO  # noqa: E402
from scripts.sinteticos import generar_personas  # noqa: E402

BASE_A = "https://lab-a.lablinea.localhost:8443"
CSRF = re.compile(r'name="csrf" value="([^"]+)"')
resultados: list[tuple[str, bool, str]] = []

# Trabajador de la prueba 5: registra un manejador que deja un evento y, en el primer intento, se cuelga.
TRABAJADOR = """
import asyncio, os, sys
sys.path.insert(0, {raiz!r})
from sqlalchemy import text
from app.core import db, tareas

@tareas.tarea("manual.colgada")
async def manejador(sesion, datos):
    await sesion.execute(text("INSERT INTO lab.eventos_seguridad (tenant_id, tipo) VALUES (lab.tenant_actual(), :t)"),
                         {{"t": datos["evento"]}})
    if os.environ.get("COLGARSE") == "1":
        await asyncio.sleep(60)

async def main():
    print("procesada" if await tareas.procesar_una(plazo_segundos=int(os.environ["PLAZO"])) else "vacia", flush=True)
    await db.cerrar()

asyncio.run(main())
"""


def correr(corrutina):
    """Cada asyncio.run tiene su propio bucle: el pool del engine no puede pasar de uno a otro."""

    async def con_cierre():
        try:
            return await corrutina
        finally:
            await db.cerrar()

    return asyncio.run(con_cierre())


def registrar(nombre: str, ok: bool, detalle: str = "") -> None:
    resultados.append((nombre, ok, detalle))
    print(f"[{'OK ' if ok else 'FALLA'}] {nombre} {detalle}")


def ingresar(ca: str, email: str) -> httpx.Client:
    settings = get_settings()
    c = httpx.Client(base_url=BASE_A, verify=ca, follow_redirects=False, timeout=30)
    token = CSRF.search(c.get("/ingresar").text).group(1)
    c.post("/ingresar", data={"email": email, "clave": settings.dev_clave_usuarios.get_secret_value(), "csrf": token})
    totp = pyotp.TOTP(settings.dev_totp_secreto.get_secret_value())
    for _ in range(2):
        token = CSRF.search(c.get("/verificar").text).group(1)
        respuesta = c.post("/verificar", data={"codigo": totp.now(), "csrf": token})
        if respuesta.status_code == 303:
            return c
        # Anti-repetición: el código de este intervalo ya se usó en una corrida anterior.
        time.sleep(31 - time.time() % 30)
    raise AssertionError(f"no se pudo completar el ingreso de {email}: {respuesta.status_code}")


async def ultima_auditoria(tenant: str, email: str, operacion: str):
    async with db.sesion_tenant(tenant) as sesion:
        return (
            (
                await sesion.execute(
                    text(
                        "SELECT a.tabla, a.resultado, host(a.ip) AS ip, a.despues FROM lab.auditoria a"
                        " JOIN lab.usuarios u ON a.usuario_id = u.uuid::text"
                        " WHERE u.email = :e AND a.operacion = :o ORDER BY a.id DESC LIMIT 1"
                    ),
                    {"e": email, "o": operacion},
                )
            )
            .mappings()
            .first()
        )


async def pruebas_de_base() -> None:
    settings = get_settings()

    # 3. Aislamiento de la auditoría.
    async with db.sesion_tenant("lab_b") as sesion:
        ajenas = await sesion.scalar(text("SELECT count(*) FROM lab.auditoria WHERE tenant_id <> 'lab_b'"))
    registrar("Auditoría de lab-a invisible desde lab-b", ajenas == 0, f"(filas ajenas: {ajenas})")

    # 4. SQL directo con el rol de la aplicación.
    app = create_async_engine(settings.url_app(), poolclass=NullPool)
    for sentencia in (
        "UPDATE lab.auditoria SET tabla = 'x'",
        "DELETE FROM lab.auditoria",
        "TRUNCATE lab.auditoria",
        "INSERT INTO lab.auditoria (tenant_id, tabla, operacion) VALUES ('lab_a', 'x', 'UPDATE')",
        "SELECT count(*) FROM lab.auditoria_sin_particion",  # partición consultada directamente
        "SELECT count(*) FROM cola.tareas",
    ):
        try:
            async with app.begin() as conexion:
                await conexion.execute(text("SELECT set_config('app.current_tenant', 'lab_a', true)"))
                await conexion.execute(text(sentencia))
            registrar(f"Rol app rechazado: {sentencia[:45]}", False, "(se ejecutó)")
        except Exception as exc:  # noqa: BLE001
            registrar(f"Rol app rechazado: {sentencia[:45]}", "permission denied" in str(exc))
    await app.dispose()


async def tarea_en_cola(evento: str) -> str:
    async with db.sesion_tenant("lab_a") as sesion:
        from app.core import tareas

        return await tareas.encolar(sesion, "manual.colgada", {"evento": evento}, max_intentos=3)


async def estado_tarea(uuid: str, evento: str) -> tuple:
    settings = get_settings()
    owner = create_async_engine(settings.url_owner(), poolclass=NullPool)
    async with owner.begin() as conexion:
        fila = (
            await conexion.execute(text("SELECT estado, intentos FROM cola.tareas WHERE uuid = :u"), {"u": uuid})
        ).one()
        await conexion.execute(text("SELECT set_config('app.current_tenant', 'lab_a', true)"))
        eventos = await conexion.scalar(
            text("SELECT count(*) FROM lab.eventos_seguridad WHERE tipo = :t"), {"t": evento}
        )
    await owner.dispose()
    return fila.estado, fila.intentos, eventos


def trabajador(colgarse: bool, plazo: int) -> subprocess.Popen:
    entorno = {**os.environ, "COLGARSE": "1" if colgarse else "0", "PLAZO": str(plazo)}
    # Intérprete propio y código fijo de este script, sin entrada externa.
    return subprocess.Popen(  # noqa: S603 # nosec B603
        [sys.executable, "-c", TRABAJADOR.format(raiz=str(RAIZ))], env=entorno, stdout=subprocess.PIPE, text=True
    )


def prueba_trabajador_muerto() -> None:
    evento = f"MANUAL_SIGKILL_{int(time.time())}"
    uuid = correr(tarea_en_cola(evento))
    primero = trabajador(colgarse=True, plazo=3)
    time.sleep(2)
    primero.send_signal(signal.SIGKILL)  # muere sin limpiar: la conexión se corta a mitad de transacción
    primero.wait()
    time.sleep(2)  # vence el plazo de 3 s
    segundo = trabajador(colgarse=False, plazo=60)
    salida, _ = segundo.communicate(timeout=60)
    estado, intentos, eventos = correr(estado_tarea(uuid, evento))
    registrar(
        "Trabajador muerto con SIGKILL: otro retoma la tarea y el efecto ocurre una vez",
        (salida.strip(), estado, intentos, eventos) == ("procesada", "COMPLETADA", 2, 1),
        f"(estado {estado}, intentos {intentos}, efectos {eventos})",
    )


def main(ca: str, log_servidor: str | None) -> int:
    # 1. Lectura real auditada.
    c = ingresar(ca, "admin@lab-a.test")
    estado = c.get("/configuracion/usuarios").status_code
    c.close()
    fila = correr(ultima_auditoria("lab_a", "admin@lab-a.test", "READ"))
    registrar(
        "Lista de usuarios auditada con usuario e IP",
        estado == 200 and fila is not None and fila["ip"] == "127.0.0.1" and fila["tabla"] == "usuarios",
        f"({dict(fila) if fila else None})",
    )
    # 2. Acceso denegado auditado.
    c = ingresar(ca, "recepcion@lab-a.test")
    estado = c.get("/configuracion/usuarios").status_code
    c.close()
    fila = correr(ultima_auditoria("lab_a", "recepcion@lab-a.test", "ACCESO"))
    registrar(
        "Acceso denegado (403) auditado",
        estado == 403 and fila is not None and fila["resultado"] == "DENEGADO",
        f"({dict(fila) if fila else None})",
    )
    correr(pruebas_de_base())
    prueba_trabajador_muerto()

    # 6. Datos de pacientes sintéticos en el log del servidor.
    if log_servidor:
        contenido = Path(log_servidor).read_text()
        hallados = []
        for tenant_id in ("lab_a", "lab_b"):
            tipos = ("AS", "CC", "CD", "CE", "CN", "DE", "MS", "PA", "PE", "PT", "RC", "SC", "TI")
            semilla = sum(map(ord, tenant_id))
            for p in generar_personas(PACIENTES_POR_LABORATORIO, semilla=semilla, tipos_documento=tipos):
                hallados += [v for v in p.identificadores() if v in contenido]
        registrar(
            "Log del servidor sin datos de pacientes sintéticos", not hallados, f"({len(hallados)} coincidencias)"
        )

    fallas = [r for r in resultados if not r[1]]
    print(f"\n{len(resultados) - len(fallas)} de {len(resultados)} pruebas manuales OK")
    return 1 if fallas else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None))
