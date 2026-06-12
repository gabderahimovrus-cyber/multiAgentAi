from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from .base import GenerationRequest, GenerationResponse


@dataclass
class OllamaProvider:
    base_url: str = "http://127.0.0.1:11434"
    name: str = "ollama"

    def _request(self, method: str, path: str, payload: dict | None = None, timeout: int = 120) -> dict:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(str(exc)) from exc

    def list_models(self) -> list[str]:
        data = self._request("GET", "/api/tags", timeout=5)
        return [item.get("name", "") for item in data.get("models", []) if item.get("name")]

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        prompt = request.prompt
        if request.context:
            prompt = f"Контекст памяти и истории:\n{request.context}\n\nЗапрос пользователя:\n{request.prompt}"
        payload = {
            "model": request.model,
            "prompt": prompt,
            "system": request.system_prompt,
            "stream": False,
            "options": {"temperature": request.temperature},
        }
        data = self._request("POST", "/api/generate", payload=payload)
        return GenerationResponse(text=data.get("response", ""), model=request.model, provider=self.name)
