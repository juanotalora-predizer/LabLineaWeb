"""Admin Hub (etapa 4): usuarios de la plataforma, alta de laboratorios y planes.

Pruebas específicas del plan:
- El rol lablinea_plataforma no puede leer el esquema lab (SQL directo).
- Un usuario de la plataforma no puede iniciar sesión en el subdominio de un laboratorio, ni al revés.
- Un alta que falla a mitad no deja nada creado.
- Módulos no incluidos en el plan → 403 en el laboratorio.
"""

import re
import uuid

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.admin import servicios
from app.core import tareas
from app.core.tenancy import laboratorio_actual, sitio_actual, sitio_admin
from app.main import app
from tests.ayudas import autenticar, cliente, csrf, enviar_clave
from tests.conftest import CLAVE, correr, ejecutar_en_plataforma, ejecutar_en_tenant

MAESTRO = "maestro@plataforma.test"
COMERCIAL = "comercial@plataforma.test"
FINANCIERO = "financiero@plataforma.test"


def admin(email: str, buzon) -> object:
    return autenticar(cliente("admin"), email, buzon, laboratorio="plataforma")


def _unico() -> str:
    return uuid.uuid4().hex[:8]


def _plan_completo() -> str:
    async def leer(sesion):
        return await sesion.scalar(text("SELECT uuid::text FROM plataforma.planes WHERE codigo = 'COMPLETO'"))

    return correr(ejecutar_en_plataforma(leer))


def _datos_alta(sub: str, **cambios) -> dict:
    return {
        "nombre": f"Laboratorio {sub}",
        "subdominio": sub,
        "identificador_fiscal": "9" + str(uuid.uuid4().int)[:9],
        "pais": "COL",
        "plan": _plan_completo(),
        "sede": "Sede Principal",
        "ciudad": "Cali",
        "admin_email": f"jefe@{sub}.test",
        "admin_nombre": "Jefe de Laboratorio",
        **cambios,
    }


def _alta(c, datos: dict):
    return c.post("/laboratorios/nuevo", data={**datos, "csrf": csrf(c, "/laboratorios/nuevo")})


async def _contar_en_lab(tenant: str) -> dict:
    async def contar(sesion):
        return {
            tabla: await sesion.scalar(text(f"SELECT count(*) FROM lab.{tabla}"))  # noqa: S608 — nombres fijos
            for tabla in ("sedes", "roles", "usuarios", "usuario_roles")
        }

    return await ejecutar_en_tenant("owner", tenant, contar)


# --- Sitios separados ---


def _dependencias(dependant):
    for d in dependant.dependencies:
        yield d.call
        yield from _dependencias(d)


def test_toda_ruta_declara_su_sitio():
    """Guardián: cada ruta exige un laboratorio, el Admin Hub o un sitio válido (nunca cualquier host)."""
    publicas = {"/health", "/openapi.json"}
    sitios = {laboratorio_actual, sitio_admin, sitio_actual}
    sin_sitio = [
        r.path
        for r in app.routes
        if isinstance(r, APIRoute) and r.path not in publicas and not sitios & set(_dependencias(r.dependant))
    ]
    assert sin_sitio == []


@pytest.mark.parametrize("ruta", ["/laboratorios", "/planes", "/plataforma/usuarios", "/laboratorios/nuevo"])
def test_rutas_del_admin_hub_no_existen_en_un_laboratorio(buzon, ruta):
    c = autenticar(cliente(), "admin@lab-a.test", buzon)
    assert c.get(ruta).status_code == 404


@pytest.mark.parametrize("ruta", ["/configuracion/usuarios", "/configuracion/usuarios/nuevo"])
def test_rutas_del_laboratorio_no_existen_en_el_admin_hub(buzon, ruta):
    assert admin(MAESTRO, buzon).get(ruta).status_code == 404


def test_usuario_de_plataforma_no_ingresa_en_un_laboratorio():
    respuesta = enviar_clave(cliente(), MAESTRO)
    assert respuesta.status_code == 400  # no existe en lab-a: mismo mensaje genérico


def test_usuario_de_laboratorio_no_ingresa_en_el_admin_hub():
    respuesta = enviar_clave(cliente("admin"), "admin@lab-a.test")
    assert respuesta.status_code == 400


def test_sesion_de_plataforma_no_sirve_en_un_laboratorio_ni_al_reves(buzon):
    plataforma = admin(MAESTRO, buzon)
    laboratorio = autenticar(cliente(), "admin@lab-a.test", buzon)
    galleta_plataforma = plataforma.cookies.get("__Host-sesion")
    galleta_laboratorio = laboratorio.cookies.get("__Host-sesion")

    intruso = cliente()
    intruso.cookies.set("__Host-sesion", galleta_plataforma)
    assert intruso.get("/panel").status_code == 303
    intruso = cliente("admin")
    intruso.cookies.set("__Host-sesion", galleta_laboratorio)
    assert intruso.get("/panel").status_code == 303


def test_personal_de_plataforma_ingresa_con_totp_y_ve_su_menu(buzon):
    c = admin(MAESTRO, buzon)
    panel = c.get("/panel")
    assert panel.status_code == 200
    for enlace in ('href="/laboratorios"', 'href="/planes"', 'href="/plataforma/usuarios"'):
        assert enlace in panel.text
    assert 'href="/configuracion/usuarios"' not in panel.text


@pytest.mark.anyio
@pytest.mark.parametrize(
    "sentencia",
    ["SELECT count(*) FROM lab.usuarios", "SELECT count(*) FROM lab.auditoria", "SELECT lab.tenant_actual()"],
)
async def test_rol_de_plataforma_no_lee_el_esquema_lab(engine_plataforma, sentencia):
    with pytest.raises(DBAPIError, match="permission denied"):
        async with engine_plataforma.begin() as conexion:
            await conexion.execute(text(sentencia))


@pytest.mark.anyio
async def test_rol_de_plataforma_no_modifica_su_auditoria(engine_plataforma):
    for sentencia in (
        "UPDATE plataforma.auditoria SET tabla = 'x'",
        "DELETE FROM plataforma.auditoria",
        "INSERT INTO plataforma.auditoria (tabla, operacion) VALUES ('x', 'READ')",
    ):
        with pytest.raises(DBAPIError, match="permission denied"):
            async with engine_plataforma.begin() as conexion:
                await conexion.execute(text(sentencia))


# --- Autorización ---


@pytest.mark.parametrize(
    ("email", "ruta", "esperado"),
    [
        (MAESTRO, "/laboratorios/nuevo", 200),
        (COMERCIAL, "/laboratorios/nuevo", 200),
        (FINANCIERO, "/laboratorios/nuevo", 403),
        (FINANCIERO, "/laboratorios", 200),
        (MAESTRO, "/planes/nuevo", 200),
        (COMERCIAL, "/planes/nuevo", 403),
        (COMERCIAL, "/planes", 200),
        (FINANCIERO, "/planes", 403),
        (MAESTRO, "/plataforma/usuarios", 200),
        (COMERCIAL, "/plataforma/usuarios", 403),
    ],
)
def test_permisos_de_los_roles_de_plataforma(buzon, email, ruta, esperado):
    assert admin(email, buzon).get(ruta).status_code == esperado


def test_acceso_denegado_y_lecturas_quedan_en_la_auditoria_de_la_plataforma(buzon):
    admin(FINANCIERO, buzon).get("/plataforma/usuarios")
    admin(MAESTRO, buzon).get("/plataforma/usuarios")

    async def leer(sesion):
        return (
            (
                await sesion.execute(
                    text(
                        "SELECT a.operacion, a.resultado, a.usuario_id FROM plataforma.auditoria a"
                        " WHERE a.tabla IN ('modulo:usuarios', 'usuarios') AND a.operacion IN ('ACCESO', 'READ')"
                        " ORDER BY a.id DESC LIMIT 2"
                    )
                )
            )
            .mappings()
            .all()
        )

    lectura, denegado = correr(ejecutar_en_plataforma(leer))
    assert (denegado["operacion"], denegado["resultado"]) == ("ACCESO", "DENEGADO")
    assert (lectura["operacion"], lectura["resultado"]) == ("READ", "EXITO")
    assert lectura["usuario_id"].startswith("plataforma:")


# --- Alta de laboratorios ---


def test_alta_crea_laboratorio_sede_roles_y_administrador_pendiente(buzon):
    sub = f"alta-{_unico()}"
    c = admin(COMERCIAL, buzon)
    respuesta = _alta(c, _datos_alta(sub))
    assert respuesta.status_code == 303 and respuesta.headers["location"].startswith("/laboratorios/")
    detalle = c.get(respuesta.headers["location"])
    assert detalle.status_code == 200 and sub in detalle.text

    tenant = "lab_" + sub.replace("-", "_")
    conteos = correr(_contar_en_lab(tenant))
    assert conteos["sedes"] == 1 and conteos["usuarios"] == 1 and conteos["usuario_roles"] == 1
    assert conteos["roles"] >= 6

    async def admin_y_auditoria(sesion):
        usuario = (
            await sesion.execute(
                text("SELECT tipo, password_hash FROM lab.usuarios WHERE email = :e"), {"e": f"jefe@{sub}.test"}
            )
        ).one()
        autor = await sesion.scalar(
            text("SELECT usuario_id FROM lab.auditoria WHERE tabla = 'usuarios' AND operacion = 'INSERT'")
        )
        return usuario, autor

    usuario, autor = correr(ejecutar_en_tenant("owner", tenant, admin_y_auditoria))
    assert usuario.tipo == "PERSONAL" and usuario.password_hash is None  # la plataforma no conoce la contraseña
    assert autor.startswith("plataforma:")  # la auditoría del laboratorio registra quién lo creó

    # Del nuevo laboratorio responde su subdominio.
    assert cliente(sub).get("/").status_code == 200


def test_alta_que_falla_a_mitad_no_deja_nada(buzon):
    """Correo del administrador inválido para la base (CHECK de lab.usuarios): falla después de crear
    el laboratorio, la sede y los roles dentro de la función; todo se revierte."""
    sub = f"falla-{_unico()}"
    datos = servicios.DatosAlta(**{**_datos_alta(sub), "admin_email": "sin-arroba-valida@x.y"})

    async def alta_con_correo_roto(sesion):
        # Se salta la validación de Python para que el fallo ocurra dentro de la transacción de la base.
        await sesion.execute(
            text(
                "SELECT plataforma.alta_laboratorio(:t, :s, :n, :nit, 'COL', CAST(:p AS uuid), 'Sede', 'Cali',"
                " 'correo invalido', 'Jefe', CAST(:r AS jsonb), 'DEMO')"
            ),
            {
                "t": datos.tenant_id,
                "s": datos.subdominio,
                "n": datos.nombre,
                "nit": datos.identificador_fiscal,
                "p": datos.plan,
                "r": servicios.roles_iniciales(),
            },
        )

    with pytest.raises(DBAPIError, match="check"):
        correr(ejecutar_en_plataforma(alta_con_correo_roto))

    async def existe(sesion):
        return await sesion.scalar(
            text("SELECT count(*) FROM plataforma.laboratorios WHERE subdominio = :s"), {"s": sub}
        )

    assert correr(ejecutar_en_plataforma(existe)) == 0
    assert set(correr(_contar_en_lab(datos.tenant_id)).values()) == {0}
    assert cliente(sub).get("/").status_code == 404


@pytest.mark.parametrize(
    ("cambio", "fragmento"),
    [
        ({"subdominio": "admin"}, "No se pudo crear"),  # reservado (CHECK de la base)
        ({"subdominio": "-malo"}, "subdominio"),
        ({"subdominio": "a"}, "subdominio"),
        ({"identificador_fiscal": "1"}, "identificador fiscal"),
        ({"admin_email": "no-es-correo"}, "administrador"),
        ({"pais": "ARG"}, "No se pudo crear"),  # país no habilitado
        ({"plan": str(uuid.uuid4())}, "No se pudo crear"),  # plan inexistente
        ({"plan": "no-es-uuid"}, "No se pudo crear"),
        ({"nombre": "<script>alert(1)</script>"}, None),  # se acepta como texto y se escapa al mostrar
    ],
)
def test_alta_valida_los_datos(buzon, cambio, fragmento):
    c = admin(MAESTRO, buzon)
    sub = f"val-{_unico()}"
    respuesta = _alta(c, _datos_alta(sub, **cambio))
    if fragmento is None:
        assert respuesta.status_code == 303
        assert "<script>" not in c.get("/laboratorios").text
    else:
        assert respuesta.status_code == 400
        assert fragmento in respuesta.text


def test_alta_con_subdominio_repetido(buzon):
    c = admin(MAESTRO, buzon)
    respuesta = _alta(c, _datos_alta("lab-a"))
    assert respuesta.status_code == 400 and "Ya existe" in respuesta.text


# --- Invitación del administrador del nuevo laboratorio ---


@pytest.mark.anyio
async def test_invitacion_llega_y_el_administrador_activa_su_cuenta(engine_owner, buzon):
    sub = f"inv-{_unico()}"
    c = admin(MAESTRO, buzon)
    assert _alta(c, _datos_alta(sub)).status_code == 303
    while await tareas.procesar_una():  # también las invitaciones de otras pruebas
        pass
    correo = next(m for m in buzon if m["To"] == f"jefe@{sub}.test")
    cuerpo = correo.get_content()
    assert "Laboratorio " + sub in correo["Subject"]
    enlace = re.search(r"https://\S+/activar/(\S+)", cuerpo)
    assert enlace and f"https://{sub}.lablinea.localhost" in cuerpo
    token = enlace.group(1)

    nuevo = cliente(sub)
    formulario = nuevo.get(f"/activar/{token}")
    assert formulario.status_code == 200
    respuesta = nuevo.post(
        f"/activar/{token}", data={"clave": CLAVE, "confirmacion": CLAVE, "csrf": csrf(nuevo, f"/activar/{token}")}
    )
    assert respuesta.status_code == 303 and respuesta.headers["location"] == "/ingresar?activada=1"
    # El enlace no sirve una segunda vez.
    assert nuevo.get(f"/activar/{token}").status_code == 404
    # Ya puede ingresar con su contraseña (y luego el segundo factor por correo, porque aún no tiene TOTP).
    assert enviar_clave(cliente(sub), f"jefe@{sub}.test").status_code == 303


def test_reenviar_invitacion(buzon):
    sub = f"reenv-{_unico()}"
    c = admin(MAESTRO, buzon)
    ubicacion = _alta(c, _datos_alta(sub)).headers["location"]
    respuesta = c.post(f"{ubicacion}/invitacion", data={"csrf": csrf(c, ubicacion)})
    assert respuesta.headers["location"].endswith("?aviso=invitacion")
    # Un laboratorio sin administrador pendiente (lab-a) no acepta reenvío.
    lab_a = correr(ejecutar_en_plataforma(_uuid_de("lab_a")))
    respuesta = c.post(f"/laboratorios/{lab_a}/invitacion", data={"csrf": csrf(c, ubicacion)})
    assert respuesta.headers["location"].endswith("?error=invitacion")


def _uuid_de(tenant: str):
    async def leer(sesion):
        return await sesion.scalar(
            text("SELECT uuid::text FROM plataforma.laboratorios WHERE tenant_id = :t"), {"t": tenant}
        )

    return leer


def test_laboratorio_inexistente_404(buzon):
    c = admin(MAESTRO, buzon)
    assert c.get(f"/laboratorios/{uuid.uuid4()}").status_code == 404
    assert c.get("/laboratorios/1").status_code == 400  # identificadores no secuenciales: solo UUID


# --- Planes y módulos ---


def _crear_plan(c, codigo: str, modulos: list[str], max_usuarios: str = "") -> str:
    respuesta = c.post(
        "/planes/nuevo",
        data={
            "codigo": codigo,
            "nombre": f"Plan {codigo}",
            "max_usuarios": max_usuarios,
            "modulos": modulos,
            "csrf": csrf(c, "/planes/nuevo"),
        },
    )
    assert respuesta.status_code == 303, respuesta.text
    return respuesta.headers["location"].rsplit("/", 1)[1]


def _cambiar_plan_de(tenant: str, plan_uuid: str, c) -> None:
    lab = correr(ejecutar_en_plataforma(_uuid_de(tenant)))
    respuesta = c.post(f"/laboratorios/{lab}/plan", data={"plan": plan_uuid, "csrf": csrf(c, f"/laboratorios/{lab}")})
    assert respuesta.status_code == 303


@pytest.fixture
def plan_original(buzon):
    """Devuelve lab_a a su plan completo al terminar."""
    yield
    _cambiar_plan_de("lab_a", _plan_completo(), admin(MAESTRO, buzon))


def test_modulo_fuera_del_plan_da_403_y_sale_del_menu(buzon, plan_original):
    c = admin(MAESTRO, buzon)
    plan = _crear_plan(
        c, f"SIN_REPORTES_{_unico().upper()}", ["pacientes", "ordenes", "caja", "muestras", "resultados"]
    )
    _cambiar_plan_de("lab_a", plan, c)

    lab = autenticar(cliente(), "admin@lab-a.test", buzon)
    panel = lab.get("/panel").text
    assert "reportes" not in panel and "pacientes" in panel
    # usuarios y configuración son siempre activos.
    assert lab.get("/configuracion/usuarios").status_code == 200

    # Sin "usuarios" en el plan no se puede quitar: es siempre activo; probamos un módulo del plan.
    plan_minimo = _crear_plan(c, f"MINIMO_{_unico().upper()}", [])
    _cambiar_plan_de("lab_a", plan_minimo, c)
    lab = autenticar(cliente(), "admin@lab-a.test", buzon)
    panel = lab.get("/panel").text
    assert "pacientes" not in panel and "usuarios" in panel


@pytest.mark.anyio
async def test_requiere_permiso_niega_modulo_fuera_del_plan(engine_app):
    from fastapi import HTTPException, Request

    from app.auth.repositorio import Permisos, Usuario
    from app.auth.web import SesionActiva, _limitar_al_plan, requiere_permiso
    from app.core.tenancy import Laboratorio

    lab = Laboratorio(
        "lab_a", "Lab A", "COL", "ACTIVO", "America/Bogota", "es-CO", "COP", "lab-a", frozenset({"usuarios"})
    )
    usuario = Usuario(1, "u", "lab_a", "x@lab-a.test", "X", "PERSONAL", "$argon2id$", None, True, 0, None)
    permisos = _limitar_al_plan(Permisos(("ADMINISTRADOR",), {"pacientes": frozenset({"consultar"})}), lab)
    activa = SesionActiva(1, usuario, permisos, True)
    peticion = Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1), "state": {"laboratorio": lab}})
    with pytest.raises(HTTPException) as error:
        await requiere_permiso("pacientes", "consultar")(peticion, lab, activa)
    assert error.value.status_code == 403


def test_editar_plan_y_validaciones(buzon):
    c = admin(MAESTRO, buzon)
    codigo = f"EDIT_{_unico().upper()}"
    plan = _crear_plan(c, codigo, ["pacientes"], "5")
    pagina = c.get(f"/planes/{plan}")
    assert pagina.status_code == 200 and codigo in pagina.text
    respuesta = c.post(
        f"/planes/{plan}",
        data={
            "nombre": "Plan Editado",
            "max_usuarios": "10",
            "activo": "si",
            "modulos": ["pacientes", "reportes"],
            "csrf": csrf(c, f"/planes/{plan}"),
        },
    )
    assert respuesta.status_code == 303
    assert "Plan Editado" in c.get("/planes").text
    for datos in (
        {"nombre": "x"},
        {"nombre": "Válido", "max_usuarios": "cero"},
        {"nombre": "Válido", "modulos": ["a", "a"]},
    ):
        respuesta = c.post(f"/planes/{plan}", data={**datos, "csrf": csrf(c, f"/planes/{plan}")})
        assert respuesta.status_code == 400
    # Código repetido y código inválido.
    for nuevo in (codigo, "1MAL"):
        respuesta = c.post("/planes/nuevo", data={"codigo": nuevo, "nombre": "Otro", "csrf": csrf(c, "/planes/nuevo")})
        assert respuesta.status_code == 400
    assert c.get(f"/planes/{uuid.uuid4()}").status_code == 404
    assert c.post(f"/planes/{uuid.uuid4()}", data={"nombre": "Xx", "csrf": csrf(c, "/planes")}).status_code == 404


def test_cambiar_plan_a_inexistente_404(buzon):
    c = admin(MAESTRO, buzon)
    lab = correr(ejecutar_en_plataforma(_uuid_de("lab_b")))
    respuesta = c.post(f"/laboratorios/{lab}/plan", data={"plan": str(uuid.uuid4()), "csrf": csrf(c, "/laboratorios")})
    assert respuesta.status_code == 404
    respuesta = c.post(f"/laboratorios/{lab}/plan", data={"plan": "x", "csrf": csrf(c, "/laboratorios")})
    assert respuesta.status_code == 400


@pytest.mark.parametrize("maximo", ["²", "٣", "１"])
def test_regresion_digitos_unicode_en_el_maximo_de_usuarios(buzon, maximo):
    c = admin(MAESTRO, buzon)
    respuesta = c.post(
        "/planes/nuevo",
        data={
            "codigo": f"UNI_{_unico().upper()}",
            "nombre": "Plan Unicode",
            "max_usuarios": maximo,
            "csrf": csrf(c, "/planes/nuevo"),
        },
    )
    assert respuesta.status_code == 400
