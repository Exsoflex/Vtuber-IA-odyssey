"""
La prueba definitiva entre las dos rutas de captura del MISMO micrófono:

    WASAPI  -> pasa por el motor de audio de Windows: Nahimic, Intel SST,
               "mejoras de audio", supresión de ruido, AGC...
    WDM-KS  -> acceso directo al driver del dispositivo, sin efectos.

Si con WDM-KS la voz es normal y con WASAPI no, el culpable es el procesado
de audio de Windows. Y además tendríamos una solución que no requiere
permisos de administrador ni desinstalar nada.

Nota técnica: WDM-KS en PortAudio no soporta lectura bloqueante, por eso se
usa la API de callbacks de sounddevice.

Uso:
    .venv\\Scripts\\python.exe comparar_rutas.py
"""

import os
import time

import numpy as np
import soundfile as sf

_SITEPKG = os.path.dirname(os.path.abspath(sf.__file__))
for _sub in ("cublas", "cudnn", "cuda_nvrtc"):
    _ruta = os.path.join(_SITEPKG, "nvidia", _sub, "bin")
    if os.path.isdir(_ruta):
        os.environ["PATH"] = _ruta + os.pathsep + os.environ.get("PATH", "")

FS_ANALISIS = 16000
FS_CAPTURA = 48000
DURACION = 6.0
FRASE = "Hola Niu, esto es una prueba. ¿Me entiendes ahora?"


def rms(x):
    return float(np.sqrt(np.mean(x.astype(np.float64) ** 2)))


def remuestrear(x, fs_in, fs_out=FS_ANALISIS):
    """Remuestreo por FFT con filtro antialiasing."""
    n_out = int(round(len(x) * fs_out / fs_in))
    esp = np.fft.rfft(x)
    nuevo = np.zeros(n_out // 2 + 1, dtype=complex)
    k = min(len(esp), len(nuevo))
    nuevo[:k] = esp[:k]
    return np.fft.irfft(nuevo * (n_out / len(x)), n=n_out)


def bands(x, fs=FS_ANALISIS):
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


def periodicidad(x, fs):
    n, s = int(fs * 0.04), int(fs * 0.02)
    lo, hi = int(fs / 400), int(fs / 60)
    picos, niveles = [], []
    for i in range(0, len(x) - n, s):
        m = x[i:i + n].astype(np.float64)
        nivel = float(np.sqrt(np.mean(m ** 2)))
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


def grabar_callback(dispositivo: int, canales: int, duracion: float = DURACION):
    """Captura con la API de callbacks (obligatoria en WDM-KS)."""
    import sounddevice as sd

    capturado = []

    def callback(indata, frames, time_info, status):
        capturado.append(indata.copy())

    with sd.InputStream(
        device=dispositivo, samplerate=FS_CAPTURA, channels=canales,
        dtype="int16", blocksize=int(FS_CAPTURA * 0.05), callback=callback,
    ):
        time.sleep(duracion)

    if not capturado:
        return None
    datos = np.concatenate(capturado)
    if datos.ndim > 1:
        nivel = [rms(datos[:, c]) for c in range(datos.shape[1])]
        mejor = int(np.argmax(nivel))
        print(f"    canales: " + " | ".join(f"ch{c} RMS={v:.0f}" for c, v in enumerate(nivel))
              + f" -> uso ch{mejor}")
        datos = datos[:, mejor]
    return datos.flatten()


def busca_wasapi() -> int | None:
    import sounddevice as sd

    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] < 1 or "DGM20" not in d["name"]:
            continue
        if "WASAPI" in sd.query_hostapis(d["hostapi"])["name"]:
            return i
    return None


def busca_wdmks() -> int | None:
    import sounddevice as sd

    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] < 1 or "DGM20" not in d["name"]:
            continue
        if "WDM-KS" in sd.query_hostapis(d["hostapi"])["name"]:
            return i
    return None


def main() -> None:
    from faster_whisper import WhisperModel

    print("=" * 72)
    print(" WASAPI (con efectos de Windows)  vs  WDM-KS (sin efectos)")
    print("=" * 72)
    print(f"Frase: {FRASE!r}")
    print("Vas a decirla dos veces, con voz normal. Solo cambia la ruta interna.")

    wasapi = busca_wasapi()
    wdmks = busca_wdmks()
    if wasapi is None or wdmks is None:
        print(f"No encontré el DGM20 en las dos rutas (WASAPI={wasapi}, WDM-KS={wdmks}).")
        return

    print("\nCargando Whisper large-v3...")
    try:
        modelo = WhisperModel("large-v3", device="cuda", compute_type="float16")
    except Exception as e:
        print(f"  ({type(e).__name__}) uso CPU")
        modelo = WhisperModel("small", device="cpu", compute_type="int8", cpu_threads=8)

    def transcribir(audio16k):
        audio16k = audio16k / (np.max(np.abs(audio16k)) or 1.0) * 0.9
        seg, _ = modelo.transcribe(audio16k.astype(np.float32), language="es",
                                   beam_size=5, vad_filter=False,
                                   condition_on_previous_text=False)
        return " ".join(s.text.strip() for s in seg)

    resultados = {}
    for nombre, dispositivo, canales in (("WASAPI", wasapi, 1), ("WDM-KS", wdmks, 2)):
        print(f"\n--- {nombre} (dispositivo {dispositivo}, {canales} canal/es) ---")
        print(f"    Di: {FRASE!r}")
        for s in (3, 2, 1):
            print(f"      ... {s}")
            time.sleep(1)
        print("      ¡HABLA AHORA!")

        pcm = grabar_callback(dispositivo, canales)
        if pcm is None:
            print("    sin datos")
            continue
        sf.write(f"ruta_{nombre.lower().replace('-', '')}.wav", pcm, FS_CAPTURA)

        x48 = pcm.astype(np.float64) / 32768
        per48, voz48 = periodicidad(x48, FS_CAPTURA)

        x16 = remuestrear(x48, FS_CAPTURA)
        rep = bands(x16)
        texto = transcribir(x16)

        print(f"    RMS={rms(pcm):7.1f} | pico={int(np.max(np.abs(pcm)))} "
              f"| periodicidad={per48:.3f} | voz clara={voz48:.0f}%")
        print("    " + " | ".join(f"{k}={v:5.1f}%" for k, v in rep.items()))
        print(f"    Whisper -> {texto!r}")
        resultados[nombre] = (per48, voz48, rep, texto)

    print("\n" + "=" * 72)
    print(" VEREDICTO")
    print("=" * 72)
    if len(resultados) < 2:
        print("  Faltan mediciones.")
        return

    p_w, v_w, _, t_w = resultados["WASAPI"]
    p_k, v_k, _, t_k = resultados["WDM-KS"]
    print(f"  WASAPI : periodicidad={p_w:.3f} voz clara={v_w:.0f}%  -> {t_w!r}")
    print(f"  WDM-KS : periodicidad={p_k:.3f} voz clara={v_k:.0f}%  -> {t_k!r}")
    print()

    if p_k > p_w + 0.08 and "entiend" in t_k.lower() and "entiend" not in t_w.lower():
        print("  ✅ CONFIRMADO: el procesado de audio de Windows está destruyendo")
        print("     la voz. Nahimic / Intel SST / mejoras de audio.")
        print("     Solución inmediata: capturar por WDM-KS.")
        print("     Solución definitiva: desactivar Nahimic y las mejoras.")
    elif p_k > p_w + 0.08:
        print("  ⚠️  WDM-KS suena mejor pero Whisper aún no acierta.")
        print("     El procesado influye, pero no es la única causa.")
    else:
        print("  ➖ Las dos rutas dan resultados parecidos.")
        print("     Entonces NO es el procesado de Windows: es el dispositivo,")
        print("     su colocación o la producción de voz.")
