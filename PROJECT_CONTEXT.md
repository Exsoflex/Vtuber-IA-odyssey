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
│   ├── brain.py           # Memoria + personalidad + llamada a LLMProvider
│   ├── llm_provider.py    # Interfaz común (Protocol) + LLMConfig/LLMResponse
│   ├── ollama_adapter.py  # Implementación local vía /api/chat
│   ├── stt.py             # Micrófono (sounddevice) + detección de silencio (VAD)
│   ├── stt_provider.py    # Interfaz común (Protocol) + utilidades de audio
│   ├── stt_whisper.py      # Adaptador local: faster-whisper (GPU/CPU)
│   ├── stt_gemini.py       # Adaptador nube: Gemini (audio → texto)
│   ├── tts.py             # Voz: Edge-TTS → MP3 → dispositivo virtual
│   ├── lipsync.py         # Boca: audio → envolvente → parámetro de VTS
│   ├── audio_devices.py   # Búsqueda de dispositivos por nombre y host API
│   └── vts_client.py      # VTube Studio: WebSocket + auth + parámetros
├── main.py                # Orquestador: entrada + LLM + TTS + VTS + CLI
├── probar_entrada_voz.py  # Prueba de extremo a extremo del oído (captura + STT)
├── probar_lipsync.py      # Prueba de extremo a extremo de la boca
├── tests/                 # pytest: lógica que puede romperse en silencio
├── requirements.txt
├── .env                   # GOOGLE_API_KEY, OLLAMA_MODEL, NIU_STT (no versionado)
├── vts_token.txt          # Token VTS persistente (no versionado)
├── test_audio.py          # Script auxiliar para listar salidas de audio
└── dia_por_dia/           # Historial de aprendizaje
```

### Flujo funcional actual

```text
Usuario: voz (micrófono DGM20) o teclado
        ↓
core/stt.py → PCM 16 kHz (2 canales nativos → mono) → VAD por RMS
        ↓
STTProvider (NIU_STT=whisper | gemini) → texto
        ↓
core/brain.py
        ↓
LLMProvider (por defecto OllamaAdapter → /api/chat)
        ↓
respuesta
        ↓
core/lipsync.py  (sintetiza, calcula la boca y reproduce)
        ├── core/tts.py → MP3 → endpoint de salida de Windows (auriculares DGM20)
        └── envolvente (40 Hz) → VTS: NiuMouthOpen → ParamMouthOpenY
```

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
- ✅ Whisper `large-v3` en GPU (RTX 4050): 0,9–1,6 s por frase. Fallback a CPU int8.
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

---

## 🧪 Problema actual

El backend local ya está integrado y responde, el oído funciona de extremo a extremo, la boca se mueve con la voz y el audio sale por los auriculares. Los puntos débiles conocidos ahora son:

- Las expresiones emocionales usan hotkeys (`MouthSmile`, `MouthFrown`...) que no existen en el modelo cargado.
- El TTS bloquea el bucle mientras habla (no hay barge-in).
- No hay wake word: Niu transcribe cualquier cosa que oiga mientras el bucle está activo.
- Hay tests de la envolvente (`tests/`), pero no del cerebro ni del adaptador LLM.

**Objetivo inmediato:** medir la latencia total (voz → respuesta → voz) y después añadir logging y tests del cerebro.

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
- Escribir tests para funciones puras (`tests/test_envolvente.py`).

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
- **Reloj absoluto en vez de esperas relativas**: si cada frame se programa como `inicio + i/fps` en lugar de "dormir 25 ms", un retraso puntual no se convierte en desfase acumulado.
- **Suavizado asimétrico**: abrir rápido y cerrar despacio es lo que diferencia una boca de un vúmetro.
- **Definiciones duplicadas en Python**: si un método se define dos veces en la misma clase, la segunda sustituye a la primera sin avisar; el código anterior queda muerto y engaña al leerlo.
- **Separar producir de usar**: `tts.py` genera y prepara el audio sin reproducirlo, para que el lip sync pueda analizarlo antes de que suene. Una función que "hace todo" no deja hueco para observar sus partes.

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
- Configuración pendiente de migrar a settings tipados.
- Logging profesional pendiente.
- Tests unitarios pendientes del cerebro y del adaptador LLM (la envolvente del lip sync ya los tiene en `tests/`).
- Interrupción de TTS pendiente.
- Streaming de audio pendiente.
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
