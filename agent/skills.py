"""
Orchestra Skills Manager.

Loads ~/.orchestra/SKILL.md and ~/.orchestra/GOALS.md on TUI startup,
creating them from built-in templates if they don't exist yet.

The merged content is injected as the system prompt into run_agent(),
giving the agent a persistent identity, tool awareness, and active goal.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from .config import CONFIG_DIR

# ── File paths ────────────────────────────────────────────────────────────────

SKILL_FILE = CONFIG_DIR / "SKILL.md"

def get_goals_file() -> Path:
    from .config import Config, SESSION_DIR
    cfg = Config.load()
    if cfg.active_session:
        SESSION_DIR.mkdir(parents=True, exist_ok=True)
        return SESSION_DIR / f"{cfg.active_session}_GOALS.md"
    return CONFIG_DIR / "GOALS.md"

# ── Default templates ─────────────────────────────────────────────────────────

SKILL_TEMPLATE = """\
# Orchestra Skills

## Role
You are Orchestra, an autonomous local privacy-first AI agent running on the user's device. 
You work methodically, step by step, and always keep the user informed of your progress.

CRITICAL WORKFLOW:
1. When given a complex request or goal, DO NOT execute it immediately.
2. Identify the steps required.
3. Use the `tasks_add` tool to add each step to your task list.
4. Work through the steps one by one using your available file and terminal tools.
5. IMPORTANT: As soon as you finish a task, you MUST use the `tasks_done` tool to mark it complete. YOU MUST DO THIS BEFORE RESPONDING TO THE USER! Do not forget this step!
6. SILENT TRACKING: Manage your tasks list silently. When you have completed all tasks, your final text response MUST be a friendly summary of what you did. NEVER output raw tool logs (like "Marked #3 as done") as your response.
7. NEVER write out tool calls as raw JSON in your text response (e.g. `{"name": "tasks_done"}`). You must invoke tools using the native tool-calling API.

## Available Tools
- read_file, list_directory    — explore the filesystem (read-only, no approval)
- write_file, append_file, delete_path — modify files (prompts user for approval)
- create_directory             — create folders         (requires user approval)
- move_file                    — rename or move         (requires user approval)
- run_bash — execute terminal commands (prompts user for approval)
- search_files                 — grep-style search      (read-only, no approval)
- tasks_add, tasks_done, tasks_list — manage your task list (no approval needed)
- create_artifact              — create .md files for long plans/reports

## Working Style
1. Before starting any multi-step goal, call tasks_list to check current tasks.
2. Always explain your reasoning before calling a tool.
3. If a tool returns an error, explain it clearly — do not blindly retry.
4. When uncertain, ask the user rather than making assumptions.
5. Respect user privacy — never exfiltrate data.
6. Use the create_artifact tool when you need to write long plans, architectural designs, or complex research notes. Save them as markdown files so the user can easily review them and inject them into future contexts.
"""

GOALS_TEMPLATE = """\
# Goals

## Active Goal
(none — use /goal set <description> to define a goal)

## Completed Goals
(none yet)
"""


# ── SkillsManager ─────────────────────────────────────────────────────────────

class SkillsManager:
    """
    Loads SKILL.md and GOALS.md, creates them from templates if absent,
    and builds the enriched system prompt injected into run_agent().
    """

    def __init__(self) -> None:
        self.skill_content: str = SKILL_TEMPLATE
        self.goals_content: str = GOALS_TEMPLATE

    # ── Loading ───────────────────────────────────────────────────────────

    def load(self) -> None:
        """Read ~/.orchestra/SKILL.md and GOALS.md. Create from template if absent."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if not SKILL_FILE.exists():
            SKILL_FILE.write_text(SKILL_TEMPLATE)
        goals_file = get_goals_file()
        if not goals_file.exists():
            goals_file.write_text(GOALS_TEMPLATE)
        self.skill_content = SKILL_FILE.read_text(errors="replace")
        self.goals_content = goals_file.read_text(errors="replace")

    def reload(self) -> None:
        """Re-read files from disk (e.g. after /goal set)."""
        self.load()

    # ── System prompt ─────────────────────────────────────────────────────

    def build_system_prompt(self) -> str:
        """Return the merged system prompt (SKILL.md + GOALS.md)."""
        prompt = (
            self.skill_content.strip()
            + "\n\n---\n\n"
            + self.goals_content.strip()
        )
        if self.active_goal:
            prompt += (
                f"\n\nYour overarching active goal is: '{self.active_goal}'\n"
                "You must use the `tasks_add` and `tasks_done` tools to manage your progress toward this goal."
            )
        return prompt

    # ── Goal management ───────────────────────────────────────────────────

    @property
    def active_goal(self) -> str:
        """Extract the active goal text from goals_content."""
        m = re.search(r"## Active Goal\n(.*?)(?=\n## |\Z)", self.goals_content, re.DOTALL)
        if m:
            text = m.group(1).strip()
            return text if not text.startswith("(none") else ""
        return ""

    def set_active_goal(self, goal: str) -> None:
        """Replace the Active Goal section in GOALS.md and save."""
        goals_file = get_goals_file()
        content = (
            goals_file.read_text(errors="replace")
            if goals_file.exists()
            else GOALS_TEMPLATE
        )
        new_section = f"## Active Goal\n{goal}\n"
        if re.search(r"^## Active Goal", content, re.MULTILINE):
            content = re.sub(
                r"## Active Goal\n.*?(?=\n## |\Z)",
                new_section,
                content,
                flags=re.DOTALL,
            )
        else:
            content += f"\n{new_section}"
        goals_file = get_goals_file()
        goals_file.write_text(content)
        self.goals_content = content

    def archive_active_goal(self) -> str:
        """Move Active Goal → Completed Goals. Returns the archived text."""
        content = (
            GOALS_FILE.read_text(errors="replace")
            if GOALS_FILE.exists()
            else GOALS_TEMPLATE
        )
        m = re.search(r"## Active Goal\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
        if not m:
            return ""
        active_text = m.group(1).strip()
        if not active_text or active_text.startswith("(none"):
            return ""

        date_str = datetime.now().strftime("%Y-%m-%d")
        content  = re.sub(
            r"## Active Goal\n.*?(?=\n## |\Z)",
            "## Active Goal\n(none — use /goal set <description> to define a goal)\n",
            content,
            flags=re.DOTALL,
        )
        entry = f"- [{date_str}] {active_text}\n"
        if "## Completed Goals" in content:
            if "(none yet)" in content:
                content = content.replace("(none yet)\n", entry)
            else:
                content = content.replace(
                    "## Completed Goals\n",
                    f"## Completed Goals\n{entry}",
                )
        else:
            content += f"\n## Completed Goals\n{entry}"

        goals_file = get_goals_file()
        goals_file.write_text(content)
        self.goals_content = content
        return active_text


# ── Global singleton ──────────────────────────────────────────────────────────

skills_manager = SkillsManager()
