from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from urllib.parse import urlparse

from .base import GenerationRequest, GenerationResponse


@dataclass
class OllamaProvider:
    base_url: str = "http://127.0.0.1:11434"
    name: str = "ollama"
    remote_urls: list[str] = field(default_factory=list)

    @property
    def endpoints(self) -> list[str]:
        seen: list[str] = []
        for url in [self.base_url, *self.remote_urls]:
            clean = url.rstrip("/")
            if clean and clean not in seen:
                seen.append(clean)
        return seen

    def configure_endpoints(self, urls: list[str]) -> None:
        clean = [url.rstrip("/") for url in urls if url.strip()]
        if clean:
            self.base_url = clean[0]
            self.remote_urls = clean[1:]

    def _request(self, method: str, path: str, payload: dict | None = None, timeout: int = 120, base_url: str | None = None) -> dict:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        endpoint = (base_url or self.base_url).rstrip("/")
        req = urllib.request.Request(
            f"{endpoint}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"{endpoint}: {exc}") from exc

    def _source_label(self, url: str) -> str:
        parsed = urlparse(url)
        host = parsed.netloc or parsed.path
        if host.startswith("127.0.0.1") or host.startswith("localhost"):
            return "local"
        return host

    def list_model_details(self) -> list[dict[str, object]]:
        models: list[dict[str, object]] = []
        for endpoint in self.endpoints:
            try:
                data = self._request("GET", "/api/tags", timeout=5, base_url=endpoint)
            except RuntimeError:
                continue
            for item in data.get("models", []):
                name = item.get("name", "")
                if name:
                    details = item.get("details") or {}
                    models.append({
                        "name": name,
                        "source": self._source_label(endpoint),
                        "endpoint": endpoint,
                        "size": item.get("size", 0),
                        "parameters": details.get("parameter_size", ""),
                        "family": details.get("family", ""),
                        "status": "available",
                    })
        return models

    def list_models_with_sources(self) -> list[tuple[str, str, str]]:
        return [(str(item["name"]), str(item["source"]), str(item["endpoint"])) for item in self.list_model_details()]

    def list_models(self) -> list[str]:
        return [f"{name} [{source}]" for name, source, _endpoint in self.list_models_with_sources()]

    def _split_model_label(self, label: str) -> tuple[str, str | None]:
        if " [" in label and label.endswith("]"):
            model, source = label.rsplit(" [", 1)
            return model, source[:-1]
        return label, None

    def endpoint_for_model(self, label: str) -> tuple[str, str]:
        model, source = self._split_model_label(label)
        sources = self.list_models_with_sources()
        for name, source_label, endpoint in sources:
            if name == model and (source is None or source == source_label):
                return model, endpoint
        return model, self.base_url

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        prompt = request.prompt
        if request.context:
            prompt = f"Контекст памяти и истории:\n{request.context}\n\nЗапрос пользователя:\n{request.prompt}"
        model_name, endpoint = self.endpoint_for_model(request.model)
        payload = {
            "model": model_name,
            "prompt": prompt,
            "system": request.system_prompt,
            "stream": False,
            "options": {"temperature": request.temperature},
        }
        data = self._request("POST", "/api/generate", payload=payload, base_url=endpoint)
        reasoning = data.get("thinking") or data.get("reasoning") or ""
        text = data.get("response", "")
        if reasoning:
            text = f"{text}\n\n[reasoning]\n{reasoning}"
        return GenerationResponse(text=text, model=request.model, provider=f"{self.name}@{self._source_label(endpoint)}")
