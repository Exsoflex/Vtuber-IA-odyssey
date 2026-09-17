#Dia 5 - Funciones
def limpiar_texto(texto):
    texto = texto.strip().lower()
    #print(texto) #para verificar lo que se limpio
    return texto

def crear_respuesta(nombre_usuario, mensaje):
    mensaje_limpio = limpiar_texto(mensaje)
    respuesta = {"usuario": nombre_usuario, "respuesta": f"AI dice: Entendi tu mensaje: {mensaje_limpio}"}
    return respuesta

nombre_usuario = input("Cual es tu nombre?")
texto = input("Escribe tu mensaje: ")

print(crear_respuesta(nombre_usuario, texto)["respuesta"])