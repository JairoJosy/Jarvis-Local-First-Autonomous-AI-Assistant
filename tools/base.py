from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ValidationError

from jarvis.schemas import ToolResult


class BaseTool(ABC):
    name: str
    description: str
    risk_level: str
    mutating: bool = False
    params_model: type[BaseModel]

    def validate_parameters(self, parameters: dict[str, Any]) -> BaseModel:
        try:
            return self.params_model.model_validate(parameters)
        except ValidationError as exc:
            raise ValueError(f"Invalid parameters for {self.name}: {exc}") from exc

    @abstractmethod
    def execute(self, parameters: BaseModel, context: dict[str, Any]) -> ToolResult:
        raise NotImplementedError

    def spec(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "risk_level": self.risk_level,
            "mutating": self.mutating,
            "parameters_schema": self.params_model.model_json_schema(),
        }

