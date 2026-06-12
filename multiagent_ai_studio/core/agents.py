from __future__ import annotations

from .bus import AgentBusMessage, AgentMessageBus
from .database import Database
from .file_workspace import WorkspaceService
from .logging_service import LogService
from .memory import MemoryService
from .models import Agent, AgentRole, AgentStatus, ChatMessage, DEFAULT_PERMISSIONS, InternalMessage
from ..providers.base import GenerationRequest
from ..providers.registry import ProviderRegistry


ROLE_DESCRIPTIONS = {
    AgentRole.COORDINATOR.value: "распределяет работу, выбирает участников и собирает итоговый ответ",
    AgentRole.ARCHITECT.value: "анализирует архитектуру решения, риски и структуру работ",
    AgentRole.DEVELOPER.value: "планирует реализацию, изменения кода и технические шаги",
    AgentRole.QA.value: "проверяет качество, тесты, крайние случаи и критерии готовности",
    AgentRole.TESTER.value: "проверяет качество, тесты, крайние случаи и критерии готовности",
    AgentRole.RESEARCHER.value: "ищет недостающую информацию и фиксирует источники/гипотезы",
    AgentRole.WRITER.value: "готовит понятное резюме, документацию и пользовательский ответ",
}


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
        if self.db.list_agents():
            return self.db.list_agents()[0]
        defaults = [
            ("Координатор", AgentRole.COORDINATOR.value, "Главный фасилитатор общего чата и распределения задач."),
            ("Архитектор", AgentRole.ARCHITECT.value, "Проектирует решение и контролирует целостность архитектуры."),
            ("Разработчик", AgentRole.DEVELOPER.value, "Предлагает реализацию, работает с файлами и техническими деталями."),
            ("QA", AgentRole.QA.value, "Проверяет результат, тесты, риски и готовность."),
            ("Исследователь", AgentRole.RESEARCHER.value, "Собирает факты и недостающий контекст."),
            ("Документатор", AgentRole.WRITER.value, "Формирует итоговые ответы и документацию."),
        ]
        first: Agent | None = None
        for name, role, description in defaults:
            permissions = dict(DEFAULT_PERMISSIONS)
            if role == AgentRole.COORDINATOR.value:
                permissions["agents.create"] = True
            agent = Agent(None, name, role=role, description=description, model=default_model, permissions=permissions)
            agent.workspace_path = str(self.workspace.ensure_agent_workspace(agent))
            saved = self.db.upsert_agent(agent)
            first = first or saved
            self.logs.log("agent.create", f"Создан системный агент: {saved.name} ({saved.role})", agent_id=saved.id)
        return first  # type: ignore[return-value]

    def create_agent(self, name: str, role: str, model: str = "", *, parent_id: int | None = None, require_confirmation: bool = True, description: str = "") -> Agent:
        global_model = self.db.get_setting("global_model", "")
        agent = Agent(id=None, name=name, role=role, model=model or global_model, parent_id=parent_id, description=description)
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

    def propose_agent_creation(self, requester: Agent, name: str, role: str, reason: str) -> None:
        self.logs.log("approval.agent.create", f"{requester.name} предлагает создать агента {name} ({role}). Причина: {reason}", agent_id=requester.id, level="ACTION")

    def propose_model_change(self, requester: Agent, model: str, reason: str) -> None:
        self.logs.log("approval.model.change", f"{requester.name} предлагает сменить модель на {model}. Причина: {reason}", agent_id=requester.id, level="ACTION")

    def _set_status(self, agent: Agent, status: AgentStatus) -> None:
        agent.status = status.value
        self.db.set_agent_status(agent.id, status.value)
        self.logs.log("agent.status", f"{agent.name}: {status.value}", agent_id=agent.id)

    def _role_agent(self, role: str) -> Agent | None:
        return self.db.get_agent_by_role(role)

    def _select_participants(self, text: str) -> list[Agent]:
        enabled = [agent for agent in self.db.list_agents() if agent.enabled]
        selected: list[Agent] = []
        coordinator = self._role_agent(AgentRole.COORDINATOR.value)
        if coordinator:
            selected.append(coordinator)
        lower = text.lower()
        desired = [AgentRole.ARCHITECT.value, AgentRole.DEVELOPER.value, AgentRole.QA.value]
        if any(word in lower for word in ["исслед", "найди", "latest", "обнов", "информац", "документац"]):
            desired.append(AgentRole.RESEARCHER.value)
        if any(word in lower for word in ["readme", "докум", "опис", "текст", "инструкц"]):
            desired.append(AgentRole.WRITER.value)
        for role in desired:
            agent = self._role_agent(role) or (self._role_agent(AgentRole.TESTER.value) if role == AgentRole.QA.value else None)
            if agent and agent not in selected:
                selected.append(agent)
        if len(selected) == 1:
            selected.extend([agent for agent in enabled if agent not in selected][:3])
        return selected

    def _build_system_prompt(self, agent: Agent, role_goal: str) -> str:
        return f"""{agent.system_prompt}

Ты участвуешь во внутреннем многоагентном обсуждении общего чата. Роль: {agent.role}. Задача роли: {role_goal}.
Не раскрывай скрытые chain-of-thought. Вместо этого веди краткий журнал действий: решения, делегирование, инструменты, файлы и риски.
{agent.capability_summary()}"""

    def _generate_for_agent(self, agent: Agent, chat_id: str, user_text: str, discussion: list[str], purpose: str = "chat") -> str:
        global_model = self.db.get_setting("global_model", "")
        model = agent.effective_model(purpose, global_model)
        role_goal = ROLE_DESCRIPTIONS.get(agent.role, "анализирует задачу со своей стороны")
        if not model:
            self.logs.log("model.skip", f"{agent.name} не имеет выбранной модели; использован локальный журнал действий вместо запроса.", agent_id=agent.id, level="WARNING")
            return f"{agent.name}: нет выбранной модели, поэтому фиксирую решение без генерации: роль {agent.role} должна {role_goal}."
        recent = "\n".join(f"{m.sender_name}: {m.content}" for m in self.db.list_messages(chat_id, 20))
        internal = "\n".join(discussion[-10:])
        prompt = f"""Пользователь написал в общий чат:
{user_text}

История чата:
{recent}

Текущее внутреннее обсуждение:
{internal}

Сформируй краткий вклад от имени роли {agent.role}: что ты решил, кому делегируешь, какие инструменты/файлы нужны, риски и следующий шаг."""
        request = GenerationRequest(
            model=model,
            system_prompt=self._build_system_prompt(agent, role_goal),
            prompt=prompt,
            temperature=agent.temperature,
            context=self.memory.build_context(agent, recent),
        )
        self.logs.log("model.request", f"{agent.name} отправил запрос в Ollama ({model})", agent_id=agent.id)
        response = self.providers.get("ollama").generate(request)
        text = response.text.strip()
        if "[reasoning]" in text:
            visible, reasoning = text.split("[reasoning]", 1)
            self.logs.log("agent.reasoning", f"{agent.name}: {reasoning.strip()[:1200]}", agent_id=agent.id)
            text = visible.strip()
        self.logs.log("model.response", f"{agent.name} получил ответ от {response.provider}/{response.model}", agent_id=agent.id)
        self.memory.remember_interaction(agent, user_text, text)
        return text

    def run_project_chat(self, chat_id: str, content: str) -> str:
        self.db.add_message(ChatMessage(None, chat_id, "user", "Пользователь", content))
        participants = self._select_participants(content)
        names = ", ".join(agent.name for agent in participants)
        self.logs.log("orchestration.start", f"Общий чат {chat_id}: выбраны участники обсуждения: {names}")
        discussion: list[str] = []
        coordinator = participants[0] if participants else None
        for index, agent in enumerate(participants):
            self._set_status(agent, AgentStatus.THINKING if index == 0 else AgentStatus.DISCUSSING)
            if coordinator and coordinator.id != agent.id:
                route = f"{coordinator.name} делегирует агенту {agent.name}: проанализируй задачу как {agent.role}."
                self.send_agent_message(coordinator, agent, route, chat_id=chat_id, topic="delegation")
                discussion.append(route)
            try:
                contribution = self._generate_for_agent(agent, chat_id, content, discussion, purpose="planning" if agent.role == AgentRole.COORDINATOR.value else "chat")
            except Exception as exc:  # noqa: BLE001
                self._set_status(agent, AgentStatus.ERROR)
                contribution = f"{agent.name}: ошибка генерации ({exc}). Продолжаю по журналу действий."
                self.logs.log("agent.error", contribution, agent_id=agent.id, level="ERROR")
            message = f"{agent.name} ({agent.role}): {contribution}"
            discussion.append(message)
            if coordinator and coordinator.id != agent.id:
                self.send_agent_message(agent, coordinator, contribution, chat_id=chat_id, topic="report")
            self.logs.log("agent.decision", message[:1600], agent_id=agent.id)
            self._set_status(agent, AgentStatus.DONE)
        writer = self._role_agent(AgentRole.WRITER.value) or coordinator or (participants[0] if participants else None)
        if writer:
            self._set_status(writer, AgentStatus.THINKING)
            try:
                final = self._generate_for_agent(writer, chat_id, content, discussion + ["Собери единый ответ пользователю."], purpose="document")
            except Exception as exc:  # noqa: BLE001
                self.logs.log("agent.error", f"Не удалось собрать финальный ответ моделью: {exc}", agent_id=writer.id, level="ERROR")
                final = "\n\n".join(discussion)
            self._set_status(writer, AgentStatus.DONE)
            sender_name = f"Команда агентов / {writer.name}"
            agent_id = writer.id
        else:
            final = "Нет доступных агентов для ответа."
            sender_name = "Система"
            agent_id = None
        self.db.add_message(ChatMessage(None, chat_id, "agent", sender_name, final, agent_id))
        self.logs.log("orchestration.complete", f"Обсуждение завершено, ответ добавлен в общий чат {chat_id}", agent_id=agent_id)
        return final

    def send_user_message(self, agent: Agent, chat_id: str, content: str) -> str:
        # Backward-compatible entry point: now routes user input through the project-wide collective chat.
        return self.run_project_chat(chat_id, content)

    def send_agent_message(self, sender: Agent, receiver: Agent, content: str, *, chat_id: str = "default", topic: str = "direct") -> None:
        self.db.add_internal_message(InternalMessage(None, sender.id, receiver.id, content, topic=topic, chat_id=chat_id))
        self.bus.publish(AgentBusMessage(sender.id, receiver.id, content, topic=topic))
