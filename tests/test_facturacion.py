"""Facturación de la plataforma (etapa 5; spec funcional/0005, sección 4).

- Cálculos en Decimal, con propiedades verificadas por hypothesis.
- Saldo y estado con pagos parciales: el modelo en Python y el trigger de la base coinciden (hypothesis).
- Un pago no supera el saldo, ni con pagos concurrentes; facturas y pagos solo se anulan.
- Al quedar pagada, la suscripción se extiende hasta el final del periodo.
"""

import asyncio
from datetime import date, timedelta
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.admin import facturacion
from app.admin.facturacion import ErrorFacturacion, calcular_importes, estado_por_pagos, leer_valor
from app.core import db
from tests.ayudas import cliente_admin, csrf, nuevo_laboratorio
from tests.conftest import correr, ejecutar_en_plataforma

MAESTRO = "maestro@plataforma.test"
FINANCIERO = "financiero@plataforma.test"
COMERCIAL = "comercial@plataforma.test"
PRECIO_MENSUAL = Decimal("100000.00")


# --- Cálculos puros ---


def test_ejemplo_de_importes():
    importes = calcular_importes(Decimal("100000"), Decimal("10"), Decimal("19"))
    assert (importes.descuento, importes.subtotal, importes.impuesto, importes.total) == (
        Decimal("10000.00"),
        Decimal("90000.00"),
        Decimal("17100.00"),
        Decimal("107100.00"),
    )


def test_redondeo_al_medio_hacia_arriba():
    importes = calcular_importes(Decimal("0.05"), Decimal("50"), Decimal("0"))
    assert importes.descuento == Decimal("0.03")  # 0.025 → 0.03


dinero = st.decimals(min_value=Decimal("0.01"), max_value=Decimal("9999999.99"), places=2)
porcentaje = st.decimals(min_value=Decimal("0"), max_value=Decimal("99.99"), places=2)


@given(valor=dinero, descuento=porcentaje, impuesto=porcentaje, decimales=st.sampled_from([0, 2]))
def test_propiedades_de_los_importes(valor, descuento, impuesto, decimales):
    i = calcular_importes(valor, descuento, impuesto, decimales)
    assert i.subtotal == i.valor_lista - i.descuento
    assert i.total == i.subtotal + i.impuesto
    assert Decimal(0) <= i.descuento <= i.valor_lista
    assert i.impuesto >= 0 and i.total >= i.subtotal
    for v in (i.valor_lista, i.descuento, i.subtotal, i.impuesto, i.total):
        assert -v.as_tuple().exponent <= decimales


@given(total=dinero, fracciones=st.lists(st.integers(min_value=1, max_value=100), max_size=8))
def test_saldo_con_pagos_parciales(total, fracciones):
    """Pagos que suman como máximo el total: saldo = total − pagado; estado según lo pagado."""
    pagos, restante = [], total
    for f in fracciones:
        valor = (restante * f / 100).quantize(Decimal("0.01"))
        if valor <= 0:
            continue
        pagos.append(valor)
        restante -= valor
    saldo, estado = estado_por_pagos(total, pagos)
    assert saldo == total - sum(pagos, Decimal(0))
    assert Decimal(0) <= saldo <= total
    assert estado == ("PENDIENTE" if not pagos else "PAGADA" if saldo == 0 else "PAGADA_PARCIAL")


@given(total=dinero, exceso=dinero)
def test_ningun_pago_supera_el_saldo(total, exceso):
    with pytest.raises(ErrorFacturacion):
        estado_por_pagos(total, [total + exceso])
    with pytest.raises(ErrorFacturacion):
        estado_por_pagos(total, [Decimal(0)])


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("150000", Decimal("150000")),
        ("150000.5", Decimal("150000.5")),
        (" 1.25 ", Decimal("1.25")),
        ("0", None),
        ("-5", None),
        ("1,5", None),
        ("1.234", None),
        ("1e5", None),
        ("NaN", None),
        ("", None),
        ("9" * 13, None),
    ],
)
def test_leer_valor(texto, esperado):
    assert leer_valor(texto) == esperado


# --- Base de datos ---


@pytest.fixture(scope="module", autouse=True)
def precios():
    """Precio vigente del plan completo en Colombia para las licencias facturables."""

    async def crear(sesion):
        for licencia, valor in (("MENSUAL", PRECIO_MENSUAL), ("ANUAL", Decimal("1000000.00"))):
            await sesion.execute(
                text(
                    "INSERT INTO plataforma.precios (pais, plan_id, tipo_licencia, moneda, valor, vigente_desde)"
                    " SELECT 'COL', id, :t, 'COP', :v, DATE '2026-01-01'"
                    " FROM plataforma.planes WHERE codigo = 'COMPLETO'"
                    " ON CONFLICT DO NOTHING"
                ),
                {"t": licencia, "v": valor},
            )

    correr(ejecutar_en_plataforma(crear))


def _generar(lab_uuid: str, licencia: str = "MENSUAL") -> str:
    async def generar(sesion):
        return await facturacion.generar_factura(sesion, lab_uuid, licencia)

    return correr(ejecutar_en_plataforma(generar))


def _pagar(factura: str, valor: str, fecha: date | None = None) -> None:
    async def pagar(sesion):
        await facturacion.registrar_pago(
            sesion, factura, Decimal(valor), "TRANSFERENCIA", "REF-1", fecha or date.today()
        )

    correr(ejecutar_en_plataforma(pagar))


def _factura(factura: str) -> dict:
    async def leer(sesion):
        return dict(
            (
                await sesion.execute(
                    text(
                        "SELECT f.total, f.saldo, f.estado, f.periodo_desde, f.periodo_hasta, s.fin,"
                        " s.estado AS suscripcion, s.tipo_licencia FROM plataforma.facturas f"
                        " JOIN plataforma.suscripciones s ON s.id = f.suscripcion_id"
                        " WHERE f.uuid = :f"
                    ),
                    {"f": factura},
                )
            )
            .mappings()
            .one()
        )

    return correr(ejecutar_en_plataforma(leer))


def test_factura_con_impuesto_del_pais_y_campana():
    lab = nuevo_laboratorio("MENSUAL")

    async def campana(sesion):
        return await sesion.scalar(
            text(
                "INSERT INTO plataforma.campanas (nombre, porcentaje, tipo_licencia, desde, hasta)"
                " VALUES ('Lanzamiento', 10, 'MENSUAL', current_date - 1, current_date + 1) RETURNING id"
            )
        )

    campana_id = correr(ejecutar_en_plataforma(campana))
    try:
        f = _factura(_generar(lab["uuid"]))
        # 100.000 − 10% = 90.000; IVA de Colombia (19%) = 17.100.
        assert (f["total"], f["saldo"], f["estado"]) == (Decimal("107100.00"), Decimal("107100.00"), "PENDIENTE")
        # El periodo empieza donde termina la suscripción vigente (7 días de gracia del alta).
        assert f["periodo_desde"] == f["fin"]
    finally:

        async def apagar(sesion):
            await sesion.execute(text("UPDATE plataforma.campanas SET activa = false WHERE id = :c"), {"c": campana_id})

        correr(ejecutar_en_plataforma(apagar))


def test_pagos_parciales_y_extension_de_la_suscripcion():
    lab = nuevo_laboratorio("MENSUAL")
    factura = _generar(lab["uuid"])
    total = _factura(factura)["total"]
    _pagar(factura, "50000")
    f = _factura(factura)
    assert (f["saldo"], f["estado"]) == (total - Decimal("50000"), "PAGADA_PARCIAL")
    fin_antes = f["fin"]
    with pytest.raises(ErrorFacturacion, match="excede"):
        _pagar(factura, str(f["saldo"] + Decimal("0.01")))
    _pagar(factura, str(f["saldo"]))
    f = _factura(factura)
    assert (f["saldo"], f["estado"]) == (Decimal(0), "PAGADA")
    # Pagada: la suscripción queda activa hasta el final del periodo facturado.
    assert f["fin"] == f["periodo_hasta"] > fin_antes
    assert (f["suscripcion"], f["tipo_licencia"]) == ("ACTIVA", "MENSUAL")
    # Ya no admite más pagos ni se puede volver a facturar el mismo periodo… pero sí el siguiente.
    with pytest.raises(ErrorFacturacion):
        _pagar(factura, "1")
    siguiente = _factura(_generar(lab["uuid"]))
    assert siguiente["periodo_desde"] == f["periodo_hasta"]
    with pytest.raises(ErrorFacturacion, match="periodo_facturado"):
        _generar(lab["uuid"])


def test_anular_pago_y_factura():
    lab = nuevo_laboratorio("MENSUAL")
    factura = _generar(lab["uuid"])
    _pagar(factura, "1000")

    async def pago(sesion):
        return await sesion.scalar(
            text(
                "SELECT p.uuid::text FROM plataforma.pagos p"
                " JOIN plataforma.facturas f ON f.id = p.factura_id WHERE f.uuid = :f"
            ),
            {"f": factura},
        )

    pago_uuid = correr(ejecutar_en_plataforma(pago))

    async def anular_factura(sesion):
        await facturacion.anular_factura(sesion, factura, "Error de digitación")

    with pytest.raises(ErrorFacturacion, match="anular_factura"):
        correr(ejecutar_en_plataforma(anular_factura))  # tiene un pago vigente

    async def anular_pago(sesion):
        await facturacion.anular_pago(sesion, pago_uuid, "Pago duplicado")

    correr(ejecutar_en_plataforma(anular_pago))
    assert _factura(factura)["estado"] == "PENDIENTE"
    with pytest.raises(ErrorFacturacion, match="anular_pago"):
        correr(ejecutar_en_plataforma(anular_pago))  # ya anulado
    correr(ejecutar_en_plataforma(anular_factura))
    f = _factura(factura)
    assert (f["estado"], f["saldo"]) == ("ANULADA", Decimal(0))
    with pytest.raises(ErrorFacturacion, match="anulada"):
        _pagar(factura, "1")

    async def motivo_corto(sesion):
        await facturacion.anular_pago(sesion, pago_uuid, "x")

    with pytest.raises(ErrorFacturacion, match="motivo"):
        correr(ejecutar_en_plataforma(motivo_corto))


@pytest.mark.parametrize(
    ("licencia", "clave"),
    [("DEMO", "licencia"), ("NO_EXISTE", "licencia")],
)
def test_no_se_factura_una_licencia_sin_cobro(licencia, clave):
    lab = nuevo_laboratorio()
    with pytest.raises(ErrorFacturacion, match=clave):
        _generar(lab["uuid"], licencia)


def test_sin_precio_no_hay_factura():
    lab = nuevo_laboratorio()

    async def plan_sin_precio(sesion):
        plan = await sesion.scalar(
            text("INSERT INTO plataforma.planes (codigo, nombre) VALUES (:c, 'Sin precio') RETURNING id"),
            {"c": "SINPRECIO_" + lab["tenant"][-8:].upper()},
        )
        await sesion.execute(
            text("UPDATE plataforma.laboratorios SET plan_id = :p WHERE uuid = :l"), {"p": plan, "l": lab["uuid"]}
        )

    correr(ejecutar_en_plataforma(plan_sin_precio))
    with pytest.raises(ErrorFacturacion, match="sin_precio"):
        _generar(lab["uuid"])


@pytest.mark.parametrize(
    ("medio", "fecha", "clave"),
    [("CHEQUE", date.today(), "medio"), ("EFECTIVO", date.today() + timedelta(days=5), "fecha")],
)
def test_pago_valida_medio_y_fecha(medio, fecha, clave):
    lab = nuevo_laboratorio("MENSUAL")
    factura = _generar(lab["uuid"])

    async def pagar(sesion):
        await facturacion.registrar_pago(sesion, factura, Decimal("1"), medio, "", fecha)

    with pytest.raises(ErrorFacturacion, match=clave):
        correr(ejecutar_en_plataforma(pagar))


@settings(max_examples=12, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(pagos=st.lists(st.decimals(min_value=Decimal("0.01"), max_value=Decimal("80000"), places=2), max_size=5))
def test_la_base_y_el_modelo_coinciden(pagos):
    """Secuencias de pagos (algunos superan el saldo y se rechazan): la base termina igual que el modelo."""
    lab = nuevo_laboratorio("MENSUAL")
    factura = _generar(lab["uuid"])
    total = _factura(factura)["total"]
    aceptados = []
    for valor in pagos:
        try:
            estado_por_pagos(total, [*aceptados, valor])
            esperado_aceptado = True
        except ErrorFacturacion:
            esperado_aceptado = False
        try:
            _pagar(factura, str(valor))
            aceptado = True
        except ErrorFacturacion:
            aceptado = False
        assert aceptado == esperado_aceptado
        if aceptado:
            aceptados.append(valor)
    saldo, estado = estado_por_pagos(total, aceptados)
    f = _factura(factura)
    assert (f["saldo"], f["estado"]) == (saldo, estado)


@pytest.mark.anyio
async def test_pagos_concurrentes_no_superan_el_saldo():
    lab = await asyncio.to_thread(nuevo_laboratorio, "MENSUAL")
    factura = await asyncio.to_thread(_generar, lab["uuid"])
    total = (await asyncio.to_thread(_factura, factura))["total"]

    async def pagar_todo():
        try:
            async with db.sesion_plataforma() as sesion:
                await facturacion.registrar_pago(sesion, factura, total, "EFECTIVO", "", date.today())
            return True
        except ErrorFacturacion:
            return False

    resultados = await asyncio.gather(*(pagar_todo() for _ in range(4)))
    await db.cerrar()
    assert sorted(resultados) == [False, False, False, True]
    f = await asyncio.to_thread(_factura, factura)
    assert (f["saldo"], f["estado"]) == (Decimal(0), "PAGADA")


@pytest.mark.anyio
@pytest.mark.parametrize(
    "sentencia",
    [
        "UPDATE plataforma.facturas SET total = 1",
        "UPDATE plataforma.facturas SET saldo = 0",
        "DELETE FROM plataforma.facturas",
        "UPDATE plataforma.pagos SET valor = 1",
        "DELETE FROM plataforma.pagos",
        "UPDATE plataforma.tipos_licencia SET duracion = interval '10 years'",
    ],
)
async def test_la_plataforma_no_edita_facturas_ni_pagos(engine_plataforma, sentencia):
    with pytest.raises(DBAPIError, match="permission denied"):
        async with engine_plataforma.begin() as conexion:
            await conexion.execute(text(sentencia))


@pytest.mark.anyio
async def test_ni_el_dueno_cambia_los_valores_de_una_factura(engine_owner):
    lab = await asyncio.to_thread(nuevo_laboratorio, "MENSUAL")
    factura = await asyncio.to_thread(_generar, lab["uuid"])
    for sentencia, mensaje in (
        ("UPDATE plataforma.facturas SET total = total + 1, saldo = saldo + 1 WHERE uuid = :f", "no se modifican"),
        ("DELETE FROM plataforma.facturas WHERE uuid = :f", "solo inserción"),
    ):
        with pytest.raises(DBAPIError, match=mensaje):
            async with engine_owner.begin() as conexion:
                await conexion.execute(text(sentencia), {"f": factura})


# --- Rutas del Admin Hub ---


def test_flujo_de_facturacion_en_el_admin_hub(buzon):
    lab = nuevo_laboratorio("MENSUAL")
    c = cliente_admin(FINANCIERO, buzon)
    respuesta = c.post(
        f"/laboratorios/{lab['uuid']}/facturas",
        data={"tipo_licencia": "MENSUAL", "csrf": csrf(c, f"/laboratorios/{lab['uuid']}")},
    )
    assert respuesta.status_code == 303 and respuesta.headers["location"].startswith("/facturas/")
    ruta = respuesta.headers["location"]
    pagina = c.get(ruta)
    assert pagina.status_code == 200 and "COP 119.000,00" in pagina.text  # 100.000 + 19% IVA
    datos = {"valor": "19000", "medio": "TRANSFERENCIA", "referencia": "TRX-1", "recibido_en": date.today().isoformat()}
    assert c.post(f"{ruta}/pagos", data={**datos, "csrf": csrf(c, ruta)}).status_code == 303
    assert "PAGADA_PARCIAL" in c.get(ruta).text
    for malo in ({"valor": "1,5"}, {"valor": "200000"}, {"recibido_en": "ayer"}, {"medio": "TRUEQUE"}):
        respuesta = c.post(f"{ruta}/pagos", data={**datos, **malo, "csrf": csrf(c, ruta)})
        assert respuesta.status_code == 400
    assert "PLT-" in c.get("/facturas").text
    assert c.get("/facturas?estado=PAGADA_PARCIAL").status_code == 200
    assert c.get("/facturas?estado=<script>").status_code == 200  # filtro desconocido: se ignora


def test_errores_de_facturacion_se_muestran_en_el_laboratorio(buzon):
    lab = nuevo_laboratorio("DEMO")
    c = cliente_admin(FINANCIERO, buzon)
    respuesta = c.post(
        f"/laboratorios/{lab['uuid']}/facturas", data={"tipo_licencia": "DEMO", "csrf": csrf(c, "/facturas")}
    )
    assert respuesta.headers["location"].endswith("?error=licencia")
    assert "licencia facturable" in c.get(respuesta.headers["location"]).text
    # Un error inventado no se muestra ni rompe la página.
    assert c.get(f"/laboratorios/{lab['uuid']}?error=<script>").status_code == 200


@pytest.mark.parametrize(
    ("email", "ruta", "esperado"),
    [
        (FINANCIERO, "/facturas", 200),
        (FINANCIERO, "/precios", 200),
        (COMERCIAL, "/facturas", 403),
        (COMERCIAL, "/precios", 403),
        ("maestro@plataforma.test", "/facturas", 200),
    ],
)
def test_permisos_de_facturacion(buzon, email, ruta, esperado):
    assert cliente_admin(email, buzon).get(ruta).status_code == esperado


def _fecha_unica() -> str:
    """Fecha futura distinta en cada corrida: los precios no se borran (la base guarda su historia)."""
    import random

    return (date(2030, 1, 1) + timedelta(days=random.randrange(20000))).isoformat()  # noqa: S311


def test_precios_y_campanas_desde_el_admin_hub(buzon):
    c = cliente_admin(MAESTRO, buzon)
    pagina = c.get("/precios").text
    plan = __import__("re").search(r'name="plan"><option value="([0-9a-f-]{36})"', pagina).group(1)
    datos = {
        "pais": "COL",
        "plan": plan,
        "tipo_licencia": "ANUAL",
        "moneda": "COP",
        "valor": "950000",
        "vigente_desde": _fecha_unica(),
    }
    assert c.post("/precios", data={**datos, "csrf": csrf(c, "/precios")}).status_code == 303
    assert c.post("/precios", data={**datos, "csrf": csrf(c, "/precios")}).status_code == 400  # repetido
    for malo in ({"valor": "-1"}, {"vigente_desde": "mañana"}, {"plan": "no-uuid"}, {"pais": "XXX"}):
        assert c.post("/precios", data={**datos, **malo, "csrf": csrf(c, "/precios")}).status_code == 400

    campana = {
        "nombre": "Promo prueba",
        "porcentaje": "15",
        "tipo_licencia": "",
        "desde": "2030-01-01",
        "hasta": "2030-01-31",
    }
    assert c.post("/campanas", data={**campana, "csrf": csrf(c, "/precios")}).status_code == 303
    for malo in ({"porcentaje": "100"}, {"hasta": "2029-12-31"}, {"nombre": "x"}, {"tipo_licencia": "INVENTADA"}):
        assert c.post("/campanas", data={**campana, **malo, "csrf": csrf(c, "/precios")}).status_code == 400
    uuid_campana = __import__("re").search(r"/campanas/([0-9a-f-]{36})/desactivar", c.get("/precios").text).group(1)
    assert c.post(f"/campanas/{uuid_campana}/desactivar", data={"csrf": csrf(c, "/precios")}).status_code == 303
    otra = "00000000-0000-0000-0000-000000000000"
    assert c.post(f"/campanas/{otra}/desactivar", data={"csrf": csrf(c, "/precios")}).status_code == 404


def test_anulaciones_desde_el_admin_hub(buzon):
    lab = nuevo_laboratorio("MENSUAL")
    factura = _generar(lab["uuid"])
    _pagar(factura, "10")
    c = cliente_admin(MAESTRO, buzon)
    ruta = f"/facturas/{factura}"
    pago = __import__("re").search(r"/pagos/([0-9a-f-]{36})/anular", c.get(ruta).text).group(1)
    assert c.post(f"{ruta}/anular", data={"motivo": "Prueba de anulación", "csrf": csrf(c, ruta)}).status_code == 400
    ajena = _generar(nuevo_laboratorio("MENSUAL")["uuid"])
    # El pago debe pertenecer a la factura de la ruta.
    assert (
        c.post(f"/facturas/{ajena}/pagos/{pago}/anular", data={"motivo": "Cruce", "csrf": csrf(c, ruta)}).status_code
        == 404
    )
    assert (
        c.post(f"{ruta}/pagos/{pago}/anular", data={"motivo": "Pago duplicado", "csrf": csrf(c, ruta)}).status_code
        == 303
    )
    assert c.post(f"{ruta}/anular", data={"motivo": "Prueba de anulación", "csrf": csrf(c, ruta)}).status_code == 303
    assert "ANULADA" in c.get(ruta).text
    assert c.get("/facturas/00000000-0000-0000-0000-000000000000").status_code == 404
