"""Importador del catálogo de Lablinea (spec funcional/0009, sección 2).

1. `leer_paquete`: valida el ZIP en memoria (firma, tamaños, bomba ZIP, rutas, cifrado, solo CSV de tablas
   del catálogo, codificación, caracteres) y devuelve las filas de cada tabla. Si algo falla lanza
   `ArchivoRechazado` y no se guarda nada.
2. `analizar`: convierte las filas de Lablinea al modelo del catálogo y produce un `Plan` con errores
   (bloquean la carga) y advertencias (rangos para revisión, datos descartados).
3. `cargar`: inserta el plan en el laboratorio de la sesión, en una sola transacción.

Ningún archivo se escribe a disco. Las tablas que no son del catálogo (por ejemplo `paciente`) hacen que
el ZIP se rechace: el servidor no debe recibir ni guardar datos de pacientes en una importación de catálogo.
"""

import csv
import io
import re
import zipfile
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

MAX_ZIP = 10 * 1024 * 1024
MAX_TOTAL = 50 * 1024 * 1024
MAX_TABLA = 20 * 1024 * 1024
MAX_ENTRADAS = 30
MAX_PROPORCION = 100
MAX_FILAS = 50_000
MAX_CAMPO = 4_000
MAX_MENSAJES = 300
EDAD_MAXIMA_DIAS = 54750

# Tabla de Lablinea (nombre normalizado) → (nombre visible, obligatoria, columnas requeridas normalizadas)
TABLAS = {
    "seccion": ("seccion", True, ("codigo", "descripcion")),
    "analisis": ("analisis", True, ("consecutivo", "descripcion", "seccion")),
    "detalleanalisis": ("detalle analisis", True, ("consecutivo", "analisis", "descripcion")),
    "unidad": ("unidad", False, ("codigo", "descripcion")),
    "listadevalores": ("lista de valores", False, ("preguntaporanalisis", "valor")),
    "tipomuestra": ("tipo muestra", False, ("tipo", "descripcion")),
    "muestrasxanalisis": ("muestras x analisis", False, ("analisis", "tipodemuestra")),
    "tipotarifa": ("tipo tarifa", False, ("codigo", "descripcion")),
    "costoanalisis": ("costo analisis", False, ("tipotarifa", "analisis", "costo")),
    "tipocodigoalterno": ("Tipo Codigo Alterno", False, ("codigo", "descripcion")),
    "codigoanalisisxempresa": ("Codigo Analisis x Empresa", False, ("tipocodigoalterno", "analisis", "codigoalterno")),
}

_VERDADERO = {"true", "1", "-1", "si", "sí", "verdadero", "yes", "s"}
_RANGO_TEXTO = re.compile(r"^\s*(-?\d+(?:[.,]\d+)?)\s*(?:-|–|a|hasta)\s*(-?\d+(?:[.,]\d+)?)\b")
_MENOR = re.compile(r"^\s*(?:<|≤|<=|menor\s+(?:de|a|que)|hasta)\s*(-?\d+(?:[.,]\d+)?)", re.I)
_MAYOR = re.compile(r"^\s*(?:>|≥|>=|mayor\s+(?:de|a|que))\s*(-?\d+(?:[.,]\d+)?)", re.I)


class ArchivoRechazado(Exception):  # noqa: N818
    """El archivo no se puede procesar. `clave` es el texto del catálogo (importador.rechazo.*)."""

    def __init__(self, clave: str, **parametros: object) -> None:
        super().__init__(clave)
        self.clave = clave
        self.parametros = parametros


def normalizar(nombre: str) -> str:
    """Compara nombres sin mayúsculas, espacios, guiones ni signos ('Es titulo ?' → 'estitulo')."""
    return re.sub(r"[^a-z0-9]", "", nombre.lower())


# --- 1. Lectura segura del paquete ---


def _decodificar(datos: bytes, tabla: str) -> str:
    if b"\x00" in datos:  # binarios y UTF-16: no son una exportación de texto válida
        raise ArchivoRechazado("codificacion", tabla=tabla)
    for codificacion in ("utf-8-sig", "cp1252"):
        try:
            texto = datos.decode(codificacion)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ArchivoRechazado("codificacion", tabla=tabla)
    if any(ord(c) < 32 and c not in "\t\r\n" for c in texto) or "\x7f" in texto:
        raise ArchivoRechazado("caracteres", tabla=tabla)
    return texto


def _filas_csv(texto: str, tabla: str) -> list[dict[str, str]]:
    # Separador: el más frecuente en el encabezado (más predecible que adivinarlo con filas inconsistentes).
    primera = texto.split("\n", 1)[0]
    separador = max(",;\t", key=primera.count) if any(c in primera for c in ",;\t") else ","
    # Estricto: una comilla sin cerrar o mal ubicada es un error, no un campo que se traga el resto del archivo.
    lector = csv.reader(io.StringIO(texto, newline=""), delimiter=separador, strict=True)
    try:
        encabezado = next(lector, None)
        if not encabezado:
            return []
        columnas = [normalizar(c) for c in encabezado]
        filas = []
        for numero, valores in enumerate(lector, start=2):
            if not any(v.strip() for v in valores):
                continue
            if len(filas) >= MAX_FILAS:
                raise ArchivoRechazado("demasiadas_filas", tabla=tabla, maximo=MAX_FILAS)
            if len(valores) != len(columnas):
                raise ArchivoRechazado("csv_malformado", tabla=tabla, fila=numero)
            if any(len(v) > MAX_CAMPO for v in valores):
                raise ArchivoRechazado("campo_largo", tabla=tabla, fila=numero)
            filas.append({**dict(zip(columnas, (v.strip() for v in valores), strict=True)), "_fila": str(numero)})
    except csv.Error:
        raise ArchivoRechazado("csv_malformado", tabla=tabla, fila=lector.line_num) from None
    return filas


def leer_paquete(datos: bytes) -> dict[str, list[dict[str, str]]]:
    """Filas de cada tabla del catálogo (clave: nombre normalizado). Lanza ArchivoRechazado."""
    if not datos:
        raise ArchivoRechazado("vacio")
    if len(datos) > MAX_ZIP:
        raise ArchivoRechazado("grande", maximo_mb=MAX_ZIP // (1024 * 1024))
    if not datos.startswith(b"PK\x03\x04"):  # firma ZIP: la extensión no cuenta
        raise ArchivoRechazado("no_zip")
    try:
        paquete = zipfile.ZipFile(io.BytesIO(datos))
        entradas = paquete.infolist()
    except zipfile.BadZipFile, zipfile.LargeZipFile, ValueError, EOFError, OSError:
        raise ArchivoRechazado("no_zip") from None
    if len(entradas) > MAX_ENTRADAS:
        raise ArchivoRechazado("demasiadas_entradas", maximo=MAX_ENTRADAS)
    total = 0
    por_tabla: dict[str, zipfile.ZipInfo] = {}
    for info in entradas:
        nombre = info.filename
        if info.is_dir() or "/" in nombre or "\\" in nombre or ".." in nombre or nombre.startswith("."):
            raise ArchivoRechazado("ruta")
        if info.flag_bits & 0x1:
            raise ArchivoRechazado("cifrado")
        if not nombre.lower().endswith(".csv"):
            raise ArchivoRechazado("no_csv", nombre=nombre[:60])
        tabla = normalizar(nombre[:-4])
        if tabla not in TABLAS:
            # Solo tablas del catálogo: nunca recibir datos de pacientes, órdenes ni resultados.
            raise ArchivoRechazado("tabla_desconocida", nombre=nombre[:60])
        if tabla in por_tabla:
            raise ArchivoRechazado("tabla_repetida", tabla=TABLAS[tabla][0])
        if info.file_size > MAX_TABLA:
            raise ArchivoRechazado("grande", maximo_mb=MAX_TABLA // (1024 * 1024))
        if info.file_size > MAX_PROPORCION * max(info.compress_size, 1):
            raise ArchivoRechazado("bomba")
        total += info.file_size
        por_tabla[tabla] = info
    if total > MAX_TOTAL:
        raise ArchivoRechazado("grande", maximo_mb=MAX_TOTAL // (1024 * 1024))
    tablas = {}
    for tabla, info in por_tabla.items():
        try:
            with paquete.open(info) as archivo:
                contenido = archivo.read(MAX_TABLA + 1)
        except zipfile.BadZipFile, NotImplementedError, OSError, EOFError, RuntimeError:
            raise ArchivoRechazado("no_zip") from None
        if len(contenido) > MAX_TABLA:  # el tamaño declarado mentía
            raise ArchivoRechazado("bomba")
        tablas[tabla] = _filas_csv(_decodificar(contenido, TABLAS[tabla][0]), TABLAS[tabla][0])
    return tablas


# --- 2. Análisis ---


def leer_decimal(valor: str) -> Decimal | None:
    """Número con punto o coma decimal; el último separador es el decimal. None si está vacío."""
    valor = valor.strip().replace(" ", "")
    if not valor:
        return None
    if "," in valor or "." in valor:
        posicion = max(valor.rfind(","), valor.rfind("."))
        entero = re.sub(r"[.,]", "", valor[:posicion])
        valor = f"{entero}.{valor[posicion + 1 :]}"
    if not re.fullmatch(r"-?[0-9]+(\.[0-9]+)?", valor):
        raise ValueError(valor)
    try:
        return Decimal(valor)
    except InvalidOperation:  # pragma: no cover — la expresión ya lo garantiza
        raise ValueError(valor) from None


def leer_booleano(valor: str) -> bool:
    return valor.strip().lower() in _VERDADERO


def leer_entero(valor: str) -> int:
    if not re.fullmatch(r"-?[0-9]{1,9}", valor.strip()):
        raise ValueError(valor)
    return int(valor)


def interpretar_referencia(texto: str) -> tuple[Decimal | None, Decimal | None]:
    """Mínimo y máximo de un texto de referencia ("70 - 100", "< 200", "> 40"); (None, None) si no aplica."""
    if m := _RANGO_TEXTO.match(texto):
        return leer_decimal(m.group(1)), leer_decimal(m.group(2))
    if m := _MENOR.match(texto):
        return None, leer_decimal(m.group(1))
    if m := _MAYOR.match(texto):
        return leer_decimal(m.group(1)), None
    return None, None


@dataclass
class Existentes:
    """Lo que ya tiene el catálogo del laboratorio (se reutiliza o choca)."""

    secciones: set[str] = field(default_factory=set)
    unidades: set[str] = field(default_factory=set)
    tipos_muestra: set[str] = field(default_factory=set)
    tarifas: set[str] = field(default_factory=set)
    tipos_codigo: set[str] = field(default_factory=set)
    codigos_examen: set[str] = field(default_factory=set)
    nombres_examen: set[str] = field(default_factory=set)
    lablinea_examen: set[int] = field(default_factory=set)
    lablinea_parametro: set[int] = field(default_factory=set)


@dataclass
class Plan:
    secciones: list[dict] = field(default_factory=list)
    unidades: list[dict] = field(default_factory=list)
    tipos_muestra: list[dict] = field(default_factory=list)
    tarifas: list[dict] = field(default_factory=list)
    tipos_codigo: list[dict] = field(default_factory=list)
    examenes: list[dict] = field(default_factory=list)
    parametros: list[dict] = field(default_factory=list)
    valores: list[dict] = field(default_factory=list)
    rangos: list[dict] = field(default_factory=list)
    requisitos: list[dict] = field(default_factory=list)
    precios: list[dict] = field(default_factory=list)
    codigos: list[dict] = field(default_factory=list)
    errores: list[dict] = field(default_factory=list)
    advertencias: list[dict] = field(default_factory=list)

    def error(self, clave: str, **parametros: object) -> None:
        self.errores.append({"clave": clave, "params": {k: str(v) for k, v in parametros.items()}})

    def advertir(self, clave: str, **parametros: object) -> None:
        self.advertencias.append({"clave": clave, "params": {k: str(v) for k, v in parametros.items()}})

    def conteos(self) -> dict[str, int]:
        return {
            nombre: len(getattr(self, nombre))
            for nombre in (
                "secciones",
                "unidades",
                "tipos_muestra",
                "tarifas",
                "tipos_codigo",
                "examenes",
                "parametros",
                "valores",
                "rangos",
                "requisitos",
                "precios",
                "codigos",
            )
        }

    def resumen(self) -> dict:
        return {
            "conteos": self.conteos(),
            "total_errores": len(self.errores),
            "total_advertencias": len(self.advertencias),
            "errores": self.errores[:MAX_MENSAJES],
            "advertencias": self.advertencias[:MAX_MENSAJES],
        }


def _texto(fila: dict, columna: str, maximo: int, plan: Plan, tabla: str, *, obligatorio: bool = True) -> str | None:
    valor = fila.get(columna, "").strip()
    if not valor:
        if obligatorio:
            plan.error("campo_invalido", tabla=tabla, fila=fila["_fila"], campo=columna)
        return None
    if len(valor) > maximo:
        plan.error("campo_largo", tabla=tabla, fila=fila["_fila"], campo=columna, maximo=maximo)
        return None
    return valor


def _maestro(plan, filas, tabla, destino, columna_codigo, max_codigo, max_nombre, existentes, extra=None):
    """Secciones, unidades, tipos de muestra, tarifas y tipos de código: código y nombre."""
    vistos = set()
    for fila in filas:
        codigo = _texto(fila, columna_codigo, max_codigo, plan, tabla)
        nombre = _texto(fila, "descripcion", max_nombre, plan, tabla)
        if codigo is None or nombre is None:
            continue
        if codigo in vistos:
            plan.error("repetido", tabla=tabla, fila=fila["_fila"], valor=codigo)
            continue
        vistos.add(codigo)
        if codigo not in existentes:
            destino.append({"codigo": codigo, "nombre": nombre, **(extra or {})})
    return vistos


def analizar(tablas: dict[str, list[dict[str, str]]], existentes: Existentes, moneda: str) -> Plan:
    plan = Plan()
    for clave, (nombre, obligatoria, columnas) in TABLAS.items():
        if clave not in tablas:
            if obligatoria:
                plan.error("falta_tabla", tabla=nombre)
            continue
        if tablas[clave]:
            faltan = [c for c in columnas if c not in tablas[clave][0]]
            for columna in faltan:
                plan.error("falta_columna", tabla=nombre, columna=columna)
            if faltan:
                tablas[clave] = []
    if plan.errores:
        return plan

    secciones = _maestro(plan, tablas["seccion"], "seccion", plan.secciones, "codigo", 50, 120, existentes.secciones)
    secciones |= existentes.secciones
    unidades = _maestro(plan, tablas.get("unidad", []), "unidad", plan.unidades, "codigo", 50, 60, existentes.unidades)
    unidades |= existentes.unidades
    tipos_muestra = _maestro(
        plan,
        tablas.get("tipomuestra", []),
        "tipo muestra",
        plan.tipos_muestra,
        "tipo",
        10,
        60,
        existentes.tipos_muestra,
    )
    tipos_muestra |= existentes.tipos_muestra
    tarifas = _maestro(
        plan, tablas.get("tipotarifa", []), "tipo tarifa", plan.tarifas, "codigo", 15, 60, existentes.tarifas,
        {"moneda": moneda},
    )  # fmt: skip
    tarifas |= existentes.tarifas
    tipos_codigo = _maestro(
        plan, tablas.get("tipocodigoalterno", []), "Tipo Codigo Alterno", plan.tipos_codigo, "codigo", 10, 60,
        existentes.tipos_codigo,
    )  # fmt: skip
    tipos_codigo |= existentes.tipos_codigo

    # Exámenes
    examenes: dict[int, dict] = {}
    codigos, nombres = set(), set()
    for fila in tablas["analisis"]:
        tabla, numero = "analisis", fila["_fila"]
        try:
            consecutivo = leer_entero(fila["consecutivo"])
        except ValueError:
            plan.error("numero_invalido", tabla=tabla, fila=numero, campo="consecutivo")
            continue
        nombre = _texto(fila, "descripcion", 120, plan, tabla)
        seccion = _texto(fila, "seccion", 50, plan, tabla)
        codigo = _texto(fila, "codigoexamen", 20, plan, tabla, obligatorio=False) or str(consecutivo)
        nacional = _texto(fila, "codigosgss", 20, plan, tabla, obligatorio=False)
        dias = _texto(fila, "diasmontaje", 30, plan, tabla, obligatorio=False)
        if nombre is None or seccion is None:
            continue
        if len(nombre) < 2:
            plan.error("campo_invalido", tabla=tabla, fila=numero, campo="descripcion")
            continue
        if seccion not in secciones:
            plan.error("seccion_inexistente", fila=numero, valor=seccion)
            continue
        if consecutivo in examenes or codigo in codigos or nombre.lower() in nombres:
            plan.error("repetido", tabla=tabla, fila=numero, valor=nombre)
            continue
        if (
            codigo in existentes.codigos_examen
            or nombre.lower() in existentes.nombres_examen
            or consecutivo in existentes.lablinea_examen
        ):
            plan.error("examen_existe", fila=numero, valor=nombre)
            continue
        codigos.add(codigo)
        nombres.add(nombre.lower())
        examenes[consecutivo] = {
            "codigo": codigo,
            "nombre": nombre,
            "seccion": seccion,
            "codigo_nacional": nacional,
            "requiere_autorizacion": leer_booleano(fila.get("autorizadic", "")),
            "dias": dias,
            "lablinea": consecutivo,
        }
    plan.examenes = list(examenes.values())

    # Valores de lista (se leen antes para inferir el tipo de los parámetros)
    listas: dict[int, list[tuple[str, str]]] = {}
    for fila in tablas.get("listadevalores", []):
        try:
            pregunta = leer_entero(fila["preguntaporanalisis"])
        except ValueError:
            plan.error("numero_invalido", tabla="lista de valores", fila=fila["_fila"], campo="pregunta por analisis")
            continue
        valor = _texto(fila, "valor", 120, plan, "lista de valores")
        if valor is not None:
            listas.setdefault(pregunta, []).append((valor, fila["_fila"]))

    # Parámetros y rangos
    parametros: dict[int, dict] = {}
    con_parametros = set()
    for fila in tablas["detalleanalisis"]:
        tabla, numero = "detalle analisis", fila["_fila"]
        try:
            consecutivo = leer_entero(fila["consecutivo"])
            examen = leer_entero(fila["analisis"])
        except ValueError:
            plan.error("numero_invalido", tabla=tabla, fila=numero, campo="consecutivo")
            continue
        nombre = _texto(fila, "descripcion", 120, plan, tabla)
        unidad = _texto(fila, "unidad", 50, plan, tabla, obligatorio=False)
        referencia = _texto(fila, "normaldereferencia", 255, plan, tabla, obligatorio=False)
        if nombre is None:
            continue
        if examen not in examenes:
            plan.error("examen_inexistente", tabla=tabla, fila=numero, valor=examen)
            continue
        if consecutivo in parametros or consecutivo in existentes.lablinea_parametro:
            plan.error("repetido", tabla=tabla, fila=numero, valor=consecutivo)
            continue
        try:
            orden = leer_entero(fila.get("ordendepresentacion", "") or "0")
        except ValueError:
            plan.advertir("numero_ignorado", tabla=tabla, fila=numero, campo="orden de presentacion")
            orden = 0
        minimo = maximo = None
        for campo in ("rangominimo", "rangomaximo"):
            try:
                valor = leer_decimal(fila.get(campo, ""))
            except ValueError:
                plan.advertir("numero_ignorado", tabla=tabla, fila=numero, campo=campo)
                valor = None
            if valor is not None and abs(valor) >= Decimal("1e10"):
                plan.advertir("numero_ignorado", tabla=tabla, fila=numero, campo=campo)
                valor = None
            if campo == "rangominimo":
                minimo = valor
            else:
                maximo = valor
        if minimo is None and maximo is None and referencia:
            try:
                minimo, maximo = interpretar_referencia(referencia)
            except ValueError:  # pragma: no cover — las expresiones solo capturan números válidos
                minimo = maximo = None
        if minimo is not None and maximo is not None and minimo > maximo:
            plan.advertir("rango_invertido", fila=numero, valor=nombre)
            minimo = maximo = None

        titulo = leer_booleano(fila.get("estitulo", ""))
        if titulo:
            tipo = "TITULO"
        elif consecutivo in listas:
            tipo = "LISTA"
        elif minimo is not None or maximo is not None or unidad:
            tipo = "NUMERICO"
        else:
            tipo = "TEXTO"
        if unidad and unidad not in unidades:
            plan.unidades.append({"codigo": unidad, "nombre": unidad[:60]})
            unidades.add(unidad)
        con_parametros.add(examen)
        parametros[consecutivo] = {
            "examen": examen,
            "nombre": nombre,
            "orden": orden,
            "tipo": tipo,
            "unidad": unidad if tipo == "NUMERICO" else None,
            "grafica": leer_booleano(fila.get("grafica", "")) and tipo == "NUMERICO",
            "lablinea": consecutivo,
        }
        if tipo != "TITULO" and (minimo is not None or maximo is not None or referencia):
            numerico = tipo == "NUMERICO"
            plan.rangos.append(
                {
                    "parametro": consecutivo,
                    "minimo": minimo if numerico else None,
                    "maximo": maximo if numerico else None,
                    "valor_esperado": None if numerico else (referencia or "")[:120] or None,
                    "texto_impreso": referencia,
                }
            )
    plan.parametros = list(parametros.values())
    if plan.rangos:
        plan.advertir("rangos_revision", cantidad=len(plan.rangos))
    for examen in examenes.values():
        if examen["lablinea"] not in con_parametros:
            plan.advertir("examen_sin_parametros", valor=examen["nombre"])

    for pregunta, valores in listas.items():
        if pregunta not in parametros:
            plan.error("parametro_inexistente", fila=valores[0][1], valor=pregunta)
            continue
        vistos = set()
        for orden, (valor, numero) in enumerate(valores):
            if valor.lower() in vistos:
                plan.advertir("valor_repetido", fila=numero, valor=valor)
                continue
            vistos.add(valor.lower())
            plan.valores.append({"parametro": pregunta, "valor": valor, "orden": orden})

    # Requisitos de muestra (tubo y volumen se completan después)
    vistos = set()
    for fila in tablas.get("muestrasxanalisis", []):
        tabla, numero = "muestras x analisis", fila["_fila"]
        try:
            examen = leer_entero(fila["analisis"])
        except ValueError:
            plan.error("numero_invalido", tabla=tabla, fila=numero, campo="analisis")
            continue
        tipo = _texto(fila, "tipodemuestra", 10, plan, tabla)
        if tipo is None:
            continue
        if examen not in examenes:
            plan.error("examen_inexistente", tabla=tabla, fila=numero, valor=examen)
        elif tipo not in tipos_muestra:
            plan.error("tipo_muestra_inexistente", fila=numero, valor=tipo)
        elif (examen, tipo) in vistos:
            plan.advertir("requisito_repetido", fila=numero)
        else:
            vistos.add((examen, tipo))
            plan.requisitos.append({"examen": examen, "tipo_muestra": tipo})
    if plan.requisitos:
        plan.advertir("requisitos_sin_tubo", cantidad=len(plan.requisitos))

    # Precios por tarifa
    vistos = set()
    for fila in tablas.get("costoanalisis", []):
        tabla, numero = "costo analisis", fila["_fila"]
        tarifa = _texto(fila, "tipotarifa", 15, plan, tabla)
        try:
            examen = leer_entero(fila["analisis"])
            costo = leer_decimal(fila["costo"])
            if costo is None or costo < 0 or costo >= Decimal("1e12"):
                raise ValueError
        except ValueError:
            plan.error("numero_invalido", tabla=tabla, fila=numero, campo="costo")
            continue
        if tarifa is None:
            continue
        if tarifa not in tarifas:
            plan.error("tarifa_inexistente", fila=numero, valor=tarifa)
        elif examen not in examenes:
            plan.error("examen_inexistente", tabla=tabla, fila=numero, valor=examen)
        elif (tarifa, examen) in vistos:
            plan.error("repetido", tabla=tabla, fila=numero, valor=f"{tarifa}/{examen}")
        else:
            vistos.add((tarifa, examen))
            valor = costo.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if valor != costo:
                plan.advertir("precio_redondeado", fila=numero, valor=valor)
            plan.precios.append({"tarifa": tarifa, "examen": examen, "valor": valor})

    # Códigos alternos por entidad
    vistos = set()
    for fila in tablas.get("codigoanalisisxempresa", []):
        tabla, numero = "Codigo Analisis x Empresa", fila["_fila"]
        tipo = _texto(fila, "tipocodigoalterno", 10, plan, tabla)
        codigo = _texto(fila, "codigoalterno", 20, plan, tabla)
        try:
            examen = leer_entero(fila["analisis"])
        except ValueError:
            plan.error("numero_invalido", tabla=tabla, fila=numero, campo="analisis")
            continue
        if tipo is None or codigo is None:
            continue
        if tipo not in tipos_codigo:
            plan.error("tipo_codigo_inexistente", fila=numero, valor=tipo)
        elif examen not in examenes:
            plan.error("examen_inexistente", tabla=tabla, fila=numero, valor=examen)
        elif (tipo, examen) in vistos:
            plan.error("repetido", tabla=tabla, fila=numero, valor=f"{tipo}/{examen}")
        else:
            vistos.add((tipo, examen))
            plan.codigos.append({"tipo": tipo, "examen": examen, "codigo": codigo})
    return plan


# --- 3. Carga (sesion_tenant: todo en la transacción del laboratorio) ---

_INSERTS = {
    "secciones": "INSERT INTO lab.secciones (codigo, nombre) VALUES (:codigo, :nombre)",
    "unidades": "INSERT INTO lab.unidades (codigo, nombre) VALUES (:codigo, :nombre)",
    "tipos_muestra": "INSERT INTO lab.tipos_muestra (codigo, nombre) VALUES (:codigo, :nombre)",
    "tarifas": "INSERT INTO lab.tarifas (codigo, nombre, moneda) VALUES (:codigo, :nombre, :moneda)",
    "tipos_codigo": "INSERT INTO lab.tipos_codigo_alterno (codigo, nombre) VALUES (:codigo, :nombre)",
    "examenes": (
        "INSERT INTO lab.examenes (codigo, nombre, seccion_id, codigo_nacional, requiere_autorizacion,"
        " dias_procesamiento, codigo_lablinea)"
        " SELECT :codigo, :nombre, s.id, :codigo_nacional, :requiere_autorizacion, :dias, :lablinea"
        " FROM lab.secciones s WHERE s.codigo = :seccion"
    ),
    "parametros": (
        "INSERT INTO lab.parametros (examen_id, nombre, orden, tipo, unidad_id, grafica, codigo_lablinea)"
        " SELECT e.id, :nombre, :orden, :tipo, (SELECT u.id FROM lab.unidades u WHERE u.codigo = :unidad),"
        " :grafica, :lablinea FROM lab.examenes e WHERE e.codigo_lablinea = :examen"
    ),
    "valores": (
        "INSERT INTO lab.valores_lista (parametro_id, valor, orden)"
        " SELECT p.id, :valor, :orden FROM lab.parametros p WHERE p.codigo_lablinea = :parametro"
    ),
    "rangos": (
        "INSERT INTO lab.rangos_referencia (parametro_id, minimo, maximo, valor_esperado, texto_impreso,"
        " requiere_revision)"
        " SELECT p.id, :minimo, :maximo, :valor_esperado, :texto_impreso, true"
        " FROM lab.parametros p WHERE p.codigo_lablinea = :parametro"
    ),
    "requisitos": (
        "INSERT INTO lab.requisitos_muestra (examen_id, tipo_muestra_id, requiere_revision)"
        " SELECT e.id, t.id, true FROM lab.examenes e, lab.tipos_muestra t"
        " WHERE e.codigo_lablinea = :examen AND t.codigo = :tipo_muestra"
    ),
    "precios": (
        "INSERT INTO lab.precios_examen (tarifa_id, examen_id, valor)"
        " SELECT t.id, e.id, :valor FROM lab.tarifas t, lab.examenes e"
        " WHERE t.codigo = :tarifa AND e.codigo_lablinea = :examen"
    ),
    "codigos": (
        "INSERT INTO lab.codigos_alternos (tipo_id, examen_id, codigo)"
        " SELECT t.id, e.id, :codigo FROM lab.tipos_codigo_alterno t, lab.examenes e"
        " WHERE t.codigo = :tipo AND e.codigo_lablinea = :examen"
    ),
}


async def existentes(sesion: AsyncSession) -> Existentes:
    async def conjunto(sql: str) -> set:
        return set((await sesion.execute(text(sql))).scalars())

    return Existentes(
        secciones=await conjunto("SELECT codigo FROM lab.secciones"),
        unidades=await conjunto("SELECT codigo FROM lab.unidades"),
        tipos_muestra=await conjunto("SELECT codigo FROM lab.tipos_muestra"),
        tarifas=await conjunto("SELECT codigo FROM lab.tarifas"),
        tipos_codigo=await conjunto("SELECT codigo FROM lab.tipos_codigo_alterno"),
        codigos_examen=await conjunto("SELECT codigo FROM lab.examenes"),
        nombres_examen=await conjunto("SELECT lower(nombre) FROM lab.examenes"),
        lablinea_examen=await conjunto("SELECT codigo_lablinea FROM lab.examenes WHERE codigo_lablinea IS NOT NULL"),
        lablinea_parametro=await conjunto(
            "SELECT codigo_lablinea FROM lab.parametros WHERE codigo_lablinea IS NOT NULL"
        ),
    )


async def cargar(sesion: AsyncSession, plan: Plan) -> dict[str, int]:
    """Inserta el plan (sin errores) en el laboratorio de la sesión. Si algo falla, la transacción se revierte."""
    if plan.errores:
        raise ValueError("un plan con errores no se carga")
    for entidad, sql in _INSERTS.items():
        filas = getattr(plan, entidad)
        if filas:
            await sesion.execute(text(sql), filas)
    return plan.conteos()
