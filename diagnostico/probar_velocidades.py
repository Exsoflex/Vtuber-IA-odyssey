"""
¿La grabación está a la velocidad equivocada?

Si un archivo se guarda con la frecuencia de muestreo mal declarada, la voz
suena más lenta o más rápida de lo real y NINGÚN motor de STT la entiende
(Whisper alucina, Gemini inventa idiomas). Y el espectro se comprime o se
estira, que es justo la deformación que medimos.

Aquí se prueba la misma grabación a varias velocidades y se mira en cuál
Whisper la entiende. También se imprime la forma espectral de cada versión:
la correcta debe parecerse a la TTS de referencia.
"""

import os
import sys

import numpy as np
import soundfile as sf

BASE = r"C:\Users\hecto\OneDrive\Documentos\Vtuber IA odyssey"

# El arreglo de las DLL de CUDA tiene que ocurrir antes de cargar faster-whisper.
_SITEPKG = os.path.dirname(os.path.abspath(sf.__file__))
for _sub in ("cublas", "cudnn", "cuda_nvrtc"):
    _ruta = os.path.join(_SITEPKG, "nvidia", _sub, "bin")
    if os.path.isdir(_ruta):
        os.environ["PATH"] = _ruta + os.pathsep + os.environ.get("PATH", "")

ARCHIVOS = [
    ("voz_cerca", os.path.join(BASE, "voz_cerca.wav")),
    ("voz_normal_bajo", os.path.join(BASE, "voz_normal_bajo.wav")),
    ("diagnostico_mic (control que SÍ funcionó)", os.path.join(BASE, "diagnostico_mic.wav")),
]

VELOCIDADES = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0]

FS_MODELO = 16000


def rms(x):
    return float(np.sqrt(np.mean(np.asarray(x, dtype=np.float64) ** 2)))


def remuestrear(x, fs_origen, fs_destino):
    """Remuestreo por FFT (se queda solo con las frecuencias que caben)."""
    n_out = int(round(len(x) * fs_destino / fs_origen))
    if n_out < 2:
        return np.zeros(2, dtype=np.float64)
    esp = np.fft.rfft(x)
    nuevo = np.zeros(n_out // 2 + 1, dtype=complex)
    k = min(len(esp), len(nuevo))
    nuevo[:k] = esp[:k]
    return np.fft.irfft(nuevo * (n_out / len(x)), n=n_out)


def forma_espectral(x, fs):
    """Niveles por banda relativos a 100-300 Hz (quita diferencias de volumen)."""
    n = int(fs * 0.04)
    if len(x) < n * 4:
        return None
    marcos = np.array([x[i:i + n] for i in range(0, len(x) - n, n // 2)])
    niveles = np.array([rms(m) for m in marcos])
    marcos = marcos[niveles >= np.percentile(niveles, 75)]
    psd = np.mean(np.abs(np.fft.rfft(marcos * np.hanning(n), axis=1)) ** 2, axis=0)
    frecs = np.fft.rfftfreq(n, 1 / fs)
    bandas = [(100, 300), (300, 1000), (1000, 3000), (3000, 8000)]
    vals = np.array([10 * np.log10(max(psd[(frecs >= lo) & (frecs < hi)].sum(), 1e-20))
                     for lo, hi in bandas])
    return vals - vals[0]


def main():
    print("Cargando Whisper large-v3...")
    from faster_whisper import WhisperModel

    try:
        modelo = WhisperModel("large-v3", device="cuda", compute_type="float16")
    except Exception as e:
        print(f"  ({type(e).__name__}) -> CPU int8")
        modelo = WhisperModel("large-v3", device="cpu", compute_type="int8", cpu_threads=8)

    def transcribir(y, fs):
        if fs != FS_MODELO:
            y = remuestrear(y, fs, FS_MODELO)
        y = y / (np.max(np.abs(y)) or 1.0) * 0.9
        seg, _ = modelo.transcribe(y.astype(np.float32), language="es",
                                   beam_size=5, vad_filter=False,
                                   condition_on_previous_text=False)
        return " ".join(s.text.strip() for s in seg).strip()

    for etiqueta, ruta in ARCHIVOS:
        if not os.path.exists(ruta):
            print(f"\n{etiqueta}: no existe")
            continue
        datos, fs = sf.read(ruta, dtype="int16")
        if datos.ndim > 1:
            datos = datos[:, 0]
        x = datos.astype(np.float64) / 32768.0

        print(f"\n{'=' * 74}")
        print(f" {etiqueta}  ({len(x) / fs:.2f} s, {fs} Hz, RMS {20 * np.log10(rms(x)):.1f} dBFS)")
        print(f"{'=' * 74}")

        for v in VELOCIDADES:
            # "acelerar k veces" = tratar el audio como si se hubiera grabado a k*fs
            y = x if v == 1.0 else remuestrear(x, fs * v, fs)
            forma = forma_espectral(y, fs)
            texto = transcribir(y, fs)
            forma_txt = " ".join(f"{a:+.0f}" for a in forma) if forma is not None else "?"
            print(f"  x{v:<4.1f} ({len(y) / fs:4.2f} s) banda[100-300,300-1k,1k-3k,3k-8k]="
                  f"{forma_txt:>16s}  -> {texto!r}")

    print("\n" + "=" * 74)
    print(" Cómo leerlo")
    print("=" * 74)
    print("  - Si alguna velocidad devuelve una frase coherente en español,")
    print("    el problema era SOLO la frecuencia de muestreo mal declarada.")
    print("  - La referencia de forma espectral de una voz buena es:")
    print("        +0  -2  -13  -16")
    print("    (la versión cuya forma se parezca a eso es la velocidad correcta).")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
