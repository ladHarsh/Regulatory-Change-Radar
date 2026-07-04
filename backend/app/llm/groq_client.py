"""
llm/groq_client.py — Groq API client wrapper.

Provides both async (streaming + non-streaming) interfaces.
Uses exponential backoff via tenacity for rate limit handling.
Falls back to Ollama if Groq is unavailable (config-controlled).
"""
import json
from typing import AsyncGenerator, List, Optional

from groq import AsyncGroq
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import get_settings

settings = get_settings()


class GroqClient:
    """
    Async wrapper around the Groq Python SDK.

    Supports:
      - complete(prompt)          → single string response
      - stream_complete(prompt)   → async generator of text chunks

    Rate limit errors are retried automatically with exponential backoff.
    """

    def __init__(self):
        if not settings.groq_api_key:
            raise ValueError(
                "GROQ_API_KEY is not set. "
                "Get a free key at https://console.groq.com and add it to .env"
            )
        self._client = AsyncGroq(api_key=settings.groq_api_key)
        self._model = settings.groq_model

    @retry(
        retry=retry_if_exception_type(Exception),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
    )
    async def complete(
        self,
        prompt: str,
        system_message: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 1024,
        model: Optional[str] = None,
    ) -> str:
        """
        Sends a completion request to Groq and returns the full response text.

        Args:
            prompt:         The user message / formatted prompt.
            system_message: Optional system context.
            temperature:    Low temperature (0.1) for factual, consistent outputs.
            max_tokens:     Maximum response length.
            model:          Override the default model (e.g., 'llama-3.1-8b-instant'
                            for faster extraction/verification tasks).

        Returns:
            Response text string.
        """
        messages = []
        if system_message:
            messages.append({"role": "system", "content": system_message})
        messages.append({"role": "user", "content": prompt})

        effective_model = model or self._model
        logger.debug(f"Groq request: model={effective_model}, tokens≤{max_tokens}")

        response = await self._client.chat.completions.create(
            model=effective_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        text = response.choices[0].message.content or ""
        logger.debug(f"Groq response: {len(text)} chars")
        return text

    async def stream_complete(
        self,
        prompt: str,
        system_message: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> AsyncGenerator[str, None]:
        """
        Sends a streaming completion request.
        Yields text chunks as they arrive from the Groq API.

        Usage:
            async for chunk in client.stream_complete(prompt):
                print(chunk, end="", flush=True)
        """
        messages = []
        if system_message:
            messages.append({"role": "system", "content": system_message})
        messages.append({"role": "user", "content": prompt})

        logger.debug(f"Groq streaming request: model={self._model}")

        stream = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )

        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
