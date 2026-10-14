"""Genera una exportación SINTÉTICA del catálogo de Lablinea (ZIP de CSV) para probar el importador.

Imita lo que produce Access en español: Windows-1252, separador punto y coma, booleanos True/False y
coma decimal en los costos. Los exámenes y rangos son de ejemplo, no un catálogo clínico validado.

    .venv/bin/python scripts/lablinea_sintetico.py lablinea_sintetico.zip
"""

import io
import sys
import zipfile

SECCIONES = [("HEM", "Hematología"), ("QUI", "Química sanguínea"), ("URO", "Uroanálisis"), ("INM", "Inmunología")]
UNIDADES = ["g/dL", "mg/dL", "%", "x10^3/uL", "mUI/mL", "U/L"]
MUESTRAS = [("SANG", "Sangre total"), ("SUER", "Suero"), ("ORIN", "Orina")]
TARIFAS = [("PART", "Particular"), ("EPS1", "Convenio EPS sintética")]

# (codigo, nombre, seccion, CUPS, muestra, costo, [(parametro, unidad, referencia, minimo, maximo)])
EXAMENES = [
    ("HEMO", "Hemograma", "HEM", "902210", "SANG", "25000,00", [
        ("Serie roja", "", "", "", ""),
        ("Hemoglobina", "g/dL", "12 - 16 g/dL", "12", "16"),
        ("Hematocrito", "%", "36 - 48 %", "36", "48"),
        ("Leucocitos", "x10^3/uL", "4,5 - 11", "", ""),
    ]),
    ("GLU", "Glucosa", "QUI", "903841", "SUER", "12000", [("Glucosa", "mg/dL", "70 - 100 mg/dL", "", "")]),
    ("COL", "Colesterol total", "QUI", "903818", "SUER", "14000", [("Colesterol", "mg/dL", "< 200 mg/dL", "", "")]),
    ("TGL", "Triglicéridos", "QUI", "903868", "SUER", "14000", [("Triglicéridos", "mg/dL", "< 150", "", "")]),
    ("CREA", "Creatinina", "QUI", "903895", "SUER", "13000", [("Creatinina", "mg/dL", "0,6 - 1,2", "0.6", "1.2")]),
    ("ALT", "Transaminasa ALT", "QUI", "903866", "SUER", "15000", [("ALT", "U/L", "Hasta 41 U/L", "", "")]),
    ("TSH", "Hormona tiroestimulante", "INM", "904902", "SUER", "38000", [("TSH", "mUI/mL", "0.4 - 4.0", "", "")]),
    ("PO", "Parcial de orina", "URO", "907106", "ORIN", "16000", [
        ("Examen físico", "", "", "", ""),
        ("Color", "", "Amarillo", "", ""),
        ("Aspecto", "", "Claro", "", ""),
        ("Proteínas", "mg/dL", "Negativo", "", ""),
    ]),
]  # fmt: skip

LISTAS = {"Color": ["Amarillo", "Ámbar", "Rojizo"], "Aspecto": ["Claro", "Ligeramente turbio", "Turbio"]}


def _csv(encabezado: list[str], filas: list[list[str]]) -> bytes:
    lineas = [";".join(encabezado), *(";".join(fila) for fila in filas)]
    return ("\r\n".join(lineas) + "\r\n").encode("cp1252")


def generar() -> bytes:
    analisis, detalle, muestras, costos, listas = [], [], [], [], []
    consecutivo_detalle = 100
    for numero, (codigo, nombre, seccion, cups, muestra, costo, parametros) in enumerate(EXAMENES, start=1):
        analisis.append([str(numero), codigo, muestra, nombre, seccion, cups, "False", "LU a VI"])
        muestras.append([str(numero), str(numero), muestra, muestra])
        costos.append(["PART", str(numero), costo])
        costos.append(["EPS1", str(numero), costo.replace("000", "500", 1)])
        for orden, (parametro, unidad, referencia, minimo, maximo) in enumerate(parametros, start=1):
            consecutivo_detalle += 1
            titulo = "True" if not referencia and not unidad else "False"
            detalle.append(
                [str(consecutivo_detalle), str(numero), parametro, unidad, str(orden), referencia, titulo, "False",
                 minimo, maximo]
            )  # fmt: skip
            for valor in LISTAS.get(parametro, []):
                listas.append([str(len(listas) + 1), str(consecutivo_detalle), valor])
    archivos = {
        "seccion.csv": _csv(["codigo", "descripcion"], [list(s) for s in SECCIONES]),
        "unidad.csv": _csv(["codigo", "descripcion"], [[u, u] for u in UNIDADES]),
        "analisis.csv": _csv(
            [
                "consecutivo",
                "codigo examen",
                "especimen",
                "descripcion",
                "seccion",
                "CodigoSGSS",
                "AutorizAdic",
                "DiasMontaje",
            ],
            analisis,
        ),  # fmt: skip
        "detalle analisis.csv": _csv(
            [
                "consecutivo",
                "analisis",
                "descripcion",
                "unidad",
                "orden de presentacion",
                "normal de referencia",
                "Es titulo ?",
                "grafica",
                "RangoMinimo",
                "RangoMaximo",
            ],
            detalle,
        ),  # fmt: skip
        "lista de valores.csv": _csv(["consecutivo", "pregunta por analisis", "valor"], listas),
        "tipo muestra.csv": _csv(["tipo", "descripcion"], [list(m) for m in MUESTRAS]),
        "muestras x analisis.csv": _csv(["consecutivo", "analisis", "descripcion", "tipo de muestra"], muestras),
        "tipo tarifa.csv": _csv(["codigo", "descripcion"], [list(t) for t in TARIFAS]),
        "costo analisis.csv": _csv(["tipo tarifa", "analisis", "costo"], costos),
    }
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as z:
        for nombre, contenido in archivos.items():
            z.writestr(nombre, contenido)
    return salida.getvalue()


if __name__ == "__main__":
    destino = sys.argv[1] if len(sys.argv) > 1 else "lablinea_sintetico.zip"
    with open(destino, "wb") as archivo:
        archivo.write(generar())
    print(f"Exportación sintética escrita en {destino}")
