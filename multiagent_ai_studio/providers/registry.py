from __future__ import annotations

from .base import ModelProvider
from .ollama import OllamaProvider


class ProviderRegistry:
    """Реестр провайдеров моделей. Новые провайдеры добавляются без изменения ядра агентов."""

    def __init__(self) -> None:
        self._providers: dict[str, ModelProvider] = {}
        self.register(OllamaProvider())

    def register(self, provider: ModelProvider) -> None:
        self._providers[provider.name] = provider

    def get(self, name: str = "ollama") -> ModelProvider:
        return self._providers[name]

    def names(self) -> list[str]:
        return sorted(self._providers)
