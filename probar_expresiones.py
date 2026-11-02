"""
Prueba de las expresiones de Niu: ¿existen y se pueden disparar los hotkeys?

Qué comprueba
-------------
Niu pide cuatro hotkeys por su nombre: `MouthSmile`, `MouthOpen`, `MouthFrown`
y `MouthAngry`. Un hotkey **no** es un parámetro: un parámetro
(`ParamMouthOpenY`) es un valor 0..1 que deforma el dibujo; un hotkey es una
acción guardada en VTube Studio (activar una expresión, lanzar una animación)
que se dispara por su nombre o por su ID.

Este script:

    1. Lista los hotkeys que tiene el modelo cargado, con su tipo y su
       archivo. Sirve para ver qué hay de verdad, sin suponer.
    2. Dispara los cuatro que Niu necesita y dice cuáles responden.

Uso:
    .venv\\Scripts\\python.exe probar_expresiones.py
"""

import asyncio
import sys

from core.motor import EXPRESIONES_NIU
from core.vts_client import vts_client

sys.stdout.reconfigure(encoding="utf-8")


async def listar() -> list[dict]:
    """Muestra los hotkeys del modelo y los devuelve."""
    hotkeys = await vts_client.listar_hotkeys()
    print(f"\n[1/2] Hotkeys del modelo cargado: {len(hotkeys)}")
    if not hotkeys:
        print("      ⚠️ No hay ningún hotkey. Se crean en VTube Studio →")
        print("         pestaña Hotkeys (una expresión o una animación con")
        print("         el nombre exacto que pide Niu).")
        return hotkeys

    for h in hotkeys:
        print(f"      - {h.get('name')!r:24} tipo={h.get('type')!r:20} "
              f"archivo={h.get('file')!r}")
    return hotkeys


async def comprobar(hotkeys: list[dict]) -> None:
    """Dispara los hotkeys que Niu espera y cuenta cuáles responden."""
    print(f"\n[2/2] Hotkeys que Niu necesita: {', '.join(EXPRESIONES_NIU)}")

    nombres = {str(h.get("name", "")).strip().lower() for h in hotkeys}
    faltan = [e for e in EXPRESIONES_NIU if e.lower() not in nombres]

    if faltan:
        print(f"      ❌ Faltan en el modelo: {', '.join(faltan)}")
        print("         Los que sí existen se prueban igualmente:")

    correctos = 0
    for expresion in EXPRESIONES_NIU:
        if expresion.lower() not in nombres:
            continue
        ok = await vts_client.trigger_expression(expresion)
        print(f"      {'✅' if ok else '❌'} {expresion}")
        correctos += int(ok)

    print()
    if not faltan and correctos == len(EXPRESIONES_NIU):
        print("      ✅ Los cuatro hotkeys existen y se disparan.")
        print("         Niu ya puede cambiar de expresión.")
    else:
        print("      ❌ Todavía no están los cuatro.")
        print("         Recuerda: el nombre debe coincidir exacto y el hotkey")
        print("         tiene que apuntar a una expresión o animación.")


async def main() -> None:
    print("=" * 70)
    print(" EXPRESIONES DE NIU — HOTKEYS DEL MODELO")
    print("=" * 70)

    if not await vts_client.connect_and_auth():
        return

    try:
        hotkeys = await listar()
        await comprobar(hotkeys)
    finally:
        await vts_client.close()


if __name__ == "__main__":
    asyncio.run(main())
