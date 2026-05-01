from __future__ import annotations

import json
from typing import Iterable

from jarvis.tools.base import BaseTool


class ToolRegistry:
    def __init__(self, tools: Iterable[BaseTool] | None = None) -> None:
        self._tools: dict[str, BaseTool] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def all(self) -> list[BaseTool]:
        return list(self._tools.values())

    def specs_text(self) -> str:
        specs = [tool.spec() for tool in self._tools.values()]
        return json.dumps(specs, indent=2)

