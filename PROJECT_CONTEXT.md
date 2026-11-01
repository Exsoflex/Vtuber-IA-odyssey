# 📄 CONTEXTO DEL PROYECTO: NIU AUTONOMOUS ENGINE

## 🎯 Visión general

**Proyecto:** Niu Autonomous Engine — Motor Cognitivo y Multimodal para VTuber IA  
**Objetivo:** Crear una VTuber autónoma ("Niu") con:

- Razonamiento y memoria persistente.
- Voz expresiva estilo anime.
- Sincronización labial en tiempo real.
- Expresiones emocionales dinámicas.
- Entrada por voz y texto.
- Arquitectura preparada para cambiar de proveedor de LLM sin reescribir el sistema completo.

**Stack base actual:** Python 3.14 | `ollama` (local) | `faster-whisper` (STT local) | `edge-tts` | `websockets` | `sounddevice`

> Nota arquitectónica: Gemini sigue siendo un proveedor posible, pero el cerebro ya no depende de su SDK. La generación de texto pasa por la interfaz `LLMProvider`.
>
> Lo mismo ocurre ahora con el oído: la transcripción pasa por `STTProvider`, con dos adaptadores intercambiables (`faster-whisper` local y Gemini en la nube).

---

## 🏗️ Arquitectura actual

```text
Vtuber IA odyssey/
├── core/
│   ├── __init__.py
│   ├── config.py          # Ajustes tipados: validación, config.json y valores por defecto
│   ├── motor.py           # Bucle de conversación: estados, eventos, iniciar/detener/detener_voz
│   ├── brain.py           # Memoria + personalidad + llamada a LLMProvider
│   ├── llm_provider.py    # Interfaz común (Protocol) + LLMConfig/LLMResponse
│   ├── ollama_adapter.py  # Implementación local vía /api/chat
│   ├── stt.py             # Micrófono (sounddevice) + detección de silencio (VAD)
│   ├── stt_provider.py    # Interfaz común (Protocol) + utilidades de audio
│   ├── stt_whisper.py      # Adaptador local: faster-whisper (GPU/CPU)
│   ├── stt_gemini.py       # Adaptador nube: Gemini (audio → texto)
│   ├── tts.py             # Voz: Edge-TTS → MP3 → dispositivo de salida (y recorte de silencio)
│   ├── frases.py          # Corta el texto en frases mientras llega (streaming)
│   ├── idiomas.py         # Perfiles de idioma: voz, código y reglas de estilo
│   ├── lipsync.py         # Boca: audio → envolvente → parámetro de VTS
│   ├── audio_devices.py   # Búsqueda de dispositivos por nombre y host API
│   └── vts_client.py      # VTube Studio: WebSocket + auth + parámetros
├── main.py                # Cliente de consola: suscribe a los eventos del motor y los imprime
├── panel/                 # Panel de control local (FastAPI en 127.0.0.1)
│   ├── app.py             # API: motor, chips, chat, ajustes y WebSocket `/ws`
│   ├── chat.py            # Historial: eventos del motor → mensajes → sesiones/*.json
│   ├── ajustes.py         # Esquema del formulario, guardado validado y «probar voz»
│   ├── __main__.py        # `python -m panel` → uvicorn en 127.0.0.1:8000
│   └── static/            # Interfaz: HTML + CSS del tema espacial + JS de sondeo, chat y ajustes
├── probar_entrada_voz.py  # Prueba de extremo a extremo del oído (captura + STT)
├── probar_lipsync.py      # Prueba de extremo a extremo de la boca
├── tests/                 # pytest: lógica que puede romperse en silencio
├── requirements.txt
├── .env                   # GOOGLE_API_KEY, OLLAMA_MODEL, NIU_STT (no versionado)
├── config.json            # Ajustes editables desde el panel (no versionado)
├── sesiones/              # Chat guardado por el panel: un JSON por arranque (no versionado)
├── vts_token.txt          # Token VTS persistente (no versionado)
├── test_audio.py          # Script auxiliar para listar salidas de audio
└── dia_por_dia/           # Historial de aprendizaje
```

### Flujo funcional actual

```text
Usuario: voz (micrófono DGM20), teclado o chat del panel
        ↓
core/motor.py  (MotorNiu: estados + eventos; main.py y el panel son clientes)
        ↓
core/stt.py → PCM 16 kHz (2 canales nativos → mono) → VAD por RMS
        ↓
STTProvider (NIU_STT=whisper | gemini) → texto
        ↓
core/brain.py
        ↓
LLMProvider (por defecto OllamaAdapter → /api/chat, en streaming)
        ↓
core/frases.py  (corta el texto en frases según llega)
        ↓
core/lipsync.py → hablar_por_partes: tres etapas solapadas por colas
        texto → síntesis → reproducción + boca
        ├── core/tts.py → MP3 → recorte de silencio → salida de Windows
        ├── core/idiomas.py decide voz, tono, reglas de estilo y prompt del STT (NIU_IDIOMA)
        └── envolvente (40 Hz) → VTS: NiuMouthOpen → ParamMouthOpenY
```

`MotorNiu` no imprime nada: emite eventos (`transcripcion`, `fragmento`,
`parte`, `metricas`, `estado`, `error`...). `main.py` los traduce a texto de
consola; el panel los convierte en chat (`panel/chat.py`), métricas por turno y
chips de estado. Los eventos de un turno llevan `turno` (número creciente) para
que el panel empareje fragmentos, audio y métricas sin adivinar por orden. La
conversación existe en un solo sitio.

Las tres etapas del final **no van en fila**: mientras una parte suena, la
siguiente se está sintetizando y el cerebro sigue escribiendo la tercera. Por
eso el primer sonido depende de la primera frase (1,95 s medidos) y no de la
respuesta completa.

### Estado funcional documentado

- ✅ Cerebro desacoplado del proveedor mediante `LLMProvider`.
- ✅ Backend local con Ollama (`qwen2.5:7b-instruct-q4_k_m` por defecto).
- ✅ Memoria manual con ventana deslizante.
- ✅ Voz con Edge-TTS reproducida directamente en el dispositivo de salida de Windows (auriculares DGM20 por DirectSound). La variable `NIU_SALIDA` permite forzar otro destino sin tocar código.
- ✅ Lip sync controlado por Niu: la boca se mueve con la envolvente de su propio audio, sin depender del micrófono de VTS. Verificado: 298/298 frames en 7,45 s para 7,46 s de audio, `ParamMouthOpenY` de 0 a 2,30.
- ✅ Parámetro propio `NiuMouthOpen` creado por API; el modelo puede mapearlo a `ParamMouthOpenY`. Mientras no exista ese mapeo, se usa `VoiceVolumePlusMouthOpen` como respaldo y funciona igual.
- ✅ Conexión persistente con VTube Studio.
- ✅ Entrada de voz con `sounddevice` (sin PyAudio) y detección de silencio por RMS.
- ✅ Oído independiente del motor: `STTProvider` con adaptadores `whisper` (local) y `gemini` (nube), elegido con `NIU_STT`.
- ✅ Whisper `large-v3-turbo` en GPU (RTX 4050): **0,45 s** por frase de 8 s (antes 5,94 s con `large-v3` y `beam 5`). Fallback a CPU int8 si no hay GPU. Configurable con `NIU_WHISPER_MODELO` y `NIU_WHISPER_BEAM`.
- ✅ Cronómetro por turno: `core/motor.py` emite `metricas` y `main.py` imprime el tiempo de cada etapa y el total hasta el primer sonido.
- ✅ **Motor separado de la consola** (`core/motor.py`): `MotorNiu.iniciar()`, `detener()` y `detener_voz()`, estados (`apagado`, `iniciando`, `escuchando`, `pensando`, `hablando`) y eventos. `detener_voz()` corta el audio (`sd.stop()`) y cancela solo la tarea del turno; el motor sigue escuchando. `main.py` quedó como cliente de consola.
- ✅ **Panel mínimo** (`panel/`): `python -m panel` levanta FastAPI + uvicorn en `127.0.0.1:8000`. Arranca y para el motor, calla la voz y muestra chips de estado (motor, Ollama, VTube Studio, micrófono, TTS) con la voz activa. La interfaz es HTML/CSS/JS estático: sin build ni `node`. Motor y panel comparten proceso y bucle de `asyncio`; si el arranque falla, el panel sigue vivo y explica el motivo.
- ✅ **Chat en el panel** (`panel/chat.py` + `/ws`): burbujas de usuario y Niu con streaming en vivo (texto al mismo ritmo que suena), métricas por turno, entrada de texto (`enviar_texto()` en el motor, funciona sin micrófono), avisos del motor como notas, y globos de respuestas cortadas marcadas «interrumpida». El chat se guarda en `sesiones/*.json` (un archivo por arranque), se limpia empezando otra sesión y se exporta a Markdown.
- ✅ **Editor de ajustes** (`panel/ajustes.py` + `GET/PUT /api/ajustes`): 10 ajustes esenciales y 3 avanzados plegados, pintados desde un esquema que manda el servidor (añadir un campo es tocar Python, no el JS). Guarda en `config.json` con validación y avisos, «Restaurar» vuelve a fábrica, y «Probar voz» sintetiza con los valores del formulario **sin guardarlos**. Los ajustes que el motor captura al arrancar (`idioma`, `micrófono`, modelos) llevan un chip «reinicia» y la respuesta del guardado dice qué queda pendiente; tono, velocidad, salida, silencio, TTS y temperatura se aplican en la frase o el turno siguiente. Solo se envían los campos que el usuario tocó.
- ✅ **Panel en dos columnas y accesibilidad** (fase 5): motor, estado, voz y ajustes en la columna izquierda; conversación fija (`sticky`) a la derecha. Por debajo de 900 px pasa a una columna con el chat entre el estado y los ajustes. Revisado con las Web Interface Guidelines: enlace para saltar al contenido, foco visible en todos los controles (incluidos los sliders), `aria-live` para la copia y los avisos, `aria-valuetext` en los sliders, `prefers-reduced-motion`, horas y números con `Intl`, y aviso del navegador si hay ajustes sin guardar o un mensaje sin enviar.
- ✅ **Voz por partes (streaming)**: el cerebro escribe, `core/frases.py` corta en frases y cada una se sintetiza mientras la anterior suena. Verificado de punta a punta: **primer sonido 1,95 s** (antes 4,7 s) con 4 partes y la boca cuadrando en todas.
- ✅ **Perfiles de idioma** (`core/idiomas.py`): `NIU_IDIOMA=es|en` elige voz, tono, reglas de estilo y **prompt del STT**. En inglés Niu responde con contracciones y muletillas nativas, sin traducir las españolas, con la voz de Aria en tono normal. La voz y el tono se pueden forzar con `NIU_VOZ` / `NIU_TONO`.
- ✅ **Oído en el idioma del perfil**: `idioma_stt()` devuelve el código del perfil salvo que `NIU_STT_IDIOMA` diga otra cosa. Antes estaba en automático con un prompt en español, y Whisper transcribía el inglés en español.
- ✅ **Sin pausas entre partes**: Edge-TTS mete ~0,85 s de silencio al final de cada frase; se recorta dejando 0,05 s al principio y 0,15 s al final. Las frases de menos de 40 caracteres se acumulan con la siguiente (la primera, no: ahí manda la velocidad).
- ✅ Tope de tiempo en Edge-TTS (15 s, 2 intentos, `NIU_TTS_TIMEOUT` / `NIU_TTS_INTENTOS`): un servicio que deja de contestar ya no cuelga la conversación.
- ✅ 184 tests en `tests/` (`pytest` + `pytest-asyncio`): corte de frases, recorte de silencio, idiomas, envolvente del lip sync, tope de tiempo del TTS, cancelación de la grabación (`test_stt_cancelar.py`), ajustes (`test_config.py`), motor (`test_motor.py`, incluida la entrada de texto), historial del chat (`test_chat.py`), formulario de ajustes (`test_ajustes_panel.py`) y panel (`test_panel.py`, con `TestClient` en memoria).
- ✅ Transcripción verificada de extremo a extremo (3/3 frases correctas con el DGM20).
- ✅ Fallback a teclado cuando no hay micrófono.
- ⚠️ Las expresiones por keyword usan nombres de hotkey que deben coincidir con los del modelo.
- ⚠️ El soporte de imágenes quedó desactivado: el modelo local no es multimodal.
- ⚠️ Gemini ya no está conectado; falta un `GeminiAdapter` si se quiere volver a usar.
- ⚠️ El logging sigue siendo `print`.

---

## 🔌 Próximo cambio arquitectónico: proveedor LLM

Objetivo:

```text
                    Niu
                     │
               LLMProvider
                 /       \
             Gemini      Ollama
                 \       /
                  Modelo
```

La interfaz común debe encapsular únicamente aquello que la aplicación necesita del proveedor, evitando propagar tipos específicos del SDK de Gemini por todo el sistema.

La primera implementación debe conservar el comportamiento actual tanto como sea posible. Después se añadirá el backend local y se compararán:

- latencia;
- calidad de respuesta;
- uso de contexto/memoria;
- estabilidad;
- consumo de recursos;
- facilidad de desarrollo.

---

## 📜 Decisiones existentes

| Fecha | Decisión | Razón |
|-------|----------|-------|
| Día 0-5 | Python 3.11 en `.venv` | Compatibilidad con `PyAudio`/`SpeechRecognition` |
| Día 6-7 | SDK `google-genai` | SDK moderno y tipado |
| Día 11-12 | Memoria manual `List[Content]` + Sliding Window | Control del historial |
| Día 13-14 | `io.BytesIO` para imágenes | Manejo binario de imágenes |
| Día 16 | Separación Cerebro/Voz | Evitar mezclar responsabilidades |
| Día 17-18 | Edge-TTS + ajustes de voz | Voz expresiva sin depender del TTS de Gemini |
| Día 19 | WebSocket persistente + token local | Evitar reautenticación manual |
| Día 20 | Lip-sync RMS → `MouthOpen` | Solución en tiempo real sin librerías pesadas |

### Nueva decisión arquitectónica propuesta

| Estado | Decisión | Razón |
|--------|----------|-------|
| Hecho | Desacoplar proveedor LLM (`LLMProvider`) | Permitir Gemini, Ollama y futuros proveedores sin reescribir el cerebro |
| Hecho | Ollama como backend por defecto | Sin cuotas, latencia local y control del modelo |
| Hecho | Entrada de audio con `sounddevice` | PyAudio no tiene wheel para Python 3.14 |
| Hecho | Salida TTS en el dispositivo por defecto de Windows | El audio va donde va el sistema, sin nombres de dispositivo clavados en el código |
| Hecho | Quitar Voicemeeter del camino de la voz | Ya no hace falta para el lip sync (lo mueve Niu) y era un eslabón que podía fallar en silencio; además añadía latencia |
| Hecho | Salida por DirectSound (no WASAPI) | WASAPI falla al abrir el stream desde un hilo secundario, y exige que la frecuencia coincida exactamente con la del endpoint |
| Hecho | `STTProvider` con `whisper` y `gemini` | Mismo patrón que `LLMProvider`: cambiar de motor sin tocar captura ni `main.py` |
| Hecho | Whisper local como motor por defecto | Sin cuotas, sin internet y sin enviar la voz a terceros |
| Hecho | Capturar con los canales nativos del micro y elegir canal en Python | Pedir `channels=1` a un dispositivo estéreo corrompe el audio en WASAPI |
| Hecho | `initial_prompt` con el nombre «Niu» | Sin contexto, el decoder lo sustituía por «New»/«Neil» |
| Hecho | Whisper `large-v3-turbo` + `beam_size=1` | Mismo encoder con decodificador de 4 capas en vez de 32: 5,94 s → 0,45 s con el mismo texto |
| Hecho | `preparar()` en el proveedor LLM | El primer turno pagaba 9,5 s de carga en frío; ahora se paga al arrancar |
| Hecho | `keep_alive` de 30 min en Ollama | Con los 5 min por defecto, una pausa descargaba el modelo y volvía el coste |
| Hecho | `silencio_final` 1,0 → 0,6 s | Era tiempo muerto puro antes de empezar a transcribir |
| Pendiente | `GeminiAdapter` | Poder alternar entre local y nube |

---

## 🔑 Configuración sensible

Nunca versionar:

- API keys.
- Tokens de VTube Studio.
- Credenciales.
- Archivos `.env` reales.

Ejemplo documentado:

```env
GOOGLE_API_KEY=tu_api_key
```

### Variables que cambian el comportamiento sin tocar código

Desde la fase 0 del panel, los ajustes viven en **`core/config.py`** como un
objeto `Ajustes` congelado, no como constantes de importación. La precedencia es:

```text
config.json  >  variables de entorno  >  valores de fábrica
```

El JSON gana porque es lo que escribe el panel; las variables siguen aceptándose
para no romper el `.env` y los scripts que ya existen. `core/config.py` carga
`.env` por su cuenta (sin pisar lo que ya esté en el entorno), así que la consola
y el panel leen lo mismo. Los valores se leen **al usarlos**, no al importar el
módulo, así que un cambio en el panel surte efecto en la siguiente frase o el
siguiente turno. Un cambio en caliente no puede tocar lo que ya está cargado
(modelo en GPU, voz de un audio ya sintetizado): esos campos se marcan en la
interfaz como «se aplica al reiniciar el motor».

| variable | por defecto | para qué | editable en el panel |
|---|---|---|---|
| `NIU_IDIOMA` | `es` | perfil de idioma: voz, tono, reglas de estilo y prompt del STT (`es`, `en`) | sí |
| `NIU_VOZ` | la del perfil | forzar una voz concreta de Edge-TTS | sí |
| `NIU_TONO` | la del perfil (`+0Hz`) | forzar el tono de Edge-TTS (`-25Hz`) | sí |
| `NIU_VELOCIDAD` | `+0%` | ritmo de habla de Edge-TTS (`-8%`, `+10%`) | sí |
| `NIU_SALIDA` | dispositivo de Windows | forzar el dispositivo de salida de la voz | sí |
| `NIU_MIC` | `DGM20 USB Microphone` | nombre del micrófono | sí |
| `NIU_SILENCIO_FINAL` | `0.9` | silencio que hay que oír para cortar la frase | sí |
| `OLLAMA_MODEL` | `qwen2.5:7b-instruct-q4_k_m` | modelo de Ollama | sí |
| `NIU_STT` | `whisper` | motor de reconocimiento (`whisper`, `gemini`) | sí |
| `NIU_WHISPER_MODELO` | `large-v3-turbo` | modelo de Whisper | sí |
| `NIU_STT_IDIOMA` | el del perfil | forzar el idioma del STT (`en`, `es`); `auto` = detección automática | no (salida de emergencia) |
| `NIU_STT_PROMPT` | el del perfil | contexto que se le da al decoder de Whisper | no (se deriva del perfil) |
| `NIU_WHISPER_BEAM` | `1` | hipótesis del decodificador (más = más calidad y más lento) | no |
| `NIU_TTS_TIMEOUT` | `15` | segundos antes de rendirse con una frase | avanzado |
| `NIU_TTS_INTENTOS` | `2` | reintentos de Edge-TTS | avanzado |
| `NIU_TEMPERATURA` | `0.9` | creatividad del LLM | avanzado |
| `NIU_OLLAMA_KEEP_ALIVE` | `30m` | cuánto mantiene Ollama el modelo en memoria | no |

Los secretos (`GOOGLE_API_KEY`, `vts_token.txt`) **no** están en `config.json` ni
se exponen en la interfaz: solo se indica si están configurados o no.

Los valores absurdos se corrigen y se avisan (`[CONFIG] ...`) en vez de romper
el arranque: un `silencio_final` de 99 s se queda en 3 s, un `tono` sin unidad
vuelve al del perfil y un `config.json` corrupto se ignora entero.

---

## 🧪 Problema actual

El backend local ya está integrado y responde, el oído funciona de extremo a extremo, la boca se mueve con la voz mientras suena (parte a parte), el audio sale por los auriculares, la conversación se siente fluida (**0,95-1,65 s hasta la primera palabra**) y funciona en español y en inglés (`NIU_IDIOMA`). Los puntos débiles conocidos ahora son:

- Las expresiones emocionales usan hotkeys (`MouthSmile`, `MouthFrown`...) que no existen en el modelo cargado.
- El TTS bloquea el bucle mientras habla (no hay barge-in): no se puede interrumpir a Niu.
- No hay wake word: Niu transcribe cualquier cosa que oiga mientras el bucle está activo.
- Las respuestas duran 14-17 s de audio; con streaming ya no bloquean, pero alargan el turno antes de poder volver a hablar.
- Los mensajes técnicos del TTS se mezclan con el texto de Niu en la consola, porque ahora ocurren a la vez.
- Hay tests de la envolvente, del corte de frases, del recorte de silencio y de los idiomas, pero no del cerebro ni del adaptador LLM.

**Objetivo inmediato:** crear contenido en inglés con `NIU_IDIOMA=en` (voz de Aria) y observar si la personalidad se sostiene en inglés. Después: respuestas más cortas, modo espejo de idioma y barge-in.

### Caso resuelto: «Niu responde pero no se la oye»

Síntoma: los logs decían `[TTS] Reproducción completada` sin ningún error, pero no salía sonido.

Causa real: `core/tts.py` reproducía en `Voicemeeter In 1`, y en este driver ese endpoint **no alimenta ninguna tira**: el audio entraba y se descartaba en silencio. Se comprobó recorriendo los 32 endpoints de Voicemeeter y grabando el bus B1 mientras sonaba un tono:

| endpoint | nivel en el bus B1 |
|---|---|
| `Voicemeeter In 1` (el que se usaba) | −240 dBFS (silencio digital) |
| `Voicemeeter In 2/3/4/5`, `VAIO3`, `AUX` | −240 dBFS |
| `Voicemeeter Input` | **−12 dBFS** ✅ |

`Voicemeeter Input` cae en el Strip 3 (Virtual VAIO), que está ruteado a A1 (auriculares) y B1 (VTube Studio). Lección: que una función de reproducción «termine sin error» no significa que el audio haya llegado a su destino; hay que medirlo en el otro extremo de la cadena.

### Caso resuelto: «el avatar no mueve la boca» → ahora la mueve Niu

La primera vía fue dejar que VTube Studio escuchara `Voicemeeter Out B1`. Falló por dos motivos distintos:

| comprobación | resultado |
|---|---|
| micrófono configurado | `Voicemeeter Out B1` ✅ |
| mapeo del modelo | `VoiceVolumePlusMouthOpen` → `ParamMouthOpenY` ✅ |
| tipo de lip sync | `OcculusVRLipsync` (Simple, legacy) → cambiado a `ULipSync` |
| captura real | `Failed to initialize microphone (timeout). Deactivating microphone.` ❌ |
| tras reiniciar VTS | `Activating microphone: ""` — Unity no veía **ningún** dispositivo ❌ |

El dispositivo estaba sano: `sounddevice` lo abría a 48 kHz sin problema, Windows veía 62 entradas y los servicios de audio corrían. El fallo era de Unity, que cachea la lista de dispositivos al arrancar y no se recupera cuando Voicemeeter se reinicia después.

La solución no fue arreglar Unity, sino **quitar la dependencia**: Niu ya conoce su audio antes de reproducirlo, así que calcula ella la apertura de boca y la inyecta por la API.

| pieza | decisión |
|---|---|
| cálculo | RMS por ventana de 25 ms → dBFS → normalizado entre −45 y −16 dB |
| suavizado | ataque 0,65 / liberación 0,30 (abre rápido, cierra despacio) |
| envío | 40 valores/s por `InjectParameterDataRequest` |
| parámetro | `NiuMouthOpen` (propio) con respaldo a `VoiceVolumePlusMouthOpen` |
| verificación | `probar_lipsync.py` mide `ParamMouthOpenY` por la API |

Resultado medido: `298/298` frames en 7,45 s para 7,46 s de audio, con `ParamMouthOpenY` recorriendo 0 → 2,30 y 14 aperturas en una frase.

#### Tres cosas que costaron encontrar

**1. Los parámetros de tracking sí se pueden inyectar; los Live2D no.** El error 453 no era «la API no deja inyectar», era «`ParamMouthOpenY` es un parámetro Live2D». `VoiceVolumePlusMouthOpen` y `VoiceVolume` aceptan inyección sin problema. Eso permitió que funcionara sin tocar la configuración de VTS.

**2. VTS no contesta al recibir: contesta en su siguiente frame de render.** Cada petición cuesta 16,7 ms fijos (1/60 s), sea cual sea el mensaje. Con 40 envíos por segundo eso deja 8 ms de margen por frame.

**3. `asyncio.sleep` en Windows se despierta en múltiplos de 15,6 ms.** Medido en este equipo:

| pedido | real | error |
|---|---|---|
| 5,0 ms | 15,6 ms | +10,6 ms |
| 16,6 ms | 31,2 ms | +14,6 ms |
| 23,3 ms | 31,2 ms | +7,9 ms |

Con ese error, el bucle se quedaba un 4–5 % atrás y la boca terminaba la frase con retraso creciente, aunque el reloj fuera absoluto. Se arregla con `timeBeginPeriod(1)` mientras dura la animación (`_TemporizadorPreciso`), que baja el error a ~1 ms, y restando 2 ms de margen para que no se acumule. Después del arreglo, 20, 25, 30, 35 y 40 Hz cumplen con un 0,1 % de error.

### Caso resuelto: «se mueve la boca pero no se oye nada»

Síntoma: el lip sync medía `ParamMouthOpenY` de 0 a 2,29 sin problema, y los logs decían `[TTS] Reproducción completada`, pero no salía sonido.

Lo primero fue comprobar el otro extremo de la cadena, no el código: se reprodujo un tono en `Voicemeeter Input` y se grabó cada bus por separado.

| comprobación | resultado |
|---|---|
| RMS de lo que se manda a `sd.play` | −15,1 dBFS ✅ (la señal es real) |
| estado del stream de salida | `activo=True` ✅ |
| bus A1 (auriculares) | −240 dBFS ❌ |
| bus B1 (virtual) | −240 dBFS ❌ |
| mismos buses por MME, DirectSound y WASAPI | silencio en los tres ❌ |

Que **los tres backends** coincidan descarta el host API. Una captura de pantalla del mezclador lo cerró: A1 estaba correctamente asignado a los auriculares DGM20, la tira 3 tenía A1 activado, y aun así **ningún medidor se movía**, ni el de la tira ni el del máster. El audio no llegaba ni a entrar.

La prueba decisiva fue quitar el eslabón: el mismo tono y la misma frase, reproducidos **directo en los auriculares**, se oyeron a la primera. Voicemeeter era el que estaba tragándose el audio; el código, los auriculares y el archivo estaban bien.

Decisión: **quitar Voicemeeter del camino de la voz**. Con el lip sync en manos de Niu, el cable virtual ya no servía para nada: era una pieza más que podía fallar en silencio, y añadía latencia.

| pieza | antes | ahora |
|---|---|---|
| destino | `Voicemeeter Input` → VAIO → A1 | endpoint de salida de Windows |
| selección | nombre fijo en el código | `buscar_salida_por_defecto()` + `NIU_SALIDA` para forzar |
| canales | la voz repetida en los 8 canales del endpoint | voz en los 2 primeros, silencio en el resto |

De paso apareció un dato útil: al reproducir el MP3 a 24 kHz en un endpoint de 48 kHz, PortAudio responde `Invalid sample rate [PaErrorCode -9997]`. Eso confirma que el remuestreo de `preparar_audio` no es decoración: sin él, el archivo no se puede ni abrir.

Lecciones:

1. **Medir en el destino, no en la salida.** `sd.play` sin excepción solo prueba que se pidió reproducir, no que algo sonara.
2. **Cuando todos los caminos fallan igual, sospecha de la pieza común**, no de cada camino por separado.
3. **Antes de arreglar una pieza, pregunta si sigue haciendo falta.** Eliminar Voicemeeter resolvió el problema y mejoró la latencia sin añadir una sola línea de código.


### Caso resuelto: «tarda 16-20 s en contestar»

Síntoma: la conversación funcionaba, pero entre callar y oír a Niu pasaban muchos segundos. La estimación inicial era «40 % transcripción, 10-20 % texto, el resto el TTS». Se midió, y el reparto real era distinto.

Punto de partida, medido:

| etapa | medido | peso |
|---|---|---|
| espera de silencio antes de cortar | 1,0 s | 9 % |
| **Whisper large-v3, beam 5** | **5,3–6,6 s** | **55 %** |
| cerebro esperando la respuesta completa | 1,9–3,8 s | 25 % |
| Edge-TTS | 0,6 s | 6 % |

Dos correcciones: la transcripción pesaba **más** de lo supuesto, y el TTS **no** era el culpable (0,57 s para una frase que suena 15 s).

Además, los «16-20 s» percibidos incluían el tiempo que Héctor pasa hablando: el silencio real hasta el primer sonido era de unos 10-11 s.

Qué se hizo, con el ahorro medido de cada cosa:

| cambio | antes | después |
|---|---|---|
| `large-v3` + `beam 5` → `large-v3-turbo` + `beam 1` | 5,94 s | **0,45 s** |
| `preparar()` del LLM al arrancar | primer turno 9,48 s | 2,6–4,2 s |
| `keep_alive` 5 min → 30 min | una pausa recargaba el modelo | sigue cargado |
| `silencio_final` 1,0 → 0,6 s | 1,0 s | 0,6 s |
| … y de vuelta a 0,9 s | cortaba frases largas | 0,9 s |

Por qué funciona cada uno:

- **`turbo`**: mismo encoder, decodificador de 4 capas en vez de 32. El texto transcrito salió idéntico en la prueba.
- **`beam_size=5` → `1`**: beam 5 calcula cinco hipótesis y se queda con la mejor; quintuplica la decodificación para una mejora marginal.
- **`preparar()`**: el coste de cargar el modelo no desaparece, solo se elige *cuándo* pagarlo. Al arrancar no hay nadie esperando una respuesta.

Riesgo comprobado antes de adoptar `turbo`: la RTX 4050 tiene 6 GB y los dos modelos tienen que convivir. Con `turbo` (~1,6 GB) y Ollama (~4,4 GB): **5797 / 6141 MiB**, sin que Ollama caiga a CPU. Quedan ~350 MB de margen, así que conviene no añadir otro modelo grande a la vez.

Resultado: primer sonido de **10,7 s → 4,7 s** (sin contar STT, medido por teclado). Con el micrófono y `turbo` queda en ~5 s.

Quedaba el cambio grande: `main.py` seguía esperando la respuesta **completa** del cerebro (3,8 s) antes de sintetizar, aunque el primer token llegaba a los 0,27 s. Se resolvió con la tubería por frases (ver el caso siguiente).

### Caso resuelto: «habla, pero tarda en arrancar»

Síntoma: con `large-v3-turbo` y el cerebro precalentado, el primer sonido era de ~4,7 s. El reparto decía que ~3,8 s eran el cerebro esperando la respuesta entera, y ~0,6 s el TTS.

La clave medida: con `procesar_mensaje_streaming`, el **primer token** llega a los **0,27 s** y la **primera frase completa** a los **0,62 s**. Es decir, se estaba esperando a tener 15 s de texto para poder decir los primeros 2 s.

Qué se hizo: dejar de tratar cerebro, TTS y reproducción como tres pasos en fila y convertirlos en tres etapas solapadas conectadas por colas.

```text
generar_texto  →  sintetizar  →  reproducir + boca
   (cola)           (cola)
```

Mientras una parte suena, la siguiente se sintetiza, y el cerebro sigue escribiendo la tercera. Nadie espera a nadie.

| | antes | después |
|---|---|---|
| primer sonido | 4,7 s | **1,95 s** |
| boca | 1 bloque de 605 frames | 4 partes, 80/80, 161/161, 332/332, 131/131 |

Los tres problemas que hubo que resolver, y ninguno es de rendimiento:

- **Dónde cortar el texto.** El corte no se puede hacer mirando solo el final del buffer: `"3." + "5"` es un decimal y `"..."` llega punto a punto. La regla es *signo final seguido de espacio*, y eso resuelve de paso los decimales, los enlaces (`niu.dev`) y los emojis compuestos (el corte siempre cae en un espacio).
- **Los puntos suspensivos no cierran frase.** Niu escribe «bueno... o sea... este...» constantemente. Si cada uno cerrara frase, cada duda sería un trozo de audio con su propia petición y su propia pausa: el habla sonaría troceada justo donde debe sonar natural. Es una decisión sobre *cómo habla el personaje*, no sobre el código.
- **Un servicio externo puede dejar de contestar.** Un turno se quedó colgado más de 5 minutos dentro de `comunicador.save()` de Edge-TTS, sin excepción y sin error. Sin tope de tiempo, una petición perdida congela la conversación para siempre. Ahora hay 15 s y 2 intentos por frase: se pierde una frase, no el turno.

Efecto secundario del corte: aparecen trozos que solo contenían emojis (`"🚀✨"`). No son un error; se detectan antes de llamar al servicio y se saltan.

Coste de esta arquitectura: ya no se tiene la frase entera antes de hablar, así que **no se puede saber la duración total ni elegir la expresión del avatar al principio** — hay que decidir parte a parte o al final (lo que devuelve `hablar_por_partes`). Y los mensajes técnicos del TTS se mezclan con el texto de Niu en la consola, porque ahora ocurren a la vez.

### Caso resuelto: «le hablo en inglés y me contesta en español»

Síntoma: la transcripción del inglés era correcta, pero Niu respondía en español. Y no siempre: en un turno contestaba «Bueno... yo creo que estoy bastante bien» y en otro «Sure thing! Here's a silly phrase». Sin patrón fijo.

Causa: **nadie le había dicho en qué idioma hablar**. El idioma vive en tres sitios y ninguno lo fijaba:

| dónde | estado anterior |
|---|---|
| STT (`language=`) | detección automática, con un `initial_prompt` en español: el inglés se transcribía **en español** (ver el caso siguiente) |
| prompt de personalidad | escrito en español, sin ninguna regla de idioma |
| voz de Edge-TTS | `es-MX-DaliaNeural`, fija |

Decisión de diseño: **tabla de perfiles, no `Protocol`**. `LLMProvider` es una interfaz porque Ollama y Gemini hacen cosas distintas (HTTP con JSON, SDK con auth, streams con otra forma). Un idioma es el mismo código con otros datos. Dos clases `EspanolProvider`/`InglesProvider` serían dos clases que solo devuelven strings distintos.

El detalle que casi se escapa: el prompt está escrito en español **con muletillas españolas** («bueno...», «o sea...», «este...»). Pidiendo solo «responde en inglés», el modelo las **traduce** y Niu suena a española hablando inglés: *«well... I mean... this...»*. Por eso el perfil inglés trae sus propias muletillas («like...», «you know...», «honestly...») y una regla explícita de no traducir literalmente.

La personalidad se escribe una vez. El perfil no la reescribe: le añade un bloque. Dos prompts paralelos se desincronizan al primer cambio.

Resultado medido: respuesta en inglés con contracciones («I'm», «gonna», «kinda»), muletillas nativas y voz inglesa. Y un efecto secundario bueno: al estar el idioma fijado, las respuestas dejan de mezclar idiomas.

Límite de esta decisión: en modo fijo Niu **no imita** el idioma del usuario. Ese modo (espejo) requiere que Whisper exponga el idioma detectado y elegir voz por turno; queda pendiente a propósito.

### Caso resuelto: «las pausas entre partes se notaban»

Síntoma: con el streaming funcionando, entre una parte y otra había pausas de «segundos o menos». La tubería no tenía la culpa: el audio siguiente solía estar listo antes de que terminara el anterior.

Medido antes de tocar nada: Edge-TTS rellena **cada frase** con ~0,18 s al principio y **~0,85 s al final**. En una respuesta entera no se nota, porque el relleno solo está en los bordes. Al hablar por partes, cada trozo arrastra el suyo y las fronteras suman ~1 s.

El dato que lo dejó claro: «¡Hola!» duraba 1,87 s con **0,40 s de voz**. El 78 % era silencio.

Dos arreglos, en este orden:

1. **Recortar** ese relleno dejando 0,05 s al principio y 0,15 s al final. No a cero: un poco de aire es lo que evita que el habla suene atropellada.
2. **No decir frases de menos de 40 caracteres por separado**: se acumulan con la siguiente. Un «¡Bueno!» de 0,6 s no compensa los ~0,3 s de pausa que abre y cierra el dispositivo.

El segundo arreglo tiene una excepción que salió de medir: aplicado también a la primera frase, el primer sonido subía de **0,95 s a 2,40 s**. Al arrancar manda la velocidad; a partir de la segunda frase manda el ritmo.

| | antes | después |
|---|---|---|
| partes (español) | 8 | 5 |
| audio dicho | 26 s | 17 s |
| partes (inglés) | 9 | 4 |
| primer sonido | 1,09 s | **0,95 s** |

### Caso resuelto: «hablo en inglés y la transcripción sale en español»

Síntoma: el renglón `👤 Tú:` aparecía en español aunque se hablara en inglés: «¿could usted decir algo en inglés para mí?». Como el cerebro contesta a la transcripción, la conversación salía torcida aunque las reglas de idioma ya estuvieran bien: el modelo recibía una frase mezclada y a veces seguía en español.

Causa: dos empujones hacia el español en el mismo sitio.

1. `NIU_STT_IDIOMA` estaba vacío por defecto, o sea **detección automática**: Whisper decidía en qué idioma estaba oyendo.
2. El `initial_prompt` de Whisper decía «Conversación hablada en español con Niu…».

El segundo pesa más de lo que parece. Medido con el mismo audio en inglés y el mismo modelo:

| configuración | transcripción |
|---|---|
| auto + prompt español | «Ok, so, hey Niu. **¿Cómo estás hoy? Estoy solo probando si me entiendes en inglés**…» |
| `language="en"` + prompt español | **igual de mala**: el prompt manda más que el flag |
| `language="en"` + prompt inglés | correcta, palabra por palabra |

O sea: fijar el idioma a medias no habría servido. El `initial_prompt` no es un adorno: es contexto que el decodificador usa para elegir palabras, y con 10 s de audio puede arrastrar todo el texto a su idioma.

Arreglo: el perfil lleva ahora `prompt_stt`, y el idioma del oído se resuelve en **una sola función** (`idioma_stt()` en `core/stt.py`) que por defecto devuelve el código del perfil. Hablar y oír apuntan al mismo sitio por construcción, no por acordarse de configurar dos variables. `NIU_STT_IDIOMA=auto` sigue existiendo como salida de emergencia para quien alterna idiomas de verdad.

Verificado: `[STT] Motor: whisper | idioma: en` al arrancar con `NIU_IDIOMA=en`, y transcripción inglesa correcta sobre audio sintetizado.

### Caso resuelto: «el micrófono no entendía»

Síntoma: el micrófono capturaba, el nivel era correcto (−30 dBFS), pero todos los motores fallaban (Google devolvía vacío, Whisper alucinaba «¡Suscríbete!», Gemini inventaba otros idiomas).

Causa real: `core/stt.py` abría el dispositivo con `channels=1`. El DGM20 entrega **2 canales** (mono duplicado), y la conversión 2→1 de WASAPI en PortAudio corrompía el audio. Medido con el mismo micrófono y la misma frase:

| captura | f0 medido | centroide de agudos | Whisper |
|---|---|---|---|
| 1 canal | 369 Hz (error de octava) | 1 103 Hz | no transcribe |
| 2 canales | 159 Hz (correcto) | 1 635 Hz | «Hola Niu, uno, dos, tres» |

Por qué costó tanto: el daño era **invisible** en las métricas obvias. El nivel era normal, la duración era correcta y el habla seguía pareciendo habla. Las hipótesis acústicas (ruido, reverberación, retumbe, velocidad de reloj, tamaño del modelo, procesado de Windows) eran plausibles y hubo que descartarlas una por una con mediciones, no por intuición.

Lección para el proyecto: cuando un síntoma afecta a **todos** los motores a la vez, el fallo suele estar en la capa común (captura), no en los motores.

---

## 🎓 Estado de aprendizaje

Esta sección existe para que el tutor no enseñe desde cero conceptos que el estudiante ya ha practicado.

### Ya practicado / con experiencia

- Python básico y creación de programas pequeños.
- Uso de terminal y entornos virtuales.
- Consumo de una API de IA.
- Texto, voz e imágenes como entradas para un programa de IA.
- Estructuración inicial de un proyecto en módulos.
- Uso de `google-genai`.
- Integración básica con Edge-TTS.
- Comunicación con VTube Studio.
- Uso de Git a nivel práctico.

### En práctica

- Asyncio y programación asíncrona.
- WebSockets.
- Arquitectura de aplicaciones más grandes.
- Manejo de errores y depuración.
- Diseño de interfaces entre componentes.
- Memoria y contexto para LLMs.
- Integración entre varios servicios.
- Depuración de audio digital (frecuencia de muestreo, canales, espectro, niveles en dBFS).
- Comprobar hipótesis con experimentos controlados en vez de cambiar cosas a ciegas.
- Distinguir «el servicio no puede» de «el cliente lo usa mal» (el caso de la inyección de parámetros).
- Medir un bucle de tiempo real y ajustar la tasa a lo que el sistema sostiene de verdad.
- Escribir tests para funciones puras (`tests/test_envolvente.py`) y para la tubería asíncrona.

### Prioridad de aprendizaje actual

1. Comprender la arquitectura existente antes de modificarla.
2. Entender el flujo completo de punta a punta: voz → STT → cerebro → TTS → envolvente → VTS.
3. Saber medir latencia y localizar dónde se va el tiempo.
4. Escribir tests para la lógica crítica (VAD, remuestreo, cerebro).
5. Ganar autonomía depurando audio y concurrencia sin depender del tutor.
6. Saber explicar cuándo una solución acoplada (VTS escuchando el bus) es peor que una explícita (Niu calculando su boca) aunque cueste una hora más.

### Conceptos aprendidos dentro del proyecto

- **Abstracción con `Protocol`**: `LLMProvider` y `STTProvider` definen el contrato; los adaptadores (`ollama_adapter`, `stt_whisper`, `stt_gemini`) lo cumplen. El resto del sistema no conoce al proveedor concreto.
- **Remuestreo con antialiasing**: interpolar linealmente sin filtrar pliega las frecuencias altas dentro de la banda audible. La versión correcta recorta el espectro antes de cambiar de tasa.
- **Depuración por medición controlada**: cambiar una sola variable (canales, frecuencia, modelo) y comparar números objetivos (f0, centroide espectral, dBFS, transcripción). Formular una hipótesis y refutarla con datos, en vez de acumular cambios.
- **Niveles en dBFS**: medir en absoluto (contra el fondo de escala) y no solo normalizando por archivo, porque normalizar oculta si lo que hay es señal o ruido amplificado.
- **Contexto del decoder (`initial_prompt`)**: Whisper elige palabras por contexto; sin él, un nombre propio como «Niu» se convierte en «New».
- **Medir en el otro extremo de la cadena**: que una función de reproducción termine correctamente no prueba que el audio llegue; hay que grabarlo donde se supone que suena.
- **Sospechar de la pieza común**: si todos los backends fallan igual, el fallo no está en cada backend sino en lo que comparten.
- **Preguntar si una pieza sigue haciendo falta antes de arreglarla**: Voicemeeter existía para el lip sync de VTS; al mover el lip sync a Niu, mantenerlo solo añadía latencia y puntos de fallo.
- **Los parámetros Live2D no se pueden escribir por la API**: `InjectParameterDataRequest` solo acepta parámetros de *tracking* (`VoiceVolume`, y los que crea un plugin). Pedir `ParamMouthOpenY` devuelve el error 453.
- **Un parámetro de tracking propio es la vía limpia**: `ParameterCreationRequest` crea un parámetro que solo escribe tu plugin y que el modelo puede usar como entrada de cualquier parámetro Live2D.
- **Medir en vez de suponer**: para saber si un mapeo existe, se inyecta 0 y 1 y se mira si la boca se mueve. Leer el archivo de configuración habría dado falsos negativos.
- **Un servicio puede contestar solo una vez por frame**: VTS responde en su siguiente frame de render, así que cada petición cuesta 16,7 ms aunque sea local. Eso fija el techo de peticiones por segundo.
- **`asyncio.sleep` no tiene precisión de milisegundos en Windows**: se despierta en múltiplos de 15,6 ms. Un bucle que dependa de dormir "16 ms" se retrasa el doble. Se arregla con `timeBeginPeriod(1)` de WinMM, o midiendo y compensando.
- **Separar el motor de la interfaz con eventos**: si el panel copiara el bucle de `main.py`, habría dos conversaciones que se separan con cada cambio. El motor emite hechos (`transcripcion`, `fragmento`, `metricas`) y cada cliente decide cómo mostrarlos. Un oyente roto se aísla: la interfaz es un consumidor, no un requisito para que Niu hable.
- **Parar de verdad no es cancelar la tarea**: el audio suena en un hilo bloqueado en `sd.wait()`. Cancelar la corrutina lo deja sonando igual; hace falta `sd.stop()` además de la cancelación, y por eso «detener voz» son dos acciones, no una.
- **Configuración como dato, no como constante de importación**: leer `os.getenv` al importar hace que un cambio en caliente no tenga efecto. Un objeto `Ajustes` congelado, leído en el momento de usarlo y validado al entrar, permite que la interfaz cambie valores sin reiniciar Python y sin dejar el estado a medio cambiar.
- **Un valor inválido se avisa, no se ignora**: corregir en silencio un tono mal escrito o un silencio de 99 s es peor que rechazarlo, porque el usuario cree que aplicó lo que pidió.
- **Reloj absoluto en vez de esperas relativas**: si cada frame se programa como `inicio + i/fps` en lugar de "dormir 25 ms", un retraso puntual no se convierte en desfase acumulado.
- **Suavizado asimétrico**: abrir rápido y cerrar despacio es lo que diferencia una boca de un vúmetro.
- **Definiciones duplicadas en Python**: si un método se define dos veces en la misma clase, la segunda sustituye a la primera sin avisar; el código anterior queda muerto y engaña al leerlo.
- **Separar producir de usar**: `tts.py` genera y prepara el audio sin reproducirlo, para que el lip sync pueda analizarlo antes de que suene. Una función que "hace todo" no deja hueco para observar sus partes.
- **Presupuesto de latencia**: en un sistema hablado, lo que importa no es "cuánto tarda en total" sino "cuánto tarda en sonar la primera palabra". Cada etapa se mide por separado, porque la intuición reparte mal el tiempo (se culpó al TTS, que costaba 0,6 s, cuando el 55 % era la transcripción).
- **`beam_size` no es un detalle de calidad, es un multiplicador de coste**: explorar cinco hipótesis y quedarse con una cuesta ~5 veces más que explorar una.
- **Mover el coste, no eliminarlo**: cargar un modelo cuesta lo mismo tarde o temprano. El truco es pagarlo al arrancar, cuando nadie espera respuesta, en vez de en la primera frase.
- **`keep_alive` y la memoria de un servidor de modelos**: un modelo local puede descargarse solo tras unos minutos de inactividad. Para una conversación con pausas, eso significa volver a pagar la carga varias veces.
- **VRAM es un recurso compartido**: dos modelos en la misma GPU compiten. Antes de cambiar uno, comprobar que los dos caben; si no, el segundo cae a CPU y gana el que parecía la mejora.
- **Tubería con colas en vez de pasos en fila**: cerebro, TTS y reproducción no tienen por qué esperarse. Con una cola entre cada uno, cada etapa trabaja mientras la siguiente consume lo anterior, y el tiempo hasta la primera palabra depende de la primera frase, no de la respuesta entera.
- **Cortar texto que todavía se está escribiendo**: el corte no puede mirar solo el final del buffer; hay que decidir con una regla estable («signo final seguido de espacio») porque el fragmento puede acabar justo en mitad de un decimal, unos puntos suspensivos o un emoji.
- **La puntuación es una decisión sobre el personaje, no sobre el código**: que los «...» no cierren frase no es un detalle técnico; es lo que evita que cada duda de Niu suene como una frase nueva.
- **Todo servicio externo necesita un tope de tiempo**: Edge-TTS dejó de contestar sin cerrar la conexión y el sistema esperó más de 5 minutos. Sin `timeout` no hay error que capturar, solo un cuelgue silencioso. Y tras un fallo hay que crear un objeto nuevo si el anterior se consumió.
- **Un test puede simular lo que no se puede provocar**: esperar a que un servicio se caiga justo ahora es imposible, pero sustituir su clase por un doble que se cuelga prueba el comportamiento igual, en milisegundos.
- **Configuración o abstracción: no todo lo que varía necesita una interfaz**: los proveedores LLM necesitan un `Protocol` porque su *comportamiento* difiere; los idiomas son el mismo código con otros datos y se resuelven con una tabla de perfiles. La pregunta que decide es «¿cambia lo que hace, o solo los valores con los que lo hace?».
- **El idioma no es solo traducir**: el registro vive en el prompt. Pedir «responde en inglés» a un prompt lleno de muletillas españolas produce inglés traducido, no inglés natural. La solución es darle al perfil sus propias muletillas, no traducir las existentes.
- **Los servicios externos rellenan el audio**: Edge-TTS añade ~0,85 s de silencio al final de cada frase. En un audio entero es invisible; al trocearlo, cada trozo arrastra su relleno y el silencio se convierte en pausa. Hay que medir los bordes, no solo la duración.
- **Política y mecanismo separados**: `extraer_frases` corta (mecanismo); cuándo *conviene* cortar (mínimo de caracteres, primera frase exenta) es política y la aplican los generadores. Así el mecanismo se puede probar con y sin política.
- **Los tests de propiedad encuentran bugs tontos y reales**: comprobar que el texto reconstruido es igual al original descubrió que al acumular frases cortas se comía un espacio y las palabras se pegaban («¡Hola!Sí»). Ningún test de «contiene esta frase» lo habría visto.
- **Un flag no basta si el contexto dice otra cosa**: poner `language="en"` en Whisper y dejar un `initial_prompt` en español seguía transcribiendo en español. El prompt del decoder es contexto que se usa para elegir palabras, no documentación decorativa. La solución no fue añadir otra variable, sino hacer que el prompt salga del **mismo dato** que el idioma.

### Aún no asumir dominio completo de

- Diseño de sistemas complejos.
- Concurrencia avanzada.
- Patrones de arquitectura para aplicaciones orientadas a eventos.
- Sistemas de memoria/RAG avanzados.
- Tool calling y agentes autónomos.
- Optimización avanzada de inferencia local.

---

## 🚧 Deuda técnica conocida

- Falta `GeminiAdapter` para volver a usar la nube.
- Los scripts sueltos de la raíz (`probar_entrada_voz.py`, `prueba_de_voz.py`, `diagnostico_mic.py`, `dia_por_dia/*`) siguen leyendo `os.getenv` directamente: no se migraron porque son herramientas de diagnóstico, no el motor.
- Varias variables se leen al construir un objeto (modelo de Whisper, `keep_alive`) y no pueden cambiar en caliente: por eso el plan del panel las marca como «se aplica al reiniciar el motor».
- Logging profesional pendiente.
- Cuando Edge-TTS (servicio en la nube) falla para todas las frases, el turno acaba sin audio. El motor ya avisa en el chat («⚠️ Esta respuesta no tiene audio...»), pero no reintenta el turno entero.
- El micrófono oye la sala (y a veces el audio de Niu) y Whisper alucina frases tipo «¡Suscríbete al canal!» con silencio: falta un filtro de transiciones falsas.
- Tests unitarios pendientes del cerebro y del adaptador LLM (la envolvente del lip sync, el corte de frases y el tope de tiempo del TTS ya los tienen en `tests/`).
- Interrupción de TTS pendiente (barge-in).
- Cambiar `idioma`, `micrófono` o los modelos desde el panel exige reiniciar el motor: la interfaz lo avisa con un chip «reinicia» y en la respuesta del guardado, pero no reinicia sola la conversación.
- El editor de ajustes no valida la voz contra la lista real de Edge-TTS: un nombre mal escrito se descubre al probar la voz. `GET /api/ajustes` devuelve solo sugerencias frecuentes.
- El chat del panel guarda la conversación mientras el panel está abierto; abrir el panel empieza una sesión nueva (`sesiones/*.json`). El motor no conserva nada: esa es la memoria del cerebro, no del panel.
- Las frases se sintetizan y reproducen de una en una: entre una parte y otra puede notarse una pausa si el TTS tarda más que la duración de la anterior (no se precargan varias por adelantado).
- El idioma es fijo por sesión: en modo `en` Niu no imita el idioma del usuario. El modo espejo necesita que Whisper exponga el idioma detectado y elegir voz por turno.
- El registro inglés del prompt está sin probar a fondo: es un modelo de 7B y la personalidad puede desdibujarse más en inglés que en español.
- Detección de voz basada en RMS (sensible al ruido de fondo: una tos o un golpe en la mesa corta la frase).
- Sin wake word: mientras el bucle está activo, Niu transcribe cualquier voz.
- El primer arranque descarga el modelo de Whisper (~3 GB) si no está en caché.
- `ParamMouthForm` se queda fijo en 1.0 (sonrisa): el mapeo `MouthSmile` existe pero nada le envía datos.
- Las expresiones llaman a hotkeys que no existen en el modelo (`MouthSmile`, `MouthFrown`...): fallan sin avisar y no hay alternativa definida.

---

## 📌 Regla para el tutor

Antes de proponer una funcionalidad nueva, comprobar en el código si ya existe.

No enseñar como nuevo algo que esté implementado y dominado.

No asumir que una funcionalidad documentada como "completa" está necesariamente comprendida por el estudiante: distinguir entre **funcionalidad existente** y **conocimiento dominado**.
