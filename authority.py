from __future__ import annotations

import uuid
from dataclasses import dataclass
from threading import Lock
from typing import Any

from jarvis.schemas import AuthorityDecision, IntentType, PlannerAction, ToolPlan
from jarvis.tools.registry import ToolRegistry


@dataclass
class PendingApproval:
    approval_id: str
    session_id: str
    action: ToolPlan
    reason: str


class AuthorityLayer:
    """
    Policy engine that decides whether a planner action is executable.
    """

    def __init__(self) -> None:
        self._pending: dict[str, dict[str, PendingApproval]] = {}
        self._lock = Lock()

    def validate(
        self,
        *,
        intent: IntentType,
        action: PlannerAction,
        session_id: str,
        tools: ToolRegistry,
    ) -> AuthorityDecision:
        if action.type == "chat":
            if intent == "command":
                return AuthorityDecision(
                    allowed=False,
                    reason="Command intent requires a valid tool action.",
                )
            return AuthorityDecision(allowed=True, reason="Chat response allowed.")

        tool = tools.get(action.action)
        if tool is None:
            return AuthorityDecision(allowed=False, reason=f"Unknown tool: {action.action}")

        try:
            tool.validate_parameters(action.parameters)
        except ValueError as exc:
            return AuthorityDecision(allowed=False, reason=str(exc))

        if tool.risk_level == "tier3" or tool.mutating:
            approval_id = self._store_pending(
                session_id=session_id,
                action=action,
                reason=f"Tool {action.action} requires explicit approval.",
            )
            return AuthorityDecision(
                allowed=False,
                reason=f"Approval required for {action.action}.",
                requires_approval=True,
                approval_id=approval_id,
            )

        return AuthorityDecision(allowed=True, reason=f"Tool {action.action} approved by policy.")

    def _store_pending(self, *, session_id: str, action: ToolPlan, reason: str) -> str:
        approval_id = uuid.uuid4().hex[:12]
        pending = PendingApproval(
            approval_id=approval_id,
            session_id=session_id,
            action=action,
            reason=reason,
        )
        with self._lock:
            by_session = self._pending.setdefault(session_id, {})
            by_session[approval_id] = pending
        return approval_id

    def consume_approval(self, session_id: str, approval_id: str) -> ToolPlan | None:
        with self._lock:
            by_session = self._pending.get(session_id, {})
            pending = by_session.pop(approval_id, None)
            if not by_session and session_id in self._pending:
                self._pending.pop(session_id, None)
        if pending is None:
            return None
        return pending.action

    def has_pending_approval(self, session_id: str, approval_id: str) -> bool:
        with self._lock:
            return approval_id in self._pending.get(session_id, {})

    def pending_for_session(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._pending.get(session_id, {}).values())
        return [
            {
                "approval_id": item.approval_id,
                "action": item.action.model_dump(),
                "reason": item.reason,
            }
            for item in items
        ]

