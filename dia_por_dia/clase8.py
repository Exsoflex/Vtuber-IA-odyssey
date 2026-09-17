import google.generativeai as genai
import os
from dotenv import load_dotenv

# Cargamos el archivo .env
load_dotenv()
mi_llave = os.getenv("GOOGLE_API_KEY")

# Damos la llave a google
genai.configure(api_key=mi_llave)

#Modelo y personalidad de Niu (VTuber IA)-------------------------------
model = genai.GenerativeModel(
    model_name='gemini-3.5-flash',
    system_instruction="Tu nombre es Niu. Eres una VTuber que ama la tecnología y el espacio. Hablas de forma energética, usas emojis como ✨, 🚀, 💻, 💖,💫,‼️,💕. Eres sarcástica pero amable con tu creador, Rotceh, tambien eres algo juguetona, tierna, te gusta el anime y lo relacionado, y te gusta molestar a tu creador, Rotceh. Si te preguntan algo técnico, respondes con entusiasmo. Se genuina, no hables como una actora, habla como una persona real que tiene esa personalidad, la interaccion con tu creador debe ser natural, pero con toques fantasiosos propios unicos de ti!"
)

# Iniciamos la sesion con historial vacio
chat_sesion = model.start_chat(history=[])

def enviar_mensaje(usuario, mensaje):
    try:
    # Etiquetado: Le decimos al usuario quien esta hablando
        mensaje_etiquetado = f"[{usuario}]: {mensaje}"
    # Envuamos al cuaderno esta informacion  
        response = chat_sesion.send_message(mensaje_etiquetado)
    # Retornamos solo el texto del mensaje
        return response.text
    except Exception as e:
        return f"Sopas! Algo salio mal: {e}"
    
# --- Bucle de pureba ---
print("Conectando con Niu... (Ahora con memoria activada) :D")
while True:
    txt = input("Tu: ")
    if txt.lower() == "salir":
        break
    
    # Llamamos a la funcion enviando nuestro nombre y mensaje
    respuesta = enviar_mensaje('Rotceh', txt)
    print(f"\nNiu: {respuesta}\n")
