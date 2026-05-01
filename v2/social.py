from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Iterator
from uuid import uuid4

from jarvis.v2.schemas import (
    ConversationCoachRequest,
    ConversationCoachResponse,
    InterviewAnswerRequest,
    SocialDraft,
    SocialDraftRequest,
    SocialDraftScenario,
)


class SocialIntelligenceService:
    """
    Local-first social assistant for drafts, interview answers, and conversation prep.
    Cloud LLM adapters can later replace the deterministic composer behind this contract.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
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
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS v2_social_drafts (
                  draft_id TEXT PRIMARY KEY,
                  payload_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS v2_social_coach_records (
                  coach_id TEXT PRIMARY KEY,
                  payload_json TEXT NOT NULL
                );
                """
            )

    def draft_message(self, request: SocialDraftRequest) -> SocialDraft:
        draft = SocialDraft(
            draft_id=uuid4().hex[:12],
            session_id=request.session_id,
            scenario=request.scenario,
            draft=self._compose_draft(request),
            rationale=self._rationale(request),
            suggested_followups=self._followups(request),
            created_at=datetime.now(timezone.utc),
        )
        self._save_draft(draft)
        return draft

    def prepare_interview_answer(self, request: InterviewAnswerRequest) -> SocialDraft:
        goal = f"Answer this interview question: {request.question}"
        if request.target_role:
            goal += f" for {request.target_role}"
        return self.draft_message(
            SocialDraftRequest(
                session_id=request.session_id,
                scenario=SocialDraftScenario.INTERVIEW_ANSWER,
                source_text=request.background,
                goal=goal,
                audience="interviewer",
                tone=request.tone,
                constraints=["Use a grounded, concise STAR-style structure."],
            )
        )

    def coach_conversation(self, request: ConversationCoachRequest) -> ConversationCoachResponse:
        person = request.other_person or "them"
        response = ConversationCoachResponse(
            coach_id=uuid4().hex[:12],
            opening_line=(
                f"I want to talk through {request.situation.strip()} and find a way that works for both of us."
                if request.tone.value != "firm"
                else f"I need to be clear about {request.situation.strip()} and agree on a concrete next step."
            ),
            talking_points=[
                f"Lead with the outcome you want: {request.desired_outcome.strip()}.",
                f"Name what matters to {person} before making your ask.",
                "Keep the next step specific enough that the conversation can actually move.",
            ],
            pitfalls=[
                "Avoid over-explaining before you have named the ask.",
                "Do not guess motives; describe observable behavior and impact.",
                "Leave room for new information instead of locking into one script.",
            ],
            suggested_replies=[
                "That makes sense. Here is what I can do next.",
                "Can we agree on one concrete step before we end this?",
                "I may be missing context, so I want to check my understanding.",
            ],
            confidence=0.78,
            rationale="Uses a low-drama structure: acknowledge context, state goal, ask for a specific next step.",
            created_at=datetime.now(timezone.utc),
        )
        self._save_coach(response)
        return response

    def get_draft(self, draft_id: str) -> SocialDraft | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT payload_json FROM v2_social_drafts WHERE draft_id = ?",
                (draft_id,),
            ).fetchone()
        if row is None:
            return None
        return SocialDraft.model_validate(json.loads(row["payload_json"]))

    def _compose_draft(self, request: SocialDraftRequest) -> str:
        if request.scenario == SocialDraftScenario.INTERVIEW_ANSWER:
            background = request.source_text.strip()
            core = background if background else "my background, strongest projects, and the work I am ready to grow into"
            return (
                "A polished answer:\n"
                f"Thank you for asking. I would describe myself through {core}. "
                "I am strongest when I can learn quickly, build carefully, and keep improving the result through feedback. "
                "One example I would highlight is a project where I had to understand the problem, create a practical plan, "
                "and turn it into a working outcome. What interests me most about this opportunity is the chance to apply "
                "that discipline in a higher-standard environment while continuing to grow."
            )

        greeting = self._greeting(request.audience)
        source_ack = ""
        if request.source_text.strip():
            source_ack = "Thank you for the context. I understand the main point and want to respond clearly.\n\n"
        constraints = " ".join(request.constraints)
        signoff = "Best regards"
        if request.tone.value in {"friendly", "warm", "witty"}:
            signoff = "Warmly"
        if request.tone.value == "firm":
            signoff = "Regards"
        draft = (
            f"{greeting}\n\n"
            f"{source_ack}"
            f"{request.goal.strip()} "
            "I appreciate your time, and I would like to keep the next step clear and easy to act on."
        )
        if constraints:
            draft += f"\n\nI have kept this aligned with: {constraints}."
        return f"{draft}\n\n{signoff},\n[Your Name]"

    def _greeting(self, audience: str) -> str:
        normalized = audience.strip()
        if not normalized:
            return "Hello,"
        if "professor" in normalized.lower():
            return "Dear Professor,"
        return f"Hi {normalized},"

    def _rationale(self, request: SocialDraftRequest) -> str:
        return (
            f"Composed for {request.scenario.value} with a {request.tone.value} tone, "
            "keeping the ask explicit and avoiding invented personal details."
        )

    def _followups(self, request: SocialDraftRequest) -> list[str]:
        if request.scenario == SocialDraftScenario.INTERVIEW_ANSWER:
            return [
                "Prepare one concrete project example with problem, action, and result.",
                "Practice a 45-second version and a 90-second version.",
            ]
        return [
            "Ask Jarvis to make this shorter or more direct.",
            "Ask for a warmer, firmer, or more professional variant.",
        ]

    def _save_draft(self, draft: SocialDraft) -> None:
        payload = json.dumps(draft.model_dump(mode="json"))
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO v2_social_drafts (draft_id, payload_json)
                VALUES (?, ?)
                ON CONFLICT(draft_id) DO UPDATE SET payload_json = excluded.payload_json
                """,
                (draft.draft_id, payload),
            )

    def _save_coach(self, response: ConversationCoachResponse) -> None:
        payload = json.dumps(response.model_dump(mode="json"))
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO v2_social_coach_records (coach_id, payload_json)
                VALUES (?, ?)
                ON CONFLICT(coach_id) DO UPDATE SET payload_json = excluded.payload_json
                """,
                (response.coach_id, payload),
            )
