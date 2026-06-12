from __future__ import annotations

from .database import Database
from .file_workspace import WorkspaceService
from .logging_service import LogService
from .models import Project


class ProjectService:
    def __init__(self, db: Database, workspace: WorkspaceService, logs: LogService) -> None:
        self.db = db
        self.workspace = workspace
        self.logs = logs

    def create_project(self, name: str, goal: str = "", description: str = "") -> Project:
        path = self.workspace.create_project_workspace(name)
        project = self.db.upsert_project(Project(None, name, goal, description, str(path)))
        self.logs.log("project.create", f"Создан проект: {name}", project_id=project.id)
        return project
