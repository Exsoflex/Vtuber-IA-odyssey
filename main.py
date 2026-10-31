"""
Cliente de consola de Niu Autonomous Engine.

Aquí ya no vive la conversación: la conversación es `core/motor.py`. Este
archivo solo arranca el motor, se suscribe a sus eventos y los imprime. Así la
consola y el panel (fase 2 del plan) usan el mismo motor en vez de dos copias
que se van separando con cada cambio.

Entrada continua por voz o teclado. Para salir: di (o escribe) «salir».
"""

import asyncio
import sys

from core.motor import MotorNiu

# ─── UTF-8 y salida sin buffering en consola Windows ───────────────────────
sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)


def mostrar_tiempos(t: dict[str, float]) -> None:
    """Resume la latencia del turno: de tu silencio al primer sonido.

    En la primera línea está lo que decide si la conversación se siente fluida;
    la cifra que manda es la última. Con streaming, `texto` ya no es lo que
    tarda el cerebro en total, sino lo que tarda en tener lista la **primera
    frase**: es cuando se puede empezar a hablar.
    """
    hasta_sonido = sum(
        t.get(clave, 0.0) for clave in ("stt", "texto", "sintesis", "preparacion")
    )
    print(
        f"⏱️  STT {t.get('stt', 0.0):.2f} | 1ª frase {t.get('texto', 0.0):.2f} | "
        f"TTS {t.get('sintesis', 0.0):.2f} | preparar {t.get('preparacion', 0.0):.2f} | "
        f"➜ primer sonido {hasta_sonido:.2f} s"
    )
    print(
        f"    partes {int(t.get('partes', 0))} | hablando {t.get('voz', 0.0):.2f} s | "
        f"cerebro completo {t.get('generando', 0.0):.2f} s"
    )


def imprimir_evento(tipo: str, datos: dict) -> None:
    """Traduce los eventos del motor a la salida de siempre."""
    if tipo == "perfil":
        print(f"[IDIOMA] Perfil: {datos['nombre']} ({datos['codigo']}) | "
              f"voz: {datos['voz']} | tono: {datos['tono']}")
    elif tipo == "sistema":
        print(f"[SISTEMA] {datos['mensaje']}")
    elif tipo == "transcripcion":
        print(f"\n👤 Tú: {datos['texto']}   ({datos['ms']:.0f} ms)")
    elif tipo == "respuesta_inicio":
        print("\nNiu: ", end="", flush=True)
    elif tipo == "fragmento":
        print(datos["texto"], end="", flush=True)
    elif tipo == "respuesta":
        print()
    elif tipo == "metricas":
        mostrar_tiempos(datos["tiempos"])
    elif tipo == "error":
        print(f"❌ [Error] {datos['mensaje']}")
    # `estado` y `parte` no se imprimen: el panel los usa, la consola no.


async def main():
    """Punto de entrada principal de Niu Autonomous Engine."""
    print("//////////////////////////////////////////////////////")
    print("[INFO] Iniciando Niu Autonomous Engine (Motor v2.5)")
    print("////////////////////////////////////////////////______\n")

    motor = MotorNiu(permitir_teclado=True)
    motor.suscribir(imprimir_evento)

    try:
        await motor.iniciar()
    except Exception as e:
        print(f"❌ [Error] No se pudo iniciar el motor: {type(e).__name__}: {e}")
        return

    try:
        await motor.esperar()
    finally:
        await motor.detener()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[INFO] Programa interrumpido. ¡Adiós!")
