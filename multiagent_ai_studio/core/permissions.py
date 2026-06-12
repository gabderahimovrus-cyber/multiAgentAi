from __future__ import annotations

from .models import Agent


DANGEROUS_PERMISSIONS = {
    "scripts.execute",
    "network.access",
    "browser.access",
    "git.write",
    "agents.create",
    "agents.delete",
    "plugins.load",
}


class PermissionService:
    def has(self, agent: Agent, permission: str) -> bool:
        return bool(agent.permissions.get(permission, False))

    def requires_confirmation(self, permission: str) -> bool:
        return permission in DANGEROUS_PERMISSIONS
