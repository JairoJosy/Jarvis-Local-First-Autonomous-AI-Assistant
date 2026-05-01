from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Iterator

from jarvis.v2.schemas import (
    PluginExecuteRequest,
    PluginExecuteResponse,
    PluginManifest,
    PluginRegisterRequest,
    PluginRegistryEntry,
)


class LocalPluginStoreService:
    """
    Local plugin catalog for future tools, agents, connectors, and workflows.
    This stores manifests only; runtime loading remains behind explicit capability policy.
    """

    RESERVED_SCOPES = {"system.admin", "security.bypass", "approval.bypass"}

    def __init__(self, db_path: Path, *, signing_secret: str | None = None) -> None:
        self._db_path = db_path
        self._sandbox_dir = db_path.parent / "plugin_sandboxes"
        self._sandbox_dir.mkdir(parents=True, exist_ok=True)
        self._signing_secret = signing_secret
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
                CREATE TABLE IF NOT EXISTS v2_plugin_registry (
                  plugin_id TEXT PRIMARY KEY,
                  payload_json TEXT NOT NULL
                )
                """
            )

    def register(self, request: PluginRegisterRequest) -> PluginRegistryEntry:
        self._validate_manifest(request.manifest)
        existing = self.get(request.manifest.plugin_id)
        entry = PluginRegistryEntry(
            **request.manifest.model_dump(),
            registered_at=existing.registered_at if existing else datetime.now(timezone.utc),
        )
        self._save(entry)
        return entry

    def list_plugins(self) -> list[PluginRegistryEntry]:
        with self._conn() as conn:
            rows = conn.execute("SELECT payload_json FROM v2_plugin_registry").fetchall()
        entries = [PluginRegistryEntry.model_validate(json.loads(row["payload_json"])) for row in rows]
        return sorted(entries, key=lambda item: (item.kind.value, item.name.lower()))

    def get(self, plugin_id: str) -> PluginRegistryEntry | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT payload_json FROM v2_plugin_registry WHERE plugin_id = ?",
                (plugin_id,),
            ).fetchone()
        if row is None:
            return None
        return PluginRegistryEntry.model_validate(json.loads(row["payload_json"]))

    def execute(self, plugin_id: str, request: PluginExecuteRequest) -> PluginExecuteResponse:
        entry = self.get(plugin_id)
        if entry is None:
            return PluginExecuteResponse(plugin_id=plugin_id, executed=False, message="Plugin not found.")
        if not entry.enabled:
            return PluginExecuteResponse(plugin_id=plugin_id, executed=False, message="Plugin is disabled.")

        entrypoint = Path(entry.entrypoint)
        if entrypoint.exists():
            command = [sys.executable, str(entrypoint.resolve())]
        else:
            command = [sys.executable, "-m", entry.entrypoint]

        sandbox = self._sandbox_dir / plugin_id
        sandbox.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"action": request.action, "parameters": request.parameters})
        env = {
            "PATH": os.environ.get("PATH", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "TEMP": os.environ.get("TEMP", ""),
            "PYTHONIOENCODING": "utf-8",
            "JARVIS_PLUGIN_ID": plugin_id,
            "JARVIS_PLUGIN_SANDBOX": str(sandbox),
        }
        try:
            result = subprocess.run(
                command,
                input=payload,
                capture_output=True,
                text=True,
                timeout=request.timeout_seconds,
                check=False,
                cwd=str(sandbox),
                env=env,
            )
        except Exception as exc:
            return PluginExecuteResponse(
                plugin_id=plugin_id,
                executed=False,
                message=f"Plugin execution failed before completion: {exc}",
                sandbox={"cwd": str(sandbox), "command": command},
            )

        output: dict = {}
        if result.stdout.strip():
            try:
                parsed = json.loads(result.stdout)
                if isinstance(parsed, dict):
                    output = parsed
            except json.JSONDecodeError:
                output = {}
        return PluginExecuteResponse(
            plugin_id=plugin_id,
            executed=result.returncode == 0,
            message="Plugin executed." if result.returncode == 0 else "Plugin exited with a non-zero code.",
            returncode=result.returncode,
            output=output,
            stdout=result.stdout[:4000],
            stderr=result.stderr[:4000],
            sandbox={"cwd": str(sandbox), "command": command},
        )

    def _validate_manifest(self, manifest: PluginManifest) -> None:
        scopes = {scope.lower() for scope in manifest.scopes}
        blocked = scopes.intersection(self.RESERVED_SCOPES)
        if blocked:
            blocked_list = ", ".join(sorted(blocked))
            raise ValueError(f"Plugin requests reserved scope(s): {blocked_list}")
        if manifest.entrypoint.startswith(("http://", "https://")):
            raise ValueError("v2.5 plugin entrypoints must be local paths or local module names.")
        if manifest.sha256:
            entrypoint = Path(manifest.entrypoint)
            if entrypoint.exists():
                digest = hashlib.sha256(entrypoint.read_bytes()).hexdigest()
                if digest.lower() != manifest.sha256.lower():
                    raise ValueError("Plugin entrypoint sha256 does not match manifest.")
        if self._signing_secret and manifest.signature:
            expected = self._signature(manifest)
            if not hmac.compare_digest(expected, manifest.signature):
                raise ValueError("Plugin signature verification failed.")
        elif self._signing_secret and not manifest.signature:
            raise ValueError("Plugin signature is required when signing is enabled.")

    def _signature(self, manifest: PluginManifest) -> str:
        payload = manifest.model_dump(mode="json")
        payload["signature"] = None
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hmac.new(self._signing_secret.encode("utf-8"), encoded, hashlib.sha256).hexdigest()

    def _save(self, entry: PluginRegistryEntry) -> None:
        payload = json.dumps(entry.model_dump(mode="json"))
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO v2_plugin_registry (plugin_id, payload_json)
                VALUES (?, ?)
                ON CONFLICT(plugin_id) DO UPDATE SET payload_json = excluded.payload_json
                """,
                (entry.plugin_id, payload),
            )
