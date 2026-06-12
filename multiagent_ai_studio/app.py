from __future__ import annotations

from pathlib import Path
import os

from .core.agents import AgentService
from .core.bus import AgentMessageBus
from .core.change_proposals import ChangeProposalService
from .core.database import Database
from .core.file_workspace import WorkspaceService
from .core.logging_service import LogService
from .core.memory import MemoryService
from .core.models import ensure_workspace
from .core.permissions import PermissionService
from .core.plugins import PluginManager
from .core.projects import ProjectService
from .core.tasks import TaskManager
from .i18n import Translator
from .providers.registry import ProviderRegistry
from .ui.tk_app import StudioWindow


def build_app() -> StudioWindow:
    data_root = Path(os.environ.get("MULTIAGENT_AI_STUDIO_HOME", Path.home() / "MultiAgentAIStudio"))
    paths = ensure_workspace(data_root)
    db = Database(data_root / "studio.sqlite3")
    logs = LogService(db)
    permissions = PermissionService()
    workspace = WorkspaceService(paths["root"], logs, permissions)
    providers = ProviderRegistry()
    memory = MemoryService(db)
    bus = AgentMessageBus(logs)
    agents = AgentService(db, providers, memory, workspace, bus, logs)
    projects = ProjectService(db, workspace, logs)
    tasks = TaskManager(db, logs)
    plugins = PluginManager(paths["plugins"], logs)
    proposals = ChangeProposalService(paths["proposals"], logs)
    translator = Translator("ru")
    return StudioWindow(
        db=db,
        translator=translator,
        providers=providers,
        logs=logs,
        agents=agents,
        projects=projects,
        tasks=tasks,
        plugins=plugins,
        proposals=proposals,
        data_root=data_root,
    )


def main() -> None:
    app = build_app()
    app.mainloop()
