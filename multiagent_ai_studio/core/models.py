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
    QA = "QA"
    RESEARCHER = "Researcher"
    ANALYST = "Analyst"
    WRITER = "Writer"
    DEVOPS = "DevOps"
    SECURITY = "Security"
    TESTER = "Tester"


class AgentStatus(str, Enum):
    IDLE = "ожидает"
    THINKING = "думает"
    DISCUSSING = "обсуждает задачу"
    FILES = "работает с файлами"
    EXECUTING = "выполняет задачу"
    DONE = "завершил задачу"
    ERROR = "ошибка"


PERMISSION_HELP = {
    "workspace.read": "Разрешает агенту читать файлы в назначенной рабочей директории и ссылаться на изученные файлы в журнале.",
    "workspace.write": "Разрешает агенту создавать и редактировать файлы только в своей рабочей директории или директории проекта.",
    "workspace.delete": "Разрешает удалять файлы в разрешённых рабочих директориях после отдельного логирования действия.",
    "scripts.execute": "Разрешает запускать локальные скрипты и команды задач. Оставляйте выключенным для непроверенных агентов.",
    "agents.create": "Разрешает агенту предлагать создание нового специализированного агента. Пользователь всё равно подтверждает запрос.",
    "agents.delete": "Разрешает агенту предлагать удаление агента. Фактическое удаление требует подтверждения пользователя.",
    "network.access": "Разрешает использовать сетевые инструменты и удалённые API, если они подключены как инструменты.",
    "git.read": "Разрешает читать состояние Git, историю и diff проекта.",
    "git.write": "Разрешает предлагать операции Git-записи: commit, branch, apply patch. Опасные действия должны логироваться.",
    "plugins.load": "Разрешает подключать утверждённые плагины и использовать их инструменты.",
    "models.manage": "Разрешает просить пользователя сменить модель агента или глобальную модель по умолчанию.",
    "tasks.create": "Разрешает создавать внутренние задачи и назначать их агентам.",
}


DEFAULT_PERMISSIONS = {
    "workspace.read": True,
    "workspace.write": True,
    "workspace.delete": False,
    "scripts.execute": False,
    "agents.create": False,
    "agents.delete": False,
    "network.access": False,
    "git.read": True,
    "git.write": False,
    "plugins.load": False,
    "models.manage": True,
    "tasks.create": True,
}


CAPABILITY_DESCRIPTIONS = {
    "read_files": "читать файлы проекта при включённом workspace.read",
    "write_files": "создавать и редактировать файлы при включённом workspace.write",
    "create_projects": "создавать проекты и рабочие области",
    "create_agents": "предлагать создание новых агентов через подтверждение пользователя",
    "use_models": "использовать локальные и удалённые модели Ollama",
    "run_tasks": "создавать и выполнять задачи в системе задач",
    "use_plugins": "использовать одобренные плагины",
    "internal_chat": "общаться с другими агентами во внутреннем канале",
}


@dataclass
class Agent:
    id: int | None
    name: str
    role: str = AgentRole.COORDINATOR.value
    description: str = ""
    system_prompt: str = "Ты автономный ИИ-агент в коллективной среде. Отвечай на русском языке, фиксируй решения и объясняй действия в журнале."
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
    status: str = AgentStatus.IDLE.value
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def effective_model(self, purpose: str = "chat", global_model: str = "") -> str:
        mapping = {
            "planning": self.planning_model,
            "coding": self.coding_model,
            "review": self.review_model,
            "document": self.document_model,
        }
        return mapping.get(purpose, "") or self.model or global_model

    def capability_summary(self) -> str:
        lines = ["Доступные возможности агента:"]
        for key, description in CAPABILITY_DESCRIPTIONS.items():
            lines.append(f"- {key}: {description}")
        lines.append("Разрешения:")
        for key, value in self.permissions.items():
            state = "разрешено" if value else "запрещено"
            help_text = PERMISSION_HELP.get(key, "")
            lines.append(f"- {key}: {state}. {help_text}")
        return "\n".join(lines)


@dataclass
class Project:
    id: int | None
    name: str
    goal: str = ""
    description: str = ""
    workspace_path: str = ""
    archived: bool = False
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class ChatSession:
    id: str
    project_id: int | None
    title: str
    archived: bool = False
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
class InternalMessage:
    id: int | None
    sender_agent_id: int | None
    receiver_agent_id: int | None
    content: str
    topic: str = "direct"
    status: str = "delivered"
    chat_id: str = "default"
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
