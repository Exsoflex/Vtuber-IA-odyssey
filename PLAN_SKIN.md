# 🎨 La skin de Niu — guía paso a paso

Estado: **pendiente de hacer**. Este documento es la ruta que se decidió seguir
y el contrato técnico entre el avatar y el código.

Decisión de la sesión: **Live2D 2D**, no 3D. El porqué está en el apartado 1;
no es una preferencia estética, sale de lo que el programa ya sabe hacer.

---

## 1. Por qué 2D y no 3D

No es «el 2D es más fácil». Es que el proyecto ya está construido sobre
VTube Studio, y VTube Studio **solo** entiende Live2D.

| | 2D + Live2D | 3D + Blender |
|---|---|---|
| Avatar que admite VTS | ✅ Live2D | ❌ VTS no carga VRM |
| Backend de avatar | ✅ El que ya existe (`core/vts_client.py`) | ❌ VRM + VSeeFace/Warudo + protocolo VMC: otro proveedor entero |
| Lip sync | ✅ `NiuMouthOpen` → `ParamMouthOpenY` | ❌ Mandíbula con blendshape y otro protocolo |
| Expresiones | ✅ Hotkeys por nombre | ❌ Otro sistema de morphs |
| Habilidad que ya tienes | ✅ Dibujar 2D | ❌ Modelado, retopología, texturizado, rig 3D |
| Tiempo hasta ver a Niu viva | Semanas | Meses |

Lo difícil de un VTuber 2D es **dibujar bien**, y eso ya lo sabes hacer. Lo que
falta es el rigging, que se aprende con los tutoriales oficiales.

El 3D no se descarta: sería una fase futura detrás de una interfaz de avatar
(igual que se hizo con los proveedores de LLM). Pero hoy no aporta nada.

---

## 2. El contrato: qué espera el programa de tu modelo

Esta es la parte que no es negociable. El código hace cosas concretas con el
modelo y, si el modelo no las tiene, Niu se queda muda o neutra **sin decir por
qué**.

| Lo que hace el código | Dónde | Qué necesita el modelo |
|---|---|---|
| Inyecta la apertura de boca | `core/lipsync.py` (`PARAMETRO_BOCA = "NiuMouthOpen"`) | Un parámetro Live2D estándar `ParamMouthOpenY`, rango 0..1 |
| Comprueba que la boca se mueve | `core/lipsync.py` (`PARAMETRO_LIVE2D`) | Que `ParamMouthOpenY` exista y responda |
| Pide una expresión | `core/motor.py` (`EXPRESIONES_NIU`) | Cuatro hotkeys con estos nombres exactos: `MouthSmile`, `MouthOpen`, `MouthFrown`, `MouthAngry` |
| Avisa de lo que falta | `core/motor.py` (`_comprobar_hotkeys`) | Los hotkeys deben llamarse así, con mayúsculas y minúsculas como están |
| VTS renderiza el modelo | VTube Studio | **Cubism 3 o superior**: `.model3.json` + `.moc3` |

### Parámetro no es hotkey (el error que más veces se comete)

Son dos cosas distintas y se confunden todo el rato:

| | Parámetro | Hotkey |
|---|---|---|
| Qué es | Un valor continuo 0..1 que deforma el dibujo | Una **acción** guardada en VTS |
| Ejemplos | `ParamMouthOpenY`, `ParamMouthForm`, `ParamEyeLOpen` | «Sonreír», «Lanzar animación» |
| Dónde se ve | Lista de parámetros del modelo | Pestaña **Hotkeys** de VTS |
| Quién lo mueve | El tracking, o un plugin por mapeo | Niu lo **dispara por nombre** |
| Lo que crea Niu | `NiuMouthOpen` (mapeado a `ParamMouthOpenY`) | Nada: usa los que ya existan |

Que el modelo tenga `ParamMouthOpenY` **no** significa que exista el hotkey
`MouthSmile`. Si Niu dice «el modelo no tiene el hotkey», revisa la pestaña
**Hotkeys**, no la de parámetros.

### El mapeo de la boca (el paso que más se olvida)

El lip sync de Niu **no** usa el micrófono de VTS. Niu calcula la apertura de
boca desde su propio audio y la inyecta en un parámetro de *tracking* propio,
`NiuMouthOpen`. Ese parámetro hay que **mapearlo** a `ParamMouthOpenY` dentro
de VTube Studio:

```text
VTube Studio → Configuración de parámetros del modelo
    → «Mouth Open» → cambiar la entrada a «NiuMouthOpen» → Guardar
```

Es un ajuste que se hace una vez y VTS lo recuerda con el modelo. Si no se
hace, el código cae al respaldo `VoiceVolumePlusMouthOpen`, que **sí** funciona
pero deja que el micrófono de VTS también mueva la boca: cualquier música o
cualquier otra voz del sistema abre la boca de Niu.

La prueba de que el mapeo está bien no es leer un archivo de configuración: es
inyectar 0, medir, inyectar 1, medir y ver que la apertura cambia. Eso es
justo lo que hace `probar_lipsync.py`.

---

## 3. Ruta de trabajo (5 fases, en este orden)

El orden importa. La fase 0 evita el escenario que te preocupaba: gastar diez
horas dibujando y descubrir después que el programa no puede mover esa skin.

### Fase 0 — Validar el pipeline sin dibujar nada ⏱️ 1 tarde

**Objetivo:** comprobar que el programa controla un avatar Live2D, antes de
invertir horas en un dibujo.

1. Descarga un modelo de ejemplo **gratuito** de Live2D:
   <https://www.live2d.com/en/learn/sample/> — para empezar, el
   [Simple model](https://www.live2d.com/en/learn/sample/simple-model/), que
   es el pensado para principiantes.
2. Cópialo a la carpeta de modelos de VTube Studio
   (`StreamingAssets/Live2DModels/NombreDelModelo/`) y cárgalo en VTS.
3. Arranca el panel (`python -m panel`) y comprueba que el chip de VTS se pone
   verde.
4. Mapea la boca: `NiuMouthOpen` → `ParamMouthOpenY` (apartado 2).
5. Corre la prueba de la boca:
   ```powershell
   .venv\Scripts\python.exe probar_lipsync.py
   ```
   Debe decir «✅ La boca se abre y se cierra». **Si esto falla, no sigas:
   el problema está en el mapeo, no en tu dibujo.**
6. Crea en VTS cuatro hotkeys de tipo «Toggle Expression» (o «Trigger
   Animation») con los nombres exactos `MouthSmile`, `MouthOpen`,
   `MouthFrown`, `MouthAngry`, cada uno apuntando a una expresión del modelo de
   ejemplo. Si el modelo de ejemplo no trae expresiones (Hiyori, por ejemplo,
   no trae ninguna), renombra dos de sus hotkeys de animación a `MouthSmile` y
   `MouthOpen`: sirve igual para comprobar que el pipeline funciona.
7. Comprueba los hotkeys con el script de diagnóstico:
   ```powershell
   .venv\Scripts\python.exe probar_expresiones.py
   ```
   Lista los hotkeys del modelo y dispara los cuatro que Niu necesita, sin
   tener que hablarle.
8. Arranca Niu y dile algo que contenga «feliz» o «triste». La cara del modelo
   de ejemplo debe cambiar.

**Qué decides al final:** si los pasos 5 y 8 funcionan, el 100 % del código de
avatar está validado. Puedes dibujar con confianza.

### Fase 1 — Aprender el rigging con un personaje de práctica ⏱️ 2-4 tardes

**Objetivo:** no aprender a hacer *la skin de Niu*, sino a hacer *un modelo
Live2D*. Sale más barato practicar con el arte de los tutoriales.

Haz el tutorial oficial «Live2D by diagrams» y el de la boca A-I-U-E-O, que
son cortos y están en español y otros idiomas. Después el tutorial básico de
6 partes.

Lo que te llevas de esta fase **no es el modelo**: es saber cómo tiene que
estar dividido el PSD para poder deformarlo. Ese conocimiento decide cómo
dibujas la fase 2, y por eso va antes.

### Fase 2 — Dibujar la skin de Niu ⏱️ depende de ti

**Objetivo:** el arte final, con las capas ya separadas como las pida el
rigging.

Reglas para el PSD (esto es lo que la fase 1 te enseñó):

- Una capa por elemento deformable. Pelo de delante, pelo de detrás, cada
  mechón que se mueva es una capa.
- Los ojos: iris, esclera, párpado superior, párpado inferior y cejas
  separados.
- La boca: Labio superior, Labio inferior, Interior de la boca y dientes
  separados. La boca es la parte que más se nota si está mal.
- Deja el pelo de la cara y el cuerpo en capas aparte de la ropa.
- Resolución y color: no uses color plano en las zonas que se van a
  transparentear; usa degradados suaves.
- **Aplica los tutoriales de física (hair physics) y de draw order** para que
  el pelo caiga de forma natural.

### Fase 3 — Rigging en Cubism ⏱️ 1-2 semanas (con práctica)

**Objetivo:** que el modelo se pueda mover.

Lo mínimo para que Niu funcione:

| Qué | Cómo |
|---|---|
| Malla y deformadores | Malla automática en las capas; deformadores de rotación y warp donde toque |
| Parámetro de boca | `ParamMouthOpenY` (0..1) en la malla de la boca, con al menos la forma de cerrada y la de abierta. El tutorial A-I-U-E-O es justo esto |
| Parámetros de ojos | `ParamEyeLOpen`, `ParamEyeROpen` (0..1) para que VTS parpadee solo |
| Angle X / Angle Y | `ParamAngleX`, `ParamAngleY` para que VTS la incline con la cara |
| Respiración | `ParamBreath` (0..1) para que no se vea congelada al callar |
| Expresiones | Crea archivos `.exp3.json`: sonrisa, sorpresa, tristeza, enfado |
| Física | Física de pelo y ropa (tutorial oficial de física) |

Sobre la boca: el lip sync de Niu manda **40 valores por segundo** en un rango
0..1 continuo. Si la boca solo tiene dos imágenes (abierta/cerrada) que se
intercambian, se verá a saltos. La forma correcta es una malla que se deforma:
el tutorial de A-I-U-E-O existe precisamente para eso.

### Fase 4 — Exportar y conectar ⏱️ 1 tarde

**Objetivo:** que VTS cargue el modelo y Niu lo controle.

1. En Cubism: **File → Export for Embedded Use → Export as moc3**.
2. Comprueba que se exportan: `.model3.json`, `.moc3`, las texturas `.png` y
   los `.exp3.json` de las expresiones.
3. Copia **toda** la carpeta a `StreamingAssets/Live2DModels/` de VTube Studio.
4. Carga el modelo en VTS y configura:
   - El mapeo de boca del apartado 2.
   - Los cuatro hotkeys con los nombres exactos.
5. Verifica:
   ```powershell
   .venv\Scripts\python.exe probar_lipsync.py
   ```
   y luego una conversación en el panel, buscando que la expresión cambie.

---

## 4. Checklist final (marcado solo cuando esté comprobado)

### En el PSD

- [ ] Pelo dividido en capas (delante, medio, detrás, mechones sueltos)
- [ ] Ojos: esclera, iris, párpado superior, párpado inferior, cejas
- [ ] Boca: labio superior, labio inferior, interior, dientes
- [ ] Sin colores planos en zonas que se van a transparentear
- [ ] Resolución de textura suficiente para el tamaño final

### En Cubism

- [ ] `ParamMouthOpenY` (0..1) con malla deformable, no dos imágenes
- [ ] `ParamEyeLOpen` / `ParamEyeROpen` (0..1)
- [ ] `ParamAngleX` / `ParamAngleY`
- [ ] `ParamBreath`
- [ ] 4 expresiones exportadas (sonrisa, sorpresa, tristeza, enfado)
- [ ] Física de pelo configurada
- [ ] Exportado como `.moc3` + `.model3.json`

### En VTube Studio

- [ ] Modelo cargado y visible
- [ ] Mapeo `NiuMouthOpen` → `ParamMouthOpenY` guardado
- [ ] Hotkey `MouthSmile` → expresión de sonrisa
- [ ] Hotkey `MouthOpen` → expresión de sorpresa
- [ ] Hotkey `MouthFrown` → expresión de tristeza
- [ ] Hotkey `MouthAngry` → expresión de enfado
- [ ] `probar_lipsync.py` dice «✅ La boca se abre y se cierra»
- [ ] `probar_expresiones.py` dice «✅ Los cuatro hotkeys existen y se disparan»
- [ ] En una conversación, la expresión cambia

### En Niu

- [ ] Al arrancar, Niu **no** avisa de hotkeys que falten (si avisa, es que
      falta alguno: el mensaje va al chat del panel)

---

## 5. Límites de Cubism FREE (la versión que te basta)

Comprobados en la
[tabla oficial FREE vs PRO](https://www.live2d.com/en/cubism/comparison/):

| Recurso | FREE | PRO |
|---|---|---|
| Texturas por modelo | 1 (hasta 2048 px) | Sin límite |
| ArtMesh | 100 | Sin límite |
| Parámetros de movimiento | 30 | Sin límite |
| Parámetros de blend shape | 3 | Sin límite |
| Deformadores | 50 | Sin límite |
| Partes (carpetas) | 30 | Sin límite |
| Divisiones de warp deformer | 9 × 9 | 100 × 100 |

Un personaje de estilo anime normal cabe de sobra: 1 textura de 2048, menos de
100 capas, menos de 30 parámetros. Si te quedas corto, PRO tiene **prueba de
42 días** (https://www.live2d.com/en/cubism/download/editor/).

Sobre la licencia: FREE permite uso comercial solo por particulares y empresas
pequeñas (ventas anuales < 10 M de yenes). Un proyecto personal está
cubierto. Si algún día Niu generase ingresos, eso ya es otra pregunta.

---

## 6. Recursos oficiales

Todos verificados y actualizados a enero de 2026.

### Tutoriales (este es el orden que funciona)

1. [Live2D by diagrams](https://docs.live2d.com/en/cubism-editor-tutorials/figure/)
   — el más rápido para entender el qué de cada cosa. Hay PSD de práctica.
2. [Parpadeo en 10 minutos](https://docs.live2d.com/en/cubism-editor-tutorials/eye-blink/)
3. [Boca A-I-U-E-O en 20 minutos](https://docs.live2d.com/en/cubism-editor-tutorials/mouth-aiueo/)
   — el más importante para Niu: es exactamente lo que necesita la boca.
4. [Tutorial básico, 6 partes](https://docs.live2d.com/en/cubism-editor-tutorials/top/)
   — ilustración → importar → expresiones → movimiento del cuerpo → XY →
   animaciones.
5. [Física](https://docs.live2d.com/en/cubism-editor-tutorials/physical-calculation-settings/)
   y [exportar para uso embebido](https://docs.live2d.com/en/cubism-editor-tutorials/exporting-data-for-embedding/)
6. [Vídeo de creación del modelo de muestra Jin Natori](https://docs.live2d.com/en/cubism-editor-tutorials/natori_making/)
   — el proceso completo de principio a fin, muy útil como referencia.

### Referencias

- [Manual del Cubism Editor](https://docs.live2d.com/en/cubism-editor-manual/top/)
  — para cuando una función concreta no esté en los tutoriales.
- [Modelos de muestra gratuitos](https://www.live2d.com/en/learn/sample/)
- [API de VTube Studio](https://github.com/DenchiSoft/VTubeStudio) — el README
  oficial. Los nombres de los mensajes (`HotkeyTriggerRequest`,
  `HotkeysInCurrentModelRequest`, `ParameterCreationRequest`…) salen de ahí.
- [Live2D JUKU](https://juku.live2dcs.jp/en/) — cursos oficiales en vídeo
  (principalmente en japonés).

---

## 7. Problemas frecuentes

**La boca no se mueve.**
No es el modelo: es el mapeo. `NiuMouthOpen` no está conectado a
`ParamMouthOpenY` en VTS. Comprueba el apartado 2 y corre `probar_lipsync.py`.

**La boca se mueve con la música del sistema.**
Estás usando el respaldo `VoiceVolumePlusMouthOpen`, que VTS alimenta con su
micrófono. Mapea `NiuMouthOpen` a propósito.

**Niu habla pero la cara no cambia.**
Falta el hotkey o no se llama exactamente igual. Ojo: que el modelo tenga el
parámetro `ParamMouthOpenY` no significa que tenga el hotkey `MouthSmile`.
Corre `probar_expresiones.py`: lista los hotkeys que hay de verdad y prueba
los cuatro que Niu necesita.

**VTS no responde al mover la boca.**
VTube Studio responde en su siguiente frame de render, no al recibir. Es lo
normal; no es un fallo.

**El modelo no aparece en VTS.**
Comprueba que la carpeta tenga el `.model3.json` y el `.moc3` **juntos** y que
la carpeta esté en `StreamingAssets/Live2DModels/`. Un modelo de Cubism 2
(`.model.json`) no se carga.

**El hotkey no se dispara aunque el nombre exista.**
VTS compara el nombre sin distinguir mayúsculas, pero con el nombre completo.
Si hay dos hotkeys con el mismo nombre, solo se ejecuta el primero. Y un mismo
hotkey no se puede disparar más de una vez cada 5 frames: si Niu pide
expresiones seguidas, se encolan (la cola admite 32).

---

## 8. Lo que este documento cubre y lo que no

Cubre: la ruta, el contrato con el código, la checklist y dónde está cada
tutorial oficial.

No cubre: el arte en sí (eso es tuyo), ni la explicación pausada de cada
función de Cubism (para eso está el manual oficial), ni un 3D futuro (que
requeriría rehacer la capa de avatar).
