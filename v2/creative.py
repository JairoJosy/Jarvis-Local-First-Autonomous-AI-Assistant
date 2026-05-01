from __future__ import annotations

import json
import sqlite3
import subprocess
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from shutil import which
from threading import Lock
from typing import Iterator
from uuid import uuid4

from jarvis.v2.schemas import (
    CreativeJob,
    CreativeJobRequest,
    CreativeJobStatus,
    CreativeStep,
    CreativeStepStatus,
)


class CreativeCopilotService:
    """
    Hybrid creative engine:
    - produces edit recommendations
    - applies reversible step plan
    - emits versioned outputs
    """

    def __init__(self, db_path: Path, *, ffmpeg_path: str = "ffmpeg") -> None:
        self._db_path = db_path
        self._ffmpeg_path = ffmpeg_path
        self._output_dir = db_path.parent / "creative_outputs"
        self._output_dir.mkdir(parents=True, exist_ok=True)
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
                CREATE TABLE IF NOT EXISTS v2_creative_jobs (
                  job_id TEXT PRIMARY KEY,
                  payload_json TEXT NOT NULL
                )
                """
            )

    def create_job(self, request: CreativeJobRequest) -> CreativeJob:
        now = datetime.now(timezone.utc)
        job = CreativeJob(
            job_id=uuid4().hex[:12],
            session_id=request.session_id,
            job_type=request.job_type,
            instructions=request.instructions,
            status=CreativeJobStatus.QUEUED,
            steps=self._recommended_steps(request),
            recommendations=self._recommendations(request),
            created_at=now,
            updated_at=now,
            reversible=True,
        )
        self._save(job)

        if request.auto_apply:
            job = self._execute(job, input_path=request.input_path)
            self._save(job)
        return job

    def get_job(self, job_id: str) -> CreativeJob | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT payload_json FROM v2_creative_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        return CreativeJob.model_validate(json.loads(row["payload_json"]))

    def _execute(self, job: CreativeJob, *, input_path: str | None) -> CreativeJob:
        job.status = CreativeJobStatus.RUNNING
        real_outputs = self._real_pipeline(job, input_path=input_path)
        base_name = input_path or f"{job.job_type.value}_artifact"
        outputs: list[str] = []
        for idx, step in enumerate(job.steps, start=1):
            step.status = CreativeStepStatus.APPLIED
            version = real_outputs[idx - 1] if idx - 1 < len(real_outputs) else f"{base_name}.v{idx}"
            step.output_ref = version
            step.notes = (
                f"Applied using {step.tool} with reversible params."
                if real_outputs
                else f"Planned output reference using {step.tool}; no real input pipeline was available."
            )
            outputs.append(version)
        job.version_outputs = outputs
        job.status = CreativeJobStatus.COMPLETED
        job.updated_at = datetime.now(timezone.utc)
        return job

    def _real_pipeline(self, job: CreativeJob, *, input_path: str | None) -> list[str]:
        if not input_path:
            return []
        source = Path(input_path).expanduser()
        if not source.exists() or not source.is_file():
            return []
        if job.job_type.value == "photo":
            return self._photo_pipeline(job, source)
        if job.job_type.value == "video":
            return self._video_pipeline(job, source)
        return []

    def _photo_pipeline(self, job: CreativeJob, source: Path) -> list[str]:
        try:
            from PIL import Image, ImageEnhance, ImageFilter  # type: ignore
        except Exception:
            return []
        outputs: list[str] = []
        image = Image.open(source).convert("RGB")
        variants = [
            ImageEnhance.Brightness(image).enhance(1.08),
            ImageEnhance.Contrast(image).enhance(1.12),
            image.filter(ImageFilter.UnsharpMask(radius=1.2, percent=120, threshold=3)),
        ]
        for idx, variant in enumerate(variants, start=1):
            output = self._output_dir / f"{job.job_id}_photo_v{idx}.jpg"
            variant.save(output, quality=92)
            outputs.append(str(output))
        return outputs

    def _video_pipeline(self, job: CreativeJob, source: Path) -> list[str]:
        ffmpeg = self._ffmpeg_path if which(self._ffmpeg_path) else None
        if not ffmpeg:
            return []
        output = self._output_dir / f"{job.job_id}_video_v1.mp4"
        command = [
            ffmpeg,
            "-y",
            "-i",
            str(source),
            "-vf",
            "eq=contrast=1.05:brightness=0.03",
            "-c:a",
            "copy",
            str(output),
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
        except Exception:
            return []
        return [str(output)] if result.returncode == 0 and output.exists() else []

    def _recommended_steps(self, request: CreativeJobRequest) -> list[CreativeStep]:
        common = [
            CreativeStep(
                step_id=uuid4().hex[:8],
                title="Analyze input and generate edit strategy",
                tool="local_analyzer",
                status=CreativeStepStatus.PLANNED,
                reversible=True,
            ),
            CreativeStep(
                step_id=uuid4().hex[:8],
                title="Apply primary transformation",
                tool="hybrid_transformer",
                status=CreativeStepStatus.PLANNED,
                reversible=True,
            ),
        ]
        if request.job_type.value == "photo":
            common.append(
                CreativeStep(
                    step_id=uuid4().hex[:8],
                    title="Color grading and retouch pass",
                    tool="image_pipeline",
                    status=CreativeStepStatus.PLANNED,
                    reversible=True,
                )
            )
        elif request.job_type.value == "video":
            common.append(
                CreativeStep(
                    step_id=uuid4().hex[:8],
                    title="Timeline cut and motion polish",
                    tool="video_pipeline",
                    status=CreativeStepStatus.PLANNED,
                    reversible=True,
                )
            )
        elif request.job_type.value == "design":
            common.append(
                CreativeStep(
                    step_id=uuid4().hex[:8],
                    title="Layout and typography refinement",
                    tool="design_pipeline",
                    status=CreativeStepStatus.PLANNED,
                    reversible=True,
                )
            )
        else:
            common.append(
                CreativeStep(
                    step_id=uuid4().hex[:8],
                    title="Debug and code quality improvements",
                    tool="code_pipeline",
                    status=CreativeStepStatus.PLANNED,
                    reversible=True,
                )
            )
        return common

    def _recommendations(self, request: CreativeJobRequest) -> list[str]:
        base = [
            "Create reversible checkpoints before each major edit.",
            "Export side-by-side before/after variants for review.",
            "Keep color and typography consistent with brand style.",
        ]
        if request.job_type.value == "code_assist":
            base = [
                "Run tests before and after applying fixes.",
                "Capture stack trace and isolate failing modules first.",
                "Prefer minimal, verifiable code changes.",
            ]
        return base

    def _save(self, job: CreativeJob) -> None:
        payload = json.dumps(job.model_dump(mode="json"))
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO v2_creative_jobs (job_id, payload_json)
                VALUES (?, ?)
                ON CONFLICT(job_id) DO UPDATE SET payload_json = excluded.payload_json
                """,
                (job.job_id, payload),
            )
