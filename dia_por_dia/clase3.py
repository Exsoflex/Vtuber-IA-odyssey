print('Sistema de moderacion para el canal!\n')
palabras_prohibidas = ['malo', 'tonoto', 'spam', 'buu']

mensaje_limpio = True
primer_mensaje = True
while mensaje_limpio == True:

    if primer_mensaje == True:
        mensaje = input('Escribe tu primer mensaje en el chat!: ')
        primer_mensaje = False
    else:
        mensaje = input('Escribe tu siguiente mensaje en el chat!: ')
    
    for palabra in palabras_prohibidas:
        
        if palabra in mensaje:
            mensaje_limpio = False
            print("\nTu mensaje contiene palabras prohibidas :[ \npor favor, mantengamos un ambiente amigable ':)")
            break
    if mensaje_limpio == True:
            print('Mensaje enviado! sigue chateando ;]\n')

