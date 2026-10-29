"""
¿Cuál es la forma correcta de abrir el micrófono? Cuatro rutas, una pasada.

Todo lo que hemos medido apunta a que el micrófono funciona, pero el audio
que llega al STT está deformado. Quedan cuatro sospechosos y esta prueba los
separa de una vez:

  1. WASAPI con 1 canal   <- lo que hace Niu ahora mismo
  2. WASAPI con 2 canales <- el dispositivo es estéreo; pedir 1 puede romperlo
  3. WDM-KS con 2 canales <- se salta el procesado de Windows (Nahimic, Intel)
  4. El array del portátil  <- para saber si el problema es el DGM20 o el PC

Cada toma se guarda SIN remuestrear (a la frecuencia real del dispositivo),
así que si algo suena lento o raro se ve en la propia grabación, no en un
resample posterior.

Vas a decir una frase corta cuatro veces. Frase:
    "Hola Niu, uno, dos, tres."

Es corta a propósito: no hay que levantar la voz ni hablar más fuerte de lo
normal. Al final se imprime qué ruta ha funcionado.

Uso:
    .venv\\Scripts\\python.exe elegir_ruta_mic.py
"""

import os
import time

import numpy as np
import soundfile as sf

BASE = r"C:\Users\hecto\OneDrive\Documentos\Vtuber IA odyssey"

# CUDA para Whisper
_SITEPKG = os.path.dirname(os.path.abspath(sf.__file__))
for _sub in ("cublas", "cudnn", "cuda_nvrtc"):
    _ruta = os.path.join(_SITEPKG, "nvidia", _sub, "bin")
    if os.path.isdir(_ruta):
        os.environ["PATH"] = _ruta + os.pathsep + os.environ.get("PATH", "")

FRASE = "Hola Niu, uno, dos, tres."
DURACION = 4.0
FS_MODELO = 16000


# ------------------------------------------------------------------ búsqueda
def buscar(host_contiene: str, fragmento: str) -> int | None:
    import sounddevice as sd

    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] < 1:
            continue
        if fragmento.lower() not in d["name"].lower():
            continue
        if host_contiene.lower() in sd.query_hostapis(d["hostapi"])["name"].lower():
            return i
    return None


def rms(x):
    return float(np.sqrt(np.mean(np.asarray(x, dtype=np.float64) ** 2)))


def remuestrear(x, fs_origen, fs_destino):
    n_out = int(round(len(x) * fs_destino / fs_origen))
    if n_out < 2:
        return np.zeros(2, dtype=np.float64)
    esp = np.fft.rfft(x)
    nuevo = np.zeros(n_out // 2 + 1, dtype=complex)
    k = min(len(esp), len(nuevo))
    nuevo[:k] = esp[:k]
    return np.fft.irfft(nuevo * (n_out / len(x)), n=n_out)


def tono_y_agudos(x, fs):
    """f0 mediana y centroide de los marcos más agudos."""
    n = int(fs * 0.04)
    lo, hi = int(fs / 400), int(fs / 60)
    f0s, centros = [], []
    frecs = np.fft.rfftfreq(n, 1 / fs)
    for i in range(0, len(x) - n, n // 2):
        m = x[i:i + n].astype(np.float64)
        if rms(m) < 1e-4:
            continue
        p = np.abs(np.fft.rfft(m * np.hanning(n))) ** 2
        if p.sum() <= 0:
            continue
        centros.append(float((p * frecs).sum() / p.sum()))
        mm = (m - m.mean()) * np.hanning(n)
        c = np.correlate(mm, mm, "full")[n - 1:]
        if c[0] <= 0:
            continue
        c = c / c[0]
        tramo = c[lo:hi]
        if len(tramo) < 3:
            continue
        k = int(np.argmax(tramo)) + lo
        if c[k] >= 0.35:
            f0s.append(fs / k)
    f0 = float(np.median(f0s)) if f0s else None
    cent = float(np.percentile(centros, 90)) if centros else None
    return f0, cent


def grabar(dispositivo: int, canales: int, fs: float, segundos: float):
    import sounddevice as sd

    bloque = int(fs * 0.1)
    with sd.InputStream(device=dispositivo, samplerate=int(fs), channels=canales,
                        dtype="int16", blocksize=bloque) as stream:
        partes = []
        for _ in range(int(segundos / 0.1)):
            partes.append(stream.read(bloque)[0].copy())
    datos = np.concatenate(partes)
    if datos.ndim > 1:
        # de un micro estéreo interesa el canal con señal
        nivel = [rms(datos[:, c]) for c in range(datos.shape[1])]
        datos = datos[:, int(np.argmax(nivel))]
    return datos.flatten(), int(fs)


def main():
    print("=" * 74)
    print(" ¿QUÉ RUTA DE CAPTURA FUNCIONA?")
    print("=" * 74)
    print(f"Frase para las CUATRO tomas: {FRASE!r}")
    print("Habla con tu voz normal. No hace falta gritar nada.")

    rutas = []
    for etiqueta, host, frag, canales in (
        ("WASAPI  1 canal ", "WASAPI", "DGM20", 1),
        ("WASAPI  2 canales", "WASAPI", "DGM20", 2),
        ("WDM-KS  2 canales", "WDM-KS", "DGM20", 2),
        ("Intel array 1 ch ", "WASAPI", "Intel", 1),
    ):
        idx = buscar(host, frag)
        if idx is None:
            print(f"  (no encontré la ruta {etiqueta})")
            continue
        rutas.append((etiqueta, idx, canales))

    from faster_whisper import WhisperModel

    print("\nCargando Whisper large-v3...")
    try:
        modelo = WhisperModel("large-v3", device="cuda", compute_type="float16")
    except Exception:
        modelo = WhisperModel("large-v3", device="cpu", compute_type="int8", cpu_threads=8)

    def transcribir(y, fs, velocidad=1.0):
        if velocidad != 1.0:
            y = remuestrear(y, fs * velocidad, fs)
        if fs != FS_MODELO:
            y = remuestrear(y, fs, FS_MODELO)
        y = y / (np.max(np.abs(y)) or 1.0) * 0.9
        seg, _ = modelo.transcribe(y.astype(np.float32), language="es",
                                   beam_size=5, vad_filter=False,
                                   condition_on_previous_text=False)
        return " ".join(s.text.strip() for s in seg).strip()

    resultados = []
    for etiqueta, idx, canales in rutas:
        import sounddevice as sd

        fs = int(sd.query_devices(idx)["default_samplerate"])
        print(f"\n--- {etiqueta}  (dispositivo {idx}, {fs} Hz) ---")
        print(f"    Di: {FRASE!r}")
        for s in (3, 2, 1):
            print(f"      ...{s}", flush=True)
            time.sleep(1)
        print("      ¡AHORA!", flush=True)

        try:
            pcm, fs = grabar(idx, canales, fs, DURACION)
        except Exception as e:
            print(f"      falló: {type(e).__name__}: {str(e)[:90]}")
            continue

        nombre = ("ruta_" + etiqueta.strip().lower().replace(" ", "_")
                  .replace("-", "").replace("__", "_"))
        sf.write(os.path.join(BASE, nombre + ".wav"), pcm, fs)

        x = pcm.astype(np.float64) / 32768.0
        f0, cent = tono_y_agudos(x, fs)
        t1 = transcribir(x, fs, 1.0)
        t15 = transcribir(x, fs, 1.5)

        nivel = 20 * np.log10(rms(x) + 1e-12)
        print(f"      RMS {nivel:6.1f} dBFS | pico {20 * np.log10(np.max(np.abs(x)) + 1e-12):6.1f} dBFS"
              f" | f0 {f0 if f0 is None else round(f0)} Hz | agudos {cent if cent is None else round(cent)} Hz")
        print(f"      1.0x -> {t1!r}")
        print(f"      1.5x -> {t15!r}")
        resultados.append((etiqueta, t1, t15, f0, cent))

    print("\n" + "=" * 74)
    print(" RESULTADO")
    print("=" * 74)
    print(f"  {'ruta':20s}{'f0':>7s}{'agudos':>9s}   1.0x / 1.5x")
    for etiqueta, t1, t15, f0, cent in resultados:
        print(f"  {etiqueta:20s}{'' if f0 is None else round(f0):>7}{'' if cent is None else round(cent):>9}")
        print(f"       {t1[:70]!r}")
        print(f"       {t15[:70]!r}")

    def acierta(t):
        return "niu" in t.lower() or "hola" in t.lower() or "uno" in t.lower()

    ganadoras = [e for e, t1, t15, *_ in resultados
                 if acierta(t1) or acierta(t15)]
    print()
    if ganadoras:
        print(f"  ✅ Funcionan: {', '.join(ganadoras)}")
        print("     Con esa ruta, Niu te entiende. Se configura en core/audio_devices.py")
        print("     o con la variable NIU_MIC del .env (el nombre del dispositivo).")
    else:
        print("  ⚠️  Ninguna ruta acertó. Entonces no es la ruta de captura.")
        print("     Lo siguiente sería el volumen de entrada de Windows y la")
        print("     distancia/orientación del micrófono. En ese caso apunta el")
        print("     resultado y lo miramos juntos.")


if __name__ == "__main__":
    main()
