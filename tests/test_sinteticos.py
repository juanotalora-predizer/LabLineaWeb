"""Generador de datos sintéticos (scripts/sinteticos.py) y ausencia de datos de pacientes en los logs.

La búsqueda sobre los logs de TODA la corrida está en tests/conftest.py (pytest_sessionfinish).
Aquí se ejercitan a propósito los caminos que registran algo, con pacientes sintéticos.
"""

import json
import logging
from datetime import date

import pytest

from app.core import correo
from scripts import sinteticos
from scripts.sinteticos import generar_personas
from tests.ayudas import autenticar, cliente, codigo_en_buzon, csrf, enviar_clave, enviar_codigo
from tests.conftest import COLECTOR_DE_LOGS, PACIENTES_SINTETICOS, identificadores_en_logs

TIPOS = ("CC", "TI", "CE")
HOY = date(2026, 10, 13)


def test_misma_semilla_mismas_personas():
    assert generar_personas(5, semilla=1, tipos_documento=TIPOS, hoy=HOY) == generar_personas(
        5, semilla=1, tipos_documento=TIPOS, hoy=HOY
    )
    assert generar_personas(5, semilla=1, tipos_documento=TIPOS) != generar_personas(
        5, semilla=2, tipos_documento=TIPOS
    )


def test_personas_validas_y_marcadas_como_sinteticas():
    personas = generar_personas(300, semilla=7, tipos_documento=TIPOS, hoy=HOY)
    assert len({p.numero_documento for p in personas}) == 300
    assert len({p.email for p in personas}) == 300
    for p in personas:
        assert p.tipo_documento in TIPOS
        assert p.numero_documento.startswith(sinteticos.PREFIJO_DOCUMENTO) and len(p.numero_documento) == 10
        assert p.email.endswith("@" + sinteticos.DOMINIO_CORREO) and p.email.isascii()
        assert p.telefono.startswith(sinteticos.PREFIJO_TELEFONO)
        assert p.sexo in ("F", "M")
        assert date(1936, 1, 1) <= p.fecha_nacimiento <= HOY
        assert p.nombre_completo in p.identificadores()


def test_exige_tipos_de_documento():
    with pytest.raises(ValueError):
        generar_personas(1, semilla=1, tipos_documento=())


def test_linea_de_comandos_produce_json(capsys):
    sinteticos.main(["--cantidad", "3", "--semilla", "9", "--tipos", "CC, TI"])
    lineas = capsys.readouterr().out.strip().splitlines()
    assert len(lineas) == 3
    assert {json.loads(linea)["tipo_documento"] for linea in lineas} <= {"CC", "TI"}


# --- Datos de pacientes en los logs ---


def test_flujos_con_pacientes_sinteticos_no_dejan_sus_datos_en_los_logs(buzon, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    paciente, otro = PACIENTES_SINTETICOS[0], PACIENTES_SINTETICOS[1]

    # Ingreso fallido, ingreso completo con código por correo y salida.
    c = cliente()
    assert enviar_clave(c, paciente.email, "clave-equivocada").status_code == 400
    autenticar(c, paciente.email, buzon)
    assert c.get("/panel").status_code == 200
    c.post("/salir", data={"csrf": csrf(c, "/panel")})

    # El servidor de correo falla al enviar el código (camino que sí registra en el log).
    def falla(_mensaje):
        raise OSError("SMTP caído para " + otro.email)

    monkeypatch.setattr(correo, "_enviar_sync", falla)
    c2 = cliente()
    enviar_clave(c2, otro.email)
    monkeypatch.setattr(correo, "_enviar_sync", buzon.append)

    # Entrada inválida con datos del paciente: el error no repite la entrada.
    respuesta = c2.post("/ingresar", data={"email": otro.nombre_completo + "\x00", "csrf": csrf(c2)})
    assert respuesta.status_code == 400
    assert otro.nombre_completo not in respuesta.text

    # Segundo factor equivocado.
    c3 = cliente()
    enviar_clave(c3, paciente.email)
    enviar_codigo(c3, "000000")
    codigo_en_buzon(buzon, paciente.email)

    assert caplog.records, "la prueba debe ejercitar caminos que registran en el log"
    assert identificadores_en_logs([caplog.text]) == []
    assert identificadores_en_logs(COLECTOR_DE_LOGS.textos) == []


def test_la_busqueda_en_logs_detecta_una_fuga():
    paciente = PACIENTES_SINTETICOS[2]
    assert identificadores_en_logs([f"Error procesando {paciente.numero_documento}"]) == [paciente.numero_documento]
