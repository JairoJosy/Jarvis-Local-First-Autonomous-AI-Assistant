from __future__ import annotations

import re
import subprocess

from pydantic import BaseModel, Field

from jarvis.schemas import ToolResult
from jarvis.tools.base import BaseTool


class ShellCommandParams(BaseModel):
    command: str = Field(min_length=1, max_length=512)
    timeout_seconds: int = Field(default=15, ge=1, le=60)


class ShellCommandTool(BaseTool):
    name = "shell_command"
    description = "Execute guarded shell commands. Explicit approval required."
    risk_level = "tier3"
    mutating = True
    params_model = ShellCommandParams

    BLOCKLIST = (
        r"\brm\b",
        r"\bdel\b",
        r"\bformat\b",
        r"Remove-Item",
        r"Stop-Computer",
        r"Restart-Computer",
        r"shutdown",
        r"reg\s+delete",
    )

    def execute(self, parameters: ShellCommandParams, context: dict) -> ToolResult:
        command = parameters.command.strip()
        if self._looks_dangerous(command):
            return ToolResult(
                success=False,
                message="Command rejected by safety policy.",
                data={"command": command},
            )
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", command],
                capture_output=True,
                text=True,
                timeout=parameters.timeout_seconds,
                check=False,
            )
        except Exception as exc:
            return ToolResult(success=False, message=f"Command execution failed: {exc}")

        output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
        output = output.strip()[:4000]
        success = result.returncode == 0
        return ToolResult(
            success=success,
            message="Command executed." if success else f"Command failed with code {result.returncode}.",
            data={"output": output, "returncode": result.returncode},
        )

    def _looks_dangerous(self, command: str) -> bool:
        return any(re.search(pattern, command, flags=re.IGNORECASE) for pattern in self.BLOCKLIST)

