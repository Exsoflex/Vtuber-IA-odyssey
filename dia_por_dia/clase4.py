#Diccionario porporcionado por IA
respuesta_ia = {
    "candidatos": [
        {
            "contenido": {
                "partes": ["¡Hola Rotceh! Soy tu asistente virtual."],
                "rol": "model"
            },
            "puntuacion_seguridad": 0.98
        }
    ],
    "uso_tokens": 45,
}



print(respuesta_ia["candidatos"][0]["contenido"]["partes"][0])
respuesta_ia['modelo'] = "Gemini-1.5-Flash"
print(f'El  modelo {respuesta_ia["modelo"]} uso {respuesta_ia["uso_tokens"]} tokens')
