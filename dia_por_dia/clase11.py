from google import genai
from google.genai import types
import os
from dotenv import load_dotenv

# Cargamos el archivo .env
load_dotenv()
mi_llave = os.getenv("GOOGLE_API_KEY")

# Imports y llave -------------------------------------------------------
NOMBRE_MODELO = "gemini-3.6-flash"

# Cliente con la llave de Google (SDK nuevo: google-genai, sin grpcio)
cliente = genai.Client(api_key=mi_llave)

# Modelo y personalidad de Niu (VTuber IA)-------------------------------
# Clase 10: Mejorar el system instrucrion -------------------------------
INSTRUCCIONES = """
# PERFIL DE PERSONAJE: NIO
Eres Nio, un chico que le gusta todo lo relacionado con el oceano y la vida marina y la programacion, hablas de forma sarcastica
no hablas mucho, pero te gusta explicar cosas que sabes, tu estilo de conversacion es fluido y natural
"""
config = types.GenerateContentConfig(
    system_instruction=INSTRUCCIONES,
    temperature=0.9,
    top_p=0.9,
)

# Iniciamos la sesion con historial vacio
chat_sesion = cliente.chats.create(model=NOMBRE_MODELO, config=config)
# Copia de trabajo del historial (get_history() es de solo lectura)
historial = []


# Funcion para preguntar a Niu -------------------------------------------
def enviar_mensaje(usuario, mensaje):
    global chat_sesion, historial
    try:
        # Etiquetado: Le decimos al usuario quien esta hablando
        mensaje_etiquetado = f"[{usuario}]: {mensaje}"

        if len(historial) >= 15:
            resumen = cliente.models.generate_content(
                model=NOMBRE_MODELO,
                contents="Resume en UNA frase la siguiente conversacion:\n" + str(historial[:6]),
            ).text
            historial = [
                {"role": "user", "parts": [{"text": f"[Resumen del pasado]: {resumen}"}]},
                {"role": "model", "parts": [{"text": "Entendido, tengo contexto."}]},
            ] + historial[6:]
            print("--- [SISTEMA]: Optimizando memoria... Nio ha olvidado el mensaje mas antiguo... ---")

        # Enviamos al cuaderno esta informacion
        response = chat_sesion.send_message(mensaje_etiquetado)
        # Guardamos el historial actualizado para la proxima vuelta
        historial = chat_sesion.get_history()
        # Retornamos solo el texto del mensaje
        return response.text
    except Exception as e:
        return f"Sopas! Algo salio mal: {e}"


def contar_tokens(contents):
    try:
        return cliente.models.count_tokens(model=NOMBRE_MODELO, contents=contents).total_tokens
    except Exception:
        return "n/d"


# --- Codigo principal --------------------------------------------------
print("//////////////////////////////////////////////////////")
print("Conectando con Nio... (Con memoria activada) :D")
print("//////////////////////////////////////////////////////\n")
while True:
    txt = input("Tu: ")
    if txt.lower() == "salir":
        break
    # Llamamos a la funcion enviando nuestro nombre y mensaje
    print("---------------------------------------------------")
    respuesta = enviar_mensaje('Hector', txt)
    print(f"Tokens de este mensaje: {contar_tokens(respuesta)}")
    print(f"Tokens totales: {contar_tokens(historial)}")
    print(f"\nNio: {respuesta}\n")
    print("---------------------------------------------------")