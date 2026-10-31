"""
Tests de la cancelación de la grabación.

Por qué esto merece tests: cuando el usuario escribe en el chat, el motor puede
estar esperando al micrófono hasta 8 s. La señal de cancelación debe cortar esa
espera sin dejar el dispositivo abierto ni el bucle bloqueado. Es un
comportamiento invisible: si falla, todo sigue funcionando, solo que el mensaje
escrito tarda en atenderse.

Se sustituye `sounddevice` por un micrófono falso: los tests no abren audio.

Ejecutar:
    .venv\\Scripts\\python.exe -m pytest tests -q
"""

import threading

import numpy as np

from core import stt


class MicrofonoFalso:
    """Entrega bloques: 1 s de silencio, medio segundo de voz y silencio."""

    def __init__(self, al_leer=None) -> None:
        self.lecturas = 0
        self.al_leer = al_leer

    def read(self, tamano: int):
        self.lecturas += 1
        if self.al_leer is not None:
            self.al_leer(self.lecturas)
        valor = 3000 if 11 <= self.lecturas <= 15 else 0
        return np.full((tamano, 1), valor, dtype=np.int16), False

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False


def preparar_micro(monkeypatch, flujo: MicrofonoFalso) -> None:
    monkeypatch.setattr(
        stt.sd, "query_devices",
        lambda dispositivo=None, kind=None: {
            "default_samplerate": 16000, "max_input_channels": 1,
        },
    )
    monkeypatch.setattr(stt.sd, "InputStream", lambda *a, **k: flujo)


def test_una_cancelacion_ya_activa_no_abre_el_microfono(monkeypatch):
    def no_tocar(*args, **kwargs):
        raise AssertionError("no debía abrir el dispositivo")

    monkeypatch.setattr(stt.sd, "query_devices", no_tocar)
    evento = threading.Event()
    evento.set()

    assert stt.grabar_hasta_silencio(dispositivo=0, cancelar=evento) is None


def test_cancelar_a_mitad_de_la_grabacion_devuelve_none(monkeypatch):
    evento = threading.Event()
    flujo = MicrofonoFalso(al_leer=lambda n: evento.set() if n >= 12 else None)
    preparar_micro(monkeypatch, flujo)

    assert stt.grabar_hasta_silencio(
        dispositivo=0,
        timeout_inicio=1.0,
        duracion_maxima=10.0,
        cancelar=evento,
    ) is None

    # Cortó pronto: no agotó los 10 s de grabación (100 bloques de 100 ms).
    assert flujo.lecturas < 20


def test_sin_cancelacion_la_grabacion_termina_por_silencio(monkeypatch):
    flujo = MicrofonoFalso()
    preparar_micro(monkeypatch, flujo)

    audio = stt.grabar_hasta_silencio(
        dispositivo=0, timeout_inicio=1.0, silencio_final=0.3, duracion_maxima=10.0
    )

    assert audio is not None
    assert flujo.lecturas < 20
    # 16 kHz, 16 bits: dos bytes por muestra.
    assert len(audio) % 2 == 0
