from __future__ import annotations

from pathlib import Path

from .bus import AgentBusMessage, AgentMessageBus
from .database import Database
from .file_workspace import WorkspaceService
from .logging_service import LogService
from .memory import MemoryService
from .models import Agent, AgentRole, ChatMessage, DEFAULT_PERMISSIONS
from .permissions import PermissionService
from ..providers.base import GenerationRequest
from ..providers.registry import ProviderRegistry


class AgentService:
    def __init__(
        self,
        db: Database,
        providers: ProviderRegistry,
        memory: MemoryService,
        workspace: WorkspaceService,
        bus: AgentMessageBus,
        logs: LogService,
    ) -> None:
        self.db = db
        self.providers = providers
        self.memory = memory
        self.workspace = workspace
        self.bus = bus
        self.logs = logs

    def bootstrap_default_agent(self, default_model: str = "") -> Agent:
        agents = self.db.list_agents()
        if agents:
            return agents[0]
        agent = Agent(
            id=None,
            name="Координатор",
            role=AgentRole.COORDINATOR.value,
            description="Главный агент для общения с пользователем и координации команды.",
            model=default_model,
            permissions=dict(DEFAULT_PERMISSIONS),
        )
        agent.workspace_path = str(self.workspace.ensure_agent_workspace(agent))
        saved = self.db.upsert_agent(agent)
        self.logs.log("agent.create", f"Создан агент по умолчанию: {saved.name}", agent_id=saved.id)
        return saved

    def create_agent(self, name: str, role: str, model: str = "", *, parent_id: int | None = None, require_confirmation: bool = True) -> Agent:
        # UI вызывает этот метод только после подтверждения пользователя для временных/дочерних агентов.
        agent = Agent(id=None, name=name, role=role, model=model, parent_id=parent_id)
        agent.workspace_path = str(self.workspace.ensure_agent_workspace(agent))
        saved = self.db.upsert_agent(agent)
        self.logs.log("agent.create", f"Создан агент: {name} ({role})", agent_id=saved.id)
        return saved

    def clone_agent(self, source: Agent, new_name: str) -> Agent:
        clone = Agent(
            id=None,
            name=new_name,
            role=source.role,
            description=source.description,
            system_prompt=source.system_prompt,
            model=source.model,
            planning_model=source.planning_model,
            coding_model=source.coding_model,
            review_model=source.review_model,
            document_model=source.document_model,
            temperature=source.temperature,
            enabled=source.enabled,
            parent_id=source.parent_id,
            permissions=dict(source.permissions),
            short_memory=source.short_memory,
            long_memory=source.long_memory,
        )
        clone.workspace_path = str(self.workspace.ensure_agent_workspace(clone))
        saved = self.db.upsert_agent(clone)
        self.logs.log("agent.clone", f"Клонирован агент {source.name} -> {new_name}", agent_id=saved.id)
        return saved

    def delete_agent(self, agent_id: int) -> None:
        agent = self.db.get_agent(agent_id)
        self.db.delete_agent(agent_id)
        if agent:
            self.logs.log("agent.delete", f"Удалён агент: {agent.name}", agent_id=agent.id)

    def send_user_message(self, agent: Agent, chat_id: str, content: str) -> str:
        if not agent.enabled:
            raise RuntimeError("Агент отключён")
        self.db.add_message(ChatMessage(None, chat_id, "user", "Пользователь", content))
        recent = "\n".join(f"{m.sender_name}: {m.content}" for m in self.db.list_messages(chat_id, 20))
        provider = self.providers.get("ollama")
        request = GenerationRequest(
            model=agent.effective_model("chat"),
            system_prompt=agent.system_prompt,
            prompt=content,
            temperature=agent.temperature,
            context=self.memory.build_context(agent, recent),
        )
        if not request.model:
            raise RuntimeError("Для агента не выбрана модель Ollama")
        self.logs.log("model.request", f"{agent.name} отправил запрос в Ollama ({request.model})", agent_id=agent.id)
        response = provider.generate(request)
        self.db.add_message(ChatMessage(None, chat_id, "agent", agent.name, response.text, agent.id))
        self.memory.remember_interaction(agent, content, response.text)
        self.logs.log("model.response", f"{agent.name} получил ответ от {response.provider}/{response.model}", agent_id=agent.id)
        return response.text

    def send_agent_message(self, sender: Agent, receiver: Agent, content: str) -> None:
        self.bus.publish(AgentBusMessage(sender.id, receiver.id, content))
