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

from jarvis.v2.approvals import ApprovalCenter
from jarvis.v2.schemas import (
    DeviceActionRecord,
    DeviceActionRequest,
    DeviceActionStatus,
    DevicePlatform,
    VerificationReport,
)


class DeviceControlService:
    SENSITIVE_ACTIONS = {"delete_file", "send_message", "pay_bill", "factory_reset", "shutdown", "purchase"}

    def __init__(self, db_path: Path, approvals: ApprovalCenter, *, adb_path: str = "adb") -> None:
        self._db_path = db_path
        self._approvals = approvals
        self._adb_path = adb_path
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
                CREATE TABLE IF NOT EXISTS v2_device_actions (
                  action_id TEXT PRIMARY KEY,
                  payload_json TEXT NOT NULL
                )
                """
            )

    def create_action(self, request: DeviceActionRequest) -> DeviceActionRecord:
        action_id = uuid4().hex[:12]
        now = datetime.now(timezone.utc)
        action = DeviceActionRecord(
            action_id=action_id,
            session_id=request.session_id,
            platform=request.platform,
            action=request.action,
            parameters=request.parameters,
            status=DeviceActionStatus.PENDING,
            created_at=now,
            updated_at=now,
            message="Action accepted.",
        )

        is_sensitive = request.sensitive or request.action.lower() in self.SENSITIVE_ACTIONS
        if is_sensitive:
            approval = self._approvals.create_card(
                source="device_action",
                summary=f"Approve {request.platform.value} action: {request.action}",
                risk_level="high",
                requires_pin=True,
                metadata={"action_id": action_id},
            )
            action.status = DeviceActionStatus.REQUIRES_APPROVAL
            action.approval_id = approval.approval_id
            action.message = "Approval required before executing action."
            self._save(action)
            return action

        executed = self._execute(action)
        self._save(executed)
        return executed

    def get_action(self, action_id: str) -> DeviceActionRecord | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT payload_json FROM v2_device_actions WHERE action_id = ?",
                (action_id,),
            ).fetchone()
        if row is None:
            return None
        return DeviceActionRecord.model_validate(json.loads(row["payload_json"]))

    def execute_approved_action(self, action_id: str) -> DeviceActionRecord | None:
        with self._lock:
            action = self.get_action(action_id)
            if action is None:
                return None
            if action.status != DeviceActionStatus.REQUIRES_APPROVAL:
                return action
            executed = self._execute(action)
            self._save(executed)
            return executed

    def _execute(self, action: DeviceActionRecord) -> DeviceActionRecord:
        platform = action.platform
        if platform == DevicePlatform.PC:
            success, checks, evidence = self._execute_pc(action)
        else:
            success, checks, evidence = self._execute_android(action)
        action.status = DeviceActionStatus.COMPLETED if success else DeviceActionStatus.FAILED
        action.updated_at = datetime.now(timezone.utc)
        action.verification = VerificationReport(
            passed=success,
            checks=checks,
            evidence={"platform": platform.value, "parameters": action.parameters, **evidence},
        )
        action.message = "Action executed with verification evidence." if success else "Action failed; see verification evidence."
        return action

    def _execute_pc(self, action: DeviceActionRecord) -> tuple[bool, list[str], dict]:
        name = action.action.lower()
        params = action.parameters
        if name == "open_app":
            target = str(params.get("app") or params.get("path") or "")
            if not target:
                return False, ["PC open_app requires app/path parameter."], {}
            try:
                subprocess.Popen([target], shell=False)
            except Exception as exc:
                return False, [f"PC open_app failed: {exc}"], {"target": target}
            return True, [f"Opened PC app/path: {target}"], {"target": target}
        if name == "type_text":
            text = str(params.get("text") or "")
            return self._send_keys(text)
        if name == "hotkey":
            keys = str(params.get("keys") or "")
            return self._send_keys(keys)
        return False, [f"Unsupported PC action: {action.action}"], {}

    def _send_keys(self, text: str) -> tuple[bool, list[str], dict]:
        if not text:
            return False, ["No text/keys provided for SendKeys."], {}
        escaped = text.replace("'", "''")
        script = (
            "Add-Type -AssemblyName System.Windows.Forms;"
            f"[System.Windows.Forms.SendKeys]::SendWait('{escaped}')"
        )
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except Exception as exc:
            return False, [f"SendKeys failed: {exc}"], {"text_length": len(text)}
        return (
            result.returncode == 0,
            ["Sent keys through Windows Forms SendKeys." if result.returncode == 0 else result.stderr.strip()],
            {"returncode": result.returncode, "text_length": len(text)},
        )

    def _execute_android(self, action: DeviceActionRecord) -> tuple[bool, list[str], dict]:
        adb = self._adb_path if which(self._adb_path) else None
        if not adb:
            return False, ["ADB executable not found. Install Android platform-tools or set adb_path."], {}
        name = action.action.lower()
        params = action.parameters
        command = [adb]
        if params.get("device_id"):
            command.extend(["-s", str(params["device_id"])])
        if name == "tap":
            command.extend(["shell", "input", "tap", str(params.get("x", "")), str(params.get("y", ""))])
        elif name == "type_text":
            text = str(params.get("text") or "").replace(" ", "%s")
            command.extend(["shell", "input", "text", text])
        elif name == "keyevent":
            command.extend(["shell", "input", "keyevent", str(params.get("keycode", ""))])
        elif name == "open_app":
            package = str(params.get("package") or "")
            if not package:
                return False, ["Android open_app requires package parameter."], {}
            command.extend(["shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"])
        else:
            return False, [f"Unsupported Android action: {action.action}"], {}

        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=15, check=False)
        except Exception as exc:
            return False, [f"ADB action failed: {exc}"], {"command": command}
        output = (result.stdout + "\n" + result.stderr).strip()
        return (
            result.returncode == 0,
            ["ADB command executed." if result.returncode == 0 else output[:500]],
            {"returncode": result.returncode, "command": command, "output": output[:1000]},
        )

    def _save(self, action: DeviceActionRecord) -> None:
        payload = json.dumps(action.model_dump(mode="json"))
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO v2_device_actions (action_id, payload_json)
                VALUES (?, ?)
                ON CONFLICT(action_id) DO UPDATE SET payload_json = excluded.payload_json
                """,
                (action.action_id, payload),
            )
