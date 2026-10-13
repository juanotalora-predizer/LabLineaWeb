"""Prueba manual: peticiones concurrentes mezclando laboratorios contra el servidor HTTPS local.

Verifica que ninguna respuesta muestre el laboratorio equivocado con el pool de conexiones real
(las pruebas automáticas corren sin pool) y compara tiempos entre subdominios existentes e
inexistentes (no deben permitir averiguar qué laboratorios existen).

    scripts/servidor_https.sh &
    .venv/bin/python scripts/pruebas_manuales/concurrencia_tenants.py "$(mkcert -CAROOT)/rootCA.pem"
"""

import asyncio
import random
import ssl
import statistics
import sys
import time

import httpx

CA = sys.argv[1]
TOTAL = 600
CONCURRENCIA = 50
ESPERADO = {"lab-a": "Laboratorio A Sintético", "lab-b": "Laboratorio B Sintético"}
AJENO = {"lab-a": "Laboratorio B Sintético", "lab-b": "Laboratorio A Sintético"}


async def main() -> None:
    contexto = ssl.create_default_context(cafile=CA)
    limite = asyncio.Semaphore(CONCURRENCIA)
    errores, cruces, tiempos = [], [], {"lab-a": [], "lab-b": [], "no-existe": []}

    async with httpx.AsyncClient(verify=contexto, timeout=20) as cliente:

        async def una(i: int) -> None:
            # Azar solo para mezclar peticiones; no es criptografía.
            sub = random.choice(["lab-a", "lab-b", "no-existe"])  # noqa: S311  # nosec B311
            async with limite:
                inicio = time.perf_counter()
                r = await cliente.get(f"https://{sub}.lablinea.localhost:8443/")
                tiempos[sub].append(time.perf_counter() - inicio)
            if sub == "no-existe":
                if r.status_code != 404:
                    errores.append((i, sub, r.status_code))
                return
            if r.status_code != 200 or ESPERADO[sub] not in r.text:
                errores.append((i, sub, r.status_code))
            if AJENO[sub] in r.text:
                cruces.append((i, sub))

        await asyncio.gather(*(una(i) for i in range(TOTAL)))

    print(f"Peticiones: {TOTAL} (concurrencia {CONCURRENCIA})")
    print(f"Errores: {len(errores)} · Respuestas con el laboratorio equivocado: {len(cruces)}")
    for sub, valores in tiempos.items():
        print(f"  {sub:10} n={len(valores):4} mediana={statistics.median(valores) * 1000:6.1f} ms")
    sys.exit(1 if errores or cruces else 0)


asyncio.run(main())
