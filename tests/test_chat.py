"""
Tests del historial del chat: mensajes, turnos, archivo y exportación.

Por qué esto merece tests: el chat es lo único que queda de una conversación
cuando cierras el panel. Si un turno se cierra mal, el archivo guarda una
respuesta a medias; si los fragmentos no se pegan al globo correcto, el texto
sale desordenado. Nada de eso lanza una excepción: se ve al releer la sesión.

No hace falta servidor ni navegador: `Historial` es una clase normal y recibe
los mismos eventos que emite `MotorNiu`.

Ejecutar:
    .venv\\Scripts\\python.exe -m pytest tests -q
"""

import asyncio
import json

import pytest

from panel.chat import Historial, resumen_metricas

TIEMPOS = {
    "stt": 0.40,
    "texto": 0.55,
    "sintesis": 0.30,
    "preparacion": 0.03,
    "voz": 2.00,
    "partes": 2,
    "generando": 1.10,
}


@pytest.fixture
def historial(tmp_path):
    return Historial(carpeta=tmp_path, metadatos={"idioma": "en", "voz": "en-US-AriaNeural"})


def eventos(cola: asyncio.Queue) -> list[dict]:
    """Vacía la cola de un suscriptor sin esperar."""
    salida = []
    while not cola.empty():
        salida.append(cola.get_nowait())
    return salida


def turno(historial: Historial, numero: int, texto: str = "Hola.") -> None:
    """Simula un turno completo, en el mismo orden que el motor."""
    historial.procesar("respuesta_inicio", {"texto_usuario": "hola", "turno": numero})
    historial.procesar("fragmento", {"texto": texto[:2], "turno": numero})
    historial.procesar("fragmento", {"texto": texto[2:], "turno": numero})
    historial.procesar("respuesta", {"texto": texto, "turno": numero})
    historial.procesar("metricas", {"tiempos": dict(TIEMPOS), "turno": numero})


# ─── El mensaje de Niu ─────────────────────────────────────────────────


def test_un_turno_completo_guarda_texto_y_metricas(historial):
    turno(historial, 1)

    assert len(historial.mensajes) == 1
    mensaje = historial.mensajes[0]
    assert mensaje["papel"] == "niu"
    assert mensaje["texto"] == "Hola."
    assert mensaje["parcial"] is False
    assert mensaje["metricas"]["voz"] == 2.00


def test_los_fragmentos_van_actualizando_el_mismo_globo(historial):
    cola = historial.suscribir()

    historial.procesar("respuesta_inicio", {"texto_usuario": "hola", "turno": 1})
    historial.procesar("fragmento", {"texto": "Ho", "turno": 1})
    historial.procesar("fragmento", {"texto": "la.", "turno": 1})

    # Un solo globo, aunque hayan llegado dos trozos.
    assert len(historial.mensajes) == 1
    publicados = [e["mensaje"] for e in eventos(cola) if e["tipo"] == "mensaje"]
    assert publicados[-1]["texto"] == "Hola."
    assert publicados[-1]["parcial"] is True


def test_el_archivo_se_escribe_al_cerrar_el_turno(historial, tmp_path):
    turno(historial, 1)

    ruta = tmp_path / historial.ruta.name
    assert ruta.exists()

    datos = json.loads(ruta.read_text(encoding="utf-8"))
    assert datos["idioma"] == "en"
    assert datos["voz"] == "en-US-AriaNeural"
    assert [m["texto"] for m in datos["mensajes"]] == ["Hola."]


def test_las_metricas_van_al_turno_que_les_toca(historial):
    turno(historial, 1, "Uno.")
    turno(historial, 2, "Dos.")
    historial.procesar(
        "metricas", {"tiempos": {**TIEMPOS, "voz": 9.0}, "turno": 2}
    )

    assert historial.mensajes[0]["metricas"]["voz"] == 2.00
    assert historial.mensajes[1]["metricas"]["voz"] == 9.00


# ─── Turnos cortados ───────────────────────────────────────────────────


def test_cancelar_con_texto_deja_el_globo_marcado_interrumpido(historial):
    historial.procesar("respuesta_inicio", {"texto_usuario": "hola", "turno": 1})
    historial.procesar("fragmento", {"texto": "Esto es", "turno": 1})
    historial.procesar("respuesta_cancelada", {"turno": 1})

    mensaje = historial.mensajes[-1]
    assert mensaje["texto"] == "Esto es"
    assert mensaje["parcial"] is False
    assert mensaje["interrumpida"] is True


def test_cancelar_sin_texto_quita_el_globo_vacio(historial):
    cola = historial.suscribir()

    historial.procesar("respuesta_inicio", {"texto_usuario": "hola", "turno": 1})
    historial.procesar("respuesta_cancelada", {"turno": 1})

    assert historial.mensajes == []
    assert eventos(cola)[-1] == {"tipo": "quitar", "id": 1}


def test_cancelar_un_turno_que_no_es_el_abierto_no_toca_nada(historial):
    historial.procesar("respuesta_inicio", {"texto_usuario": "hola", "turno": 2})
    historial.procesar("fragmento", {"texto": "sigo", "turno": 2})

    historial.procesar("respuesta_cancelada", {"turno": 1})

    assert historial.mensajes[-1]["texto"] == "sigo"
    assert historial.mensajes[-1]["parcial"] is True


def test_un_turno_nuevo_cierra_el_anterior_si_quedo_abierto(historial):
    historial.procesar("respuesta_inicio", {"texto_usuario": "uno", "turno": 1})
    historial.procesar("fragmento", {"texto": "corte", "turno": 1})
    historial.procesar("respuesta_inicio", {"texto_usuario": "dos", "turno": 2})

    assert historial.mensajes[0]["interrumpida"] is True
    assert historial.mensajes[0]["parcial"] is False
    assert historial.mensajes[1]["parcial"] is True


# ─── Usuario y sistema ─────────────────────────────────────────────────


def test_la_transcripcion_del_micro_se_convierte_en_mensaje_del_usuario(historial):
    historial.procesar("transcripcion", {"texto": "  hola  ", "ms": 420})

    mensaje = historial.mensajes[-1]
    assert mensaje["papel"] == "usuario"
    assert mensaje["texto"] == "hola"


def test_un_mensaje_vacio_no_ensucia_el_chat(historial):
    assert historial.agregar_usuario("   ") is None
    assert historial.agregar_sistema("") is None
    assert historial.mensajes == []


def test_los_avisos_del_motor_aparecen_como_sistema(historial):
    historial.procesar("error", {"mensaje": "Ollama no contesta"})
    historial.procesar("sistema", {"mensaje": "Voz detenida."})

    assert [m["papel"] for m in historial.mensajes] == ["sistema", "sistema"]
    assert historial.mensajes[0]["texto"] == "Ollama no contesta"


def test_el_historial_al_conectar_trae_todo_lo_guardado(historial):
    historial.agregar_usuario("hola")
    turno(historial, 1)

    datos = historial.snapshot()

    assert datos["tipo"] == "historial"
    assert datos["archivo"].endswith(".json")
    assert [m["papel"] for m in datos["mensajes"]] == ["usuario", "niu"]


# ─── Sesiones y exportación ────────────────────────────────────────────


def test_limpiar_empieza_una_sesion_nueva_sin_borrar_la_anterior(historial):
    historial.agregar_usuario("hola")
    ruta_vieja = historial.ruta

    historial.limpiar()

    assert historial.mensajes == []
    assert historial.ruta != ruta_vieja
    assert ruta_vieja.exists()
    assert ruta_vieja.read_text(encoding="utf-8")


def test_exportar_markdown_incluye_los_dos_lados_y_las_metricas(historial):
    historial.agregar_usuario("hola")
    turno(historial, 1)

    markdown = historial.exportar_markdown()

    assert "### Tú" in markdown
    assert "### Niu" in markdown
    assert "hola" in markdown
    assert "Hola." in markdown
    assert "1er sonido 1.28 s" in markdown


def test_el_resumen_de_metricas_suma_hasta_el_primer_sonido():
    resumen = resumen_metricas(TIEMPOS)

    assert "1er sonido 1.28 s" in resumen
    assert "2 partes" in resumen
