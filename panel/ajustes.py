"""
Ajustes del panel: qué se puede cambiar, cómo se aplica y cómo se prueba.

Por qué existe
--------------
`core/config.py` sabe validar y guardar, pero es ciego a la interfaz: no sabe
que `tono` se pinta como un slider de −50 a +50 Hz, ni que `microfono` conviene
elegirlo de una lista de dispositivos, ni que cambiar `idioma` en caliente no
sirve porque el cerebro y el oído se fijan al arrancar el motor.

Ese conocimiento es de la interfaz y vive aquí, junto a las tres operaciones
que el panel necesita:

- `descripcion_ajustes()`: valores actuales, valores de fábrica y esquema.
- `aplicar_ajustes()` / `restaurar_ajustes()`: validar → guardar → activar.
- `probar_voz()`: oír el resultado sin guardar nada.

Reglas que se respetan
----------------------
1. **Nada se aplica en silencio.** Un valor inválido no se rechaza a secas: se
   corrige con su aviso para que la interfaz lo muestre (mismo criterio que
   `core/config.py`).
2. **Lo que no puede cambiar en caliente se dice.** El cerebro y el oído
   capturan idioma, modelos y micrófono al arrancar; si alguno cambia, la
   respuesta incluye que hace falta reiniciar el motor.
3. **Probar no guarda.** «Probar voz» sintetiza con los valores del
   formulario, no con los guardados: el tono se elige de oído antes de
   confirmarlo.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from pathlib import Path
from typing import Any

from core import config, perfiles, tts
from core.idiomas import elegir_idioma, tono_activo, voz_activa

try:                        # igual que en tts.py: sin PortAudio no hay listas
    import sounddevice as sd
except Exception:           # pragma: no cover - depende del entorno
    sd = None               # type: ignore[assignment]

URL_OLLAMA = "http://localhost:11434/api/tags"

# La prueba se escribe aparte del archivo del motor: si Niu está hablando por
# partes, cada parte pasa por `voz_temp.mp3` y no deben pisarse.
CARPETA_TEMPORALES = Path(__file__).resolve().parent.parent / "dia_por_dia"
ARCHIVO_PRUEBA = str(CARPETA_TEMPORALES / "voz_prueba.mp3")

FRASES_PRUEBA = {
    "es": "Hola, soy Niu. Así suena mi voz con estos ajustes.",
    "en": "Hi, I'm Niu. This is how my voice sounds with these settings.",
}

VOCES_FRECUENTES = [
    "es-MX-DaliaNeural",
    "es-MX-JorgeNeural",
    "es-ES-ElviraNeural",
    "es-ES-AlvaroNeural",
    "en-US-AriaNeural",
    "en-US-JennyNeural",
    "en-US-GuyNeural",
    "en-GB-SoniaNeural",
]

MODELOS_WHISPER = [
    "large-v3-turbo",
    "large-v3",
    "medium",
    "small",
    "base",
]

# Campos que el motor captura al arrancar (cerebro, oído y micrófono) y que no
# se pueden cambiar mientras conversa. Todo lo demás se lee al usarlo. La lista
# vive en `core/config.py` porque también la usa el cambio de perfil.
REQUIEREN_REINICIO = config.CAMPOS_FRIOS


class MotorOcupado(Exception):
    """Niu está pensando o hablando: la prueba de voz esperaría su turno."""


# ─── Esquema de campos ─────────────────────────────────────────────────

# `tipo` le dice a la interfaz qué control pintar; `fuente` (en los de texto)
# de dónde salen las sugerencias del datalist. El orden de la lista es el orden
# de pintado.
CAMPOS: list[dict[str, Any]] = [
    {
        "campo": "idioma", "etiqueta": "Idioma", "tipo": "seleccion",
        "seccion": "voz", "en_caliente": False,
        "opciones": [{"valor": "es", "texto": "Español"},
                     {"valor": "en", "texto": "English"}],
        "nota": "Cambia voz, reglas de estilo y oído a la vez. Se aplica al reiniciar.",
    },
    {
        "campo": "voz", "etiqueta": "Voz", "tipo": "texto",
        "seccion": "voz", "en_caliente": True, "fuente": "voces",
        "sugerencias": VOCES_FRECUENTES,
        "nota": "Vacío usa la voz del idioma. Se oye en la frase siguiente.",
    },
    {
        "campo": "tono", "etiqueta": "Tono", "tipo": "hz",
        "seccion": "voz", "en_caliente": True,
        "minimo": -50, "maximo": 50, "paso": 5,
        "nota": "Afecta a la frase siguiente, sin reiniciar nada.",
    },
    {
        "campo": "velocidad", "etiqueta": "Velocidad", "tipo": "porcentaje",
        "seccion": "voz", "en_caliente": True,
        "minimo": -20, "maximo": 20, "paso": 2,
        "nota": "Ritmo de habla. Afecta a la frase siguiente.",
    },
    {
        "campo": "microfono", "etiqueta": "Micrófono", "tipo": "texto",
        "seccion": "audio", "en_caliente": False, "fuente": "entrada",
        "nota": "Basta una parte del nombre. Se aplica al reiniciar el motor.",
    },
    {
        "campo": "salida", "etiqueta": "Salida", "tipo": "texto",
        "seccion": "audio", "en_caliente": True, "fuente": "salida",
        "nota": "Vacío usa el dispositivo predeterminado de Windows.",
    },
    {
        "campo": "modelo_llm", "etiqueta": "Modelo LLM", "tipo": "texto",
        "seccion": "modelos", "en_caliente": False, "fuente": "llm",
        "nota": "Los modelos instalados en Ollama. Se aplica al reiniciar.",
    },
    {
        "campo": "motor_stt", "etiqueta": "Motor STT", "tipo": "seleccion",
        "seccion": "modelos", "en_caliente": False,
        "opciones": [{"valor": "whisper", "texto": "Whisper (local)"},
                     {"valor": "gemini", "texto": "Gemini (nube)"}],
        "nota": "Gemini necesita la clave configurada en .env. Se aplica al reiniciar.",
    },
    {
        "campo": "modelo_whisper", "etiqueta": "Modelo Whisper", "tipo": "seleccion",
        "seccion": "modelos", "en_caliente": False,
        "opciones": [{"valor": m, "texto": m} for m in MODELOS_WHISPER],
        "nota": "Más grande = más preciso y más VRAM (quedan ~350 MB libres). Se aplica al reiniciar.",
    },
    {
        "campo": "silencio_final", "etiqueta": "Silencio final", "tipo": "numero",
        "seccion": "conversacion", "en_caliente": True,
        # Mismo rango que `_RANGOS` en core/config.py: si la interfaz ofreciera
        # menos, el formulario no podría ni mostrar un valor guardado a mano.
        "minimo": 0.2, "maximo": 3.0, "paso": 0.05, "unidad": "s",
        "nota": "Cuánto silencio cierra tu turno. Bájalo si te corta antes de tiempo.",
    },
    {
        "campo": "tts_timeout", "etiqueta": "Tope del TTS", "tipo": "numero",
        "seccion": "avanzado", "en_caliente": True,
        "minimo": 1, "maximo": 120, "paso": 1, "unidad": "s",
        "nota": "Segundos antes de rendirse con una frase.",
    },
    {
        "campo": "tts_intentos", "etiqueta": "Reintentos del TTS", "tipo": "numero",
        "seccion": "avanzado", "en_caliente": True,
        "minimo": 1, "maximo": 5, "paso": 1, "unidad": "",
        "nota": "Intentos por frase ante un servicio lento.",
    },
    {
        "campo": "temperatura", "etiqueta": "Temperatura del LLM", "tipo": "numero",
        "seccion": "avanzado", "en_caliente": True,
        "minimo": 0, "maximo": 2, "paso": 0.05, "unidad": "",
        "nota": "0 = repetitivo, 2 = caótico. Se aplica en el siguiente turno.",
    },
]

SECCIONES = {
    "voz": "Voz",
    "audio": "Audio",
    "modelos": "Modelos",
    "conversacion": "Conversación",
    "avanzado": "Avanzados",
}


# ─── Operaciones ───────────────────────────────────────────────────────

def descripcion_ajustes() -> dict[str, Any]:
    """Lo que la interfaz necesita para pintar el formulario completo."""
    return {
        "valores": asdict(config.ajustes()),
        "defecto": asdict(config.por_defecto()),
        "campos": CAMPOS,
        "secciones": SECCIONES,
    }


def _respuesta(antes: Any, nuevos: Any, avisos: list[str]) -> dict[str, Any]:
    """Valores finales, avisos y qué quedó pendiente de un reinicio."""
    reinicio = sorted(
        campo for campo in REQUIEREN_REINICIO
        if getattr(antes, campo) != getattr(nuevos, campo)
    )
    return {
        "valores": asdict(nuevos),
        "avisos": avisos,
        "requiere_reinicio": reinicio,
    }


def aplicar_ajustes(cambios: dict[str, Any]) -> dict[str, Any]:
    """Valida, guarda en disco y activa los cambios, avisando de lo que falte.

    Se usa `normalizar` y no `con_cambios` a propósito: la interfaz necesita
    los avisos como datos para mostrarlos, no impresos en la consola.
    """
    antes = config.ajustes()
    datos = asdict(antes)
    datos.update(cambios)

    nuevos, avisos = config.normalizar(datos)
    config.guardar_ajustes(nuevos)
    config.fijar_ajustes(nuevos)
    # El perfil activo guarda su propia copia: si se cambiara de perfil y se
    # volviera, estos valores tienen que seguir aquí.
    perfiles.sincronizar_ajustes(nuevos)
    return _respuesta(antes, nuevos, avisos)


def restaurar_ajustes() -> dict[str, Any]:
    """Vuelve a los valores de fábrica, en memoria y en disco."""
    antes = config.ajustes()
    nuevos = config.restablecer()
    perfiles.sincronizar_ajustes(nuevos)
    return _respuesta(antes, nuevos, [])


# ─── Prueba de voz ─────────────────────────────────────────────────────

async def probar_voz(
    motor: Any,
    *,
    voz: str | None = None,
    tono: str | None = None,
    velocidad: str | None = None,
    idioma: str | None = None,
) -> dict[str, Any]:
    """Sintetiza y reproduce una frase fija con los valores indicados.

    No guarda nada: sirve para elegir de oído antes de confirmar. Si Niu está
    pensando o hablando se rechaza, porque el audio de la prueba pelearía con
    el suyo por el mismo stream de sonido.

    `idioma` también puede venir del formulario: si se elige inglés y se prueba
    antes de guardar, la frase de prueba debe ser la inglesa.
    """
    if motor.estado in ("pensando", "hablando"):
        raise MotorOcupado("Niu está hablando: espera a que termine.")

    codigo = (idioma or config.ajustes().idioma)[:2]
    frase = FRASES_PRUEBA.get(codigo, FRASES_PRUEBA["es"])

    # Si el formulario cambia de idioma y la voz está vacía («la del perfil»),
    # la prueba debe usar la voz del perfil **del formulario**, no la guardada.
    perfil = elegir_idioma(codigo) if idioma else None
    voz = voz or (perfil.voz if perfil else None)
    tono = tono or (perfil.tono if perfil else None)
    generado = await tts.sintetizar_voz_async(
        frase, ARCHIVO_PRUEBA, voz=voz, tono=tono, velocidad=velocidad
    )
    if not generado:
        return {
            "ok": False,
            "detalle": "No se pudo generar el audio. Revisa la conexión con "
                       "el servicio de voz.",
        }

    audio = await asyncio.to_thread(tts.preparar_audio, ARCHIVO_PRUEBA)
    if audio is None:
        return {"ok": False, "detalle": "No se pudo preparar el audio de prueba."}

    # Una prueba anterior podría seguir sonando.
    tts.detener_reproduccion()
    await asyncio.to_thread(tts.reproducir_audio, audio)

    return {
        "ok": True,
        "duracion": audio.duracion,
        "voz": voz or voz_activa(),
        "tono": tono or tono_activo(),
        "velocidad": velocidad or config.ajustes().velocidad,
    }


# ─── Listas para los selectores ────────────────────────────────────────

async def listar_dispositivos() -> dict[str, Any]:
    """Dispositivos de entrada y salida, por nombre y host API.

    Los índices cambian al reconectar el USB, así que al ajuste se le guarda
    el **nombre** (aunque sea parcial) y nunca el número.
    """
    if sd is None:
        return {"entrada": [], "salida": [],
                "error": "sounddevice no está disponible"}

    def _listar() -> dict[str, Any]:
        try:
            todos = sd.query_devices()
            hostapis = sd.query_hostapis()
        except Exception as e:
            return {"entrada": [], "salida": [],
                    "error": f"{type(e).__name__}: {e}"}

        def nombre_host(indice: int) -> str:
            try:
                return str(hostapis[indice]["name"])
            except (IndexError, KeyError, TypeError):
                return "?"

        entrada, salida = [], []
        for indice, d in enumerate(todos):
            fila = {
                "id": indice,
                "nombre": str(d["name"]).strip(),
                "host_api": nombre_host(d["hostapi"]),
            }
            if d["max_input_channels"] > 0:
                entrada.append(fila)
            if d["max_output_channels"] > 0:
                salida.append(fila)
        return {"entrada": entrada, "salida": salida}

    # `query_devices` consulta el host de audio: mejor fuera del bucle.
    return await asyncio.to_thread(_listar)


async def listar_modelos(cliente: Any) -> dict[str, Any]:
    """Modelos instalados en Ollama (`ollama list` vía /api/tags)."""
    try:
        respuesta = await cliente.get(URL_OLLAMA, timeout=2.0)
        respuesta.raise_for_status()
        modelos = respuesta.json().get("models", [])
    except Exception as e:
        return {"llm": [], "error": f"{type(e).__name__}: {e}"}
    return {"llm": [m.get("name", "") for m in modelos if m.get("name")]}
