from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from tkinter import BOTH, END, HORIZONTAL, LEFT, RIGHT, VERTICAL, WORD, BooleanVar, StringVar, Text, Tk, Toplevel, filedialog, messagebox, simpledialog
from tkinter import ttk

from ..core.agents import AgentService
from ..core.change_proposals import ChangeProposalService
from ..core.database import Database
from ..core.logging_service import LogService
from ..core.models import Agent, AgentRole, AgentStatus, DEFAULT_PERMISSIONS, PERMISSION_HELP, WorkMode
from ..core.plugins import PluginManager
from ..core.projects import ProjectService
from ..core.tasks import TaskManager
from ..i18n import Translator
from ..providers.registry import ProviderRegistry


class Tooltip:
    def __init__(self, widget, text: str) -> None:
        self.widget = widget
        self.text = text
        self.tip: Toplevel | None = None
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)

    def show(self, _event=None) -> None:
        if self.tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + 20
        self.tip = Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        ttk.Label(self.tip, text=self.text, wraplength=320, padding=8).pack()

    def hide(self, _event=None) -> None:
        if self.tip:
            self.tip.destroy()
            self.tip = None


class StudioWindow(Tk):
    def __init__(
        self,
        *,
        db: Database,
        translator: Translator,
        providers: ProviderRegistry,
        logs: LogService,
        agents: AgentService,
        projects: ProjectService,
        tasks: TaskManager,
        plugins: PluginManager,
        proposals: ChangeProposalService,
        data_root: Path,
    ) -> None:
        super().__init__()
        self.db = db
        self.t = translator.t
        self.providers = providers
        self.logs = logs
        self.agent_service = agents
        self.project_service = projects
        self.task_manager = tasks
        self.plugins = plugins
        self.proposals = proposals
        self.data_root = data_root
        self.chat_id = self.db.list_chats(include_archived=True)[0].id if self.db.list_chats(include_archived=True) else "default"
        self.current_agent: Agent | None = None
        self.ollama_models: list[str] = []
        self.theme = StringVar(value=self.db.get_setting("theme", "dark"))
        self.status_text = StringVar(value=self.t("top.status.stopped"))
        self.activity_text = StringVar(value="Агенты: 0 активных")
        self.global_model = StringVar(value=self.db.get_setting("global_model", ""))
        self.work_mode = StringVar(value=self.db.get_setting("work_mode", WorkMode.TEAM.value) or WorkMode.TEAM.value)
        self.ollama_endpoints = StringVar(value=self.db.get_setting("ollama_endpoints", "http://127.0.0.1:11434"))
        self._configure_window()
        self._build_styles()
        self._build_layout()
        self._wire_events()
        self._bootstrap_data()
        self.refresh_all()

    def _configure_window(self) -> None:
        self.title(self.t("app.title"))
        self.geometry("1580x960")
        self.minsize(1120, 720)

    def _build_styles(self) -> None:
        self.style = ttk.Style(self)
        try:
            self.style.theme_use("clam")
        except Exception:
            pass
        self.apply_theme()

    def apply_theme(self) -> None:
        dark = self.theme.get() == "dark"
        self.colors = {
            "bg": "#101317" if dark else "#f5f7fb",
            "panel": "#171b21" if dark else "#ffffff",
            "muted": "#9aa4b2" if dark else "#526070",
            "text": "#eef2f7" if dark else "#16202a",
            "accent": "#6aa8ff" if dark else "#1d65d8",
            "border": "#2a313b" if dark else "#d9e0ea",
            "entry": "#0d1117" if dark else "#ffffff",
        }
        self.configure(bg=self.colors["bg"])
        self.style.configure("TFrame", background=self.colors["bg"])
        self.style.configure("Panel.TFrame", background=self.colors["panel"], relief="flat")
        self.style.configure("TLabel", background=self.colors["bg"], foreground=self.colors["text"])
        self.style.configure("Panel.TLabel", background=self.colors["panel"], foreground=self.colors["text"])
        self.style.configure("Muted.TLabel", background=self.colors["panel"], foreground=self.colors["muted"])
        self.style.configure("TButton", padding=6)
        self.style.configure("Accent.TButton", padding=7)
        self.style.configure("Treeview", background=self.colors["panel"], foreground=self.colors["text"], fieldbackground=self.colors["panel"], bordercolor=self.colors["border"])
        self.style.configure("Treeview.Heading", background=self.colors["panel"], foreground=self.colors["text"])

    def _build_layout(self) -> None:
        self.topbar = ttk.Frame(self, style="Panel.TFrame")
        self.topbar.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Button(self.topbar, text=self.t("top.start"), command=self.start_system).pack(side=LEFT, padx=3)
        ttk.Button(self.topbar, text=self.t("top.resume"), command=self.resume_system).pack(side=LEFT, padx=3)
        ttk.Button(self.topbar, text=self.t("top.pause"), command=self.pause_system).pack(side=LEFT, padx=3)
        ttk.Button(self.topbar, text=self.t("top.stop"), command=self.stop_system).pack(side=LEFT, padx=3)
        ttk.Label(self.topbar, textvariable=self.status_text, style="Panel.TLabel").pack(side=LEFT, padx=18)
        ttk.Label(self.topbar, textvariable=self.activity_text, style="Muted.TLabel").pack(side=LEFT)
        ttk.Label(self.topbar, text="Режим", style="Panel.TLabel").pack(side=LEFT, padx=(18, 3))
        self.work_mode_combo = ttk.Combobox(self.topbar, textvariable=self.work_mode, values=[mode.value for mode in WorkMode], width=18, state="readonly")
        self.work_mode_combo.pack(side=LEFT)
        self.work_mode_combo.bind("<<ComboboxSelected>>", lambda _e: self.db.set_setting("work_mode", self.work_mode.get()))
        ttk.Label(self.topbar, text="Ollama endpoints (;)", style="Panel.TLabel").pack(side=LEFT, padx=(18, 3))
        ttk.Entry(self.topbar, textvariable=self.ollama_endpoints, width=38).pack(side=LEFT)
        ttk.Button(self.topbar, text="Применить", command=self.apply_model_settings).pack(side=LEFT, padx=4)
        ttk.Button(self.topbar, text="Панели", command=self.restore_panels).pack(side=LEFT, padx=4)
        ttk.Label(self.topbar, text=self.t("settings.theme"), style="Panel.TLabel").pack(side=RIGHT, padx=(10, 3))
        self.theme_box = ttk.Combobox(self.topbar, values=["dark", "light"], textvariable=self.theme, width=8, state="readonly")
        self.theme_box.pack(side=RIGHT)
        self.theme_box.bind("<<ComboboxSelected>>", lambda _e: self.change_theme())

        self.main_pane = ttk.PanedWindow(self, orient=HORIZONTAL)
        self.main_pane.pack(fill=BOTH, expand=True, padx=8, pady=4)
        self.left = ttk.Frame(self.main_pane, style="Panel.TFrame")
        self.center_vertical = ttk.PanedWindow(self.main_pane, orient=VERTICAL)
        self.right = ttk.Frame(self.main_pane, style="Panel.TFrame")
        self.main_pane.add(self.left, weight=1)
        self.main_pane.add(self.center_vertical, weight=4)
        self.main_pane.add(self.right, weight=2)
        self._panels_visible = {"left": True, "right": True, "bottom": True}
        self.chat_frame = ttk.Frame(self.center_vertical, style="Panel.TFrame")
        self.log_frame = ttk.Frame(self.center_vertical, style="Panel.TFrame")
        self.center_vertical.add(self.chat_frame, weight=5)
        self.center_vertical.add(self.log_frame, weight=2)
        self._build_left_panel()
        self._build_chat_panel()
        self._build_right_panel()
        self._build_log_panel()

    def _build_left_panel(self) -> None:
        hide = ttk.Frame(self.left, style="Panel.TFrame")
        hide.pack(fill="x", padx=8, pady=(8, 0))
        ttk.Button(hide, text="Скрыть левую", command=lambda: self.toggle_panel("left")).pack(side=RIGHT)
        ttk.Label(self.left, text="Проекты, чаты и история", style="Panel.TLabel", font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=10, pady=(6, 3))
        ttk.Label(self.left, text="Чаты проекта", style="Muted.TLabel").pack(anchor="w", padx=10, pady=(2, 3))
        chat_buttons = ttk.Frame(self.left, style="Panel.TFrame")
        chat_buttons.pack(fill="x", padx=10)
        ttk.Button(chat_buttons, text="+", width=3, command=self.create_chat).pack(side=LEFT, padx=(0, 3))
        ttk.Button(chat_buttons, text="✎", width=3, command=self.rename_chat).pack(side=LEFT, padx=3)
        ttk.Button(chat_buttons, text="Архив", command=self.archive_chat).pack(side=LEFT, padx=3)
        ttk.Button(chat_buttons, text="−", width=3, command=self.delete_chat).pack(side=LEFT, padx=3)
        self.chat_list = ttk.Treeview(self.left, show="tree", height=8)
        self.chat_list.pack(fill="x", padx=10, pady=(4, 8))
        self.chat_list.bind("<<TreeviewSelect>>", lambda _e: self.on_chat_selected())

        ttk.Label(self.left, text=self.t("left.projects"), style="Panel.TLabel", font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=10, pady=(8, 3))
        ttk.Button(self.left, text=self.t("projects.new"), command=self.create_project).pack(fill="x", padx=10, pady=(0, 4))
        self.project_list = ttk.Treeview(self.left, show="tree", height=7)
        self.project_list.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _build_chat_panel(self) -> None:
        toolbar = ttk.Frame(self.chat_frame, style="Panel.TFrame")
        toolbar.pack(fill="x", padx=10, pady=(10, 4))
        ttk.Button(toolbar, text="Скрыть низ", command=lambda: self.toggle_panel("bottom")).pack(side=RIGHT, padx=3)
        ttk.Button(toolbar, text=self.t("chat.export"), command=self.export_history).pack(side=RIGHT, padx=3)
        ttk.Button(toolbar, text=self.t("chat.clear"), command=self.clear_session).pack(side=RIGHT, padx=3)
        self.chat_title = ttk.Label(toolbar, text="Единый общий чат проекта", style="Panel.TLabel", font=("Segoe UI", 12, "bold"))
        self.chat_title.pack(side=LEFT)
        self.chat_text = Text(self.chat_frame, wrap=WORD, height=18, borderwidth=0, padx=12, pady=12, undo=True)
        self.chat_text.pack(fill=BOTH, expand=True, padx=10, pady=4)
        self.chat_text.configure(state="disabled", bg=self.colors["entry"], fg=self.colors["text"], insertbackground=self.colors["text"], font=("Segoe UI", 10))
        self.chat_text.tag_configure("user", foreground=self.colors["accent"], font=("Segoe UI", 10, "bold"))
        self.chat_text.tag_configure("agent", foreground="#74d99f", font=("Segoe UI", 10, "bold"))
        self.chat_text.tag_configure("meta", foreground=self.colors["muted"], font=("Segoe UI", 8))
        entry_frame = ttk.Frame(self.chat_frame, style="Panel.TFrame")
        entry_frame.pack(fill="x", padx=10, pady=(4, 10))
        self.message_entry = Text(entry_frame, height=4, wrap=WORD, borderwidth=1, padx=8, pady=8, undo=True)
        self.message_entry.pack(side=LEFT, fill="x", expand=True)
        self.message_entry.configure(bg=self.colors["entry"], fg=self.colors["text"], insertbackground=self.colors["text"], font=("Segoe UI", 10))
        self.message_entry.bind("<Return>", self.on_enter)
        ttk.Button(entry_frame, text="Отправить в общий чат", style="Accent.TButton", command=self.send_message).pack(side=RIGHT, padx=(8, 0), fill="y")

    def _build_right_panel(self) -> None:
        right_top = ttk.Frame(self.right, style="Panel.TFrame")
        right_top.pack(fill="x", padx=8, pady=(8, 0))
        ttk.Button(right_top, text="Скрыть правую", command=lambda: self.toggle_panel("right")).pack(side=RIGHT)
        ttk.Label(self.right, text="Агенты команды", style="Panel.TLabel", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=10, pady=(6, 6))
        ttk.Button(self.right, text="Создать нового агента", command=self.create_agent).pack(fill="x", padx=10, pady=(0, 4))
        columns = ("role", "model", "status")
        self.agent_list = ttk.Treeview(self.right, columns=columns, show="tree headings", height=9)
        self.agent_list.heading("#0", text="Имя")
        self.agent_list.heading("role", text="Роль")
        self.agent_list.heading("model", text="Модель")
        self.agent_list.heading("status", text="Состояние")
        self.agent_list.column("#0", width=110)
        self.agent_list.column("role", width=85)
        self.agent_list.column("model", width=105)
        self.agent_list.column("status", width=100)
        self.agent_list.pack(fill="x", padx=10, pady=(0, 8))
        self.agent_list.bind("<<TreeviewSelect>>", lambda _e: self.on_agent_selected())

        card = ttk.LabelFrame(self.right, text="Карточка агента")
        card.pack(fill=BOTH, expand=True, padx=10, pady=(0, 10))
        self.agent_name = StringVar()
        self.agent_role = StringVar()
        self.agent_model = StringVar()
        self.agent_enabled = BooleanVar(value=True)
        self.agent_temp = StringVar(value="0.7")
        self._labeled_entry(card, self.t("agent.name"), self.agent_name)
        self._labeled_combo(card, self.t("agent.role"), self.agent_role, [role.value for role in AgentRole])
        self._labeled_combo(card, "Модель агента (пусто = глобальная)", self.agent_model, [])
        self._labeled_entry(card, self.t("agent.temperature"), self.agent_temp)
        ttk.Checkbutton(card, text=self.t("agent.enabled"), variable=self.agent_enabled).pack(anchor="w", pady=4, padx=8)
        ttk.Label(card, text="Глобальная модель по умолчанию", style="Panel.TLabel").pack(anchor="w", pady=(8, 2), padx=8)
        self.global_model_combo = ttk.Combobox(card, textvariable=self.global_model, values=[])
        self.global_model_combo.pack(fill="x", padx=8)
        ttk.Label(card, text=self.t("agent.system_prompt"), style="Panel.TLabel").pack(anchor="w", pady=(8, 2), padx=8)
        self.system_prompt = Text(card, height=5, wrap=WORD)
        self.system_prompt.pack(fill="x", padx=8)
        self.system_prompt.configure(bg=self.colors["entry"], fg=self.colors["text"], insertbackground=self.colors["text"])
        perms_wrap = ttk.LabelFrame(card, text="Разрешения и инструменты")
        perms_wrap.pack(fill="x", padx=8, pady=8)
        self.permission_vars: dict[str, BooleanVar] = {}
        for i, perm in enumerate(DEFAULT_PERMISSIONS):
            var = BooleanVar(value=DEFAULT_PERMISSIONS[perm])
            self.permission_vars[perm] = var
            cb = ttk.Checkbutton(perms_wrap, text=perm, variable=var)
            cb.grid(row=i // 2, column=i % 2, sticky="w", padx=4, pady=2)
            Tooltip(cb, PERMISSION_HELP.get(perm, ""))
        actions = ttk.Frame(card)
        actions.pack(fill="x", padx=8, pady=4)
        ttk.Button(actions, text="Сохранить", command=self.save_agent).pack(side=LEFT, padx=2)
        ttk.Button(actions, text="Клон", command=self.clone_agent).pack(side=LEFT, padx=2)
        ttk.Button(actions, text="Удалить", command=self.delete_agent).pack(side=LEFT, padx=2)
        ttk.Button(actions, text="Память", command=self.show_agent_memory).pack(side=LEFT, padx=2)
        ttk.Button(actions, text="История", command=self.show_agent_history).pack(side=LEFT, padx=2)
        ttk.Button(card, text=self.t("agent.refresh_models"), command=self.refresh_models).pack(fill="x", padx=8, pady=4)

    def _build_log_panel(self) -> None:
        toolbar = ttk.Frame(self.log_frame, style="Panel.TFrame")
        toolbar.pack(fill="x", padx=10, pady=(8, 4))
        ttk.Label(toolbar, text="Наблюдение за системой", style="Panel.TLabel", font=("Segoe UI", 11, "bold")).pack(side=LEFT)
        self.log_filter = StringVar()
        self.log_type_filter = StringVar()
        self.log_agent_filter = StringVar()
        self.log_project_filter = StringVar()
        ttk.Entry(toolbar, textvariable=self.log_filter, width=22).pack(side=LEFT, padx=5)
        ttk.Entry(toolbar, textvariable=self.log_type_filter, width=18).pack(side=LEFT, padx=5)
        ttk.Entry(toolbar, textvariable=self.log_agent_filter, width=8).pack(side=LEFT, padx=5)
        ttk.Entry(toolbar, textvariable=self.log_project_filter, width=8).pack(side=LEFT, padx=5)
        ttk.Button(toolbar, text=self.t("logs.filter"), command=self.refresh_logs).pack(side=LEFT)
        ttk.Button(toolbar, text=self.t("logs.export"), command=self.export_logs).pack(side=RIGHT)
        self.log_tabs = ttk.Notebook(self.log_frame)
        self.log_tabs.pack(fill=BOTH, expand=True, padx=10, pady=(0, 10))
        self.event_text = self._log_text_widget(self.log_tabs)
        self.internal_text = self._log_text_widget(self.log_tabs)
        self.reasoning_text = self._log_text_widget(self.log_tabs)
        self.simulation_text = self._log_text_widget(self.log_tabs)
        self.brain_text = self._log_text_widget(self.log_tabs)
        decision_frame = ttk.Frame(self.log_tabs, style="Panel.TFrame")
        self.decision_list = ttk.Treeview(decision_frame, columns=("type", "agent", "message"), show="headings", height=7)
        for column, title in (("type", "Тип"), ("agent", "Агент"), ("message", "Запрос подтверждения")):
            self.decision_list.heading(column, text=title)
        self.decision_list.column("type", width=150)
        self.decision_list.column("agent", width=80)
        self.decision_list.column("message", width=600)
        self.decision_list.pack(fill=BOTH, expand=True, padx=6, pady=6)
        decision_buttons = ttk.Frame(decision_frame, style="Panel.TFrame")
        decision_buttons.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(decision_buttons, text="Принять", command=lambda: self.resolve_decision(True)).pack(side=LEFT, padx=3)
        ttk.Button(decision_buttons, text="Отклонить", command=lambda: self.resolve_decision(False)).pack(side=LEFT, padx=3)
        self.log_tabs.add(self.event_text, text="Системный журнал")
        self.log_tabs.add(self.simulation_text, text="Журнал симуляции")
        self.log_tabs.add(self.internal_text, text="Внутренние сообщения")
        self.log_tabs.add(self.brain_text, text="Мозг системы")
        self.log_tabs.add(decision_frame, text="Решения")
        self.log_tabs.add(self.reasoning_text, text="Reasoning")

    def _log_text_widget(self, parent) -> Text:
        widget = Text(parent, height=8, wrap=WORD, borderwidth=0, padx=8, pady=8)
        widget.configure(state="disabled", bg=self.colors["entry"], fg=self.colors["text"], font=("Consolas", 9))
        return widget

    def _labeled_entry(self, parent, label: str, var: StringVar) -> None:
        ttk.Label(parent, text=label).pack(anchor="w", pady=(6, 2), padx=8)
        ttk.Entry(parent, textvariable=var).pack(fill="x", padx=8)

    def _labeled_combo(self, parent, label: str, var: StringVar, values: list[str]) -> None:
        ttk.Label(parent, text=label).pack(anchor="w", pady=(6, 2), padx=8)
        combo = ttk.Combobox(parent, textvariable=var, values=values)
        combo.pack(fill="x", padx=8)
        if "Модель агента" in label or label == self.t("agent.model"):
            self.model_combo = combo

    def _wire_events(self) -> None:
        self.logs.subscribe(lambda _event: self.after(0, self.refresh_logs))
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _bootstrap_data(self) -> None:
        self.apply_model_settings(silent=True)
        default_model = self.global_model.get() or (self.ollama_models[0] if self.ollama_models else "")
        self.agent_service.bootstrap_default_agent(default_model)
        if not self.db.list_projects():
            self.project_service.create_project("Локальная рабочая область", "Общая область для автономной работы агентов")
        if not self.db.list_chats():
            self.db.create_chat("Основной чат")

    def refresh_all(self) -> None:
        self.refresh_chats()
        self.refresh_agents()
        self.refresh_projects()
        self.refresh_chat()
        self.refresh_logs()
        self.update_activity()

    def apply_model_settings(self, silent: bool = False) -> None:
        endpoints = [item.strip() for item in self.ollama_endpoints.get().split(";") if item.strip()]
        provider = self.providers.get("ollama")
        if hasattr(provider, "configure_endpoints"):
            provider.configure_endpoints(endpoints)
        self.db.set_setting("ollama_endpoints", ";".join(endpoints) or "http://127.0.0.1:11434")
        self.refresh_models(silent=silent)
        self.db.set_setting("global_model", self.global_model.get())
        self.db.set_setting("work_mode", self.work_mode.get())

    def refresh_models(self, silent: bool = False) -> None:
        try:
            provider = self.providers.get("ollama")
            self.ollama_models = provider.list_models()
            if hasattr(self, "model_combo"):
                self.model_combo.configure(values=self.ollama_models)
            if hasattr(self, "global_model_combo"):
                self.global_model_combo.configure(values=self.ollama_models)
            if hasattr(provider, "list_model_details"):
                details = provider.list_model_details()
                detail_text = "; ".join(f"{item['name']} [{item['source']}] size={item.get('size') or '-'} params={item.get('parameters') or '-'} status={item.get('status')}" for item in details)
                self.logs.log("model.discover", f"Обнаружены модели Ollama: {detail_text or 'нет доступных моделей'}")
            else:
                self.logs.log("model.discover", f"Обнаружены модели Ollama: {', '.join(self.ollama_models) or 'нет'}")
        except Exception as exc:  # noqa: BLE001
            self.ollama_models = []
            if not silent:
                messagebox.showwarning(self.t("app.title"), self.t("error.ollama", error=exc))

    def refresh_chats(self) -> None:
        self.chat_list.delete(*self.chat_list.get_children())
        chats = self.db.list_chats(include_archived=False)
        for chat in chats:
            self.chat_list.insert("", END, iid=chat.id, text=chat.title)
        if chats and self.chat_id not in {chat.id for chat in chats}:
            self.chat_id = chats[0].id
        if self.chat_id in self.chat_list.get_children(""):
            self.chat_list.selection_set(self.chat_id)

    def refresh_agents(self) -> None:
        self.agent_list.delete(*self.agent_list.get_children())
        agents = self.db.list_agents()
        for agent in agents:
            marker = "●" if agent.enabled else "○"
            self.agent_list.insert("", END, iid=str(agent.id), text=f"{marker} {agent.name}", values=(agent.role, agent.model or self.global_model.get(), agent.status))
        if agents and (not self.current_agent or not self.db.get_agent(self.current_agent.id or -1)):
            self.current_agent = agents[0]
            self.agent_list.selection_set(str(self.current_agent.id))
            self.load_agent_form(self.current_agent)

    def refresh_projects(self) -> None:
        self.project_list.delete(*self.project_list.get_children())
        for project in self.db.list_projects():
            self.project_list.insert("", END, iid=str(project.id), text=f"{project.name} — {project.goal[:40]}")

    def refresh_chat(self) -> None:
        chat = self.db.get_chat(self.chat_id)
        self.chat_title.configure(text=f"Единый общий чат: {chat.title if chat else self.chat_id}")
        self.chat_text.configure(state="normal")
        self.chat_text.delete("1.0", END)
        for msg in self.db.list_messages(self.chat_id):
            tag = "user" if msg.sender_type == "user" else "agent"
            self.chat_text.insert(END, f"{msg.sender_name}\n", tag)
            self.chat_text.insert(END, f"{msg.content}\n", None)
            self.chat_text.insert(END, f"{msg.created_at}\n\n", "meta")
        self.chat_text.configure(state="disabled")
        self.chat_text.see(END)

    def refresh_logs(self) -> None:
        agent_filter = None
        if self.log_agent_filter.get().strip().isdigit():
            agent_filter = int(self.log_agent_filter.get().strip())
        project_filter = int(self.log_project_filter.get().strip()) if self.log_project_filter.get().strip().isdigit() else None
        events = self.db.list_logs(text_filter=self.log_filter.get(), event_type=self.log_type_filter.get(), agent_id=agent_filter, project_id=project_filter)
        self._fill_text(self.event_text, [f"[{event.created_at}] {event.level} {event.event_type} agent={event.agent_id or '-'}: {event.message}" for event in events])
        internal_lines = []
        for msg in self.db.list_internal_messages(self.chat_id):
            internal_lines.append(f"[{msg.created_at}] {msg.topic} {msg.sender_agent_id}->{msg.receiver_agent_id}: {msg.content}")
        self._fill_text(self.internal_text, internal_lines)
        reasoning = [f"[{event.created_at}] {event.event_type} agent={event.agent_id}: {event.message}" for event in events if event.event_type in {"agent.reasoning", "simulation.agent_message", "agent.status"}]
        self._fill_text(self.reasoning_text, reasoning)
        simulation = [f"[{event.created_at}] {event.level} {event.event_type} agent={event.agent_id or '-'} project={event.project_id or '-'}: {event.message}" for event in events if event.event_type.startswith(("simulation.", "action.", "observer."))]
        self._fill_text(self.simulation_text, simulation)
        brain_lines = []
        for agent in self.db.list_agents():
            brain_lines.append(f"{agent.name} [{agent.role}] — {agent.status}; модель: {agent.model or self.global_model.get() or 'глобальная не выбрана'}; workspace: {agent.workspace_path or '-'}")
        brain_lines.append("\nОчередь действий:")
        brain_lines.extend(f"- {event.message}" for event in events if event.event_type == "action.plan")
        self._fill_text(self.brain_text, brain_lines)
        self.decision_list.delete(*self.decision_list.get_children())
        for event in events:
            if event.level == "ACTION" or event.event_type.startswith("approval."):
                self.decision_list.insert("", END, iid=str(event.id), values=(event.event_type, event.agent_id or "-", event.message[:240]))

    def _fill_text(self, widget: Text, lines: list[str]) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", END)
        widget.insert(END, "\n".join(lines))
        widget.configure(state="disabled")
        widget.see(END)

    def on_chat_selected(self) -> None:
        selection = self.chat_list.selection()
        if selection:
            self.chat_id = selection[0]
            self.refresh_chat()
            self.refresh_logs()

    def on_agent_selected(self) -> None:
        selection = self.agent_list.selection()
        if not selection:
            return
        agent = self.db.get_agent(int(selection[0]))
        if agent:
            self.current_agent = agent
            self.load_agent_form(agent)

    def load_agent_form(self, agent: Agent) -> None:
        self.agent_name.set(agent.name)
        self.agent_role.set(agent.role)
        self.agent_model.set(agent.model)
        self.agent_enabled.set(agent.enabled)
        self.agent_temp.set(str(agent.temperature))
        self.system_prompt.delete("1.0", END)
        self.system_prompt.insert("1.0", agent.system_prompt)
        for perm, var in self.permission_vars.items():
            var.set(bool(agent.permissions.get(perm, False)))

    def save_agent(self) -> None:
        self.db.set_setting("global_model", self.global_model.get().strip())
        if not self.current_agent:
            return
        self.current_agent.name = self.agent_name.get().strip() or self.current_agent.name
        self.current_agent.role = self.agent_role.get().strip() or self.current_agent.role
        self.current_agent.model = self.agent_model.get().strip()
        self.current_agent.enabled = self.agent_enabled.get()
        try:
            self.current_agent.temperature = float(self.agent_temp.get().replace(",", "."))
        except ValueError:
            self.current_agent.temperature = 0.7
        self.current_agent.system_prompt = self.system_prompt.get("1.0", END).strip()
        self.current_agent.permissions = {perm: var.get() for perm, var in self.permission_vars.items()}
        self.db.upsert_agent(self.current_agent)
        self.logs.log("agent.update", f"Обновлены настройки агента: {self.current_agent.name}", agent_id=self.current_agent.id)
        self.refresh_agents()

    def create_agent(self) -> None:
        name = simpledialog.askstring(self.t("agent.new"), "Введите имя агента:", parent=self)
        if not name:
            return
        role = simpledialog.askstring(self.t("agent.new"), "Роль агента:", initialvalue=AgentRole.DEVELOPER.value, parent=self) or AgentRole.DEVELOPER.value
        description = simpledialog.askstring(self.t("agent.new"), "Краткое описание:", parent=self) or ""
        agent = self.agent_service.create_agent(name, role, self.global_model.get(), description=description)
        self.current_agent = agent
        self.refresh_agents()
        self.agent_list.selection_set(str(agent.id))

    def clone_agent(self) -> None:
        if not self.current_agent:
            messagebox.showinfo(self.t("app.title"), self.t("error.no_agent"))
            return
        name = simpledialog.askstring(self.t("agent.clone"), "Имя клона:", initialvalue=f"{self.current_agent.name} копия", parent=self)
        if not name:
            return
        clone = self.agent_service.clone_agent(self.current_agent, name)
        self.current_agent = clone
        self.refresh_agents()
        self.agent_list.selection_set(str(clone.id))

    def delete_agent(self) -> None:
        if not self.current_agent:
            return
        if messagebox.askyesno(self.t("agent.delete"), self.t("confirm.delete_agent")):
            self.agent_service.delete_agent(self.current_agent.id or 0)
            self.current_agent = None
            self.refresh_agents()

    def show_agent_memory(self) -> None:
        if self.current_agent:
            messagebox.showinfo("Память агента", f"Краткая память:\n{self.current_agent.short_memory}\n\nДолгая память:\n{self.current_agent.long_memory}")

    def show_agent_history(self) -> None:
        if self.current_agent:
            logs = self.db.list_logs(agent_id=self.current_agent.id, limit=100)
            messagebox.showinfo("История действий", "\n".join(f"{e.created_at} {e.event_type}: {e.message}" for e in logs[-30:]) or "История пуста")

    def create_chat(self) -> None:
        title = simpledialog.askstring("Новый чат", "Название чата:", parent=self)
        if not title:
            return
        chat = self.db.create_chat(title)
        self.chat_id = chat.id
        self.logs.log("chat.create", f"Создан чат: {title}")
        self.refresh_chats()
        self.refresh_chat()

    def rename_chat(self) -> None:
        chat = self.db.get_chat(self.chat_id)
        if not chat:
            return
        title = simpledialog.askstring("Переименовать чат", "Новое название:", initialvalue=chat.title, parent=self)
        if title:
            chat.title = title
            self.db.upsert_chat(chat)
            self.logs.log("chat.rename", f"Чат переименован: {title}")
            self.refresh_chats()
            self.refresh_chat()

    def archive_chat(self) -> None:
        self.db.archive_chat(self.chat_id, True)
        self.logs.log("chat.archive", f"Чат архивирован: {self.chat_id}")
        self.refresh_chats()
        self.refresh_chat()

    def delete_chat(self) -> None:
        if messagebox.askyesno("Удалить чат", "Удалить текущий чат и его историю?"):
            self.db.delete_chat(self.chat_id)
            chats = self.db.list_chats(include_archived=False)
            self.chat_id = chats[0].id if chats else "default"
            self.logs.log("chat.delete", f"Чат удалён")
            self.refresh_chats()
            self.refresh_chat()

    def create_project(self) -> None:
        name = simpledialog.askstring(self.t("projects.new"), "Название проекта:", parent=self)
        if not name:
            return
        goal = simpledialog.askstring(self.t("projects.new"), "Цель проекта:", parent=self) or ""
        self.project_service.create_project(name, goal)
        self.refresh_projects()

    def on_enter(self, event) -> str | None:
        if event.state & 0x0001:
            return None
        self.send_message()
        return "break"

    def send_message(self) -> None:
        text = self.message_entry.get("1.0", END).strip()
        if not text:
            return
        self.message_entry.delete("1.0", END)
        self.append_pending_user_message(text)
        threading.Thread(target=self._generate_response, args=(text,), daemon=True).start()

    def append_pending_user_message(self, text: str) -> None:
        self.chat_text.configure(state="normal")
        self.chat_text.insert(END, "Пользователь\n", "user")
        self.chat_text.insert(END, text + "\n")
        self.chat_text.insert(END, datetime.utcnow().isoformat() + "\n\n", "meta")
        self.chat_text.configure(state="disabled")
        self.chat_text.see(END)

    def _generate_response(self, text: str) -> None:
        try:
            self.agent_service.run_project_chat(self.chat_id, text, self.work_mode.get())
        except Exception as exc:  # noqa: BLE001
            self.logs.log("orchestration.error", str(exc), level="ERROR")
            self.after(0, lambda: messagebox.showerror(self.t("app.title"), self.t("error.ollama", error=exc)))
        finally:
            self.after(0, self.refresh_all)

    def clear_session(self) -> None:
        if messagebox.askyesno(self.t("chat.clear"), self.t("confirm.clear")):
            self.db.clear_chat(self.chat_id)
            self.db.clear_logs()
            self.refresh_chat()
            self.refresh_logs()

    def export_history(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".md", filetypes=[("Markdown", "*.md"), ("Text", "*.txt")])
        if not path:
            return
        lines = []
        for msg in self.db.list_messages(self.chat_id, limit=100000):
            lines.append(f"## {msg.sender_name}\n\n{msg.content}\n\n_{msg.created_at}_\n")
        Path(path).write_text("\n".join(lines), encoding="utf-8")
        self.logs.log("chat.export", f"История экспортирована: {path}")

    def export_logs(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".log", filetypes=[("Log", "*.log"), ("Text", "*.txt")])
        if path:
            self.logs.export(Path(path))

    def start_system(self) -> None:
        self.task_manager.start()
        self.status_text.set(self.t("top.status.running"))
        self.update_activity()

    def resume_system(self) -> None:
        self.task_manager.resume()
        self.status_text.set(self.t("top.status.running"))
        self.update_activity()

    def pause_system(self) -> None:
        self.task_manager.pause()
        self.status_text.set(self.t("top.status.paused"))
        self.update_activity()

    def stop_system(self) -> None:
        self.task_manager.stop()
        self.status_text.set(self.t("top.status.stopped"))
        self.update_activity()

    def update_activity(self) -> None:
        agents = self.db.list_agents()
        active = sum(1 for agent in agents if agent.enabled)
        busy = sum(1 for agent in agents if agent.status not in {AgentStatus.IDLE.value, AgentStatus.DONE.value})
        self.activity_text.set(f"Агенты: {active} активных, {busy} в работе")

    def change_theme(self) -> None:
        self.db.set_setting("theme", self.theme.get())
        self.apply_theme()
        for widget in (getattr(self, "chat_text", None), getattr(self, "message_entry", None), getattr(self, "event_text", None), getattr(self, "internal_text", None), getattr(self, "reasoning_text", None), getattr(self, "simulation_text", None), getattr(self, "brain_text", None), getattr(self, "system_prompt", None)):
            if widget:
                widget.configure(bg=self.colors["entry"], fg=self.colors["text"], insertbackground=self.colors["text"])


    def toggle_panel(self, panel: str) -> None:
        if panel == "left" and self._panels_visible.get("left"):
            self.main_pane.forget(self.left)
            self._panels_visible["left"] = False
        elif panel == "right" and self._panels_visible.get("right"):
            self.main_pane.forget(self.right)
            self._panels_visible["right"] = False
        elif panel == "bottom" and self._panels_visible.get("bottom"):
            self.center_vertical.forget(self.log_frame)
            self._panels_visible["bottom"] = False

    def restore_panels(self) -> None:
        if not self._panels_visible.get("left"):
            self.main_pane.insert(0, self.left, weight=1)
            self._panels_visible["left"] = True
        if not self._panels_visible.get("right"):
            self.main_pane.add(self.right, weight=2)
            self._panels_visible["right"] = True
        if not self._panels_visible.get("bottom"):
            self.center_vertical.add(self.log_frame, weight=2)
            self._panels_visible["bottom"] = True

    def resolve_decision(self, accepted: bool) -> None:
        selection = self.decision_list.selection()
        if not selection:
            return
        decision_id = selection[0]
        state = "принято" if accepted else "отклонено"
        self.logs.log("approval.resolve", f"Решение #{decision_id} {state} пользователем", level="INFO")
        self.refresh_logs()

    def on_close(self) -> None:
        self.db.close()
        self.destroy()
