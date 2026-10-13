SaaS Pasarela de Pagos

Sí, totalmente! Para operar en Colombia y recibir pagos locales e internacionales, Stripe directo no procesa transacciones en pesos colombianos (COP) ni opera cuentas mercantiles locales físicas, a menos que estructures una entidad legal en EE. UU. (como una LLC).
Sin embargo, para un SaaS operando desde Colombia con clientes nacionales e internacionales, tenemos dos excelentes caminos de integración:
Alternativa A: Usar Pasarelas Locales en Colombia (La opción más ágil para cobros en COP)
Para soportar nativamente Tarjetas de Crédito, PSE, Transferencias y Nequi de forma directa en pesos colombianos, las mejores pasarelas con APIs robustas integrables con FastAPI son:
Wompi (del Grupo Bancolombia): Ideal por su confiabilidad, soporte nativo de Nequi, tarjetas y botones de pago locales, además de permitir generar links de pago.
ePayco o PayU: Excelente cobertura de métodos de pago alternativos y botones de pago corporativos.
Alternativa B: Stripe Global (Mediante una LLC en EE. UU.)
Si prefieres usar Stripe por su potente ecosistema de suscripciones recurrentes automatizadas (Stripe Billing), manejo de tarjetas internacionales y multimoneda en dólares (USD), muchos سافٹ‌wares (SaaS) latinoamericanos abren una LLC en Estados Unidos (por ejemplo, en Delaware o Wyoming). Esto te da una cuenta en EE. UU. y acceso total a Stripe para cobrarle a laboratorios tanto de Colombia como del resto del mundo de manera automatizada.
¿Cómo se integra esto con el módulo contable que acabamos de diseñar?
Independientemente de si eliges una pasarela local (como Wompi) o Stripe, la arquitectura se conecta mediante Webhooks (Notificaciones de eventos de pago):
El administrador SaaS genera la factura en saas_facturas.
El sistema envía un link de pago o procesa la tarjeta a través de la API de la pasarela elegida.
Cuando el laboratorio paga (vía Nequi, Tarjeta o PSE), la pasarela le avisa a tu backend en FastAPI mediante un webhook seguro.
FastAPI registra automáticamente el pago en la tabla saas_pagos, recalcula el saldo_pendiente en la factura y, si la factura queda pagada en su totalidad, activa o extiende automáticamente la vigencia de la licencia en saas_suscripciones.