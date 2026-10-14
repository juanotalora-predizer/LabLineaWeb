# 0010. Pacientes, autorización de tratamiento de datos y derechos del titular

- **Estado:** Aceptada
- **Fecha:** 2026-10-13
- **Responsable:** Juan Otálora
- **Base:** [infraestructura/0004](../infraestructura/0004-normativa-colombia-latam.md) (Ley 1581), [infraestructura/0003](../infraestructura/0003-seguridad-hipaa.md) (HIPAA), [infraestructura/0007](../infraestructura/0007-base-de-datos.md) (auditoría), [0002](0002-pos-ordenes-caja.md) (la recepción registra al paciente)

> Traduce la Ley 1581 de 2012 y el Decreto 1377 de 2013 a reglas del software. Los plazos, la supresión con historia clínica y el texto modelo de la autorización deben validarse con un asesor legal antes de producción (backlog).

## Contexto

La recepción registra al paciente antes de crear su orden (etapa 8). Los datos de salud son **sensibles**: el laboratorio (Responsable del tratamiento) necesita la autorización **previa, expresa e informada** del titular y debe poder demostrarla después. El titular puede conocer, actualizar, rectificar y suprimir sus datos y revocar la autorización. LabLineaWeb es el Encargado: da las herramientas y guarda la evidencia.

## Decisión

### 1. Paciente

- Por laboratorio (esquema `lab`, RLS). Identificado por **tipo y número de documento**; los tipos salen de `global.tipos_documento` del país del laboratorio, que ahora incluye la expresión válida de cada tipo (configuración, no código).
- Campos: tipo y número de documento, nombres, apellidos, sexo biológico (`F`, `M` o `I` indeterminado; los rangos de referencia por sexo usan `F`/`M`, el `I` solo recibe rangos para ambos sexos), fecha de nacimiento, **país de residencia**, correo, teléfono y dirección (opcionales).
- Único por laboratorio: tipo + número de documento. Identificador público: UUID.
- **La base no guarda un paciente sin autorización:** un trigger diferido rechaza la transacción que crea un paciente sin su autorización.
- **Auditoría sin copiar datos personales:** el trigger de auditoría de pacientes, autorizaciones y solicitudes marca las columnas personales como `[protegido]` (registra qué cambió, quién y cuándo, nunca el valor). Así la auditoría, que es de solo inserción, no guarda datos que el titular pida suprimir.

### 2. Autorización de tratamiento de datos (versionada)

- **Texto por laboratorio, versionado e inmutable** (`lab.textos_autorizacion`): el laboratorio publica una versión nueva; las anteriores no se modifican ni se borran. El primer texto parte de un **modelo del país** (`global.textos_legales`) que el laboratorio completa. Sin texto publicado no se registran pacientes.
- **Cada autorización** guarda: versión del texto aceptada, medio (`FORMATO_FIRMADO` en papel o `ACEPTACION_EN_PANTALLA`), quién la registró, cuándo y, para **menores de edad** (según `global.paises.mayoria_edad`), nombre, documento y parentesco del representante legal (obligatorios).
- Una sola autorización vigente por paciente (índice único parcial). Una autorización no se modifica: solo se revoca (fecha, quién y motivo), y la base impide cualquier otro cambio.
- **Revocación:** el titular la pide; queda registrada como solicitud resuelta. Sin autorización vigente:
  - no se crean órdenes ni se procesan datos del paciente (la etapa 8 exige `lab.autorizacion_vigente(paciente)`; la función queda lista y probada);
  - los datos solo se modifican para atender una solicitud del titular (actualización o rectificación);
  - se puede registrar una autorización nueva si el titular vuelve a otorgarla.
- Los datos que el laboratorio debe conservar por ley (historia clínica, facturación) no se borran por la revocación (Decreto 1377, art. 9).

### 3. Derechos del titular (solicitudes)

- `lab.solicitudes_titular`: tipo (`CONSULTA`, `ACTUALIZACION`, `RECTIFICACION`, `SUPRESION`, `REVOCACION`), canal, descripción, fecha de recepción, **vencimiento**, estado (`ABIERTA`, `RESUELTA`, `RECHAZADA`), respuesta, quién y cuándo resolvió.
- **Vencimiento en días hábiles** desde la recepción: consultas `plazo_consulta_dias` (10 en Colombia, art. 14) y reclamos `plazo_reclamo_dias` (15, art. 15), excluyendo fines de semana y los festivos de `global.festivos` del país (Colombia 2026 y 2027 cargados). Las solicitudes abiertas se listan por vencimiento, con aviso de las que vencen.
- **Consultar:** el informe *Datos del titular* reúne todo lo que el laboratorio guarda del paciente (datos, autorizaciones, solicitudes) para entregárselo; su generación queda auditada como `EXPORT`.
- **Actualizar y rectificar:** se editan los datos; si no hay autorización vigente, la edición exige una solicitud abierta de ese tipo, que queda resuelta.
- **Suprimir** (permiso `pacientes.eliminar`, solo con una solicitud de supresión abierta y confirmación escrita):
  - **sin historia clínica** (ni órdenes ni resultados): **anonimización irreversible** del registro. Nombres, documento, fecha de nacimiento y contacto se reemplazan o se vacían; se revoca la autorización; se borran el representante y el texto de las solicitudes. Queda un registro `SUPRIMIDO` sin datos personales para que la auditoría y las solicitudes sigan íntegras;
  - **con historia clínica:** se rechaza con el motivo legal (deber de conservación, Res. 1995 de 1999); el paciente queda sin autorización vigente. La función `lab.paciente_tiene_historia(paciente)` responde `false` hasta la etapa 8, que la redefine con las órdenes.

### 4. Búsqueda sin exponer datos ni permitir enumeración

- **Por POST** con CSRF: el nombre o el documento buscados nunca van en la URL ni en los logs de acceso.
- Documento: solo coincidencia **exacta** (no se puede recorrer por prefijos). Nombre: al menos 3 caracteres y cada palabra debe aparecer en nombres o apellidos.
- Máximo 20 resultados; si hay más, se pide afinar sin decir cuántos hay.
- Límite de 60 búsquedas por usuario cada 5 minutos (429).
- Cada búsqueda y cada ficha abierta quedan auditadas (`READ`) con conteos, nunca con el texto buscado.
- Un UUID de otro laboratorio o inexistente → 404 (RLS).

### 5. Permisos

- `pacientes.consultar`: buscar, ver la ficha y generar el informe del titular.
- `pacientes.crear`: registrar pacientes y autorizaciones.
- `pacientes.modificar`: editar, revocar y registrar o resolver solicitudes.
- `pacientes.eliminar`: suprimir (solo el administrador en los roles iniciales).
- `configuracion.modificar`: publicar el texto de la autorización.

## Alternativas consideradas

- **Borrar el registro al suprimir:** deja huérfanas la auditoría y las solicitudes, y no es posible cuando hay historia clínica. La anonimización cumple el fin (no queda dato personal) sin romper la trazabilidad.
- **Guardar los valores anteriores en la auditoría:** facilitaría ver el historial de cambios, pero la auditoría es de solo inserción y conservaría para siempre datos que el titular puede pedir suprimir.
- **Búsqueda por GET con `?q=`:** el texto (nombre o documento) quedaría en la URL, el historial del navegador y los logs.
- **Búsqueda por prefijo del documento:** permitiría enumerar pacientes.
- **Texto de autorización global de la plataforma:** el Responsable es cada laboratorio; el texto debe ser suyo.

## Consecuencias

- La etapa 8 llama a `lab.autorizacion_vigente()` al crear órdenes y redefine `lab.paciente_tiene_historia()`.
- El portal del paciente (etapa 14) podrá registrar solicitudes y autorizaciones en pantalla con el mismo modelo.
- Hay que mantener los festivos de cada país (los de Colombia para 2028 en adelante, en el backlog).
- Pendiente con el asesor legal: texto modelo de la autorización, plazos y tratamiento de la supresión con historia clínica.
