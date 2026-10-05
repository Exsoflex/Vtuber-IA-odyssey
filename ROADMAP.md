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

El proyecto ahora entra en una etapa de **comprensión, desacoplamiento y robustez**.

---

# 🎯 FASE 2.5: DESACOPLAMIENTO DEL LLM — PRIORIDAD INMEDIATA

La API actual de Gemini no resulta adecuada como único backend para desarrollo continuo. El objetivo no es descartar el trabajo existente, sino convertir el cerebro en una arquitectura independiente del proveedor.

| Tarea | Descripción | Resultado de aprendizaje |
|-------|-------------|--------------------------|
| Auditoría de `brain.py` | Entender exactamente cómo entra un mensaje y cómo sale una respuesta | Leer arquitectura existente |
| Definir interfaz LLM | Diseñar qué necesita realmente Niu de un proveedor | Abstracción / interfaces |
| Aislar Gemini | Mover detalles del SDK fuera del resto del cerebro | Separación de responsabilidades |
| Probar backend Gemini | Confirmar que el comportamiento anterior se conserva | Refactor seguro |
| Integrar Ollama | Crear un proveedor local compatible con la interfaz común | HTTP / JSON / servicios locales |
| Selector de proveedor | Configurar qué backend utilizar | Configuración y arquitectura |
| Comparación | Medir latencia, calidad, estabilidad y consumo | Observabilidad y toma de decisiones |
| Fallback futuro | Diseñar una estrategia local + nube opcional | Arquitectura resiliente |

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

**No continuar con una nueva funcionalidad grande todavía.**

Primero:

1. Auditar `brain.py`.
2. Comprender qué parte es memoria/personality y qué parte es Gemini.
3. Diseñar la frontera entre Niu y un proveedor LLM.
4. Implementar el cambio de forma incremental.
5. Añadir Ollama como segundo proveedor.

El objetivo del siguiente hito es que el estudiante pueda responder con sus propias palabras:

> "¿Qué necesita realmente Niu de un modelo de lenguaje y qué cosas no deberían depender del modelo?"
