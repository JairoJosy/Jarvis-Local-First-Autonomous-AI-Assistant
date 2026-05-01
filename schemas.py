from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Union

from pydantic import BaseModel, Field


IntentType = Literal["command", "chat", "memory_query"]


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    user_text: str = Field(min_length=1, max_length=4000)


class ChatResponse(BaseModel):
    type: Literal["chat", "tool_result", "error"]
    message: str
    tool_trace_id: str | None = None


class ToolPlan(BaseModel):
    type: Literal["tool"]
    action: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class ChatPlan(BaseModel):
    type: Literal["chat"]
    response: str


PlannerAction = Union[ToolPlan, ChatPlan]


class ToolResult(BaseModel):
    success: bool
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    trace_id: str | None = None


class AuthorityDecision(BaseModel):
    allowed: bool
    reason: str
    requires_approval: bool = False
    approval_id: str | None = None


class PersonFact(BaseModel):
    type: Literal["person"] = "person"
    name: str
    profession: str | None = None
    location: str | None = None
    traits: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)


class EventFact(BaseModel):
    type: Literal["event"] = "event"
    event: str
    location: str | None = None
    description: str = ""
    timestamp: datetime | None = None
    source_turn_id: str | None = None


class ExtractedFacts(BaseModel):
    people: list[PersonFact] = Field(default_factory=list)
    events: list[EventFact] = Field(default_factory=list)


class MemorySnippet(BaseModel):
    source: Literal["person", "event", "semantic", "timeline", "history"]
    text: str
    score: float | None = None
    ref_id: int | None = None


class MemoryContext(BaseModel):
    snippets: list[MemorySnippet] = Field(default_factory=list)

    def to_prompt_block(self) -> str:
        if not self.snippets:
            return "Relevant past information:\n- None"
        lines = ["Relevant past information:"]
        for snippet in self.snippets:
            score_label = ""
            if snippet.score is not None:
                score_label = f" (score={snippet.score:.3f})"
            lines.append(f"- [{snippet.source}]{score_label} {snippet.text}")
        return "\n".join(lines)


class PlannerResult(BaseModel):
    action: PlannerAction
    raw_text: str
    used_fallback: bool = False


class TurnAuditRecord(BaseModel):
    turn_id: str
    session_id: str
    user_text: str
    intent: IntentType
    memory_refs: list[str] = Field(default_factory=list)
    planner_raw_output: str
    planner_action: dict[str, Any]
    authority_decision: dict[str, Any]
    execution_result: dict[str, Any]
    latency_ms: int
    timestamp_utc: datetime
    timestamp_local: datetime

