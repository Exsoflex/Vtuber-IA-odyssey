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

**Stack base actual:** Python 3.11+ | `google-genai` | `edge-tts` | `websockets` | `winsound` | `SpeechRecognition`

> Nota arquitectónica: Gemini es el proveedor LLM actualmente integrado, pero ya no debe considerarse una dependencia permanente. La siguiente evolución del proyecto es desacoplar el cerebro del proveedor y permitir un backend local como Ollama.

---

## 🏗️ Arquitectura actual

```text
Vtuber IA odyssey/
├── core/
│   ├── __init__.py
│   ├── brain.py          # Cerebro actual: Gemini + memoria + personalidad
│   ├── tts.py            # Voz: Edge-TTS → WAV
│   └── vts_client.py     # VTube Studio: WebSocket + auth + parámetros + expresiones
├── main.py               # Orquestador: entrada + LLM + TTS + VTS + CLI
├── requirements.txt
├── .env                  # GOOGLE_API_KEY (no versionado)
├── vts_token.txt         # Token VTS persistente (no versionado)
└── dia_por_dia/          # Historial de aprendizaje
```

### Flujo funcional actual

```text
Usuario: voz/texto
        ↓
main.py
        ↓
core/brain.py
        ↓
Gemini + memoria + personalidad
        ↓
respuesta
        ├──────────────→ core/tts.py → WAV → winsound
        │
        └──────────────→ core/vts_client.py → WebSocket → VTube Studio
```

### Estado funcional documentado

- ✅ Cerebro con Gemini y memoria manual.
- ✅ Voz con Edge-TTS.
- ✅ Conexión persistente con VTube Studio.
- ✅ Lip-sync mediante RMS → `MouthOpen`.
- ✅ Expresiones mediante keywords → hotkeys.
- ✅ CLI con entrada de voz/texto.
- ⚠️ El cerebro está acoplado al SDK/proveedor Gemini y debe desacoplarse.
- ⚠️ El proveedor actual presenta límites/cuotas que impiden usarlo de manera confiable para pruebas continuas.

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
| Pendiente | Desacoplar proveedor LLM | Permitir Gemini, Ollama y futuros proveedores sin reescribir el cerebro |

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

El sistema actual depende de Gemini y las pruebas han encontrado respuestas de saturación/cuota. El proyecto necesita una alternativa que permita experimentar continuamente sin depender de la disponibilidad de una API gratuita.

**Objetivo inmediato:** evaluar e integrar un backend local mediante Ollama sin perder el trabajo ya realizado con Gemini, TTS y VTube Studio.

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

### Prioridad de aprendizaje actual

1. Comprender la arquitectura existente antes de modificarla.
2. Aprender a separar la lógica de Niu del proveedor LLM.
3. Entender HTTP/JSON y la comunicación con Ollama.
4. Implementar y probar un backend local.
5. Mejorar progresivamente autonomía para depurar y modificar el sistema.

### Aún no asumir dominio completo de

- Diseño de sistemas complejos.
- Concurrencia avanzada.
- Patrones de arquitectura para aplicaciones orientadas a eventos.
- Sistemas de memoria/RAG avanzados.
- Tool calling y agentes autónomos.
- Optimización avanzada de inferencia local.

---

## 🚧 Deuda técnica conocida

- `brain.py` está fuertemente ligado a Gemini.
- Falta una interfaz común para proveedores LLM.
- Configuración pendiente de migrar a settings tipados.
- Logging profesional pendiente.
- Tests unitarios pendientes.
- Interrupción de TTS pendiente.
- Streaming de audio pendiente.

---

## 📌 Regla para el tutor

Antes de proponer una funcionalidad nueva, comprobar en el código si ya existe.

No enseñar como nuevo algo que esté implementado y dominado.

No asumir que una funcionalidad documentada como "completa" está necesariamente comprendida por el estudiante: distinguir entre **funcionalidad existente** y **conocimiento dominado**.
