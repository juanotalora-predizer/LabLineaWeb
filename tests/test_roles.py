"""Matriz rol × esquema × operación y reglas de plataforma.laboratorios (spec infraestructura/0007, etapa 1)."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.anyio

APP = "lablinea_app"
PLATAFORMA = "lablinea_plataforma"

ESQUEMAS = [
    # (rol, esquema, puede usarlo)
    (APP, "lab", True),
    (APP, "global", True),
    (APP, "acceso", True),
    (APP, "plataforma", False),
    (PLATAFORMA, "plataforma", True),
    (PLATAFORMA, "global", True),
    (PLATAFORMA, "lab", False),
    (PLATAFORMA, "acceso", False),
]

TABLAS = [
    # (rol, tabla, privilegio, lo tiene)
    (APP, "global.paises", "SELECT", True),
    (APP, "global.paises", "INSERT", False),
    (APP, "global.paises", "UPDATE", False),
    (APP, "global.paises", "DELETE", False),
    (APP, "global.tipos_documento", "SELECT", True),
    (APP, "global.monedas", "SELECT", True),
    (APP, "plataforma.laboratorios", "SELECT", False),
    (APP, "plataforma.laboratorios", "UPDATE", False),
    (PLATAFORMA, "plataforma.laboratorios", "SELECT", True),
    (PLATAFORMA, "plataforma.laboratorios", "INSERT", True),
    (PLATAFORMA, "plataforma.laboratorios", "UPDATE", True),
    (PLATAFORMA, "plataforma.laboratorios", "DELETE", False),
    (PLATAFORMA, "global.paises", "SELECT", True),
    (PLATAFORMA, "global.paises", "INSERT", False),
    (PLATAFORMA, "global.paises", "UPDATE", False),
]


@pytest.mark.parametrize(("rol", "esquema", "esperado"), ESQUEMAS)
async def test_matriz_de_esquemas(engine_owner, rol, esquema, esperado):
    async with engine_owner.connect() as conexion:
        valor = await conexion.scalar(text("SELECT has_schema_privilege(:r, :e, 'USAGE')"), {"r": rol, "e": esquema})
    assert valor is esperado


@pytest.mark.parametrize(("rol", "tabla", "privilegio", "esperado"), TABLAS)
async def test_matriz_de_tablas(engine_owner, rol, tabla, privilegio, esperado):
    async with engine_owner.connect() as conexion:
        valor = await conexion.scalar(
            text("SELECT has_table_privilege(:r, :t, :p)"), {"r": rol, "t": tabla, "p": privilegio}
        )
    assert valor is esperado


async def test_app_no_puede_leer_laboratorios_directamente(engine_app):
    with pytest.raises(DBAPIError, match="permission denied"):
        async with engine_app.connect() as conexion:
            await conexion.execute(text("SELECT * FROM plataforma.laboratorios"))


async def test_app_no_puede_modificar_catalogos_globales(engine_app):
    with pytest.raises(DBAPIError, match="permission denied"):
        async with engine_app.begin() as conexion:
            await conexion.execute(text("UPDATE \"global\".paises SET habilitado = true WHERE codigo = 'COL'"))


async def test_plataforma_no_puede_usar_lab(engine_plataforma):
    with pytest.raises(DBAPIError, match="permission denied"):
        async with engine_plataforma.connect() as conexion:
            await conexion.execute(text("SELECT lab.tenant_actual()"))


async def test_plataforma_no_puede_borrar_laboratorios(engine_plataforma):
    with pytest.raises(DBAPIError, match="permission denied"):
        async with engine_plataforma.begin() as conexion:
            await conexion.execute(text("DELETE FROM plataforma.laboratorios WHERE tenant_id = 'lab_canc'"))


async def test_funcion_de_resolucion_no_devuelve_cancelados(engine_app):
    async with engine_app.connect() as conexion:
        filas = (await conexion.execute(text("SELECT * FROM acceso.resolver_laboratorio('lab-canc')"))).all()
    assert filas == []


async def test_funcion_de_resolucion_es_security_definer_con_search_path_fijo(engine_owner):
    async with engine_owner.connect() as conexion:
        fila = (
            await conexion.execute(
                text(
                    "SELECT p.prosecdef, p.proconfig, has_function_privilege('public', p.oid, 'EXECUTE') AS publico"
                    " FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace"
                    " WHERE n.nspname = 'acceso' AND p.proname = 'resolver_laboratorio'"
                )
            )
        ).one()
    assert fila.prosecdef is True
    assert any(c.startswith("search_path=") for c in fila.proconfig)
    assert fila.publico is False


def _laboratorio(**cambios) -> dict:
    datos = {
        "t": "lab_nuevo",
        "s": "lab-nuevo",
        "n": "Laboratorio Nuevo",
        "nit": "900000099",
        "p": "COL",
    }
    datos.update(cambios)
    return datos


INSERTAR = text(
    "INSERT INTO plataforma.laboratorios (tenant_id, subdominio, nombre_comercial, identificador_fiscal, pais)"
    " VALUES (:t, :s, :n, :nit, :p)"
)


@pytest.mark.parametrize(
    ("cambios", "error"),
    [
        ({"s": "admin"}, "check"),
        ({"s": "www"}, "check"),
        ({"s": "Lab-Mayus"}, "check"),
        ({"s": "lab_guion_bajo"}, "check"),
        ({"s": "-lab"}, "check"),
        ({"t": "Lab A"}, "check"),
        ({"t": "1lab"}, "check"),
        ({"s": "lab-a"}, "unique"),
        ({"t": "lab_a"}, "unique"),
        ({"nit": "900000001"}, "unique"),
        ({"n": "X"}, "check"),
    ],
)
async def test_restricciones_de_laboratorios(engine_plataforma, cambios, error):
    with pytest.raises(DBAPIError, match=f"(?i){error}"):
        async with engine_plataforma.begin() as conexion:
            await conexion.execute(INSERTAR, _laboratorio(**cambios))


async def test_no_se_registran_laboratorios_en_paises_no_habilitados(engine_owner, engine_plataforma):
    async with engine_owner.begin() as conexion:
        await conexion.execute(
            text(
                'INSERT INTO "global".paises (codigo, codigo_iso2, nombre, moneda, zona_horaria, idioma)'
                " VALUES ('ZZZ', 'ZZ', 'País de prueba', 'USD', 'UTC', 'es-ZZ') ON CONFLICT DO NOTHING"
            )
        )
    try:
        with pytest.raises(DBAPIError, match="no está habilitado"):
            async with engine_plataforma.begin() as conexion:
                await conexion.execute(INSERTAR, _laboratorio(p="ZZZ"))
    finally:
        async with engine_owner.begin() as conexion:
            await conexion.execute(text("DELETE FROM \"global\".paises WHERE codigo = 'ZZZ'"))


async def test_colombia_es_el_unico_pais_habilitado(engine_app):
    async with engine_app.connect() as conexion:
        habilitados = (await conexion.execute(text('SELECT codigo FROM "global".paises WHERE habilitado'))).scalars()
        assert list(habilitados) == ["COL"]
        zona_valida = await conexion.scalar(
            text('SELECT bool_and(zona_horaria IN (SELECT name FROM pg_timezone_names)) FROM "global".paises')
        )
    assert zona_valida is True
