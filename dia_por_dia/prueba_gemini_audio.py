import os
import wave  # <--- Librería estándar de Python para audio
from dotenv import load_dotenv
from google import genai
from google.genai import types
import pygame

load_dotenv()
client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

config_audio_niu = types.GenerateContentConfig(
    response_modalities=["AUDIO"],
    speech_config=types.SpeechConfig(
        voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Autonoe")
        )
    ),
    temperature=0.7,
)


def probar_voz_nativa():
  print("\n[Generando audio con gemini-3.1-flash-tts-preview...]")

  frase = (
      "¡Hola Rotceh! Oye, dime la verdad... ¿a poco no suena mil veces más"
      " natural mi voz así? ¡Hasta me puedo reír sin sonar como robot, jijiji!"
  )

  try:
    response = client.models.generate_content(
        model="gemini-3.1-flash-tts-preview",
        contents=frase,
        config=config_audio_niu,
    )

    audio_bytes = None
    for part in response.candidates[0].content.parts:
      if part.inline_data:
        audio_bytes = part.inline_data.data
        break

    if audio_bytes:
      archivo_salida = "voz_nativa_niu.wav"

      # Empaquetamos los bytes crudos en un archivo WAV estándar a 24kHz
      with wave.open(archivo_salida, "wb") as wav_file:
        wav_file.setnchannels(1)  # 1 canal (Mono)
        wav_file.setsampwidth(2)  # 16-bit (2 bytes por muestra)
        wav_file.setframerate(24000)  # Frecuencia nativa de Gemini (24kHz)
        wav_file.writeframes(audio_bytes)

      print("🎙️ ¡Reproduciendo voz nativa de Niu!")
      pygame.mixer.init()
      pygame.mixer.music.load(archivo_salida)
      pygame.mixer.music.play()
      while pygame.mixer.music.get_busy():
        pygame.time.Clock().tick(10)
      pygame.mixer.music.unload()
      pygame.mixer.quit()
    else:
      print("No se encontraron bytes de audio en la respuesta.")

  except Exception as e:
    print(f"Error técnico: {e}")


if __name__ == "__main__":
  probar_voz_nativa()