from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Iterator
from uuid import uuid4

from jarvis.v2.knowledge import KnowledgeDocService
from jarvis.v2.reminders import ReminderOpsService
from jarvis.v2.schemas import (
    BillReminderState,
    RadarFinding,
    RadarFindingType,
    RadarScanRequest,
    RadarScanResult,
)


class RiskOpportunityRadarService:
    """
    Scans local signals for missed deadlines, useful opportunities, and early risk markers.
    It only recommends actions; execution still flows through approvals and task policy.
    """

    OPPORTUNITY_KEYWORDS = {
        "scholarship",
        "internship",
        "competition",
        "fellowship",
        "hackathon",
        "opportunity",
        "application",
        "iit",
    }
    RISK_KEYWORDS = {
        "burnout",
        "exhausted",
        "overwhelmed",
        "poor score",
        "failed",
        "late",
        "missed",
        "deadline",
    }

    def __init__(
        self,
        *,
        db_path: Path,
        reminders: ReminderOpsService,
        knowledge: KnowledgeDocService,
    ) -> None:
        self._db_path = db_path
        self._reminders = reminders
        self._knowledge = knowledge
        self._lock = Lock()
        self._init_db()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS v2_radar_findings (
                  finding_id TEXT PRIMARY KEY,
                  payload_json TEXT NOT NULL
                )
                """
            )

    def scan(self, request: RadarScanRequest) -> RadarScanResult:
        findings: list[RadarFinding] = []
        if request.include_deadlines:
            findings.extend(self._deadline_findings())
        if request.include_opportunities:
            findings.extend(self._opportunity_findings(request))
        if request.include_risks:
            findings.extend(self._risk_findings(request))

        findings.sort(key=lambda f: self._severity_rank(f.severity), reverse=True)
        for finding in findings:
            self._save(finding)

        summary = self._summary(findings)
        return RadarScanResult(
            generated_at=datetime.now(timezone.utc),
            findings=findings,
            summary=summary,
        )

    def list_findings(self, *, limit: int = 50) -> list[RadarFinding]:
        with self._conn() as conn:
            rows = conn.execute("SELECT payload_json FROM v2_radar_findings").fetchall()
        findings = [RadarFinding.model_validate(json.loads(row["payload_json"])) for row in rows]
        findings.sort(key=lambda item: item.created_at, reverse=True)
        return findings[:limit]

    def _deadline_findings(self) -> list[RadarFinding]:
        findings: list[RadarFinding] = []
        today = date.today()
        for occurrence in self._reminders.upcoming_occurrences(within_days=14):
            if occurrence.state == BillReminderState.PAID:
                continue
            severity = "high" if occurrence.state == BillReminderState.OVERDUE else "medium"
            if occurrence.notify_on > today:
                severity = "low"
            findings.append(
                RadarFinding(
                    finding_id=uuid4().hex[:12],
                    finding_type=RadarFindingType.DEADLINE,
                    title=f"{occurrence.bill_name} payment checkpoint",
                    description=(
                        f"{occurrence.bill_name} is due on {occurrence.due_date.isoformat()} "
                        f"with a reminder scheduled for {occurrence.notify_on.isoformat()}."
                    ),
                    severity=severity,  # type: ignore[arg-type]
                    confidence=0.9,
                    recommended_actions=[
                        "Confirm whether this bill is already paid.",
                        "Schedule a visible reminder if it is still pending.",
                    ],
                    source_refs=[f"bill:{occurrence.bill_id}", occurrence.reminder_id],
                    created_at=datetime.now(timezone.utc),
                )
            )
        return findings

    def _opportunity_findings(self, request: RadarScanRequest) -> list[RadarFinding]:
        sources = self._matching_knowledge(request.session_id, self.OPPORTUNITY_KEYWORDS)
        context_match = self._contains_any(request.context_text, self.OPPORTUNITY_KEYWORDS)
        findings: list[RadarFinding] = []
        if sources or context_match:
            refs = [f"knowledge:{artifact.artifact_id}" for artifact in sources[:5]]
            if context_match:
                refs.append("context_text")
            findings.append(
                RadarFinding(
                    finding_id=uuid4().hex[:12],
                    finding_type=RadarFindingType.OPPORTUNITY,
                    title="Opportunity worth checking",
                    description="Jarvis found opportunity-related signals in your notes or current context.",
                    severity="medium",
                    confidence=0.74,
                    recommended_actions=[
                        "Extract deadline, eligibility, documents needed, and application link.",
                        "Create a task plan if this opportunity matches your goals.",
                    ],
                    source_refs=refs,
                    created_at=datetime.now(timezone.utc),
                )
            )
        return findings

    def _risk_findings(self, request: RadarScanRequest) -> list[RadarFinding]:
        sources = self._matching_knowledge(request.session_id, self.RISK_KEYWORDS)
        context_match = self._contains_any(request.context_text, self.RISK_KEYWORDS)
        findings: list[RadarFinding] = []
        if sources or context_match:
            refs = [f"knowledge:{artifact.artifact_id}" for artifact in sources[:5]]
            if context_match:
                refs.append("context_text")
            findings.append(
                RadarFinding(
                    finding_id=uuid4().hex[:12],
                    finding_type=RadarFindingType.RISK,
                    title="Personal risk signal detected",
                    description=(
                        "Recent context suggests a possible academic, workload, or wellbeing risk. "
                        "Treat this as an early warning, not a diagnosis."
                    ),
                    severity="high" if context_match else "medium",
                    confidence=0.72,
                    recommended_actions=[
                        "Break the concern into one next action due today.",
                        "Ask Jarvis to simulate the conversation or plan needed to recover.",
                        "Escalate to a trusted person if this involves health, safety, or serious stress.",
                    ],
                    source_refs=refs,
                    created_at=datetime.now(timezone.utc),
                )
            )
        return findings

    def _matching_knowledge(self, session_id: str, keywords: set[str]):
        artifacts = self._knowledge.list_notes(session_id=session_id, limit=100)
        matches = []
        for artifact in artifacts:
            haystack = f"{artifact.title} {artifact.content} {' '.join(artifact.tags)}".lower()
            if any(keyword in haystack for keyword in keywords):
                matches.append(artifact)
        return matches

    def _contains_any(self, text: str, keywords: set[str]) -> bool:
        lowered = text.lower()
        return any(keyword in lowered for keyword in keywords)

    def _summary(self, findings: list[RadarFinding]) -> str:
        if not findings:
            return "Radar scan complete: no urgent deadline, opportunity, or risk signals found."
        counts: dict[str, int] = {}
        for finding in findings:
            key = finding.finding_type.value
            counts[key] = counts.get(key, 0) + 1
        parts = [f"{count} {kind}" for kind, count in sorted(counts.items())]
        return "Radar scan complete: " + ", ".join(parts) + " finding(s)."

    def _severity_rank(self, severity: str) -> int:
        return {"low": 1, "medium": 2, "high": 3}.get(severity, 0)

    def _save(self, finding: RadarFinding) -> None:
        payload = json.dumps(finding.model_dump(mode="json"))
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO v2_radar_findings (finding_id, payload_json)
                VALUES (?, ?)
                ON CONFLICT(finding_id) DO UPDATE SET payload_json = excluded.payload_json
                """,
                (finding.finding_id, payload),
            )
