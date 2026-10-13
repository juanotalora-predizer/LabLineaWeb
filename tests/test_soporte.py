"""Acceso de soporte de la plataforma (etapa 5; spec infraestructura/0005).

- Sin autorización vigente del laboratorio → 403 (y queda en la auditoría de la plataforma).
- Con autorización: tiquete de un solo uso → sesión de solo lectura en el laboratorio, auditada petición a
  petición, que termina al vencer o revocarse la autorización.
"""

import re
import uuid

import pytest
from sqlalchemy import text

from tests.ayudas import autenticar, cliente, cliente_admin, csrf, nuevo_laboratorio
from tests.conftest import correr, ejecutar_en_plataforma, ejecutar_en_tenant

TECNICO = "tecnico@plataforma.test"


def _autorizar(c, horas: str = "2", motivo: str = "Caso 1234: revisar usuarios"):
    return c.post(
        "/configuracion/soporte", data={"horas": horas, "motivo": motivo, "csrf": csrf(c, "/configuracion/soporte")}
    )


def _uuid_lab(tenant: str) -> str:
    async def leer(sesion):
        return await sesion.scalar(
            text("SELECT uuid::text FROM plataforma.laboratorios WHERE tenant_id = :t"), {"t": tenant}
        )

    return correr(ejecutar_en_plataforma(leer))


def _iniciar(plataforma, lab_uuid: str):
    return plataforma.post(f"/soporte/{lab_uuid}/iniciar", data={"csrf": csrf(plataforma, "/soporte")})


def _enlace(respuesta) -> str:
    """Enlace al laboratorio de la página que muestra el Admin Hub al emitir el tiquete."""
    assert respuesta.status_code == 200, respuesta.status_code
    return re.search(r'href="(https://[^"]+/soporte/entrar/[^"]+)"', respuesta.text).group(1)


def _entrar(subdominio: str, ubicacion: str):
    """Abre el enlace del Admin Hub en el laboratorio y confirma la entrada."""
    token = re.search(r"/soporte/entrar/(\S+)$", ubicacion).group(1)
    c = cliente(subdominio)
    assert c.get(f"/soporte/entrar/{token}").status_code == 200
    return c, token, c.post(f"/soporte/entrar/{token}", data={"csrf": csrf(c, f"/soporte/entrar/{token}")})


@pytest.fixture
def lab_autorizado(buzon):
    """Laboratorio nuevo cuyo administrador (activado) autorizó el soporte."""
    lab = nuevo_laboratorio()
    import pyotp

    from app.auth import contrasenas, repositorio
    from tests.conftest import CLAVE, SECRETOS_TOTP

    email = f"jefe@{lab['subdominio']}.test"
    SECRETOS_TOTP[(lab["tenant"], email)] = pyotp.random_base32()

    async def activar(sesion):
        # Como si hubiera activado su cuenta e inscrito su app autenticadora.
        await sesion.execute(text("UPDATE lab.usuarios SET password_hash = :h"), {"h": contrasenas.hashear(CLAVE)})
        usuario = await repositorio.buscar_usuario_por_email(sesion, email)
        await repositorio.guardar_totp(sesion, usuario, SECRETOS_TOTP[(lab["tenant"], email)])
        await repositorio.confirmar_totp(sesion, usuario.id, 0)

    correr(ejecutar_en_tenant("app", lab["tenant"], activar))
    admin = autenticar(cliente(lab["subdominio"]), f"jefe@{lab['subdominio']}.test", buzon, laboratorio=lab["tenant"])
    return lab, admin


def test_sin_autorizacion_403_y_auditado(buzon):
    lab = nuevo_laboratorio()
    plataforma = cliente_admin(TECNICO, buzon)
    assert lab["uuid"] not in plataforma.get("/soporte").text
    assert _iniciar(plataforma, lab["uuid"]).status_code == 403

    async def denegado(sesion):
        return await sesion.scalar(
            text(
                "SELECT count(*) FROM plataforma.auditoria WHERE tabla = 'soporte' AND resultado = 'DENEGADO'"
                " AND despues->>'laboratorio' = :l"
            ),
            {"l": lab["uuid"]},
        )

    assert correr(ejecutar_en_plataforma(denegado)) == 1
    assert _iniciar(plataforma, str(uuid.uuid4())).status_code == 403  # laboratorio inexistente: igual


def test_flujo_completo_de_soporte(lab_autorizado, buzon):
    lab, admin = lab_autorizado
    assert _autorizar(admin).status_code == 303
    assert "Caso 1234" in admin.get("/configuracion/soporte").text

    plataforma = cliente_admin(TECNICO, buzon)
    assert "Caso 1234" in plataforma.get("/soporte").text
    enlace = _enlace(_iniciar(plataforma, lab["uuid"]))
    assert enlace.startswith(f"https://{lab['subdominio']}.lablinea.localhost")

    soporte, token, entrada = _entrar(lab["subdominio"], enlace)
    assert entrada.status_code == 303 and entrada.headers["location"] == "/panel"
    panel = soporte.get("/panel")
    assert panel.status_code == 200 and "Sesión de soporte" in panel.text
    # Solo lectura: consulta usuarios, pero no invita ni autoriza soporte.
    assert soporte.get("/configuracion/usuarios").status_code == 200
    assert soporte.get("/configuracion/usuarios/nuevo").status_code == 403
    assert soporte.get("/configuracion/soporte").status_code == 403
    # El tiquete no se reutiliza.
    otro = cliente(lab["subdominio"])
    assert (
        otro.post(f"/soporte/entrar/{token}", data={"csrf": csrf(otro, f"/soporte/entrar/{token}")}).status_code == 404
    )

    # Cada petición del soporte queda en la auditoría del laboratorio, a su nombre.
    async def auditoria(sesion):
        return (
            (
                await sesion.execute(
                    text(
                        "SELECT a.despues->>'ruta' FROM lab.auditoria a"
                        " JOIN lab.usuarios u ON a.usuario_id = u.uuid::text"
                        " WHERE u.tipo = 'SOPORTE' AND a.tabla = 'soporte' ORDER BY a.id"
                    )
                )
            )
            .scalars()
            .all()
        )

    rutas = correr(ejecutar_en_tenant("app", lab["tenant"], auditoria))
    assert "/panel" in rutas and "/configuracion/usuarios" in rutas
    # El laboratorio ve a la persona de soporte en su lista de usuarios.
    assert TECNICO in admin.get("/configuracion/usuarios").text

    # Revocar cierra la sesión de soporte.
    acceso = re.search(
        r"/configuracion/soporte/([0-9a-f-]{36})/revocar", admin.get("/configuracion/soporte").text
    ).group(1)
    assert (
        admin.post(
            f"/configuracion/soporte/{acceso}/revocar", data={"csrf": csrf(admin, "/configuracion/soporte")}
        ).status_code
        == 303
    )
    assert soporte.get("/panel").status_code == 303
    assert _iniciar(plataforma, lab["uuid"]).status_code == 403
    assert (
        admin.post(
            f"/configuracion/soporte/{acceso}/revocar", data={"csrf": csrf(admin, "/configuracion/soporte")}
        ).status_code
        == 404
    )


def test_autorizacion_vencida_termina_la_sesion(lab_autorizado, buzon):
    lab, admin = lab_autorizado
    _autorizar(admin, horas="1")
    soporte, _, entrada = _entrar(lab["subdominio"], _enlace(_iniciar(cliente_admin(TECNICO, buzon), lab["uuid"])))
    assert soporte.get("/panel").status_code == 200

    async def vencer(sesion):
        await sesion.execute(
            text(
                "UPDATE lab.accesos_soporte SET inicio = now() - interval '2 hours', fin = now() - interval '1 minute'"
            )
        )

    correr(ejecutar_en_tenant("owner", lab["tenant"], vencer))
    assert soporte.get("/panel").status_code == 303  # defensa en cada petición


def test_tiquete_de_un_laboratorio_no_sirve_en_otro(lab_autorizado, buzon):
    lab, admin = lab_autorizado
    _autorizar(admin)
    ubicacion = _enlace(_iniciar(cliente_admin(TECNICO, buzon), lab["uuid"]))
    token = re.search(r"/soporte/entrar/(\S+)$", ubicacion).group(1)
    ajeno = cliente("lab-b")
    assert ajeno.post(f"/soporte/entrar/{token}", data={"csrf": csrf(ajeno, "/ingresar")}).status_code == 404
    # En su laboratorio sigue sirviendo.
    _, _, entrada = _entrar(lab["subdominio"], ubicacion)
    assert entrada.status_code == 303


def test_tiquete_vencido(lab_autorizado, buzon):
    lab, admin = lab_autorizado
    _autorizar(admin)
    ubicacion = _enlace(_iniciar(cliente_admin(TECNICO, buzon), lab["uuid"]))

    async def vencer(sesion):
        await sesion.execute(text("UPDATE lab.tickets_soporte SET expira_en = now() - interval '1 second'"))

    correr(ejecutar_en_tenant("app", lab["tenant"], vencer))
    _, _, entrada = _entrar(lab["subdominio"], ubicacion)
    assert entrada.status_code == 404


@pytest.mark.parametrize("token", ["corto", "x" * 43, "y" * 200])
def test_tiquetes_inventados(token):
    c = cliente()
    assert c.get(f"/soporte/entrar/{token}").status_code in (200, 404)
    assert c.post(f"/soporte/entrar/{token}", data={"csrf": csrf(c)}).status_code == 404


@pytest.mark.parametrize(
    ("horas", "motivo"), [("0", "Motivo válido"), ("73", "Motivo válido"), ("dos", "Motivo válido"), ("2", "x")]
)
def test_autorizacion_valida_duracion_y_motivo(buzon, horas, motivo):
    admin = autenticar(cliente(), "admin@lab-a.test", buzon)
    assert _autorizar(admin, horas, motivo).status_code == 400


@pytest.mark.parametrize("email", ["recepcion@lab-a.test", "auditor@lab-a.test"])
def test_sin_la_accion_no_se_autoriza_soporte(buzon, email):
    assert autenticar(cliente(), email, buzon).get("/configuracion/soporte").status_code == 403


def test_otro_laboratorio_no_revoca_mi_autorizacion(buzon):
    admin_a = autenticar(cliente(), "admin@lab-a.test", buzon)
    _autorizar(admin_a)
    acceso = re.search(
        r"/configuracion/soporte/([0-9a-f-]{36})/revocar", admin_a.get("/configuracion/soporte").text
    ).group(1)
    admin_b = autenticar(cliente("lab-b"), "admin@lab-b.test", buzon, laboratorio="lab_b")
    respuesta = admin_b.post(f"/configuracion/soporte/{acceso}/revocar", data={"csrf": csrf(admin_b, "/panel")})
    assert respuesta.status_code == 404
    assert "Revocar" in admin_a.get("/configuracion/soporte").text  # sigue vigente
    admin_a.post(f"/configuracion/soporte/{acceso}/revocar", data={"csrf": csrf(admin_a, "/configuracion/soporte")})


@pytest.mark.parametrize(
    ("email", "esperado"), [("financiero@plataforma.test", 403), ("comercial@plataforma.test", 403)]
)
def test_solo_quien_tiene_el_modulo_de_soporte(buzon, email, esperado):
    assert cliente_admin(email, buzon).get("/soporte").status_code == esperado


def test_correo_de_soporte_que_ya_es_usuario_del_laboratorio(buzon):
    """Si el correo del técnico ya pertenece a una persona del laboratorio, no se mezclan las cuentas."""
    admin_a = autenticar(cliente(), "admin@lab-a.test", buzon)
    _autorizar(admin_a)

    async def crear_homonimo(sesion):
        await sesion.execute(
            text(
                "INSERT INTO lab.usuarios (email, nombre, tipo)"
                " VALUES ('maestro@plataforma.test', 'Homónimo', 'PERSONAL')"
                " ON CONFLICT DO NOTHING"
            )
        )

    correr(ejecutar_en_tenant("app", "lab_a", crear_homonimo))
    assert _iniciar(cliente_admin("maestro@plataforma.test", buzon), _uuid_lab("lab_a")).status_code == 403
    acceso = re.search(
        r"/configuracion/soporte/([0-9a-f-]{36})/revocar", admin_a.get("/configuracion/soporte").text
    ).group(1)
    admin_a.post(f"/configuracion/soporte/{acceso}/revocar", data={"csrf": csrf(admin_a, "/configuracion/soporte")})

    async def quitar_homonimo(sesion):
        await sesion.execute(text("DELETE FROM lab.usuarios WHERE email = 'maestro@plataforma.test'"))

    correr(ejecutar_en_tenant("owner", "lab_a", quitar_homonimo))  # lab_a vuelve a su estado sembrado


@pytest.mark.anyio
async def test_usuario_de_soporte_nunca_tiene_contrasena(engine_owner):
    from sqlalchemy.exc import DBAPIError

    with pytest.raises(DBAPIError, match="soporte_sin_contrasena"):
        async with engine_owner.begin() as conexion:
            await conexion.execute(text("SELECT set_config('app.current_tenant', 'lab_a', true)"))
            await conexion.execute(
                text(
                    "INSERT INTO lab.usuarios (tenant_id, email, nombre, tipo, password_hash)"
                    " VALUES ('lab_a', 'falso@soporte.test', 'Falso', 'SOPORTE', '$argon2id$x')"
                )
            )


@pytest.mark.parametrize("horas", ["²", "٣", "１"])
def test_regresion_digitos_unicode_en_la_duracion(buzon, horas):
    """Regresión (fuzzing de la etapa 5): "²" pasaba str.isdigit() y int() fallaba con un error 500."""
    admin = autenticar(cliente(), "admin@lab-a.test", buzon)
    assert _autorizar(admin, horas, "Motivo válido").status_code == 400
