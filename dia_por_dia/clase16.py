from google import genai
import os
from dotenv import load_dotenv


#///////////////////////////////////////////////////////////////////////
# Cargamos el archivo .env ---------------------------------------------
load_dotenv()
# Damos la llave a google
mi_llave = os.getenv("GOOGLE_API_KEY")
#///////////////////////////////////////////////////////////////////////

client = genai.Client(api_key=mi_llave)
response = client.models.generate_content(
    model="gemini-3.6-flash", # ¡Podemos usar las versiones 2.0 o 3.5 con este cliente!
    contents="Hola Niu, ¿estás lista para tu nuevo cuerpo?"
)
print(response.text)