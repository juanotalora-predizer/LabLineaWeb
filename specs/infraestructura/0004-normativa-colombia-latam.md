# 0004. Normativa: Colombia como base, alcance Latinoamérica

- **Estado:** Aceptada
- **Fecha:** 2026-10-12
- **Responsable:** Juan Otálora

## Contexto

LabLineaWeb operará en Colombia y tiene alcance Latinoamérica. Las specs [0002](0002-interoperabilidad-hl7-fhir.md) (HL7 FHIR) y [0003](0003-seguridad-hipaa.md) (HIPAA) definen el estándar técnico y el marco de controles de seguridad, pero HIPAA es una ley de EE. UU.: en Colombia y en el resto de la región las obligaciones legales vienen de la normativa local.

> Esta spec traduce la normativa a requisitos de software. No reemplaza la revisión de un asesor legal, que debe validarla antes de salir a producción en cada país.

## Decisión

### 1. Relación entre marcos

- **HIPAA** se mantiene como **marco de controles técnicos de seguridad** (spec 0003) en todos los países.
- **La ley local es la obligación legal** y prevalece cuando es más exigente que HIPAA.
- **HL7 FHIR R4** (spec 0002) es el estándar de interoperabilidad en todos los países, con los perfiles nacionales que cada uno publique.

### 2. Colombia (país base)

| Norma | Qué exige al software |
|-------|----------------------|
| **Ley 1581 de 2012** y **Decreto 1377 de 2013** (compilado en el Decreto 1074 de 2015): protección de datos personales | Los datos de salud son **datos sensibles**. Se requiere autorización **previa, expresa e informada** del titular, que debe poder consultarse después; aviso de privacidad y política de tratamiento visibles; mecanismos para que el titular **conozca, actualice, rectifique y suprima** sus datos y **revoque** la autorización. |
| **Ley 1581, art. 26**: transferencia internacional | Los datos solo se transfieren o alojan en países con nivel adecuado de protección según la SIC, o con un contrato de transmisión o la autorización del titular. Esto restringe la elección de hosting. |
| **Registro Nacional de Bases de Datos (RNBD)** ante la SIC | Las bases de datos con datos personales se inscriben cuando la empresa está obligada. La aplicación debe permitir inventariar qué bases existen y qué datos guardan. |
| **Ley 2015 de 2020** y **Resolución 866 de 2021**: Historia Clínica Electrónica Interoperable (IHCE) | Los datos clínicos se intercambian según el conjunto de elementos de datos de la Res. 866 y los **perfiles FHIR que publique el Ministerio de Salud para la IHCE**. |
| **Resolución 1995 de 1999** (modificada por la **Res. 839 de 2017**): historia clínica | Si los resultados forman parte de la historia clínica, deben custodiarse y conservarse por el plazo vigente (hoy 15 años desde la última atención) y su acceso es confidencial. Debe confirmarse con asesoría legal si aplica al rol del laboratorio. |
| **Ley 527 de 1999** y **Decreto 2364 de 2012**: mensajes de datos y firma electrónica | El informe PDF lleva firma electrónica o digital del profesional que valida, para que tenga validez jurídica e integridad verificable. |

**Codificación y datos propios de Colombia:**
- Exámenes codificados con **CUPS** (Clasificación Única de Procedimientos en Salud) además de **LOINC**: CUPS para facturación y reportes nacionales, LOINC para interoperabilidad.
- Identificación del paciente con tipo y número de documento colombiano (CC, TI, RC, CE, PA, PPT, entre otros) en `Patient.identifier`.
- Interfaz en español (`es-CO`), fechas en formato `DD/MM/AAAA` y zona horaria `America/Bogota`.

**Rol como SaaS** ([funcional/0001](../funcional/0001-producto-lis-saas.md)):
- Cada **laboratorio cliente es el Responsable del tratamiento**: recoge la autorización del paciente y responde ante él y ante la SIC.
- **LabLineaWeb es el Encargado del tratamiento**: trata los datos por cuenta del laboratorio y según sus instrucciones. Se firma un **contrato de transmisión de datos** con cada cliente (Decreto 1377 de 2013, compilado en el Decreto 1074 de 2015).
- El software debe darle al laboratorio las herramientas para cumplir sus obligaciones: registrar autorizaciones, atender derechos del titular y exportar o suprimir datos al terminar el contrato.

**Obligaciones del laboratorio que el LIS debe soportar:**
- **Reporte de eventos de interés en salud pública** al SIVIGILA (Instituto Nacional de Salud) cuando un resultado lo requiera.
- **Habilitación** del servicio de laboratorio clínico (Resolución 3100 de 2019): trazabilidad de muestras, registros y control de calidad que el laboratorio debe demostrar.
- **RIPS y facturación electrónica** (DIAN): fuera del alcance inicial, pero el modelo de datos debe permitir generarlos (CUPS por examen).

**Por confirmar con asesoría legal:** si alguna funcionalidad del LIS (por ejemplo, interpretación automática de resultados) lo haría calificar como software dispositivo médico ante el INVIMA.

### 3. Estrategia para Latinoamérica

- **Colombia primero.** Ningún otro país se habilita sin una spec propia de normativa aprobada.
- **Configuración por país, no código por país.** Lo que varía entre países se modela como configuración:
  - tipos de documento de identidad;
  - terminologías locales (CUPS en Colombia, por ejemplo) y perfiles FHIR nacionales;
  - textos legales (autorización de datos, aviso de privacidad);
  - idioma (`es-*`, `pt-BR` para Brasil) y zona horaria;
  - plazos de conservación y reglas de transferencia internacional.
- **Residencia de datos por país:** la arquitectura debe permitir alojar los datos de cada país en una región distinta si su ley lo exige. Cada laboratorio (tenant) tiene un país y vive en una celda regional ([0005](0005-arquitectura-saas-multitenant.md)).
- **Internacionalización desde el inicio:** los textos de las plantillas se externalizan (no van escritos directamente en el HTML) para soportar varios idiomas. Fechas en UTC en la base de datos y conversión a la zona local al mostrarlas.
- **Leyes de referencia por país** (se detallan en la spec de cada uno al expandirse): Brasil (LGPD, Lei 13.709/2018; RNDS con FHIR), México (ley federal de protección de datos personales en posesión de particulares), Argentina (Ley 25.326), Chile (Ley 19.628 y su reforma, Ley 21.719), Perú (Ley 29733), Ecuador (LOPDP 2021).

## Alternativas consideradas

- **Solo HIPAA:** no cumple la ley colombiana. HIPAA no exige, por ejemplo, la autorización expresa para datos sensibles ni los derechos del titular en la forma en que lo hace la Ley 1581.
- **Diseñar solo para Colombia y adaptar después:** más rápido al inicio, pero los identificadores, idiomas, textos legales y la residencia de datos escritos directamente en el código son costosos de cambiar después.
- **Cubrir todos los países desde el inicio:** multiplica el trabajo legal y técnico antes de validar el producto en un mercado.

## Consecuencias

- Hay nuevas funcionalidades obligatorias para Colombia: flujo de autorización de tratamiento de datos sensibles, aviso de privacidad, y gestión de derechos del titular (consulta, rectificación, supresión, revocación).
- El hosting debe estar en un país con nivel adecuado de protección según la SIC, o contar con contrato de transmisión, además de los requisitos de la spec 0003 (cifrado y BAA).
- El modelo de datos incluye el país en paciente, laboratorio y resultado.
- Las plantillas Jinja2 usan textos externalizados para i18n.
- Pendiente: obtener y aplicar la versión vigente de los perfiles FHIR de la IHCE del Ministerio de Salud; confirmar con asesoría legal el plazo de conservación y la obligación de inscripción en el RNBD.
