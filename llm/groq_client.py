from __future__ import annotations

import requests

from jarvis.config import Settings
from jarvis.llm.base import LLMError


class GroqClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def generate(self, *, system_prompt: str, user_prompt: str, temperature: float) -> str:
        if not self._settings.groq_api_key:
            raise LLMError("Groq API key not configured.")
        payload = {
            "model": self._settings.groq_model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self._settings.groq_api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = requests.post(
                self._settings.groq_base_url,
                json=payload,
                headers=headers,
                timeout=self._settings.llm_timeout_seconds,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise LLMError(f"Groq call failed: {exc}") from exc
        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            raise LLMError("Groq response missing choices.")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if not isinstance(content, str):
            raise LLMError("Groq response missing content.")
        return content

