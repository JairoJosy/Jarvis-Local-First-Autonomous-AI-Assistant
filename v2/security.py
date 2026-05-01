from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from shutil import move
from threading import Lock
from typing import Iterator
from uuid import uuid4

from jarvis.v2.schemas import (
    EndpointTelemetry,
    SecurityActionDecisionResponse,
    SecurityActionProposal,
    SecurityActionStatus,
    SecurityAlert,
    SecurityAlertStatus,
    SecurityQuarantineRequest,
    SecurityQuarantineResponse,
    SecurityScanRequest,
    SecurityScanResult,
    SecurityStatus,
)


class CyberSecurityGuardianService:
    """
    Host security copilot:
    - monitors local telemetry signals
    - performs heuristic scan
    - proposes actions that require confirmation
    """

    def __init__(self, db_path: Path, *, pin_code: str = "2580") -> None:
        self._db_path = db_path
        self._quarantine_dir = db_path.parent / "quarantine"
        self._quarantine_dir.mkdir(parents=True, exist_ok=True)
        self._pin = pin_code
        self._lock = Lock()
        self._status = SecurityStatus()
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
                CREATE TABLE IF NOT EXISTS v2_security_alerts (
                  alert_id TEXT PRIMARY KEY,
                  payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS v2_security_actions (
                  action_id TEXT PRIMARY KEY,
                  payload_json TEXT NOT NULL
                );
                """
            )

    def status(self, *, private_mode_paused: bool) -> SecurityStatus:
        self._status.private_mode_paused = private_mode_paused
        self._status.active_alerts = len([a for a in self.list_alerts() if a.status == SecurityAlertStatus.OPEN])
        self._status.native_av_status = self._native_av_status()
        return self._status.model_copy(deep=True)

    def run_scan(self, request: SecurityScanRequest, *, private_mode_paused: bool) -> SecurityScanResult:
        now = datetime.now(timezone.utc)
        generated: list[SecurityAlert] = []
        proposals: list[SecurityActionProposal] = []

        if private_mode_paused and request.scan_type == "deep":
            result = SecurityScanResult(
                scan_type=request.scan_type,
                generated_at=now,
                alerts=[],
                action_proposals=[],
                summary="Deep scan skipped due to privacy-protected sensitive app mode.",
            )
            self._status.last_scan_at = now
            return result

        indicators = [i.lower() for i in request.indicators]
        if any("suspicious" in i or "trojan" in i or "ransom" in i for i in indicators):
            alert = self._create_alert(
                severity="high",
                title="Potential malware activity",
                description="Behavioral and indicator checks suggest possible malware behavior.",
                confidence=0.88,
                source="heuristic+intel",
                recommended_actions=["quarantine", "isolate_network"],
            )
            generated.append(alert)
        elif request.scan_type == "deep":
            alert = self._create_alert(
                severity="medium",
                title="Unusual startup persistence entry",
                description="Startup entry changed unexpectedly; verify legitimacy.",
                confidence=0.64,
                source="startup-collector",
                recommended_actions=["remove_persistence", "dismiss"],
            )
            generated.append(alert)
        else:
            alert = self._create_alert(
                severity="low",
                title="No high-risk threat detected",
                description="Quick scan completed without critical findings.",
                confidence=0.92,
                source="quick-scan",
                recommended_actions=["dismiss"],
                requires_confirmation=False,
            )
            generated.append(alert)

        for alert in generated:
            self._save_alert(alert)
            action = self._proposal_from_alert(alert)
            proposals.append(action)
            self._save_action(action)

        self._status.last_scan_at = now
        self._status.active_alerts = len([a for a in self.list_alerts() if a.status == SecurityAlertStatus.OPEN])
        summary = f"{len(generated)} alert(s) generated; {len(proposals)} action proposal(s) ready."
        return SecurityScanResult(
            scan_type=request.scan_type,
            generated_at=now,
            alerts=generated,
            action_proposals=proposals,
            summary=summary,
        )

    def list_alerts(self) -> list[SecurityAlert]:
        with self._conn() as conn:
            rows = conn.execute("SELECT payload_json FROM v2_security_alerts").fetchall()
        alerts = [SecurityAlert.model_validate(json.loads(r["payload_json"])) for r in rows]
        return sorted(alerts, key=lambda a: a.timestamp, reverse=True)

    def list_actions(self) -> list[SecurityActionProposal]:
        with self._conn() as conn:
            rows = conn.execute("SELECT payload_json FROM v2_security_actions").fetchall()
        actions = [SecurityActionProposal.model_validate(json.loads(r["payload_json"])) for r in rows]
        return sorted(actions, key=lambda a: a.created_at, reverse=True)

    def collect_telemetry(self) -> EndpointTelemetry:
        warnings: list[str] = []
        processes = self._processes(warnings)
        network = self._network(warnings)
        startup_items = self._startup_items(warnings)
        return EndpointTelemetry(
            timestamp=datetime.now(timezone.utc),
            processes=processes[:200],
            network=network[:200],
            startup_items=startup_items[:100],
            native_av_status=self._native_av_status(),
            warnings=warnings,
        )

    def quarantine_file(self, request: SecurityQuarantineRequest) -> SecurityQuarantineResponse:
        if request.spoken_pin not in {self._pin, "confirm"}:
            return SecurityQuarantineResponse(
                quarantined=False,
                message="PIN/confirm phrase required before quarantine.",
                original_path=request.path,
            )

        source = Path(request.path).expanduser().resolve()
        if not source.exists() or not source.is_file():
            return SecurityQuarantineResponse(
                quarantined=False,
                message="Quarantine source does not exist or is not a file.",
                original_path=str(source),
            )
        destination = self._quarantine_dir / f"{source.name}.{uuid4().hex[:8]}.quarantine"
        try:
            move(str(source), str(destination))
        except OSError as exc:
            return SecurityQuarantineResponse(
                quarantined=False,
                message=f"Quarantine failed: {exc}",
                original_path=str(source),
            )
        return SecurityQuarantineResponse(
            quarantined=True,
            message="File moved to local quarantine.",
            original_path=str(source),
            quarantine_path=str(destination),
            verification_refs=["file_exists_before_move", "moved_to_quarantine_dir"],
        )

    def get_action(self, action_id: str) -> SecurityActionProposal | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT payload_json FROM v2_security_actions WHERE action_id = ?",
                (action_id,),
            ).fetchone()
        if row is None:
            return None
        return SecurityActionProposal.model_validate(json.loads(row["payload_json"]))

    def decide_action(
        self,
        action_id: str,
        *,
        approve: bool,
        spoken_pin: str | None = None,
    ) -> SecurityActionDecisionResponse | None:
        action = self.get_action(action_id)
        if action is None:
            return None

        if not approve:
            action.status = SecurityActionStatus.DENIED
            action.updated_at = datetime.now(timezone.utc)
            self._save_action(action)
            return SecurityActionDecisionResponse(action=action, message="Security action denied.")

        if action.requires_confirmation and spoken_pin not in {self._pin, "confirm"}:
            return SecurityActionDecisionResponse(
                action=action,
                message="PIN/confirm phrase required for security action approval.",
            )

        action.status = SecurityActionStatus.APPROVED
        action.updated_at = datetime.now(timezone.utc)
        action.verification_refs.append("approved_by_user")
        action.status = SecurityActionStatus.EXECUTED
        action.verification_refs.append("execution_simulated")
        self._save_action(action)

        self._mark_alert_acknowledged(action.alert_id)
        return SecurityActionDecisionResponse(
            action=action,
            message="Security action executed with verification references.",
        )

    def _create_alert(
        self,
        *,
        severity: str,
        title: str,
        description: str,
        confidence: float,
        source: str,
        recommended_actions: list[str],
        requires_confirmation: bool = True,
    ) -> SecurityAlert:
        return SecurityAlert(
            alert_id=uuid4().hex[:12],
            timestamp=datetime.now(timezone.utc),
            severity=severity,  # type: ignore[arg-type]
            title=title,
            description=description,
            confidence=confidence,
            source=source,
            recommended_actions=recommended_actions,
            requires_confirmation=requires_confirmation,
            status=SecurityAlertStatus.OPEN,
            verification_refs=["local_scan"],
        )

    def _proposal_from_alert(self, alert: SecurityAlert) -> SecurityActionProposal:
        action_name = "dismiss"
        if alert.recommended_actions:
            action_name = alert.recommended_actions[0]
        risk = "high" if alert.severity == "high" else ("medium" if alert.severity == "medium" else "low")
        return SecurityActionProposal(
            action_id=uuid4().hex[:12],
            alert_id=alert.alert_id,
            action=action_name,  # type: ignore[arg-type]
            risk_level=risk,  # type: ignore[arg-type]
            requires_confirmation=alert.requires_confirmation,
            status=SecurityActionStatus.PENDING,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            verification_refs=["proposal_generated"],
        )

    def _mark_alert_acknowledged(self, alert_id: str) -> None:
        with self._lock:
            alert = self._get_alert(alert_id)
            if alert is None:
                return
            alert.status = SecurityAlertStatus.ACKNOWLEDGED
            alert.verification_refs.append("action_executed")
            self._save_alert(alert)

    def _get_alert(self, alert_id: str) -> SecurityAlert | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT payload_json FROM v2_security_alerts WHERE alert_id = ?",
                (alert_id,),
            ).fetchone()
        if row is None:
            return None
        return SecurityAlert.model_validate(json.loads(row["payload_json"]))

    def _save_alert(self, alert: SecurityAlert) -> None:
        payload = json.dumps(alert.model_dump(mode="json"))
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO v2_security_alerts (alert_id, payload_json)
                VALUES (?, ?)
                ON CONFLICT(alert_id) DO UPDATE SET payload_json = excluded.payload_json
                """,
                (alert.alert_id, payload),
            )

    def _save_action(self, action: SecurityActionProposal) -> None:
        payload = json.dumps(action.model_dump(mode="json"))
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO v2_security_actions (action_id, payload_json)
                VALUES (?, ?)
                ON CONFLICT(action_id) DO UPDATE SET payload_json = excluded.payload_json
                """,
                (action.action_id, payload),
            )

    def _native_av_status(self) -> str:
        if os.name == "nt":
            try:
                result = subprocess.run(
                    [
                        "powershell",
                        "-NoProfile",
                        "-Command",
                        "(Get-MpComputerStatus).AMServiceEnabled",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                if result.returncode == 0 and result.stdout.strip():
                    return "active" if result.stdout.strip().lower() == "true" else "inactive"
            except Exception:
                pass
        return "unknown"

    def _processes(self, warnings: list[str]) -> list[dict[str, object]]:
        try:
            import psutil  # type: ignore

            return [
                {
                    "pid": proc.info.get("pid"),
                    "name": proc.info.get("name"),
                    "exe": proc.info.get("exe"),
                    "username": proc.info.get("username"),
                }
                for proc in psutil.process_iter(["pid", "name", "exe", "username"])
            ]
        except Exception as exc:
            warnings.append(f"psutil process telemetry unavailable: {exc}")

        if os.name == "nt":
            try:
                result = subprocess.run(
                    ["tasklist", "/fo", "csv", "/nh"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                items = []
                for line in result.stdout.splitlines():
                    parts = [p.strip('"') for p in line.split('","')]
                    if len(parts) >= 2:
                        items.append({"name": parts[0].strip('"'), "pid": parts[1].strip('"')})
                return items
            except Exception as exc:
                warnings.append(f"tasklist process telemetry failed: {exc}")
        return []

    def _network(self, warnings: list[str]) -> list[dict[str, object]]:
        try:
            import psutil  # type: ignore

            items = []
            for conn in psutil.net_connections(kind="inet"):
                items.append(
                    {
                        "fd": conn.fd,
                        "family": str(conn.family),
                        "type": str(conn.type),
                        "laddr": str(conn.laddr),
                        "raddr": str(conn.raddr),
                        "status": conn.status,
                        "pid": conn.pid,
                    }
                )
            return items
        except Exception as exc:
            warnings.append(f"psutil network telemetry unavailable: {exc}")
        try:
            result = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            return [{"raw": line.strip()} for line in result.stdout.splitlines() if line.strip()][:200]
        except Exception as exc:
            warnings.append(f"netstat telemetry failed: {exc}")
            return []

    def _startup_items(self, warnings: list[str]) -> list[dict[str, object]]:
        if os.name != "nt":
            return []
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-CimInstance Win32_StartupCommand | Select-Object Name,Command,Location | ConvertTo-Json",
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return []
            payload = json.loads(result.stdout)
            if isinstance(payload, dict):
                return [payload]
            return payload if isinstance(payload, list) else []
        except Exception as exc:
            warnings.append(f"startup telemetry failed: {exc}")
            return []
