"""Autenticación: contraseña, segundo factor, bloqueo, sesiones (spec infraestructura/0008, etapa 2)."""

import statistics
import time

import pytest
from sqlalchemy import text

from app.auth import contrasenas
from tests.ayudas import (
    autenticar,
    cliente,
    codigo_en_buzon,
    csrf,
    enviar_clave,
    enviar_codigo,
    totp_actual,
)
from tests.conftest import CLAVE, ejecutar_en_tenant

ERROR_CREDENCIALES = "Correo o contraseña incorrectos."

# ------------------------------------------------------------------ contraseñas


@pytest.mark.parametrize(
    ("clave", "email", "valida"),
    [
        ("corta", "", False),
        ("a" * 12, "", False),  # poca variedad
        ("x" * 129 + "abcde", "", False),
        ("mi-correo-largo-2026", "micorreo@lab.test", True),
        ("contiene-paciente-2026", "paciente@lab.test", False),
        ("Clave-Segura-2026", "", True),
    ],
)
def test_politica_de_contrasenas(clave, email, valida):
    assert (contrasenas.validar_politica(clave, email) == []) is valida


def test_hash_es_argon2id_y_verifica():
    h = contrasenas.hashear("Clave-Segura-2026")
    assert h.startswith("$argon2id$")
    assert contrasenas.verificar(h, "Clave-Segura-2026")
    assert not contrasenas.verificar(h, "Clave-Segura-2027")
    assert not contrasenas.verificar(None, "Clave-Segura-2026")
    assert not contrasenas.verificar(h, "x" * 5000)
    assert not contrasenas.verificar("no-es-un-hash", "Clave-Segura-2026")
    assert not contrasenas.necesita_rehash(h)
    with pytest.raises(ValueError):
        contrasenas.hashear("corta")


# ------------------------------------------------------------- flujo completo


def test_paciente_ingresa_con_codigo_por_correo(buzon):
    c = cliente()
    respuesta = enviar_clave(c, "paciente@lab-a.test")
    assert respuesta.status_code == 303
    assert respuesta.headers["location"] == "/verificar"

    mensaje = buzon[-1]
    assert mensaje["To"] == "paciente@lab-a.test"
    cuerpo = mensaje.get_content()
    assert "Laboratorio A Sintético" in cuerpo
    for palabra in ("resultado", "examen", "diagnóstico", "orden"):
        assert palabra not in cuerpo.lower()  # el correo no lleva datos clínicos

    respuesta = enviar_codigo(c, codigo_en_buzon(buzon, "paciente@lab-a.test"))
    assert respuesta.status_code == 303
    assert respuesta.headers["location"] == "/panel"
    panel = c.get("/panel")
    assert panel.status_code == 200
    assert "Paciente A" in panel.text


def test_personal_ingresa_con_app_autenticadora(buzon):
    c = cliente()
    assert enviar_clave(c, "admin@lab-a.test").status_code == 303
    assert buzon == []  # con TOTP no se envía correo
    respuesta = enviar_codigo(c, totp_actual("lab_a", "admin@lab-a.test"))
    assert respuesta.headers["location"] == "/panel"
    assert "ADMINISTRADOR" in c.get("/panel").text


def test_codigo_totp_no_se_puede_reutilizar(buzon):
    autenticar(cliente(), "admin@lab-a.test", buzon)
    otro = cliente()
    enviar_clave(otro, "admin@lab-a.test")
    respuesta = enviar_codigo(otro, totp_actual("lab_a", "admin@lab-a.test"))
    assert respuesta.status_code == 400


def test_personal_con_totp_puede_usar_codigo_por_correo_como_respaldo(buzon):
    c = cliente()
    enviar_clave(c, "admin@lab-a.test")
    c.post("/verificar/reenviar", data={"csrf": csrf(c, "/verificar")})
    respuesta = enviar_codigo(c, codigo_en_buzon(buzon, "admin@lab-a.test"))
    assert respuesta.headers["location"] == "/panel"


def test_personal_sin_totp_debe_inscribirlo_antes_de_continuar(buzon):
    c = autenticar(cliente(), "nuevo@lab-a.test", buzon)
    assert c.get("/panel").headers["location"] == "/seguridad/totp"

    pagina = c.get("/seguridad/totp")
    assert pagina.status_code == 200
    secreto = pagina.text.split('class="secreto"')[1].split(">")[1].split("<")[0].strip()
    token = csrf(c, "/seguridad/totp")
    assert c.post("/seguridad/totp", data={"codigo": "000000", "csrf": token}).headers["location"] == (
        "/seguridad/totp?error=1"
    )

    import pyotp

    respuesta = c.post("/seguridad/totp", data={"codigo": pyotp.TOTP(secreto).now(), "csrf": token})
    assert respuesta.headers["location"] == "/panel"
    assert c.get("/panel").status_code == 200
    # Ya inscrito: la página de inscripción redirige al panel.
    assert c.get("/seguridad/totp").headers["location"] == "/panel"


# ------------------------------------------------------- credenciales y bloqueo


@pytest.mark.parametrize(
    ("email", "clave"),
    [
        ("paciente@lab-a.test", "Clave-equivocada-1"),
        ("no-existe@lab-a.test", CLAVE),
        ("admin@lab-b.test", CLAVE),  # existe, pero en otro laboratorio
        ("", ""),
    ],
)
def test_fallos_dan_el_mismo_mensaje_y_estado(email, clave):
    respuesta = enviar_clave(cliente(), email, clave)
    assert respuesta.status_code == 400
    assert ERROR_CREDENCIALES in respuesta.text
    assert "__Host-sesion" not in respuesta.headers.get("set-cookie", "")


@pytest.mark.parametrize("email", ["paciente@lab-a.test", "no-existe@lab-a.test"])
def test_bloqueo_tras_5_fallos_aunque_luego_la_clave_sea_correcta(email, buzon):
    c = cliente()
    for _ in range(5):
        assert enviar_clave(c, email, "Clave-equivocada-1").status_code == 400
    respuesta = enviar_clave(c, email, CLAVE)
    assert respuesta.status_code == 400
    assert ERROR_CREDENCIALES in respuesta.text  # el bloqueo no se distingue de una clave errada
    assert buzon == []


def test_bloqueo_queda_registrado(buzon):
    c = cliente()
    for _ in range(5):
        enviar_clave(c, "recepcion@lab-a.test", "Clave-equivocada-1")

    async def consultar(sesion):
        eventos = (
            await sesion.execute(
                text(
                    "SELECT e.tipo FROM lab.eventos_seguridad e JOIN lab.usuarios u ON u.id = e.usuario_id"
                    " WHERE u.email = 'recepcion@lab-a.test'"
                )
            )
        ).scalars()
        bloqueado = await sesion.scalar(
            text("SELECT bloqueado_hasta > now() FROM lab.usuarios WHERE email = 'recepcion@lab-a.test'")
        )
        return list(eventos), bloqueado

    import asyncio

    eventos, bloqueado = asyncio.run(ejecutar_en_tenant("app", "lab_a", consultar))
    assert eventos.count("INGRESO_FALLIDO") >= 5
    assert "CUENTA_BLOQUEADA" in eventos
    assert bloqueado is True


def test_limite_por_ip():
    c = cliente()
    for _ in range(100):
        c.post("/ingresar", data={"email": "x@y.test", "clave": "x", "csrf": csrf(c)})
    respuesta = enviar_clave(c, "paciente@lab-a.test")
    assert respuesta.status_code == 429


def test_tiempo_de_respuesta_no_revela_si_el_correo_existe():
    def mediana(email):
        tiempos = []
        for i in range(4):
            c = cliente()
            token = csrf(c)
            inicio = time.perf_counter()
            c.post(
                "/ingresar",
                data={
                    "email": f"{i}{email}" if "no-existe" in email else email,
                    "clave": "Clave-mala-1",
                    "csrf": token,
                },
            )
            tiempos.append(time.perf_counter() - inicio)
        return statistics.median(tiempos)

    existe, no_existe = mediana("paciente@lab-a.test"), mediana("no-existe@lab-a.test")
    # Ambos calculan un Argon2 completo; la diferencia debe ser pequeña frente a su costo.
    assert abs(existe - no_existe) < 0.5 * max(existe, no_existe)


def test_entradas_demasiado_largas_no_se_reflejan():
    c = cliente()
    clave_larga = "SECRETO-" + "x" * 2000
    respuesta = c.post("/ingresar", data={"email": "paciente@lab-a.test", "clave": clave_larga, "csrf": csrf(c)})
    assert respuesta.status_code == 400
    assert "SECRETO" not in respuesta.text


# ------------------------------------------------------------ segundo factor


def test_codigo_incorrecto_vencido_o_reutilizado(buzon):
    c = cliente()
    enviar_clave(c, "paciente@lab-a.test")
    codigo = codigo_en_buzon(buzon, "paciente@lab-a.test")
    otro = "000000" if codigo != "000000" else "111111"
    assert enviar_codigo(c, otro).status_code == 400

    async def vencer(sesion):
        await sesion.execute(text("UPDATE lab.codigos_verificacion SET expira_en = now() - interval '1 second'"))

    import asyncio

    asyncio.run(ejecutar_en_tenant("app", "lab_a", vencer))
    assert enviar_codigo(c, codigo).status_code == 400

    # Un código nuevo funciona una sola vez.
    c.post("/verificar/reenviar", data={"csrf": csrf(c, "/verificar")})
    nuevo = codigo_en_buzon(buzon, "paciente@lab-a.test")
    assert enviar_codigo(c, nuevo).status_code == 303
    otro_cliente = cliente()
    enviar_clave(otro_cliente, "paciente@lab-a.test")
    assert enviar_codigo(otro_cliente, nuevo).status_code == 400


def test_codigo_de_otro_usuario_no_sirve(buzon):
    a = cliente()
    enviar_clave(a, "paciente@lab-a.test")
    b = cliente()
    enviar_clave(b, "nuevo@lab-a.test")
    assert enviar_codigo(b, codigo_en_buzon(buzon, "paciente@lab-a.test")).status_code == 400


def test_maximo_de_intentos_del_segundo_factor(buzon):
    c = cliente()
    enviar_clave(c, "paciente@lab-a.test")
    codigo = codigo_en_buzon(buzon, "paciente@lab-a.test")
    for _ in range(5):
        enviar_codigo(c, "999999" if codigo != "999999" else "888888")
    assert enviar_codigo(c, codigo).status_code == 429


def test_maximo_de_codigos_por_hora(buzon):
    c = cliente()
    enviar_clave(c, "paciente@lab-a.test")  # 1
    for _ in range(4):  # 2..5
        assert c.post("/verificar/reenviar", data={"csrf": csrf(c, "/verificar")}).status_code == 200
    assert c.post("/verificar/reenviar", data={"csrf": csrf(c, "/verificar")}).status_code == 429
    assert len(buzon) == 5


# ------------------------------------------------------------------ sesiones


def _cookie_sesion(respuesta) -> str:
    return next(c for c in respuesta.headers.get_list("set-cookie") if c.startswith("__Host-sesion="))


def test_cookie_de_sesion_con_atributos_seguros(buzon):
    c = cliente()
    cookie = _cookie_sesion(enviar_clave(c, "paciente@lab-a.test")).lower()
    assert "secure" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "path=/" in cookie
    assert "domain=" not in cookie


def test_token_cambia_al_completar_el_ingreso_y_el_anterior_queda_revocado(buzon):
    c = cliente()
    c.cookies.set("__Host-sesion", "token-plantado-por-un-atacante", domain="lab-a.lablinea.localhost")
    pendiente = _cookie_sesion(enviar_clave(c, "paciente@lab-a.test")).split(";")[0].split("=", 1)[1]
    assert pendiente != "token-plantado-por-un-atacante"
    # Con solo la contraseña no se llega al panel.
    assert c.get("/panel").headers["location"] == "/verificar"

    final = enviar_codigo(c, codigo_en_buzon(buzon, "paciente@lab-a.test"))
    completo = _cookie_sesion(final).split(";")[0].split("=", 1)[1]
    assert completo != pendiente

    viejo = cliente()
    viejo.cookies.set("__Host-sesion", pendiente, domain="lab-a.lablinea.localhost")
    assert viejo.get("/panel").headers["location"] == "/ingresar"


def test_salir_invalida_la_sesion_en_el_servidor(buzon):
    c = autenticar(cliente(), "paciente@lab-a.test", buzon)
    token = c.cookies.get("__Host-sesion")
    assert c.post("/salir", data={"csrf": csrf(c, "/panel")}).headers["location"] == "/ingresar"
    copia = cliente()
    copia.cookies.set("__Host-sesion", token, domain="lab-a.lablinea.localhost")
    assert copia.get("/panel").headers["location"] == "/ingresar"


@pytest.mark.parametrize(
    "vencimiento",
    [
        "ultima_actividad = now() - interval '16 minutes'",  # inactividad
        "expira_en = now() - interval '1 second'",  # duración máxima
        "revocada_en = now()",
    ],
)
def test_sesion_vencida_o_revocada(vencimiento, buzon):
    c = autenticar(cliente(), "paciente@lab-a.test", buzon)
    assert c.get("/panel").status_code == 200

    async def vencer(sesion):
        await sesion.execute(text(f"UPDATE lab.sesiones SET {vencimiento}"))  # noqa: S608

    import asyncio

    asyncio.run(ejecutar_en_tenant("app", "lab_a", vencer))
    assert c.get("/panel").headers["location"] == "/ingresar"


def test_sesion_de_un_laboratorio_no_sirve_en_otro(buzon):
    a = autenticar(cliente("lab-a"), "paciente@lab-a.test", buzon)
    b = cliente("lab-b")
    b.cookies.set("__Host-sesion", a.cookies.get("__Host-sesion"), domain="lab-b.lablinea.localhost")
    assert b.get("/panel").headers["location"] == "/ingresar"


def test_mismo_correo_en_dos_laboratorios_son_cuentas_distintas(buzon):
    a = autenticar(cliente("lab-a"), "paciente@lab-a.test", buzon, "lab_a")
    b = autenticar(cliente("lab-b"), "paciente@lab-a.test", buzon, "lab_b")
    assert "Paciente A" in a.get("/panel").text
    assert "Paciente A en B" in b.get("/panel").text


def test_la_base_guarda_el_hash_del_token_no_el_token(buzon):
    c = autenticar(cliente(), "paciente@lab-a.test", buzon)
    token = c.cookies.get("__Host-sesion")

    async def hashes(sesion):
        return [bytes(h) for h in (await sesion.execute(text("SELECT token_hash FROM lab.sesiones"))).scalars()]

    import asyncio

    guardados = asyncio.run(ejecutar_en_tenant("app", "lab_a", hashes))
    assert all(len(h) == 32 for h in guardados)
    assert token.encode() not in guardados


def test_paginas_protegidas_redirigen_sin_sesion():
    c = cliente()
    for ruta in ("/panel", "/configuracion/usuarios", "/seguridad/totp"):
        assert c.get(ruta).headers["location"] == "/ingresar"
    assert c.get("/verificar").headers["location"] == "/ingresar"


def test_autenticacion_no_existe_en_el_dominio_base():
    """Ni laboratorio ni Admin Hub: el dominio base no tiene ingreso (el Admin Hub sí, desde la etapa 4)."""
    from fastapi.testclient import TestClient

    from app.main import app

    assert TestClient(app, base_url="https://lablinea.localhost").get("/ingresar").status_code == 404


def test_hash_con_parametros_viejos_se_actualiza_al_ingresar(buzon):
    import asyncio

    from argon2 import PasswordHasher

    debil = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1).hash(CLAVE)

    async def poner_hash(sesion):
        await sesion.execute(
            text("UPDATE lab.usuarios SET password_hash = :h WHERE email = 'paciente@lab-a.test'"), {"h": debil}
        )

    async def leer_hash(sesion):
        return await sesion.scalar(text("SELECT password_hash FROM lab.usuarios WHERE email = 'paciente@lab-a.test'"))

    asyncio.run(ejecutar_en_tenant("app", "lab_a", poner_hash))
    assert enviar_clave(cliente(), "paciente@lab-a.test").status_code == 303
    nuevo = asyncio.run(ejecutar_en_tenant("app", "lab_a", leer_hash))
    assert nuevo != debil
    assert not contrasenas.necesita_rehash(nuevo)
    assert contrasenas.verificar(nuevo, CLAVE)


def test_si_el_correo_falla_no_hay_error_500(monkeypatch, caplog):
    from app.core import correo

    def falla(_mensaje):
        raise ConnectionRefusedError("SMTP caído")

    monkeypatch.setattr(correo, "_enviar_sync", falla)
    c = cliente()
    respuesta = enviar_clave(c, "paciente@lab-a.test")
    assert respuesta.status_code == 303  # la contraseña es correcta; el código se podrá reenviar
    respuesta = c.post("/verificar/reenviar", data={"csrf": csrf(c, "/verificar")})
    assert respuesta.status_code == 503
    assert "No pudimos enviar el código" in respuesta.text
    assert "paciente@lab-a.test" not in caplog.text  # el log no expone el correo


@pytest.mark.parametrize("campo", ["email", "clave"])
def test_caracter_nulo_no_provoca_error_500(campo):
    """Regresión (fuzzing de la etapa 2): PostgreSQL no admite \\x00 en texto; antes daba 500."""
    c = cliente()
    datos = {"email": "admin@lab-a.test", "clave": CLAVE, "csrf": csrf(c)}
    datos[campo] += "\x00"
    respuesta = c.post("/ingresar", data=datos)
    assert respuesta.status_code == 400
