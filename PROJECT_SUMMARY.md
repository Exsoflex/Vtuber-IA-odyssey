# 📑 DOCUMENTO TÉCNICO DE ARQUITECTURA Y MIGRACIÓN: PROYECTO "NIU" (v2.5)

**Software:** Niu Autonomous Engine — AI VTuber Cognitive & Multimodal Core  
**Desarrollador Principal:** Rotceh (Estudiante de Desarrollo de Software)  
**Dirección Técnica:** Ing. Aiko  
**Entorno de Ejecución:** Python 3.11.9 (Virtual Environment .venv)  
**Fecha de Consolidación:** Septiembre de 2026

---

## 1. Objetivo General del Software

Desarrollar una **VTuber autónoma e interactiva impulsada por Inteligencia Artificial** ("Niu") capaz de:

1. **Razonar y dialogar:** Mantener conversaciones continuas con memoria persistente, identidad fija (sarcástica, tierna, apasionada por la tecnología/espacio) y reconocimiento de interlocutores (Creador vs. Chat).
    
2. **Interactuar multimodalmente:** Percibir estímulos auditivos (reconocimiento de voz STT) y visuales (análisis de imágenes/pantalla).
    
3. **Expresarse acústicamente:** Sintetizar voz en tiempo real con modulación emocional humana (Gemini Native Audio / Edge-TTS).
    
4. **Animar un avatar virtual:** Conectarse en tiempo real con **VTube Studio** vía WebSockets para sincronización labial (Lip-sync) y control de expresiones corporales.
    

---

## 2. Cronología y Evolución del Código (Días 0 a 18)

|   |   |   |
|---|---|---|
|Fase / Día|Hito Técnico / Contenido Implementado|Estado|
|**Día 0 - 1**|Setup inicial (VS Code, Python). Tipos de datos primitivos, F-Strings, entrada/salida estándar (input/print) y tipado dinámico.|Concluido|
|**Día 2 - 3**|Lógica de bifurcación (if/elif/else), captura de excepciones (try/except), bucles while/for y filtrado con listas (Flags de moderación).|Concluido|
|**Día 4 - 5**|Estructuras complejas: Diccionarios anidados (JSON simulation), funciones modulares (def), parámetros, return y gestión de Scope.|Concluido|
|**Día 6 - 7**|Conexión a Google AI Studio API (google-generativeai). Descubrimiento de modelos (list_models). Creación del System Instruction narrativo de Niu.|Concluido|
|**Día 8 - 10**|Persistencia con ChatSession, etiquetado de usuarios ([Rotceh]:), seguridad con .env (python-dotenv) y humanización del prompt (ritmo orgánico).|Concluido|
|**Día 11 - 12**|Auditoría de tokens (count_tokens). Algoritmo de **Ventana Deslizante** (pop(0) x2) sobre el historial para mitigar latencia y costes acumulativos.|Concluido|
|**Día 13 - 14**|Entrada multimodal visual (PIL.Image). Adición de audición (STT con SpeechRecognition). Diagnóstico y migración de entorno de Python 3.14 a **Python 3.11** para compatibilidad con binarios de PyAudio.|Concluido|
|**Día 15**|**Examen Intermedio:** Unificación de Texto + Voz + Visión + Memoria en un CLI interactivo (match/case).|Concluido|
|**Día 16 - 16.2**|**Refactorización Mayor:** Migración de SDK deprecado a **google-genai** con modelo gemini-3.6-flash. Cumplimiento estricto de Pydantic mediante types.Content, types.Part e inyección binaria con io.BytesIO.|Concluido|
|**Día 17 - 18**|**Módulo de Síntesis Vocal:** Evaluación de Edge-TTS (es-VE-PaolaNeural) y **Gemini Native Audio** (gemini-3.1-flash-tts-preview). Resolución de formato PCM 24kHz crudo a contenedor canónico WAV vía módulo nativo wave. Selección de voces Zephyr y Autonoe.|Concluido|

---

## 3. Arquitectura Actual del Sistema y Tecnologías

codeMermaid

```
graph TD
    subgraph "1. Capa de Percepción y Entradas (Frontend I/O)"
        MIC[Micrófono Hardware] -->|PyAudio + SpeechRecognition| STT[Audio-to-Text es-MX]
        CLI[Consola / Terminal] --> TXT[Texto de Usuario]
        IMG[Archivos Gráficos / Captura] -->|PIL + io.BytesIO| BIN[Buffer Binario de Imagen]
    end

    subgraph "2. Capa de Middleware & Contexto (Local Python 3.11 Core)"
        STT & TXT & BIN --> PRF[Etiquetado Prefijo: 'Rotceh']
        PRF --> TYP[types.Part: from_text / from_bytes]
        TYP --> CNT[types.Content: role='user']
        CNT --> SW{Historial >= 10?}
        SW -->|Sí| POP[Podado: mi_historial.pop 0 x2]
        SW -->|No| MEM[mi_historial List]
        POP --> MEM
    end

    subgraph "3. Capa Cognitiva y Generativa (Google Cloud / GenAI SDK)"
        MEM --> G36[gemini-3.6-flash]
        SYS[System Instruction Narrativa + Temp 0.9] --> G36
        G36 -->|Inferencia Texto| RESP[Texto Generado de Niu]
        RESP -->|Almacenamiento Turno| MEM_OUT[types.Content: role='model']
        MEM_OUT --> MEM
    end

    subgraph "4. Capa de Transducción Acústica (Pipeline de Voz)"
        RESP --> GTTS[gemini-3.1-flash-tts-preview]
        VCFG[Voice: Zephyr / Autonoe] --> GTTS
        GTTS -->|Bytes PCM 24kHz| WAV[wave.open: Envoltura RIFF / Mono / 16-bit]
        WAV --> PLAY[Pygame Mixer Audio Output]
    end

    style G36 fill:#f8bbd0,stroke:#c2185b
    style GTTS fill:#b2dfdb,stroke:#004d40
    style MEM fill:#fff9c4,stroke:#fbc02d
    style PLAY fill:#c8e6c9,stroke:#2e7d32
```

### Matriz de Dependencias y Modelos:

- **Lenguaje & Entorno:** Python 3.11.9 (.venv)
    
- **SDK Principal:** google-genai (v0.1.x+)
    
- **Modelo de Razonamiento:** gemini-3.6-flash
    
- **Modelo de Síntesis Vocal:** gemini-3.1-flash-tts-preview (Alternativa ligera: edge-tts con es-VE-PaolaNeural)
    
- **Gestión de Hardware/Audio:** SpeechRecognition, PyAudio, pygame, wave, io, PIL (Pillow), python-dotenv.
    

---

## 4. Últimas Decisiones Críticas de Código Tomadas

1. **Gestión Manual de Historial:** Se abandonó la clase client.chats.create en favor de una lista local de objetos types.Content. Esto otorga control absoluto sobre el algoritmo de poda (Sliding Window) y elimina los fallos de atributos inexistentes (AttributeError: 'Chat' object has no attribute 'history').
    
2. **Serialización In-Memory de Imágenes:** Eliminación de métodos inexistentes (from_image). Se implementó io.BytesIO para extraer el stream binario de cualquier objeto PIL.Image y pasarlo canónicamente como types.Part.from_bytes(data, mime_type).
    
3. **Desacoplamiento Cerebro-Locutor (Pipeline en Cascada):** Se determinó que los modelos -tts-preview rechazan configuraciones de system_instruction (Developer Instructions). La personalidad reside exclusivamente en gemini-3.6-flash, y el texto procesado se envía limpio al motor acústico.
    
4. **Corrección de Contenedor de Audio:** Los streams nativos de Gemini entregan PCM crudo (24kHz, 16-bit, Mono). Se implementó el empaquetado mediante wave.open para inyectar cabeceras estándar RIFF/WAVE requeridas por los reproductores del sistema (pygame/SDL_mixer).
    

---

## 5. Tareas Pendientes y Próximos Pasos (Mes 2 - Semana 6+)

### A. Tareas y Correcciones Inmediatas (Refinamiento):

**Ajuste de Umbral Auditivo:** Calibrar energy_threshold, pause_threshold (1.8s - 2.0s) y phrase_time_limit en SpeechRecognition para evitar cortes involuntarios durante pausas naturales del habla.

**Captura Visual Dinámica:** Sustituir la carga estática de rutas (input("pingu.jpg")) por captura de pantalla en tiempo real con mss (para videojuegos/escritorio) o streaming de webcam con OpenCV.

**Enrutamiento de Voz Bilingüe:** Implementar selector condicional para alternar automáticamente entre timbres en español y modelos fonéticos en inglés según el idioma detectado en la respuesta.

### B. Módulo Central de Integración (El Esqueleto Virtual):

**Cliente WebSocket para VTube Studio API:** Construir el script en Python para autenticación y envío de eventos al puerto local de VTube Studio (puerto por defecto 8001).

**Sincronización Labial en Vivo (Lip-sync):** Analizar la amplitud/frecuencia del buffer de audio generado (RMS / Fast Fourier Transform) y mapearlo a los parámetros de Live2D (MouthOpen, MouthForm).

**Disparador de Expresiones:** Extraer etiquetas contextuales de la respuesta de Gemini (ej. [FELIZ], [SARCASMO], [SORPRESA]) para activar animaciones/hotkeys en el modelo de VTube Studio.