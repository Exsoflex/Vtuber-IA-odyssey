"""
Prueba de bucle acústico: ¿el micrófono destruye la voz, o es la voz?

Se reproduce una frase conocida por los auriculares del DGM20 y se graba con
el propio micrófono del DGM20. Si Whisper entiende lo grabado, la cadena de
captura está bien y el problema es la producción de voz (volumen, aire).

No hace falta hablar ni acercarse: solo tener el auricular puesto, porque el
micrófono captará el sonido que se escape del auricular.

Uso:
    .venv\\Scripts\\python.exe prueba_loopback.py
"""

import asyncio
import os
import time

import numpy as np
import soundfile as sf

_SITEPKG = os.path.dirname(os.path.abspath(sf.__file__))
for _sub in ("cublas", "cudnn", "cuda_nvrtc"):
    _ruta = os.path.join(_SITEPKG, "nvidia", _sub, "bin")
    if os.path.isdir(_ruta):
        os.environ["PATH"] = _ruta + os.pathsep + os.environ.get("PATH", "")

FRASE = "Hola Niu, esto es una prueba de bucle. ¿Me entiendes ahora? Quiero hablar contigo."
VOLUMEN = 0.35


def buscar(fragmento: str, salida: bool) -> int | None:
    import sounddevice as sd

    clave = "max_output_channels" if salida else "max_input_channels"
    mejor = None
    for i, d in enumerate(sd.query_devices()):
        if d[clave] > 0 and fragmento.lower() in d["name"].lower():
            if "WASAPI" in sd.query_hostapis(d["hostapi"])["name"]:
                return i
            mejor = i if mejor is None else mejor
    return mejor


def remuestrear_fft(x, fs_in, fs_out=16000):
    n_out = int(round(len(x) * fs_out / fs_in))
    esp = np.fft.rfft(x)
    nuevo = np.zeros(n_out // 2 + 1, dtype=complex)
    k = min(len(esp), len(nuevo))
    nuevo[:k] = esp[:k]
    return np.fft.irfft(nuevo * (n_out / len(x)), n=n_out)


def diezmar_ingenuo(x, fs_in, fs_out=16000):
    n = int(len(x) * fs_out / fs_in)
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x)


def periodicidad(x, fs=16000, ventana=0.04, salto=0.02):
    n, s = int(fs * ventana), int(fs * salto)
    lo, hi = int(fs / 400), int(fs / 60)
    picos, niveles = [], []
    for i in range(0, len(x) - n, s):
        m = x[i:i + n].astype(np.float64)
        nivel = np.sqrt(np.mean(m ** 2))
        if nivel < 1e-5:
            continue
        m = (m - m.mean()) * np.hanning(n)
        f = np.fft.rfft(m, 2 * n)
        ac = np.fft.irfft(f * np.conj(f))[:n]
        ac /= (ac[0] or 1.0)
        picos.append(float(np.max(ac[lo:hi])))
        niveles.append(nivel)
    picos, niveles = np.array(picos), np.array(niveles)
    sel = niveles >= np.percentile(niveles, 60)
    return float(picos[sel].mean()), 100 * float(np.mean(picos[sel] > 0.45))


def main() -> None:
    import sounddevice as sd
    from faster_whisper import WhisperModel

    print("=" * 70)
    print(" PRUEBA DE BUCLE: ¿MICRÓFONO O VOZ?")
    print("=" * 70)
    print("Se reproduce una frase por los auriculares y se graba con el micro.")
    print("Ponte el auricular (o acércalo al micrófono) y sube un poco el volumen.")

    # 1. Generar la frase de referencia
    ruta_ref = os.path.join(os.environ["TEMP"], "loopback_ref.mp3")
    asyncio.run(edge_tts_guardar(FRASE, ruta_ref))
    ref, fs_ref = sf.read(ruta_ref, dtype="int16")
    ref = ref.astype(np.float64) / 32768
    print(f"\n  Frase de referencia: {len(ref) / fs_ref:.2f} s a {fs_ref} Hz")

    # 2. Reproducir y grabar a la vez
    salida = buscar("Auriculares", salida=True) or buscar("DGM20", salida=True)
    entrada = buscar("DGM20", salida=False)
    if salida is None or entrada is None:
        print("  No encontré los dispositivos del DGM20.")
        return
    print(f"  Reproduciendo por: {sd.query_devices(salida)['name']}")
    print(f"  Grabando con:      {sd.query_devices(entrada)['name']}")

    # WASAPI compartido solo admite la frecuencia del mezclador del dispositivo
    # (48 kHz aquí), no la del MP3 (24 kHz). Hay que remuestrear antes de sonar.
    fs = 48000
    fs_play = int(sd.query_devices(salida)["default_samplerate"])
    ref_play = ref if fs_ref == fs_play else remuestrear_fft(ref, fs_ref, fs_play)

    duracion = len(ref_play) / fs_play + 1.5
    sd.play(ref_play * VOLUMEN, fs_play, device=salida)
    with sd.InputStream(device=entrada, samplerate=fs, channels=1,
                        dtype="int16", blocksize=int(fs * 0.1)) as stream:
        bloques = [stream.read(int(fs * 0.1))[0].copy()
                   for _ in range(int(duracion / 0.1))]
    sd.stop()

    grabado = np.concatenate(bloques).flatten()
    x = grabado.astype(np.float64) / 32768
    nivel = float(np.sqrt(np.mean(x ** 2)))
    sf.write("loopback_grabado.wav", grabado, fs)
    print(f"\n  Grabado: {len(x) / fs:.2f} s | RMS={nivel:.5f} | pico={np.max(np.abs(x)):.4f}")

    if nivel < 0.001:
        print("\n  ⚠️  Se grabó casi nada. Sube el volumen del sistema y repite,")
        print("      o acerca el auricular al micrófono. Sin señal no hay prueba.")
        return

    # 3. Analizar
    print("\n  Analizando...")
    per, vozeado = periodicidad(x, fs)
    print(f"  periodicidad={per:.3f} | voz clara={vozeado:.0f}%")

    modelo = WhisperModel("large-v3", device="cuda", compute_type="float16")

    def transcribir(audio, nombre):
        t0 = time.perf_counter()
        audio = audio / (np.max(np.abs(audio)) or 1.0) * 0.9
        seg, _ = modelo.transcribe(audio.astype(np.float32), language="es",
                                   beam_size=5, vad_filter=False,
                                   condition_on_previous_text=False)
        texto = " ".join(s.text.strip() for s in seg)
        print(f"  {nombre:28s} {time.perf_counter() - t0:4.1f} s -> {texto!r}")
        return texto

    print(f"\n  Frase real: {FRASE!r}")
    t_ing = transcribir(diezmar_ingenuo(x, fs), "decimación del proyecto")
    t_fft = transcribir(remuestrear_fft(x, fs), "con antialiasing")

    print("\n" + "=" * 70)
    print(" VEREDICTO")
    print("=" * 70)
    aciertos = sum("entiend" in t.lower() for t in (t_ing, t_fft))
    if aciertos:
        print("  ✅ El micrófono SÍ captura voz inteligible.")
        print("     La cadena de audio está bien. Lo que falla es la producción")
        print("     de voz: volumen bajo o voz con mucho aire (susurro).")
        print("     Solución: sube la ganancia en Windows y habla con voz normal;")
        print("     no hace falta gritar.")
    else:
        print("  ❌ El micrófono NO captura voz inteligible ni siquiera desde")
        print("     el auricular. Entonces la cadena de captura sí está dañada")
        print("     (procesado de Windows/Nahimic o el propio dispositivo).")


async def edge_tts_guardar(texto: str, ruta: str) -> None:
    import edge_tts

    if os.path.exists(ruta):
        return
    await edge_tts.Communicate(texto, voice="es-MX-JorgeNeural").save(ruta)


if __name__ == "__main__":
    main()
