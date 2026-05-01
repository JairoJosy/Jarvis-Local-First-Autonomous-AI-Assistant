from __future__ import annotations

import subprocess

from pydantic import BaseModel, Field

from jarvis.schemas import ToolResult
from jarvis.tools.base import BaseTool


class OpenAppParams(BaseModel):
    app: str = Field(min_length=1, max_length=64)
    dry_run: bool = False


class OpenAppTool(BaseTool):
    name = "open_app"
    description = "Open approved local applications (chrome, explorer, calculator)."
    risk_level = "tier2"
    mutating = False
    params_model = OpenAppParams

    APP_MAP = {
        "chrome": "chrome",
        "explorer": "explorer",
        "calculator": "calc",
        "calc": "calc",
    }

    def execute(self, parameters: OpenAppParams, context: dict) -> ToolResult:
        app_key = parameters.app.strip().lower()
        command = self.APP_MAP.get(app_key)
        if not command:
            return ToolResult(
                success=False,
                message=f"Unsupported app '{parameters.app}'. Allowed: {', '.join(sorted(self.APP_MAP))}.",
            )
        if parameters.dry_run:
            return ToolResult(
                success=True,
                message=f"Dry run: would open {app_key}.",
                data={"command": command},
            )
        try:
            subprocess.Popen([command], shell=False)
        except Exception as exc:
            return ToolResult(success=False, message=f"Failed to open {app_key}: {exc}")
        return ToolResult(success=True, message=f"Opened {app_key}.", data={"command": command})

