from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Iterator
from uuid import uuid4

from jarvis.v2.schemas import SimulationRequest, SimulationRun, SimulationTurn, SimulationType


class SimulationEngineService:
    """
    Practice engine for interviews, debates, and decision outcomes.
    The first version is deterministic so the flow is testable and safe.
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS v2_simulation_runs (
                  run_id TEXT PRIMARY KEY,
                  payload_json TEXT NOT NULL
                )
                """
            )

    def create_run(self, request: SimulationRequest) -> SimulationRun:
        run = SimulationRun(
            run_id=uuid4().hex[:12],
            session_id=request.session_id,
            simulation_type=request.simulation_type,
            prompt=request.prompt,
            turns=self._build_turns(request),
            scorecard=self._scorecard(request),
            created_at=datetime.now(timezone.utc),
        )
        self._save(run)
        return run

    def get_run(self, run_id: str) -> SimulationRun | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT payload_json FROM v2_simulation_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return SimulationRun.model_validate(json.loads(row["payload_json"]))

    def _build_turns(self, request: SimulationRequest) -> list[SimulationTurn]:
        if request.simulation_type == SimulationType.INTERVIEW:
            return self._interview_turns(request)
        if request.simulation_type == SimulationType.DEBATE:
            return self._debate_turns(request)
        return self._decision_turns(request)

    def _interview_turns(self, request: SimulationRequest) -> list[SimulationTurn]:
        prompts = [
            "Tell me about yourself in a way that connects to this opportunity.",
            "Describe a time you handled pressure or ambiguity.",
            "Why should we select you over another capable candidate?",
            "What is one weakness you are actively improving?",
            "What would you do in your first month if selected?",
        ]
        turns: list[SimulationTurn] = []
        for idx in range(request.rounds):
            question = prompts[idx % len(prompts)]
            turns.append(
                SimulationTurn(
                    turn_index=idx + 1,
                    role="interviewer",
                    message=f"{question} Context: {request.prompt}",
                    feedback="Answer with one clear example, measurable impact if available, and a calm closing line.",
                )
            )
        return turns

    def _debate_turns(self, request: SimulationRequest) -> list[SimulationTurn]:
        stance = request.stance or "your idea"
        angles = [
            "assumption risk",
            "cost and execution difficulty",
            "long-term consequences",
            "counterexample from a realistic edge case",
        ]
        return [
            SimulationTurn(
                turn_index=idx + 1,
                role="opponent",
                message=f"I will challenge {stance} through {angles[idx % len(angles)]}: {request.prompt}",
                feedback="Respond by steelmanning the concern first, then narrow the claim and offer evidence.",
            )
            for idx in range(request.rounds)
        ]

    def _decision_turns(self, request: SimulationRequest) -> list[SimulationTurn]:
        frames = [
            "best-case outcome",
            "worst-case outcome",
            "most likely tradeoff",
            "reversible experiment",
        ]
        return [
            SimulationTurn(
                turn_index=idx + 1,
                role="scenario",
                message=f"Decision lens: {frames[idx % len(frames)]} for {request.prompt}",
                feedback="Look for reversible next steps, hidden costs, and what evidence would change your mind.",
            )
            for idx in range(request.rounds)
        ]

    def _scorecard(self, request: SimulationRequest) -> dict[str, object]:
        if request.simulation_type == SimulationType.INTERVIEW:
            return {
                "clarity": "Practice direct openings.",
                "evidence": "Prepare two concrete examples.",
                "presence": "Keep answers calm, concise, and grounded.",
                "confidence": 0.8,
            }
        if request.simulation_type == SimulationType.DEBATE:
            return {
                "logic": "Separate assumptions from conclusions.",
                "counterplay": "Answer the strongest objection first.",
                "confidence": 0.78,
            }
        return {
            "option_quality": "Compare upside, downside, reversibility, and timing.",
            "decision_rule": "Choose the step that creates useful evidence fastest.",
            "confidence": 0.76,
        }

    def _save(self, run: SimulationRun) -> None:
        payload = json.dumps(run.model_dump(mode="json"))
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO v2_simulation_runs (run_id, payload_json)
                VALUES (?, ?)
                ON CONFLICT(run_id) DO UPDATE SET payload_json = excluded.payload_json
                """,
                (run.run_id, payload),
            )
