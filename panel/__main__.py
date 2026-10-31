"""
Arranca el panel: `python -m panel`.

Se sirve solo en 127.0.0.1 para que Windows no pida permiso de firewall y para
que la interfaz no quede expuesta a la red local. El motor corre en el mismo
proceso y el mismo bucle de asyncio: cerrar el panel cierra el motor.
"""

from __future__ import annotations

import argparse
import asyncio

import uvicorn

from panel.app import crear_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Panel de control de Niu")
    parser.add_argument("--puerto", type=int, default=8000,
                        help="puerto local (por defecto 8000)")
    args = parser.parse_args()

    app = crear_app()
    servidor = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=args.puerto, log_level="warning")
    )

    print(f"[PANEL] Abre http://127.0.0.1:{args.puerto} en el navegador",
          flush=True)
    try:
        asyncio.run(servidor.serve())
    except KeyboardInterrupt:
        pass
    finally:
        print("[PANEL] Cerrado.", flush=True)


if __name__ == "__main__":
    main()
