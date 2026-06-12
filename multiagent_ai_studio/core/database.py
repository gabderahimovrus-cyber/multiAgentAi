from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

from .models import Agent, ChatMessage, ChatSession, DEFAULT_PERMISSIONS, InternalMessage, LogEvent, Project, TaskSpec


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.migrate()

    def migrate(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS agents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                role TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                system_prompt TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                planning_model TEXT NOT NULL DEFAULT '',
                coding_model TEXT NOT NULL DEFAULT '',
                review_model TEXT NOT NULL DEFAULT '',
                document_model TEXT NOT NULL DEFAULT '',
                temperature REAL NOT NULL DEFAULT 0.7,
                enabled INTEGER NOT NULL DEFAULT 1,
                parent_id INTEGER,
                workspace_path TEXT NOT NULL DEFAULT '',
                permissions TEXT NOT NULL DEFAULT '{}',
                short_memory TEXT NOT NULL DEFAULT '',
                long_memory TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                goal TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                workspace_path TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS project_agents (
                project_id INTEGER NOT NULL,
                agent_id INTEGER NOT NULL,
                PRIMARY KEY(project_id, agent_id)
            );
            CREATE TABLE IF NOT EXISTS chats (
                id TEXT PRIMARY KEY,
                project_id INTEGER,
                title TEXT NOT NULL,
                archived INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL,
                sender_type TEXT NOT NULL,
                sender_name TEXT NOT NULL,
                content TEXT NOT NULL,
                agent_id INTEGER,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                agent_id INTEGER,
                project_id INTEGER,
                level TEXT NOT NULL DEFAULT 'INFO',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                task_type TEXT NOT NULL,
                status TEXT NOT NULL,
                agent_id INTEGER,
                project_id INTEGER,
                payload TEXT NOT NULL DEFAULT '{}',
                schedule TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS plugins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                path TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 0,
                approved_hash TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS internal_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_agent_id INTEGER,
                receiver_agent_id INTEGER,
                content TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        self._ensure_column("agents", "status", "TEXT NOT NULL DEFAULT 'ожидает'")
        self._ensure_column("projects", "archived", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column("internal_messages", "topic", "TEXT NOT NULL DEFAULT 'direct'")
        self._ensure_column("internal_messages", "chat_id", "TEXT NOT NULL DEFAULT 'default'")
        if not self.get_chat("default"):
            self.upsert_chat(ChatSession("default", None, "Основной чат"))
        if not self.get_setting("global_model", ""):
            self.set_setting("global_model", "")
        if not self.get_setting("ollama_endpoints", ""):
            self.set_setting("ollama_endpoints", "http://127.0.0.1:11434")
        self.conn.commit()

    def _ensure_column(self, table: str, name: str, definition: str) -> None:
        columns = {row["name"] for row in self.conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if name not in columns:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def get_setting(self, key: str, default: str = "") -> str:
        row = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, value))
        self.conn.commit()

    def upsert_agent(self, agent: Agent) -> Agent:
        payload = (
            agent.name, agent.role, agent.description, agent.system_prompt, agent.model,
            agent.planning_model, agent.coding_model, agent.review_model, agent.document_model,
            agent.temperature, int(agent.enabled), agent.parent_id, agent.workspace_path,
            json.dumps(agent.permissions, ensure_ascii=False), agent.short_memory, agent.long_memory,
            agent.status, agent.created_at,
        )
        if agent.id is None:
            cur = self.conn.execute(
                """INSERT INTO agents(name,role,description,system_prompt,model,planning_model,coding_model,review_model,document_model,
                temperature,enabled,parent_id,workspace_path,permissions,short_memory,long_memory,status,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                payload,
            )
            agent.id = int(cur.lastrowid)
        else:
            self.conn.execute(
                """UPDATE agents SET name=?,role=?,description=?,system_prompt=?,model=?,planning_model=?,coding_model=?,review_model=?,document_model=?,
                temperature=?,enabled=?,parent_id=?,workspace_path=?,permissions=?,short_memory=?,long_memory=?,status=?,created_at=? WHERE id=?""",
                payload + (agent.id,),
            )
        self.conn.commit()
        return agent

    def list_agents(self) -> list[Agent]:
        rows = self.conn.execute("SELECT * FROM agents ORDER BY enabled DESC, role, name COLLATE NOCASE").fetchall()
        return [self._row_to_agent(row) for row in rows]

    def get_agent(self, agent_id: int) -> Agent | None:
        row = self.conn.execute("SELECT * FROM agents WHERE id=?", (agent_id,)).fetchone()
        return self._row_to_agent(row) if row else None

    def get_agent_by_role(self, role: str) -> Agent | None:
        row = self.conn.execute("SELECT * FROM agents WHERE role=? AND enabled=1 ORDER BY id LIMIT 1", (role,)).fetchone()
        return self._row_to_agent(row) if row else None

    def set_agent_status(self, agent_id: int | None, status: str) -> None:
        if agent_id is None:
            return
        self.conn.execute("UPDATE agents SET status=? WHERE id=?", (status, agent_id))
        self.conn.commit()

    def delete_agent(self, agent_id: int) -> None:
        self.conn.execute("DELETE FROM agents WHERE id=?", (agent_id,))
        self.conn.commit()

    def _row_to_agent(self, row: sqlite3.Row) -> Agent:
        permissions = dict(DEFAULT_PERMISSIONS)
        try:
            permissions.update(json.loads(row["permissions"] or "{}"))
        except json.JSONDecodeError:
            pass
        return Agent(
            id=row["id"], name=row["name"], role=row["role"], description=row["description"],
            system_prompt=row["system_prompt"], model=row["model"], planning_model=row["planning_model"],
            coding_model=row["coding_model"], review_model=row["review_model"], document_model=row["document_model"],
            temperature=row["temperature"], enabled=bool(row["enabled"]), parent_id=row["parent_id"],
            workspace_path=row["workspace_path"], permissions=permissions, short_memory=row["short_memory"],
            long_memory=row["long_memory"], status=row["status"], created_at=row["created_at"],
        )

    def upsert_chat(self, chat: ChatSession) -> ChatSession:
        chat.id = chat.id or uuid.uuid4().hex
        self.conn.execute(
            "INSERT OR REPLACE INTO chats(id,project_id,title,archived,created_at) VALUES(?,?,?,?,?)",
            (chat.id, chat.project_id, chat.title, int(chat.archived), chat.created_at),
        )
        self.conn.commit()
        return chat

    def create_chat(self, title: str, project_id: int | None = None) -> ChatSession:
        return self.upsert_chat(ChatSession(uuid.uuid4().hex, project_id, title))

    def get_chat(self, chat_id: str) -> ChatSession | None:
        row = self.conn.execute("SELECT * FROM chats WHERE id=?", (chat_id,)).fetchone()
        return ChatSession(id=row["id"], project_id=row["project_id"], title=row["title"], archived=bool(row["archived"]), created_at=row["created_at"]) if row else None

    def list_chats(self, include_archived: bool = False) -> list[ChatSession]:
        query = "SELECT * FROM chats"
        params: tuple = ()
        if not include_archived:
            query += " WHERE archived=0"
        rows = self.conn.execute(query + " ORDER BY created_at DESC", params).fetchall()
        return [ChatSession(id=row["id"], project_id=row["project_id"], title=row["title"], archived=bool(row["archived"]), created_at=row["created_at"]) for row in rows]

    def delete_chat(self, chat_id: str) -> None:
        self.conn.execute("DELETE FROM messages WHERE chat_id=?", (chat_id,))
        self.conn.execute("DELETE FROM internal_messages WHERE chat_id=?", (chat_id,))
        self.conn.execute("DELETE FROM chats WHERE id=?", (chat_id,))
        self.conn.commit()
        if not self.list_chats(include_archived=True):
            self.upsert_chat(ChatSession("default", None, "Основной чат"))

    def archive_chat(self, chat_id: str, archived: bool = True) -> None:
        self.conn.execute("UPDATE chats SET archived=? WHERE id=?", (int(archived), chat_id))
        self.conn.commit()

    def add_message(self, message: ChatMessage) -> ChatMessage:
        cur = self.conn.execute(
            "INSERT INTO messages(chat_id,sender_type,sender_name,content,agent_id,created_at) VALUES(?,?,?,?,?,?)",
            (message.chat_id, message.sender_type, message.sender_name, message.content, message.agent_id, message.created_at),
        )
        self.conn.commit()
        message.id = int(cur.lastrowid)
        return message

    def list_messages(self, chat_id: str = "default", limit: int = 300) -> list[ChatMessage]:
        rows = self.conn.execute("SELECT * FROM messages WHERE chat_id=? ORDER BY id DESC LIMIT ?", (chat_id, limit)).fetchall()
        return [ChatMessage(**dict(row)) for row in reversed(rows)]

    def clear_chat(self, chat_id: str = "default") -> None:
        self.conn.execute("DELETE FROM messages WHERE chat_id=?", (chat_id,))
        self.conn.commit()

    def add_internal_message(self, message: InternalMessage) -> InternalMessage:
        cur = self.conn.execute(
            "INSERT INTO internal_messages(sender_agent_id,receiver_agent_id,content,status,created_at,topic,chat_id) VALUES(?,?,?,?,?,?,?)",
            (message.sender_agent_id, message.receiver_agent_id, message.content, message.status, message.created_at, message.topic, message.chat_id),
        )
        self.conn.commit()
        message.id = int(cur.lastrowid)
        return message

    def list_internal_messages(self, chat_id: str = "default", limit: int = 500) -> list[InternalMessage]:
        rows = self.conn.execute("SELECT * FROM internal_messages WHERE chat_id=? ORDER BY id DESC LIMIT ?", (chat_id, limit)).fetchall()
        return [InternalMessage(id=row["id"], sender_agent_id=row["sender_agent_id"], receiver_agent_id=row["receiver_agent_id"], content=row["content"], status=row["status"], created_at=row["created_at"], topic=row["topic"], chat_id=row["chat_id"]) for row in reversed(rows)]

    def add_log(self, event: LogEvent) -> LogEvent:
        cur = self.conn.execute(
            "INSERT INTO logs(event_type,message,agent_id,project_id,level,created_at) VALUES(?,?,?,?,?,?)",
            (event.event_type, event.message, event.agent_id, event.project_id, event.level, event.created_at),
        )
        self.conn.commit()
        event.id = int(cur.lastrowid)
        return event

    def list_logs(self, limit: int = 500, text_filter: str = "", event_type: str = "", agent_id: int | None = None) -> list[LogEvent]:
        clauses: list[str] = []
        params: list[object] = []
        if text_filter:
            clauses.append("(message LIKE ? OR event_type LIKE ?)")
            params.extend([f"%{text_filter}%", f"%{text_filter}%"])
        if event_type:
            clauses.append("event_type LIKE ?")
            params.append(f"%{event_type}%")
        if agent_id is not None:
            clauses.append("agent_id=?")
            params.append(agent_id)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self.conn.execute(f"SELECT * FROM logs{where} ORDER BY id DESC LIMIT ?", (*params, limit)).fetchall()
        return [LogEvent(**dict(row)) for row in reversed(rows)]

    def clear_logs(self) -> None:
        self.conn.execute("DELETE FROM logs")
        self.conn.commit()

    def upsert_project(self, project: Project) -> Project:
        payload = (project.name, project.goal, project.description, project.workspace_path, int(project.archived), project.created_at)
        if project.id is None:
            cur = self.conn.execute("INSERT INTO projects(name,goal,description,workspace_path,archived,created_at) VALUES(?,?,?,?,?,?)", payload)
            project.id = int(cur.lastrowid)
        else:
            self.conn.execute("UPDATE projects SET name=?,goal=?,description=?,workspace_path=?,archived=?,created_at=? WHERE id=?", payload + (project.id,))
        self.conn.commit()
        return project

    def list_projects(self) -> list[Project]:
        rows = self.conn.execute("SELECT * FROM projects WHERE archived=0 ORDER BY name COLLATE NOCASE").fetchall()
        return [Project(id=row["id"], name=row["name"], goal=row["goal"], description=row["description"], workspace_path=row["workspace_path"], archived=bool(row["archived"]), created_at=row["created_at"]) for row in rows]

    def upsert_task(self, task: TaskSpec) -> TaskSpec:
        payload = (task.title, task.task_type, task.status, task.agent_id, task.project_id, json.dumps(task.payload, ensure_ascii=False), task.schedule, task.created_at)
        if task.id is None:
            cur = self.conn.execute("INSERT INTO tasks(title,task_type,status,agent_id,project_id,payload,schedule,created_at) VALUES(?,?,?,?,?,?,?,?)", payload)
            task.id = int(cur.lastrowid)
        else:
            self.conn.execute("UPDATE tasks SET title=?,task_type=?,status=?,agent_id=?,project_id=?,payload=?,schedule=?,created_at=? WHERE id=?", payload + (task.id,))
        self.conn.commit()
        return task

    def close(self) -> None:
        self.conn.close()
