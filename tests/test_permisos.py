"""Autorización: roles, permisos por módulo y acciones especiales (spec infraestructura/0008)."""

import asyncio

import pytest
from fastapi import HTTPException, Request
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.auth import repositorio
from app.auth.repositorio import Permisos, Usuario
from app.auth.roles_sistema import ROLES
from app.auth.web import SesionActiva, requiere_accion, requiere_permiso
from app.core.tenancy import Laboratorio
from tests.ayudas import autenticar, cliente
from tests.conftest import USUARIOS, ejecutar_en_tenant

USUARIOS_POR_ROL = {roles[0]: email for lab, email, _, _, roles, _, _ in USUARIOS if lab == "lab_a" and roles}


@pytest.mark.parametrize("rol", sorted(USUARIOS_POR_ROL))
def test_permisos_cargados_coinciden_con_la_definicion_del_rol(rol):
    _, modulos, acciones = ROLES[rol]

    async def cargar(sesion):
        usuario = await repositorio.buscar_usuario_por_email(sesion, USUARIOS_POR_ROL[rol])
        return await repositorio.cargar_permisos(sesion, usuario.id)

    permisos = asyncio.run(ejecutar_en_tenant("app", "lab_a", cargar))
    assert permisos.roles == (rol,)
    assert permisos.modulos == {m: frozenset(ops) for m, ops in modulos.items()}
    assert permisos.acciones == frozenset(acciones)


@pytest.mark.parametrize(
    ("email", "estado"),
    [
        ("admin@lab-a.test", 200),
        ("auditor@lab-a.test", 200),
        ("recepcion@lab-a.test", 403),
        ("validador@lab-a.test", 403),
        ("paciente@lab-a.test", 403),
    ],
)
def test_lista_de_usuarios_segun_rol(email, estado, buzon):
    c = autenticar(cliente(), email, buzon)
    assert c.get("/configuracion/usuarios").status_code == estado


def test_lista_de_usuarios_solo_muestra_el_propio_laboratorio(buzon):
    pagina = autenticar(cliente(), "admin@lab-a.test", buzon).get("/configuracion/usuarios").text
    assert "admin@lab-a.test" in pagina
    assert "lab-b.test" not in pagina
    assert "Paciente A en B" not in pagina


def test_el_menu_solo_ofrece_lo_permitido(buzon):
    assert "/configuracion/usuarios" in autenticar(cliente(), "admin@lab-a.test", buzon).get("/panel").text
    assert "/configuracion/usuarios" not in autenticar(cliente(), "recepcion@lab-a.test", buzon).get("/panel").text


def _activa(roles=(), modulos=None, acciones=(), tarjeta=None) -> SesionActiva:
    usuario = Usuario(1, "u", "lab_a", "x@lab-a.test", "X", "PERSONAL", "$argon2id$", None, True, 0, tarjeta)
    return SesionActiva(1, usuario, Permisos(tuple(roles), modulos or {}, frozenset(acciones)), True)


LAB_A = Laboratorio("lab_a", "Laboratorio A Sintético", "COL", "ACTIVO", "America/Bogota", "es-CO", "COP")


def _peticion() -> Request:
    """Petición mínima del laboratorio A: la dependencia la usa para auditar el acceso denegado."""
    return Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1), "state": {"laboratorio": LAB_A}})


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("activa", "permitido"),
    [
        (_activa(acciones=("VALIDAR_RESULTADOS",), tarjeta="TP-1"), True),
        (_activa(acciones=("VALIDAR_RESULTADOS",), tarjeta=None), False),  # sin tarjeta profesional
        (_activa(acciones=("ABRIR_CAJA",), tarjeta="TP-1"), False),
        (_activa(), False),
    ],
)
async def test_validar_resultados_exige_accion_y_tarjeta_profesional(activa, permitido):
    dependencia = requiere_accion("VALIDAR_RESULTADOS")
    if permitido:
        assert await dependencia(_peticion(), LAB_A, activa) is activa
    else:
        with pytest.raises(HTTPException) as error:
            await dependencia(_peticion(), LAB_A, activa)
        assert error.value.status_code == 403


@pytest.mark.anyio
@pytest.mark.parametrize("operacion", ["consultar", "crear", "modificar", "eliminar"])
async def test_requiere_permiso_por_operacion(operacion):
    activa = _activa(modulos={"pacientes": frozenset({"consultar"})})
    dependencia = requiere_permiso("pacientes", operacion)
    if operacion == "consultar":
        assert await dependencia(_peticion(), LAB_A, activa) is activa
    else:
        with pytest.raises(HTTPException):
            await dependencia(_peticion(), LAB_A, activa)


@pytest.mark.anyio
async def test_otros_modulos_no_heredan_permisos():
    activa = _activa(modulos={"pacientes": frozenset({"consultar", "crear", "modificar", "eliminar"})})
    with pytest.raises(HTTPException):
        await requiere_permiso("resultados", "consultar")(_peticion(), LAB_A, activa)


# --- Eventos de seguridad: solo inserción ---


@pytest.mark.anyio
async def test_eventos_de_seguridad_no_se_modifican_ni_borran_con_el_rol_de_la_app(engine_app):
    for sentencia in ("UPDATE lab.eventos_seguridad SET tipo = 'X'", "DELETE FROM lab.eventos_seguridad"):
        with pytest.raises(DBAPIError, match="permission denied"):
            async with engine_app.begin() as conexion:
                await conexion.execute(text("SELECT set_config('app.current_tenant', 'lab_a', true)"))
                await conexion.execute(text(sentencia))


@pytest.mark.anyio
async def test_eventos_de_seguridad_bloqueados_por_trigger_incluso_para_el_dueno(engine_owner):
    async with engine_owner.begin() as conexion:
        await conexion.execute(text("SELECT set_config('app.current_tenant', 'lab_a', true)"))
        await conexion.execute(
            text("INSERT INTO lab.eventos_seguridad (tenant_id, tipo) VALUES ('lab_a', 'PRUEBA_INMUTABLE')")
        )
    for sentencia in (
        "UPDATE lab.eventos_seguridad SET tipo = 'X' WHERE tipo = 'PRUEBA_INMUTABLE'",
        "DELETE FROM lab.eventos_seguridad WHERE tipo = 'PRUEBA_INMUTABLE'",
    ):
        with pytest.raises(DBAPIError, match="solo inserción"):
            async with engine_owner.begin() as conexion:
                await conexion.execute(text("SELECT set_config('app.current_tenant', 'lab_a', true)"))
                await conexion.execute(text(sentencia))


@pytest.mark.anyio
async def test_usuarios_de_otro_laboratorio_invisibles_con_rls(engine_app):
    async with engine_app.begin() as conexion:
        await conexion.execute(text("SELECT set_config('app.current_tenant', 'lab_a', true)"))
        correos = (await conexion.execute(text("SELECT email::text FROM lab.usuarios"))).scalars().all()
        # Intento de insertar un usuario en otro laboratorio: WITH CHECK lo impide.
        with pytest.raises(DBAPIError, match="row-level security"):
            async with conexion.begin_nested():
                await conexion.execute(
                    text(
                        "INSERT INTO lab.usuarios (tenant_id, email, nombre, tipo, password_hash)"
                        " VALUES ('lab_b', 'intruso@lab-b.test', 'Intruso', 'PERSONAL', '$argon2id$x')"
                    )
                )
    # Solo correos de lab_a (personal @lab-a.test y pacientes sintéticos); ninguno exclusivo de lab_b.
    assert correos and all(c.endswith(("@lab-a.test", "@sintetico.test")) for c in correos)
    assert not {"admin@lab-b.test", "paciente@lab-b.test"} & set(correos)
