"""Rangos de referencia: cobertura por sexo y edad (spec funcional/0009, sección 1).

Un rango cubre las edades [edad_min_dias, edad_max_dias) del sexo indicado; `T` aplica a ambos sexos.
Para cada sexo se revisa la cobertura de 0 a EDAD_MAXIMA_DIAS: huecos y solapes son advertencias
(un laboratorio puede no atender neonatos), nunca errores.
"""

from dataclasses import dataclass

EDAD_MAXIMA_DIAS = 54750  # 150 años
SEXOS = ("M", "F")


@dataclass(frozen=True)
class Rango:
    sexo: str  # M, F o T
    edad_min_dias: int
    edad_max_dias: int


@dataclass(frozen=True)
class Advertencia:
    tipo: str  # HUECO o SOLAPE
    sexo: str
    desde_dias: int
    hasta_dias: int


def analizar(rangos: list[Rango]) -> list[Advertencia]:
    advertencias: list[Advertencia] = []
    for sexo in SEXOS:
        aplicables = sorted(
            (r for r in rangos if r.sexo in (sexo, "T")), key=lambda r: (r.edad_min_dias, r.edad_max_dias)
        )
        cubierto_hasta = 0
        for rango in aplicables:
            if rango.edad_min_dias > cubierto_hasta:
                advertencias.append(Advertencia("HUECO", sexo, cubierto_hasta, rango.edad_min_dias))
            elif rango.edad_min_dias < cubierto_hasta:
                advertencias.append(
                    Advertencia("SOLAPE", sexo, rango.edad_min_dias, min(cubierto_hasta, rango.edad_max_dias))
                )
            cubierto_hasta = max(cubierto_hasta, rango.edad_max_dias)
        if cubierto_hasta < EDAD_MAXIMA_DIAS:
            advertencias.append(Advertencia("HUECO", sexo, cubierto_hasta, EDAD_MAXIMA_DIAS))
    return advertencias


def aplicable(rangos: list[Rango], sexo: str, edad_dias: int) -> list[Rango]:
    """Rangos que aplican a un paciente (lo usará la evaluación de resultados, etapa 12)."""
    return [r for r in rangos if r.sexo in (sexo, "T") and r.edad_min_dias <= edad_dias < r.edad_max_dias]


def edad_legible(dias: int) -> tuple[int, str]:
    """(cantidad, unidad) para mostrar una edad en días: años si es exacta en años, si no meses o días."""
    if dias and dias % 365 == 0:
        return dias // 365, "anios"
    if dias and dias % 30 == 0:
        return dias // 30, "meses"
    return dias, "dias"
