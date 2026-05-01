from __future__ import annotations

from jarvis.llm.base import LLMClient, LLMError


class LLMRouter:
    """
    Cloud-first LLM router with local fallback.
    """

    def __init__(self, primary: LLMClient, fallback: LLMClient | None = None) -> None:
        self._primary = primary
        self._fallback = fallback
        self.last_provider: str | None = None

    def generate(self, *, system_prompt: str, user_prompt: str, temperature: float) -> str:
        try:
            result = self._primary.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=temperature,
            )
            self.last_provider = self._primary.__class__.__name__
            return result
        except Exception as primary_exc:
            if not self._fallback:
                raise LLMError(f"Primary LLM failed with no fallback: {primary_exc}") from primary_exc
            try:
                result = self._fallback.generate(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=temperature,
                )
                self.last_provider = self._fallback.__class__.__name__
                return result
            except Exception as fallback_exc:
                raise LLMError(
                    f"Both primary and fallback LLM providers failed. "
                    f"Primary: {primary_exc}; Fallback: {fallback_exc}"
                ) from fallback_exc

