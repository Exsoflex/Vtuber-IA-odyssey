import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
#-----------------------------------------------------------------------
#Funcion para preguntar a Gemini
def preguntar_a_gemini (pregunta):
    #modelo
    model = genai.GenerativeModel('gemini-1.5-flash')
    #responde en base a lo que se escribio
    try:
        response = model.generate_content(pregunta)
        return response.text
    #si hay un error lo imprime
    except Exception as e:
        print(f"Hubo un error: {e}")

#Codigo principal ---------------------------------------------------------
print("Bienvenid@ al chat con Gemi-ni! :D\nEscribe 'salir' para temrinar.")
while True:
    #se pide al usuario que esriba su mensaje
    entrada = input("Tu: ")
    #si el usuario escribe salir, termina el programa
    if entrada.lower() == "salir":
        print("Byeee! :D")
        break
    #llamamos a la funcion para preguntar a Gemini y la guardamos en una variable
    respuesta = preguntar_a_gemini(entrada)
    #escribimos la respuesta de Gemini en la pantalla
    print(f"Gemi-ni: {respuesta}\n")
    