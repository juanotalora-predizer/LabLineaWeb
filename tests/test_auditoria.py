"""Auditoría de datos (spec infraestructura/0007, sección 5; etapa 3).

- Escrituras: triggers con el registro antes y después, usuario e IP de la transacción.
- Lecturas y accesos denegados: los registra la aplicación.
- Solo inserción: el rol de la aplicación no modifica, borra ni vacía la auditoría, ni siquiera
  con SQL directo; el dueño tampoco (trigger). Las particiones no se pueden consultar directamente.
- Aislamiento: la auditoría de un laboratorio no es visible desde otro.
"""

import uuid
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.auth import repositorio
from app.core import tareas
from app.core.auditoria import registrar_acceso
from app.core.db import sesion_tenant
from tests.ayudas import autenticar, cliente
from tests.conftest import correr, ejecutar_en_tenant

pytestmark = pytest.mark.anyio

# Tablas de lab sin trigger de auditoría, con su razón. Cualquier tabla nueva debe auditarse o
# aparecer aquí con una justificación (guardián más abajo).
SIN_TRIGGER = {
    "auditoria": "es la propia auditoría",
    "eventos_seguridad": "bitácora de seguridad de solo inserción",
    "sesiones": "operativa: se actualiza en cada petición; ingresos y salidas van a eventos_seguridad",
    "codigos_verificacion": "operativa: solo HMAC de códigos de un solo uso",
    "limites": "operativa: contadores de intentos sin datos personales",
}


async def _ultimas(engine_owner, tenant: str, condicion: str = "true", parametros: dict | None = None) -> list:
    """Filas de auditoría del laboratorio, leídas con el dueño (también bajo RLS forzado)."""
    async with engine_owner.begin() as conexion:
        await conexion.execute(text("SELECT set_config('app.current_tenant', :t, true)"), {"t": tenant})
        # Condiciones fijas escritas en esta prueba, nunca entrada externa.
        consulta = text(
            "SELECT tabla, operacion, registro_id, usuario_id, host(ip) AS ip, resultado, antes, despues"  # noqa: S608
            " FROM lab.auditoria WHERE " + condicion + " ORDER BY id DESC"
        )
        return (await conexion.execute(consulta, parametros or {})).mappings().all()


async def _crear_usuario(email: str, *, usuario: str = "auditor-prueba", ip: str = "10.1.2.3") -> int:
    async with sesion_tenant("lab_a", usuario_id=usuario, ip=ip) as sesion:
        return await repositorio.crear_usuario(
            sesion, email=email, nombre="Persona Auditada", tipo="PACIENTE", clave="Clave-de-prueba-2026"
        )


# --- Escrituras (triggers) ---


async def test_insercion_queda_auditada_con_usuario_ip_y_despues(engine_app, engine_owner):
    email = f"audit-{uuid.uuid4().hex[:8]}@lab-a.test"
    usuario_id = await _crear_usuario(email)
    filas = await _ultimas(engine_owner, "lab_a", "tabla = 'usuarios' AND registro_id = :i", {"i": usuario_id})
    assert len(filas) == 1
    fila = filas[0]
    assert (fila["operacion"], fila["usuario_id"], fila["ip"], fila["resultado"]) == (
        "INSERT",
        "auditor-prueba",
        "10.1.2.3",
        "EXITO",
    )
    assert fila["antes"] is None
    assert fila["despues"]["email"] == email
    assert fila["despues"]["tenant_id"] == "lab_a"


async def test_actualizacion_guarda_antes_y_despues(engine_app, engine_owner):
    usuario_id = await _crear_usuario(f"audit-{uuid.uuid4().hex[:8]}@lab-a.test")
    async with sesion_tenant("lab_a", usuario_id="editor") as sesion:
        await sesion.execute(text("UPDATE lab.usuarios SET nombre = 'Nombre Nuevo' WHERE id = :i"), {"i": usuario_id})
    fila = (await _ultimas(engine_owner, "lab_a", "registro_id = :i AND operacion = 'UPDATE'", {"i": usuario_id}))[0]
    assert fila["antes"]["nombre"] == "Persona Auditada"
    assert fila["despues"]["nombre"] == "Nombre Nuevo"
    assert fila["usuario_id"] == "editor"


async def test_borrado_queda_auditado(engine_app, engine_owner):
    async with sesion_tenant("lab_a", usuario_id="admin") as sesion:
        rol_id = await sesion.scalar(text("SELECT id FROM lab.roles WHERE codigo = 'AUDITOR'"))
        await sesion.execute(
            text(
                "INSERT INTO lab.rol_acciones (tenant_id, rol_id, accion)"
                " VALUES (lab.tenant_actual(), :r, 'ANULAR_ORDEN')"
            ),
            {"r": rol_id},
        )
        await sesion.execute(
            text("DELETE FROM lab.rol_acciones WHERE rol_id = :r AND accion = 'ANULAR_ORDEN'"), {"r": rol_id}
        )
    fila = (await _ultimas(engine_owner, "lab_a", "tabla = 'rol_acciones' AND operacion = 'DELETE'"))[0]
    assert fila["antes"]["accion"] == "ANULAR_ORDEN"
    assert fila["despues"] is None
    assert fila["registro_id"] is None  # tabla sin columna id


async def test_secretos_nunca_llegan_a_la_auditoria(engine_app, engine_owner):
    usuario_id = await _crear_usuario(f"audit-{uuid.uuid4().hex[:8]}@lab-a.test")
    async with sesion_tenant("lab_a") as sesion:
        await repositorio.actualizar_hash(sesion, usuario_id, "$argon2id$v=19$nuevo-hash-sintetico")
    filas = await _ultimas(engine_owner, "lab_a", "tabla = 'usuarios' AND registro_id = :i", {"i": usuario_id})
    insercion = next(f for f in filas if f["operacion"] == "INSERT")
    cambio = next(f for f in filas if f["operacion"] == "UPDATE")
    assert insercion["despues"]["password_hash"] == "[protegido]"
    assert insercion["despues"]["totp_secreto_cifrado"] == "[protegido]"
    assert "totp_ultimo_contador" not in insercion["despues"]  # columna ignorada
    # El cambio de contraseña queda registrado, sin el valor.
    assert cambio["antes"]["password_hash"] == "[protegido]"
    assert cambio["despues"]["password_hash"] == "[protegido, modificado]"
    assert "argon2id" not in str(filas)


async def test_cambio_solo_en_columna_ignorada_no_genera_ruido(engine_app, engine_owner):
    usuario_id = await _crear_usuario(f"audit-{uuid.uuid4().hex[:8]}@lab-a.test")
    async with sesion_tenant("lab_a") as sesion:
        await repositorio.registrar_contador_totp(sesion, usuario_id, 12345)
    filas = await _ultimas(engine_owner, "lab_a", "tabla = 'usuarios' AND registro_id = :i", {"i": usuario_id})
    assert [f["operacion"] for f in filas] == ["INSERT"]


async def test_toda_tabla_de_lab_esta_auditada_o_justificada(engine_app):
    """Guardián: una tabla nueva de lab sin trigger de auditoría hace fallar la suite."""
    async with engine_app.connect() as conexion:
        tablas = set(
            (
                await conexion.execute(
                    text(
                        "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
                        " WHERE n.nspname = 'lab' AND c.relkind IN ('r', 'p') AND NOT c.relispartition"
                    )
                )
            ).scalars()
        )
        auditadas = set(
            (
                await conexion.execute(
                    text(
                        "SELECT c.relname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid"
                        " JOIN pg_namespace n ON n.oid = c.relnamespace"
                        " WHERE n.nspname = 'lab' AND t.tgfoid = 'lab.auditar'::regproc AND NOT t.tgisinternal"
                    )
                )
            ).scalars()
        )
    assert tablas - auditadas == set(SIN_TRIGGER), "Tablas sin auditoría ni justificación"


# --- Lecturas y accesos denegados (aplicación) ---


def test_lista_de_usuarios_deja_registro_de_lectura(buzon):
    c = autenticar(cliente(), "admin@lab-a.test", buzon)
    assert c.get("/configuracion/usuarios").status_code == 200

    async def leer(sesion):
        return (
            (
                await sesion.execute(
                    text(
                        "SELECT a.operacion, a.resultado, a.despues, a.usuario_id = u.uuid::text AS es_admin"
                        " FROM lab.auditoria a, lab.usuarios u"
                        " WHERE u.email = 'admin@lab-a.test' AND a.tabla = 'usuarios' AND a.operacion = 'READ'"
                        " ORDER BY a.id DESC LIMIT 1"
                    )
                )
            )
            .mappings()
            .first()
        )

    fila = correr(ejecutar_en_tenant("app", "lab_a", leer))
    assert fila["resultado"] == "EXITO" and fila["es_admin"]
    assert fila["despues"]["vista"] == "lista_usuarios" and fila["despues"]["filas"] > 0


def test_acceso_denegado_queda_auditado(buzon):
    c = autenticar(cliente(), "recepcion@lab-a.test", buzon)
    assert c.get("/configuracion/usuarios").status_code == 403

    async def leer(sesion):
        return (
            (
                await sesion.execute(
                    text(
                        "SELECT a.tabla, a.resultado, a.despues FROM lab.auditoria a, lab.usuarios u"
                        " WHERE u.email = 'recepcion@lab-a.test' AND a.usuario_id = u.uuid::text"
                        " AND a.operacion = 'ACCESO' ORDER BY a.id DESC LIMIT 1"
                    )
                )
            )
            .mappings()
            .first()
        )

    fila = correr(ejecutar_en_tenant("app", "lab_a", leer))
    assert (fila["tabla"], fila["resultado"]) == ("modulo:usuarios", "DENEGADO")
    assert fila["despues"] == {"permiso": "usuarios.consultar"}


async def test_registrar_acceso_exige_laboratorio(engine_app):
    with pytest.raises(DBAPIError, match="sin laboratorio"):
        async with engine_app.begin() as conexion:
            await conexion.execute(text("SELECT lab.registrar_acceso('usuarios', 'READ', NULL, 'EXITO', NULL)"))


async def test_la_aplicacion_no_puede_forjar_escrituras_en_la_auditoria(engine_app):
    for operacion in ("INSERT", "UPDATE", "DELETE"):
        with pytest.raises(DBAPIError, match="Operación no permitida"):
            async with sesion_tenant("lab_a") as sesion:
                await registrar_acceso(sesion, "usuarios", operacion=operacion)  # type: ignore[arg-type]


# --- Solo inserción ---


@pytest.mark.parametrize(
    "sentencia",
    [
        "INSERT INTO lab.auditoria (tenant_id, tabla, operacion) VALUES ('lab_a', 'x', 'READ')",
        "UPDATE lab.auditoria SET tabla = 'x'",
        "DELETE FROM lab.auditoria",
        "TRUNCATE lab.auditoria",
    ],
)
async def test_rol_app_no_modifica_la_auditoria_ni_con_sql_directo(engine_app, sentencia):
    with pytest.raises(DBAPIError, match="permission denied"):
        async with engine_app.begin() as conexion:
            await conexion.execute(text("SELECT set_config('app.current_tenant', 'lab_a', true)"))
            await conexion.execute(text(sentencia))


@pytest.mark.parametrize(
    "sentencia", ["UPDATE lab.auditoria SET tabla = 'x'", "DELETE FROM lab.auditoria", "TRUNCATE lab.auditoria"]
)
async def test_ni_el_dueno_modifica_la_auditoria(engine_owner, sentencia):
    with pytest.raises(DBAPIError, match="solo inserción"):
        async with engine_owner.begin() as conexion:
            await conexion.execute(text("SELECT set_config('app.current_tenant', 'lab_a', true)"))
            await conexion.execute(text(sentencia))


async def test_particiones_protegidas_y_no_consultables_directamente(engine_app, engine_owner):
    async with engine_owner.connect() as conexion:
        particiones = (
            (
                await conexion.execute(
                    text(
                        "SELECT c.relname, c.relrowsecurity AND c.relforcerowsecurity AS rls,"
                        " EXISTS (SELECT 1 FROM pg_policy p WHERE p.polrelid = c.oid"
                        "         AND p.polqual IS NOT NULL AND p.polwithcheck IS NOT NULL) AS politica,"
                        " has_table_privilege('lablinea_app', c.oid, 'SELECT, INSERT, UPDATE, DELETE') AS app"
                        " FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid"
                        " WHERE i.inhparent = 'lab.auditoria'::regclass"
                    )
                )
            )
            .mappings()
            .all()
        )
    assert len(particiones) >= 13  # 12 meses + partición por defecto
    assert all(p["rls"] and p["politica"] and not p["app"] for p in particiones), particiones
    with pytest.raises(DBAPIError, match="permission denied"):
        async with engine_app.begin() as conexion:
            await conexion.execute(text(f"SELECT * FROM lab.{particiones[0]['relname']}"))  # noqa: S608


async def test_particiones_se_crean_solo_en_rango_y_son_idempotentes(engine_app):
    await tareas.mantener_particiones(meses=2)
    await tareas.mantener_particiones(meses=2)  # idempotente
    async with engine_app.begin() as conexion:
        with pytest.raises(DBAPIError, match="fuera del rango"):
            await conexion.execute(text("SELECT lab.crear_particion_auditoria(:m)"), {"m": date(2000, 1, 1)})


# --- Aislamiento ---


async def test_auditoria_de_un_laboratorio_invisible_desde_otro(engine_app):
    await _crear_usuario(f"audit-{uuid.uuid4().hex[:8]}@lab-a.test")
    async with sesion_tenant("lab_b") as sesion:
        ajenas = await sesion.scalar(text("SELECT count(*) FROM lab.auditoria WHERE tenant_id <> 'lab_b'"))
        propias = await sesion.scalar(text("SELECT count(*) FROM lab.auditoria"))
    async with sesion_tenant("lab_a") as sesion:
        de_a = await sesion.scalar(text("SELECT count(*) FROM lab.auditoria"))
    assert ajenas == 0
    assert de_a > 0 and propias >= 0


async def test_registrar_acceso_no_escribe_en_otro_laboratorio(engine_app):
    async with sesion_tenant("lab_b", usuario_id="intruso") as sesion:
        await registrar_acceso(sesion, "usuarios", detalle={"prueba": "aislamiento"})
    async with sesion_tenant("lab_a") as sesion:
        en_a = await sesion.scalar(text("SELECT count(*) FROM lab.auditoria WHERE usuario_id = 'intruso'"))
    async with sesion_tenant("lab_b") as sesion:
        en_b = await sesion.scalar(text("SELECT count(*) FROM lab.auditoria WHERE usuario_id = 'intruso'"))
    assert en_a == 0 and en_b >= 1
