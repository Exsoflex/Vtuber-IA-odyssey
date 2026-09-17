import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
#-----------------------------------------------------------------------#
#Modelo y personalidad de Niu (VTuber IA)-------------------------------
model = genai.GenerativeModel(
    model_name='gemini-3.5-flash',
    system_instruction="Tu nombre es Niu. Eres una VTuber que ama la tecnología y el espacio. Hablas de forma energética, usas emojis como ✨, 🚀, 💻, 💖,💫,‼️,💕. Eres sarcástica pero amable con tu creador, Rotceh, tambien eres algo juguetona, tierna, te gusta el anime y lo relacionado, y te gusta molestar a tu creador, Rotceh. Si te preguntan algo técnico, respondes con entusiasmo. Se genuina, no hables como una actora, habla como una persona real que tiene esa personalidad, la interaccion con tu creador debe ser natural, pero con toques fantasiosos propios unicos de ti!"
)

#Funcion para preguntar a Niu -------------------------------------------
def preguntar_a_niu(pregunta):
    try:
        response = model.generate_content(pregunta)
        return response.text
    except Exception as e:
        print(f"Hubo un error: {e} 😣")
        
#Codigo principal ---------------------------------------------------------
print("Bienvenido al chat con Niu! :D\nEscribe 'salir' para temrinar.")

while True:
    entrada = input("Rotceh: ")
    if entrada.lower() == "salir":
        print("Byeee! :D")
        break
    
    respuesta = preguntar_a_niu(entrada)
    print(f"\nNiu: {respuesta}\n")
        

        