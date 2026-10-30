"""
Tests de la envolvente del lip sync.

`envolvente()` es la función que decide cuánto se abre la boca en cada instante.
No toca red ni audio ni VTS: entra un array y sale una lista de números. Eso la
hace ideal para probarla, y también la convierte en el punto donde un cambio
"inocente" (otra ventana, otro umbral) rompe el resultado sin dar ningún error.

Ejecutar:
    .venv\\Scripts\\python.exe -m pytest tests -q
"""

import numpy as np
import pytest

from core.lipsync import envolvente

FS = 48000


def onda(segundos: float, amplitud: float = 0.6, frecuencia: float = 220.0) -> np.ndarray:
    """Genera un tono senoidal (o silencio si la amplitud es 0)."""
    t = np.arange(int(FS * segundos)) / FS
    return (amplitud * np.sin(2 * np.pi * frecuencia * t)).astype(np.float32)


def silencio(segundos: float) -> np.ndarray:
    return np.zeros(int(FS * segundos), dtype=np.float32)


# ─── Forma de la salida ────────────────────────────────────────────────


def test_cantidad_de_frames():
    """A 40 fps, 1 segundo debe dar 40 valores."""
    assert len(envolvente(onda(1.0), FS, fps=40)) == 40


def test_audio_mas_corto_que_una_ventana():
    """Con menos muestras que una ventana no hay nada que medir."""
    assert envolvente(np.zeros(10, dtype=np.float32), FS, fps=40) == []


def test_valores_dentro_de_rango():
    """La salida nunca se sale de [0, 1]: es lo que espera el parámetro."""
    boca = envolvente(onda(1.0, amplitud=1.0), FS)
    assert all(0.0 <= v <= 1.0 for v in boca)


# ─── Comportamiento con el volumen ─────────────────────────────────────


def test_silencio_cierra_la_boca():
    assert max(envolvente(silencio(1.0), FS)) == 0.0


def test_tono_fuerte_abre_la_boca():
    assert max(envolvente(onda(1.0), FS)) > 0.9


def test_mas_volumen_mas_apertura():
    """Un tono más fuerte debe abrir más la boca que uno más flojo."""
    flojo = max(envolvente(onda(1.0, amplitud=0.05), FS))
    fuerte = max(envolvente(onda(1.0, amplitud=0.5), FS))
    assert fuerte > flojo


def test_tono_y_silencio():
    """Alterna tono/silencio: la boca sigue el patrón."""
    audio = np.concatenate([onda(1.0), silencio(1.0)])
    boca = np.array(envolvente(audio, FS))

    mitad = len(boca) // 2
    assert boca[:mitad].max() > 0.9          # durante el tono, abierta
    assert boca[-10:].max() < 0.02           # al final del silencio, cerrada


# ─── Suavizado ─────────────────────────────────────────────────────────


def test_ataque_mas_rapido_que_liberacion():
    """La boca debe abrirse antes de lo que tarda en cerrarse.

    Es lo que hace que parezca una boca y no un vúmetro: al empezar a hablar
    abre casi de golpe, y al callar se cierra progresivamente.
    """
    audio = np.concatenate([onda(1.0), silencio(1.0)])
    boca = np.array(envolvente(audio, FS))

    mitad = len(boca) // 2
    frames_en_abrir = int(np.argmax(boca[:mitad] > 0.8)) if boca[:mitad].max() > 0.8 else 0
    frames_en_cerrar = int(np.argmax(boca[mitad:] < 0.2)) if boca[mitad:].min() < 0.2 else 999

    assert frames_en_abrir < frames_en_cerrar


def test_el_suavizado_evita_saltos_bruscos():
    """Ningún frame debe saltar de 0 a 1 de golpe (sería un parpadeo)."""
    boca = envolvente(onda(1.0), FS)
    saltos = np.abs(np.diff(boca))
    assert saltos.max() <= 0.7


# ─── Entradas raras ────────────────────────────────────────────────────


def test_audio_estereo_se_mezcla():
    """Si llega estéreo, se promedia: la boca se mide sobre la mezcla."""
    mono = onda(1.0)
    estereo = np.column_stack([mono, mono])
    assert envolvente(estereo, FS) == envolvente(mono, FS)


def test_umbrales_configurables():
    """Los umbrales en dB se pueden mover sin tocar el resto."""
    audio = onda(1.0, amplitud=0.01)   # unos -40 dBFS

    # Con umbrales muy bajos, ese tono flojo satura la boca.
    assert max(envolvente(audio, FS, suelo_db=-90, techo_db=-50)) == 1.0
    # Con umbrales altos, queda por debajo del suelo y la boca no abre.
    assert max(envolvente(audio, FS, suelo_db=-30, techo_db=-10)) == 0.0


@pytest.mark.parametrize("fps", [20, 25, 30, 40, 60])
def test_cualquier_fps_da_la_cantidad_correcta(fps: int):
    assert len(envolvente(onda(1.0), FS, fps=fps)) == fps
