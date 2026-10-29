"""
¿Por qué Niu no te entiende? Susurro vs voz normal, medido en 30 segundos.

Graba la MISMA frase tres veces, con la misma postura y el mismo volumen
de Windows. Lo único que cambia es cómo produces la voz:

    1. susurrando (como si no quisieras que te oigan)
    2. con voz normal pero bajita, sin gritar
    3. con voz normal, un poco más cerca del micrófono

Para cada toma mide la "periodicidad" (la vibración de las cuerdas vocales)
y transcribe con Whisper large-v3 en GPU.

Qué buscar en el resultado:
    - periodicidad > 0.5 y Whisper acierta  ->  el micrófono está bien y
      Niu te entiende. El problema era solo el susurro.
    - las tres tomas con periodicidad < 0.45  ->  hay procesado de audio
      (Nahimic / mejoras de Windows) destruyendo la voz. Eso se arregla
      desactivándolo.

Uso:
    .venv\\Scripts\\python.exe prueba_de_voz.py
"""

import os
import time

import numpy as np
import soundfile as sf

# CUDA: CTranslate2 necesita encontrar cublas/cudnn en el PATH del proceso.
_SITEPKG = os.path.dirname(os.path.abspath(sf.__file__))
for _sub in ("cublas", "cudnn", "cuda_nvrtc"):
    _ruta = os.path.join(_SITEPKG, "nvidia", _sub, "bin")
    if os.path.isdir(_ruta):
        os.environ["PATH"] = _ruta + os.pathsep + os.environ.get("PATH", "")

FS = 16000
DURACION = 5.0
FRASE = "Hola Niu, esto es una prueba de voz. ¿Me estás entendiendo bien?"

TOMAS = [
    ("susurro", "SUSURRA la frase (como si no quisieras que te oigan)."),
    ("normal_bajo", "Di la frase HABLANDO, con voz normal pero bajita. Sin gritar."),
    ("cerca", "Otra vez hablando, y acerca la boca al micrófono (5-10 cm)."),
]


def rms(x):
    return float(np.sqrt(np.mean(x.astype(np.float64) ** 2)))


def periodicidad(x, fs=FS, ventana=0.04, salto=0.02):
    """Proporción de tramos con vibración de cuerdas vocales clara."""
    n, s = int(fs * ventana), int(fs * salto)
    picos, niveles = [], []
    for i in range(0, len(x) - n, s):
        m = x[i:i + n].astype(np.float64)
        nivel = np.sqrt(np.mean(m ** 2))
        if nivel < 1e-5:
            continue
        m = (m - m.mean()) * np.hanning(n)
        c = np.correlate(m, m, "full")[n - 1:]
        c /= (c[0] or 1.0)
        lo, hi = int(fs / 400), min(int(fs / 80), len(c) - 1)
        picos.append(float(np.max(c[lo:hi])) if hi > lo else 0.0)
        niveles.append(nivel)
    if not picos:
        return 0.0, 0.0
    picos, niveles = np.array(picos), np.array(niveles)
    sel = niveles >= np.percentile(niveles, 60)
    return float(picos[sel].mean()), 100 * float(np.mean(picos[sel] > 0.45))


def grabar(instruccion):
    import sounddevice as sd
    from core.audio_devices import buscar_dispositivo

    dispositivo = buscar_dispositivo(os.getenv("NIU_MIC", "DGM20"), salida=False)
    info = sd.query_devices(dispositivo)
    fs_real = int(info["default_samplerate"])
    canales = max(1, min(2, int(info["max_input_channels"])))

    print(f"\n  {instruccion}")
    for s in (3, 2, 1):
        print(f"    ... {s}")
        time.sleep(1)
    print("    ¡AHORA!")

    # OJO: pedir channels=1 a un dispositivo estéreo corrompe el audio en
    # WASAPI (se dispara el tono y se pierden los agudos). Se captura con los
    # canales nativos y se elige después el que tiene señal.
    with sd.InputStream(device=dispositivo, samplerate=fs_real, channels=canales,
                        dtype="int16", blocksize=int(fs_real * 0.1)) as stream:
        bloques = [stream.read(int(fs_real * 0.1))[0].copy()
                   for _ in range(int(DURACION / 0.1))]

    datos = np.concatenate(bloques)
    if datos.ndim > 1:
        datos = datos[:, int(np.argmax(np.std(datos.astype(np.float64), axis=0)))]
    mono = datos.flatten()
    if fs_real != FS:
        n = int(len(mono) * FS / fs_real)
        mono = np.interp(np.linspace(0, len(mono) - 1, n),
                         np.arange(len(mono)), mono.astype(np.float64))
        mono = np.clip(mono, -32768, 32767).astype(np.int16)
    return mono, rms(mono)


def main():
    print("=" * 68)
    print(" ¿SUSURRO O VOZ NORMAL? — LA PRUEBA DEFINITIVA")
    print("=" * 68)
    print(f"Frase: {FRASE!r}")
    print("Mismo micrófono, misma distancia y mismo volumen de Windows.")
    print("No hace falta hablar fuerte: solo HABLAR en vez de susurrar.")

    from faster_whisper import WhisperModel

    print("\nCargando Whisper large-v3 en GPU...")
    try:
        modelo = WhisperModel("large-v3", device="cuda", compute_type="float16")
        print("  ✅ GPU")
    except Exception as e:
        print(f"  ({type(e).__name__}) usando CPU")
        modelo = WhisperModel("small", device="cpu", compute_type="int8", cpu_threads=8)

    resultados = []
    for nombre, instruccion in TOMAS:
        pcm, nivel = grabar(instruccion)
        sf.write(f"voz_{nombre}.wav", pcm, FS)

        per, vozeado = periodicidad(pcm)
        audio = pcm.astype(np.float32) / 32768
        audio = audio * (0.9 / (np.max(np.abs(audio)) or 1.0))
        t0 = time.perf_counter()
        seg, _ = modelo.transcribe(audio, language="es", beam_size=5, vad_filter=True,
                                   condition_on_previous_text=False)
        texto = " ".join(s.text.strip() for s in seg)
        dt = time.perf_counter() - t0

        print(f"    -> periodicidad={per:.3f} | voz clara={vozeado:.0f}% "
              f"| RMS={nivel:.0f} | {dt:.1f} s")
        print(f"    -> Whisper: {texto!r}")
        resultados.append((nombre, per, vozeado, texto))

    print("\n" + "=" * 68)
    print(" RESULTADO")
    print("=" * 68)
    print(f"  {'toma':14s}{'periodicidad':>14s}{'voz clara':>12s}   transcripción")
    for nombre, per, vozeado, texto in resultados:
        print(f"  {nombre:14s}{per:14.3f}{vozeado:11.0f}%   {texto[:44]!r}")

    acertadas = [n for n, _, _, t in resultados if "entiend" in t.lower()]
    print()
    if acertadas:
        print(f"  ✅ Whisper entendió la frase en: {', '.join(acertadas)}")
        print("     El micrófono está bien. Habla normal y Niu te entiende.")
    else:
        print("  ⚠️  No acertó en ninguna toma.")
        print("     Si la periodicidad también es baja en 'normal_bajo', el")
        print("     problema es procesado de audio: desactiva Nahimic y las")
        print("     mejoras de audio de Windows, y repite esta prueba.")


if __name__ == "__main__":
    main()
