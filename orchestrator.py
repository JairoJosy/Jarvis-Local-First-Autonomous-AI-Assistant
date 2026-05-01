from __future__ import annotations

import re
import time
import uuid
from datetime import datetime, timezone

from jarvis.audit import AuditLogger
from jarvis.authority import AuthorityLayer
from jarvis.config import Settings
from jarvis.intent import IntentDetector
from jarvis.memory.manager import MemoryManager
from jarvis.planner import Planner
from jarvis.schemas import (
    AuthorityDecision,
    ChatPlan,
    ChatResponse,
    IntentType,
    PlannerAction,
    ToolPlan,
    TurnAuditRecord,
)
from jarvis.timezone_utils import safe_zoneinfo
from jarvis.timeline import TimelineService
from jarvis.tools.registry import ToolRegistry


class Orchestrator:
    APPROVAL_RE = re.compile(r"^\s*approve\s+([a-zA-Z0-9]{4,40})\s*$", re.IGNORECASE)

    def __init__(
        self,
        *,
        settings: Settings,
        intent_detector: IntentDetector,
        planner: Planner,
        memory: MemoryManager,
        authority: AuthorityLayer,
        tools: ToolRegistry,
        audit: AuditLogger,
        timeline: TimelineService,
    ) -> None:
        self._settings = settings
        self._intent_detector = intent_detector
        self._planner = planner
        self._memory = memory
        self._authority = authority
        self._tools = tools
        self._audit = audit
        self._timeline = timeline

    def handle_turn(self, session_id: str, user_text: str) -> ChatResponse:
        turn_id = uuid.uuid4().hex
        started = time.perf_counter()
        now_utc = datetime.now(timezone.utc)
        now_local = now_utc.astimezone(safe_zoneinfo(self._settings.timezone))

        intent: IntentType = "chat"
        memory_context = self._memory.retrieve_context(
            session_id=session_id,
            user_text=user_text,
            intent="chat",
        )
        planner_raw = ""
        planner_action: PlannerAction = ChatPlan(type="chat", response="I am ready.")
        authority_decision = AuthorityDecision(allowed=True, reason="Initialization placeholder.")
        execution_result: dict[str, object] = {"status": "not_executed"}
        response: ChatResponse
        tool_action_name: str | None = None
        tool_success: bool | None = None

        approval_match = self.APPROVAL_RE.match(user_text)
        if approval_match:
            intent = "command"
            approval_id = approval_match.group(1)
            approved_action = self._authority.consume_approval(session_id, approval_id)
            if approved_action is None:
                planner_action = ChatPlan(
                    type="chat",
                    response=f"No pending action found for approval id {approval_id}.",
                )
                authority_decision = AuthorityDecision(allowed=False, reason="Approval id not found.")
                response = ChatResponse(type="chat", message=planner_action.response)
            else:
                planner_action = approved_action
                authority_decision = AuthorityDecision(
                    allowed=True,
                    reason=f"Pending action {approval_id} approved by user.",
                )
                tool_result = self._execute_tool(approved_action, session_id, turn_id)
                tool_action_name = approved_action.action
                tool_success = tool_result["success"]
                execution_result = tool_result
                if tool_result["success"]:
                    response = ChatResponse(
                        type="tool_result",
                        message=str(tool_result["message"]),
                        tool_trace_id=str(tool_result.get("trace_id")),
                    )
                else:
                    response = ChatResponse(
                        type="error",
                        message=str(tool_result["message"]),
                        tool_trace_id=str(tool_result.get("trace_id")),
                    )
        else:
            intent_result = self._intent_detector.detect(user_text)
            intent = intent_result.intent
            memory_context = self._memory.retrieve_context(
                session_id=session_id,
                user_text=user_text,
                intent=intent,
            )
            plan_result = self._planner.plan(
                user_text=user_text,
                intent=intent,
                memory_context=memory_context,
                tool_specs=self._tools.specs_text(),
            )
            planner_raw = plan_result.raw_text
            planner_action = plan_result.action

            authority_decision = self._authority.validate(
                intent=intent,
                action=planner_action,
                session_id=session_id,
                tools=self._tools,
            )

            if authority_decision.allowed:
                if planner_action.type == "tool":
                    tool_action_name = planner_action.action
                    tool_result = self._execute_tool(planner_action, session_id, turn_id)
                    tool_success = tool_result["success"]
                    execution_result = tool_result
                    if tool_result["success"]:
                        response = ChatResponse(
                            type="tool_result",
                            message=str(tool_result["message"]),
                            tool_trace_id=str(tool_result.get("trace_id")),
                        )
                    else:
                        response = ChatResponse(
                            type="error",
                            message=str(tool_result["message"]),
                            tool_trace_id=str(tool_result.get("trace_id")),
                        )
                else:
                    execution_result = {"status": "chat_response"}
                    response = ChatResponse(type="chat", message=planner_action.response)
            else:
                if authority_decision.requires_approval and authority_decision.approval_id:
                    approval_message = (
                        f"{authority_decision.reason} "
                        f"Reply with `approve {authority_decision.approval_id}` to continue."
                    )
                    execution_result = {
                        "status": "approval_required",
                        "approval_id": authority_decision.approval_id,
                    }
                    response = ChatResponse(type="chat", message=approval_message)
                elif intent == "command":
                    # Command path is tool-only; fallback to safe chat only after validation failure.
                    response = ChatResponse(
                        type="chat",
                        message=(
                            "I could not safely execute that command because validation failed: "
                            f"{authority_decision.reason}"
                        ),
                    )
                    execution_result = {"status": "validation_failed", "reason": authority_decision.reason}
                else:
                    response = ChatResponse(
                        type="chat",
                        message=f"I cannot comply with that request: {authority_decision.reason}",
                    )
                    execution_result = {"status": "blocked", "reason": authority_decision.reason}

        memory_update = self._memory.update_after_turn(
            session_id=session_id,
            turn_id=turn_id,
            user_text=user_text,
            assistant_text=response.message,
            intent=intent,
            tool_action=tool_action_name,
            tool_success=tool_success,
        )
        execution_result["memory_update"] = memory_update

        latency_ms = int((time.perf_counter() - started) * 1000)
        memory_refs = [
            f"{snippet.source}:{snippet.ref_id}"
            for snippet in memory_context.snippets
            if snippet.ref_id is not None
        ]

        audit_record = TurnAuditRecord(
            turn_id=turn_id,
            session_id=session_id,
            user_text=user_text,
            intent=intent,
            memory_refs=memory_refs,
            planner_raw_output=planner_raw,
            planner_action=planner_action.model_dump(),
            authority_decision=authority_decision.model_dump(),
            execution_result=execution_result,
            latency_ms=latency_ms,
            timestamp_utc=now_utc,
            timestamp_local=now_local,
        )
        self._audit.log_turn(audit_record)
        return response

    def timeline_summary(self, range_key: str, limit: int) -> str:
        return self._timeline.summarize(range_key=range_key, limit=limit)

    def _execute_tool(self, action: ToolPlan, session_id: str, turn_id: str) -> dict[str, object]:
        tool = self._tools.get(action.action)
        trace_id = uuid.uuid4().hex[:12]
        if tool is None:
            return {
                "success": False,
                "message": f"Tool not found: {action.action}",
                "trace_id": trace_id,
                "data": {},
            }
        try:
            params = tool.validate_parameters(action.parameters)
        except ValueError as exc:
            return {
                "success": False,
                "message": str(exc),
                "trace_id": trace_id,
                "data": {},
            }
        result = tool.execute(
            params,
            {
                "session_id": session_id,
                "turn_id": turn_id,
                "timezone": self._settings.timezone,
            },
        )
        payload = result.model_dump()
        payload["trace_id"] = trace_id
        return payload
