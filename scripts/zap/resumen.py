"""Resume el reporte JSON de ZAP y falla si hay hallazgos de riesgo alto o medio (spec infraestructura/0011)."""

import json
import sys
from collections import Counter

RIESGOS = {"3": "Alto", "2": "Medio", "1": "Bajo", "0": "Informativo"}


def main(ruta: str) -> int:
    with open(ruta, encoding="utf-8") as archivo:
        reporte = json.load(archivo)

    alertas = [a for sitio in reporte.get("site", []) for a in sitio.get("alerts", [])]
    conteo = Counter(a["riskcode"] for a in alertas)

    print("Hallazgos por riesgo: " + " · ".join(f"{RIESGOS[r]}: {conteo.get(r, 0)}" for r in RIESGOS))
    for alerta in sorted(alertas, key=lambda a: a["riskcode"], reverse=True):
        riesgo = RIESGOS[alerta["riskcode"]]
        print(f"  [{riesgo}] {alerta['name']} (plugin {alerta['pluginid']}, {alerta['count']} instancias)")

    bloqueantes = conteo.get("3", 0) + conteo.get("2", 0)
    if bloqueantes:
        print(f"FALLA: {bloqueantes} hallazgos de riesgo alto o medio.")
        return 1
    print("OK: sin hallazgos de riesgo alto o medio.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
