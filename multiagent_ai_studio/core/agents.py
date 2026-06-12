from __future__ import annotations

from collections import Counter

from .bus import AgentBusMessage, AgentMessageBus
from .database import Database
from .file_workspace import WorkspaceService
from .logging_service import LogService
from .memory import MemoryService
from .models import Agent, AgentRole, AgentStatus, ChatMessage, DEFAULT_PERMISSIONS, InternalMessage, WorkMode
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
    AgentRole.ANALYST.value: "структурирует требования, ограничения, метрики успеха и план работ",
    AgentRole.SECURITY.value: "оценивает безопасность, секреты, права доступа и рискованные операции",
    AgentRole.DEVOPS.value: "планирует окружение, запуск, скрипты, CI/CD и эксплуатационные риски",
    AgentRole.OBSERVER.value: "наблюдает за симуляцией, предотвращает циклы и предлагает завершение обсуждения",
}

MODE_PLANS = {
    WorkMode.FAST.value: ["Coordinator"],
    WorkMode.TEAM.value: ["Coordinator", "Analyst", "Architect", "Developer", "QA", "Writer"],
    WorkMode.AUTONOMOUS.value: ["Coordinator", "Analyst", "Architect", "Developer", "Security", "DevOps", "QA", "Writer"],
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
        existing = self.db.list_agents()
        if existing:
            self._ensure_core_team(default_model)
            return existing[0]
        self._ensure_core_team(default_model)
        return self.db.list_agents()[0]

    def _ensure_core_team(self, default_model: str = "") -> None:
        defaults = [
            ("Координатор", AgentRole.COORDINATOR.value, "Главный фасилитатор общего чата и распределения задач."),
            ("Аналитик", AgentRole.ANALYST.value, "Уточняет цель проекта, ограничения, критерии результата и план действий."),
            ("Архитектор", AgentRole.ARCHITECT.value, "Проектирует решение и контролирует целостность архитектуры."),
            ("Разработчик", AgentRole.DEVELOPER.value, "Предлагает реализацию, работает с файлами и техническими деталями."),
            ("QA", AgentRole.QA.value, "Проверяет результат, тесты, риски и готовность."),
            ("Исследователь", AgentRole.RESEARCHER.value, "Собирает факты и недостающий контекст."),
            ("Документатор", AgentRole.WRITER.value, "Формирует итоговые ответы и документацию."),
            ("Безопасник", AgentRole.SECURITY.value, "Проверяет разрешения, риски, секреты и опасные действия."),
            ("DevOps", AgentRole.DEVOPS.value, "Отвечает за запуск, скрипты, окружение и эксплуатацию."),
            ("Observer", AgentRole.OBSERVER.value, "Системный наблюдатель за эффективностью симуляции."),
        ]
        existing_roles = {agent.role for agent in self.db.list_agents()}
        for name, role, description in defaults:
            if role in existing_roles:
                continue
            permissions = dict(DEFAULT_PERMISSIONS)
            if role == AgentRole.COORDINATOR.value:
                permissions["agents.create"] = True
            if role in {AgentRole.SECURITY.value, AgentRole.OBSERVER.value}:
                permissions["workspace.write"] = False
                permissions["models.manage"] = False
            agent = Agent(None, name, role=role, description=description, model=default_model, permissions=permissions)
            agent.workspace_path = str(self.workspace.ensure_agent_workspace(agent))
            saved = self.db.upsert_agent(agent)
            self.logs.log("agent.create", f"Создан системный агент команды: {saved.name} ({saved.role})", agent_id=saved.id)

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

    def _set_status(self, agent: Agent | None, status: AgentStatus) -> None:
        if not agent:
            return
        agent.status = status.value
        self.db.set_agent_status(agent.id, status.value)
        self.logs.log("agent.status", f"{agent.name}: {status.value}", agent_id=agent.id)

    def _role_agent(self, role: str) -> Agent | None:
        return self.db.get_agent_by_role(role)

    def _chat_project_id(self, chat_id: str) -> int | None:
        chat = self.db.get_chat(chat_id)
        if chat and chat.project_id:
            return chat.project_id
        projects = self.db.list_projects()
        return projects[0].id if projects else None

    def _select_participants(self, text: str, mode: str) -> list[Agent]:
        enabled = [agent for agent in self.db.list_agents() if agent.enabled]
        selected: list[Agent] = []
        lower = text.lower()
        if mode == WorkMode.FAST.value:
            roles = [AgentRole.COORDINATOR.value]
        else:
            roles = list(MODE_PLANS.get(mode, MODE_PLANS[WorkMode.TEAM.value]))
            if any(word in lower for word in ["исслед", "найди", "latest", "обнов", "информац", "документац"]):
                roles.insert(2, AgentRole.RESEARCHER.value)
            if any(word in lower for word in ["безопас", "секрет", "permission", "уязв", "доступ"]):
                roles.append(AgentRole.SECURITY.value)
            if any(word in lower for word in ["deploy", "ci", "docker", "терминал", "скрипт", "запуск"]):
                roles.append(AgentRole.DEVOPS.value)
        for role in roles:
            agent = self._role_agent(role) or (self._role_agent(AgentRole.TESTER.value) if role == AgentRole.QA.value else None)
            if agent and agent not in selected:
                selected.append(agent)
        if not selected:
            selected = enabled[:1]
        if mode != WorkMode.FAST.value:
            observer = self._role_agent(AgentRole.OBSERVER.value)
            if observer and observer not in selected:
                selected.append(observer)
        return selected

    def _build_system_prompt(self, agent: Agent, role_goal: str, mode: str) -> str:
        return f"""{agent.system_prompt}

Ты работаешь не как отдельный чат-бот, а как участник единой AI Studio и общей команды проекта.
Режим работы: {mode}. Роль: {agent.role}. Задача роли: {role_goal}.
Автоматически учитывай свои инструменты, разрешения, память, состояние и специализацию.
Если тебе нечего добавить, явно напиши: confidence=<число от 0 до 1>; no_more_input=true.
Не раскрывай скрытые chain-of-thought. Вместо этого веди краткий журнал действий: решения, делегирование, инструменты, файлы, память, риски и уверенность.
{agent.capability_summary()}"""

    def _project_context(self, chat_id: str) -> str:
        project_id = self._chat_project_id(chat_id)
        project = self.db.get_project(project_id)
        memory = self.db.get_project_memory(project_id)
        tasks = memory.get("tasks", []) if isinstance(memory, dict) else []
        decisions = memory.get("decisions", []) if isinstance(memory, dict) else []
        return "\n".join([
            f"Цель проекта: {project.goal if project else 'не задана'}",
            f"Состояние проекта: {project.description if project and project.description else 'рабочая область активна'}",
            f"Последние решения: {decisions[-5:] if isinstance(decisions, list) else decisions}",
            f"Активные задачи: {tasks[-8:] if isinstance(tasks, list) else tasks}",
        ])

    def _generate_for_agent(self, agent: Agent, chat_id: str, user_text: str, discussion: list[str], purpose: str = "chat", mode: str = WorkMode.TEAM.value) -> str:
        global_model = self.db.get_setting("global_model", "")
        model = agent.effective_model(purpose, global_model)
        role_goal = ROLE_DESCRIPTIONS.get(agent.role, "анализирует задачу со своей стороны")
        if not model:
            self.logs.log("model.skip", f"{agent.name} не имеет выбранной модели; использован локальный журнал действий вместо запроса.", agent_id=agent.id, level="WARNING")
            return f"{agent.name}: нет выбранной модели, поэтому фиксирую решение без генерации: роль {agent.role} должна {role_goal}. confidence=0.55"
        recent = "\n".join(f"{m.sender_name}: {m.content}" for m in self.db.list_messages(chat_id, 12))
        internal = "\n".join(discussion[-8:])
        prompt = f"""Пользователь написал в общий чат проекта:
{user_text}

Централизованный контекст проекта:
{self._project_context(chat_id)}

Последние релевантные сообщения:
{recent}

Текущее внутреннее обсуждение:
{internal}

Сформируй компактный вклад от имени роли {agent.role}: решение, делегирование, инструменты/файлы/память, риски, следующий шаг, confidence=<0..1>."""
        request = GenerationRequest(
            model=model,
            system_prompt=self._build_system_prompt(agent, role_goal, mode),
            prompt=prompt,
            temperature=agent.temperature,
            context=self.memory.build_context(agent, recent, project_context=self._project_context(chat_id)),
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

    def _confidence(self, text: str) -> float:
        lower = text.lower()
        if "no_more_input=true" in lower or "нечего добавить" in lower:
            return 0.0
        marker = "confidence="
        if marker in lower:
            raw = lower.split(marker, 1)[1].split()[0].strip(";,.%")
            try:
                value = float(raw)
                return value / 100 if value > 1 else value
            except ValueError:
                return 0.65
        return 0.65

    def _observer_check(self, observer: Agent | None, discussion: list[str]) -> bool:
        if not observer or len(discussion) < 3:
            return False
        normalized = [line.split(":", 1)[-1].strip().lower()[:140] for line in discussion[-6:]]
        repeated = any(count > 1 for count in Counter(normalized).values())
        if repeated or len(discussion) > 14:
            self._set_status(observer, AgentStatus.ACTION)
            self.logs.log("observer.loop_detected", "Observer обнаружил повтор или чрезмерную длину обсуждения и предлагает завершить текущий цикл.", agent_id=observer.id, level="WARNING")
            self._set_status(observer, AgentStatus.DONE)
            return True
        return False

    def run_project_chat(self, chat_id: str, content: str, mode: str | None = None) -> str:
        mode = mode or self.db.get_setting("work_mode", WorkMode.TEAM.value) or WorkMode.TEAM.value
        self.db.add_message(ChatMessage(None, chat_id, "user", "Пользователь", content))
        participants = self._select_participants(content, mode)
        observer = self._role_agent(AgentRole.OBSERVER.value)
        names = ", ".join(agent.name for agent in participants)
        project_id = self._chat_project_id(chat_id)
        self.logs.log("simulation.start", f"Режим '{mode}'. Выбрана команда: {names}", project_id=project_id)
        self.logs.log("orchestration.start", f"Общий чат {chat_id}: выбраны участники обсуждения: {names}", project_id=project_id)
        plan = [f"{i + 1}. {agent.role}: {ROLE_DESCRIPTIONS.get(agent.role, 'вклад в задачу')}" for i, agent in enumerate(participants) if agent.role != AgentRole.OBSERVER.value]
        for step in plan:
            self.logs.log("action.plan", step, project_id=project_id)
        discussion: list[str] = []
        coordinator = participants[0] if participants else None
        max_rounds = 3 if mode == WorkMode.AUTONOMOUS.value else 1
        for round_index in range(max_rounds):
            self.logs.log("simulation.round", f"Цикл симуляции {round_index + 1}/{max_rounds}", project_id=project_id)
            active_contributions = 0
            for index, agent in enumerate(participants):
                if agent.role == AgentRole.OBSERVER.value:
                    continue
                self._set_status(agent, AgentStatus.ANALYZING if index == 0 else AgentStatus.DISCUSSING)
                if coordinator and coordinator.id != agent.id:
                    route = f"{coordinator.name} делегирует агенту {agent.name}: проанализируй задачу как {agent.role}."
                    self._set_status(coordinator, AgentStatus.WAITING_AGENT)
                    self.send_agent_message(coordinator, agent, route, chat_id=chat_id, topic="delegation")
                    discussion.append(route)
                try:
                    contribution = self._generate_for_agent(agent, chat_id, content, discussion, purpose="planning" if agent.role == AgentRole.COORDINATOR.value else "chat", mode=mode)
                except Exception as exc:  # noqa: BLE001
                    self._set_status(agent, AgentStatus.ERROR)
                    contribution = f"{agent.name}: ошибка генерации ({exc}). Продолжаю по журналу действий. confidence=0.2"
                    self.logs.log("agent.error", contribution, agent_id=agent.id, level="ERROR")
                confidence = self._confidence(contribution)
                message = f"{agent.name} ({agent.role}, confidence={confidence:.2f}): {contribution}"
                discussion.append(message)
                if confidence > 0.05:
                    active_contributions += 1
                if coordinator and coordinator.id != agent.id:
                    self.send_agent_message(agent, coordinator, contribution, chat_id=chat_id, topic="report")
                self.logs.log("simulation.agent_message", message[:1600], agent_id=agent.id, project_id=project_id)
                self._set_status(agent, AgentStatus.DONE if confidence > 0.05 else AgentStatus.IDLE)
                if self._observer_check(observer, discussion):
                    active_contributions = 0
                    break
            if mode != WorkMode.AUTONOMOUS.value or active_contributions == 0:
                break
            discussion.append("Observer: автономный цикл продолжается только если остаются нерешённые шаги; текущий прототип ограничивает глубину для защиты ресурсов.")
        writer = self._role_agent(AgentRole.WRITER.value) or coordinator or (participants[0] if participants else None)
        if writer:
            self._set_status(writer, AgentStatus.ACTION)
            try:
                final = self._generate_for_agent(writer, chat_id, content, discussion + ["Собери единый ответ команды пользователю."], purpose="document", mode=mode)
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
        self.db.update_project_memory(project_id, discussions=[{"chat_id": chat_id, "summary": final[:1000]}], decisions=[f"{mode}: ответ команды сформирован"])
        self.logs.log("simulation.complete", f"Обсуждение завершено, ответ добавлен в общий чат {chat_id}", agent_id=agent_id, project_id=project_id)
        self.logs.log("orchestration.complete", f"Обсуждение завершено, ответ добавлен в общий чат {chat_id}", agent_id=agent_id, project_id=project_id)
        return final

    def send_user_message(self, agent: Agent, chat_id: str, content: str) -> str:
        # Backward-compatible entry point: now routes user input through the project-wide collective chat.
        return self.run_project_chat(chat_id, content)

    def send_agent_message(self, sender: Agent, receiver: Agent, content: str, *, chat_id: str = "default", topic: str = "direct") -> None:
        self.db.add_internal_message(InternalMessage(None, sender.id, receiver.id, content, topic=topic, chat_id=chat_id))
        self.bus.publish(AgentBusMessage(sender.id, receiver.id, content, topic=topic))
