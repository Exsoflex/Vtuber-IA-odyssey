from typing import Protocol, List, Dict, Any, Optional, AsyncIterator
from dataclasses import dataclass

@dataclass
class LLMConfig:
    temperature: float = 0.9
    max_tokens: int | None = None

@dataclass
class LLMResponse:
    text: str
    # Futuro: tokens_used, finish_reason, model, latency_ms
    
# Tipo simple para mensajes (empieza simple, migra luego)
# Dict[str, Any] = {"role": "user", "content": "hola"}
Messages = List[Dict[str, Any]]

class LLMProvider(Protocol):
    async def generate(
        self, #? que es self?
        messages: Messages,
        system_instruction: str | None,
        config: LLMConfig,
    ) -> LLMResponse: # ? Porque -> LLMResponse
        """Genera una respuesta del modelo"""
        ...
        # ? los tres puntos significan algo?
        
    async def generate_stream(
        self,
        messages: Messages, 
        system_instruction: str | None,
        config: LLMConfig,
    ) -> AsyncIterator[str]:
        ...