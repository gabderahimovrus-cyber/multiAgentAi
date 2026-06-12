from __future__ import annotations

from .database import Database
from .models import Agent


class MemoryService:
    """Дисковая краткосрочная и долговременная память. Позже сюда подключается vector/RAG backend."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def build_context(self, agent: Agent, recent_dialogue: str) -> str:
        blocks = []
        if agent.short_memory:
            blocks.append("Краткосрочная память агента:\n" + agent.short_memory)
        if agent.long_memory:
            blocks.append("Долговременная память агента:\n" + agent.long_memory)
        if recent_dialogue:
            blocks.append("Последние сообщения:\n" + recent_dialogue)
        return "\n\n".join(blocks)

    def remember_interaction(self, agent: Agent, user_text: str, answer: str) -> Agent:
        snippet = f"Пользователь: {user_text[:500]}\n{agent.name}: {answer[:700]}"
        agent.short_memory = (agent.short_memory + "\n\n" + snippet).strip()[-6000:]
        if "запомни" in user_text.lower() or "важно" in user_text.lower():
            agent.long_memory = (agent.long_memory + "\n\n" + snippet).strip()[-20000:]
        return self.db.upsert_agent(agent)
