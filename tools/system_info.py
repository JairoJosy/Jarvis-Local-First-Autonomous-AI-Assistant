from __future__ import annotations

import os
import platform
from datetime import datetime

from pydantic import BaseModel

from jarvis.schemas import ToolResult
from jarvis.timezone_utils import safe_zoneinfo
from jarvis.tools.base import BaseTool


class SystemInfoParams(BaseModel):
    query: str = "all"


class SystemInfoTool(BaseTool):
    name = "system_info"
    description = "Read-only system information such as OS, working directory, and local time."
    risk_level = "tier1"
    mutating = False
    params_model = SystemInfoParams

    def execute(self, parameters: SystemInfoParams, context: dict) -> ToolResult:
        tz_name = context.get("timezone", "UTC")
        now = datetime.now(safe_zoneinfo(tz_name)).isoformat()
        payload = {
            "time_local": now,
            "os": platform.platform(),
            "cwd": os.getcwd(),
            "query": parameters.query,
        }
        if parameters.query == "time":
            payload = {"time_local": now}
        elif parameters.query == "os":
            payload = {"os": platform.platform()}
        elif parameters.query == "cwd":
            payload = {"cwd": os.getcwd()}
        return ToolResult(success=True, message="System information retrieved.", data=payload)
