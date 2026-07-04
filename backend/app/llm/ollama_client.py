"""
llm/ollama_client.py — Local Ollama fallback client.

Provides the same interface as GroqClient but calls a locally running
Ollama instance. Zero cost, fully offline, no API key required.

To use: install Ollama (https://ollama.com) and run:
  ollama pull llama3.1:8b
  ollama serve  (or it starts automatically on Windows)

Set LLM_PROVIDER=ollama in .env to use this client.
"""
from typing import AsyncGenerator, Optional

import httpx
from loguru import logger

from app.config import get_settings

settings = get_settings()


class OllamaClient:
    """
    Async HTTP client for the Ollama local inference server.
    Mirrors the GroqClient interface so it can be swapped in transparently.
    """

    def __init__(self):
        self._base_url = settings.ollama_base_url.rstrip("/")
        self._model = settings.ollama_model

    async def _check_availability(self) -> bool:
        """Returns True if the Ollama server is reachable."""
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False

    async def complete(
        self,
        prompt: str,
        system_message: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> str:
        """
        Sends a non-streaming chat completion to Ollama.
        """
        if not await self._check_availability():
            raise RuntimeError(
                f"Ollama is not running at {self._base_url}. "
                f"Start it with: ollama serve"
            )

        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if system_message:
            payload["system"] = system_message

        logger.debug(f"Ollama request: model={self._model}")

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{self._base_url}/api/generate",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("response", "")

    async def stream_complete(
        self,
        prompt: str,
        system_message: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> AsyncGenerator[str, None]:
        """
        Streams a chat completion from Ollama, yielding text chunks.
        """
        import json

        if not await self._check_availability():
            raise RuntimeError("Ollama is not running.")

        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": True,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if system_message:
            payload["system"] = system_message

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{self._base_url}/api/generate",
                json=payload,
            ) as response:
                async for line in response.aiter_lines():
                    if line.strip():
                        try:
                            data = json.loads(line)
                            token = data.get("response", "")
                            if token:
                                yield token
                            if data.get("done"):
                                break
                        except json.JSONDecodeError:
                            continue


def get_llm_client():
    """
    Factory function — returns the configured LLM client based on LLM_PROVIDER env var.
    This is the single injection point used throughout the codebase.
    """
    provider = settings.llm_provider.lower()
    if provider == "ollama":
        return OllamaClient()
    else:
        return GroqClient()


# Avoid circular import in factory
from app.llm.groq_client import GroqClient  # noqa: E402
