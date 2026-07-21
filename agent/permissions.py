"""
Orchestra Permission System.

Every destructive tool calls permission_manager.request() before executing.
The TUI overrides confirm_fn at startup with a Rich-panel version that pauses
the Live spinner, shows a styled diff/preview panel, and reads y/N.
The non-TUI fallback (_cli_confirm) uses plain input() for ask/chat commands.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class PermissionRequest:
    """Describes a pending action that needs user approval."""

    tool_name: str    # e.g. "write_file"
    action:    str    # e.g. "Create file"
    target:    str    # path or command string shown to user
    preview:   str    # diff lines or command to display
    dangerous: bool = False   # True → red border + extra warning


class PermissionManager:
    """
    Singleton gate between tools and user approval.

    Tools call  permission_manager.request(req)  synchronously.
    The TUI replaces  confirm_fn  at startup with a Rich-panel implementation
    that pauses the spinner, shows a panel, and reads user input.
    """

    def __init__(self) -> None:
        self.confirm_fn: Callable[[PermissionRequest], bool] = _cli_confirm

    def request(self, req: PermissionRequest) -> bool:
        """Return True if the user approves, False to cancel."""
        return self.confirm_fn(req)


def _cli_confirm(req: PermissionRequest) -> bool:
    """Fallback for non-TUI usage (ask / chat commands)."""
    danger = "\n  !! DANGEROUS — this action cannot be undone !!" if req.dangerous else ""
    print(f"\n[Permission Required]{danger}")
    print(f"  Tool   : {req.tool_name}")
    print(f"  Action : {req.action}")
    print(f"  Target : {req.target}")
    print(f"  Preview:\n{req.preview}")
    try:
        answer = input("\n  Allow? (y/N): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = "n"
    return answer == "y"


# ── Global singleton ──────────────────────────────────────────────────────────

permission_manager = PermissionManager()
