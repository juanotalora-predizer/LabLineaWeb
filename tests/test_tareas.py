"""Cola de tareas (spec infraestructura/0012, etapa 3).

- Una tarea que falla se reintenta con espera y termina FALLIDA al agotar los intentos.
- Una tarea no se ejecuta dos veces: ni con trabajadores concurrentes ni cuando vence el plazo.
- La cola no mezcla laboratorios: la tarea corre con el laboratorio con que se encoló.
- El rol de la aplicación no toca la tabla de la cola directamente.
"""

import asyncio
import logging

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core import db, tareas
from app.core.db import sesion_tenant

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
async def cola_vacia(engine_owner):
    async with engine_owner.begin() as conexion:
        # Los eventos de seguridad (efecto de las tareas de prueba) se vacían al iniciar la corrida;
        # cada prueba usa su propio tipo de evento.
        await conexion.execute(text("TRUNCATE cola.tareas"))
    yield
    await db.cerrar()


@pytest.fixture
def manejadores(monkeypatch):
    """Registro de manejadores aislado por prueba."""
    registro: dict = {}
    monkeypatch.setattr(tareas, "MANEJADORES", registro)
    return registro


async def _encolar(tenant: str, tipo: str, datos: dict | None = None, **opciones) -> str:
    async with sesion_tenant(tenant) as sesion:
        return await tareas.encolar(sesion, tipo, datos, **opciones)


async def _tarea(engine_owner, uuid: str):
    async with engine_owner.connect() as conexion:
        return (
            (
                await conexion.execute(
                    text(
                        "SELECT tenant_id, estado, intentos, ultimo_error, disponible_en > now() AS en_espera"
                        " FROM cola.tareas WHERE uuid = :u"
                    ),
                    {"u": uuid},
                )
            )
            .mappings()
            .one()
        )


async def _hacer_disponible(engine_owner, uuid: str) -> None:
    async with engine_owner.begin() as conexion:
        await conexion.execute(text("UPDATE cola.tareas SET disponible_en = now() WHERE uuid = :u"), {"u": uuid})


async def _eventos(engine_owner, tenant: str, tipo: str) -> int:
    async with engine_owner.begin() as conexion:
        await conexion.execute(text("SELECT set_config('app.current_tenant', :t, true)"), {"t": tenant})
        return await conexion.scalar(text("SELECT count(*) FROM lab.eventos_seguridad WHERE tipo = :t"), {"t": tipo})


async def _registrar_evento(sesion, tipo: str) -> None:
    """Efecto visible de una tarea: un evento en la tabla del laboratorio de la transacción."""
    await sesion.execute(
        text("INSERT INTO lab.eventos_seguridad (tenant_id, tipo) VALUES (lab.tenant_actual(), :t)"), {"t": tipo}
    )


# --- Encolar ---


async def test_encolar_exige_laboratorio(engine_app):
    with pytest.raises(DBAPIError, match="sin laboratorio"):
        async with engine_app.begin() as conexion:
            await conexion.execute(text("SELECT cola.encolar('prueba.x', '{}', NULL, 0, 5)"))


async def test_la_tarea_queda_del_laboratorio_de_la_transaccion(engine_owner):
    uuid = await _encolar("lab_b", "prueba.tenant")
    assert (await _tarea(engine_owner, uuid))["tenant_id"] == "lab_b"


async def test_clave_unica_hace_idempotente_el_encolado(engine_owner):
    primera = await _encolar("lab_a", "prueba.unica", clave_unica="orden-1")
    segunda = await _encolar("lab_a", "prueba.unica", clave_unica="orden-1")
    otra_lab = await _encolar("lab_b", "prueba.unica", clave_unica="orden-1")
    assert primera == segunda
    assert otra_lab != primera


async def test_si_la_transaccion_se_revierte_la_tarea_no_existe(engine_owner):
    with pytest.raises(RuntimeError):
        async with sesion_tenant("lab_a") as sesion:
            await tareas.encolar(sesion, "prueba.revertida")
            raise RuntimeError("falla después de encolar")
    async with engine_owner.connect() as conexion:
        assert await conexion.scalar(text("SELECT count(*) FROM cola.tareas WHERE tipo = 'prueba.revertida'")) == 0


@pytest.mark.parametrize(
    "datos",
    [{"anidado": {"x": 1}}, {"lista": [1, 2]}, {"largo": "x" * 201}, {"decimal": 1.5}, {1: "clave no texto"}],
)
async def test_datos_de_tarea_solo_valores_simples(engine_app, datos):
    with pytest.raises(ValueError):
        await _encolar("lab_a", "prueba.datos", datos)


@pytest.mark.parametrize(
    "sentencia",
    [
        "SELECT * FROM cola.tareas",
        "INSERT INTO cola.tareas (tenant_id, tipo) VALUES ('lab_b', 'prueba.directa')",
        "UPDATE cola.tareas SET estado = 'COMPLETADA'",
        "DELETE FROM cola.tareas",
    ],
)
async def test_rol_app_no_accede_directamente_a_la_cola(engine_app, sentencia):
    with pytest.raises(DBAPIError, match="permission denied"):
        async with engine_app.begin() as conexion:
            await conexion.execute(text(sentencia))


# --- Procesar ---


async def test_sin_tareas_no_hace_nada(engine_app):
    assert await tareas.procesar_una() is False


async def test_tarea_corre_con_el_laboratorio_de_la_tarea(engine_owner, manejadores):
    vistos = []

    async def manejador(sesion, datos):
        tenant = await sesion.scalar(text("SELECT lab.tenant_actual()"))
        correos = (await sesion.execute(text("SELECT email::text FROM lab.usuarios"))).scalars().all()
        vistos.append((datos["lab"], tenant, {c.split("@")[1] for c in correos}))

    manejadores["prueba.tenant"] = manejador
    await _encolar("lab_a", "prueba.tenant", {"lab": "lab_a"})
    await _encolar("lab_b", "prueba.tenant", {"lab": "lab_b"})
    while await tareas.procesar_una():
        pass
    assert len(vistos) == 2
    for esperado, tenant, dominios in vistos:
        assert tenant == esperado
        # lab_b tiene un paciente con correo @lab-a.test; lo importante es que solo ve sus filas.
        assert dominios <= {"lab-a.test", "lab-b.test", "sintetico.test", "plataforma.test"}
    async with sesion_tenant("lab_b") as sesion:
        en_b = await sesion.scalar(text("SELECT count(*) FROM lab.usuarios"))
    assert en_b < 10  # el manejador de lab_b no ve los usuarios de lab_a (más de 10)


async def test_tarea_exitosa_se_completa_y_audita_como_tarea(engine_owner, manejadores):
    async def manejador(sesion, datos):
        await _registrar_evento(sesion, "TAREA_OK")

    manejadores["prueba.ok"] = manejador
    uuid = await _encolar("lab_a", "prueba.ok")
    assert await tareas.procesar_una() is True
    fila = await _tarea(engine_owner, uuid)
    assert (fila["estado"], fila["intentos"]) == ("COMPLETADA", 1)
    assert await _eventos(engine_owner, "lab_a", "TAREA_OK") == 1
    assert await tareas.procesar_una() is False  # no se vuelve a ejecutar


async def test_tarea_que_falla_se_reintenta_con_espera(engine_owner, manejadores):
    intentos = []

    async def manejador(sesion, datos):
        intentos.append(1)
        await _registrar_evento(sesion, "TAREA_REINTENTO")
        if len(intentos) == 1:
            raise ConnectionError("servicio externo caído")

    manejadores["prueba.reintento"] = manejador
    uuid = await _encolar("lab_a", "prueba.reintento")
    await tareas.procesar_una()
    fila = await _tarea(engine_owner, uuid)
    assert (fila["estado"], fila["intentos"], fila["ultimo_error"], fila["en_espera"]) == (
        "PENDIENTE",
        1,
        "ConnectionError",
        True,
    )
    assert await tareas.procesar_una() is False  # todavía en espera
    await _hacer_disponible(engine_owner, uuid)
    await tareas.procesar_una()
    fila = await _tarea(engine_owner, uuid)
    assert (fila["estado"], fila["intentos"]) == ("COMPLETADA", 2)
    # El intento fallido se revirtió: el efecto ocurrió una sola vez.
    assert await _eventos(engine_owner, "lab_a", "TAREA_REINTENTO") == 1


async def test_tarea_agota_intentos_y_queda_fallida(engine_owner, manejadores):
    async def manejador(sesion, datos):
        raise TimeoutError

    manejadores["prueba.agotada"] = manejador
    uuid = await _encolar("lab_a", "prueba.agotada", max_intentos=2)
    await tareas.procesar_una()
    await _hacer_disponible(engine_owner, uuid)
    await tareas.procesar_una()
    fila = await _tarea(engine_owner, uuid)
    assert (fila["estado"], fila["intentos"], fila["ultimo_error"]) == ("FALLIDA", 2, "TimeoutError")
    await _hacer_disponible(engine_owner, uuid)
    assert await tareas.procesar_una() is False


@pytest.mark.parametrize("registrado", [True, False])
async def test_error_permanente_o_tipo_desconocido_no_se_reintenta(engine_owner, manejadores, registrado):
    async def manejador(sesion, datos):
        raise tareas.ErrorPermanente

    if registrado:
        manejadores["prueba.permanente"] = manejador
    uuid = await _encolar("lab_a", "prueba.permanente")
    await tareas.procesar_una()
    fila = await _tarea(engine_owner, uuid)
    assert (fila["estado"], fila["intentos"], fila["ultimo_error"]) == ("FALLIDA", 1, "ErrorPermanente")


async def test_trabajadores_concurrentes_no_repiten_tareas(engine_owner, manejadores):
    ejecutadas = []

    async def manejador(sesion, datos):
        ejecutadas.append(datos["n"])
        await _registrar_evento(sesion, "TAREA_CONCURRENTE")
        await asyncio.sleep(0.01)

    manejadores["prueba.concurrente"] = manejador
    for n in range(30):
        await _encolar("lab_a" if n % 2 else "lab_b", "prueba.concurrente", {"n": n})

    async def trabajador():
        while await tareas.procesar_una():
            pass

    await asyncio.gather(*(trabajador() for _ in range(5)))
    assert sorted(ejecutadas) == list(range(30))
    assert await _eventos(engine_owner, "lab_a", "TAREA_CONCURRENTE") == 15
    assert await _eventos(engine_owner, "lab_b", "TAREA_CONCURRENTE") == 15


async def test_plazo_vencido_otro_trabajador_la_toma_y_el_primero_se_revierte(engine_owner, manejadores):
    llamadas = []

    async def manejador(sesion, datos):
        llamadas.append(1)
        await _registrar_evento(sesion, "TAREA_PLAZO")
        if len(llamadas) == 1:
            await asyncio.sleep(2.5)  # más que el plazo de 1 s: el trabajador "se colgó"

    manejadores["prueba.plazo"] = manejador
    uuid = await _encolar("lab_a", "prueba.plazo")

    async def segundo():
        await asyncio.sleep(1.3)
        return await tareas.procesar_una(plazo_segundos=60)

    _, tomo = await asyncio.gather(tareas.procesar_una(plazo_segundos=1), segundo())
    assert tomo is True
    fila = await _tarea(engine_owner, uuid)
    assert (fila["estado"], fila["intentos"]) == ("COMPLETADA", 2)
    assert len(llamadas) == 2
    assert await _eventos(engine_owner, "lab_a", "TAREA_PLAZO") == 1  # el efecto, una sola vez


async def test_plazo_vencido_sin_intentos_restantes_queda_fallida(engine_owner, manejadores):
    uuid = await _encolar("lab_a", "prueba.colgada", max_intentos=1)
    async with engine_owner.begin() as conexion:
        await conexion.execute(
            text(
                "UPDATE cola.tareas SET estado = 'EN_CURSO', intentos = 1, ficha = gen_random_uuid(),"
                " bloqueada_hasta = now() - interval '1 second' WHERE uuid = :u"
            ),
            {"u": uuid},
        )
    assert await tareas.procesar_una() is False
    fila = await _tarea(engine_owner, uuid)
    assert (fila["estado"], fila["ultimo_error"]) == ("FALLIDA", "PlazoVencido")


async def test_errores_de_tareas_no_registran_el_mensaje(engine_owner, manejadores, caplog):
    """El mensaje de una excepción puede llevar datos del registro: ni en la cola ni en el log."""

    async def manejador(sesion, datos):
        raise ValueError("Paciente Ficticio Pérez 99123456")

    manejadores["prueba.mensaje"] = manejador
    uuid = await _encolar("lab_a", "prueba.mensaje")
    with caplog.at_level(logging.DEBUG):
        await tareas.procesar_una()
    assert (await _tarea(engine_owner, uuid))["ultimo_error"] == "ValueError"
    assert "Ficticio" not in caplog.text and "99123456" not in caplog.text
    assert "ValueError" in caplog.text


async def test_decorador_registra_el_manejador(engine_owner, manejadores):
    @tareas.tarea("prueba.decorada")
    async def manejador(sesion, datos):
        await _registrar_evento(sesion, "TAREA_DECORADA")

    assert manejadores["prueba.decorada"] is manejador
    await _encolar("lab_b", "prueba.decorada")
    await tareas.procesar_una()
    assert await _eventos(engine_owner, "lab_b", "TAREA_DECORADA") == 1


async def test_espera_exponencial_con_tope():
    assert [tareas.espera_para(i, base=30) for i in (1, 2, 3)] == [30, 60, 120]
    assert tareas.espera_para(20) == tareas.ESPERA_MAXIMA_SEGUNDOS


async def test_bucle_del_trabajador_procesa_y_se_detiene(engine_owner, manejadores):
    parar = asyncio.Event()

    async def manejador(sesion, datos):
        parar.set()

    manejadores["prueba.bucle"] = manejador
    uuid = await _encolar("lab_a", "prueba.bucle")
    await asyncio.wait_for(tareas.trabajar(parar, intervalo=0.05), timeout=10)
    assert (await _tarea(engine_owner, uuid))["estado"] == "COMPLETADA"

    # Sin tareas: espera y sale al activarse la señal.
    otra = asyncio.Event()
    asyncio.get_running_loop().call_later(0.2, otra.set)
    await asyncio.wait_for(tareas.trabajar(otra, intervalo=0.05), timeout=10)
