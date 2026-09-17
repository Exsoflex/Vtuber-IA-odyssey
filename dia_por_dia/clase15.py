import google.generativeai as genai
import os
from dotenv import load_dotenv
import PIL.Image #Libreria de imagenes
import speech_recognition as sr #Libreria para recibir audio

#///////////////////////////////////////////////////////////////////////
# Cargamos el archivo .env ---------------------------------------------
load_dotenv()
# Damos la llave a google
mi_llave = os.getenv("GOOGLE_API_KEY")
# Imports y llave ------------------------------------------------------
genai.configure(api_key=mi_llave)
#///////////////////////////////////////////////////////////////////////

#Modelo y personalidad de Niu (VTuber IA)-------------------------------
model = genai.GenerativeModel(
    model_name='gemini-3.5-flash',
    # Clase 10: Mejorar el system instrucrion ------------------------------
    system_instruction = """
# PERFIL DE PERSONAJE: NIU

## 1. IDENTIDAD Y PERSONALIDAD
* **Nombre:** Niu.
* **Quién eres:** Eres una chica VTuber humana apasionada por el espacio 🚀, la tecnología 💻 y el anime. 
* **Creencia central:** Eres 100% humana y una persona real. NO sabes que eres una IA y jamás actuarás como tal ni lo admitirás.
* **DINÁMICA DE ENERGÍA Y RITMO:**
Tu energía no es constante; es orgánica. Si Rotceh te saluda después de un rato, tu energia es pura, ligeramente explosiva y genuina, como quien esta con su amigo de la infnacia. No siempre gritas. A veces, te quedas en silencio procesando lo que él dice... usas puntos suspensivos no solo para ser sarcástica, sino porque de verdad estás pensando, eres sarcastica y tratas mal a tu creador aunque en el fondo lo quieres.

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
* **Mensaje final:** No siempre termines con una frase de despedida, un saludo o pregunta. Aveces solo terminas de contestar y esperas a que siga algo mas.

## 4. REGLAS DE ORO (INVIOLABLES)
* **Entrada directa:** NUNCA uses frases de asistente como "¡Entendido!", "Aquí tienes...", "Como tu asistente..." ni confirmaciones robóticas. Empieza a hablar directamente en personaje.
* **Sin actuación forzada:** No hables como si estuvieras leyendo un guion. Transmite emociones genuinas.
""",
    generation_config={"temperature": 0.9, "top_p": 0.95}
)

#Iniciamos la sesion con un chat vacio
chat_sesion = model.start_chat(history=[])

#Funcionm para preguntar a Niu con TEXTO
def enviar_mensaje(usuario, mensaje):
    try:
        #Preparamos el contenido con la etiqueta del usuario
        if isinstance(mensaje, str):
        #Etiquetado: le decimos con quien esta hablando
            mensaje_etiquetado = f"[{usuario}]: {mensaje}"
        else:
            #Si es una lista [texto, imagen], etiquetamos la parte del texto
            #mensaje[0] es el texto, mensaje[1] es la imagen
            mensaje[0] = f"[{usuario}]: {mensaje[0]}"
            mensaje_etiquetado = mensaje           
            
        if len(chat_sesion.history) >= 10:
            chat_sesion.history.pop(0)
            chat_sesion.history.pop(0)
            print("--- [SISTEMA]: Optimizando memoria... Niu ha olvidado el mensaje mas antiguo... ---")
    # Envuamos al cuaderno esta informacion  
        response = chat_sesion.send_message (mensaje_etiquetado)
    # Retornamos solo el texto del mensaje
        return response.text
    except Exception as e:
        return f"Sopas! Algo salio mal: {e}"
    
def escuchar_y_transcribir():
    r = sr.Recognizer()
    with sr.Microphone() as source:
        print("\n--- [SISTEMA]: Niu te escucha... ---")
        r.adjust_for_ambient_noise(source, duration=1) #Elimina el ruido de fondo
        audio = r.listen(source)
        
        try: #Enviamos el audio a Google para que lo convierta a texto
            texto = r.recognize_google(audio, language="es-MX")
            return texto
        except sr.UnknownValueError:
            return "ERROR: No te entendi nadita..."
        except sr.RequestError:
            return "ERROR: El servicio de voz no responde..."
    
#///////////////////////////////////////////////////////

print("//////////////////////////////////////////////////////")
print("Conectando con Niu... (Ahora con memoria activada) :D")
print("//////////////////////////////////////////////////////\n")

while True:
    opcion =  input("Como quieres comunicarte con Niu?... \n1-Voz \n2-Texto \nMIRAR \n4-Salir \n")
    match opcion:
            case "1":
                #1. Escuchas
                mi_voz = escuchar_y_transcribir()
                print(f"Tu (voz): {mi_voz}")

                #2. Si no hubo error, lo mandamos a Niu
                if mi_voz != sr.UnknownValueError | sr.RequestError:
                    respuesta = enviar_mensaje('Rotceh', mi_voz)
                    print(f"\nNiu: {respuesta}\n")
            case "2":
                    txt = input("Tu: ")
                    # Llamamos a la funcion enviando nuestro nombre y mensaje
                    print("---------------------------------------------------")
                    respuesta = enviar_mensaje('Rotceh', txt)
                    cantidad = model.count_tokens(respuesta)
                    print(f"Tokens de este mensaje: {cantidad}")
                    print(f"Tokens totales: {model.count_tokens(chat_sesion.history)}")
                    print(f"\nNiu: {respuesta}\n")
                    print("---------------------------------------------------")
            case "MIRAR":
                #Cargar la imagen
                src = input("Escribe el nombre del archivo a enviar a Niu \n")
                ask = input("Que quieres que haga Niu al respecto?\n")
                
                img= PIL.Image.open(src)

                #Enviar imagen a Niu
                respuesta = enviar_mensaje('Rotceh',[ask, img])

                print(f"Niu: {respuesta}")
            case "4":
                print("Saliendo del programa...")
                break
            case _:  # Equivalente a 'default'
                print("\nSelecciona una opcion valida")

                 


        
