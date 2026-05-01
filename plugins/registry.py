from __future__ import annotations

from typing import Iterable

from jarvis.plugins.base import PluginConnector


class PluginRegistry:
    """
    v1 plugin-ready registry. No built-in external connectors are registered by default.
    """

    def __init__(self, plugins: Iterable[PluginConnector] | None = None) -> None:
        self._plugins: dict[str, PluginConnector] = {}
        for plugin in plugins or []:
            self.register(plugin)

    def register(self, plugin: PluginConnector) -> None:
        self._plugins[plugin.name] = plugin

    def get(self, name: str) -> PluginConnector | None:
        return self._plugins.get(name)

    def list(self) -> list[str]:
        return sorted(self._plugins.keys())

