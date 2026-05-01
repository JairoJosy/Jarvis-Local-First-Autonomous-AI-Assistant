from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class PluginConnector(ABC):
    name: str
    version: str
    description: str

    @abstractmethod
    def capabilities(self) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def execute(self, action: str, parameters: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

