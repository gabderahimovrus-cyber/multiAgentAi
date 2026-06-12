from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

from .logging_service import LogService


class PluginManager:
    """Горячая загрузка плагинов после явного подтверждения пользователя в UI."""

    def __init__(self, plugin_dir: Path, logs: LogService) -> None:
        self.plugin_dir = plugin_dir
        self.logs = logs
        self.loaded: dict[str, ModuleType] = {}
        self.plugin_dir.mkdir(parents=True, exist_ok=True)

    def discover(self) -> list[dict]:
        plugins = []
        for manifest in self.plugin_dir.glob("*/plugin.json"):
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
                data["path"] = str(manifest.parent)
                data["hash"] = self.hash_plugin(manifest.parent)
                plugins.append(data)
            except Exception as exc:  # noqa: BLE001 - plugin scan must not crash app
                self.logs.log("plugin.error", f"Ошибка чтения {manifest}: {exc}", level="ERROR")
        return plugins

    def hash_plugin(self, path: Path) -> str:
        digest = hashlib.sha256()
        for file in sorted(path.rglob("*")):
            if file.is_file():
                digest.update(file.relative_to(path).as_posix().encode())
                digest.update(file.read_bytes())
        return digest.hexdigest()

    def load(self, path: Path, approved: bool = False) -> ModuleType:
        if not approved:
            raise PermissionError("Загрузка плагина требует подтверждения пользователя")
        entry = path / "plugin.py"
        spec = importlib.util.spec_from_file_location(f"mai_plugin_{path.name}", entry)
        if spec is None or spec.loader is None:
            raise ImportError(f"Не удалось загрузить plugin.py из {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.loaded[path.name] = module
        self.logs.log("plugin.load", f"Загружен плагин: {path.name}")
        return module
