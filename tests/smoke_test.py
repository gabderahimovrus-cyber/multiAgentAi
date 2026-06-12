from pathlib import Path
from tempfile import TemporaryDirectory
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from multiagent_ai_studio.core.agents import AgentService
from multiagent_ai_studio.core.bus import AgentMessageBus
from multiagent_ai_studio.core.database import Database
from multiagent_ai_studio.core.file_workspace import WorkspaceService
from multiagent_ai_studio.core.logging_service import LogService
from multiagent_ai_studio.core.memory import MemoryService
from multiagent_ai_studio.core.models import Agent, AgentRole, ChatSession, ensure_workspace
from multiagent_ai_studio.core.permissions import PermissionService
from multiagent_ai_studio.providers.registry import ProviderRegistry


def main() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        paths = ensure_workspace(root)
        db = Database(root / "test.sqlite3")
        logs = LogService(db)
        workspace = WorkspaceService(paths["root"], logs, PermissionService())
        agent = Agent(None, "Тестовый агент", model="dummy")
        agent.workspace_path = str(workspace.ensure_agent_workspace(agent))
        agent = db.upsert_agent(agent)
        workspace.write_file(agent, "notes/result.md", "# Проверка")
        assert workspace.read_file(agent, "notes/result.md") == "# Проверка"
        assert db.list_agents()[0].name == "Тестовый агент"
        assert db.list_logs()

        chat = db.create_chat("Командное обсуждение")
        assert db.get_chat(chat.id).title == "Командное обсуждение"
        db.upsert_chat(ChatSession(chat.id, None, "Переименованный чат"))
        assert db.get_chat(chat.id).title == "Переименованный чат"

        providers = ProviderRegistry()
        bus = AgentMessageBus(logs)
        service = AgentService(db, providers, MemoryService(db), workspace, bus, logs)
        service.create_agent("Координатор", AgentRole.COORDINATOR.value, "")
        service.create_agent("Архитектор", AgentRole.ARCHITECT.value, "")
        service.create_agent("Разработчик", AgentRole.DEVELOPER.value, "")
        service.create_agent("QA", AgentRole.QA.value, "")
        answer = service.run_project_chat(chat.id, "Нужно спланировать изменение интерфейса")
        assert "нет выбранной модели" in answer or "Координатор" in answer
        assert db.list_internal_messages(chat.id)
        assert any(event.event_type == "orchestration.complete" for event in db.list_logs(limit=1000))
        db.close()


if __name__ == "__main__":
    main()
