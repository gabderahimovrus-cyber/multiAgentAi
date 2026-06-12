from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from queue import Queue

from .logging_service import LogService


@dataclass
class AgentBusMessage:
    sender_agent_id: int | None
    receiver_agent_id: int | None
    content: str
    topic: str = "direct"
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


class AgentMessageBus:
    def __init__(self, logs: LogService) -> None:
        self.logs = logs
        self._queue: Queue[AgentBusMessage] = Queue()
        self.subscribers = []

    def subscribe(self, callback) -> None:
        self.subscribers.append(callback)

    def publish(self, message: AgentBusMessage) -> None:
        self._queue.put(message)
        self.logs.log("agent.message", f"Сообщение агента {message.sender_agent_id} для {message.receiver_agent_id}: {message.content[:160]}", agent_id=message.sender_agent_id)
        for callback in list(self.subscribers):
            callback(message)

    def drain(self) -> list[AgentBusMessage]:
        items = []
        while not self._queue.empty():
            items.append(self._queue.get_nowait())
        return items
