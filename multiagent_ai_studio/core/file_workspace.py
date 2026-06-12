from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

from .logging_service import LogService
from .models import Agent
from .permissions import PermissionService


class WorkspaceService:
    def __init__(self, root: Path, logs: LogService, permissions: PermissionService) -> None:
        self.root = root.resolve()
        self.logs = logs
        self.permissions = permissions

    def ensure_agent_workspace(self, agent: Agent) -> Path:
        path = Path(agent.workspace_path) if agent.workspace_path else self.root / "agents" / self._safe_name(agent.name)
        for sub in ("files", "notes", "scripts", "projects", "memory"):
            (path / sub).mkdir(parents=True, exist_ok=True)
        return path

    def create_project_workspace(self, name: str) -> Path:
        path = self.root / "projects" / self._safe_name(name)
        for sub in ("files", "docs", "tasks", "artifacts", "logs"):
            (path / sub).mkdir(parents=True, exist_ok=True)
        self.logs.log("project.workspace", f"Создана рабочая область проекта: {path}")
        return path

    def write_file(self, agent: Agent, relative_path: str, content: str) -> Path:
        if not self.permissions.has(agent, "workspace.write"):
            raise PermissionError("У агента нет права записи в рабочую область")
        path = self._resolve_agent_path(agent, relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self.logs.log("file.write", f"{agent.name} записал файл {path}", agent_id=agent.id)
        return path

    def read_file(self, agent: Agent, relative_path: str) -> str:
        if not self.permissions.has(agent, "workspace.read"):
            raise PermissionError("У агента нет права чтения рабочей области")
        path = self._resolve_agent_path(agent, relative_path)
        self.logs.log("file.read", f"{agent.name} прочитал файл {path}", agent_id=agent.id)
        return path.read_text(encoding="utf-8")

    def copy(self, agent: Agent, src: str, dst: str) -> None:
        shutil.copy2(self._resolve_agent_path(agent, src), self._resolve_agent_path(agent, dst))
        self.logs.log("file.copy", f"{agent.name} скопировал {src} в {dst}", agent_id=agent.id)

    def move(self, agent: Agent, src: str, dst: str) -> None:
        shutil.move(str(self._resolve_agent_path(agent, src)), str(self._resolve_agent_path(agent, dst)))
        self.logs.log("file.move", f"{agent.name} переместил {src} в {dst}", agent_id=agent.id)

    def delete(self, agent: Agent, relative_path: str) -> None:
        path = self._resolve_agent_path(agent, relative_path)
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
        self.logs.log("file.delete", f"{agent.name} удалил {relative_path}", agent_id=agent.id)

    def archive(self, agent: Agent, relative_dir: str, archive_name: str) -> Path:
        base = self._resolve_agent_path(agent, relative_dir)
        archive = self._resolve_agent_path(agent, archive_name)
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for item in base.rglob("*"):
                if item.is_file():
                    zf.write(item, item.relative_to(base))
        self.logs.log("file.archive", f"{agent.name} создал архив {archive}", agent_id=agent.id)
        return archive

    def _resolve_agent_path(self, agent: Agent, relative_path: str) -> Path:
        base = self.ensure_agent_workspace(agent).resolve()
        path = (base / relative_path).resolve()
        if not str(path).startswith(str(base)):
            raise ValueError("Путь выходит за пределы рабочей папки агента")
        return path

    @staticmethod
    def _safe_name(name: str) -> str:
        return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name).strip("_") or "agent"
