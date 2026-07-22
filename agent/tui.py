"""
Orchestra TUI — rich, interactive terminal interface.

First run:
  A full-screen welcome intro walks the user through what Orchestra is
  and lets them pick a theme. Saved to ~/.orchestra/config.json;
  subsequent launches skip straight to the main interface.

Slash commands:
  /help          Show all commands
  /model         Switch Ollama model
  /fast          Switch to fastest CPU model
  /mode          Cycle through Action, Plan, and Chat modes
  /add           Inject file into context
  /session       Manage chat sessions
  /tasks          Manage the tasks list
  /goal          Show or set the active goal
  /skills        Show ~/.orchestra/SKILL.md
  /clear         Clear conversation
  /tools         List available tools
  /context       Show context window usage
  /settings      View active configuration
  /about         View information about Orchestra
  /exit          Quit Orchestra
"""

from __future__ import annotations

import math
import time
import random
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pyfiglet

try:
    import os
    os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "hide"
    import pygame
    pygame.mixer.init()
    _pygame_available = True
except Exception:
    _pygame_available = False

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.styles import Style as PTStyle
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.application import get_app
import threading

_anim_thread_started = False
def _start_anim_thread():
    global _anim_thread_started
    if _anim_thread_started: return
    _anim_thread_started = True
    def run():
        while True:
            time.sleep(0.2)
            if _pygame_available and pygame.mixer.music.get_busy():
                try:
                    app = get_app()
                    if app and app.is_running:
                        app.invalidate()
                except Exception:
                    pass
    threading.Thread(target=run, daemon=True).start()

from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from rich.rule import Rule
from rich.live import Live
from rich.spinner import Spinner
from rich.align import Align
from rich.table import Table
from rich.prompt import Prompt
from rich import box

from .loop import run_agent
from .tools import TOOL_REGISTRY
from .memory import MemoryLayer
from .permissions import PermissionRequest, permission_manager
from .skills import skills_manager
from .tasks import TaskList, STATUS_ICON, STATUS_STYLE
from .config import (
    Config, Theme, THEMES, THEME_KEYS, DEFAULT_THEME,
    HISTORY_FILE, SESSION_DIR, VERSION,
)
from .prompts import init_prompts, list_prompts, get_prompt

# ── Prompt cycle counter (for tips) ──────────────────────────────────────────

_prompt_cycle = 0

TIPS = [
    "Shift+Tab toggles lofi music",
    "Use /mode to switch between Action, Plan, and Chat",
    "Use /session new to start a fresh conversation",
    "Prefix commands with ! to run them in the terminal",
    "Use /fast for quick CPU-only responses",
    "Use /add &lt;file&gt; to inject files into context",
    "Use /theme to change the visual theme",
    "Use /goal set &lt;text&gt; to set a persistent goal",
]

# ── Shared console ────────────────────────────────────────────────────────────

console = Console()

# ── Module-level Live handle (so _tui_confirm can pause/resume it) ────────────

_active_live: Live | None = None

# ── Slash-command registry ────────────────────────────────────────────────────

SLASH_COMMANDS: dict[str, str] = {
    "/help":         "Show this help",
    "/model":        "Switch model  —  /model <name>",
    "/fast":         "Instantly switch to the fastest CPU-optimized model",
    "/mode":         "Cycle between Action, Plan, and Chat modes",
    "/theme":        "Change the visual theme  —  /theme [name]",
    "/prompt":       "Load a prompt template  —  /prompt [name]",
    "/add":          "Inject a file's content into AI context  —  /add <file>",
    "/session":      "Manage chat sessions  —  /session [list|new|delete|<hash>]",
    "/artifact":     "Manage AI-generated artifacts  —  /artifact [list|view|add]",
    "/tasks":         "Manage your tasks list",
    "/goal":         "Manage your overarching goal",
    "/clear":        "Clear conversation",
    "/tools":        "List available tools",
    "/context":      "Show context usage map",
    "/settings":     "View current configuration settings",
    "/about":        "Show information about Orchestra",
    "/exit":         "Quit Orchestra",
}


# ── Permission panel (TUI override for permission_manager.confirm_fn) ─────────

def _tui_confirm(req: PermissionRequest) -> bool:
    """Show a styled permission panel and read y/N from the user."""
    global _active_live
    if _active_live:
        _active_live.stop()

    border = "red" if req.dangerous else "yellow"
    icon   = (
        "[bold red]!! DANGEROUS — Approval Required !!  [/]"
        if req.dangerous
        else "[bold yellow]  Permission Required  [/]"
    )

    # Colour the preview diff lines
    preview_text = Text()
    for line in req.preview.splitlines()[:25]:
        if line.startswith("+"):
            preview_text.append(line + "\n", style="green")
        elif line.startswith("-"):
            preview_text.append(line + "\n", style="red")
        else:
            preview_text.append(line + "\n", style="dim")

    body = Group(
        Text(""),
        Text.assemble(
            ("  Tool    ", "dim"), (req.tool_name + "\n", "bold"),
            ("  Action  ", "dim"), (req.action    + "\n", ""),
            ("  Target  ", "dim"), (req.target    + "\n", "dim"),
        ),
        Rule(style="dim"),
        Text(""),
        preview_text,
        Text(""),
    )
    console.print(Panel(body, title=icon, border_style=border, box=box.ROUNDED))

    try:
        answer = Prompt.ask(
            "  Allow this action?",
            choices=["y", "n"],
            default="n",
            console=console,
        )
    except (EOFError, KeyboardInterrupt):
        answer = "n"

    console.print()

    if _active_live:
        _active_live.start()

    return answer == "y"


# ── prompt_toolkit session ────────────────────────────────────────────────────

def _make_session(theme: Theme, state: dict | None = None) -> PromptSession:
    _start_anim_thread()
    completer = WordCompleter(list(SLASH_COMMANDS.keys()), sentence=True)
    pt_style  = PTStyle.from_dict({
        "completion-menu.completion":
            f"bg:#1e1e2e #{theme.pt_model}",
        "completion-menu.completion.current":
            f"bg:#{theme.pt_main} #1e1e2e bold",
        "auto-suggestion":
            f"#{theme.pt_dim} italic",
        "bottom-toolbar":
            f"bg:#{theme.pt_main} #000000",
    })
    
    def get_toolbar():
        if not state: return None
        return _get_bottom_toolbar(state)

    bindings = KeyBindings()

    @bindings.add('s-tab')
    def toggle_music(event):
        if not _pygame_available: return
        if pygame.mixer.music.get_busy():
            pygame.mixer.music.stop()
        else:
            music_file = Path("assets/lofi.mp3")
            if music_file.exists():
                try:
                    pygame.mixer.music.load(str(music_file))
                    pygame.mixer.music.play(loops=-1)
                except Exception:
                    pass

    return PromptSession(
        history             = FileHistory(str(HISTORY_FILE)),
        auto_suggest        = AutoSuggestFromHistory(),
        completer           = completer,
        style               = pt_style,
        complete_while_typing = True,
        bottom_toolbar      = get_toolbar,
        key_bindings        = bindings,
    )


def _gradient_rule(theme: Theme, width: int) -> str:
    """Generate a gradient horizontal rule that glows from center."""
    r = int(theme.pt_main[:2], 16)
    g = int(theme.pt_main[2:4], 16)
    b = int(theme.pt_main[4:6], 16)
    chars = []
    half = width // 2
    for i in range(width):
        dist = abs(i - half) / max(half, 1)
        factor = max(0.2, 1.0 - dist * 0.8)
        cr, cg, cb = int(r * factor), int(g * factor), int(b * factor)
        chars.append(f"\033[38;2;{cr};{cg};{cb}m─\033[0m")
    return "".join(chars)


def _prompt_html(model: str, theme: Theme) -> HTML:
    global _prompt_cycle
    _prompt_cycle += 1
    c = f"#{theme.pt_main}"
    w = shutil.get_terminal_size().columns

    # Show a tip every 3rd prompt
    if _prompt_cycle % 3 == 0:
        tip = random.choice(TIPS)
        label = f" 💡 {tip} "
        pad = max(0, w - len(label)) // 2
        top = "─" * pad + label + "─" * (w - pad - len(label))
        top_html = f"<style fg='{c}'>{top}</style>"
    else:
        top_html = f"<style fg='{c}'>{'─' * w}</style>"

    return HTML(
        f"{top_html}\n"
        f"<b><style fg='{c}'>&gt;</style></b> "
    )


def _get_bottom_toolbar(state: dict) -> HTML:
    model = state["cfg"].model
    mood = state["mood"].capitalize()
    
    try:
        tasks = TaskList.load()
        pending = sum(1 for i in tasks.items if i.status == "pending")
        goal_status = "Active" if tasks.goal else "None"
    except Exception:
        pending = 0
        goal_status = "None"
        
    theme = state["cfg"].current_theme
    c = f"#{theme.pt_main}"
    d = f"#{theme.pt_dim}"
    
    music_status = ""
    if _pygame_available:
        if pygame.mixer.music.get_busy():
            t = time.time()
            bars = "".join(
                "▁▂▃▄▅▆▇█"[int((math.sin(t * 3 + i * 1.2) + 1) * 3.5)]
                for i in range(5)
            )
            music_status = f"♫ Playing {bars}"
        else:
            music_status = f"Paused ▄▃▂ "
    
    return HTML(
        f" Model: <b>{model}</b>"
        f"  |  Mode: <b>{mood}</b>"
        f"  |  Tasks: <b>{pending}</b>"
        f"  |  Goal: <b>{goal_status}</b>"
        f"  |  Theme: <b>{theme.emoji} {theme.name}</b>"
        f"  |  {music_status}"
    )


# ── Banner ────────────────────────────────────────────────────────────────────

def _make_logo(terminal_width: int = 100) -> str:
    font = "small_slant"
    try:
        return pyfiglet.figlet_format("ORCHESTRA", font=font).rstrip()
    except Exception:
        return "  O R C H E S T R A"

def _render_icon(theme: Theme | None = None, path: str = "assets/icon.png", width: int = 16, height: int = 8) -> Text:
    try:
        from PIL import Image
        img = Image.open(path).resize((width, height * 2), Image.Resampling.LANCZOS).convert("RGBA")
        pixels = img.load()
        text = Text()
        
        if theme:
            tr = int(theme.pt_main[:2], 16)
            tg = int(theme.pt_main[2:4], 16)
            tb = int(theme.pt_main[4:6], 16)
            
        for y in range(0, height * 2, 2):
            for x in range(width):
                r1, g1, b1, a1 = pixels[x, y]
                r2, g2, b2, a2 = pixels[x, y + 1]
                
                if theme:
                    brightness1 = (r1 + g1 + b1) / (3 * 255.0)
                    r1, g1, b1 = int(tr * brightness1), int(tg * brightness1), int(tb * brightness1)
                    brightness2 = (r2 + g2 + b2) / (3 * 255.0)
                    r2, g2, b2 = int(tr * brightness2), int(tg * brightness2), int(tb * brightness2)
                
                c1 = f"rgb({r1},{g1},{b1})" if a1 > 127 else "default"
                c2 = f"rgb({r2},{g2},{b2})" if a2 > 127 else "default"
                
                if c1 == "default" and c2 == "default": text.append(" ", style="")
                elif c1 == "default": text.append("▄", style=c2)
                elif c2 == "default": text.append("▀", style=c1)
                else: text.append("▀", style=f"{c1} on {c2}")
            if y < (height * 2) - 2: text.append("\n")
        return text
    except Exception:
        return Text("[ICON ERROR]", style="red")

def print_banner(theme: Theme, model: str) -> None:
    import random
    from rich.panel import Panel
    from rich.align import Align
    from rich.console import Group

    logo_text = Text(_make_logo(console.width), style=f"bold #{theme.pt_main}")
    icon = _render_icon(theme=theme)

    quotes = [
        "“The best way to predict the future is to invent it.” – Alan Kay",
        "“Any sufficiently advanced technology is indistinguishable from magic.” – Arthur C. Clarke",
        "“Quality is not an act, it is a habit.” – Aristotle",
        "“First, solve the problem. Then, write the code.” – John Johnson",
        "“Talk is cheap. Show me the code.” – Linus Torvalds"
    ]
    quote_text = Text('\n"' + random.choice(quotes).strip('“”') + '"\n', style=f"italic #{theme.pt_main}", justify="center")

    group = Group(
        Align.center(icon),
        Align.center(logo_text),
        quote_text
    )

    panel = Panel(
        group,
        border_style=f"#{theme.pt_main}", 
        padding=(0, 4),
        title=f"[bold #{theme.pt_main}]Orchestra[/]",
        subtitle=f"[dim #{theme.pt_main}]local AI · v{VERSION}[/]"
    )

    console.print()
    console.print(panel)
    console.print()

# ── Welcome screen ────────────────────────────────────────────────────────────

def show_welcome(cfg: Config) -> Config:
    console.clear()
    print_banner(cfg.current_theme, cfg.model)
    
    msg = "Thanks for choosing Orchestra! Your agentic journey begins now..."
    for i in range(len(msg) + 1):
        console.print(f"  [bold {cfg.current_theme.accent}]{msg[:i]}[/]", end="\r")
        import time
        time.sleep(0.03)
    print("\n")
    
    cfg.welcomed = True
    cfg.save()
    
    return cfg


# ── Response rendering ────────────────────────────────────────────────────────

def print_response(text: str, theme: Theme) -> None:
    try:
        body = Markdown(text, code_theme="monokai")
    except Exception:
        body = Text(text)  # type: ignore[assignment]
    console.print(
        Panel(body, title=f"[{theme.accent}]orchestra[/]",
              border_style=theme.agent_border, box=box.ROUNDED, padding=(0, 1))
    )


def _info(msg: str, theme: Theme)  -> None:
    console.print(f"  [{theme.info}]i  {msg}[/]")

def _warn(msg: str, theme: Theme)  -> None:
    console.print(f"  [{theme.warn}]!  {msg}[/]")

def _error(msg: str, theme: Theme) -> None:
    console.print(f"  [{theme.error}]x  {msg}[/]")


# ── /help ─────────────────────────────────────────────────────────────────────

def print_help(theme: Theme) -> None:
    tbl = Table(box=box.SIMPLE_HEAD, border_style="dim", header_style=theme.accent)
    tbl.add_column("Command", style="bold yellow", no_wrap=True)
    tbl.add_column("Description")
    for cmd, desc in SLASH_COMMANDS.items():
        tbl.add_row(cmd, desc)
    console.print(
        Panel(tbl, title=f"[{theme.accent}]Slash Commands[/]",
              border_style=theme.border, box=box.ROUNDED)
    )


# ── /tools ───────────────────────────────────────────────────────────────────

def print_tools(theme: Theme) -> None:
    tbl = Table(box=box.SIMPLE_HEAD, border_style="dim", header_style=theme.accent)
    tbl.add_column("Tool", style="bold green", no_wrap=True)
    tbl.add_column("Description")
    for name, fn in TOOL_REGISTRY.items():
        doc = (fn.__doc__ or "").strip().splitlines()[0]
        tbl.add_row(name, doc)
    body = Group(
        tbl,
        Text(""),
        Text("  /tools  (shows available tools)", style="dim")
    )
    console.print(
        Panel(body, title=f"[{theme.accent}]Available Tools[/]",
              border_style=theme.border, box=box.ROUNDED)
    )


# ── /memory ───────────────────────────────────────────────────────────────────

def print_memory(memory: MemoryLayer, theme: Theme, context_limit: int = 32_768) -> None:
    if memory.is_empty:
        console.print(
            Panel(
                Text("  No conversation history yet.", style="dim"),
                title=f"[{theme.accent}]Context Window[/]",
                border_style=theme.border, box=box.ROUNDED,
            )
        )
        return

    stats = Text.assemble(
        "  ",
        (str(memory.message_count), theme.accent), (" messages",  "dim"),
        ("  ·  ", "dim"),
        (str(memory.user_turns),    theme.accent), (" user turns", "dim"),
        ("  ·  ", "dim"),
        (str(memory.tool_calls),    theme.accent), (" tool calls", "dim"),
        ("  ·  ", "dim"),
        (f"~{memory.total_tokens:,}", theme.accent), (" est. tokens", "dim"),
    )

    hint = Text(
        "  /context clear  (wipes the context window)",
        style="dim",
    )

    console.print(
        Panel(
            Group(
                Text(""),
                stats,
                Text(""),
                Rule(style=f"dim {theme.border}"),
                Text(""),
                memory.render_cubes(theme, context_limit),
                Rule(style=f"dim {theme.border}"),
                Text(""),
                hint,
                Text(""),
            ),
            title=f"[{theme.accent}]Context Window[/]",
            border_style=theme.border,
            box=box.ROUNDED,
        )
    )


# ── /tasks ─────────────────────────────────────────────────────────────────────

def _progress_bar(done: int, total: int, width: int = 20, theme: Theme | None = None) -> Text:
    """Render a compact progress bar."""
    if total == 0:
        return Text("")
    filled = int((done / total) * width)
    pct = int((done / total) * 100)
    bar_style = "green" if pct == 100 else (theme.accent if theme else "cyan")
    bar = Text()
    bar.append("  ")
    bar.append("█" * filled, style=bar_style)
    bar.append("░" * (width - filled), style="dim")
    bar.append(f" {pct}% complete ({done}/{total} tasks done)", style="dim")
    return bar


def print_tasks(tasks: TaskList, theme: Theme) -> None:

    tbl = Table(
        box=box.SIMPLE_HEAD, border_style="dim",
        header_style=theme.accent, show_header=bool(tasks.items),
    )
    tbl.add_column("#",      style="dim", width=4,  no_wrap=True)
    tbl.add_column("Status", width=14,              no_wrap=True)
    tbl.add_column("Task")

    for item in tasks.items:
        icon   = STATUS_ICON[item.status]
        istyle = STATUS_STYLE[item.status]
        tbl.add_row(
            str(item.id),
            Text(f"{icon} {item.status}", style=istyle),
            item.text,
        )

    done = sum(1 for x in tasks.items if x.status == "done")
    ip   = sum(1 for x in tasks.items if x.status == "in_progress")
    pend = sum(1 for x in tasks.items if x.status == "pending")
    total = len(tasks.items)

    footer = Text.assemble(
        (f"  {done} done",         "green"),
        ("  ·  ",                   "dim"),
        (f"{ip} in progress",       "cyan"),
        ("  ·  ",                   "dim"),
        (f"{pend} pending",         "dim"),
    ) if tasks.items else Text("")

    progress = _progress_bar(done, total, theme=theme) if tasks.items else Text("")

    body = Group(
        Text(""),
        tbl if tasks.items
            else Text("  (no tasks yet — use /tasks add <text>)", style="dim"),
        Text(""),
        progress,
        footer,
        Text(""),
        Text("  /tasks add <text>  ·  /tasks done <n>  ·  /tasks clear", style="dim"),
        Text(""),
    )
    console.print(
        Panel(body, title=f"[{theme.accent}]Task List[/]",
              border_style=theme.border, box=box.ROUNDED)
    )


# ── /skills & /goal ───────────────────────────────────────────────────────────

def print_skills(theme: Theme) -> None:
    console.print(
        Panel(
            Markdown(skills_manager.skill_content),
            title=f"[{theme.accent}]SKILL.md  (~/.orchestra/SKILL.md)[/]",
            border_style=theme.border, box=box.ROUNDED,
        )
    )


def print_goals(theme: Theme) -> None:
    active = skills_manager.active_goal
    active_label = (
        Text(active, style=theme.accent)
        if active
        else Text("(none set)", style="dim")
    )
    console.print(
        Panel(
            Group(
                Text.assemble(("  Active: ", "dim"), active_label),
                Text(""),
                Markdown(skills_manager.goals_content),
                Text(""),
                Text("  /goal set <text>  ·  /goal done", style="dim"),
            ),
            title=f"[{theme.accent}]GOALS.md  (~/.orchestra/GOALS.md)[/]",
            border_style=theme.border, box=box.ROUNDED,
        )
    )


# ── Agent activity display ────────────────────────────────────────────────────

class AgentActivity:
    """Context manager: shows a spinner + live tool call feed while the agent works."""

    def __init__(self, model: str, theme: Theme) -> None:
        self._model = model
        self._theme = theme
        self._live: Live | None = None

    def __enter__(self) -> "AgentActivity":
        global _active_live
        import random
        t = self._theme
        
        messages = [
            "  consulting the digital oracles with ",
            "  brewing some fresh ideas using ",
            "  weaving algorithmic magic via ",
            "  connecting the neural dots for ",
            "  polishing the gigabytes using ",
            "  asking the rubber duck about ",
            "  bribing the CPU with electricity for ",
            "  doing a little dance while pondering with ",
            "  summoning clever solutions via ",
            "  gathering stardust alongside ",
            "  petting the server cat while using ",
            "  crunching the numbers creatively with ",
        ]
        msg = random.choice(messages)
        
        spinner = Spinner(
            "dots2",
            text=Text.assemble(
                (msg, "dim"),
                (self._model,       t.accent),
                ("...",             "dim"),
            ),
        )
        self._live = Live(
            spinner, console=console, refresh_per_second=15, transient=True
        )
        self._live.start()
        _active_live = self._live
        return self

    def on_tool_call(self, name: str, args: dict, result: str) -> None:
        """Called by run_agent after each tool execution."""
        t = self._theme
        if self._live:
            self._live.stop()

        # Extract a brief summary from the result
        summary = str(result).split('\n')[0][:80]
        if str(result).startswith("OK") or str(result).startswith("Marked"):
            icon, style = "✓", "green"
        elif str(result).startswith("Error"):
            icon, style = "✗", "red"
        elif str(result).startswith("Task #"):
            icon, style = "✓", "green"
        else:
            icon, style = "→", t.tool

        console.print(f"  [{style}]{icon}[/] [{t.tool}]{name}[/] [dim]→ {summary}[/]")
        if self._live:
            self._live.start()

    def __exit__(self, *_: Any) -> None:
        global _active_live
        if self._live:
            self._live.stop()
        _active_live = None


# ── Slash-command handler ─────────────────────────────────────────────────────

def _render_history(memory: MemoryLayer, theme: Theme) -> None:
    """Print the conversation history natively into the terminal context."""
    if memory.is_empty:
        return
        
    for turn in memory.turns:
        if turn.role == "user":
            if "System Auto-Intercept:" not in turn.content and "(System Note:" not in turn.content:
                console.print(f"\n[bold {theme.accent}]>[/bold {theme.accent}] {turn.content}")
        elif turn.role == "assistant" and turn.content.strip():
            console.print(Panel(Markdown(turn.content, code_theme="monokai"), border_style=theme.border, box=box.ROUNDED))


def handle_slash(cmd_line: str, state: dict[str, Any]) -> bool:
    """
    Dispatch one slash command.
    Returns True to keep the REPL running, False to exit.
    """
    parts = cmd_line.strip().split(maxsplit=1)
    cmd   = parts[0].lower()
    arg   = parts[1].strip() if len(parts) > 1 else ""

    cfg: Config         = state["cfg"]
    theme: Theme        = cfg.current_theme
    memory: MemoryLayer = state["memory"]

    # ── exit ──────────────────────────────────────────────────────────────
    if cmd == "/exit":
        import time
        msg = "  Shutting down all local systems and securely preserving your session state...\n  Farewell, Commander. Until next time."
        console.print()
        for char in msg:
            console.print(f"[{theme.accent}]{char}[/]", end="")
            time.sleep(0.03)
        console.print("\n")
        return False

    # ── help ──────────────────────────────────────────────────────────────
    elif cmd == "/help":
        print_help(theme)

    # ── clear ─────────────────────────────────────────────────────────────
    elif cmd == "/clear":
        console.clear()
        print_banner(theme, cfg.model)

    # ── reset ─────────────────────────────────────────────────────────────
    elif cmd == "/reset":
        memory.reset()
        memory.save(SESSION_DIR / f"{cfg.active_session}.json")
        _info("Conversation history cleared.", theme)

    # ── context ───────────────────────────────────────────────────────────
    elif cmd == "/context":
        if arg.lower() in ("clear", "reset"):
            memory.reset()
            memory.save(SESSION_DIR / f"{cfg.active_session}.json")
            _info("Context window cleared.", theme)
        else:
            print_memory(memory, theme, cfg.context_limit)


    # ── tasks ──────────────────────────────────────────────────────────────
    elif cmd == "/tasks":
        sub_parts = arg.split(maxsplit=1)
        sub       = sub_parts[0].lower() if sub_parts else ""
        sub_arg   = sub_parts[1].strip() if len(sub_parts) > 1 else ""

        tasks = TaskList.load()

        if not arg or sub == "list":
            print_tasks(tasks, theme)

        elif sub == "add":
            if not sub_arg:
                _warn("Usage: /tasks add <task description>", theme)
            else:
                item = tasks.add(sub_arg)
                tasks.save()
                _info(f"Added task #{item.id}: {sub_arg}", theme)

        elif sub == "done":
            if sub_arg.isdigit():
                n = int(sub_arg)
                if tasks.complete(n):
                    item = tasks._get(n)
                    tasks.save()
                    _info(f"Marked #{n} done: {item.text if item else ''}", theme)
                else:
                    _warn(f"Could not complete task #{n} — check number or status.", theme)
            else:
                _warn("Usage: /tasks done <number>", theme)

        elif sub == "clear":
            tasks.clear_all()
            tasks.save()
            _info("Tasks list cleared.", theme)

        else:
            _warn("Usage: /tasks  |  /tasks add <text>  |  /tasks done <n>  |  /tasks clear", theme)

    # ── goal ──────────────────────────────────────────────────────────────
    elif cmd == "/goal":
        sub_parts = arg.split(maxsplit=1)
        sub       = sub_parts[0].lower() if sub_parts else ""
        sub_arg   = sub_parts[1].strip() if len(sub_parts) > 1 else ""

        if not arg:
            print_goals(theme)

        elif sub == "set":
            if not sub_arg:
                _warn("Usage: /goal set <description>", theme)
            else:
                skills_manager.set_active_goal(sub_arg)
                state["system_prompt"] = skills_manager.build_system_prompt()
                # Also store goal in tasks list
                tasks = TaskList.load()
                tasks.goal = sub_arg
                tasks.save()
                _info(f"Goal set: [{theme.accent}]{sub_arg}[/]", theme)

        elif sub == "done":
            archived = skills_manager.archive_active_goal()
            state["system_prompt"] = skills_manager.build_system_prompt()
            if archived:
                _info(f"Goal archived: [{theme.accent}]{archived}[/]", theme)
            else:
                _warn("No active goal to archive.", theme)

        else:
            _warn("Usage: /goal  |  /goal set <text>  |  /goal done", theme)

    # ── skills ────────────────────────────────────────────────────────────
    elif cmd == "/skills":
        print_skills(theme)

    # ── verbose ───────────────────────────────────────────────────────────
    elif cmd == "/verbose":
        state["verbose"] = not state["verbose"]
        flag = "[green]ON[/]" if state["verbose"] else "[red]OFF[/]"
        _info(f"Verbose mode {flag}", theme)

    # ── tools ─────────────────────────────────────────────────────────────
    elif cmd == "/tools":
        print_tools(theme)

    # ── model ─────────────────────────────────────────────────────────────
    elif cmd == "/model":
        if not arg:
            _info(f"Current model: [{theme.accent}]{cfg.model}[/]", theme)
            _info("  [dim]/model <name>  (e.g., /model llama3)[/]", theme)
            try:
                import ollama
                list_resp = ollama.list()
                models = [m.model for m in list_resp.models]
                if not models:
                    _warn("No Ollama models found. Ensure Ollama is running.", theme)
                else:
                    _info("Available Models:", theme)
                    for i, m in enumerate(models, 1):
                        console.print(f"  [{theme.accent}]{i}.[/] {m}")
                    
                    choice = Prompt.ask("\n  Select model number", choices=[str(i) for i in range(1, len(models)+1)], show_choices=False)
                    if choice:
                        result = models[int(choice)-1]
                        cfg.model = result
                        memory.reset()
                        memory.save(SESSION_DIR / f"{cfg.active_session}.json")
                        cfg.save()
                        _info(f"Switched to [{theme.accent}]{result}[/] [dim](history reset)[/]", theme)
            except Exception as e:
                _error(f"Could not fetch models: {e}", theme)
        else:
            cfg.model = arg
            memory.reset()
            memory.save(SESSION_DIR / f"{cfg.active_session}.json")
            cfg.save()
            _info(
                f"Switched to [{theme.accent}]{arg}[/]  [dim](history reset)[/]",
                theme,
            )

    # ── settings ──────────────────────────────────────────────────────────
    elif cmd == "/settings":
        import json
        import dataclasses
        settings_str = json.dumps(dataclasses.asdict(cfg), indent=2)
        console.print(Panel(settings_str, title=f"[{theme.accent}]Configuration[/]", border_style=theme.border))

    # ── about ─────────────────────────────────────────────────────────────
    elif cmd == "/about":
        about_text = (
            f"[bold {theme.accent}]Orchestra[/] by TheAhsanFarabi\n\n"
            "An agentic AI assistant framework built for power users.\n"
            "Features include autonomous planning, persistent memory, multi-session support, "
            "and ambient background music (Shift+Tab to toggle).\n\n"
            "v1.0.0"
        )
        console.print(Panel(about_text, title=f"[{theme.accent}]About[/]", border_style=theme.border))

    # ── mode ──────────────────────────────────────────────────────────────
    elif cmd == "/mode":
        current = state.get("mood", "action")
        if current == "action":
            new_mood = "plan"
        elif current == "plan":
            new_mood = "chat"
        else:
            new_mood = "action"
        state["mood"] = new_mood
        _info(f"Mode switched to: [bold {theme.accent}]{new_mood.upper()}[/]", theme)

    # ── fast ──────────────────────────────────────────────────────────────
    elif cmd == "/fast":
        cfg.model = "qwen2.5:1.5b"
        cfg.save()
        _info(f"Fast mode engaged. Switched to [{theme.accent}]qwen2.5:1.5b[/]", theme)

    # ── theme ─────────────────────────────────────────────────────────────
    elif cmd == "/theme":
        if arg and arg.lower() in THEMES:
            cfg.theme = arg.lower()
            cfg.save()
            new_theme = cfg.current_theme
            # Rebuild the prompt_toolkit session with new theme colors
            state["session"] = _make_session(new_theme, state)
            _info(f"Theme switched to {new_theme.emoji} [{new_theme.accent}]{new_theme.name}[/]", new_theme)
        else:
            # Show interactive theme picker
            tbl = Table(box=box.SIMPLE_HEAD, border_style="dim", header_style=theme.accent)
            tbl.add_column("#", style="dim", width=3)
            tbl.add_column("Theme", style="bold")
            tbl.add_column("Description")
            for i, (key, t) in enumerate(THEMES.items(), 1):
                active = " ←" if key == cfg.theme else ""
                tbl.add_row(str(i), f"{t.emoji} {t.name}{active}", t.description)
            console.print(Panel(tbl, title=f"[{theme.accent}]Pick a Theme[/]", border_style=theme.border, box=box.ROUNDED))
            
            theme_keys = list(THEMES.keys())
            choices = [str(i) for i in range(1, len(theme_keys) + 1)]
            try:
                choice = Prompt.ask("  Select theme number", choices=choices, show_choices=False)
                if choice:
                    selected = theme_keys[int(choice) - 1]
                    cfg.theme = selected
                    cfg.save()
                    new_theme = cfg.current_theme
                    state["session"] = _make_session(new_theme, state)
                    _info(f"Theme switched to {new_theme.emoji} [{new_theme.accent}]{new_theme.name}[/]", new_theme)
            except (EOFError, KeyboardInterrupt):
                pass

    # ── prompt ────────────────────────────────────────────────────────────
    elif cmd == "/prompt":
        if arg:
            prompt_content = get_prompt(arg)
            if prompt_content:
                state["next_input"] = prompt_content
                _info(f"Loaded prompt [{theme.accent}]{arg}[/] into your input buffer. You can now modify it before sending.", theme)
            else:
                _error(f"Prompt not found: {arg}", theme)
        else:
            prompts = list_prompts()
            if not prompts:
                _warn("No prompts found in ~/.orchestra/prompts/", theme)
            else:
                tbl = Table(box=box.SIMPLE_HEAD, border_style="dim", header_style=theme.accent, show_lines=True)
                tbl.add_column("Prompt Name", style="bold", ratio=1)
                tbl.add_column("Full Text", ratio=4)
                for name, content in prompts.items():
                    tbl.add_row(name, content)
                console.print(Panel(tbl, title=f"[{theme.accent}]Prompt Library[/]", border_style=theme.border, box=box.ROUNDED))
                _info("  [dim]/prompt <name>  (loads the prompt into your input buffer)[/]", theme)

    # ── add (Context Injection) ───────────────────────────────────────────
    elif cmd == "/add":
        if not arg:
            _info("  [dim]/add <file>  (injects file contents into context)[/]", theme)
        else:
            path = Path(arg)
            if not path.is_file():
                _error(f"File not found: {arg}", theme)
            else:
                try:
                    content = path.read_text(encoding="utf-8")
                    state["context_buffer"] += f"\n\n--- File: {arg} ---\n{content}\n"
                    _info(f"Loaded {len(content)} chars from {arg} into next context.", theme)
                except Exception as e:
                    _error(f"Could not read {arg}: {e}", theme)

    # ── artifact ──────────────────────────────────────────────────────────
    elif cmd == "/artifact":
        artifact_dir = Path.home() / ".orchestra" / "artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        
        sub_parts = arg.split(maxsplit=1)
        sub       = sub_parts[0].lower() if sub_parts else ""
        sub_arg   = sub_parts[1].strip() if len(sub_parts) > 1 else ""

        if not arg or sub == "list":
            artifacts = list(artifact_dir.glob("*.md"))
            if not artifacts:
                _warn("No artifacts found in ~/.orchestra/artifacts/", theme)
                _info("  [dim]/artifact view <name>  ·  /artifact add <name>[/]", theme)
            else:
                tbl = Table(box=box.SIMPLE_HEAD, border_style="dim", header_style=theme.accent)
                tbl.add_column("Artifact Name", style="bold")
                tbl.add_column("Size", style="dim")
                for a in artifacts:
                    size = f"{a.stat().st_size / 1024:.1f} KB"
                    tbl.add_row(a.name, size)
                console.print(Panel(tbl, title=f"[{theme.accent}]Saved Artifacts[/]", border_style=theme.border, box=box.ROUNDED))
                _info("  [dim]/artifact view <name>  ·  /artifact add <name>[/]", theme)
                
        elif sub == "view":
            if not sub_arg:
                _warn("Usage: /artifact view <name>", theme)
            else:
                name = sub_arg if sub_arg.endswith(".md") else f"{sub_arg}.md"
                path = artifact_dir / name
                if not path.is_file():
                    _error(f"Artifact not found: {name}", theme)
                else:
                    content = path.read_text(encoding="utf-8")
                    console.print(Panel(Markdown(content, code_theme="monokai"), title=f"[{theme.accent}]{name}[/]", border_style=theme.border, box=box.ROUNDED))
                    
        elif sub == "add":
            if not sub_arg:
                _warn("Usage: /artifact add <name>", theme)
            else:
                name = sub_arg if sub_arg.endswith(".md") else f"{sub_arg}.md"
                path = artifact_dir / name
                if not path.is_file():
                    _error(f"Artifact not found: {name}", theme)
                else:
                    try:
                        content = path.read_text(encoding="utf-8")
                        state["context_buffer"] += f"\n\n--- Artifact: {name} ---\n{content}\n"
                        _info(f"Loaded {len(content)} chars from {name} into next context.", theme)
                    except Exception as e:
                        _error(f"Could not read {name}: {e}", theme)
        else:
            _warn("Usage: /artifact [list] | /artifact view <name> | /artifact add <name>", theme)

    # ── session ───────────────────────────────────────────────────────────
    elif cmd == "/session":
        if not arg or arg == "list":
            sessions = []
            if SESSION_DIR.exists():
                sessions = [p.stem for p in SESSION_DIR.glob("*.json") if not p.stem.endswith("_tasks")]
            if not sessions:
                _info("No saved sessions.", theme)
            else:
                _info("Saved sessions:\n  " + "\n  ".join(sessions), theme)
                _info(f"Current active session: {cfg.active_session}", theme)
                _info("  [dim]/session new  ·  /session <hash>  ·  /session delete <hash>  ·  /session delete all[/]", theme)
        elif arg == "new":
            import uuid
            new_hash = uuid.uuid4().hex[:8]
            cfg.active_session = new_hash
            cfg.save()
            state["memory"] = MemoryLayer()
            state["memory"].save(SESSION_DIR / f"{new_hash}.json")
            _info(f"Started new session: {new_hash}", theme)
        elif arg.startswith("delete "):
            target_hash = arg.split(" ", 1)[1].strip()
            
            if target_hash == "all":
                count = 0
                if SESSION_DIR.exists():
                    for target in list(SESSION_DIR.glob("*.json")) + list(SESSION_DIR.glob("*.md")):
                        target.unlink()
                        count += 1
                
                import uuid
                new_hash = uuid.uuid4().hex[:8]
                cfg.active_session = new_hash
                cfg.save()
                state["memory"].reset()
                state["memory"].save(SESSION_DIR / f"{new_hash}.json")
                _info(f"Deleted {count} session file(s). Started a fresh session: {new_hash}", theme)
            else:
                target = SESSION_DIR / f"{target_hash}.json"
                if target.exists():
                    target.unlink()
                    todo_file = SESSION_DIR / f"{target_hash}_tasks.json"
                    if todo_file.exists():
                        todo_file.unlink()
                    goals_file = SESSION_DIR / f"{target_hash}_GOALS.md"
                    if goals_file.exists():
                        goals_file.unlink()
                    _info(f"Session '{target_hash}' has been deleted.", theme)
                    if cfg.active_session == target_hash:
                        import uuid
                        new_hash = uuid.uuid4().hex[:8]
                        cfg.active_session = new_hash
                        cfg.save()
                        state["memory"].reset()
                        state["memory"].save(SESSION_DIR / f"{new_hash}.json")
                        _info(f"Active session deleted. Started a new session: {new_hash}", theme)
                else:
                    _warn(f"Session not found: {target_hash}", theme)
        else:
            target = SESSION_DIR / f"{arg}.json"
            if target.exists():
                cfg.active_session = arg
                cfg.save()
                state["memory"] = MemoryLayer.load(target)
                _info(f"Resumed session: {arg}", theme)
                _render_history(state["memory"], theme)
            else:
                _warn(f"Session not found: {arg}", theme)

    # ── unknown ───────────────────────────────────────────────────────────
    else:
        _warn(
            f"Unknown command: [bold]{cmd}[/]  —  type [bold]/help[/] for all commands.",
            theme,
        )

    return True


# ── Main entry point ──────────────────────────────────────────────────────────

def run_tui(model: str | None = None, verbose: bool = False) -> None:
    """Start the Orchestra TUI. Handles first-run welcome automatically."""
    cfg = Config.load()

    if model:
        cfg.model = model
        cfg.save()

    # ── First-run welcome (runs exactly once) ─────────────────────────────
    if not cfg.welcomed:
        cfg = show_welcome(cfg)

    # ── Wire permission panel ─────────────────────────────────────────────
    permission_manager.confirm_fn = _tui_confirm

    # ── Load skills + goals (create ~/.orchestra/SKILL.md etc. if absent) ─
    skills_manager.load()
    init_prompts()

    theme   = cfg.current_theme

    print_banner(theme, cfg.model)

    if not cfg.active_session:
        import uuid
        cfg.active_session = uuid.uuid4().hex[:8]
        cfg.save()

    active_session_file = SESSION_DIR / f"{cfg.active_session}.json"
    memory = MemoryLayer.load(active_session_file)
    _render_history(memory, theme)

    state: dict[str, Any] = {
        "cfg":           cfg,
        "memory":        memory,
        "verbose":       verbose,
        "session":       None,
        "system_prompt": skills_manager.build_system_prompt(),
        "mood":          "action",
        "context_buffer": "",
    }
    
    session = _make_session(theme, state)
    state["session"] = session

    # ── REPL ──────────────────────────────────────────────────────────────
    while True:
        theme = state["cfg"].current_theme

        # Rebuild prompt_toolkit style from current theme each iteration
        pt_style = PTStyle.from_dict({
            "completion-menu.completion":
                f"bg:#1e1e2e #{theme.pt_model}",
            "completion-menu.completion.current":
                f"bg:#{theme.pt_main} #1e1e2e bold",
            "auto-suggestion":
                f"#{theme.pt_dim} italic",
            "bottom-toolbar":
                f"bg:#{theme.pt_main} #000000",
        })

        def get_toolbar():
            return _get_bottom_toolbar(state)

        try:
            w = shutil.get_terminal_size().columns
            
            default_text = state.pop("next_input", "")
            
            user_input: str = state["session"].prompt(
                _prompt_html(state["cfg"].model, theme),
                style=pt_style,
                bottom_toolbar=get_toolbar,
                default=default_text,
            )
            # Print gradient bottom border to complete the layout
            print(_gradient_rule(theme, w), flush=True)
        except KeyboardInterrupt:
            console.print()
            continue
        except EOFError:
            console.print(f"\n  [{theme.accent}]Goodbye.[/]\n")
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        if user_input.startswith("/"):
            if not handle_slash(user_input, state):
                break
            continue

        if user_input.startswith("!"):
            command = user_input[1:].strip()
            console.print(f"  [dim]$ {command}[/]")
            try:
                result = subprocess.run(command, shell=True, text=True, capture_output=True)
                output = (result.stdout + "\n" + result.stderr).strip()
            except Exception as e:
                output = f"Command failed: {e}"
                
            console.print(Panel(output, border_style="dim", title=f"Terminal: {command}", box=box.ROUNDED))
            
            # Inject terminal execution into history so the LLM is aware
            state["memory"].push({
                "role": "user", 
                "content": f"I ran a terminal command: `{command}`\n\nOutput:\n```\n{output}\n```"
            })
            state["memory"].save(SESSION_DIR / f"{state['cfg'].active_session}.json")
            continue

        # ── Agent turn ────────────────────────────────────────────────────
        console.print()
        memory: MemoryLayer = state["memory"]
        
        # Inject context buffer if present
        if state["context_buffer"]:
            user_input = f"<CONTEXT>{state['context_buffer']}</CONTEXT>\n\n{user_input}"
            state["context_buffer"] = "" # consume it

        history_in = memory.to_list() if not memory.is_empty else None

        # Set up streaming response display
        _stream_live: Live | None = None
        _stream_started = False

        def _on_stream(text: str) -> None:
            nonlocal _stream_live, _stream_started
            if not _stream_started:
                _stream_started = True
                try:
                    body = Markdown(text, code_theme="monokai")
                except Exception:
                    body = Text(text)
                _stream_live = Live(
                    Panel(body, title=f"[{theme.accent}]orchestra[/]",
                          border_style=theme.agent_border, box=box.ROUNDED, padding=(0, 1)),
                    console=console, refresh_per_second=8, transient=False
                )
                _stream_live.start()
            elif _stream_live:
                try:
                    body = Markdown(text, code_theme="monokai")
                except Exception:
                    body = Text(text)
                _stream_live.update(
                    Panel(body, title=f"[{theme.accent}]orchestra[/]",
                          border_style=theme.agent_border, box=box.ROUNDED, padding=(0, 1))
                )

        try:
            activity = AgentActivity(state["cfg"].model, theme)
            with activity:
                answer, new_msgs = run_agent(
                    user_input,
                    model         = state["cfg"].model,
                    history       = history_in,
                    verbose       = state["verbose"],
                    system_prompt = state["system_prompt"],
                    mood          = state["mood"],
                    context_limit = state["cfg"].context_limit,
                    on_tool_call  = activity.on_tool_call,
                    on_stream     = _on_stream,
                )
            state["memory"] = MemoryLayer.from_list(new_msgs)
            state["memory"].save(SESSION_DIR / f"{state['cfg'].active_session}.json")

        except Exception as exc:
            if _stream_live:
                _stream_live.stop()
            _error(f"Agent error: {exc}", theme)
            console.print()
            continue

        if _stream_live:
            _stream_live.stop()
        
        # If streaming didn't render, fall back to static render
        if not _stream_started:
            print_response(answer, theme)
        console.print()
