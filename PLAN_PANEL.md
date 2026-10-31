# 🛰️ Panel de control de Niu — plan

Estado: **propuesta**. Nada de esto está implementado todavía.
Objetivo: operar a Niu desde una interfaz, cambiar sus ajustes sin editar `.env`
y ver la conversación mientras ocurre.

---

## 1. Qué tiene que resolver

Tres problemas distintos que suelen confundirse en uno:

| # | problema | dificultad real |
|---|---|---|
| 1 | **Operar** el motor: arrancar, parar, saber qué está haciendo | media |
| 2 | **Configurar** sin editar `.env` ni reiniciar Python, con valores por defecto | **alta** |
| 3 | **Ver** la conversación: tu transcripción, el texto de Niu y sus tiempos | baja |

El 2 es el que manda. Si se empieza por la interfaz, se acaba con botones que
escriben variables que nadie vuelve a leer.

---

## 2. El hallazgo que condiciona el diseño

Hoy la configuración se lee **al importar**, no al usar:

| archivo | valores | cuándo se leen |
|---|---|---|
| `core/idiomas.py` | `IDIOMA`, `VOZ`, `tono` | al importar |
| `core/tts.py` | `TONO`, `VELOCIDAD`, `NIU_SALIDA`, `TIMEOUT_TTS` | al importar |
| `core/stt.py` | `SILENCIO_FINAL` | al importar |
| `core/ollama_adapter.py` | `KEEP_ALIVE` | al importar |
| `main.py` | `NIU_MIC`, `IDIOMA_STT` | al importar |
| `core/stt_whisper.py` | modelo, beam, prompt | al construir el proveedor |

Consecuencia: si el panel escribe `NIU_IDIOMA=en` y no reinicia nada, **Niu
sigue en español**. Y `importlib.reload` no sirve: hay estado vivo que no se
puede recargar (modelos en GPU, socket de VTS, hilos de audio).

Por eso el panel no empieza por la interfaz. Empieza por una pieza que todavía
no existe:

```text
.env (secretos)  ─┐
                  ├──▶  core/config.py (Ajustes)  ──▶  cada módulo lee al usarlo
config.json ──────┘                ▲
                                   │
                          panel (REST + WebSocket)
```

**Regla:** un ajuste se lee cuando se usa, no cuando se importa. Los que no
pueden cambiar en caliente (modelo cargado, voz de un audio ya sintetizado) se
marcan en la interfaz como «se aplica al reiniciar el motor», en vez de fingir
que se aplicaron.

---

## 3. Decisiones de arquitectura

### 3.1 Interfaz: web local, no aplicación de escritorio

| opción | por qué no (o sí) |
|---|---|
| Tkinter | cero dependencias, pero estética de 2005 y controles pobres para esto |
| PyQt/PySide | buena, pero 100 MB de dependencia y empaquetado propio |
| Electron / Tauri | un navegador entero para una app local; sobra |
| **Web local (FastAPI + uvicorn)** | **recomendada**: el navegador ya es el renderizador, CSS moderno gratis, y comparte el bucle de `asyncio` con el motor |

Coste: dos dependencias nuevas (`fastapi`, `uvicorn`). Se sirve solo en
`127.0.0.1`, así que Windows no pide permiso de firewall.

### 3.2 Motor y panel en el **mismo proceso**

El panel arranca al instante; el motor es una **tarea** que se inicia con un
botón. Ventajas:

- El chat se alimenta de los mismos fragmentos que van al TTS, sin IPC.
- Cambiar un ajuste y aplicarlo es una llamada a un objeto, no un archivo.
- Un solo bucle de `asyncio`, que es como ya funciona todo.

Riesgo: un fallo del motor no debe tumbar el panel. El motor corre en una tarea
con `try/except` y el error se pinta como mensaje de sistema.

**«Cancelar» significa dos cosas distintas**, y conviene no mezclarlas:

| botón | qué hace | qué libera |
|---|---|---|
| **Detener motor** | cancela la tarea del bucle | micrófono, VTS, la voz en curso |
| **Detener voz** | cancela solo la reproducción (`sd.stop()` + tareas de la tubería) | el audio, no el motor |

### 3.3 Extraer el motor de `main.py`

Hoy `main.py` mezcla el bucle con `print`. El plan es mover el bucle a
`core/motor.py` (`MotorNiu`) con estado y eventos:

```python
class MotorNiu:
    estado: str                       # apagado | iniciando | escuchando | pensando | hablando
    async def iniciar() -> None
    async def detener() -> None
    async def detener_voz() -> None
    # eventos: transcripcion, fragmento, parte, metricas, error, estado
```

`main.py` pasa a ser **un cliente de consola** que se suscribe a esos eventos e
imprime lo mismo que hoy. Así la CLI no se rompe y el panel no duplica lógica.

---

## 4. Qué debe incluir el panel

### 4.1 Ajustes esenciales (10)

Criterio: un ajuste entra si cambia algo que se **oye** o que **se nota** en la
conversación, y si su valor por defecto no es obvio.

| control | variable | tipo | en caliente | por qué está |
|---|---|---|---|---|
| Idioma | `NIU_IDIOMA` | selector es/en | reinicio | cambia voz, reglas y oído a la vez |
| Voz | `NIU_VOZ` | selector (voces del idioma) | reinicio | es la decisión más personal del proyecto |
| Tono | `NIU_TONO` | slider −50…+50 Hz + **Probar** | siguiente frase | se elige de oído, no de memoria |
| Velocidad | `NIU_VELOCIDAD` **(nuevo)** | slider −20…+20 % + **Probar** | siguiente frase | hoy está clavada en `+0%` |
| Micrófono | `NIU_MIC` | selector de entradas + medidor | reinicio | el fallo más frecuente es «no me oye» |
| Salida | `NIU_SALIDA` | selector + **Probar** | siguiente frase | hoy se autodetecta; a veces hay que forzar |
| Modelo LLM | `OLLAMA_MODEL` | selector de `ollama list` | reinicio | cambia carácter y latencia |
| Motor STT | `NIU_STT` | whisper / gemini | reinicio | gemini se deshabilita sin clave |
| Modelo Whisper | `NIU_WHISPER_MODELO` | selector | reinicio | equilibra precisión y VRAM |
| Silencio final | `NIU_SILENCIO_FINAL` | slider 0,3…2,0 s | siguiente turno | decide cuándo Niu cree que terminaste |

### 4.2 Avanzados (3, plegados)

`NIU_TTS_TIMEOUT`, `NIU_TTS_INTENTOS`, temperatura del LLM. Están porque algún
día hacen falta, no porque sean parte del uso normal.

### 4.3 Lo que el panel **no** debe tener

| se queda fuera | por qué |
|---|---|
| `GOOGLE_API_KEY`, `vts_token.txt` | secretos: se muestran como «configurada / no configurada», **nunca** su valor ni un campo editable |
| `NIU_STT_PROMPT` | se deriva del perfil; exponerlo invita a romper el idioma sin entender por qué |
| `NIU_WHISPER_HILOS`, `NIU_WHISPER_BEAM`, `NIU_OLLAMA_KEEP_ALIVE` | decisiones de rendimiento que nadie ajusta a mano; viven en `config.json` si alguna vez hacen falta |
| índices de dispositivos (`[38]`, `[64]`) | nombres, nunca números: los índices cambian al reconectar el USB |
| rutas de archivos temporales | detalle de implementación |
| descarga de modelos / gestión de VRAM | peligroso desde una UI: 350 MB libres en esta GPU |
| editar la personalidad de Niu | el prompt es código y se versiona; no un campo de texto libre |

### 4.4 Vista de chat

- Línea de tiempo con **tú** y **Niu**, hora y texto. El de Niu aparece
  **mientras se escribe** (el mismo stream que alimenta al TTS).
- Chips de métricas por turno: STT, 1ª frase, **primer sonido**, partes, segundos
  hablando, cerebro completo. Es el dato que decide si la conversación se
  siente fluida.
- Caja de texto para escribir (útil si el micrófono está ocupado o para probar
  sin hablar).
- Botones: **Detener voz**, limpiar chat, copiar última respuesta, exportar la
  sesión a Markdown (sirve para preparar contenido).
- Mensajes de sistema: error de VTS, micrófono no encontrado, turno sin
  transcripción.

### 4.5 Funciones que no pediste pero evitan llamadas de soporte

| función | problema que resuelve |
|---|---|
| **Medidor de nivel del micrófono** | «Niu no me oye» se diagnostica en 2 segundos |
| **Probar voz** (sintetiza una frase fija) | elegir voz/tono sin reiniciar el motor |
| **Chips de estado**: motor, Ollama, VTS, micrófono, TTS | saber qué falta sin leer la consola |
| **Logs plegables** (últimas N líneas, filtro por nivel) | dejar de mezclar mensajes técnicos con el texto de Niu |
| **Presets**: «Español», «English content» | cambiar de modo sin tocar 5 campos |
| **Restaurar valores por defecto**, por campo y global | lo pediste explícitamente; por campo evita perder todo |

---

## 5. Estética: espacial, clara y sin ruido

La regla: **el espacio va en el fondo y en los estados; los datos van limpios.**
Nada de animaciones en el chat ni de texto sobre nebulosas.

### 5.1 Paleta

| token | valor | uso |
|---|---|---|
| `--fondo` | `#F6F9FF` | base, blanco con un toque azul |
| `--superficie` | `rgba(255,255,255,.72)` + blur | tarjetas de vidrio |
| `--borde` | `rgba(120,150,255,.18)` | separadores suaves |
| `--tinta` | `#141B2E` | texto principal (contraste AA) |
| `--tinta-suave` | `#5B6478` | etiquetas y horas |
| `--azul` | `#3D7BFD` | acción principal |
| `--indigo` | `#5B5BD6` | énfasis |
| `--violeta` | `#8B5CF6` | acentos, degradados |
| `--menta` | `#2FBF8F` | todo en orden |
| `--ambar` | `#E0A100` | aviso |
| `--coral` | `#E5566A` | error / detener |

Fondo: degradado radial muy suave `#EDF4FF → #F6F9FF` y un campo de estrellas
hecho con `radial-gradient` en CSS, opacidad 0,25 y **sin animación** por
defecto (se activa solo si el sistema no pide movimiento reducido).

### 5.2 Estructura

```text
┌──────────────┬────────────────────────────────┬─────────────────────┐
│  NI U        │  Chat                          │  Ajustes            │
│  ● en línea  │  ┌──────────────────────────┐  │  Idioma  [es ▾]     │
│              │  │ 👤 Tú            12:04   │  │  Voz     [Aria ▾]   │
│  Motor       │  │ Hey Niu, how are you?    │  │  Tono    ─●── +0Hz  │
│  [Iniciar]   │  └──────────────────────────┘  │  [Probar]           │
│  [Detener]   │  ┌──────────────────────────┐  │                     │
│              │  │ 🛰️ Niu           12:04   │  │  Audio              │
│  Estado      │  │ Hey there! I'm...▌       │  │  Mic     [DGM20 ▾]  │
│  Ollama  ●   │  └──────────────────────────┘  │  ▁▃▅▇▅▃▁ medidor   │
│  VTS     ●   │  STT 1.2s · 1ª frase 0.7s ·    │  Salida  [Auric ▾]  │
│  Mic     ●   │  primer sonido 1.9s            │                     │
│  TTS     ●   │                                │  Modelos            │
│              │  [ escribe aquí…        ] [▶]  │  LLM     [qwen ▾]   │
│  [Logs ▾]    │  [Detener voz] [Limpiar] [⤓]   │  Whisper [turbo ▾]  │
└──────────────┴────────────────────────────────┴─────────────────────┘
```

- **Dos columnas + riel**: en pantallas anchas los ajustes están siempre
  visibles; en estrechas pasan a un panel deslizante.
- El indicador de estado es un anillo orbital: gira mientras «piensa», pulsa
  mientras «habla», se queda quieto en «escuchando».
- Los sliders muestran el valor numérico al lado. Un slider sin número es una
  lotería.

### 5.3 Accesibilidad y detalle

- Contraste mínimo AA en texto y controles.
- Foco visible en todo lo interactivo; sliders operables con teclado.
- El estado nunca se comunica **solo** con color: punto + palabra.
- `prefers-reduced-motion` desactiva el campo de estrellas y el anillo orbital.
- Tipografía del sistema (Segoe UI Variable), sin fuentes descargadas: funciona
  sin internet. Números tabulares para las métricas.

---

## 6. Fases de implementación

Cada fase deja el programa funcionando. Ninguna exige reescribir la siguiente.

| fase | entregable | criterio de aceptación | tamaño |
|---|---|---|---|
| **0. Ajustes** | `core/config.py`: dataclass validada, `config.json`, defaults, `restaurar()`; los módulos leen de ahí | los 84 tests siguen verdes y la CLI se comporta igual | 1 sesión |
| **1. Motor** | `core/motor.py` con `iniciar/detener/detener_voz`, estados y eventos; `main.py` como cliente | misma conversación que hoy, con la boca y los tiempos iguales | 1–2 |
| **2. Panel mínimo** | FastAPI + uvicorn en `127.0.0.1`, arrancar/parar, chips de estado | se abre en el navegador y opera el motor | 1 |
| **3. Chat** | WebSocket con fragmentos, transcripción y métricas en vivo | el texto aparece al mismo ritmo que la voz | 1 |
| **4. Ajustes** | las 10 esenciales + avanzados + restaurar + probar voz | cambiar voz y tono desde la UI y oírlo | 1–2 |
| **5. Pulido** | tema espacial, logs, presets, exportar sesión, accesibilidad | revisión con `web-design-guidelines` | 1 |

El orden no es negociable en las fases 0 y 1: son las que evitan que el panel
sea una cáscara bonita sobre valores que no se aplican.

---

## 7. Riesgos y cómo se mitigan

| riesgo | mitigación |
|---|---|
| **Dos fuentes de verdad** (`.env` y `config.json`) | `.env` solo secretos; `config.json` el resto. Al primer arranque se migra y se avisa |
| **VRAM**: 350 MB libres | el panel no usa GPU; cambiar de modelo solo con el motor detenido, y avisando |
| **Parar audio a mitad** | `detener_voz` cancela tareas y llama a `sd.stop()`; se prueba con un TTS lento |
| **El motor cae y tumba el panel** | tarea con `try/except`; el error se muestra como mensaje de sistema |
| **`print` por todas partes** | los eventos del motor son la fuente del chat; el logging estructurado llega en la fase 5 |
| **Firewall de Windows** | escuchar solo en `127.0.0.1` |

---

## 8. Preguntas abiertas

1. **Idioma de la interfaz**: español (para ti y para aprender) o inglés (para
   que coincida con el contenido)? Recomiendo español en la UI y los textos de
   Niu en el idioma del perfil.
2. **Historial entre sesiones**: guardar el chat en disco desde la fase 3 o
   dejarlo en memoria hasta la fase 5?
3. **Acceso desde otro dispositivo** (móvil/tablet en la misma red) o solo
   `localhost`? Cambia el diseño responsive y la seguridad.
