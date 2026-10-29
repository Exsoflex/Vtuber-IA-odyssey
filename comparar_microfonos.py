"""
¿El problema es el micrófono o nuestro conversor a 16 kHz?

Graba la misma frase con dos micrófonos:

    1. DGM20 (el del proyecto)
    2. El array interno del portátil (Intel Smart Sound)

y con cada uno calcula:

    - periodicidad de la voz, medida en la señal CRUDA de 48 kHz,
    - reparto de energía por bandas,
    - qué entiende Whisper con dos formas de bajar a 16 kHz:
        (a) interpolación lineal  <- lo que hace core/stt.py ahora
        (b) remuestreo por FFT con filtro antialiasing

Por qué importa (a) vs (b): bajar de 48 kHz a 16 kHz sin filtrar antes
mezcla al rango audible todo lo que había por encima de 8 kHz (aliasing).
Eso añade ruido y puede destruir la estructura de la voz.

Si en el mismo micrófono (a) falla y (b) acierta, el error está en el
código, no en el hardware.

Uso:
    .venv\\Scripts\\python.exe comparar_microfonos.py
"""

import os
import time

import numpy as np
import soundfile as sf

# CUDA: CTranslate2 busca cublas/cudnn en el PATH del proceso.
_SITEPKG = os.path.dirname(os.path.abspath(sf.__file__))
for _sub in ("cublas", "cudnn", "cuda_nvrtc"):
    _ruta = os.path.join(_SITEPKG, "nvidia", _sub, "bin")
    if os.path.isdir(_ruta):
        os.environ["PATH"] = _ruta + os.pathsep + os.environ.get("PATH", "")

FS = 16000
DURACION = 6.0
FRASE = "Hola Niu, esto es una prueba. ¿Me entiendes ahora?"

CANDIDATOS = [
    ("DGM20", "DGM20"),
    ("Intel", "interno del portátil"),
]


# --------------------------------------------------------------------------
# Audio
# --------------------------------------------------------------------------
def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x.astype(np.float64) ** 2)))


def a_float(x: np.ndarray) -> np.ndarray:
    return x.astype(np.float64) / 32768.0


def diezmar_ingenuo(x: np.ndarray, fs_in: int, fs_out: int = FS) -> np.ndarray:
    """Lo que hace el proyecto: interpolar sin filtrar antes."""
    n = int(len(x) * fs_out / fs_in)
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x)


def remuestrear_fft(x: np.ndarray, fs_in: int, fs_out: int = FS) -> np.ndarray:
    """
    Remuestreo por FFT: se queda solo con las frecuencias que caben en la
    nueva tasa. Es exactamente el filtro antialiasing que falta arriba.
    """
    n_out = int(round(len(x) * fs_out / fs_in))
    espectro = np.fft.rfft(x)
    nuevo = np.zeros(n_out // 2 + 1, dtype=complex)
    k = min(len(espectro), len(nuevo))
    nuevo[:k] = espectro[:k]
    return np.fft.irfft(nuevo * (n_out / len(x)), n=n_out)


def normalizar(x: np.ndarray, obj: float = 0.9) -> np.ndarray:
    return (x / (np.max(np.abs(x)) or 1.0) * obj).astype(np.float32)


def bandas(x: np.ndarray, fs: int) -> dict[str, float]:
    n, s = int(fs * 0.04), int(fs * 0.02)
    marcos, energias = [], []
    for i in range(0, len(x) - n, s):
        m = x[i:i + n] * np.hanning(n)
        e = float(np.sum(m ** 2))
        if e < 1e-9:
            continue
        marcos.append(np.abs(np.fft.rfft(m)) ** 2)
        energias.append(e)
    energias = np.array(energias)
    sel = energias >= np.percentile(energias, 60)
    prom = np.mean([m for m, keep in zip(marcos, sel) if keep], axis=0)
    fr = np.fft.rfftfreq(n, 1 / fs)
    total = prom.sum() or 1.0
    return {f"{lo}-{hi}": 100 * prom[(fr >= lo) & (fr < hi)].sum() / total
            for lo, hi in [(0, 100), (100, 300), (300, 1000), (1000, 3000), (3000, 8000)]}


def periodicidad(x: np.ndarray, fs: int) -> tuple[float, float, float]:
    """(media del pico, % de tramos vozeados, F0 mediana). Se mide en fs real."""
    n, s = int(fs * 0.04), int(fs * 0.02)
    lo, hi = int(fs / 400), int(fs / 60)
    picos, f0s, niveles = [], [], []
    for i in range(0, len(x) - n, s):
        m = x[i:i + n].astype(np.float64)
        nivel = np.sqrt(np.mean(m ** 2))
        if nivel < 1e-5:
            continue
        m = (m - m.mean()) * np.hanning(n)
        f = np.fft.rfft(m, 2 * n)
        ac = np.fft.irfft(f * np.conj(f))[:n]
        ac /= (ac[0] or 1.0)
        tramo = ac[lo:hi]
        pico = float(np.max(tramo))
        picos.append(pico)
        niveles.append(nivel)
        if pico > 0.45:
            f0s.append(fs / (int(np.argmax(tramo)) + lo))
    if not picos:
        return 0.0, 0.0, 0.0
    picos, niveles = np.array(picos), np.array(niveles)
    sel = niveles >= np.percentile(niveles, 60)
    f0 = float(np.median(f0s)) if f0s else 0.0
    return float(picos[sel].mean()), 100 * float(np.mean(picos[sel] > 0.45)), f0


# --------------------------------------------------------------------------
# Captura
# --------------------------------------------------------------------------
def buscar(fragmento: str) -> int | None:
    import sounddevice as sd

    mejor = None
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0 and fragmento.lower() in d["name"].lower():
            if "WASAPI" in sd.query_hostapis(d["hostapi"])["name"]:
                return i
            mejor = i if mejor is None else mejor
    return mejor


def grabar(dispositivo: int) -> tuple[np.ndarray, int] | None:
    import sounddevice as sd

    print(f"\n--- {sd.query_devices(dispositivo)['name']} (dispositivo {dispositivo}) ---")
    print(f"    Di con voz normal: {FRASE!r}")
    input("    Pulsa ENTER cuando estés listo...")
    for s in (3, 2, 1):
        print(f"      ... {s}")
        time.sleep(1)
    print("      ¡HABLA AHORA!")

    fs_real = int(sd.query_devices(dispositivo)["default_samplerate"])
    with sd.InputStream(device=dispositivo, samplerate=fs_real, channels=1,
                        dtype="int16", blocksize=int(fs_real * 0.1)) as stream:
        bloques = [stream.read(int(fs_real * 0.1))[0].copy()
                   for _ in range(int(DURACION / 0.1))]
    mono = np.concatenate(bloques).flatten()

    print(f"    RMS={rms(mono):7.1f} | pico={int(np.max(np.abs(mono)))} de 32767")
    return mono, fs_real


# --------------------------------------------------------------------------
def main() -> None:
    print("=" * 70)
    print(" ¿MICRÓFONO MALO O CONVERSOR MALO?")
    print("=" * 70)
    print(f"Frase: {FRASE!r}")
    print("Misma frase, misma distancia, misma voz normal (sin susurrar).")

    from faster_whisper import WhisperModel

    print("\nCargando Whisper large-v3 en GPU...")
    try:
        modelo = WhisperModel("large-v3", device="cuda", compute_type="float16")
        print("  ✅ GPU")
    except Exception as e:
        print(f"  ({type(e).__name__}) uso CPU")
        modelo = WhisperModel("small", device="cpu", compute_type="int8", cpu_threads=8)

    def transcribir(audio16k: np.ndarray, nombre: str) -> str:
        t0 = time.perf_counter()
        seg, _ = modelo.transcribe(normalizar(audio16k), language="es", beam_size=5,
                                   vad_filter=False, condition_on_previous_text=False)
        texto = " ".join(s.text.strip() for s in seg)
        print(f"      {nombre:26s} {time.perf_counter() - t0:4.1f} s -> {texto!r}")
        return texto

    filas = []
    for fragmento, etiqueta in CANDIDATOS:
        dispositivo = buscar(fragmento)
        if dispositivo is None:
            print(f"\n[AVISO] No hay dispositivo que contenga '{fragmento}'.")
            continue
        salida = grabar(dispositivo)
        if salida is None:
            continue
        pcm, fs_real = salida
        archivo = f"crudo_{fragmento.lower()}.wav"
        sf.write(archivo, pcm, fs_real)
        print(f"    guardado {archivo} ({fs_real} Hz)")

        x = a_float(pcm)
        per, vozeado, f0 = periodicidad(x, fs_real)
        rep = bandas(x, fs_real)
        print(f"    periodicidad={per:.3f} | voz clara={vozeado:.0f}% | F0={f0:.0f} Hz")
        print("    " + " | ".join(f"{k}={v:5.1f}%" for k, v in rep.items()))

        print("    Transcripción a 16 kHz:")
        t_ing = transcribir(diezmar_ingenuo(x, fs_real), "inyectando tal cual")
        t_fft = transcribir(remuestrear_fft(x, fs_real), "con antialiasing (FFT)")

        filas.append((etiqueta, per, vozeado, rep, t_ing, t_fft))

    if not filas:
        print("\nSin mediciones.")
        return

    print("\n" + "=" * 70)
    print(" RESULTADO")
    print("=" * 70)
    for etiqueta, per, vozeado, rep, t_ing, t_fft in filas:
        print(f"\n  {etiqueta}")
        print(f"    periodicidad={per:.3f}  voz clara={vozeado:.0f}%  "
              f"300-1000 Hz={rep['300-1000']:.1f}%  3-8 kHz={rep['3000-8000']:.1f}%")
        print(f"    sin filtrar  -> {t_ing!r}")
        print(f"    con filtro   -> {t_fft!r}")

    if len(filas) == 2:
        (e1, p1, v1, _, _, t1), (e2, p2, v2, _, _, t2) = filas
        print("\n  Cómo leerlo:")
        if p1 < 0.45 and p2 < 0.45:
            print("  ⚠️  Los DOS micrófonos dan voz sin periodicidad.")
            print("     No es el micrófono: es procesado de audio de Windows")
            print("     (Nahimic / mejoras) o algo del sistema.")
        elif p1 < 0.45 <= p2:
            print(f"  ⚠️  {e1} está mal y {e2} bien. El problema es ese micrófono")
            print("     (colocación, ganancia o hardware), no el código.")
        else:
            print("  ✅ El micrófono del proyecto da voz normal.")
