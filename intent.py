from __future__ import annotations

import re
from dataclasses import dataclass

from jarvis.schemas import IntentType


@dataclass
class IntentResult:
    intent: IntentType
    confidence: float
    reason: str


class IntentDetector:
    """
    Rule-first intent detector with light heuristics.
    """

    MEMORY_PATTERNS = (
        "what did i do today",
        "recent activity",
        "remember",
        "do you remember",
        "who is ",
        "when did i ",
    )
    COMMAND_VERBS = {
        "open",
        "launch",
        "run",
        "execute",
        "start",
        "close",
    }
    COMMAND_HINTS = {
        "calculator",
        "chrome",
        "explorer",
        "terminal",
        "app",
        "command",
        "shell",
    }

    def detect(self, user_text: str) -> IntentResult:
        text = user_text.strip()
        lower = text.lower()

        if lower.startswith("approve "):
            return IntentResult(intent="command", confidence=0.99, reason="approval token")

        if any(p in lower for p in self.MEMORY_PATTERNS):
            return IntentResult(intent="memory_query", confidence=0.9, reason="memory query pattern")

        tokens = re.findall(r"[a-zA-Z]+", lower)
        if tokens:
            first = tokens[0]
            if first in self.COMMAND_VERBS:
                return IntentResult(intent="command", confidence=0.88, reason=f"command verb: {first}")
            if any(token in self.COMMAND_HINTS for token in tokens):
                # Commands that omit a direct imperative still often reference tools.
                return IntentResult(intent="command", confidence=0.7, reason="command hint token")

        if "?" in text:
            return IntentResult(intent="chat", confidence=0.65, reason="question fallback")

        return IntentResult(intent="chat", confidence=0.6, reason="default chat fallback")

