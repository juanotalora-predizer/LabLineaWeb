"""Resume el reporte JSON de ZAP y falla si hay hallazgos de riesgo alto o medio (spec infraestructura/0011).

Las alertas que un filtro de scripts/zap/plan.yaml marcó como falso positivo (confianza 0) se listan aparte y no
bloquean: cada filtro está acotado a regla y ruta, y su evidencia queda en el cierre de la etapa.
"""

import json
import sys
from collections import Counter

RIESGOS = {"3": "Alto", "2": "Medio", "1": "Bajo", "0": "Informativo"}
FALSO_POSITIVO = "0"  # confianza que ZAP asigna a las alertas filtradas como falso positivo


def main(ruta: str) -> int:
    with open(ruta, encoding="utf-8") as archivo:
        reporte = json.load(archivo)

    todas = [a for sitio in reporte.get("site", []) for a in sitio.get("alerts", [])]
    alertas = [a for a in todas if a.get("confidence") != FALSO_POSITIVO]
    descartadas = [a for a in todas if a.get("confidence") == FALSO_POSITIVO]
    conteo = Counter(a["riskcode"] for a in alertas)

    resumen = " · ".join(f"{RIESGOS[r]}: {conteo.get(r, 0)}" for r in RIESGOS)
    print(f"Hallazgos por riesgo: {resumen} · Falsos positivos verificados: {len(descartadas)}")
    for alerta in sorted(alertas, key=lambda a: a["riskcode"], reverse=True):
        riesgo = RIESGOS[alerta["riskcode"]]
        print(f"  [{riesgo}] {alerta['name']} (plugin {alerta['pluginid']}, {alerta['count']} instancias)")
    for alerta in descartadas:
        print(
            f"  [Falso positivo verificado] {alerta['name']} (plugin {alerta['pluginid']}, ver scripts/zap/plan.yaml)"
        )

    bloqueantes = conteo.get("3", 0) + conteo.get("2", 0)
    if bloqueantes:
        print(f"FALLA: {bloqueantes} hallazgos de riesgo alto o medio.")
        return 1
    print("OK: sin hallazgos de riesgo alto o medio.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
