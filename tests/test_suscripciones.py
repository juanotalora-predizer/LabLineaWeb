"""Ciclo de la suscripción (etapa 5; spec funcional/0005, sección 3).

- El estado efectivo vence en el instante del fin, aunque el trabajador aún no lo haya marcado.
- Una suscripción vencida o suspendida bloquea crear órdenes nuevas (dependencia `SuscripcionVigente`),
  pero NO la consulta: el personal y los pacientes siguen entrando y consultando.
- El trabajador marca las vencidas, encola los avisos de renovación (una vez por umbral) y factura la
  renovación automática.
"""

import asyncio
import re

import pytest
from fastapi import HTTPException, Request
from sqlalchemy import text

from app.admin import facturacion
from app.auth.repositorio import Permisos, Usuario
from app.auth.web import SesionActiva, requiere_suscripcion_vigente
from app.core import tareas
from app.core.tenancy import buscar_laboratorio
from tests.ayudas import autenticar, cliente, cliente_admin, csrf, nuevo_laboratorio
from tests.conftest import correr, ejecutar_en_plataforma

MAESTRO = "maestro@plataforma.test"
COMERCIAL = "comercial@plataforma.test"


def _ajustar(lab_uuid: str, sentencia: str, **parametros) -> None:
    async def ajustar(sesion):
        await sesion.execute(
            text(
                f"UPDATE plataforma.suscripciones SET {sentencia} WHERE laboratorio_id ="  # noqa: S608 — fijas
                " (SELECT id FROM plataforma.laboratorios WHERE uuid = :lab)"
            ),
            {"lab": lab_uuid, **parametros},
        )

    correr(ejecutar_en_plataforma(ajustar))


def _suscripcion(lab_uuid: str) -> dict:
    async def leer(sesion):
        return dict(
            (
                await sesion.execute(
                    text(
                        "SELECT s.tipo_licencia, s.estado, s.fin, s.fin - now() AS restante, s.renovacion_automatica"
                        " FROM plataforma.suscripciones s JOIN plataforma.laboratorios l ON l.id = s.laboratorio_id"
                        " WHERE l.uuid = :l"
                    ),
                    {"l": lab_uuid},
                )
            )
            .mappings()
            .one()
        )

    return correr(ejecutar_en_plataforma(leer))


# --- Alta y licencias ---


@pytest.mark.parametrize(
    ("licencia", "dias", "max_usuarios"), [("DEMO", 30, 3), ("MENSUAL", 7, None), ("AD_HONOREM", None, None)]
)
def test_suscripcion_inicial_segun_la_licencia(licencia, dias, max_usuarios):
    lab = nuevo_laboratorio(licencia)
    s = _suscripcion(lab["uuid"])
    assert (s["tipo_licencia"], s["estado"]) == (licencia, "ACTIVA")
    if dias is None:
        assert s["fin"] is None
    else:
        assert abs(s["restante"].days - dias) <= 1
    resuelto = correr(buscar_laboratorio(lab["subdominio"]))
    assert resuelto.suscripcion_vigente and resuelto.max_usuarios == max_usuarios  # el menor entre plan y licencia


def test_licencia_invalida_en_el_alta(buzon):
    c = cliente_admin(MAESTRO, buzon)
    datos = {
        "nombre": "Laboratorio Licencia",
        "subdominio": "lic-" + __import__("uuid").uuid4().hex[:6],
        "identificador_fiscal": "9" + str(__import__("uuid").uuid4().int)[:9],
        "pais": "COL",
        "plan": re.search(r'name="plan"><option value="([0-9a-f-]{36})"', c.get("/laboratorios/nuevo").text).group(1),
        "sede": "Sede",
        "ciudad": "Cali",
        "admin_email": "jefe@lic.test",
        "admin_nombre": "Jefe",
        "tipo_licencia": "VITALICIA",
    }
    respuesta = c.post("/laboratorios/nuevo", data={**datos, "csrf": csrf(c, "/laboratorios/nuevo")})
    assert respuesta.status_code == 400


# --- Estado efectivo y bloqueo ---


def test_vence_en_el_instante_aunque_no_se_haya_marcado():
    lab = nuevo_laboratorio("DEMO")
    _ajustar(lab["uuid"], "inicio = now() - interval '31 days', fin = now() - interval '1 second'")
    assert _suscripcion(lab["uuid"])["estado"] == "ACTIVA"  # el trabajador aún no pasó
    resuelto = correr(buscar_laboratorio(lab["subdominio"]))
    assert resuelto.suscripcion_estado == "VENCIDA" and not resuelto.suscripcion_vigente


def _peticion(laboratorio) -> Request:
    return Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1), "state": {"laboratorio": laboratorio}})


@pytest.mark.anyio
@pytest.mark.parametrize("estado", ["VENCIDA", "SUSPENDIDA", "CANCELADA", "SIN_SUSCRIPCION"])
async def test_sin_suscripcion_vigente_no_se_crean_ordenes(engine_app, estado):
    from app.core.tenancy import Laboratorio

    lab = Laboratorio("lab_a", "Lab A", "COL", "ACTIVO", "America/Bogota", "es-CO", "COP", suscripcion_estado=estado)
    usuario = Usuario(1, "u", "lab_a", "x@lab-a.test", "X", "PERSONAL", "$argon2id$", None, True, 0, None)
    activa = SesionActiva(1, usuario, Permisos(("RECEPCION",), {"ordenes": frozenset({"crear"})}), True)
    with pytest.raises(HTTPException) as error:
        await requiere_suscripcion_vigente(_peticion(lab), lab, activa)
    assert error.value.status_code == 403
    vigente = Laboratorio("lab_a", "Lab A", "COL", "ACTIVO", "America/Bogota", "es-CO", "COP")
    assert await requiere_suscripcion_vigente(_peticion(vigente), vigente, activa) is None


@pytest.fixture
def lab_a_vencido():
    """lab_a con la suscripción vencida durante la prueba."""

    async def lab_a(sesion):
        return await sesion.scalar(text("SELECT uuid::text FROM plataforma.laboratorios WHERE tenant_id = 'lab_a'"))

    uuid_a = correr(ejecutar_en_plataforma(lab_a))
    _ajustar(uuid_a, "tipo_licencia = 'MENSUAL', inicio = now() - interval '40 days', fin = now() - interval '1 day'")
    yield uuid_a
    _ajustar(uuid_a, "tipo_licencia = 'AD_HONOREM', estado = 'ACTIVA', fin = NULL, motivo_suspension = NULL")


def test_vencida_no_bloquea_la_consulta(buzon, lab_a_vencido):
    """El personal y los pacientes siguen ingresando y consultando; solo ven el aviso."""
    admin = autenticar(cliente(), "admin@lab-a.test", buzon)
    panel = admin.get("/panel")
    assert panel.status_code == 200 and "está vencida" in panel.text
    assert admin.get("/configuracion/usuarios").status_code == 200
    paciente = autenticar(cliente(), "paciente@lab-a.test", buzon)
    assert paciente.get("/panel").status_code == 200


def test_laboratorio_al_dia_no_ve_el_aviso(buzon):
    assert "franja alerta" not in autenticar(cliente(), "admin@lab-a.test", buzon).get("/panel").text


# --- Mantenimiento: vencer y avisar ---


def test_mantenimiento_vence_y_avisa_una_vez_por_umbral(buzon):
    vence = nuevo_laboratorio("MENSUAL")  # fin en 7 días (gracia)
    _ajustar(vence["uuid"], "fin = now() + interval '20 hours'")
    vencida = nuevo_laboratorio("DEMO")
    _ajustar(vencida["uuid"], "inicio = now() - interval '31 days', fin = now() - interval '1 minute'")

    async def mantener(sesion):
        return await sesion.scalar(text("SELECT plataforma.mantener_suscripciones()"))

    correr(ejecutar_en_plataforma(mantener))
    correr(ejecutar_en_plataforma(mantener))  # segunda vez: no duplica avisos (clave única)
    assert _suscripcion(vencida["uuid"])["estado"] == "VENCIDA"

    async def avisos(sesion):
        return await sesion.scalar(
            text("SELECT count(*) FROM cola.tareas WHERE tipo = 'suscripcion.aviso' AND datos->>'subdominio' = :s"),
            {"s": vence["subdominio"]},
        )

    async def contar():
        from tests.conftest import engine_de

        owner = engine_de("owner")
        async with owner.connect() as conexion:
            total = await avisos(conexion)
        await owner.dispose()
        return total

    assert correr(contar()) == 1


@pytest.mark.anyio
async def test_aviso_de_renovacion_llega_a_los_administradores_activos(buzon):
    lab = await asyncio.to_thread(nuevo_laboratorio, "MENSUAL")
    # El administrador invitado aún no tiene contraseña: no recibe avisos. Se le asigna una.
    from app.auth import contrasenas
    from tests.conftest import CLAVE, ejecutar_en_tenant

    async def activar(sesion):
        await sesion.execute(text("UPDATE lab.usuarios SET password_hash = :h"), {"h": contrasenas.hashear(CLAVE)})
        await tareas.encolar(
            sesion,
            "suscripcion.aviso",
            {"subdominio": lab["subdominio"], "dias": 7, "fin": "2026-12-31T05:00:00Z"},
        )

    await ejecutar_en_tenant("app", lab["tenant"], activar)
    while await tareas.procesar_una():
        pass
    mensaje = next(m for m in buzon if m["To"] == f"jefe@{lab['subdominio']}.test" and "vence" in m["Subject"])
    cuerpo = mensaje.get_content()
    assert "31/12/2026" in cuerpo  # 05:00 UTC = 00:00 en Bogotá: la fecha local del laboratorio
    assert lab["subdominio"] in mensaje["Subject"]


@pytest.mark.anyio
async def test_aviso_con_datos_cruzados_no_se_envia(buzon, engine_owner):
    from tests.conftest import ejecutar_en_tenant

    async def encolar(sesion):
        a = await tareas.encolar(sesion, "suscripcion.aviso", {"subdominio": "lab-b", "dias": 7, "fin": "2026-12-31"})
        b = await tareas.encolar(sesion, "suscripcion.aviso", {"subdominio": "lab-a", "dias": 7, "fin": "no-es-fecha"})
        return a, b

    uuids = await ejecutar_en_tenant("app", "lab_a", encolar)
    while await tareas.procesar_una():
        pass
    async with engine_owner.connect() as conexion:
        estados = (
            (
                await conexion.execute(
                    text("SELECT estado FROM cola.tareas WHERE uuid = ANY(CAST(:u AS uuid[]))"), {"u": list(uuids)}
                )
            )
            .scalars()
            .all()
        )
    assert estados == ["FALLIDA", "FALLIDA"]
    assert not [m for m in buzon if "vence" in (m["Subject"] or "")]


@pytest.mark.anyio
async def test_renovacion_automatica_factura_una_sola_vez(engine_owner):
    lab = await asyncio.to_thread(nuevo_laboratorio, "MENSUAL")

    async def precio(sesion):
        await sesion.execute(
            text(
                "INSERT INTO plataforma.precios (pais, plan_id, tipo_licencia, moneda, valor, vigente_desde)"
                " SELECT 'COL', id, 'MENSUAL', 'COP', 100000, DATE '2026-01-01' FROM plataforma.planes"
                " WHERE codigo = 'COMPLETO' ON CONFLICT DO NOTHING"
            )
        )

    await ejecutar_en_plataforma(precio)
    await asyncio.to_thread(_ajustar, lab["uuid"], "renovacion_automatica = true")
    await facturacion.mantener_suscripciones()
    await facturacion.mantener_suscripciones()
    from app.core import db

    await db.cerrar()
    async with engine_owner.connect() as conexion:
        facturas = await conexion.scalar(
            text(
                "SELECT count(*) FROM plataforma.facturas f JOIN plataforma.laboratorios l ON l.id = f.laboratorio_id"
                " WHERE l.uuid = :l AND f.estado <> 'ANULADA'"
            ),
            {"l": lab["uuid"]},
        )
    assert facturas == 1


@pytest.mark.anyio
async def test_un_mantenimiento_que_falla_no_detiene_los_demas(monkeypatch, caplog):
    llamados = []

    async def falla():
        raise RuntimeError("Datos internos que no deben salir al log")

    async def funciona():
        llamados.append(True)

    monkeypatch.setattr(tareas, "MANTENIMIENTOS", [falla, funciona])
    with caplog.at_level("WARNING"):
        await tareas.mantener()
    assert llamados == [True]
    assert "RuntimeError" in caplog.text and "Datos internos" not in caplog.text


# --- Acciones del Admin Hub ---


def _accion(c, lab_uuid: str, accion: str, **datos):
    return c.post(
        f"/laboratorios/{lab_uuid}/suscripcion",
        data={"accion": accion, **datos, "csrf": csrf(c, f"/laboratorios/{lab_uuid}")},
    )


def test_suspender_reactivar_y_cancelar(buzon):
    lab = nuevo_laboratorio("DEMO")
    c = cliente_admin(COMERCIAL, buzon)
    assert _accion(c, lab["uuid"], "suspender", motivo="x").headers["location"].endswith("?error=motivo")
    assert (
        _accion(c, lab["uuid"], "suspender", motivo="Falta de pago").headers["location"].endswith("?aviso=suscripcion")
    )
    assert _suscripcion(lab["uuid"])["estado"] == "SUSPENDIDA"
    assert not correr(buscar_laboratorio(lab["subdominio"])).suscripcion_vigente
    assert "Falta de pago" in c.get(f"/laboratorios/{lab['uuid']}").text
    assert _accion(c, lab["uuid"], "reactivar").headers["location"].endswith("?aviso=suscripcion")
    assert _accion(c, lab["uuid"], "reactivar").headers["location"].endswith("?error=suscripcion")  # ya activa
    assert _accion(c, lab["uuid"], "renovacion_si").status_code == 303
    assert _suscripcion(lab["uuid"])["renovacion_automatica"] is True
    assert _accion(c, lab["uuid"], "renovacion_no").status_code == 303
    assert _accion(c, lab["uuid"], "licencia", tipo_licencia="AD_HONOREM").status_code == 303
    assert _suscripcion(lab["uuid"])["tipo_licencia"] == "AD_HONOREM"
    # Las licencias con cobro no se asignan a mano: se activan pagando.
    assert _accion(c, lab["uuid"], "licencia", tipo_licencia="ANUAL").headers["location"].endswith("?error=suscripcion")
    assert _accion(c, lab["uuid"], "cancelar").status_code == 303
    assert _suscripcion(lab["uuid"])["estado"] == "CANCELADA"
    assert _accion(c, lab["uuid"], "reactivar").headers["location"].endswith("?error=suscripcion")
    assert _accion(c, lab["uuid"], "inventada").status_code == 400
    respuesta = c.post(
        "/laboratorios/00000000-0000-0000-0000-000000000000/suscripcion",
        data={"accion": "cancelar", "csrf": csrf(c, "/laboratorios")},
    )
    assert respuesta.status_code == 404


def test_permiso_para_cambiar_la_suscripcion(buzon):
    lab = nuevo_laboratorio("DEMO")
    tecnico = cliente_admin("tecnico@plataforma.test", buzon)
    assert _accion(tecnico, lab["uuid"], "cancelar").status_code == 403
    assert _suscripcion(lab["uuid"])["estado"] == "ACTIVA"


def test_detalle_muestra_suscripcion_y_facturas(buzon):
    lab = nuevo_laboratorio("MENSUAL")
    pagina = cliente_admin(MAESTRO, buzon).get(f"/laboratorios/{lab['uuid']}").text
    assert "MENSUAL" in pagina and "Generar factura" in pagina and "Suspender" in pagina
