"""Usuarios del laboratorio e invitaciones (etapa 4; spec infraestructura/0008).

- Invitar crea el usuario sin contraseña; la tarea envía un enlace de un solo uso a su subdominio.
- El enlace no sirve en otro laboratorio, ni vencido, ni dos veces.
- El plan limita los usuarios activos. Desactivar revoca las sesiones.
"""

import re
import uuid

import pytest
from sqlalchemy import text

from app.auth import invitaciones
from app.core import tareas
from app.core.config import get_settings
from tests.ayudas import autenticar, cliente, csrf, enviar_clave
from tests.conftest import CLAVE, correr, ejecutar_en_plataforma, ejecutar_en_tenant


def _unico() -> str:
    return uuid.uuid4().hex[:8]


def _invitar(c, email: str, roles=("RECEPCION",), tipo="PERSONAL", nombre="Persona Invitada"):
    datos = {"email": email, "nombre": nombre, "tipo": tipo, "roles": list(roles)}
    return c.post("/configuracion/usuarios/nuevo", data={**datos, "csrf": csrf(c, "/configuracion/usuarios/nuevo")})


def _procesar_cola() -> None:
    async def todas():
        while await tareas.procesar_una():
            pass

    correr(todas())


def _token_de(buzon, email: str) -> tuple[str, str]:
    mensaje = next(m for m in reversed(buzon) if m["To"] == email)
    encontrado = re.search(r"(https://[^/\s]+)/activar/(\S+)", mensaje.get_content())
    return encontrado.group(1), encontrado.group(2)


def _activar(c, token: str, clave: str = CLAVE, confirmacion: str | None = None):
    datos = {"clave": clave, "confirmacion": clave if confirmacion is None else confirmacion}
    return c.post(f"/activar/{token}", data={**datos, "csrf": csrf(c, "/ingresar")})


def test_admin_invita_y_la_persona_activa_su_cuenta(buzon):
    email = f"nuevo-{_unico()}@lab-a.test"
    admin = autenticar(cliente(), "admin@lab-a.test", buzon)
    assert admin.get("/configuracion/usuarios/nuevo").status_code == 200
    respuesta = _invitar(admin, email)
    assert respuesta.status_code == 303
    lista = admin.get("/configuracion/usuarios").text
    assert email in lista and "Invitación pendiente" in lista

    _procesar_cola()
    base, token = _token_de(buzon, email)
    assert base == get_settings().url_sitio("lab-a")  # el enlace lleva a su propio laboratorio
    mensaje = next(m for m in reversed(buzon) if m["To"] == email)
    assert "Laboratorio A Sintético" in mensaje["Subject"]

    persona = cliente()
    assert persona.get(f"/activar/{token}").status_code == 200
    assert _activar(persona, token).status_code == 303
    assert persona.get(f"/activar/{token}").status_code == 404  # un solo uso
    assert "Ya puede ingresar" in cliente().get("/ingresar?activada=1").text
    # Ingresa; como es personal sin TOTP, recibe un código por correo y luego debe inscribir la app.
    assert enviar_clave(cliente(), email).status_code == 303


@pytest.mark.parametrize(
    ("clave", "confirmacion", "fragmento"),
    [
        ("corta", None, "al menos 12"),
        ("aaaaaaaaaaaaaa", None, "variedad"),
        (CLAVE, "Otra-Clave-Distinta-2026", "no coinciden"),
    ],
)
def test_activacion_exige_la_politica_de_contrasenas(buzon, clave, confirmacion, fragmento):
    email = f"politica-{_unico()}@lab-a.test"
    _invitar(autenticar(cliente(), "admin@lab-a.test", buzon), email)
    _procesar_cola()
    _, token = _token_de(buzon, email)
    respuesta = _activar(cliente(), token, clave, confirmacion)
    assert respuesta.status_code == 400 and fragmento in respuesta.text
    assert cliente().get(f"/activar/{token}").status_code == 200  # el enlace sigue vigente


def test_enlace_de_un_laboratorio_no_sirve_en_otro(buzon):
    email = f"cruce-{_unico()}@lab-a.test"
    _invitar(autenticar(cliente(), "admin@lab-a.test", buzon), email)
    _procesar_cola()
    _, token = _token_de(buzon, email)
    otro = cliente("lab-b")
    assert otro.get(f"/activar/{token}").status_code == 404
    assert _activar(otro, token).status_code == 404
    assert cliente().get(f"/activar/{token}").status_code == 200  # en su laboratorio sigue vigente


@pytest.mark.parametrize("token", ["x" * 43, "corto", "y" * 200])
def test_enlaces_inventados(token):
    c = cliente()
    assert c.get(f"/activar/{token}").status_code == 404
    assert _activar(c, token).status_code == 404


def test_enlace_vencido_y_reemplazado(buzon):
    email = f"vence-{_unico()}@lab-a.test"
    admin = autenticar(cliente(), "admin@lab-a.test", buzon)
    _invitar(admin, email)
    _procesar_cola()
    _, primero = _token_de(buzon, email)

    async def reinvitar_y_vencer(sesion):
        usuario = await sesion.scalar(text("SELECT uuid::text FROM lab.usuarios WHERE email = :e"), {"e": email})
        await tareas.encolar(sesion, invitaciones.TIPO_TAREA, {"usuario": usuario, "subdominio": "lab-a"})

    correr(ejecutar_en_tenant("app", "lab_a", reinvitar_y_vencer))
    _procesar_cola()
    _, segundo = _token_de(buzon, email)
    assert segundo != primero
    assert cliente().get(f"/activar/{primero}").status_code == 404  # la invitación nueva anula la anterior

    async def vencer(sesion):
        await sesion.execute(
            text(
                "UPDATE lab.invitaciones SET expira_en = now() - interval '1 minute'"
                " WHERE usuario_id = (SELECT id FROM lab.usuarios WHERE email = :e)"
            ),
            {"e": email},
        )

    correr(ejecutar_en_tenant("app", "lab_a", vencer))
    assert cliente().get(f"/activar/{segundo}").status_code == 404


@pytest.mark.anyio
async def test_tarea_de_invitacion_rechaza_datos_cruzados(engine_owner):
    """Una tarea de lab_a con el subdominio de lab-b (o un usuario ya activo) no envía nada y no se reintenta."""

    async def encolar_cruzadas(sesion):
        activo = await sesion.scalar(text("SELECT uuid::text FROM lab.usuarios WHERE email = 'admin@lab-a.test'"))
        a = await tareas.encolar(sesion, invitaciones.TIPO_TAREA, {"usuario": activo, "subdominio": "lab-b"})
        b = await tareas.encolar(sesion, invitaciones.TIPO_TAREA, {"usuario": activo, "subdominio": "lab-a"})
        return a, b

    cruzada, activa = await ejecutar_en_tenant("app", "lab_a", encolar_cruzadas)
    while await tareas.procesar_una():
        pass
    async with engine_owner.connect() as conexion:
        estados = dict(
            (
                await conexion.execute(
                    text("SELECT uuid::text, estado FROM cola.tareas WHERE uuid = ANY(CAST(:u AS uuid[]))"),
                    {"u": [cruzada, activa]},
                )
            ).all()
        )
    assert estados == {cruzada: "FALLIDA", activa: "FALLIDA"}


# --- Invitar: validaciones, autorización y límites ---


@pytest.mark.parametrize(
    ("datos", "fragmento"),
    [
        ({"email": "no-es-correo"}, "correo válido"),
        ({"nombre": "x"}, "nombre"),
        ({"tipo": "PACIENTE"}, "tipo de usuario"),
        ({"roles": ["NO_EXISTE"]}, "roles no existe"),
        ({"email": "recepcion@lab-a.test"}, "Ya existe"),
    ],
)
def test_invitar_valida_los_datos(buzon, datos, fragmento):
    admin = autenticar(cliente(), "admin@lab-a.test", buzon)
    base = {
        "email": f"valida-{_unico()}@lab-a.test",
        "nombre": "Persona Válida",
        "tipo": "PERSONAL",
        "roles": ["RECEPCION"],
    }
    base.update(datos)
    respuesta = admin.post(
        "/configuracion/usuarios/nuevo", data={**base, "csrf": csrf(admin, "/configuracion/usuarios/nuevo")}
    )
    assert respuesta.status_code == 400 and fragmento in respuesta.text


@pytest.mark.parametrize("email", ["recepcion@lab-a.test", "auditor@lab-a.test"])
def test_sin_permiso_de_crear_usuarios_403(buzon, email):
    c = autenticar(cliente(), email, buzon)
    assert c.get("/configuracion/usuarios/nuevo").status_code == 403


def test_limite_de_usuarios_del_plan(buzon):
    async def plan_con_limite(sesion):
        actuales = await sesion.scalar(
            text("SELECT count(*) FROM lab.usuarios WHERE estado = 'ACTIVO' AND tipo IN ('PERSONAL', 'MEDICO')")
        )
        return actuales

    actuales = correr(ejecutar_en_tenant("app", "lab_b", plan_con_limite))
    codigo = f"LIMITE_{_unico().upper()}"

    async def asignar(sesion):
        plan_id = await sesion.scalar(
            text(
                "INSERT INTO plataforma.planes (codigo, nombre, max_usuarios)"
                " VALUES (:c, 'Con límite', :m) RETURNING id"
            ),
            {"c": codigo, "m": actuales},
        )
        await sesion.execute(
            text("UPDATE plataforma.laboratorios SET plan_id = :p WHERE tenant_id = 'lab_b'"), {"p": plan_id}
        )

    async def restaurar(sesion):
        await sesion.execute(
            text(
                "UPDATE plataforma.laboratorios"
                " SET plan_id = (SELECT id FROM plataforma.planes WHERE codigo = 'COMPLETO') WHERE tenant_id = 'lab_b'"
            )
        )

    correr(ejecutar_en_plataforma(asignar))
    try:
        admin = autenticar(cliente("lab-b"), "admin@lab-b.test", buzon, laboratorio="lab_b")
        respuesta = admin.post(
            "/configuracion/usuarios/nuevo",
            data={
                "email": f"excede-{_unico()}@lab-b.test",
                "nombre": "Excede Límite",
                "tipo": "PERSONAL",
                "csrf": csrf(admin, "/configuracion/usuarios/nuevo"),
            },
        )
        assert respuesta.status_code == 400 and f"como máximo {actuales}" in respuesta.text
    finally:
        correr(ejecutar_en_plataforma(restaurar))


# --- Desactivar ---


def _uuid_de(tenant: str, email: str) -> str:
    async def leer(sesion):
        return await sesion.scalar(text("SELECT uuid::text FROM lab.usuarios WHERE email = :e"), {"e": email})

    return correr(ejecutar_en_tenant("app", tenant, leer))


def test_desactivar_revoca_sesiones_y_bloquea_el_ingreso(buzon):
    email = f"desact-{_unico()}@lab-a.test"
    admin = autenticar(cliente(), "admin@lab-a.test", buzon)
    _invitar(admin, email, roles=())
    _procesar_cola()
    _, token = _token_de(buzon, email)
    _activar(cliente(), token)
    persona = autenticar(cliente(), email, buzon)  # personal sin TOTP: código por correo, luego inscripción
    assert persona.get("/seguridad/totp").status_code == 200

    objetivo = _uuid_de("lab_a", email)
    respuesta = admin.post(
        f"/configuracion/usuarios/{objetivo}/desactivar", data={"csrf": csrf(admin, "/configuracion/usuarios")}
    )
    assert respuesta.status_code == 303
    assert persona.get("/seguridad/totp").status_code == 303  # sesión revocada
    assert enviar_clave(cliente(), email).status_code == 400
    # Desactivar de nuevo: ya no está activo.
    respuesta = admin.post(
        f"/configuracion/usuarios/{objetivo}/desactivar", data={"csrf": csrf(admin, "/configuracion/usuarios")}
    )
    assert respuesta.status_code == 404


def test_nadie_se_desactiva_a_si_mismo(buzon):
    admin = autenticar(cliente(), "admin@lab-a.test", buzon)
    propio = _uuid_de("lab_a", "admin@lab-a.test")
    respuesta = admin.post(
        f"/configuracion/usuarios/{propio}/desactivar", data={"csrf": csrf(admin, "/configuracion/usuarios")}
    )
    assert respuesta.status_code == 400


def test_no_se_desactiva_un_usuario_de_otro_laboratorio(buzon):
    """IDOR: el UUID de un usuario de lab-b no existe para lab-a (RLS) → 404, y sigue activo."""
    admin = autenticar(cliente(), "admin@lab-a.test", buzon)
    ajeno = _uuid_de("lab_b", "admin@lab-b.test")
    respuesta = admin.post(
        f"/configuracion/usuarios/{ajeno}/desactivar", data={"csrf": csrf(admin, "/configuracion/usuarios")}
    )
    assert respuesta.status_code == 404
    assert autenticar(cliente("lab-b"), "admin@lab-b.test", buzon, laboratorio="lab_b").get("/panel").status_code == 200


def test_auditor_no_desactiva(buzon):
    auditor = autenticar(cliente(), "auditor@lab-a.test", buzon)
    objetivo = _uuid_de("lab_a", "recepcion@lab-a.test")
    respuesta = auditor.post(
        f"/configuracion/usuarios/{objetivo}/desactivar", data={"csrf": csrf(auditor, "/configuracion/usuarios")}
    )
    assert respuesta.status_code == 403


def test_identificador_no_uuid_400(buzon):
    admin = autenticar(cliente(), "admin@lab-a.test", buzon)
    respuesta = admin.post(
        "/configuracion/usuarios/1/desactivar", data={"csrf": csrf(admin, "/configuracion/usuarios")}
    )
    assert respuesta.status_code == 400
