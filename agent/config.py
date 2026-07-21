"""
Orchestra — theme definitions and persistent configuration.

Config is stored at ~/.orchestra/config.json and is loaded at startup.
Themes define all Rich + prompt_toolkit styling tokens so the entire TUI
can be re-skinned by swapping a single Theme object.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────

CONFIG_DIR   = Path.home() / ".orchestra"
CONFIG_FILE  = CONFIG_DIR / "config.json"
HISTORY_FILE = CONFIG_DIR / "history"
SESSION_DIR  = CONFIG_DIR / "sessions"
VERSION      = "1.0.0"


# ── Theme dataclass ───────────────────────────────────────────────────────────

@dataclass
class Theme:
    """All styling tokens for one visual theme."""

    name: str
    emoji: str
    description: str

    # ── Rich markup styles ────────────────────────────────────────────────────
    banner: str        # logo text             e.g. "bold #7c83e0"
    border: str        # generic panel border  e.g. "bright_blue"
    agent_border: str  # agent-response panel  e.g. "cyan"
    accent: str        # highlights / labels   e.g. "bold #89b4fa"
    info: str          # ℹ messages
    warn: str          # ⚠ messages
    error: str         # ✗ messages
    tool: str          # tool-call lines       e.g. "dim cyan"
    rule: str          # horizontal rules

    # ── prompt_toolkit hex colours (no leading #) ─────────────────────────────
    pt_main: str       # prompt label + chevron  e.g. "89b4fa"
    pt_model: str      # model name chip         e.g. "cba6f7"
    pt_dim: str        # ghost suggestions       e.g. "585b70"


# ── Theme catalogue ───────────────────────────────────────────────────────────

THEMES: dict[str, Theme] = {
    "mint": Theme(
        name="Mint", emoji="🌿",
        description="Mint green — simple and clean",
        banner      = "bold #4ade80",
        border      = "#4ade80",
        agent_border= "bold #4ade80",
        accent      = "bold #4ade80",
        info        = "bold #4ade80",
        warn        = "bold yellow",
        error       = "bold red",
        tool        = "dim #4ade80",
        rule        = "dim #4ade80",
        pt_main     = "4ade80",
        pt_model    = "4ade80",
        pt_dim      = "4ade80",
    ),
    "ocean": Theme(
        name="Ocean", emoji="🌊",
        description="Deep blue — calm and focused",
        banner      = "bold #60a5fa",
        border      = "#3b82f6",
        agent_border= "bold #60a5fa",
        accent      = "bold #93c5fd",
        info        = "bold #60a5fa",
        warn        = "bold #fbbf24",
        error       = "bold #ef4444",
        tool        = "dim #60a5fa",
        rule        = "dim #3b82f6",
        pt_main     = "60a5fa",
        pt_model    = "93c5fd",
        pt_dim      = "475569",
    ),
    "ember": Theme(
        name="Ember", emoji="🔥",
        description="Warm amber — bold and energetic",
        banner      = "bold #f59e0b",
        border      = "#d97706",
        agent_border= "bold #fbbf24",
        accent      = "bold #fbbf24",
        info        = "bold #f59e0b",
        warn        = "bold #fb923c",
        error       = "bold #ef4444",
        tool        = "dim #f59e0b",
        rule        = "dim #d97706",
        pt_main     = "f59e0b",
        pt_model    = "fbbf24",
        pt_dim      = "78716c",
    ),
    "lavender": Theme(
        name="Lavender", emoji="💜",
        description="Soft purple — elegant and serene",
        banner      = "bold #a78bfa",
        border      = "#8b5cf6",
        agent_border= "bold #a78bfa",
        accent      = "bold #c4b5fd",
        info        = "bold #a78bfa",
        warn        = "bold #fbbf24",
        error       = "bold #ef4444",
        tool        = "dim #a78bfa",
        rule        = "dim #8b5cf6",
        pt_main     = "a78bfa",
        pt_model    = "c4b5fd",
        pt_dim      = "6b7280",
    ),
    "rose": Theme(
        name="Rose", emoji="🌹",
        description="Soft pink — warm and inviting",
        banner      = "bold #fb7185",
        border      = "#e11d48",
        agent_border= "bold #fb7185",
        accent      = "bold #fda4af",
        info        = "bold #fb7185",
        warn        = "bold #fbbf24",
        error       = "bold #ef4444",
        tool        = "dim #fb7185",
        rule        = "dim #e11d48",
        pt_main     = "fb7185",
        pt_model    = "fda4af",
        pt_dim      = "6b7280",
    ),
    "frost": Theme(
        name="Frost", emoji="❄️",
        description="Ice white on dark — crisp and minimal",
        banner      = "bold #e2e8f0",
        border      = "#94a3b8",
        agent_border= "bold #cbd5e1",
        accent      = "bold #f1f5f9",
        info        = "bold #e2e8f0",
        warn        = "bold #fbbf24",
        error       = "bold #ef4444",
        tool        = "dim #94a3b8",
        rule        = "dim #64748b",
        pt_main     = "e2e8f0",
        pt_model    = "cbd5e1",
        pt_dim      = "475569",
    ),
}

DEFAULT_THEME = "mint"
THEME_KEYS    = list(THEMES.keys())


# ── Persistent config ─────────────────────────────────────────────────────────

@dataclass
class Config:
    theme:         str  = DEFAULT_THEME
    welcomed:      bool = False
    model:         str  = "qwen2.5:1.5b"
    context_limit: int  = 32_768
    active_session: str | None = None

    # ── persistence ───────────────────────────────────────────────────────────

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls) -> "Config":
        if not CONFIG_FILE.exists():
            return cls()
        try:
            data  = json.loads(CONFIG_FILE.read_text())
            valid = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
            return cls(**valid)
        except Exception:
            return cls()

    # ── helpers ───────────────────────────────────────────────────────────────

    @property
    def current_theme(self) -> Theme:
        return THEMES.get(self.theme, THEMES[DEFAULT_THEME])
