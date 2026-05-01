from __future__ import annotations

from typing import Protocol


class LLMError(RuntimeError):
    """Raised when an LLM provider call fails."""


class LLMClient(Protocol):
    def generate(self, *, system_prompt: str, user_prompt: str, temperature: float) -> str:
        """Generate a text response from the model."""

