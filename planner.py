from __future__ import annotations

import json
import re
from typing import Any

from pydantic import TypeAdapter, ValidationError

from jarvis.config import Settings
from jarvis.llm.base import LLMError
from jarvis.llm.router import LLMRouter
from jarvis.schemas import ChatPlan, IntentType, MemoryContext, PlannerAction, PlannerResult, ToolPlan


PLANNER_OUTPUT_SPEC = """
Output a single JSON object only.

Tool format:
{
  "type": "tool",
  "action": "tool_name",
  "parameters": {}
}

Chat format:
{
  "type": "chat",
  "response": "text"
}
"""

SYSTEM_PROMPT = """
You are Jarvis planner.
Rules:
- Be friendly and natural in chat responses.
- Never hallucinate memory. Use only supplied context.
- Never assume past events not present in context.
- Output valid JSON matching the required schema.
- No markdown, no extra prose outside JSON.
"""


class Planner:
    def __init__(self, llm: LLMRouter, settings: Settings) -> None:
        self._llm = llm
        self._settings = settings
        self._adapter = TypeAdapter(PlannerAction)

    def plan(
        self,
        *,
        user_text: str,
        intent: IntentType,
        memory_context: MemoryContext,
        tool_specs: str,
    ) -> PlannerResult:
        prompt = self._build_prompt(
            user_text=user_text,
            intent=intent,
            memory_context=memory_context,
            tool_specs=tool_specs,
        )
        try:
            raw = self._llm.generate(
                system_prompt=SYSTEM_PROMPT.strip(),
                user_prompt=prompt,
                temperature=self._settings.planner_temperature,
            )
        except LLMError:
            fallback = ChatPlan(
                type="chat",
                response="I hit a planning issue and will stay in safe mode. Please retry or rephrase.",
            )
            return PlannerResult(action=fallback, raw_text="", used_fallback=True)

        action = self._parse_action(raw)
        if action is None:
            fallback = ChatPlan(
                type="chat",
                response=(
                    "I could not generate a safe structured plan for that request. "
                    "Please try again with a clearer instruction."
                ),
            )
            return PlannerResult(action=fallback, raw_text=raw, used_fallback=True)
        return PlannerResult(action=action, raw_text=raw, used_fallback=False)

    def _build_prompt(
        self,
        *,
        user_text: str,
        intent: IntentType,
        memory_context: MemoryContext,
        tool_specs: str,
    ) -> str:
        return (
            f"Intent: {intent}\n"
            f"{PLANNER_OUTPUT_SPEC.strip()}\n\n"
            f"Available tools:\n{tool_specs}\n\n"
            f"{memory_context.to_prompt_block()}\n\n"
            f"User input:\n{user_text}\n"
        )

    def _parse_action(self, raw_text: str) -> PlannerAction | None:
        for candidate in self._extract_json_candidates(raw_text):
            try:
                payload = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            action = self._validate_action(payload)
            if action is not None:
                return action
        return None

    def _validate_action(self, payload: Any) -> PlannerAction | None:
        if not isinstance(payload, dict):
            return None
        payload_type = payload.get("type")
        if payload_type == "tool":
            if not isinstance(payload.get("action"), str):
                return None
            if not isinstance(payload.get("parameters"), dict):
                payload["parameters"] = {}
        if payload_type == "chat" and not isinstance(payload.get("response"), str):
            return None
        try:
            return self._adapter.validate_python(payload)
        except ValidationError:
            return None

    def _extract_json_candidates(self, text: str) -> list[str]:
        candidates: list[str] = []

        stripped = text.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            candidates.append(stripped)

        fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
        candidates.extend(fenced)

        candidates.extend(self._balanced_json_objects(text))

        # De-duplicate while preserving order.
        seen: set[str] = set()
        unique: list[str] = []
        for item in candidates:
            if item not in seen:
                unique.append(item)
                seen.add(item)
        return unique

    def _balanced_json_objects(self, text: str) -> list[str]:
        results: list[str] = []
        start_index: int | None = None
        depth = 0
        in_string = False
        escape = False

        for i, char in enumerate(text):
            if char == '"' and not escape:
                in_string = not in_string
            if in_string:
                escape = (char == "\\") and not escape
                continue

            if char == "{":
                if depth == 0:
                    start_index = i
                depth += 1
            elif char == "}":
                if depth > 0:
                    depth -= 1
                    if depth == 0 and start_index is not None:
                        results.append(text[start_index : i + 1])
                        start_index = None
            escape = (char == "\\") and not escape
        return results

