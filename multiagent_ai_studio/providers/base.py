from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class GenerationRequest:
    model: str
    system_prompt: str
    prompt: str
    temperature: float = 0.7
    context: str = ""


@dataclass
class GenerationResponse:
    text: str
    model: str
    provider: str


class ModelProvider(Protocol):
    name: str

    def list_models(self) -> list[str]: ...

    def generate(self, request: GenerationRequest) -> GenerationResponse: ...
