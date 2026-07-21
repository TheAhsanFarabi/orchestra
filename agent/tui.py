"""
Orchestra TUI — rich, interactive terminal interface.

First run:
  A full-screen welcome intro walks the user through what Orchestra is
  and lets them pick a theme. Saved to ~/.orchestra/config.json;
  subsequent launches skip straight to the main interface.

Slash commands:
  /help          Show all commands
  /model         Switch Ollama model
  /memory        Show context window (cube grid)
  /todo          Manage the todo list
  /goal          Show or set the active goal
  /skills        Show ~/.orchestra/SKILL.md
  /history       View conversation history
  /clear         Clear conversation
  /tools         List available tools
  /memory        Show context window usage
  /exit          Quit Orchestra
"""

from __future__ import annotations

import time
import subprocess
from pathlib import Path
from typing import Any

import pyfiglet

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.styles import Style as PTStyle
from prompt_toolkit.formatted_text import HTML

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
from .todo import TodoList, STATUS_ICON, STATUS_STYLE
from .config import (
    Config, Theme, THEMES, THEME_KEYS, DEFAULT_THEME,
    HISTORY_FILE, VERSION,
)

# ── Shared console ────────────────────────────────────────────────────────────

console = Console()

# ── Module-level Live handle (so _tui_confirm can pause/resume it) ────────────

_active_live: Live | None = None

# ── Slash-command registry ────────────────────────────────────────────────────

SLASH_COMMANDS: dict[str, str] = {
    "/help":         "Show this help",
    "/model":        "Switch model  —  /model <name>",
    "/mood":         "Toggle between Action (default) and Plan mode",
    "/add":          "Inject a file's content into AI context  —  /add <file>",
    "/history":      "View conversation history",
    "/clear":        "Clear conversation",
    "/tools":        "List available tools",
    "/memory":       "Show context usage map",
    "/exit":         "Quit Orchestra",
    "/quit":         "Quit Orchestra",
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

def _make_session(theme: Theme) -> PromptSession:
    completer = WordCompleter(list(SLASH_COMMANDS.keys()), sentence=True)
    pt_style  = PTStyle.from_dict({
        "completion-menu.completion":
            f"bg:#1e1e2e #{theme.pt_model}",
        "completion-menu.completion.current":
            f"bg:#{theme.pt_main} #1e1e2e bold",
        "auto-suggestion":
            f"#{theme.pt_dim} italic",
    })
    return PromptSession(
        history             = FileHistory(str(HISTORY_FILE)),
        auto_suggest        = AutoSuggestFromHistory(),
        completer           = completer,
        style               = pt_style,
        complete_while_typing = True,
    )


def _prompt_html(model: str, theme: Theme) -> HTML:
    c = f"#{theme.pt_main}"
    m = f"#{theme.pt_model}"
    return HTML(
        f"<b><style fg='{c}'>you</style></b>"
        f" <style fg='{m}'>({model})</style>"
        f" <b><style fg='{c}'>›</style></b> "
    )


# ── Banner ────────────────────────────────────────────────────────────────────

def _make_logo(terminal_width: int = 100) -> str:
    font = "small_slant"
    try:
        return pyfiglet.figlet_format("ORCHESTRA", font=font).rstrip()
    except Exception:
        return "  O R C H E S T R A"

def _render_icon(path: str = "icon.png", width: int = 16, height: int = 8) -> Text:
    try:
        from PIL import Image
        img = Image.open(path).resize((width, height * 2), Image.Resampling.LANCZOS).convert("RGBA")
        pixels = img.load()
        text = Text()
        for y in range(0, height * 2, 2):
            for x in range(width):
                r1, g1, b1, a1 = pixels[x, y]
                r2, g2, b2, a2 = pixels[x, y + 1]
                
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
    icon = _render_icon()

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
    console.print(
        Panel(tbl, title=f"[{theme.accent}]Available Tools[/]",
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
        "  /reset to clear  ·  /memory clear is an alias for /reset",
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


# ── /todo ─────────────────────────────────────────────────────────────────────

def print_todo(todo: TodoList, theme: Theme) -> None:
    goal_text = todo.goal if todo.goal else "(no goal set — use /goal set <text>)"

    tbl = Table(
        box=box.SIMPLE_HEAD, border_style="dim",
        header_style=theme.accent, show_header=bool(todo.items),
    )
    tbl.add_column("#",      style="dim", width=4,  no_wrap=True)
    tbl.add_column("Status", width=14,              no_wrap=True)
    tbl.add_column("Task")

    for i, item in enumerate(todo.items, 1):
        icon   = STATUS_ICON[item.status]
        istyle = STATUS_STYLE[item.status]
        tbl.add_row(
            str(i),
            Text(f"{icon} {item.status}", style=istyle),
            item.text,
        )

    done = sum(1 for x in todo.items if x.status == "done")
    ip   = sum(1 for x in todo.items if x.status == "in_progress")
    pend = sum(1 for x in todo.items if x.status == "pending")

    footer = Text.assemble(
        (f"  {done} done",         "green"),
        ("  ·  ",                   "dim"),
        (f"{ip} in progress",       "cyan"),
        ("  ·  ",                   "dim"),
        (f"{pend} pending",         "dim"),
    ) if todo.items else Text("")

    body = Group(
        Text(f"  {goal_text}", style="dim italic"),
        Text(""),
        tbl if todo.items
            else Text("  (no tasks yet — use /todo add <text>)", style="dim"),
        Text(""),
        footer,
        Text(""),
        Text("  /todo add <text>  ·  /todo done <n>  ·  /todo clear", style="dim"),
        Text(""),
    )
    console.print(
        Panel(body, title=f"[{theme.accent}]Todo List[/]",
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
            ),
            title=f"[{theme.accent}]GOALS.md  (~/.orchestra/GOALS.md)[/]",
            border_style=theme.border, box=box.ROUNDED,
        )
    )


# ── Thinking spinner ──────────────────────────────────────────────────────────

class Thinking:
    """Context manager: animated spinner while the agent is working."""

    def __init__(self, model: str, theme: Theme) -> None:
        self._model = model
        self._theme = theme
        self._live: Live | None = None

    def __enter__(self) -> "Thinking":
        global _active_live
        t = self._theme
        spinner = Spinner(
            "dots2",
            text=Text.assemble(
                ("  thinking with ", "dim"),
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

    def __exit__(self, *_: Any) -> None:
        global _active_live
        if self._live:
            self._live.stop()
        _active_live = None


# ── Slash-command handler ─────────────────────────────────────────────────────

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
    if cmd in ("/exit", "/quit"):
        console.print(f"\n  [{theme.accent}]Goodbye.[/]\n")
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
        _info("Conversation history cleared.", theme)

    # ── memory ────────────────────────────────────────────────────────────
    elif cmd == "/memory":
        if arg.lower() in ("clear", "reset"):
            memory.reset()
            _info("Context window cleared.", theme)
        else:
            print_memory(memory, theme, cfg.context_limit)

    # ── todo ──────────────────────────────────────────────────────────────
    elif cmd == "/todo":
        sub_parts = arg.split(maxsplit=1)
        sub       = sub_parts[0].lower() if sub_parts else ""
        sub_arg   = sub_parts[1].strip() if len(sub_parts) > 1 else ""

        todo = TodoList.load()

        if not arg or sub == "list":
            print_todo(todo, theme)

        elif sub == "add":
            if not sub_arg:
                _warn("Usage: /todo add <task description>", theme)
            else:
                item = todo.add(sub_arg)
                todo.save()
                _info(f"Added task #{item.id}: {sub_arg}", theme)

        elif sub == "done":
            if sub_arg.isdigit():
                n = int(sub_arg)
                if todo.complete(n):
                    item = todo._get(n)
                    todo.save()
                    _info(f"Marked #{n} done: {item.text if item else ''}", theme)
                else:
                    _warn(f"Could not complete task #{n} — check number or status.", theme)
            else:
                _warn("Usage: /todo done <number>", theme)

        elif sub == "clear":
            todo.clear_all()
            todo.save()
            _info("Todo list cleared.", theme)

        else:
            _warn("Usage: /todo  |  /todo add <text>  |  /todo done <n>  |  /todo clear", theme)

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
                # Also store goal in todo list
                todo = TodoList.load()
                todo.goal = sub_arg
                todo.save()
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
            _info("Usage: /model <name>  e.g. /model llama3.1:8b", theme)
        else:
            cfg.model = arg
            memory.reset()
            cfg.save()
            _info(
                f"Switched to [{theme.accent}]{arg}[/]  [dim](history reset)[/]",
                theme,
            )

    # ── mood ──────────────────────────────────────────────────────────────
    elif cmd == "/mood":
        current = state.get("mood", "action")
        new_mood = "plan" if current == "action" else "action"
        state["mood"] = new_mood
        _info(f"Mood switched to: [bold {theme.accent}]{new_mood.upper()}[/]", theme)

    # ── add (Context Injection) ───────────────────────────────────────────
    elif cmd == "/add":
        if not arg:
            _warn("Usage: /add <file>", theme)
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

    theme   = cfg.current_theme
    session = _make_session(theme)

    print_banner(theme, cfg.model)

    state: dict[str, Any] = {
        "cfg":           cfg,
        "memory":        MemoryLayer(),
        "verbose":       verbose,
        "session":       session,
        "system_prompt": skills_manager.build_system_prompt(),
        "mood":          "action",
        "context_buffer": "",
    }

    # ── REPL ──────────────────────────────────────────────────────────────
    while True:
        theme = state["cfg"].current_theme

        try:
            user_input: str = state["session"].prompt(
                _prompt_html(state["cfg"].model, theme)
            )
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
            continue

        # ── Agent turn ────────────────────────────────────────────────────
        console.print()
        memory: MemoryLayer = state["memory"]
        
        # Inject context buffer if present
        if state["context_buffer"]:
            user_input = f"<CONTEXT>{state['context_buffer']}</CONTEXT>\n\n{user_input}"
            state["context_buffer"] = "" # consume it

        history_in = memory.to_list() if not memory.is_empty else None

        try:
            with Thinking(state["cfg"].model, theme):
                answer, new_msgs = run_agent(
                    user_input,
                    model         = state["cfg"].model,
                    history       = history_in,
                    verbose       = state["verbose"],
                    system_prompt = state["system_prompt"],
                    mood          = state["mood"],
                )
            state["memory"] = MemoryLayer.from_list(new_msgs)

        except Exception as exc:
            _error(f"Agent error: {exc}", theme)
            console.print()
            continue

        print_response(answer, theme)
        console.print()
