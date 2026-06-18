"""Persistent conversation storage.

Each conversation is one JSON file under the platform's standard per-user data
directory (resolved via Qt's QStandardPaths) so chats survive across sessions
and can be reopened to continue:
  - Linux:   ~/.local/share/perplexity-council/conversations/<id>.json
  - Windows: %LOCALAPPDATA%\\perplexity-council\\conversations\\<id>.json
  - macOS:   ~/Library/Application Support/perplexity-council/conversations/<id>.json
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QStandardPaths

# Folder name kept stable (matches config.APP_DIR_NAME) so existing installs
# keep their saved conversations after the move to QStandardPaths.
APP_DIR_NAME = "perplexity-council"


def data_dir() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.GenericDataLocation)
    return Path(base) / APP_DIR_NAME / "conversations"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class Conversation:
    id: str
    title: str = "New chat"
    created: str = ""
    updated: str = ""
    messages: list = field(default_factory=list)  # [{"role", "content"}]

    @staticmethod
    def new() -> "Conversation":
        t = _now()
        return Conversation(id=uuid.uuid4().hex, title="New chat", created=t, updated=t)

    @property
    def path(self) -> Path:
        return data_dir() / f"{self.id}.json"


def save(conv: Conversation) -> None:
    data_dir().mkdir(parents=True, exist_ok=True)
    conv.updated = _now()
    conv.path.write_text(json.dumps(asdict(conv), indent=2))


def load(cid: str) -> Conversation:
    data = json.loads((data_dir() / f"{cid}.json").read_text())
    return Conversation(
        id=data["id"],
        title=data.get("title", "Chat"),
        created=data.get("created", ""),
        updated=data.get("updated", ""),
        messages=data.get("messages", []),
    )


def delete(cid: str) -> None:
    p = data_dir() / f"{cid}.json"
    if p.exists():
        p.unlink()


def list_all() -> list[dict]:
    """Return conversation metadata dicts, newest first."""
    d = data_dir()
    d.mkdir(parents=True, exist_ok=True)
    out = []
    for p in d.glob("*.json"):
        try:
            data = json.loads(p.read_text())
            out.append({
                "id": data["id"],
                "title": data.get("title", "Chat"),
                "updated": data.get("updated", ""),
                "count": len(data.get("messages", [])),
            })
        except (json.JSONDecodeError, OSError, KeyError):
            continue
    out.sort(key=lambda d: d.get("updated", ""), reverse=True)
    return out


def title_from(text: str, limit: int = 48) -> str:
    text = " ".join(text.split())
    return text[: limit - 1] + "…" if len(text) > limit else text
