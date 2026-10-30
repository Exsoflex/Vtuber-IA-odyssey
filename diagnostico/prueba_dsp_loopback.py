"""
Prueba del procesado de audio de Windows SIN que Héctor hable.

Idea: si reproduzco una frase conocida por el altavoz y la grabo con el mismo
micrófono por dos rutas distintas, la única diferencia posible es el procesado
de Windows:

    WASAPI  -> pasa por Nahimic / Intel SST / "mejoras de audio"
    WDM-KS  -> acceso directo al driver, sin efectos

Y como conozco el espectro de la frase original, puedo medir si la grabación
se parece al original o si Windows le ha cambiado la forma (típico: quitarle
los agudos y hincharle los graves).

Eso separa DOS causas que hasta ahora estaban mezcladas:
    - el micrófono / la voz / la acústica de la habitación
    - el procesado de software de Windows
"""

import os
import threading
import time

import numpy as np
import soundfile as sf

BASE = r"C:\Users\hecto\OneDrive\Documentos\Vtuber IA odyssey"
REFERENCIA = os.path.join(BASE, "ctrl_voz48.wav")

FS = 48000
DURACION_EXTRA = 1.0          # un poco antes y después de la frase


# ---------------------------------------------------------------- utilidades
def rms(x):
    return float(np.sqrt(np.mean(np.asarray(x, dtype=np.float64) ** 2)))


def db(v):
    return 20 * np.log10(max(float(v), 1e-12))


def espectro_forma(x, fs, marcos_fuertes=True):
    """
    Devuelve la forma del espectro en bandas, normalizada a 0 dB en 100-300 Hz.

    Normalizar así quita las diferencias de volumen y deja solo la FORMA:
    si Windows recorta agudos, se ve aquí aunque el volumen cambie.
    """
    n = int(fs * 0.02)
    if len(x) < n * 4:
        return None, None
    marcos = np.array([x[i:i + n] for i in range(0, len(x) - n, n)])
    niveles = np.array([rms(m) for m in marcos])
    if not np.any(niveles > 0):
        return None, None
    if marcos_fuertes:
        # solo los marcos donde hay señal: los que superan el percentil 75
        sel = niveles >= np.percentile(niveles, 75)
        marcos = marcos[sel]
    ventana = np.hanning(n)
    psd = np.mean(np.abs(np.fft.rfft(marcos * ventana, axis=1)) ** 2, axis=0)
    frecs = np.fft.rfftfreq(n, 1 / fs)

    bandas = [(100, 300), (300, 1000), (1000, 3000), (3000, 8000), (8000, 16000)]
    niveles_banda = []
    for lo, hi in bandas:
        sel = (frecs >= lo) & (frecs < hi)
        niveles_banda.append(10 * np.log10(max(psd[sel].sum(), 1e-20)))
    niveles_banda = np.array(niveles_banda)
    forma = niveles_banda - niveles_banda[0]        # 0 dB en 100-300 Hz
    return bandas, forma


def inclinacion(x, fs):
    """Energía de 1-8 kHz menos energía de 100-1000 Hz, en dB. Voz normal: ~-10 dB."""
    n = int(fs * 0.02)
    marcos = np.array([x[i:i + n] for i in range(0, len(x) - n, n)])
    niveles = np.array([rms(m) for m in marcos])
    marcos = marcos[niveles >= np.percentile(niveles, 75)]
    psd = np.mean(np.abs(np.fft.rfft(marcos * np.hanning(n), axis=1)) ** 2, axis=0)
    frecs = np.fft.rfftfreq(n, 1 / fs)
    agudos = psd[(frecs >= 1000) & (frecs < 8000)].sum()
    medios = psd[(frecs >= 100) & (frecs < 1000)].sum()
    return 10 * np.log10(max(agudos, 1e-20) / max(medios, 1e-20))


# ---------------------------------------------------------------- dispositivos
def dispositivo_salida():
    import sounddevice as sd

    preferencias = ["Altavoz de PC", "Altavoces", "Speakers", "Auriculares"]
    for pref in preferencias:
        for i, d in enumerate(sd.query_devices()):
            if d["max_output_channels"] >= 1 and pref.lower() in d["name"].lower():
                # preferir el backend que no da problemas desde hilos secundarios
                host = sd.query_hostapis(d["hostapi"])["name"]
                if "WDM-KS" in host:
                    continue
                return i, d["name"], host
    return None, None, None


def dispositivo_entrada(nombre_host):
    import sounddevice as sd

    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] < 1 or "DGM20" not in d["name"]:
            continue
        host = sd.query_hostapis(d["hostapi"])["name"]
        if nombre_host in host:
            return i
    return None


def grabar_mientras_suena(dispositivo, canales, senal, fs_salida, salida):
    """Reproduce `senal` y graba con `dispositivo` al mismo tiempo."""
    import sounddevice as sd

    capturado = []

    def callback(indata, frames, time_info, status):
        capturado.append(indata.copy())

    espera = DURACION_EXTRA
    total = len(senal) / fs_salida + 2 * espera

    hilo = threading.Thread(
        target=lambda: sd.play(senal, fs_salida, device=salida), daemon=True
    )

    with sd.InputStream(
        device=dispositivo, samplerate=FS, channels=canales, dtype="int16",
        blocksize=int(FS * 0.05), callback=callback,
    ):
        time.sleep(espera)
        hilo.start()
        time.sleep(total - espera)
        sd.stop()

    hilo.join(timeout=3)

    if not capturado:
        return None
    datos = np.concatenate(capturado)
    if datos.ndim > 1:
        niveles = [rms(datos[:, c]) for c in range(datos.shape[1])]
        datos = datos[:, int(np.argmax(niveles))]
    return datos.astype(np.int16)


# ---------------------------------------------------------------- principal
def main():
    print("=" * 74)
    print(" ¿EL PROCESADO DE WINDOWS ESTÁ ESTROPEANDO EL MICRÓFONO?")
    print("=" * 74)

    x, fs_ref = sf.read(REFERENCIA, dtype="int16")
    if x.ndim > 1:
        x = x[:, 0]
    fuente = x.astype(np.float64) / 32768.0
    fuente = fuente / (np.max(np.abs(fuente)) or 1.0) * 0.95

    salida, nombre_salida, host_salida = dispositivo_salida()
    if salida is None:
        print("No encontré altavoces. Conecta algo o avísame.")
        return
    print(f"\nFrase de referencia: {len(fuente) / fs_ref:.2f} s")
    print(f"Reproduciendo por : [{salida}] {nombre_salida} ({host_salida})")
    print(f"Volumen de la frase: pico al 95% del fondo de escala")

    bandas, forma_fuente = espectro_forma(fuente, fs_ref)
    tilt_fuente = inclinacion(fuente, fs_ref)
    print(f"\nORIGINAL -> inclinación (1-8k vs 100-1k) = {tilt_fuente:+.1f} dB")
    print("            forma: " + " | ".join(
        f"{lo}-{hi}={v:+.1f}" for (lo, hi), v in zip(bandas, forma_fuente)))

    resultados = {}
    for etiqueta, host in (("WASAPI", "WASAPI"), ("WDM-KS", "WDM-KS")):
        dispositivo = dispositivo_entrada(host)
        if dispositivo is None:
            print(f"\n[{etiqueta}] no encontrado")
            continue
        canales = 2 if etiqueta == "WDM-KS" else 1
        print(f"\n--- Grabando por {etiqueta} (dispositivo {dispositivo}) ---")
        pcm = grabar_mientras_suena(dispositivo, canales, fuente, fs_ref, salida)
        if pcm is None:
            print("    sin datos")
            continue

        ruta = os.path.join(BASE, f"dsp_{etiqueta.lower().replace('-', '')}.wav")
        sf.write(ruta, pcm, FS)

        y = pcm.astype(np.float64) / 32768.0
        _, forma = espectro_forma(y, FS)
        if forma is None:
            print("    grabación vacía")
            continue
        tilt = inclinacion(y, FS)

        # parecido de forma: distancia media en dB entre la grabación y el original
        error = float(np.mean(np.abs(forma - forma_fuente)))
        corr = float(np.corrcoef(forma, forma_fuente)[0, 1])

        print(f"    RMS {db(rms(y)):.1f} dBFS | pico {db(np.max(np.abs(y))):.1f} dBFS")
        print(f"    inclinación {tilt:+.1f} dB (original {tilt_fuente:+.1f}) "
              f"-> diferencia {tilt - tilt_fuente:+.1f} dB")
        print("    forma: " + " | ".join(
            f"{lo}-{hi}={v:+.1f}" for (lo, hi), v in zip(bandas, forma)))
        print(f"    parecido con el original: error medio {error:.1f} dB, "
              f"correlación {corr:+.3f}")
        resultados[etiqueta] = (tilt, error, corr, ruta)

    print("\n" + "=" * 74)
    print(" VEREDICTO")
    print("=" * 74)
    if len(resultados) < 2:
        print(" Faltan medidas: revisa los mensajes de arriba.")
        return

    t_w, e_w, *_ = resultados["WASAPI"]
    t_k, e_k, *_ = resultados["WDM-KS"]
    print(f"  WASAPI : inclinación {t_w:+.1f} dB (error {e_w:.1f} dB vs original)")
    print(f"  WDM-KS : inclinación {t_k:+.1f} dB (error {e_k:.1f} dB vs original)")
    print()
    if e_k + 3.0 < e_w:
        print("  ✅ CONFIRMADO: WASAPI (con efectos) deforma el audio y WDM-KS no.")
        print("     Culpable: el procesado de audio de Windows (Nahimic / Intel SST).")
        print("     Solución inmediata: capturar por WDM-KS (sin admin).")
        print("     Solución definitiva: desactivar Nahimic y las mejoras.")
    elif abs(e_k - e_w) < 3.0:
        print("  ➖ Las dos rutas deforman el audio casi igual.")
        print("     Entonces NO es el procesado de Windows: es el micrófono,")
        print("     cómo está colocado, o el volumen de entrada.")
        print("     Siguiente prueba: subir el volumen de entrada en Windows y")
        print("     hablar de frente a 10-15 cm, sin gritar.")
    else:
        print("  ⚠️  WDM-KS sale peor, lo cual es raro. Revisa el volumen: puede")
        print("     que una de las dos tomas haya quedado casi muda.")


if __name__ == "__main__":
    main()
