from __future__ import annotations

import requests

from jarvis.config import Settings
from jarvis.llm.base import LLMError


class OllamaClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def generate(self, *, system_prompt: str, user_prompt: str, temperature: float) -> str:
        payload = {
            "model": self._settings.ollama_model,
            "stream": False,
            "options": {"temperature": temperature},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        try:
            response = requests.post(
                self._settings.ollama_base_url,
                json=payload,
                timeout=self._settings.llm_timeout_seconds,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise LLMError(f"Ollama call failed: {exc}") from exc
        data = response.json()
        message = data.get("message") or {}
        content = message.get("content")
        if not isinstance(content, str):
            raise LLMError("Ollama response missing content.")
        return content

