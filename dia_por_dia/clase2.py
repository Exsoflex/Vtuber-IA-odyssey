edad = 0
print("///////////////////")
print("Stream de Rotceh!")
print("///////////////////\n")
try:
    nombre = input("Cual es tu nombre? ")
except ValueError:
    print("Ingresa un nombre valido la proxima por favor ;d")
while edad <=0:
    try:
            edad = int(input("Ingresa tu edad por favor: \n"))
            print(f"Genial {nombre}, entonces tienes {edad} años.")
            if edad <= 13:
                print("Lo siento, eres muy jove para entrar al stream ;b")
            elif nombre == "Aiko" and edad >=18:
                print(f"Bienvenida al stream Sensei {nombre}! Es un gusto tenerla por aqui :D")
            elif edad >= 14 and edad <=17:
                print(f"Bienvenido al stream {nombre}! entras en modo seguro :D")
            elif edad >= 18:
                print(f"Bienvenido al stream {nombre}! Asegurate de respetar las reglas y diviertete! :D")
    except ValueError:
            print("\nPor favor ingresa un numero valido!:]")

        