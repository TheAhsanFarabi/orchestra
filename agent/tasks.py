"""
Orchestra TaskList.

Persisted at ~/.orchestra/tasks.json. Both the agent (via tool functions
tasks_add / tasks_done / tasks_list) and the user (via /tasks slash commands)
can manage it.

Status lifecycle:
    pending  →  in_progress  →  done
                             →  failed
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Literal

from .config import CONFIG_DIR, Config, SESSION_DIR

def get_tasks_file() -> Path:
    cfg = Config.load()
    if cfg.active_session:
        SESSION_DIR.mkdir(parents=True, exist_ok=True)
        return SESSION_DIR / f"{cfg.active_session}_tasks.json"
    return CONFIG_DIR / "tasks.json"

# ── Display constants ─────────────────────────────────────────────────────────

STATUS_ICON: dict[str, str] = {
    "pending":     "○",
    "in_progress": "◉",
    "done":        "✓",
    "failed":      "✗",
}

STATUS_STYLE: dict[str, str] = {
    "pending":     "dim",
    "in_progress": "cyan",
    "done":        "green",
    "failed":      "red",
}


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class TaskItem:
    id:           int
    text:         str
    status:       Literal["pending", "in_progress", "done", "failed"] = "pending"
    created_at:   float = field(default_factory=time.time)
    completed_at: float | None = None


@dataclass
class TaskList:
    goal:  str            = ""
    items: list[TaskItem] = field(default_factory=list)

    # ── Mutation ──────────────────────────────────────────────────────────

    def add(self, text: str) -> TaskItem:
        next_id = (max(i.id for i in self.items) + 1) if self.items else 1
        item    = TaskItem(id=next_id, text=text)
        self.items.append(item)
        return item

    def _get(self, item_id: int) -> TaskItem | None:
        """Find item by its unique id."""
        for item in self.items:
            if item.id == item_id:
                return item
        return None

    def start(self, item_id: int) -> bool:
        item = self._get(item_id)
        if item and item.status == "pending":
            item.status = "in_progress"
            return True
        return False

    def complete(self, item_id: int) -> bool:
        item = self._get(item_id)
        if item and item.status in ("pending", "in_progress"):
            item.status       = "done"
            item.completed_at = time.time()
            return True
        return False

    def fail(self, item_id: int) -> bool:
        item = self._get(item_id)
        if item and item.status in ("pending", "in_progress"):
            item.status       = "failed"
            item.completed_at = time.time()
            return True
        return False

    def clear_done(self) -> int:
        before     = len(self.items)
        self.items = [i for i in self.items if i.status not in ("done", "failed")]
        return before - len(self.items)

    def clear_all(self) -> None:
        self.items.clear()

    # ── Persistence ───────────────────────────────────────────────────────

    def save(self) -> None:
        p = get_tasks_file()
        p.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "goal":  self.goal,
            "items": [asdict(i) for i in self.items],
        }
        p.write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls) -> "TaskList":
        p = get_tasks_file()
        if not p.exists():
            return cls()
        try:
            data  = json.loads(p.read_text())
            items = [TaskItem(**i) for i in data.get("items", [])]
            return cls(goal=data.get("goal", ""), items=items)
        except Exception:
            return cls()

    # ── Plain-text summary (used by tasks_list tool) ───────────────────────

    def summary(self) -> str:
        if not self.items:
            return "(no tasks)"
        lines: list[str] = []
        if self.goal:
            lines.append(f"Goal: {self.goal}\n")
        for item in self.items:
            icon = STATUS_ICON[item.status]
            lines.append(f"  {item.id}. {icon} {item.text}  [{item.status}]")
        done    = sum(1 for x in self.items if x.status == "done")
        pending = sum(1 for x in self.items if x.status == "pending")
        lines.append(f"\n  {done} done, {pending} pending, {len(self.items)} total")
        return "\n".join(lines)


# ── Agent-facing tool functions ───────────────────────────────────────────────

def tasks_add(item: str) -> str:
    """Add a new task to the tasks list.

    Args:
        item: Description of the task to add.

    Returns:
        Confirmation with the assigned task number.
    """
    t        = TaskList.load()
    new_item = t.add(item)
    t.save()
    return f"Added task #{new_item.id}: {item}"


def tasks_done(task_id: int) -> str:
    """Mark a task as completed by its ID.

    Args:
        task_id: The ID of the task shown in /tasks.

    Returns:
        Confirmation or error message.
    """
    t = TaskList.load()
    item = t._get(task_id)
    if not item:
        return f"Error: task #{task_id} does not exist."
    if item.status == "done":
        return f"Task #{task_id} is already marked as done."
    if t.complete(task_id):
        t.save()
        return f"Marked #{task_id} as done: {item.text}"
    return f"Error: could not complete task #{task_id}."


def tasks_list() -> str:
    """Return the current tasks list as plain text.

    Returns:
        Numbered list of tasks with status icons, or a message if empty.
    """
    return TaskList.load().summary()
