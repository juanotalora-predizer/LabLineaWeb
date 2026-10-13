# 0006. Integración con sistemas clínicos y equipos de laboratorio

- **Estado:** Aceptada
- **Fecha:** 2026-10-12
- **Responsable:** Juan Otálora
- **Modifica:** punto 8 de [0002](0002-interoperabilidad-hl7-fhir.md)

## Contexto

La spec [0002](0002-interoperabilidad-hl7-fhir.md) suponía que LabLineaWeb recibiría resultados de un LIS externo y trataba HL7 v2 como una excepción. Ahora LabLineaWeb **es** el LIS ([funcional/0001](../funcional/0001-producto-lis-saas.md)), por lo que debe integrarse con:

- **Sistemas de los clientes** (HIS, historia clínica, sistemas de clínicas y aseguradoras), que envían órdenes y reciben resultados. Muchos en la región solo hablan HL7 v2.
- **Equipos de análisis** (analizadores de química, hematología, etc.), que están en la red local del laboratorio y usan protocolos como ASTM o HL7 v2 sobre puerto serial o TCP. Un SaaS en la nube no puede conectarse directamente a ellos.

## Decisión

### 1. Modelo interno

FHIR R4 sigue siendo el **único modelo interno** ([0002](0002-interoperabilidad-hl7-fhir.md)). Todo formato externo se convierte a FHIR al entrar y desde FHIR al salir.

### 2. Sistemas clínicos de los clientes

| Canal | Uso |
|-------|-----|
| **API FHIR R4** | Opción preferida para recibir órdenes (`ServiceRequest`) y entregar resultados (`DiagnosticReport`, `Observation`) |
| **HL7 v2.5.1** | Soportado para clientes sin FHIR: `OML^O21` (u `ORM^O01`) para órdenes entrantes, `ORU^R01` para resultados salientes, con acuses `ACK` |

HL7 v2 deja de ser una excepción: es un canal de integración soportado, pero siempre se convierte a FHIR en el borde.

### 3. Equipos de análisis: conector local

- Se construye un **conector local** (*agente*) que el laboratorio instala en un equipo de su red.
- El conector habla con los analizadores en sus protocolos (**ASTM E1381/E1394**, HL7 v2) por serial o TCP y se comunica con la plataforma por **HTTPS saliente**, sin abrir puertos de entrada en la red del laboratorio.
- Se autentica ante la plataforma con credenciales propias por tenant y sede, que se pueden revocar.
- Si se pierde la conexión a internet, guarda los resultados en una cola cifrada y los envía al reconectar.
- Los resultados del equipo nunca se publican sin pasar por validación en el LIS.
- El controlador de cada modelo de equipo es configurable; se priorizan los equipos más usados por los primeros clientes.

## Alternativas consideradas

- **Solo FHIR para sistemas de clientes:** más simple, pero deja fuera a buena parte de los HIS de la región.
- **Integración de equipos a través de middleware de terceros:** reduce desarrollo inicial, pero agrega costo de licencia por laboratorio y una dependencia crítica.
- **VPN entre cada laboratorio y la nube:** permite conexión directa a los equipos, pero es costosa de operar, frágil y amplía la superficie de ataque.

## Consecuencias

- El conector local es un componente aparte del SaaS, con su propio ciclo de versiones y actualizaciones.
- Hace falta un motor de conversión HL7 v2 ↔ FHIR con pruebas por tipo de mensaje.
- Se necesita conocer los modelos de equipos de los primeros laboratorios clientes para priorizar controladores.
- El conector maneja datos de salud: aplican todos los controles de [0003](0003-seguridad-hipaa.md) (cifrado de la cola local, TLS, auditoría).
