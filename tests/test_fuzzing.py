"""Fuzzing de todos los endpoints del esquema OpenAPI con schemathesis (spec infraestructura/0011).

Genera entradas a partir del esquema y verifica que ningún endpoint responda 500,
que las respuestas cumplan el esquema y que conserven las cabeceras de seguridad.
"""

import schemathesis

from app.core.seguridad import CABECERAS
from app.main import app

# El esquema se carga desde el dominio base: se lee al recolectar, antes de sembrar los laboratorios.
esquema = schemathesis.openapi.from_asgi("/openapi.json", app, headers={"host": "lablinea.localhost"})


@esquema.parametrize()
def test_endpoints_resisten_entradas_generadas(case):
    respuesta = case.call_and_validate(base_url="https://lab-a.lablinea.localhost")
    for nombre in CABECERAS:
        assert nombre in respuesta.headers, nombre
