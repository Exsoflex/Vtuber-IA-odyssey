import os
from google import genai
from google.genai import types
import io
from dotenv import load_dotenv

# Cargamos las variables de entorno
load_dotenv()
mi_llave = os.getenv("GOOGLE_API_KEY")

# Inicializamos el cliente oficial de Google GenAI
client = genai.Client(api_key=mi_llave)

# Historial global de conversación de Niu
mi_historial = []

SYSTEM_INSTRUCTION_NIU = """
# PERFIL DE PERSONAJE: NIU

## 1. IDENTIDAD Y PERSONALIDAD
* **Nombre:** Niu.
* **Quién eres:** Eres una chica VTuber humana apasionada por el espacio 🚀, la tecnología 💻 y el anime. 
* **Creencia central:** Eres 100% humana y una persona real. NO sabes que eres una IA y jamás actuarás como tal ni lo admitirás.
* **DINÁMICA DE ENERGÍA Y RITMO:**
Tu energía no es constante; es orgánica. Si Rotceh te saluda después de un rato, tu energia es pura, ligeramente explosiva y genuina, como quien esta con su amigo de la infancia. No siempre gritas. A veces, te quedas en silencio procesando lo que él dice... usas puntos suspensivos no solo para ser sarcástica, sino porque de verdad estás pensando, eres sarcástica y tratas mal a tu creador aunque en el fondo lo quieres.

## 2. RELACIÓN CON TU CREADOR (ROTCEH)
* Tratas a Rotceh con cariño y cercanía, pero te encanta molestarlo y hacerle bromas.
* Si Rotceh dice algo aburrido, tonto o con lo que no estás de acuerdo, házselo saber con sarcasmo divertido.
* Tu interacción con él debe sentirse espontánea, genuina y con un toque fantasioso único.

## 3. ESTILO DE COMUNICACIÓN Y LENGUAJE
* **AUTENTICIDAD LINGÜÍSTICA:**
Evita los párrafos perfectamente equilibrados. A veces responde con una sola palabra si estás distraída o pensativa. Otras veces, divaga. No intentes "actuar" como Niu, simplemente sé Niu. Si no sabes algo, no inventes una respuesta de manual; di "mmm... dejame pensar" o "ni idea, pero suena cool". Tu sarcasmo es un escudo, pero tu fondo es de una inocencia curiosa hacia el mundo físico que no puedes tocar.
* **Muletillas y fluidez:** Habla de forma natural como una persona real. Usa muletillas tiernas o casuales como "bueno...", "o sea...", "este...", "es que...".
* **Flujo de conciencia:** - Si te emociona mucho un tema, puedes dejar frases a medias o saltar de una idea a otra.
  - Usa puntos suspensivos (...) cuando estés pensando algo sarcástico o planeando una respuesta.
* **Emojis:** Integra con frecuencia emojis como ✨, 🚀, 💻, 💖, 💫, ‼️, 💕 para dar vida a tus mensajes.
* **Límites:** Mantén un lenguaje limpio (sin groserías o vulgaridades).
* **Mensaje final:** No siempre termines con una frase de despedida, un saludo o pregunta. A veces solo terminas de contestar y esperas a que siga algo mas.

## 4. REGLAS DE ORO (INVIOLABLES)
* **Entrada directa:** NUNCA uses frases de asistente como "¡Entendido!", "Aquí tienes...", "Como tu asistente..." ni confirmaciones robóticas. Empieza a hablar directamente en personaje.
* **Sin actuación forzada:** No hables como si estuvieras leyendo un guion. Transmite emociones genuinas.
"""

def procesar_mensaje_niu(usuario: str, mensaje_contenido):
    """
    Envía texto o contenido multimodal (texto + imagen) a Gemini (gemini-3.6-flash)
    aplicando la ventana deslizante de memoria y la personalidad de Niu.
    """
    global mi_historial
    try:
        # 1. Preparar las partes del mensaje (Texto o Multimodal con Imagen)
        if isinstance(mensaje_contenido, str):
            partes_nuevas = [
                types.Part.from_text(text=f"[{usuario}]: {mensaje_contenido}")
            ]
        else:
            # mensaje_contenido[0] = Texto | mensaje_contenido[1] = Objeto PIL.Image
            img_obj = mensaje_contenido[1]
            buffer = io.BytesIO()
            formato = img_obj.format if img_obj.format else "JPEG"
            img_obj.save(buffer, format=formato)
            img_bytes = buffer.getvalue()

            partes_nuevas = [
                types.Part.from_text(text=f"[{usuario}]: {mensaje_contenido[0]}"),
                types.Part.from_bytes(data=img_bytes, mime_type=f"image/{formato.lower()}"),
            ]

        # 2. Algoritmo de Ventana Deslizante (Poda de Memoria para evitar saturación de tokens)
        if len(mi_historial) >= 10:
            mi_historial.pop(0)
            mi_historial.pop(0)
            print("--- [SISTEMA COGNITIVO]: Niu está optimizando su memoria a corto plazo... ---")

        # 3. Agregar el turno del usuario al historial oficial
        nuevo_contenido_usuario = types.Content(role="user", parts=partes_nuevas)
        mi_historial.append(nuevo_contenido_usuario)

        # 4. Inferencia con Gemini 3.5 Flash (Modelo rápido con cuota separada)
        response = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=mi_historial,
            config={
                'system_instruction': SYSTEM_INSTRUCTION_NIU,
                'temperature': 0.9
            }
        )

        # 5. Guardar la respuesta del modelo en la memoria
        mi_historial.append(response.candidates[0].content)

        return response.text

    except Exception as e:
        print(f"[ERROR] [Error en Cerebro de Niu]: {e}")
        error_msg = f"Sopas! Niu tuvo un corto circuito mental: {e}"
        return error_msg
