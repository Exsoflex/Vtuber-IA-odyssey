# 🗺️ ROADMAP: NIU AUTONOMOUS ENGINE

## 📍 Estado Actual: FASE 2 COMPLETADA ✅

**Motor base funcional:**
- ✅ Cerebro (Gemini + Memoria + Personalidad)
- ✅ Voz (Edge-TTS anime + winsound)
- ✅ VTube Studio (WebSocket + Auth persistente)
- ✅ Lip-sync (RMS → MouthOpen tiempo real)
- ✅ Expresiones (Keywords → Hotkeys)
- ✅ CLI interactivo (Voz/Texto)

---

## 🎯 FASE 3: ROBUSTEZ Y CALIDAD (Prioridad Alta)

| Tarea | Descripción | Esfuerzo | Dependencias |
|-------|-------------|----------|--------------|
| **Config tipada** | Migrar `.env` → `pydantic-settings` (`Settings` class) | 🟢 Bajo | `pydantic-settings` |
| **Logging profesional** | Reemplazar `print` → `loguru`/`structlog` (niveles, JSON, rotación) | 🟢 Bajo | `loguru` |
| **Tests unitarios** | `pytest` para `brain.py` (memoria, poda), `vts_client.py` (auth, parámetros) | 🟡 Medio | `pytest`, `pytest-asyncio` |
| **Type checking CI** | `mypy` strict + `ruff` en pre-commit / GitHub Actions | 🟡 Medio | `mypy`, `ruff` |
| **Manejo de errores robusto** | Reintentos exponenciales (`tenacity`), timeouts, circuit breaker | 🟡 Medio | `tenacity` |

---

## 🎯 FASE 4: EXPERIENCIA DE USUARIO (Prioridad Media)

| Tarea | Descripción | Esfuerzo | Dependencias |
|-------|-------------|----------|--------------|
| **Barge-in (Interrupción)** | Cancelar TTS si usuario habla mientras Niu habla | 🟡 Medio | `SpeechRecognition` en hilo, `asyncio.Event` |
| **Streaming de audio** | Eliminar archivo WAV temporal → streaming directo a `winsound`/dispositivo | 🟡 Medio | `pyaudio` streaming o `sounddevice` |
| **VAD (Voice Activity Detection)** | Detectar fin de frase automático (silencio > 1.5s) sin `phrase_time_limit` fijo | 🟡 Medio | `webrtcvad` o `silero-vad` |
| **Historial persistente** | Guardar/cargar `mi_historial` en JSON/DB (SQLite) entre sesiones | 🟢 Bajo | `json` / `sqlite3` |
| **Múltiples usuarios** | Identificar speaker (diarización simple o prefijo manual) | 🟡 Medio | Lógica en `brain.py` |

---

## 🎯 FASE 5: MODELO 3D PROPIO (Prioridad Creativa)

| Hito | Descripción | Herramientas |
|------|-------------|--------------|
| **Diseño de capas** | Dibujar Niu en capas separadas (cara, ojos, boca, cabello, cuerpo, accesorios) | Clip Studio Paint / Krita / Photoshop |
| **Rigging Live2D** | Importar PSD → Live2D Cubism Editor → Mallas, deformadores, física | Live2D Cubism Editor (Free) |
| **Parámetros estándar** | `MouthOpen`, `EyeOpen`, `AngleX/Y`, `ParamBreath`, `BodyAngleX` | Live2D |
| **Exportar .model3.json** | Colocar en `Documents/VTubeStudio/Live2DModels/Niu/` | VTube Studio |
| **Hotkeys personalizados** | Crear animaciones: Happy, Sad, Surprised, Angry, Thinking | VTube Studio / Live2D |

---

## 🎯 FASE 6: ESCALABILIDAD Y PRODUCCIÓN (Prioridad Futura)

| Área | Mejoras |
|------|---------|
| **Observabilidad** | Métricas Prometheus/Grafana (latencia, tokens, errores, uptime) |
| **Deploy** | Dockerfile, docker-compose, systemd service para Linux |
| **Multi-plataforma** | Discord bot / Twitch chat integration / Web UI (FastAPI + WebSocket) |
| **Memoria semántica** | RAG con embeddings (conversaciones largas, conocimiento externo) |
| **Fine-tuning** | LoRA en modelo abierto (Gemma/Llama) para personalidad fija sin system prompt |

---

## 📅 Sugerencia de Secuencia de Aprendizaje (Cuando Retomes)

```
Semana 1: Config tipada + Logging + Tests básicos
Semana 2: Barge-in + Streaming audio
Semana 3: Historial persistente + Múltiples usuarios
Semana 4: Live2D - Diseño de capas (arte)
Semana 5: Live2D - Rigging básico (parámetros faciales)
Semana 6: Live2D - Física, respiración, hotkeys
Semana 7: Integración completa + Pulido
```

---

## 🏷️ Convenciones de Commit (Mantener)

```
feat:     Nueva funcionalidad
fix:      Corrección de bug
refactor: Reestructuración sin cambio de comportamiento
docs:     Documentación
test:     Tests
chore:    Mantenimiento (deps, config, lint)
style:    Formato, lint
perf:     Optimización
```

---

## 📌 Notas para la Próxima Sesión

1. **Revisar cuota Gemini** antes de empezar (https://ai.google.dev/gemini-api/docs/rate-limits)
2. **Leer `AGENTS.md`** para recordar metodología de tutoría
3. **Objetivo de la sesión:** Definir 1 sola meta clara (ej: "Agregar logging estructurado")
4. **Tú escribes, yo guío** - línea por línea, con explicación y links a docs
5. **Commit al final** de cada hito funcional