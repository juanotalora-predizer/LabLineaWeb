"""Pruebas manuales dirigidas de la etapa 6 (catálogo e importador) contra el servidor HTTPS local.

Requiere el servidor corriendo (scripts/servidor_https.sh) y los datos de desarrollo sembrados
(scripts/sembrar_desarrollo.py, que deja el catálogo sintético en lab-a).

    .venv/bin/python scripts/pruebas_manuales/catalogo.py "$(mkcert -CAROOT)/rootCA.pem"
"""

import csv
import io
import re
import sys
import time
import uuid
import zipfile
from pathlib import Path

import httpx
import pyotp

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
from app.core.config import get_settings  # noqa: E402
from scripts.lablinea_sintetico import generar  # noqa: E402

PUERTO = 8443
CSRF = re.compile(r'name="csrf" value="([^"]+)"')
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


def zip_de(archivos: dict[str, bytes]) -> bytes:
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as z:
        for nombre, contenido in archivos.items():
            z.writestr(nombre, contenido)
    return salida.getvalue()


def subir(c: httpx.Client, datos: bytes, nombre: str) -> httpx.Response:
    return c.post(
        "/catalogo/importar",
        data={"csrf": token(c, "/catalogo/importar")},
        files={"archivo": (nombre, datos, "application/zip")},
    )


def main(ca: str) -> int:
    lab_a = ingresar(ca, "lab-a", "admin@lab-a.test")
    lab_b = ingresar(ca, "lab-b", "admin@lab-b.test")

    # 1. Archivos que no corresponden o maliciosos: rechazados con 400, sin error 500.
    valido = generar()
    casos = {
        "Ejecutable de Windows renombrado a .zip": (b"MZ\x90\x00" + b"\x00" * 4000, "malware.zip"),
        "Script de shell renombrado": (b"#!/bin/sh\nrm -rf /\n", "catalogo.zip"),
        "ZIP con ruta ../ (path traversal)": (zip_de({"../../etc/passwd.csv": b"a;b\n"}), "x.zip"),
        "ZIP con tabla de pacientes": (
            zip_de({"paciente.csv": b"consecutivo;apellidos\n1;Ficticio\n"}),
            "x.zip",
        ),
        "Bomba ZIP (10 MB de ceros)": (zip_de({"seccion.csv": b"codigo;descripcion\n" + b"0" * 10_000_000}), "x.zip"),
        "ZIP truncado": (valido[: len(valido) // 3], "x.zip"),
        "Archivo de 11 MB": (b"PK\x03\x04" + b"0" * (11 * 1024 * 1024), "grande.zip"),
        "CSV en UTF-16": (zip_de({"seccion.csv": "codigo;descripcion\nH;Hema\n".encode("utf-16")}), "x.zip"),
    }
    for nombre, (datos, archivo) in casos.items():
        r = subir(lab_b, datos, archivo)
        registrar(f"Rechazo: {nombre}", r.status_code == 400 and "Ficticio" not in r.text, f"({r.status_code})")

    # 2. Importación válida en lab-b: vista previa sin carga, carga atómica.
    r = subir(lab_b, valido, "lablinea_sintetico.zip")
    vista = r.headers.get("location", "")
    previa = lab_b.get(vista).text if vista else ""
    nada_cargado = "Hemograma" not in lab_b.get("/catalogo").text
    cargado = lab_b.post(f"{vista}/cargar", data={"csrf": token(lab_b, vista)}).status_code == 303 if vista else False
    hay_catalogo = "Hemograma" in lab_b.get("/catalogo").text
    registrar(
        "Importación válida: vista previa sin cargar nada, luego carga completa",
        "Cargar el catálogo" in previa or "ya existe" in previa,
        f"(previa sin carga: {nada_cargado}, cargado: {cargado}, catálogo: {hay_catalogo})",
    )

    # 3. IDOR: un examen y una importación de lab-b desde lab-a.
    examen_b = re.search(r'href="(/catalogo/examenes/[0-9a-f-]{36})"', lab_b.get("/catalogo").text)
    if examen_b:
        ruta = examen_b.group(1)
        registrar("IDOR: examen de lab-b desde lab-a → 404", lab_a.get(ruta).status_code == 404)
        r = lab_a.post(f"{ruta}/estado", data={"csrf": token(lab_a, "/catalogo")})
        registrar("IDOR: desactivar examen de lab-b desde lab-a → 404", r.status_code == 404)
    if vista:
        registrar("IDOR: importación de lab-b desde lab-a → 404", lab_a.get(vista).status_code == 404)

    # 4. Inyección: HTML y fórmulas en el nombre; SQL en la búsqueda.
    s = uuid.uuid4().hex[:5]
    lab_a.post(
        "/catalogo/maestros/secciones",
        data={"codigo": f"M{s}", "nombre": "Manual", "csrf": token(lab_a, "/catalogo/maestros")},
    )
    nombre = f'<img src=x onerror=alert(1)>=cmd|" /C calc"!A0 {s}'
    r = lab_a.post(
        "/catalogo/examenes/nuevo",
        data={
            "codigo": f"=M{s}",
            "nombre": nombre,
            "seccion": f"M{s}",
            "csrf": token(lab_a, "/catalogo/examenes/nuevo"),
        },
    )
    pagina = lab_a.get(r.headers.get("location", "/catalogo")).text
    registrar("HTML en el nombre del examen se muestra escapado", "<img src=x" not in pagina and "&lt;img" in pagina)
    exportado = lab_a.get("/catalogo/exportar.csv").text.lstrip("﻿")
    celdas = [c for fila in csv.reader(io.StringIO(exportado)) for c in fila]
    registrar(
        "Exportación CSV: ninguna celda empieza como fórmula",
        all(not c.startswith(("=", "+", "-", "@")) for c in celdas) and f"'=M{s}" in celdas,
    )
    r = lab_a.get("/catalogo", params={"q": "' OR 1=1; DROP TABLE lab.examenes; --"})
    registrar(
        "SQL en la búsqueda: 200 y el catálogo sigue",
        r.status_code == 200 and "Hemograma" in lab_a.get("/catalogo").text,
    )

    # 5. CSRF y Host.
    r = lab_a.post(
        "/catalogo/maestros/secciones", data={"codigo": "X", "nombre": "X"}, headers={"Origin": "https://evil.example"}
    )
    registrar("Maestro desde otro origen (CSRF) → 403", r.status_code == 403)
    r = httpx.get(f"https://lab-a.lablinea.localhost:{PUERTO}/catalogo", headers={"Host": "evil.example"}, verify=ca)
    registrar("Host ajeno → 400", r.status_code == 400)

    fallas = [r for r in resultados if not r[1]]
    print(f"\n{len(resultados) - len(fallas)} de {len(resultados)} pruebas manuales OK")
    return 1 if fallas else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
