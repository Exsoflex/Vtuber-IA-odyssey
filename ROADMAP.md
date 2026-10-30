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
| Salida de TTS | `Voicemeeter In 1` no alimenta ninguna tira; el destino es `Voicemeeter Input` | ✅ |
| Canales de salida | El endpoint expone 8 canales: se rellenan con silencio, no se duplican a 2 | ✅ |
| Verificación objetiva | Tono y frase reales medidos en el bus B1 (−34 dBFS, 3,8 s de señal) | ✅ |
| Reconexión con VTS | Reintentos (5 × 2 s) en vez de rendirse ante `WinError 1225` | ✅ |
| Limpieza de `vts_client.py` | Métodos definidos 4 veces; se conserva solo la versión viva (504 → 233 líneas) | ✅ |
| Prueba del lip sync | `probar_lipsync.py`: mide `VoiceVolume` y `ParamMouthOpenY` por la API | ✅ |
| Captura de VTS | El micro de VTS muere con `Failed to initialize (timeout)`; requiere reiniciar VTS | ⚠️ abierto |
| Expresiones | Los hotkeys `MouthSmile`/`MouthFrown`/`MouthAngry`/`MouthOpen` no existen en el modelo | ⚠️ pendiente |

### Criterio de éxito

```text
voz de Niu → Voicemeeter (strip VAIO) → A1 auriculares   (se oye)
                                     → B1 VTube Studio   (mueve la boca)
```

### Pregunta guía del hito

> "Si el programa dice que ha reproducido el audio, ¿cómo demuestras que el sonido llegó de verdad?"

```text
La respuesta está en el otro extremo de la cadena: grabar el bus donde debería
sonar y medir. Un "sin errores" en el origen no prueba nada en el destino.
```

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
