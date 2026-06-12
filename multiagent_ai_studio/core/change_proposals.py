from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path

from .logging_service import LogService


@dataclass
class ChangeProposal:
    title: str
    description: str
    target_file: Path
    proposed_content: str

    def diff(self) -> str:
        old = self.target_file.read_text(encoding="utf-8").splitlines() if self.target_file.exists() else []
        new = self.proposed_content.splitlines()
        return "\n".join(difflib.unified_diff(old, new, fromfile=str(self.target_file), tofile=str(self.target_file)))


class ChangeProposalService:
    def __init__(self, proposal_dir: Path, logs: LogService) -> None:
        self.proposal_dir = proposal_dir
        self.logs = logs
        self.proposal_dir.mkdir(parents=True, exist_ok=True)

    def save(self, proposal: ChangeProposal) -> Path:
        safe = "".join(ch if ch.isalnum() else "_" for ch in proposal.title)[:80]
        path = self.proposal_dir / f"{safe}.diff"
        path.write_text(proposal.diff(), encoding="utf-8")
        self.logs.log("proposal.create", f"Создано предложение изменения ядра: {proposal.title}")
        return path
