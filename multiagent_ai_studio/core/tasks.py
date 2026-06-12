from __future__ import annotations

from enum import Enum

from .database import Database
from .logging_service import LogService
from .models import TaskSpec


class SystemState(str, Enum):
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"


class TaskManager:
    def __init__(self, db: Database, logs: LogService) -> None:
        self.db = db
        self.logs = logs
        self.state = SystemState.STOPPED

    def start(self) -> None:
        self.state = SystemState.RUNNING
        self.logs.log("system.start", "Система агентов запущена")

    def resume(self) -> None:
        self.state = SystemState.RUNNING
        self.logs.log("system.resume", "Система агентов продолжила работу")

    def pause(self) -> None:
        self.state = SystemState.PAUSED
        self.logs.log("system.pause", "Система агентов поставлена на паузу")

    def stop(self) -> None:
        self.state = SystemState.STOPPED
        self.logs.log("system.stop", "Система агентов остановлена")

    def create_task(self, task: TaskSpec) -> TaskSpec:
        saved = self.db.upsert_task(task)
        self.logs.log("task.create", f"Создана задача: {task.title}", agent_id=task.agent_id, project_id=task.project_id)
        return saved
