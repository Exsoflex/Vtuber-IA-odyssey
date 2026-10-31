"""
Tests del recorte de silencio.

Edge-TTS rellena cada frase con silencio (medido: ~0,85 s al final). En una
respuesta entera no molesta, pero al hablar por partes cada trozo arrastra su
propio relleno y las pausas se suman. Si el recorte se pasa, el habla suena
atropellada; si no recorta nada, vuelven las pausas. Por eso tiene márgenes
concretos y merece tests.

Ejecutar:
    .venv\\Scripts\\python.exe -m pytest tests -q
"""

import numpy as np

from core.tts import MARGEN_FINAL, MARGEN_INICIO, recortar_silencio

FS = 48000


def tono(segundos: float, amplitud: float = 0.5) -> np.ndarray:
    """Tono senoidal a 220 Hz (lo que importa es que no sea silencio)."""
    t = np.arange(int(FS * segundos)) / FS
    return (amplitud * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def silencio(segundos: float) -> np.ndarray:
    return np.zeros(int(FS * segundos), dtype=np.float32)


# ─── Lo básico ─────────────────────────────────────────────────────────


def test_recorta_el_silencio_de_los_extremos():
    audio = np.concatenate([silencio(1.0), tono(0.5), silencio(1.0)])
    recortado = recortar_silencio(audio, FS)

    esperado = 0.5 + MARGEN_INICIO + MARGEN_FINAL
    assert abs(len(recortado) / FS - esperado) < 0.05
    # El original dura 2,5 s; recortar debe quitar casi todo el relleno.
    assert len(recortado) / FS < 1.0


def test_conserva_los_margenes():
    """No se recorta a cero: un poco de aire evita que suene cortado."""
    audio = np.concatenate([silencio(1.0), tono(0.5), silencio(1.0)])
    recortado = recortar_silencio(audio, FS)

    assert MARGEN_INICIO > 0
    assert MARGEN_FINAL > MARGEN_INICIO      # al final se deja más aire
    # El tono sigue completo en medio.
    assert np.max(np.abs(recortado)) > 0.4


def test_no_alarga_ni_recorta_si_no_hay_silencio():
    audio = tono(0.5)
    assert len(recortar_silencio(audio, FS)) == len(audio)


def test_todo_silencio_se_devuelve_intacto():
    """Devolver un array vacío rompería la reproducción."""
    audio = silencio(1.0)
    assert np.array_equal(recortar_silencio(audio, FS), audio)


def test_audio_mas_corto_que_una_ventana():
    audio = tono(0.01)       # menos de 25 ms
    assert len(recortar_silencio(audio, FS)) == len(audio)


# ─── El umbral es relativo, no absoluto ────────────────────────────────


def test_funciona_con_audio_muy_bajo():
    """Si el umbral fuera absoluto, una grabación floja no se recortaría."""
    audio = np.concatenate([silencio(1.0), tono(0.5, amplitud=0.001), silencio(1.0)])
    recortado = recortar_silencio(audio, FS)
    assert abs(len(recortado) / FS - (0.5 + MARGEN_INICIO + MARGEN_FINAL)) < 0.05


def test_funciona_a_otra_frecuencia_de_muestreo():
    """Las ventanas son en segundos, no en muestras: 16 kHz debe dar lo mismo."""
    fs = 16000
    t = np.arange(int(fs * 0.5)) / fs
    audio = np.concatenate([
        np.zeros(int(fs * 1.0), dtype=np.float32),
        (0.5 * np.sin(2 * np.pi * 220 * t)).astype(np.float32),
        np.zeros(int(fs * 1.0), dtype=np.float32),
    ])
    recortado = recortar_silencio(audio, fs)
    assert abs(len(recortado) / fs - (0.5 + MARGEN_INICIO + MARGEN_FINAL)) < 0.05
