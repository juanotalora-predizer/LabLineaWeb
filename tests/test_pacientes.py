"""Pacientes y Ley 1581 (etapa 7, spec funcional/0010): registro con autorización, búsqueda sin
enumeración, revocación, solicitudes del titular, supresión, aislamiento, permisos y auditoría.

Usa los pacientes sintéticos de la corrida (PACIENTES_SINTETICOS): sus identificadores no pueden
aparecer en ningún log, y eso se verifica al terminar la sesión de pruebas.
"""

import re
import uuid
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.pacientes import servicio
from scripts.sinteticos import generar_personas
from tests.ayudas import autenticar, cliente, csrf
from tests.conftest import PACIENTES_SINTETICOS, correr, ejecutar_en_tenant

TEXTO = (
    "Autorizo al Laboratorio Sintético a tratar mis datos personales y de salud para prestar el servicio,"
    " con los derechos de la Ley 1581 de 2012."
)
REPRESENTANTE = {
    "representante_nombre": "Representante Sintético",
    "representante_documento": "99000001",
    "representante_parentesco": "Madre",
}
HOY = date(2026, 10, 13)


# --- Reglas sin HTTP ---


def _config(**cambios) -> servicio.ConfigPais:
    base = {
        "tipos": {"CC": ("Cédula", "^[0-9]{3,12}$"), "PA": ("Pasaporte", "^[A-Z0-9-]{3,20}$")},
        "paises": {"COL": "Colombia", "VEN": "Venezuela"},
        "mayoria_edad": 18,
        "plazo_consulta": 10,
        "plazo_reclamo": 15,
    }
    return servicio.ConfigPais(**{**base, **cambios})


def _formulario(**cambios) -> dict:
    base = {
        "tipo_documento": "CC",
        "numero_documento": "99.123.456",
        "nombres": "  Ana   María ",
        "apellidos": "Gómez",
        "sexo": "F",
        "fecha_nacimiento": "1990-02-28",
        "pais": "COL",
        "email": "Ana@Sintetico.test",
        "telefono": "300 000 1234",
        "direccion": "",
    }
    return {**base, **cambios}


def test_validar_limpia_los_datos():
    limpio, errores = servicio.validar(_formulario(), _config(), HOY)
    assert errores == []
    assert limpio["numero_documento"] == "99123456" and limpio["nombres"] == "Ana María"
    assert limpio["email"] == "ana@sintetico.test" and limpio["direccion"] is None
    assert limpio["fecha_nacimiento"] == date(1990, 2, 28)


@pytest.mark.parametrize(
    ("cambios", "error"),
    [
        ({"tipo_documento": "XX"}, "error_tipo_documento"),
        ({"numero_documento": "ABC123"}, "error_documento"),
        ({"numero_documento": "12"}, "error_documento"),
        ({"tipo_documento": "PA", "numero_documento": "a$b"}, "error_documento"),
        ({"nombres": " "}, "error_nombres"),
        ({"apellidos": "x" * 81}, "error_apellidos"),
        ({"sexo": "X"}, "error_sexo"),
        ({"fecha_nacimiento": "2030-01-01"}, "error_nacimiento"),
        ({"fecha_nacimiento": "1800-01-01"}, "error_nacimiento"),
        ({"fecha_nacimiento": "2026-02-30"}, "error_nacimiento"),
        ({"fecha_nacimiento": "13/10/2000"}, "error_nacimiento"),
        ({"pais": "ZZZ"}, "error_pais"),
        ({"email": "sin-arroba"}, "error_email"),
        ({"telefono": "llámame"}, "error_telefono"),
        ({"direccion": "x" * 201}, "error_direccion"),
    ],
)
def test_validar_rechaza(cambios, error):
    assert error in servicio.validar(_formulario(**cambios), _config(), HOY)[1]


def test_pasaporte_alfanumerico():
    limpio, errores = servicio.validar(_formulario(tipo_documento="PA", numero_documento="ab-12 345"), _config(), HOY)
    assert errores == [] and limpio["numero_documento"] == "AB-12345"


def test_edad_y_menor():
    assert servicio.edad_anios(date(2008, 10, 14), HOY) == 17
    assert servicio.edad_anios(date(2008, 10, 13), HOY) == 18
    assert servicio.es_menor(date(2008, 10, 14), HOY, 18)
    assert not servicio.es_menor(date(2008, 10, 13), HOY, 18)
    assert not servicio.es_menor(None, HOY, 18)


def test_representante_obligatorio_solo_para_menores():
    assert servicio.validar_representante(REPRESENTANTE, menor=False) == (dict.fromkeys(REPRESENTANTE), [])
    assert servicio.validar_representante(REPRESENTANTE, menor=True)[1] == []
    for campo in REPRESENTANTE:
        assert servicio.validar_representante({**REPRESENTANTE, campo: ""}, menor=True)[1] == ["error_representante"]
    sucio = {**REPRESENTANTE, "representante_documento": "<script>"}
    assert servicio.validar_representante(sucio, menor=True)[1] == ["error_representante"]


@pytest.mark.parametrize(
    ("consulta", "modo"),
    [
        ("ab", None),
        ("  a  ", None),
        ("99123456", "documento"),
        ("99.123.456", "documento"),
        ("AB-1234", "documento"),
        ("Gómez", "nombre"),
        ("ana gómez", "nombre"),
        ("%_%", "nombre"),
    ],
)
def test_modo_de_busqueda(consulta, modo):
    assert servicio.modo_busqueda(consulta) == modo


# --- Base de datos ---


@pytest.fixture
def texto_publicado():
    """El laboratorio A tiene un texto de autorización publicado."""

    async def publicar(sesion):
        if not await sesion.scalar(text("SELECT count(*) FROM lab.textos_autorizacion")):
            await sesion.execute(
                text("INSERT INTO lab.textos_autorizacion (version, contenido) VALUES (1, :c)"), {"c": TEXTO}
            )

    # lab-b queda sin texto: así se prueba que sin él no se registran pacientes.
    correr(ejecutar_en_tenant("app", "lab_a", publicar))


def test_dias_habiles_de_colombia():
    async def sumar(sesion):
        consultas = [("2026-10-09", 10), ("2026-12-24", 1), ("2026-04-01", 1), ("2026-10-13", 0), ("2026-10-10", 1)]
        return [
            str(
                await sesion.scalar(
                    text("SELECT \"global\".sumar_dias_habiles('COL', :d, :n)"), {"d": date.fromisoformat(d), "n": n}
                )
            )
            for d, n in consultas
        ]

    # 12 de octubre, 25 de diciembre y jueves y viernes santos son festivos; los fines de semana no cuentan.
    assert correr(ejecutar_en_tenant("app", "lab_a", sumar)) == [
        "2026-10-26",
        "2026-12-28",
        "2026-04-06",
        "2026-10-13",
        "2026-10-13",
    ]


async def _insertar_paciente(sesion, documento: str, *, con_autorizacion: bool = True) -> int:
    paciente = await sesion.scalar(
        text(
            "INSERT INTO lab.pacientes (tipo_documento, numero_documento, nombres, apellidos, sexo,"
            " fecha_nacimiento, pais) VALUES ('CC', :d, 'Prueba', 'Sintética', 'F', DATE '1990-01-01', 'COL')"
            " RETURNING id"
        ),
        {"d": documento},
    )
    if con_autorizacion:
        await sesion.execute(
            text(
                "INSERT INTO lab.autorizaciones_datos (paciente_id, texto_id, medio)"
                " SELECT :p, max(id), 'FORMATO_FIRMADO' FROM lab.textos_autorizacion"
            ),
            {"p": paciente},
        )
    return paciente


def _documento() -> str:
    return "98" + str(uuid.uuid4().int)[:8]


def test_la_base_no_guarda_un_paciente_sin_autorizacion(texto_publicado):
    with pytest.raises(DBAPIError, match="sin autorización"):
        correr(
            ejecutar_en_tenant("app", "lab_a", lambda s: _insertar_paciente(s, _documento(), con_autorizacion=False))
        )


def test_reglas_de_la_autorizacion_en_la_base(texto_publicado):
    documento = _documento()
    correr(ejecutar_en_tenant("app", "lab_a", lambda s: _insertar_paciente(s, documento)))

    async def ejecutar(sql):
        async def funcion(sesion):
            paciente = await sesion.scalar(
                text("SELECT id FROM lab.pacientes WHERE numero_documento = :d"), {"d": documento}
            )
            await sesion.execute(text(sql), {"p": paciente})

        return await ejecutar_en_tenant("app", "lab_a", funcion)

    # Dos autorizaciones vigentes del mismo paciente: la base deja una.
    otra = (
        "INSERT INTO lab.autorizaciones_datos (paciente_id, texto_id, medio)"
        " SELECT :p, max(id), 'FORMATO_FIRMADO' FROM lab.textos_autorizacion"
    )
    with pytest.raises(DBAPIError, match="autorizacion_vigente_unica"):
        correr(ejecutar(otra))
    for sql in (
        "UPDATE lab.autorizaciones_datos SET medio = 'ACEPTACION_EN_PANTALLA' WHERE paciente_id = :p",
        "UPDATE lab.autorizaciones_datos SET otorgada_en = now() - interval '1 year' WHERE paciente_id = :p",
        "UPDATE lab.autorizaciones_datos SET representante_nombre = 'Otro' WHERE paciente_id = :p",
    ):
        with pytest.raises(DBAPIError, match="no se modifica"):
            correr(ejecutar(sql))
    revocar = "UPDATE lab.autorizaciones_datos SET revocada_en = now(), motivo_revocacion = 'x' WHERE paciente_id = :p"
    correr(ejecutar(revocar))
    with pytest.raises(DBAPIError, match="ya fue revocada"):
        correr(ejecutar("UPDATE lab.autorizaciones_datos SET motivo_revocacion = 'otro' WHERE paciente_id = :p"))
    for sql in (
        "DELETE FROM lab.pacientes WHERE id = :p",
        "DELETE FROM lab.autorizaciones_datos WHERE paciente_id = :p",
        "DELETE FROM lab.solicitudes_titular WHERE paciente_id = :p",
        "UPDATE lab.textos_autorizacion SET contenido = contenido || 'x' WHERE CAST(:p AS bigint) IS NOT NULL",
        "DELETE FROM lab.textos_autorizacion WHERE CAST(:p AS bigint) IS NOT NULL",
    ):
        with pytest.raises(DBAPIError, match="permission denied"):
            correr(ejecutar(sql))


def test_autorizacion_vigente_para_las_ordenes(texto_publicado):
    """La función que la etapa 8 exige al crear órdenes."""

    async def funcion(sesion):
        paciente = await _insertar_paciente(sesion, _documento())
        antes = await sesion.scalar(text("SELECT lab.autorizacion_vigente(:p)"), {"p": paciente})
        await sesion.execute(
            text(
                "UPDATE lab.autorizaciones_datos SET revocada_en = now(), motivo_revocacion = 'x'"
                " WHERE paciente_id = :p"
            ),
            {"p": paciente},
        )
        despues = await sesion.scalar(text("SELECT lab.autorizacion_vigente(:p)"), {"p": paciente})
        historia = await sesion.scalar(text("SELECT lab.paciente_tiene_historia(:p)"), {"p": paciente})
        return antes, despues, historia

    assert correr(ejecutar_en_tenant("app", "lab_a", funcion)) == (True, False, False)


def test_rls_impide_escribir_pacientes_de_otro_laboratorio(texto_publicado):
    async def funcion(sesion):
        await sesion.execute(
            text(
                "INSERT INTO lab.pacientes (tenant_id, tipo_documento, numero_documento, nombres, apellidos, sexo,"
                " fecha_nacimiento, pais) VALUES ('lab_b', 'CC', '123456', 'X', 'Y', 'F', DATE '1990-01-01', 'COL')"
            )
        )

    with pytest.raises(DBAPIError, match="row-level security"):
        correr(ejecutar_en_tenant("app", "lab_a", funcion))


# --- Interfaz ---


@pytest.fixture
def admin(buzon):
    return autenticar(cliente(), "admin@lab-a.test", buzon)


def _datos(persona, **cambios) -> dict:
    return {
        "tipo_documento": persona.tipo_documento,
        "numero_documento": persona.numero_documento,
        "nombres": persona.nombres,
        "apellidos": persona.apellidos,
        "sexo": persona.sexo,
        "fecha_nacimiento": persona.fecha_nacimiento.isoformat(),
        "pais": "COL",
        "email": persona.email,
        "telefono": persona.telefono,
        "direccion": "",
        "medio": "FORMATO_FIRMADO",
        "acepto": "si",
        **REPRESENTANTE,
        **cambios,
    }


def _persona(tipo: str = "CC"):
    return generar_personas(1, semilla=uuid.uuid4().int % 10**9, tipos_documento=(tipo,))[0]


def _registrar(c, persona, **cambios) -> str:
    respuesta = c.post("/pacientes/nuevo", data={**_datos(persona, **cambios), "csrf": csrf(c, "/pacientes/nuevo")})
    assert respuesta.status_code == 303, respuesta.text[-1500:]
    return respuesta.headers["location"]


async def _auditoria(sesion, tabla: str) -> list[str]:
    filas = await sesion.execute(
        text(
            "SELECT operacion || ' ' || coalesce(antes::text, '') || ' ' || coalesce(despues::text, '')"
            " FROM lab.auditoria WHERE tabla = :t ORDER BY id DESC LIMIT 50"
        ),
        {"t": tabla},
    )
    return list(filas.scalars())


def test_registro_completo_con_autorizacion(admin, texto_publicado):
    persona = PACIENTES_SINTETICOS[0]
    ficha = _registrar(admin, persona)
    pagina = admin.get(ficha)
    assert pagina.status_code == 200 and persona.apellidos in pagina.text
    assert "Vigente" in pagina.text and "Formato firmado" in pagina.text
    assert pagina.headers["cache-control"].startswith("no-store")
    # El correo se guarda en minúsculas; el documento, sin puntos.
    assert persona.email in pagina.text
    auditoria = correr(ejecutar_en_tenant("owner", "lab_a", lambda s: _auditoria(s, "pacientes")))
    # La auditoría registra la creación y la lectura de la ficha, sin copiar los datos personales.
    assert any(f.startswith("INSERT") and "[protegido]" in f for f in auditoria)
    assert any(f.startswith("READ") and '"ficha"' in f for f in auditoria)
    assert not any(persona.numero_documento in f or persona.apellidos in f for f in auditoria)


def test_registro_rechazado_no_guarda_nada(admin, texto_publicado):
    persona = _persona()
    url = "/pacientes/nuevo"
    for cambios in (
        {"acepto": ""},
        {"medio": "VERBAL"},
        {"numero_documento": "ABC"},
        {"fecha_nacimiento": "2999-01-01"},
        {"texto_version": "999"},
        {"pais": "ZZZ"},
    ):
        respuesta = admin.post(url, data={**_datos(persona, **cambios), "csrf": csrf(admin, url)})
        assert respuesta.status_code == 400, cambios
        assert persona.numero_documento not in respuesta.headers.get("location", "")

    async def contar(sesion):
        return await sesion.scalar(
            text("SELECT count(*) FROM lab.pacientes WHERE numero_documento = :d"), {"d": persona.numero_documento}
        )

    assert correr(ejecutar_en_tenant("app", "lab_a", contar)) == 0


def test_menor_de_edad_exige_representante(admin, texto_publicado):
    persona = _persona("TI")
    menor = {"fecha_nacimiento": "2015-06-01"}
    url = "/pacientes/nuevo"
    sin = {**_datos(persona, **menor), "representante_nombre": "", "csrf": csrf(admin, url)}
    respuesta = admin.post(url, data=sin)
    assert respuesta.status_code == 400 and "representante legal" in respuesta.text
    ficha = _registrar(admin, persona, **menor)
    pagina = admin.get(ficha).text
    assert "Menor de edad" in pagina and "Por su representante (Madre)" in pagina


def test_documento_repetido(admin, texto_publicado):
    persona = _persona()
    _registrar(admin, persona)
    url = "/pacientes/nuevo"
    respuesta = admin.post(url, data={**_datos(persona, nombres="Otra"), "csrf": csrf(admin, url)})
    assert respuesta.status_code == 400 and "Ya existe un paciente" in respuesta.text
    # El mismo número con otro tipo de documento es otra persona.
    _registrar(admin, persona, tipo_documento="CE")


def test_sin_texto_publicado_no_se_registra(buzon):
    """lab-b sin texto: aviso en la búsqueda y el registro, y 400 al intentar."""

    async def tiene_texto(sesion):
        return await sesion.scalar(text("SELECT count(*) FROM lab.textos_autorizacion"))

    if correr(ejecutar_en_tenant("app", "lab_b", tiene_texto)):
        pytest.skip("lab-b ya tiene texto publicado en esta corrida")
    c = autenticar(cliente("lab-b"), "admin@lab-b.test", buzon, laboratorio="lab_b")
    assert "no ha publicado el texto" in c.get("/pacientes").text
    assert "no ha publicado el texto" in c.get("/pacientes/nuevo").text
    respuesta = c.post("/pacientes/nuevo", data={**_datos(_persona()), "csrf": csrf(c, "/pacientes")})
    assert respuesta.status_code == 400


def test_texto_de_autorizacion_versionado(admin):
    pagina = admin.get("/configuracion/autorizacion")
    assert pagina.status_code == 200
    token = csrf(admin, "/configuracion/autorizacion")

    async def ultima(sesion):
        return await sesion.scalar(text("SELECT coalesce(max(version), 0) FROM lab.textos_autorizacion"))

    antes = correr(ejecutar_en_tenant("app", "lab_a", ultima))
    for contenido, error in (
        ("corto", "entre 50"),
        ("Modelo con campos sin completar: [correo del laboratorio] " + "x" * 50, "Complete los campos"),
    ):
        respuesta = admin.post("/configuracion/autorizacion", data={"contenido": contenido, "csrf": token})
        assert respuesta.status_code == 400 and error in respuesta.text
    nuevo = f"{TEXTO}\nVersión de prueba {uuid.uuid4().hex}.\nCon saltos de línea."
    assert admin.post("/configuracion/autorizacion", data={"contenido": nuevo, "csrf": token}).status_code == 303
    assert correr(ejecutar_en_tenant("app", "lab_a", ultima)) == antes + 1
    igual = admin.post("/configuracion/autorizacion", data={"contenido": nuevo, "csrf": token})
    assert igual.status_code == 400 and "igual a la versión vigente" in igual.text
    # El formulario de registro muestra la versión nueva.
    assert f"versión {antes + 1}" in admin.get("/pacientes/nuevo").text


def test_el_modelo_del_pais_parte_del_nombre_del_laboratorio(buzon):
    c = autenticar(cliente("lab-b"), "admin@lab-b.test", buzon, laboratorio="lab_b")

    async def tiene_texto(sesion):
        return await sesion.scalar(text("SELECT count(*) FROM lab.textos_autorizacion"))

    if correr(ejecutar_en_tenant("app", "lab_b", tiene_texto)):
        pytest.skip("lab-b ya tiene texto publicado en esta corrida")
    pagina = c.get("/configuracion/autorizacion").text
    assert "Laboratorio B" in pagina and "{laboratorio}" not in pagina and "Ley 1581" in pagina


# --- Búsqueda ---


def _buscar(c, consulta: str):
    return c.post("/pacientes/buscar", data={"consulta": consulta, "csrf": csrf(c, "/pacientes")})


def test_busqueda_por_documento_exacto_y_por_nombre(admin, texto_publicado):
    persona = PACIENTES_SINTETICOS[1]
    ficha = _registrar(admin, persona)
    assert ficha in _buscar(admin, persona.numero_documento).text
    # Con puntos de miles también.
    con_puntos = f"{int(persona.numero_documento):,}".replace(",", ".")
    assert ficha in _buscar(admin, con_puntos).text
    # Un prefijo del documento no encuentra nada: no se puede recorrer por partes.
    assert ficha not in _buscar(admin, persona.numero_documento[:-2]).text
    assert ficha in _buscar(admin, f"{persona.nombres} {persona.apellidos.split()[0]}").text
    assert ficha not in _buscar(admin, f"{persona.nombres} Inexistente").text
    corta = _buscar(admin, "ab")
    assert corta.status_code == 400 and "al menos 3" in corta.text
    # La búsqueda viaja en el cuerpo del POST, nunca en la URL; la auditoría no guarda el texto buscado.
    auditoria = correr(ejecutar_en_tenant("owner", "lab_a", lambda s: _auditoria(s, "pacientes")))
    busquedas = [f for f in auditoria if '"busqueda"' in f]
    assert busquedas and not any(persona.nombres in f or persona.numero_documento in f for f in busquedas)


def test_busqueda_con_comodines_e_inyeccion(admin, texto_publicado):
    for consulta in ("%%%", "___", "' OR 1=1 --", "a%' OR '1'='1", "\\\\\\", "x" * 80):
        respuesta = _buscar(admin, consulta)
        assert respuesta.status_code == 200, consulta
        assert "No se encontró ningún paciente" in respuesta.text, consulta
    assert (
        admin.post("/pacientes/buscar", data={"consulta": "a\x00b", "csrf": csrf(admin, "/pacientes")}).status_code
        == 400
    )


def test_busqueda_limita_resultados(admin, texto_publicado):
    # Solo letras: un texto con dígitos se busca como documento.
    apellido = "Limite" + "".join(chr(97 + int(c, 16) % 26) for c in uuid.uuid4().hex[:8])

    async def crear(sesion):
        for _ in range(servicio.MAX_RESULTADOS + 2):
            paciente = await _insertar_paciente(sesion, _documento())
            await sesion.execute(
                text("UPDATE lab.pacientes SET apellidos = :a WHERE id = :p"), {"a": apellido, "p": paciente}
            )

    correr(ejecutar_en_tenant("app", "lab_a", crear))
    respuesta = _buscar(admin, apellido)
    # Máximo 20 filas y un aviso para afinar, sin decir cuántos coinciden (no se puede contar pacientes).
    assert len(re.findall(r'href="/pacientes/[0-9a-f-]{36}"', respuesta.text)) == servicio.MAX_RESULTADOS
    assert "Afine la búsqueda" in respuesta.text


def test_demasiadas_busquedas(admin):
    token = csrf(admin, "/pacientes")
    for _ in range(servicio.LIMITE_BUSQUEDAS):
        assert admin.post("/pacientes/buscar", data={"consulta": "zzz", "csrf": token}).status_code == 200
    assert admin.post("/pacientes/buscar", data={"consulta": "zzz", "csrf": token}).status_code == 429


# --- Aislamiento y permisos ---


def test_paciente_de_otro_laboratorio_no_existe(admin, buzon, texto_publicado):
    ficha = _registrar(admin, _persona())
    paciente = ficha.rsplit("/", 1)[1]
    otro = autenticar(cliente("lab-b"), "admin@lab-b.test", buzon, laboratorio="lab_b")
    token = csrf(otro, "/pacientes")
    for ruta in (ficha, f"{ficha}/editar", f"{ficha}/datos"):
        assert otro.get(ruta).status_code == 404, ruta
    for ruta, datos in (
        (f"{ficha}/editar", _datos(_persona())),
        (f"{ficha}/revocar", {"canal": "PRESENCIAL", "motivo": "x"}),
        (f"{ficha}/autorizacion", {"medio": "FORMATO_FIRMADO", "acepto": "si"}),
        (f"{ficha}/solicitudes", {"tipo": "CONSULTA", "canal": "CORREO"}),
        (f"{ficha}/suprimir", {"solicitud": paciente, "confirmacion": "SUPRIMIR"}),
    ):
        assert otro.post(ruta, data={**datos, "csrf": token}).status_code == 404, ruta
    # Una solicitud de lab-a tampoco se resuelve desde lab-b.
    admin.post(f"{ficha}/solicitudes", data={"tipo": "CONSULTA", "canal": "CORREO", "csrf": csrf(admin, ficha)})
    solicitud = re.search(r"/pacientes/solicitudes/([0-9a-f-]{36})/resolver", admin.get(ficha).text).group(1)
    resolver = {"estado": "RESUELTA", "respuesta": "x", "csrf": token}
    assert otro.post(f"/pacientes/solicitudes/{solicitud}/resolver", data=resolver).status_code == 404
    assert ficha not in otro.get("/pacientes/solicitudes/abiertas").text


@pytest.mark.parametrize(
    ("email", "ruta", "metodo", "esperado"),
    [
        ("recepcion@lab-a.test", "/pacientes", "get", 200),
        ("recepcion@lab-a.test", "/pacientes/nuevo", "get", 200),
        ("auditor@lab-a.test", "/pacientes", "get", 200),
        ("auditor@lab-a.test", "/pacientes/nuevo", "get", 403),
        ("validador@lab-a.test", "/pacientes", "get", 200),
        ("paciente@lab-a.test", "/pacientes", "get", 403),
        ("recepcion@lab-a.test", "/configuracion/autorizacion", "get", 403),
        ("auditor@lab-a.test", "/configuracion/autorizacion", "post", 403),
    ],
)
def test_permisos(buzon, email, ruta, metodo, esperado):
    c = autenticar(cliente(), email, buzon)
    if metodo == "get":
        assert c.get(ruta).status_code == esperado
    else:
        token = csrf(c, "/panel")
        assert c.post(ruta, data={"contenido": TEXTO, "csrf": token}).status_code == esperado


def test_recepcion_registra_pero_no_suprime(buzon, texto_publicado):
    c = autenticar(cliente(), "recepcion@lab-a.test", buzon)
    ficha = _registrar(c, _persona())
    token = csrf(c, ficha)
    assert (
        c.post(f"{ficha}/solicitudes", data={"tipo": "SUPRESION", "canal": "CORREO", "csrf": token}).status_code == 303
    )
    assert "Suprimir los datos" not in c.get(ficha).text
    assert c.post(f"{ficha}/suprimir", data={"confirmacion": "SUPRIMIR", "csrf": token}).status_code == 403


# --- Revocación, solicitudes y edición ---


def _solicitudes(c, ficha) -> list[str]:
    return re.findall(r"/pacientes/solicitudes/([0-9a-f-]{36})/resolver", c.get(ficha).text)


def test_revocar_editar_con_solicitud_y_volver_a_autorizar(admin, texto_publicado):
    persona = PACIENTES_SINTETICOS[2]
    ficha = _registrar(admin, persona)
    token = csrf(admin, ficha)
    assert admin.post(f"{ficha}/revocar", data={"canal": "PRESENCIAL", "motivo": "", "csrf": token}).status_code == 400
    respuesta = admin.post(f"{ficha}/revocar", data={"canal": "PRESENCIAL", "motivo": "Lo pidió", "csrf": token})
    assert respuesta.status_code == 303
    pagina = admin.get(ficha).text
    assert "Sin autorización" in pagina and "Revocada" in pagina and "Revocación" in pagina
    assert admin.post(f"{ficha}/revocar", data={"canal": "PRESENCIAL", "motivo": "x", "csrf": token}).status_code == 400

    # Sin autorización, editar exige una solicitud de actualización o rectificación abierta.
    cambios = {k: v for k, v in _datos(persona, telefono="3000009999").items() if k not in ("medio", "acepto")}
    editar = f"{ficha}/editar"
    respuesta = admin.post(editar, data={**cambios, "csrf": token})
    assert respuesta.status_code == 400 and "elija la solicitud" in respuesta.text
    datos = {"tipo": "RECTIFICACION", "canal": "CORREO", "descripcion": "Corregir teléfono", "csrf": token}
    assert admin.post(f"{ficha}/solicitudes", data=datos).status_code == 303
    solicitud = re.search(r'<option value="([0-9a-f-]{36})"', admin.get(editar).text).group(1)
    assert admin.post(editar, data={**cambios, "solicitud": solicitud, "csrf": token}).status_code == 303
    pagina = admin.get(ficha).text
    assert "3000009999" in pagina and "Datos actualizados según la solicitud." in pagina
    # La solicitud ya quedó atendida: no sirve otra vez.
    assert admin.post(editar, data={**cambios, "solicitud": solicitud, "csrf": token}).status_code == 400

    # El titular vuelve a autorizar.
    nueva = {"medio": "ACEPTACION_EN_PANTALLA", "acepto": "si", **REPRESENTANTE, "csrf": token}
    assert admin.post(f"{ficha}/autorizacion", data=nueva).status_code == 303
    assert "Aceptación en pantalla" in admin.get(ficha).text
    assert admin.post(f"{ficha}/autorizacion", data=nueva).status_code == 400  # ya tiene una vigente
    # Con autorización vigente, editar no exige solicitud.
    assert admin.post(editar, data={**cambios, "telefono": "3000008888", "csrf": token}).status_code == 303


def test_solicitudes_con_vencimiento_y_respuesta(admin, texto_publicado):
    ficha = _registrar(admin, _persona())
    token = csrf(admin, ficha)
    for tipo in ("CONSULTA", "ACTUALIZACION"):
        datos = {"tipo": tipo, "canal": "CORREO", "descripcion": "Línea 1\nLínea 2", "csrf": token}
        assert admin.post(f"{ficha}/solicitudes", data=datos).status_code == 303
    for datos in (
        {"tipo": "REVOCACION", "canal": "CORREO"},
        {"tipo": "OTRA", "canal": "CORREO"},
        {"tipo": "CONSULTA", "canal": "FAX"},
    ):
        assert admin.post(f"{ficha}/solicitudes", data={**datos, "csrf": token}).status_code == 400

    async def vencimientos(sesion):
        filas = await sesion.execute(
            text(
                "SELECT s.tipo, s.vence_en = \"global\".sumar_dias_habiles('COL',"
                " (s.recibida_en AT TIME ZONE 'America/Bogota')::date, CASE s.tipo WHEN 'CONSULTA' THEN 10 ELSE 15 END)"
                " FROM lab.solicitudes_titular s JOIN lab.pacientes p ON p.id = s.paciente_id WHERE p.uuid = :u"
            ),
            {"u": ficha.rsplit("/", 1)[1]},
        )
        return dict(filas.all())

    assert correr(ejecutar_en_tenant("app", "lab_a", vencimientos)) == {"CONSULTA": True, "ACTUALIZACION": True}
    assert ficha.rsplit("/", 1)[1] in admin.get("/pacientes/solicitudes/abiertas").text
    primera = _solicitudes(admin, ficha)[0]
    resolver = f"/pacientes/solicitudes/{primera}/resolver"
    assert admin.post(resolver, data={"estado": "RESUELTA", "respuesta": "", "csrf": token}).status_code == 400
    assert admin.post(resolver, data={"estado": "OTRO", "respuesta": "x", "csrf": token}).status_code == 400
    assert (
        admin.post(resolver, data={"estado": "RECHAZADA", "respuesta": "No procede", "csrf": token}).status_code == 303
    )
    assert admin.post(resolver, data={"estado": "RESUELTA", "respuesta": "x", "csrf": token}).status_code == 400
    assert (
        admin.post(
            f"/pacientes/solicitudes/{uuid.uuid4()}/resolver",
            data={"estado": "RESUELTA", "respuesta": "x", "csrf": token},
        ).status_code
        == 404
    )


def test_informe_del_titular_queda_auditado(admin, texto_publicado):
    persona = PACIENTES_SINTETICOS[3]
    ficha = _registrar(admin, persona)
    pagina = admin.get(f"{ficha}/datos")
    assert pagina.status_code == 200
    # Incluye el texto de la versión que el titular aceptó (otra prueba pudo publicar más versiones).
    assert persona.numero_documento in pagina.text and "Texto de la autorización, versión" in pagina.text
    auditoria = correr(ejecutar_en_tenant("owner", "lab_a", lambda s: _auditoria(s, "pacientes")))
    assert any(f.startswith("EXPORT") and '"datos_titular"' in f for f in auditoria)


# --- Supresión ---


def _pedir_supresion(c, ficha) -> str:
    token = csrf(c, ficha)
    assert (
        c.post(
            f"{ficha}/solicitudes",
            data={"tipo": "SUPRESION", "canal": "CORREO", "descripcion": "Supriman mis datos", "csrf": token},
        ).status_code
        == 303
    )
    return re.search(r'name="solicitud"><option value="([0-9a-f-]{36})"', c.get(ficha).text).group(1)


def test_supresion_anonimiza_sin_dejar_datos(admin, texto_publicado):
    persona = PACIENTES_SINTETICOS[4]
    ficha = _registrar(admin, persona, fecha_nacimiento="2014-03-03")  # menor: con representante
    paciente_uuid = ficha.rsplit("/", 1)[1]
    solicitud = _pedir_supresion(admin, ficha)
    token = csrf(admin, ficha)
    suprimir = f"{ficha}/suprimir"
    assert admin.post(suprimir, data={"solicitud": solicitud, "confirmacion": "no", "csrf": token}).status_code == 400
    assert (
        admin.post(
            suprimir, data={"solicitud": str(uuid.uuid4()), "confirmacion": "SUPRIMIR", "csrf": token}
        ).status_code
        == 400
    )
    # El genérico de resolver no sirve para dar por resuelta una supresión.
    resolver = f"/pacientes/solicitudes/{solicitud}/resolver"
    assert admin.post(resolver, data={"estado": "RESUELTA", "respuesta": "x", "csrf": token}).status_code == 400
    respuesta = admin.post(suprimir, data={"solicitud": solicitud, "confirmacion": "suprimir", "csrf": token})
    assert respuesta.status_code == 303 and respuesta.headers["location"].endswith("?resultado=suprimido")
    pagina = admin.get(respuesta.headers["location"]).text
    assert "Registro suprimido" in pagina and "se suprimieron" in pagina
    assert persona.apellidos not in pagina and persona.numero_documento not in pagina
    assert (
        admin.post(suprimir, data={"solicitud": solicitud, "confirmacion": "SUPRIMIR", "csrf": token}).status_code
        == 400
    )
    assert admin.get(f"{ficha}/editar").status_code == 404
    assert paciente_uuid not in _buscar(admin, persona.numero_documento).text

    async def todo_del_paciente(sesion):
        filas = await sesion.execute(
            text(
                "SELECT row_to_json(p)::text FROM lab.pacientes p WHERE p.uuid = :u"
                " UNION ALL SELECT row_to_json(a)::text FROM lab.autorizaciones_datos a"
                "   JOIN lab.pacientes p ON p.id = a.paciente_id WHERE p.uuid = :u"
                " UNION ALL SELECT row_to_json(s)::text FROM lab.solicitudes_titular s"
                "   JOIN lab.pacientes p ON p.id = s.paciente_id WHERE p.uuid = :u"
                " UNION ALL SELECT coalesce(antes::text, '') || coalesce(despues::text, '') FROM lab.auditoria"
                "   WHERE tabla IN ('pacientes', 'autorizaciones_datos', 'solicitudes_titular')"
            ),
            {"u": paciente_uuid},
        )
        return "\n".join(filas.scalars())

    todo = correr(ejecutar_en_tenant("owner", "lab_a", todo_del_paciente))
    for dato in (
        *persona.identificadores(),
        persona.nombres,
        persona.fecha_nacimiento.isoformat(),
        "Representante Sintético",
        "Supriman mis datos",
    ):
        assert dato not in todo, dato
    assert '"estado":"SUPRIMIDO"' in todo


def test_supresion_con_historia_clinica_se_rechaza(admin, texto_publicado):
    ficha = _registrar(admin, _persona())
    solicitud = _pedir_supresion(admin, ficha)

    async def historia(valor: str):
        async def funcion(sesion):
            await sesion.execute(
                text(
                    "CREATE OR REPLACE FUNCTION lab.paciente_tiene_historia(p_paciente bigint) RETURNS boolean"
                    f" LANGUAGE sql STABLE AS $$ SELECT {valor} $$"
                )  # noqa: E501
            )

        await ejecutar_en_tenant("owner", "lab_a", funcion)

    correr(historia("true"))
    try:
        respuesta = admin.post(
            f"{ficha}/suprimir", data={"solicitud": solicitud, "confirmacion": "SUPRIMIR", "csrf": csrf(admin, ficha)}
        )
    finally:
        correr(historia("false"))
    assert respuesta.headers["location"].endswith("?resultado=rechazado")
    pagina = admin.get(respuesta.headers["location"]).text
    assert "historia clínica" in pagina and "Sin autorización" in pagina and "Rechazada" in pagina
    assert "Registro suprimido" not in pagina


def test_resultado_desconocido_no_muestra_nada(admin, texto_publicado):
    ficha = _registrar(admin, _persona())
    pagina = admin.get(f"{ficha}?resultado=<script>alert(1)</script>")
    assert (
        pagina.status_code == 200
        and "<script>alert" not in pagina.text
        and 'class="aviso" role="status"' not in pagina.text
    )
