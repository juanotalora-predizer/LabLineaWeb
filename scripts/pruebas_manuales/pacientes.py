"""Pruebas manuales dirigidas de la etapa 7 (pacientes y Ley 1581) contra el servidor HTTPS local.

Requiere el servidor corriendo (scripts/servidor_https.sh, con su salida en un archivo) y los datos de
desarrollo sembrados (scripts/sembrar_desarrollo.py: texto de autorización y pacientes sintéticos).

    .venv/bin/python scripts/pruebas_manuales/pacientes.py "$(mkcert -CAROOT)/rootCA.pem" servidor.log
"""

import re
import sys
import time
import uuid
from pathlib import Path

import httpx
import pyotp

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
from app.core.config import get_settings  # noqa: E402
from scripts.sinteticos import generar_personas  # noqa: E402

PUERTO = 8443
CSRF = re.compile(r'name="csrf" value="([^"]+)"')
UUID_PACIENTE = re.compile(r'href="(/pacientes/[0-9a-f-]{36})"')
resultados: list[tuple[str, bool, str]] = []


def registrar(nombre: str, ok: bool, detalle: str = "") -> None:
    resultados.append((nombre, ok, detalle))
    print(f"[{'OK ' if ok else 'FALLA'}] {nombre} {detalle}")


def token(c: httpx.Client, ruta: str = "/ingresar") -> str:
    return CSRF.search(c.get(ruta).text).group(1)


def ingresar(ca: str, sub: str, email: str) -> httpx.Client:
    settings = get_settings()
    totp = pyotp.TOTP(settings.dev_totp_secreto.get_secret_value())
    c = httpx.Client(
        base_url=f"https://{sub}.lablinea.localhost:{PUERTO}", verify=ca, follow_redirects=False, timeout=60
    )
    clave = settings.dev_clave_usuarios.get_secret_value()
    if c.post("/ingresar", data={"email": email, "clave": clave, "csrf": token(c)}).status_code != 303:
        raise SystemExit(f"Ingreso fallido de {email}")
    for _ in range(2):
        if c.post("/verificar", data={"codigo": totp.now(), "csrf": token(c, "/verificar")}).status_code == 303:
            return c
        time.sleep(31 - time.time() % 30)
    raise SystemExit(f"Segundo factor fallido para {email}")


def buscar(c: httpx.Client, consulta: str) -> httpx.Response:
    return c.post("/pacientes/buscar", data={"consulta": consulta, "csrf": token(c, "/pacientes")})


def registrar_paciente(c: httpx.Client, **datos) -> httpx.Response:
    base = {
        "tipo_documento": "CC",
        "numero_documento": "96" + str(uuid.uuid4().int)[:8],
        "nombres": "Manual",
        "apellidos": "Sintético",
        "sexo": "F",
        "fecha_nacimiento": "1988-08-08",
        "pais": "COL",
        "medio": "FORMATO_FIRMADO",
        "acepto": "si",
    }
    return c.post("/pacientes/nuevo", data={**base, **datos, "csrf": token(c, "/pacientes/nuevo")})


def main(ca: str, log_servidor: str) -> int:
    # Los mismos pacientes sintéticos que siembra sembrar_desarrollo.py en cada laboratorio.
    tipos = ("AS", "CC", "CD", "CE", "CN", "DE", "MS", "PA", "PE", "PT", "RC", "SC", "TI")
    de_lab_a = generar_personas(10, semilla=sum(map(ord, "lab_a")), tipos_documento=tipos)
    de_lab_b = generar_personas(10, semilla=sum(map(ord, "lab_b")), tipos_documento=tipos)
    usados = [de_lab_a[0].numero_documento, de_lab_b[0].numero_documento]

    lab_a = ingresar(ca, "lab-a", "admin@lab-a.test")
    lab_b = ingresar(ca, "lab-b", "admin@lab-b.test")

    # 1. Búsqueda sin enumeración.
    r = buscar(lab_a, de_lab_a[0].numero_documento)
    encontrado = UUID_PACIENTE.search(r.text)
    registrar("Búsqueda por documento exacto encuentra al paciente", r.status_code == 200 and bool(encontrado))
    r = buscar(lab_a, de_lab_a[0].numero_documento[:-3])
    registrar("Un prefijo del documento no encuentra nada", not UUID_PACIENTE.search(r.text))
    r = buscar(lab_a, "' OR 1=1 --")
    registrar("SQL en la búsqueda: sin resultados", r.status_code == 200 and not UUID_PACIENTE.search(r.text))
    r = buscar(lab_a, de_lab_b[0].numero_documento)
    registrar("Documento de un paciente de lab-b no aparece en lab-a", not UUID_PACIENTE.search(r.text))

    # 2. IDOR: la ficha de un paciente de lab-b desde lab-a.
    ficha_b = UUID_PACIENTE.search(buscar(lab_b, de_lab_b[0].numero_documento).text).group(1)
    estados = [lab_a.get(f"{ficha_b}{sufijo}").status_code for sufijo in ("", "/datos", "/editar")]
    registrar("IDOR: ficha, informe y edición de lab-b desde lab-a → 404", estados == [404, 404, 404], f"{estados}")
    r = lab_a.post(f"{ficha_b}/revocar", data={"canal": "CORREO", "motivo": "x", "csrf": token(lab_a, "/pacientes")})
    registrar("IDOR: revocar la autorización de un paciente de lab-b → 404", r.status_code == 404)

    # 3. HTML en el nombre: escapado en la ficha y en la búsqueda.
    r = registrar_paciente(lab_a, nombres="<img src=x onerror=alert(1)>", apellidos="Xss")
    ficha = r.headers.get("location", "")
    pagina = lab_a.get(ficha).text if ficha else ""
    registrar("HTML en el nombre se muestra escapado", "<img src=x" not in pagina and "&lt;img" in pagina)

    # 4. Ley 1581: revocar y suprimir.
    r = registrar_paciente(lab_a)
    ficha = r.headers["location"]
    lab_a.post(f"{ficha}/revocar", data={"canal": "PRESENCIAL", "motivo": "Lo pidió", "csrf": token(lab_a, ficha)})
    registrar("Revocación: la ficha queda sin autorización", "Sin autorización" in lab_a.get(ficha).text)
    documento = "96" + str(uuid.uuid4().int)[:8]
    usados.append(documento)
    ficha = registrar_paciente(lab_a, numero_documento=documento).headers["location"]
    lab_a.post(f"{ficha}/solicitudes", data={"tipo": "SUPRESION", "canal": "CORREO", "csrf": token(lab_a, ficha)})
    solicitud = re.search(r'name="solicitud"><option value="([0-9a-f-]{36})"', lab_a.get(ficha).text).group(1)
    recepcion = ingresar(ca, "lab-a", "recepcion@lab-a.test")
    r = recepcion.post(
        f"{ficha}/suprimir",
        data={"solicitud": solicitud, "confirmacion": "SUPRIMIR", "csrf": token(recepcion, "/pacientes")},
    )
    registrar("Recepción no puede suprimir → 403", r.status_code == 403)
    r = lab_a.post(
        f"{ficha}/suprimir", data={"solicitud": solicitud, "confirmacion": "SUPRIMIR", "csrf": token(lab_a, ficha)}
    )
    pagina = lab_a.get(r.headers.get("location", ficha)).text
    sin_rastro = not UUID_PACIENTE.search(buscar(lab_a, documento).text)
    registrar(
        "Supresión: registro anonimizado y el documento ya no se encuentra",
        "Registro suprimido" in pagina and documento not in pagina and sin_rastro,
    )

    # 5. Enumeración por fuerza bruta: límite de búsquedas.
    estados = [buscar(lab_b, f"{n:010d}").status_code for n in range(65)]
    registrar("Más de 60 búsquedas en 5 minutos → 429", 429 in estados, f"(primer 429 en la {estados.index(429) + 1})")

    # 6. CSRF y método.
    r = lab_a.post("/pacientes/buscar", data={"consulta": "Gómez"}, headers={"Origin": "https://evil.example"})
    registrar("Búsqueda desde otro origen (CSRF) → 403", r.status_code == 403)
    r = lab_a.get("/pacientes/buscar", params={"consulta": "sonda-sin-datos"})
    # La sonda no lleva un documento: el log de acceso registra toda URL que envíe el cliente.
    registrar("La búsqueda no acepta GET (el documento no viaja en la URL)", r.status_code in (404, 405, 422, 400))

    # 7. Ningún documento usado quedó en el log del servidor (accesos y errores).
    log = Path(log_servidor).read_text(encoding="utf-8", errors="replace")
    fuga = [d for d in usados if d in log]
    errores_500 = log.count('" 500')
    registrar("Sin documentos de pacientes en el log del servidor", not fuga)
    registrar("Sin errores 500 en el log del servidor", errores_500 == 0, f"({errores_500})")

    fallas = [r for r in resultados if not r[1]]
    print(f"\n{len(resultados) - len(fallas)} de {len(resultados)} pruebas manuales OK")
    return 1 if fallas else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
