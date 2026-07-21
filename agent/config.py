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
VERSION      = "0.2.0"


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
    )
}

DEFAULT_THEME = "mint"
THEME_KEYS    = list(THEMES.keys())


# ── Persistent config ─────────────────────────────────────────────────────────

@dataclass
class Config:
    theme:         str  = DEFAULT_THEME
    welcomed:      bool = False
    model:         str  = "qwen2.5:latest"
    context_limit: int  = 32_768

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
