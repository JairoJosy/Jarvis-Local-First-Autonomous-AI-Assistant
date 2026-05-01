from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Callable, Iterator

from jarvis.v2.schemas import TaskControlRequest, TaskGraph, TaskStatus, VerificationReport
from jarvis.v2.supervisor import SupervisorAgent


class TaskEngine:
    def __init__(self, db_path: Path, supervisor: SupervisorAgent) -> None:
        self._db_path = db_path
        self._supervisor = supervisor
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
                CREATE TABLE IF NOT EXISTS v2_tasks (
                  task_id TEXT PRIMARY KEY,
                  payload_json TEXT NOT NULL
                )
                """
            )

    def create_task(self, task: TaskGraph) -> TaskGraph:
        with self._lock:
            self._save(task)
        return task

    def get_task(self, task_id: str) -> TaskGraph | None:
        with self._conn() as conn:
            row = conn.execute("SELECT payload_json FROM v2_tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        return TaskGraph.model_validate(json.loads(row["payload_json"]))

    def update_task(self, task_id: str, mutator: Callable[[TaskGraph], TaskGraph]) -> TaskGraph | None:
        with self._lock:
            task = self.get_task(task_id)
            if task is None:
                return None
            updated = mutator(task)
            updated.updated_at = datetime.now(timezone.utc)
            self._save(updated)
            return updated

    def apply_control(self, task_id: str, control: TaskControlRequest) -> TaskGraph | None:
        def mutate(task: TaskGraph) -> TaskGraph:
            if control.action == "pause" and task.status == TaskStatus.RUNNING:
                task.status = TaskStatus.PAUSED
            elif control.action == "resume" and task.status in {TaskStatus.PAUSED, TaskStatus.PENDING}:
                task.status = TaskStatus.RUNNING
            elif control.action == "cancel":
                task.status = TaskStatus.CANCELLED
            elif control.action == "retry" and task.status in {
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
                TaskStatus.REQUIRES_APPROVAL,
            }:
                task.status = TaskStatus.PENDING
                task.last_error = None
                task.result_summary = None
                for step in task.steps:
                    step.status = TaskStatus.PENDING
                    step.verification = None
            return task

        return self.update_task(task_id, mutate)

    def execute_task(self, task_id: str) -> TaskGraph | None:
        def mutate(task: TaskGraph) -> TaskGraph:
            if task.status in {TaskStatus.CANCELLED, TaskStatus.REQUIRES_APPROVAL}:
                return task
            task.status = TaskStatus.RUNNING
            try:
                for step in task.steps:
                    if step.status == TaskStatus.COMPLETED:
                        continue
                    step.status = TaskStatus.RUNNING
                    new_status, evidence, message = self._supervisor.execute_step(step, task.user_text)
                    step.status = new_status
                    step.verification = VerificationReport(
                        passed=new_status == TaskStatus.COMPLETED,
                        checks=[message],
                        evidence=evidence,
                    )
                    task.verification_refs.append(f"step:{step.step_id}")
                if all(step.status == TaskStatus.COMPLETED for step in task.steps):
                    task.status = TaskStatus.COMPLETED
                    task.result_summary = "Task completed with verification."
                else:
                    task.status = TaskStatus.FAILED
                    task.last_error = "One or more steps failed."
            except Exception as exc:
                task.status = TaskStatus.FAILED
                task.last_error = str(exc)
            return task

        return self.update_task(task_id, mutate)

    def _save(self, task: TaskGraph) -> None:
        payload = json.dumps(task.model_dump(mode="json"))
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO v2_tasks (task_id, payload_json)
                VALUES (?, ?)
                ON CONFLICT(task_id) DO UPDATE SET payload_json = excluded.payload_json
                """,
                (task.task_id, payload),
            )
