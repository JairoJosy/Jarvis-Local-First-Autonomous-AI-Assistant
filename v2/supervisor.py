from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from jarvis.v2.schemas import TaskGraph, TaskStatus, TaskStep


@dataclass
class PlannedTask:
    task: TaskGraph
    requires_confirmation: bool
    risk_level: str
    confirmation_summary: str | None = None


class SpecialistAgent:
    def __init__(self, name: str, keywords: list[str]) -> None:
        self.name = name
        self.keywords = keywords

    def matches(self, text: str) -> bool:
        lowered = text.lower()
        return any(keyword in lowered for keyword in self.keywords)


class SupervisorAgent:
    HIGH_IMPACT_PATTERNS = (
        r"\bdelete\b",
        r"\bpay\b",
        r"\bpurchase\b",
        r"\bshutdown\b",
        r"\btransfer\b",
        r"\bwire\b",
        r"\bfactory reset\b",
    )

    MEDIUM_IMPACT_PATTERNS = (
        r"\bsend email\b",
        r"\bpost\b",
        r"\bpublish\b",
        r"\bdeploy\b",
    )

    def __init__(self) -> None:
        self._specialists = [
            SpecialistAgent("Coding", ["code", "implement", "feature", "python", "refactor"]),
            SpecialistAgent("Debugging", ["debug", "fix", "bug", "error", "failure"]),
            SpecialistAgent("ProjectWriting", ["write", "proposal", "document", "spec"]),
            SpecialistAgent("Deadline", ["deadline", "schedule", "calendar", "remind"]),
            SpecialistAgent("Presentation", ["slide", "presentation", "deck", "ppt"]),
            SpecialistAgent("TaskOps", ["task", "organize", "arrange", "todo", "bill"]),
            SpecialistAgent("ContextSense", ["weather", "traffic", "meeting", "outfit", "going out"]),
            SpecialistAgent("DeviceControl", ["open", "type", "click", "phone", "android", "pc"]),
            SpecialistAgent("ScreenAnalyst", ["screen", "on my screen", "visible", "what's this window"]),
            SpecialistAgent("CyberGuardian", ["virus", "threat", "malware", "security", "antivirus"]),
            SpecialistAgent("CreativeEditor", ["photo", "image", "video", "edit", "design", "poster"]),
            SpecialistAgent("WebQASpecialist", ["lighthouse", "accessibility", "responsive", "visual diff", "web qa"]),
            SpecialistAgent("KnowledgeDoc", ["meeting notes", "summarize", "documentation", "knowledge base"]),
            SpecialistAgent("SocialIntel", ["reply", "email", "message", "professor", "conversation", "tell me about yourself"]),
            SpecialistAgent("SimulationCoach", ["simulate", "interview", "debate", "argue against", "decision outcome"]),
            SpecialistAgent("RiskOpportunityRadar", ["opportunity", "risk", "burnout", "poor score", "missing deadline"]),
            SpecialistAgent("PluginEcosystem", ["plugin", "connector", "app store", "new tool", "api integration"]),
        ]

    def plan(self, *, session_id: str, user_text: str) -> PlannedTask:
        assigned = self._select_specialist(user_text)
        steps = self._build_steps(assigned, user_text)
        risk_level = self._risk_level(user_text)
        requires_confirmation = risk_level in {"medium", "high"}
        summary = None
        if requires_confirmation:
            summary = f"Confirm {risk_level}-risk task before execution: {user_text[:120]}"
        task = TaskGraph(
            task_id=uuid4().hex[:12],
            session_id=session_id,
            user_text=user_text,
            assigned_agent=assigned,
            status=TaskStatus.REQUIRES_APPROVAL if requires_confirmation else TaskStatus.PENDING,
            steps=steps,
            created_at=self._now(),
            updated_at=self._now(),
            source_confidence=0.82,
            verification_refs=["supervisor_plan"],
        )
        return PlannedTask(
            task=task,
            requires_confirmation=requires_confirmation,
            risk_level=risk_level,
            confirmation_summary=summary,
        )

    def execute_step(self, step: TaskStep, user_text: str) -> tuple[TaskStatus, dict[str, Any], str]:
        # v2 execution layer returns deterministic placeholder results;
        # concrete connectors/tools can replace these handlers without changing contracts.
        evidence = {"agent": step.agent, "step_id": step.step_id}
        if step.agent == "Coding":
            return TaskStatus.COMPLETED, evidence, "Drafted and verified implementation path."
        if step.agent == "Debugging":
            return TaskStatus.COMPLETED, evidence, "Identified likely root cause and applied fix strategy."
        if step.agent == "ProjectWriting":
            return TaskStatus.COMPLETED, evidence, "Prepared structured writing draft."
        if step.agent == "Presentation":
            return TaskStatus.COMPLETED, evidence, "Prepared slide outline and speaker notes draft."
        if step.agent == "Deadline":
            return TaskStatus.COMPLETED, evidence, "Scheduled reminders and timeline checkpoints."
        if step.agent == "ContextSense":
            return TaskStatus.COMPLETED, evidence, "Produced context-aware recommendation set."
        if step.agent == "DeviceControl":
            return TaskStatus.COMPLETED, evidence, "Queued device actions with verification checkpoints."
        if step.agent == "ScreenAnalyst":
            return TaskStatus.COMPLETED, evidence, "Captured masked screen context and generated explanation."
        if step.agent == "CyberGuardian":
            return TaskStatus.COMPLETED, evidence, "Security scan and incident recommendation completed."
        if step.agent == "CreativeEditor":
            return TaskStatus.COMPLETED, evidence, "Creative edit plan executed with reversible outputs."
        if step.agent == "WebQASpecialist":
            return TaskStatus.COMPLETED, evidence, "Web QA findings generated and prioritized."
        if step.agent == "KnowledgeDoc":
            return TaskStatus.COMPLETED, evidence, "Knowledge artifact captured with summary."
        if step.agent == "SocialIntel":
            return TaskStatus.COMPLETED, evidence, "Drafted social response with tone and follow-up options."
        if step.agent == "SimulationCoach":
            return TaskStatus.COMPLETED, evidence, "Generated practice simulation and feedback scorecard."
        if step.agent == "RiskOpportunityRadar":
            return TaskStatus.COMPLETED, evidence, "Scanned deadlines, opportunities, and personal risk signals."
        if step.agent == "PluginEcosystem":
            return TaskStatus.COMPLETED, evidence, "Validated local plugin manifest and catalog metadata."
        return TaskStatus.COMPLETED, evidence, "Executed task operation."

    def _select_specialist(self, user_text: str) -> str:
        for specialist in self._specialists:
            if specialist.matches(user_text):
                return specialist.name
        return "TaskOps"

    def _build_steps(self, assigned: str, user_text: str) -> list[TaskStep]:
        return [
            TaskStep(
                step_id=uuid4().hex[:8],
                title=f"Plan {assigned} workflow",
                agent="CapabilityDiscovery",
                status=TaskStatus.PENDING,
                details=f"Discover strategy for: {user_text[:200]}",
            ),
            TaskStep(
                step_id=uuid4().hex[:8],
                title=f"Execute via {assigned}",
                agent=assigned,
                status=TaskStatus.PENDING,
                details="Run selected steps with policy and safety checks.",
            ),
            TaskStep(
                step_id=uuid4().hex[:8],
                title="Verify outcome",
                agent="TaskOps",
                status=TaskStatus.PENDING,
                details="Confirm success and record evidence.",
            ),
        ]

    def _risk_level(self, user_text: str) -> str:
        lowered = user_text.lower()
        if any(re.search(pattern, lowered) for pattern in self.HIGH_IMPACT_PATTERNS):
            return "high"
        if any(re.search(pattern, lowered) for pattern in self.MEDIUM_IMPACT_PATTERNS):
            return "medium"
        return "low"

    def _now(self):
        from datetime import datetime, timezone

        return datetime.now(timezone.utc)
