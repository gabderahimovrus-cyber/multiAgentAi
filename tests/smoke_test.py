from pathlib import Path
from tempfile import TemporaryDirectory
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from multiagent_ai_studio.core.database import Database
from multiagent_ai_studio.core.logging_service import LogService
from multiagent_ai_studio.core.models import Agent, ensure_workspace
from multiagent_ai_studio.core.permissions import PermissionService
from multiagent_ai_studio.core.file_workspace import WorkspaceService


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
        db.close()


if __name__ == "__main__":
    main()
