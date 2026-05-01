from __future__ import annotations

import random
import re

from jarvis.v2.schemas import BanterLevel, BanterProfile


class PersonaEngine:
    """
    Keeps responses conversational and playful while enforcing boundaries.
    """

    BLOCKED_PATTERNS = (
        r"\bhate\b",
        r"\bkill\b",
        r"\bslur\b",
        r"\bterror\b",
    )

    WITTY_TAGS = [
        "Nice move.",
        "That should make your day easier.",
        "One less thing on your plate.",
    ]
    SASSY_TAGS = [
        "Handled. Try to look surprised.",
        "Done. I even made it look easy.",
        "Sorted. We move.",
    ]

    def apply_style(self, text: str, profile: BanterProfile) -> str:
        base = text.strip()
        if not base:
            base = "Ready when you are."

        if profile.safety_guardrails and self._looks_unsafe(base):
            return (
                "I can keep this witty, but I will not generate harmful or abusive content. "
                "I can help with a safer alternative."
            )

        if profile.level == BanterLevel.NORMAL:
            return base
        if profile.level == BanterLevel.WITTY:
            return f"{base} {random.choice(self.WITTY_TAGS)}"
        if profile.level == BanterLevel.SASSY:
            return f"{base} {random.choice(self.SASSY_TAGS)}"
        return base

    def _looks_unsafe(self, text: str) -> bool:
        return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in self.BLOCKED_PATTERNS)

