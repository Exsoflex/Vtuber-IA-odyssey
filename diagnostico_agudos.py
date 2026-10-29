"""
¿Quién mata los agudos: el micrófono o el procesado de Windows?

Graba el mismo sonido por dos caminos:

    WASAPI   -> pasa por el motor de audio de Windows (Nahimic, Intel SST, APOs)
    WDM-KS   -> acceso directo al hardware, sin procesado de Windows

El sonido de prueba es una "s" sostenida (ssssss), que es casi todo agudo.
Así se ve en un segundo si el filtro es de software o del micrófono.

Uso:
    .venv\\Scripts\\python.exe diagnostico_agudos.py
"""

import time

import numpy as np
import soundfile as sf

FS = 48000
DURACION = 3.0
FRASE = "ssssssssssssssss"   # s sostenida, como una serpiente


def bandas(x: np.ndarray, fs: int) -> dict[str, float]:
    esp = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    freqs = np.fft.rfftfreq(len(x), 1 / fs)
    total = esp.sum() or 1.0
    return {f"{lo}-{hi}": 100 * esp[(freqs >= lo) & (freqs < hi)].sum() / total
            for lo, hi in [(0, 300), (300, 1000), (1000, 3000), (3000, 8000), (8000, 16000)]}


def grabar(nombre: str, dispositivo: int, canales: int) -> np.ndarray | None:
    import sounddevice as sd

    print(f"\n--- {nombre} (device {dispositivo}, {canales} canal/es) ---")
    try:
        sd.check_input_settings(device=dispositivo, samplerate=FS, channels=canales, dtype="int16")
    except Exception as e:
        print(f"    NO DISPONIBLE: {e}")
        return None

    input(f"    Pulsa ENTER y prepárate para hacer: {FRASE}")
    for s in (3, 2, 1):
        print(f"      ... {s}")
        time.sleep(1)
    print("      ¡SSSSSSSS AHORA!")

    with sd.InputStream(device=dispositivo, samplerate=FS, channels=canales,
                        dtype="int16", blocksize=int(FS * 0.1)) as stream:
        bloques = [stream.read(int(FS * 0.1))[0].copy() for _ in range(int(DURACION / 0.1))]

    datos = np.concatenate(bloques)
    mono = datos[:, 0].astype(np.float64) if datos.ndim > 1 else datos.astype(np.float64)
    mono /= 32768
    sf.write(f"agudos_{nombre}.wav", (mono * 32767).astype(np.int16), FS)

    rms = float(np.sqrt(np.mean(mono ** 2)))
    reparto = bandas(mono, FS)
    print(f"    RMS={rms:.4f} pico={np.max(np.abs(mono)):.3f}")
    print("    " + " | ".join(f"{k}={v:5.1f}%" for k, v in reparto.items()))
    print(f"    >>> agudos (>3 kHz): {reparto['3000-8000'] + reparto['8000-16000']:.1f}%")
    return mono


def main() -> None:
    print("=" * 64)
    print(" ¿MICRÓFONO APAGADO O WINDOWS APAGANDO LOS AGUDOS?")
    print("=" * 64)
    print("Vas a hacer 'ssssss' tres veces. Es el sonido con más agudos que")
    print("puede producir tu boca: ideal para medir si el micrófono los capta.")
    print("No importa el volumen exacto, solo que sea el mismo en las tres.")

    wasapi = grabar("wasapi", 64, 1)
    wdmks = grabar("wdmks", 76, 2)
    normal = grabar("frase", 76, 2)

    print("\n" + "=" * 64)
    print(" RESULTADO")
    print("=" * 64)
    if wasapi is not None and wdmks is not None:
        a = bandas(wasapi, FS)
        b = bandas(wdmks, FS)
        agudo_wasapi = a["3000-8000"] + a["8000-16000"]
        agudo_wdmks = b["3000-8000"] + b["8000-16000"]
        print(f"  WASAPI (con procesado): {agudo_wasapi:5.1f}% de agudos")
        print(f"  WDM-KS (sin procesado): {agudo_wdmks:5.1f}% de agudos")
        if agudo_wdmks > 3 * max(agudo_wasapi, 0.5):
            print("\n  ✅ El procesado de Windows está apagando los agudos.")
            print("     Culpables probables: Nahimic / mejoras de audio / Intel SST.")
        elif agudo_wdmks < 5 and agudo_wasapi < 5:
            print("\n  ⚠️  Ni siquiera el acceso directo capta agudos.")
            print("     Entonces es físico: distancia, orientación o el propio micrófono.")
        else:
            print("\n  ➖ Diferencia no concluyente; revisa los WAV generados.")


if __name__ == "__main__":
    main()
