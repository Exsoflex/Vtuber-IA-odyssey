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
│   ├── audio_devices.py   # Búsqueda de dispositivos por nombre y host API
│   └── vts_client.py      # VTube Studio: WebSocket + auth + parámetros
├── main.py                # Orquestador: entrada + LLM + TTS + VTS + CLI
├── probar_entrada_voz.py  # Prueba de extremo a extremo del oído (captura + STT)
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
        └──────────────→ core/tts.py → MP3 → Voicemeeter In 1
                                              ↓
                                    VTube Studio (lip sync + audio)
```

### Estado funcional documentado

- ✅ Cerebro desacoplado del proveedor mediante `LLMProvider`.
- ✅ Backend local con Ollama (`qwen2.5:7b-instruct-q4_k_m` por defecto).
- ✅ Memoria manual con ventana deslizante.
- ✅ Voz con Edge-TTS reproducida en `Voicemeeter In 1`.
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
| Hecho | Salida TTS en `Voicemeeter In 1` | Ruteo de audio propio para que VTS haga lip sync |
| Hecho | Salida por DirectSound (no WASAPI) | WASAPI falla al abrir el stream desde un hilo secundario |
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

El backend local ya está integrado y responde, y el oído funciona de extremo a extremo. Los puntos débiles conocidos ahora son:

- Las expresiones emocionales dependen de hotkeys con nombres concretos.
- El TTS bloquea el bucle mientras habla (no hay barge-in).
- No hay wake word: Niu transcribe cualquier cosa que oiga mientras el bucle está activo.
- No hay tests automatizados del cerebro ni del adaptador.

**Objetivo inmediato:** probar la conversación completa (`main.py`), medir la latencia total (voz → respuesta → voz) y después añadir tests y logging.

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

### Prioridad de aprendizaje actual

1. Comprender la arquitectura existente antes de modificarla.
2. Entender el flujo completo de punta a punta: voz → STT → cerebro → TTS → VTS.
3. Saber medir latencia y localizar dónde se va el tiempo.
4. Escribir tests para la lógica crítica (VAD, remuestreo, cerebro).
5. Ganar autonomía depurando audio y concurrencia sin depender del tutor.

### Conceptos aprendidos dentro del proyecto

- **Abstracción con `Protocol`**: `LLMProvider` y `STTProvider` definen el contrato; los adaptadores (`ollama_adapter`, `stt_whisper`, `stt_gemini`) lo cumplen. El resto del sistema no conoce al proveedor concreto.
- **Remuestreo con antialiasing**: interpolar linealmente sin filtrar pliega las frecuencias altas dentro de la banda audible. La versión correcta recorta el espectro antes de cambiar de tasa.
- **Depuración por medición controlada**: cambiar una sola variable (canales, frecuencia, modelo) y comparar números objetivos (f0, centroide espectral, dBFS, transcripción). Formular una hipótesis y refutarla con datos, en vez de acumular cambios.
- **Niveles en dBFS**: medir en absoluto (contra el fondo de escala) y no solo normalizando por archivo, porque normalizar oculta si lo que hay es señal o ruido amplificado.
- **Contexto del decoder (`initial_prompt`)**: Whisper elige palabras por contexto; sin él, un nombre propio como «Niu» se convierte en «New».

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
- Tests unitarios pendientes.
- Interrupción de TTS pendiente.
- Streaming de audio pendiente.
- Detección de voz basada en RMS (sensible al ruido de fondo: una tos o un golpe en la mesa corta la frase).
- Sin wake word: mientras el bucle está activo, Niu transcribe cualquier voz.
- El primer arranque descarga el modelo de Whisper (~3 GB) si no está en caché.

---

## 📌 Regla para el tutor

Antes de proponer una funcionalidad nueva, comprobar en el código si ya existe.

No enseñar como nuevo algo que esté implementado y dominado.

No asumir que una funcionalidad documentada como "completa" está necesariamente comprendida por el estudiante: distinguir entre **funcionalidad existente** y **conocimiento dominado**.
