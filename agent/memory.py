"""
Orchestra Memory Layer.

Wraps the flat list[dict] that run_agent() consumes/produces with
per-message metadata, token estimation, and Rich display helpers.

Integration pattern (in the TUI loop):
    # Before calling run_agent:
    history = state["memory"].to_list() or None (if empty)

    # After calling run_agent:
    state["memory"] = MemoryLayer.from_list(new_msgs)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

# Rough heuristic: English prose ≈ 4 chars per token.
# Good enough for an in-TUI estimate; no tokenizer required.
CHARS_PER_TOKEN: int = 4


# ── Turn ──────────────────────────────────────────────────────────────────────

@dataclass
class Turn:
    """A single message in the conversation, with display metadata."""

    role:       str
    content:    str
    timestamp:  float       = field(default_factory=time.time)
    tool_name:  str | None  = None   # populated for assistant tool-calls

    # ── Properties ────────────────────────────────────────────────────────

    @property
    def estimated_tokens(self) -> int:
        return max(1, len(self.content) // CHARS_PER_TOKEN)

    def preview(self, width: int = 65) -> str:
        """Single-line truncated preview of content."""
        text = self.content.strip().replace("\n", " ")
        return (text[:width] + "…") if len(text) > width else text

    # ── Serialisation ─────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Minimal dict compatible with Ollama's message format."""
        return {"role": self.role, "content": self.content}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Turn":
        role = d.get("role", "unknown")

        # Content may be absent (pure tool-call message) or non-string.
        content = d.get("content") or ""
        if not isinstance(content, str):
            content = str(content)

        # Try to extract the first tool name from tool_calls.
        tool_name: str | None = None
        raw_calls = d.get("tool_calls")
        if raw_calls:
            try:
                tc = raw_calls[0]
                fn = (tc.get("function", tc) if isinstance(tc, dict) else tc.function)
                tool_name = (fn.get("name") if isinstance(fn, dict) else fn.name)
            except Exception:
                pass

        return cls(role=role, content=content, tool_name=tool_name)


# ── MemoryLayer ───────────────────────────────────────────────────────────────

@dataclass
class MemoryLayer:
    """
    Persistent, queryable conversation context for Orchestra.

    Keeps a Turn-level record of every message (system prompt, user turns,
    assistant replies, tool calls, and tool results) and exposes aggregated
    stats for the /memory context-window display.

    Conversion to/from a plain list[dict] keeps it compatible with the
    existing run_agent() interface without touching loop.py.
    """

    turns: list[Turn] = field(default_factory=list)

    # ── Mutation ──────────────────────────────────────────────────────────

    def push(self, msg: dict[str, Any]) -> None:
        """Append one raw message dict (from the agent loop)."""
        self.turns.append(Turn.from_dict(msg))

    def reset(self) -> None:
        """Wipe everything. The next run_agent() call will re-add the system prompt."""
        self.turns.clear()

    # ── Compatibility with run_agent() ────────────────────────────────────

    def to_list(self) -> list[dict[str, Any]]:
        """Export as a plain list[dict] for run_agent(history=…)."""
        return [t.to_dict() for t in self.turns]

    @classmethod
    def from_list(cls, msgs: list[dict[str, Any]]) -> "MemoryLayer":
        """Import from the list[dict] returned by run_agent()."""
        obj = cls()
        for m in msgs:
            obj.turns.append(Turn.from_dict(m))
        return obj

    # ── Stats ─────────────────────────────────────────────────────────────

    @property
    def is_empty(self) -> bool:
        return len(self.turns) == 0

    @property
    def total_tokens(self) -> int:
        """Estimated total tokens across all messages."""
        return sum(t.estimated_tokens for t in self.turns)

    @property
    def user_turns(self) -> int:
        return sum(1 for t in self.turns if t.role == "user")

    @property
    def tool_calls(self) -> int:
        """Number of assistant messages that contained tool calls."""
        return sum(1 for t in self.turns if t.tool_name is not None)

    @property
    def message_count(self) -> int:
        return len(self.turns)

    def render_cubes(self, theme: Any, context_limit: int = 32_768) -> Any:
        """
        Render the conversation as a grid of cubes (Rich Columns of Panels)
        plus a context-window usage bar.

        Returns a Rich Group renderable.
        """
        from rich.columns import Columns
        from rich.console import Group
        from rich.panel import Panel
        from rich.text import Text
        from rich import box

        ROLE_LABEL: dict[str, str] = {
            "system":    "SYSTEM",
            "user":      "YOU",
            "assistant": "AGENT",
            "tool":      "TOOL",
        }

        MAX_CUBES = 20
        visible   = self.turns[:MAX_CUBES]
        overflow  = len(self.turns) - MAX_CUBES

        cubes = []
        for i, turn in enumerate(visible, 1):
            border = {
                "system":    "dim",
                "user":      theme.border,
                "assistant": theme.agent_border,
                "tool":      "cyan",
            }.get(turn.role, "dim")

            label   = ROLE_LABEL.get(turn.role, turn.role.upper()[:6])
            preview = (
                f"\u2699 {turn.tool_name[:7]}…" if turn.tool_name
                else turn.preview(9)
            )

            body = Text.assemble(
                ("\n",          ""),
                (f" ~{turn.estimated_tokens} tok\n", "dim"),
                (f" {preview}\n",                    "dim"),
                (f" #{i}",                            "dim"),
            )
            cubes.append(
                Panel(
                    body,
                    title         = f"[bold]{label}[/]",
                    border_style  = border,
                    box           = box.SQUARE,
                    width         = 14,
                    padding       = (0, 0),
                )
            )

        # Context usage bar
        used_pct  = min(self.total_tokens / max(context_limit, 1), 1.0)
        bar_width = 32
        filled    = int(bar_width * used_pct)
        bar       = "\u2588" * filled + "\u2591" * (bar_width - filled)
        pct_str   = f"{used_pct * 100:.0f}%"

        context_bar = Text.assemble(
            ("  Context  ", "dim"),
            (bar,           theme.accent),
            (f"  ~{self.total_tokens:,} / {context_limit:,} tok  ({pct_str})", "dim"),
        )

        overflow_text = (
            Text(f"  … {overflow} more messages not shown  (/reset to clear)",
                 style="dim italic")
            if overflow > 0
            else Text("")
        )

        return Group(
            Columns(cubes, expand=False),
            overflow_text,
            Text(""),
            context_bar,
        )
