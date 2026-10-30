"""
¿El retumbe de graves está enterrando la voz?

Hipótesis: las grabaciones tienen una componente muy fuerte por debajo de
100 Hz (retumbe de la habitación, ventilador, mesa). Al normalizar por el
pico, tu voz queda muy por debajo del fondo de escala y los motores de voz
la oyen como un susurro lejano.

Se mide la energía de graves vs la de la voz, y se transcribe:
    a) tal cual
    b) sin los graves (filtro paso alto a 120 Hz)
    c) sin graves ni extremos agudos (120 - 7000 Hz)

Si con el filtro el texto sale coherente, la solución es un filtro de dos
líneas en el camino de captura.
"""

import os

import numpy as np
import soundfile as sf

BASE = r"C:\Users\hecto\OneDrive\Documentos\Vtuber IA odyssey"

_SITEPKG = os.path.dirname(os.path.abspath(sf.__file__))
for _sub in ("cublas", "cudnn", "cuda_nvrtc"):
    _ruta = os.path.join(_SITEPKG, "nvidia", _sub, "bin")
    if os.path.isdir(_ruta):
        os.environ["PATH"] = _ruta + os.pathsep + os.environ.get("PATH", "")

ARCHIVOS = [
    ("voz_normal_bajo", os.path.join(BASE, "voz_normal_bajo.wav")),
    ("voz_cerca", os.path.join(BASE, "voz_cerca.wav")),
    ("diagnostico_mic", os.path.join(BASE, "diagnostico_mic.wav")),
]

FS = 16000


def db(v):
    return 20 * np.log10(max(float(v), 1e-12))


def filtrar(x, fs, corte_inferior=0.0, corte_superior=None):
    """Filtro por FFT: deja pasar solo [corte_inferior, corte_superior]."""
    esp = np.fft.rfft(x)
    frecs = np.fft.rfftfreq(len(x), 1 / fs)
    mascara = frecs >= corte_inferior
    if corte_superior is not None:
        mascara &= frecs <= corte_superior
    return np.fft.irfft(esp * mascara, n=len(x))


def main():
    from faster_whisper import WhisperModel

    print("Cargando Whisper large-v3...")
    try:
        modelo = WhisperModel("large-v3", device="cuda", compute_type="float16")
    except Exception:
        modelo = WhisperModel("large-v3", device="cpu", compute_type="int8", cpu_threads=8)

    def transcribir(y, fs):
        z = y / (np.max(np.abs(y)) or 1.0) * 0.9
        seg, _ = modelo.transcribe(z.astype(np.float32), language="es",
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

        graves = filtrar(x, fs, 0.0, 120.0)
        voz = filtrar(x, fs, 120.0, None)

        print(f"\n{'=' * 74}")
        print(f" {etiqueta}  ({len(x) / fs:.2f} s, {fs} Hz)")
        print(f"{'=' * 74}")
        print(f"  TODO     : pico {db(np.max(np.abs(x))):6.1f} dBFS | RMS {db(np.sqrt(np.mean(x**2))):6.1f}")
        print(f"  <120 Hz  : pico {db(np.max(np.abs(graves))):6.1f} dBFS | RMS {db(np.sqrt(np.mean(graves**2))):6.1f}")
        print(f"  >120 Hz  : pico {db(np.max(np.abs(voz))):6.1f} dBFS | RMS {db(np.sqrt(np.mean(voz**2))):6.1f}")
        # cuánto hay que bajar la voz para que el pico total sea 0 dBFS
        atenuacion = db(np.max(np.abs(x))) - db(np.max(np.abs(voz)))
        print(f"  -> los graves obligan a atenuar la voz {atenuacion:.1f} dB al normalizar")

        variantes = [
            ("tal cual        ", x),
            ("paso alto 120 Hz", filtrar(x, fs, 120.0)),
            ("120-7000 Hz     ", filtrar(x, fs, 120.0, 7000.0)),
            ("paso alto 200 Hz", filtrar(x, fs, 200.0)),
        ]
        for nombre, y in variantes:
            print(f"    {nombre} -> {transcribir(y, fs)!r}")


if __name__ == "__main__":
    main()
