from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class AgentRole(str, Enum):
    COORDINATOR = "Coordinator"
    ARCHITECT = "Architect"
    DEVELOPER = "Developer"
    TESTER = "Tester"
    RESEARCHER = "Researcher"
    ANALYST = "Analyst"
    WRITER = "Writer"
    DEVOPS = "DevOps"
    SECURITY = "Security"


DEFAULT_PERMISSIONS = {
    "workspace.read": True,
    "workspace.write": True,
    "scripts.execute": False,
    "network.access": False,
    "browser.access": False,
    "git.read": True,
    "git.write": False,
    "agents.create": False,
    "agents.delete": False,
    "plugins.load": False,
}


@dataclass
class Agent:
    id: int | None
    name: str
    role: str = AgentRole.COORDINATOR.value
    description: str = ""
    system_prompt: str = "Ты автономный ИИ-агент. Отвечай на русском языке, работай аккуратно и логируй важные действия."
    model: str = ""
    planning_model: str = ""
    coding_model: str = ""
    review_model: str = ""
    document_model: str = ""
    temperature: float = 0.7
    enabled: bool = True
    parent_id: int | None = None
    workspace_path: str = ""
    permissions: dict[str, bool] = field(default_factory=lambda: dict(DEFAULT_PERMISSIONS))
    short_memory: str = ""
    long_memory: str = ""
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def effective_model(self, purpose: str = "chat") -> str:
        mapping = {
            "planning": self.planning_model,
            "coding": self.coding_model,
            "review": self.review_model,
            "document": self.document_model,
        }
        return mapping.get(purpose, "") or self.model


@dataclass
class Project:
    id: int | None
    name: str
    goal: str = ""
    description: str = ""
    workspace_path: str = ""
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class ChatMessage:
    id: int | None
    chat_id: str
    sender_type: str
    sender_name: str
    content: str
    agent_id: int | None = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class LogEvent:
    id: int | None
    event_type: str
    message: str
    agent_id: int | None = None
    project_id: int | None = None
    level: str = "INFO"
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class TaskSpec:
    id: int | None
    title: str
    task_type: str = "one_shot"
    status: str = "paused"
    agent_id: int | None = None
    project_id: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    schedule: str = ""
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


def ensure_workspace(root: Path) -> dict[str, Path]:
    paths = {
        "root": root,
        "agents": root / "agents",
        "projects": root / "projects",
        "plugins": root / "plugins",
        "scripts": root / "scripts",
        "exports": root / "exports",
        "proposals": root / "change_proposals",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths
