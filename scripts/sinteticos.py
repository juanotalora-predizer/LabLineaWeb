"""Generador de personas sintéticas para desarrollo y pruebas (spec infraestructura/0003: solo datos sintéticos).

Reproducible: la misma semilla produce siempre las mismas personas. Nada sale de datos reales:
nombres y apellidos de listas comunes combinados al azar, documentos con el prefijo 99 (fuera de
los rangos de expedición habituales), correos en el dominio reservado .test (RFC 2606) y
teléfonos con el prefijo 300 000.

Los tipos de documento se reciben como parámetro (salen de la configuración del país en
global.tipos_documento); el generador no conoce ningún país.

    .venv/bin/python scripts/sinteticos.py --cantidad 20 --semilla 7 --tipos CC,TI,CE
"""

import argparse
import json
import random
import sys
from dataclasses import asdict, dataclass
from datetime import date, timedelta

NOMBRES_F = (
    "María", "Luisa", "Ana", "Carolina", "Daniela", "Valentina", "Sofía", "Camila", "Paula", "Andrea",
    "Juliana", "Natalia", "Laura", "Mariana", "Gabriela", "Isabela", "Catalina", "Adriana", "Lucía", "Elena",
)  # fmt: skip
NOMBRES_M = (
    "Juan", "Carlos", "Andrés", "Felipe", "Santiago", "Sebastián", "Mateo", "Nicolás", "Diego", "Alejandro",
    "Camilo", "Esteban", "Julián", "Martín", "Samuel", "Tomás", "David", "Gabriel", "Simón", "Emilio",
)  # fmt: skip
APELLIDOS = (
    "Gómez", "Rodríguez", "Martínez", "López", "González", "Pérez", "Sánchez", "Ramírez", "Torres", "Díaz",
    "Vargas", "Rojas", "Moreno", "Jiménez", "Castro", "Ortiz", "Rubio", "Herrera", "Mejía", "Suárez",
    "Cárdenas", "Quintero", "Salazar", "Ospina", "Arango", "Restrepo", "Zapata", "Cifuentes", "Patiño", "Londoño",
)  # fmt: skip

PREFIJO_DOCUMENTO = "99"
DOMINIO_CORREO = "sintetico.test"
PREFIJO_TELEFONO = "300000"


@dataclass(frozen=True)
class PersonaSintetica:
    tipo_documento: str
    numero_documento: str
    nombres: str
    apellidos: str
    sexo: str  # F / M (sexo biológico, usado por los rangos de referencia)
    fecha_nacimiento: date
    email: str
    telefono: str

    @property
    def nombre_completo(self) -> str:
        return f"{self.nombres} {self.apellidos}"

    def identificadores(self) -> tuple[str, ...]:
        """Valores que nunca deben aparecer en logs, errores ni URLs."""
        return (self.nombre_completo, self.numero_documento, self.email, self.telefono)


def _sin_tildes(texto: str) -> str:
    tabla = str.maketrans("áéíóúñÁÉÍÓÚÑ", "aeiounAEIOUN")
    return texto.translate(tabla).lower()


def generar_personas(
    cantidad: int, *, semilla: int, tipos_documento: tuple[str, ...], hoy: date | None = None
) -> list[PersonaSintetica]:
    """Genera `cantidad` personas distintas (documento y correo únicos) de 0 a 90 años."""
    if not tipos_documento:
        raise ValueError("se requiere al menos un tipo de documento")
    # Azar reproducible para datos de prueba; no es criptografía.
    azar = random.Random(semilla)  # noqa: S311 # nosec B311
    hoy = hoy or date.today()
    personas: list[PersonaSintetica] = []
    documentos: set[str] = set()
    while len(personas) < cantidad:
        sexo = azar.choice("FM")
        nombres = azar.choice(NOMBRES_F if sexo == "F" else NOMBRES_M)
        apellidos = f"{azar.choice(APELLIDOS)} {azar.choice(APELLIDOS)}"
        numero = PREFIJO_DOCUMENTO + f"{azar.randrange(10**8):08d}"
        if numero in documentos:
            continue
        documentos.add(numero)
        nacimiento = hoy - timedelta(days=azar.randrange(0, 90 * 365))
        usuario_correo = f"{_sin_tildes(nombres)}.{_sin_tildes(apellidos.split()[0])}.{numero[-6:]}"
        personas.append(
            PersonaSintetica(
                tipo_documento=azar.choice(tipos_documento),
                numero_documento=numero,
                nombres=nombres,
                apellidos=apellidos,
                sexo=sexo,
                fecha_nacimiento=nacimiento,
                email=f"{usuario_correo}@{DOMINIO_CORREO}",
                telefono=PREFIJO_TELEFONO + f"{azar.randrange(10**4):04d}",
            )
        )
    return personas


def main(argumentos: list[str] | None = None) -> None:
    analizador = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analizador.add_argument("--cantidad", type=int, default=10)
    analizador.add_argument("--semilla", type=int, default=2026)
    analizador.add_argument("--tipos", default="CC", help="tipos de documento separados por coma")
    opciones = analizador.parse_args(argumentos)
    tipos = tuple(t.strip() for t in opciones.tipos.split(",") if t.strip())
    for persona in generar_personas(opciones.cantidad, semilla=opciones.semilla, tipos_documento=tipos):
        sys.stdout.write(json.dumps(asdict(persona), default=str, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
