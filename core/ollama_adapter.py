import httpx
import json
import os
from typing import AsyncIterator, List, Dict, Any
from core.llm_provider import LLMProvider, Messages, LLMConfig, LLMResponse

# Cuánto tiempo mantiene Ollama el modelo cargado tras la última petición.
#
# Por defecto son 5 minutos. Si te paras a pensar, a mirar algo o a leer, el
# modelo se descarga de la VRAM y el turno siguiente paga varios segundos de
# carga otra vez. Media hora cubre una sesión de conversación normal.
KEEP_ALIVE = os.getenv("NIU_OLLAMA_KEEP_ALIVE", "30m")


class OllamaAdapter:
    """
    Adaptador para modelos locales via Ollama
    Implementa la interfaz LLMProvider (Protocol)
    """
    
    def __init__(
        self, 
        base_url: str = "http://localhost:11434",
        model: str = "qwen2.5:7b-instruct-q4_k_m",
        timeout: float = 120.0,
    ):
        """
        inicializa el adaptador

        Args:
            base_url (_type_, optional): _description_. Defaults to "http://localhost:11434".
            model (_type_, optional): _description_. Defaults to "qwen2.5:7b-instruct-q4_k_m".
            timeout (float, optional): _description_. Defaults to 120.0.
        """
    
        self.base_url = base_url.strip("/")
        self.model = model
        self.timeout = timeout
        # Cliente HTTP reutilizable (Conexiones resistentes, pooling)
        self._client = httpx.AsyncClient(timeout=timeout)
        
    async def generate(
        self,                           
        messages: Messages,             # List[Dict[str, Any]] - historial + mensaje actual
        system_instruction: str | None, # Prompt de personalidad
        config: LLMConfig,              # temperature, max_tokens, etc.
    ) -> LLMResponse:
        
        """
        Respuesta (No streaming) usando la API /api/chat de Ollama.
        
        Args:
            messages: Lista de mensajes [{"role": "user", "content": "..."}, ...]
            system_instruction: Prompt del sistema
            config: Configuracion de generacion (temperature, max tokens)
            
        Returns:
            LLMResponse con el texto generado
        """
        
        # 1. Preparar payload apra la API de Ollama (api/chat)
        payload = self._build_payload(messages, system_instruction, config)
        
        # 2. Hacer POST HTTP a /api/chat
        response = await self._client.post(
            f"{self.base_url}/api/chat",
            json=payload,
        )
        response.raise_for_status() # Lanza exepcion si status >= 400
        
        # 3. Parear respuesta JSON
        data = response.json()
        
        # 4. Extraer texto de la respuesta (formato Ollama: {"message": {"content": "..."}})
        content = data.get("message", {}).get("content", "")
        
        # 5. Devolver formato estadar LLMResponse
        return LLMResponse(text=content)
    
    async def generate_stream(
        self,
        messages: Messages,
        system_instruction: str | None,
        config: LLMConfig,
    ) -> AsyncIterator[str]:
        """
        Genera respuesta en streaming (trozo a trozo) para subtitulos en vivo
        Devuelve AsyncIterator[str] - cada yield es un trozo de texto.
        """
        payload = self._build_payload(messages, system_instruction, config)
        payload["stream"] = True # Importante: tream=true
        
        async with self._client.stream(
            "POST",
            f"{self.base_url}/api/chat",
            json=payload,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                # Cada linea es un JSON: {"message": {"content": "trozo"}, "done": false}
                chunk = json.loads(line)
                content = chunk.get("message", {}).get("content", "")
                if content:
                    yield content
                if chunk.get("done", False):
                    break
    
    def _build_payload(
        self,
        messages: Messages,
        system_instruction: str | None,
        config: LLMConfig | None,
    ) -> dict:
        
        # Default robusto
        if config is None:
            config = LLMConfig()
        """
        Convierte el formato comun (Messages + system_instruction + config)
        al formato que espera la API de Ollama (/api/chat).
        """
        ollama_messages = []
        
        # 1a. Si hay system_instruction, anadirlo como primer mensaje cone role="System"
        if system_instruction:
            ollama_messages.append({
                "role": "system",
                "content": system_instruction
            })
        
        # qb. Anadir el historial + mensaje actual
        # Nuevo formato Messages = List[Dict[str, Any]] ya es compatible
        ollama_messages.extend(messages)
        
        # 2. Construir el payload completo
        payload = {
            "model": self.model,
            "messages": ollama_messages,
            "stream": False,
            "keep_alive": KEEP_ALIVE,
            "options": {
                "temperature": config.temperature,
            }
        }
        
        # 3. Anadir max_tokens si esta configurado
        if config.max_tokens is not None:
            payload["options"]["num_predict"] = config.max_tokens # Ollama usa "num_predict"
            
        return payload
    
    async def close(self):
        """Cierra el cliente HTTP (Libera conexiones)."""
        await self._client.aclose()

    async def preparar(self) -> None:
        """Trae el modelo a la memoria sin generar una respuesta de verdad.

        La primera petición de una sesión paga dos costes ajenos a la
        respuesta: mover el modelo a la VRAM (~4,7 GB con qwen2.5 7B q4) y
        procesar el prompt de personalidad completo. Medido en este equipo:
        primer turno 9,5 s, turnos siguientes 3,6 s.

        Ese coste existe de todas formas. La diferencia es *cuándo* se paga:
        aquí, al arrancar, cuando todavía no hay nadie esperando respuesta.

        Es opcional: si falla (Ollama apagado, modelo sin descargar), el
        sistema sigue funcionando y solo se pierde la mejora.
        """
        try:
            respuesta = await self._client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": "ok"}],
                    "stream": False,
                    "keep_alive": KEEP_ALIVE,
                    # Una sola palabra: aquí solo interesa cargar, no generar.
                    "options": {"num_predict": 1},
                },
            )
            respuesta.raise_for_status()
            print(f"[LLM] {self.model} cargado en memoria")
        except Exception as e:
            print(f"[WARN] [LLM] No se pudo precalentar el modelo: "
                  f"{type(e).__name__}: {e}")
        
    async def __aenter__(self):
        """Soporta 'async ith OllamaAdapter() as adapter:"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()