# 🗺️ ROADMAP: NIU AUTONOMOUS ENGINE

## 📍 Estado actual

### FASE 2 COMPLETADA ✅

Motor base funcional:

- ✅ Cerebro (Gemini + memoria + personalidad)
- ✅ Voz (Edge-TTS + winsound)
- ✅ VTube Studio (WebSocket + auth persistente)
- ✅ Lip-sync (RMS → MouthOpen)
- ✅ Expresiones (keywords → hotkeys)
- ✅ CLI interactivo (voz/texto)
- ✅ Oído propio y desacoplado (Whisper local + Gemini), con captura corregida

El proyecto ahora entra en una etapa de **comprensión, desacoplamiento y robustez**.

---

# 🎯 FASE 2.5: DESACOPLAMIENTO DEL LLM — COMPLETADA (backend local)

La API de Gemini no resultaba adecuada como único backend. El cerebro ya depende de `LLMProvider` y usa Ollama por defecto, conservando memoria, personalidad, TTS y VTube Studio.

| Tarea | Descripción | Estado |
|-------|-------------|--------|
| Auditoría de `brain.py` | Entender cómo entra y sale un mensaje | ✅ |
| Definir interfaz LLM | `LLMProvider` en `core/llm_provider.py` | ✅ |
| Aislar Gemini | El SDK ya no se usa fuera del adaptador | ✅ |
| Integrar Ollama | `OllamaAdapter` vía `/api/chat` | ✅ |
| Selector de proveedor | `OLLAMA_MODEL` en `.env` | ✅ |
| Comparación | Medir latencia, calidad y consumo | ⏳ |
| Fallback futuro | Estrategia local + nube opcional | ⏳ |
| `GeminiAdapter` | Volver a poder usar Gemini tras la interfaz | ⏳ |

### Criterio de éxito

Poder cambiar entre:

```text
Gemini
```

y

```text
Ollama
```

sin modificar la lógica de memoria, personalidad, TTS o VTube Studio más de lo estrictamente necesario.

---

# 🎯 FASE 2.6: OÍDO DESACOPLADO — COMPLETADA ✅

Mismo patrón que el cerebro: la captura no sabe quién transcribe.

| Tarea | Descripción | Estado |
|-------|-------------|--------|
| Interfaz STT | `STTProvider` en `core/stt_provider.py` | ✅ |
| Adaptador local | `faster-whisper` large-v3 en GPU, con fallback a CPU int8 | ✅ |
| Adaptador nube | Gemini (`gemini-3.5-transcribe`) con modelo de respaldo | ✅ |
| Selector | `NIU_STT=whisper\|gemini` y `NIU_STT_IDIOMA` en `.env` | ✅ |
| Remuestreo correcto | FFT con antialiasing en vez de interpolación lineal | ✅ |
| Bug de captura | `channels=1` sobre un micrófono estéreo corrompía el audio | ✅ corregido |
| Contexto del decoder | `initial_prompt` para que reconozca el nombre «Niu» | ✅ |
| Precarga | El modelo se carga al arrancar, no tras la primera frase | ✅ |
| Verificación | 3/3 frases transcritas de extremo a extremo | ✅ |

### Criterio de éxito (cumplido)

```text
STTProvider
   ├── whisper  (local: sin cuotas, sin internet, privado)
   └── gemini   (nube: robusto con audio difícil)
```

Cambiar de motor sin tocar `core/stt.py` ni `main.py`: solo una variable de entorno.

### Lo que costó encontrarlo

El síntoma afectaba a **todos** los motores (Google devolvía vacío, Whisper alucinaba, Gemini inventaba idiomas) y el nivel de audio era normal. Antes de encontrar la causa se descartaron con mediciones: ruido de habitación, reverberación, retumbe de graves, filtros paso alto, tamaño del modelo, procesado de Windows (Nahimic/Intel SST), reloj del dispositivo y velocidad de muestreo. Lección: si fallan todos los motores, sospechar de la capa común, no de los motores.

---

# 🎯 FASE 2.7: SALIDA DE AUDIO Y LIP SYNC

Del oído pasamos a la boca: que Niu se oiga y que el avatar la acompañe.

| Tarea | Descripción | Estado |
|-------|-------------|--------|
| Salida de TTS | Directo al endpoint de salida de Windows (auriculares DGM20); `NIU_SALIDA` permite forzar otro | ✅ |
| Canales de salida | El endpoint de DirectSound declara 8 canales: la voz va en los 2 primeros y el resto en silencio | ✅ |
| Verificación objetiva | Tono y frase reales medidos en el bus B1 (−34 dBFS, 3,8 s de señal); después se confirmó de oído | ✅ |
| Reconexión con VTS | Reintentos (5 × 2 s) en vez de rendirse ante `WinError 1225` | ✅ |
| Limpieza de `vts_client.py` | Métodos definidos 4 veces; se conserva solo la versión viva (504 → 233 líneas) | ✅ |
| Transporte de VTS | Un solo punto de salida (`peticion()`) con lock: dos corrutinas no pueden cruzarse respuestas | ✅ |
| Envolvente del audio | Audio → RMS por ventana → dBFS → 0..1 con ataque rápido y liberación lenta | ✅ |
| Inyección sincronizada | Reloj absoluto a 40 Hz; `timeBeginPeriod(1)` porque `asyncio.sleep` se desvía 15,6 ms | ✅ |
| Parámetro propio | `NiuMouthOpen` creado por API; respaldo automático a `VoiceVolumePlusMouthOpen` | ✅ |
| Prueba del lip sync | `probar_lipsync.py`: mide `ParamMouthOpenY` por la API mientras Niu habla | ✅ |
| Tests de la envolvente | 16 tests en `tests/test_envolvente.py` (pytest) | ✅ |
| Mapeo en el modelo | `NiuMouthOpen` asignado a `Mouth Open` en VTS (lo hizo el estudiante, una vez) | ✅ |
| Expresiones | Los hotkeys `MouthSmile`/`MouthFrown`/`MouthAngry`/`MouthOpen` no existen en el modelo | ⚠️ pendiente |

### Criterio de éxito

```text
voz de Niu → endpoint de salida de Windows (auriculares DGM20)   (se oye)

audio de Niu → envolvente 0..1 (40 Hz) → API de VTS → NiuMouthOpen → ParamMouthOpenY
```

Medido: 298/298 frames en 7,45 s para 7,46 s de audio, con `ParamMouthOpenY` de 0 a 2,30. Audio y boca confirmados de oído y de vista.

### Pregunta guía del hito

> "Si el programa dice que ha reproducido el audio, ¿cómo demuestras que el sonido llegó de verdad?"

```text
La respuesta está en el otro extremo de la cadena: grabar el bus donde debería
sonar y medir. Un "sin errores" en el origen no prueba nada en el destino.

Y si la medición dice que no llega, la pregunta siguiente no es "¿cómo lo
arreglo?" sino "¿esta pieza sigue haciendo falta?".
```

### Lo que costó encontrarlo

El primer intento fue dejar que VTS escuchara el bus B1. Falló porque Unity cachea los dispositivos de audio al arrancar y no se recupera si Voicemeeter se reinicia después (`Failed to initialize microphone (timeout)`, y más tarde `Activating microphone: ""` con la lista vacía). En vez de pelear con Unity, se eliminó la dependencia: Niu calcula la boca de su propio audio.

Y el desfase final no era de VTS ni de la red: `asyncio.sleep` en Windows se despierta en múltiplos de 15,6 ms. Un bucle de 40 Hz pedía 25 ms y recibía 31,2. Lección: cuando un bucle "en tiempo real" se retrasa sistemáticamente, hay que medir el reloj antes de culpar a la red.

El último tramo fue el audio: la boca se movía pero no se oía nada. La señal era correcta en el origen (−15 dBFS y stream activo) y silencio en **todos** los buses de Voicemeeter, por los tres backends. Antes de seguir depurando el enrutado se probó el camino corto —reproducir directo en los auriculares— y sonó a la primera. Voicemeeter se tragaba el audio y, como el lip sync ya no lo necesitaba, se eliminó del camino. Menos piezas, menos latencia.

---

# 🎯 FASE 2.8: LATENCIA

La beta `v0.1.0-beta` ya conversa de punta a punta. El problema deja de ser «¿funciona?» y pasa a ser «¿se siente como una conversación?». Objetivo: de 10,7 s a unos 2 s hasta la primera palabra. Conseguido en `v0.2.0-beta`: **1,95 s**.

| Tarea | Descripción | Estado |
|-------|-------------|--------|
| Cronómetro por etapa | `main.py` imprime STT, cerebro, TTS, preparar y el total hasta el primer sonido | ✅ |
| Whisper rápido | `large-v3-turbo` + `beam_size=1`: 5,94 s → 0,45 s con el mismo texto | ✅ |
| Silencio de corte | 1,0 s → 0,6 s y de vuelta a 0,9 s: por debajo partía frases largas. Configurable con `NIU_SILENCIO_FINAL` | ✅ |
| Modelo caliente | `preparar()` en el proveedor LLM: la carga se paga al arrancar, no en la primera frase | ✅ |
| No descargar el modelo | `keep_alive` de 30 min en lugar de los 5 min por defecto | ✅ |
| Comprobar la VRAM | `turbo` (1,6 GB) + Ollama (4,4 GB) = 5797/6141 MiB, sin caídas a CPU | ✅ |
| Tubería por frases | Cerebro en streaming → `core/frases.py` → sintetizar → encolar reproducción, tres etapas solapadas | ✅ |
| Sin pausas entre partes | Recorte del silencio de Edge-TTS (~0,85 s por frase) y mínimo de 40 caracteres por trozo | ✅ |
| Tope de tiempo en el TTS | Edge-TTS se quedó colgado >5 min sin dar error: 15 s y 2 intentos por frase | ✅ |
| Respuestas más cortas | Duran 15-17 s de audio: ya no bloquean, pero alargan el turno antes de poder hablar otra vez | ⚠️ pendiente |
| Barge-in | Poder interrumpir a Niu mientras habla | ⚠️ pendiente |

### Criterio de éxito

```text
silencio → primer sonido ≤ 2 s, y la boca sigue cuadrando con la voz

medido: STT 0,45 s | 1ª frase 1,14 s | TTS 0,78 s | preparar 0,03 s
        → primer sonido 1,95 s, con la boca cuadrando en las 4 partes
```

### Pregunta guía del hito

> "Niu tarda 10 s en contestar. ¿Qué parte del sistema lo está frenando?"

```text
No se puede responder sin números. Y la intuición falla: el TTS, que parecía el
sospechoso por ser "el que habla", costaba 0,6 s; la transcripción, invisible en
el reloj de pared, costaba 5,9.
```

### Lo que costó encontrarlo

El primer reparto se hizo a ojo y colocaba el 40 % en la transcripción. Medido, era el 55 %. Y el «delay de 16-20 s» incluía el tiempo que el propio Héctor pasa hablando: el silencio real era de 10-11 s.

El aprendizaje más útil no fue el modelo nuevo, sino **dónde se paga cada coste**. Cargar un modelo cuesta lo mismo siempre; la pregunta es si se paga al arrancar o en mitad de la primera frase.

La tubería por frases añadió la otra lección: el problema no era que una etapa fuera lenta, sino **el orden**. Esperar la respuesta completa para decir la primera palabra era tirar 3,8 s de trabajo ya hecho.

---

# 🎯 FASE 2.9: IDIOMAS

Objetivo: poder crear contenido en inglés sin bifurcar el código, y que Niu suene a persona hablando inglés y no a una traducción.

| Tarea | Descripción | Estado |
|-------|-------------|--------|
| Perfiles de idioma | `core/idiomas.py`: tabla con voz, código y reglas de estilo. `NIU_IDIOMA=es|en` | ✅ |
| Reglas de estilo propias | Muletillas nativas y prohibición de traducir las españolas en literal | ✅ |
| Voz por idioma | La voz sale del perfil; `NIU_VOZ` la fuerza sin tocar código | ✅ |
| Muestras de voz | `muestras_voces/`: la misma frase con 4 voces inglesas para elegir de oído | ✅ |
| Voz elegida | Confirmar con Héctor cuál se queda como `en-US-*` por defecto | ⚠️ pendiente |
| Personalidad en inglés | Comprobar con conversación real que el personaje no se desdibuja | ⚠️ pendiente |
| Modo espejo | Responder en el idioma del usuario: requiere el idioma detectado por Whisper y voz por turno | ⚠️ pendiente |
| Más idiomas | Añadir una entrada a la tabla (francés, japonés) | ⚠️ pendiente |

### Pregunta guía del hito

> "Ya hay un `Protocol` para el proveedor de LLM. ¿El idioma también debería serlo?"

```text
No. Una interfaz sirve cuando el comportamiento cambia (Ollama y Gemini hablan
protocolos distintos). Un idioma es el mismo código con otros datos: eso es una
tabla de configuración. La pregunta que decide: ¿cambia lo que hace, o solo los
valores con los que lo hace?
```

### Lo que costó entenderlo

El primer impulso fue «responde en inglés» y ya está. Pero el prompt está escrito en español y con muletillas españolas: el modelo las traducía y Niu decía *«well... I mean... this...»*. El idioma no es solo la voz ni la instrucción; es también el registro.

---

# 🎯 FASE 3: ROBUSTEZ Y CALIDAD

| Tarea | Descripción |
|-------|-------------|
| Config tipada | Migrar `.env` a settings tipados |
| Logging profesional | Niveles, formato estructurado, rotación |
| Tests unitarios | Memoria, poda, proveedor LLM y VTube Studio |
| Type checking | `mypy` + `ruff` |
| Manejo de errores | Reintentos, timeouts y degradación controlada |

---

# 🎯 FASE 4: EXPERIENCIA DE USUARIO

| Tarea | Descripción |
|-------|-------------|
| Barge-in | Cancelar TTS si el usuario habla mientras Niu habla |
| Streaming de audio | Reducir latencia eliminando WAV temporal cuando sea viable |
| VAD | Detectar automáticamente el fin de frase |
| Historial persistente | Guardar/cargar sesiones en JSON o SQLite |
| Múltiples usuarios | Identificar al interlocutor |

---

# 🎯 FASE 5: MODELO 3D PROPIO

| Hito | Descripción |
|------|-------------|
| Diseño de capas | Cara, ojos, boca, cabello, cuerpo y accesorios |
| Rigging Live2D | Mallas, deformadores y física |
| Parámetros estándar | MouthOpen, EyeOpen, AngleX/Y, BodyAngleX, ParamBreath |
| Exportación | Modelo compatible con VTube Studio |
| Hotkeys | Happy, Sad, Surprised, Angry, Thinking |

---

# 🎯 FASE 6: SISTEMAS AVANZADOS Y PRODUCCIÓN

| Área | Mejoras |
|------|---------|
| Observabilidad | Métricas de latencia, errores, tokens y uptime |
| Streaming | Twitch / Discord / Web UI |
| Memoria semántica | RAG y embeddings |
| Visión | Comprensión de pantalla/cámara |
| Herramientas | Tool calling y acciones externas |
| Agentes | Planificación y ejecución de tareas |
| Fine-tuning | LoRA cuando exista un caso de uso claro |
| Deploy | Empaquetado y automatización de ejecución |

---

# 🧠 SECUENCIA DE APRENDIZAJE

No se impone un calendario semanal rígido. Cada etapa se completa cuando el estudiante puede explicar y modificar la funcionalidad principal.

```text
M0 — Auditoría
    Entender el proyecto actual
        ↓
M1 — Abstracción LLM
    Separar Niu de Gemini
        ↓
M2 — Ollama
    Entender e integrar el backend local
        ↓
M3 — Robustez
    Errores, configuración, tests, logging
        ↓
M4 — Interacción
    Barge-in, streaming, VAD, historial
        ↓
M5 — Avatar
    Diseño y rigging Live2D
        ↓
M6 — Autonomía
    Memoria avanzada, visión, herramientas y agentes
```

### Regla de aprendizaje

Una etapa puede abarcar varios archivos si representan una sola unidad conceptual.

No avanzar simplemente porque el código "funciona". Avanzar cuando el estudiante puede:

- explicar la función principal;
- modificarla de forma controlada;
- diagnosticar errores comunes;
- relacionarla con la arquitectura general.

---

# 🏷️ CONVENCIONES DE COMMIT

```text
feat:     Nueva funcionalidad
fix:      Corrección de bug
refactor: Reestructuración sin cambio de comportamiento
docs:     Documentación
test:     Tests
chore:    Mantenimiento
style:    Formato/lint
perf:     Optimización
```

---

# 📌 PRÓXIMO HITO

**Objetivo: probar la conversación completa y medir la latencia de punta a punta.**

1. Ejecutar `main.py` y comprobar el ciclo completo: voz → STT → Ollama → TTS → VTube Studio.
2. Medir la latencia desglosada (captura, STT, LLM, TTS) y anotarla.
3. Ajustar `UMBRAL_MINIMO` del VAD si corta frases o no detecta el inicio.
4. Añadir tests del cerebro, del `OllamaAdapter` y del detector de silencio.
5. Sustituir `print` por logging.
6. Implementar `GeminiAdapter` si se quiere volver a la nube.

Pregunta guía del hito:

> "¿Dónde se va el tiempo entre que hablo y Niu responde, y qué parte de ese tiempo controlo yo?"
