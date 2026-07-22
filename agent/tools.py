"""
Tools available to the agent.

Each tool is a plain Python function with a docstring and type hints.
ollama-python inspects these to auto-generate the JSON schema the model sees,
so keep the docstring and type hints accurate and descriptive.

Read-only tools (no approval):
    read_file, list_directory, search_files, tasks_list

Write tools (yellow-border approval panel):
    write_file, append_file, create_directory, move_file

Dangerous tools (red-border approval panel):
    delete_path, run_bash

Task tools (no approval, write to ~/.orchestra/tasks.json):
    tasks_add, tasks_done, tasks_list
"""

from __future__ import annotations

import difflib
import subprocess
from pathlib import Path

# Optional: restrict filesystem access to a root directory.
# Set to None to allow anywhere the OS user can access.
SAFE_ROOT: Path | None = None


# ── Internal helpers ──────────────────────────────────────────────────────────

def _resolve(path: str) -> tuple[Path, str | None]:
    """
    Resolve a path string to an absolute Path.
    Returns (resolved_path, error_string_or_None).
    """
    try:
        p = Path(path).expanduser().resolve()
    except Exception as e:
        return Path("."), f"Error: invalid path '{path}': {e}"

    if SAFE_ROOT is not None:
        root = Path(SAFE_ROOT).expanduser().resolve()
        if root not in p.parents and p != root:
            return p, f"Error: access denied — '{path}' is outside the allowed directory."

    return p, None


def _make_diff(old_lines: list[str], new_lines: list[str], label: str = "") -> str:
    """Return a unified-diff-style string (+/-/ ) for permission panel preview."""
    diff = list(difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"existing {label}" if old_lines else "(new file)",
        tofile=label,
        lineterm="",
    ))
    if not diff:
        return "(no changes)"
    out = "\n".join(diff[:30])
    if len(diff) > 30:
        out += f"\n... ({len(diff) - 30} more lines)"
    return out


# ── Read-only tools ───────────────────────────────────────────────────────────

def read_file(path: str) -> str:
    """Read and return the text contents of a file on disk.

    Args:
        path: Absolute or relative path to a text file (e.g. notes.md, report.txt).

    Returns:
        The file's contents as a string, or an error message if it can't be read.
    """
    try:
        p, err = _resolve(path)
        if err:
            return err
        if not p.exists():
            return f"Error: file not found: {path}"
        if p.is_dir():
            return f"Error: '{path}' is a directory, not a file."
        max_bytes = 50_000
        data = p.read_text(errors="replace")
        if len(data) > max_bytes:
            data = data[:max_bytes] + f"\n\n...[truncated, file has {len(data)} chars total]"
        return data
    except Exception as e:
        return f"Error reading file: {e}"


def list_directory(path: str = ".") -> str:
    """List files and subdirectories inside a given directory.

    Args:
        path: Directory path to list. Defaults to the current directory.

    Returns:
        A newline-separated list of entries, or an error message.
    """
    try:
        p, err = _resolve(path)
        if err:
            return err
        if not p.exists():
            return f"Error: path not found: {path}"
        if not p.is_dir():
            return f"Error: '{path}' is not a directory."
        entries = sorted(p.iterdir())
        if not entries:
            return "(empty directory)"
        return "\n".join(f"{e.name}/" if e.is_dir() else e.name for e in entries)
    except Exception as e:
        return f"Error listing directory: {e}"


def search_files(pattern: str, path: str = ".", glob: str = "*") -> str:
    """Search for a text pattern inside files in a directory.

    Args:
        pattern: Text string to search for (case-insensitive).
        path:    Directory to search in. Defaults to current directory.
        glob:    File name glob filter (e.g. '*.py', '*.md'). Default: all files.

    Returns:
        Matching lines as 'filename:linenum: content', or a no-results message.
    """
    try:
        p, err = _resolve(path)
        if err:
            return err
        if not p.is_dir():
            return f"Error: '{path}' is not a directory."
        results: list[str] = []
        needle = pattern.lower()
        for file in sorted(p.rglob(glob)):
            if not file.is_file():
                continue
            try:
                for lineno, line in enumerate(file.read_text(errors="replace").splitlines(), 1):
                    if needle in line.lower():
                        rel = file.relative_to(p)
                        results.append(f"{rel}:{lineno}: {line.rstrip()}")
                        if len(results) >= 200:
                            results.append("...[truncated at 200 results]")
                            return "\n".join(results)
            except Exception:
                continue
        return "\n".join(results) if results else f"No matches for '{pattern}' in {path}"
    except Exception as e:
        return f"Error searching: {e}"


# ── Write tools (yellow-border approval) ──────────────────────────────────────

def write_file(path: str, content: str) -> str:
    """Create or overwrite a file with the given text content.

    Creates any missing parent directories automatically.

    Args:
        path:    Path to the file to write (absolute or relative).
        content: Full text content to write to the file.

    Returns:
        Success message or error string.
    """
    from .permissions import permission_manager, PermissionRequest
    try:
        p, err = _resolve(path)
        if err:
            return err
        old_lines = p.read_text(errors="replace").splitlines() if p.exists() else []
        new_lines = content.splitlines()
        preview   = _make_diff(old_lines, new_lines, p.name)
        req = PermissionRequest(
            tool_name = "write_file",
            action    = "Overwrite file" if p.exists() else "Create file",
            target    = str(p),
            preview   = preview,
            dangerous = False,
        )
        if not permission_manager.request(req):
            return "Action cancelled by user."
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return f"OK: wrote {len(content)} chars to '{p}'"
    except Exception as e:
        return f"Error writing file: {e}"


def append_file(path: str, content: str) -> str:
    """Append text to the end of a file, creating it if it doesn't exist.

    Args:
        path:    Path to the file to append to.
        content: Text to append at the end.

    Returns:
        Success message or error string.
    """
    from .permissions import permission_manager, PermissionRequest
    try:
        p, err = _resolve(path)
        if err:
            return err
        preview = f"(appending {len(content)} chars to '{p.name}')\n"
        preview += "\n".join("+ " + ln for ln in content.splitlines()[:20])
        req = PermissionRequest(
            tool_name = "append_file",
            action    = "Append to file",
            target    = str(p),
            preview   = preview,
            dangerous = False,
        )
        if not permission_manager.request(req):
            return "Action cancelled by user."
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as f:
            f.write(content)
        return f"OK: appended {len(content)} chars to '{p}'"
    except Exception as e:
        return f"Error appending to file: {e}"


def create_directory(path: str) -> str:
    """Create a new directory, including any missing parent directories.

    Args:
        path: Path of the directory to create.

    Returns:
        Success message or error string.
    """
    from .permissions import permission_manager, PermissionRequest
    try:
        p, err = _resolve(path)
        if err:
            return err
        if p.exists():
            return f"OK: Directory already exists: '{p}'"
        req = PermissionRequest(
            tool_name = "create_directory",
            action    = "Create directory",
            target    = str(p),
            preview   = f"+ {p}/",
            dangerous = False,
        )
        if not permission_manager.request(req):
            return "Action cancelled by user."
        p.mkdir(parents=True, exist_ok=True)
        return f"OK: created directory '{p}'"
    except Exception as e:
        return f"Error creating directory: {e}"


def move_file(source: str, destination: str) -> str:
    """Move or rename a file or directory.

    Args:
        source:      Current path of the file or directory.
        destination: Target path after the move or rename.

    Returns:
        Success message or error string.
    """
    from .permissions import permission_manager, PermissionRequest
    import shutil
    try:
        src, err = _resolve(source)
        if err:
            return err
        dst, err = _resolve(destination)
        if err:
            return err
        if not src.exists():
            return f"Error: source not found: '{source}'"
        req = PermissionRequest(
            tool_name = "move_file",
            action    = "Move / rename",
            target    = f"{src}  →  {dst}",
            preview   = f"- {src}\n+ {dst}",
            dangerous = False,
        )
        if not permission_manager.request(req):
            return "Action cancelled by user."
        shutil.move(str(src), str(dst))
        return f"OK: moved '{src}' → '{dst}'"
    except Exception as e:
        return f"Error moving: {e}"


# ── Dangerous tools (red-border approval) ─────────────────────────────────────

def delete_path(path: str) -> str:
    """Permanently delete a file or entire directory tree. Cannot be undone.

    Args:
        path: Path to the file or directory to delete.

    Returns:
        Success message or error string.
    """
    from .permissions import permission_manager, PermissionRequest
    import shutil
    try:
        p, err = _resolve(path)
        if err:
            return err
        if not p.exists():
            return f"Error: path not found: '{path}'"
        kind = "directory tree" if p.is_dir() else "file"
        req  = PermissionRequest(
            tool_name = "delete_path",
            action    = f"Permanently delete {kind}",
            target    = str(p),
            preview   = f"- {p}  ({kind}, cannot be undone)",
            dangerous = True,
        )
        if not permission_manager.request(req):
            return "Action cancelled by user."
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        return f"OK: deleted '{p}'"
    except Exception as e:
        return f"Error deleting: {e}"


def run_bash(command: str, cwd: str = ".") -> str:
    """Execute a bash shell command and return combined stdout + stderr.

    Output is capped at 10,000 characters to protect the context window.

    Args:
        command: The shell command to run.
        cwd:     Working directory. Defaults to current directory.

    Returns:
        Combined stdout and stderr, or an error message.
    """
    from .permissions import permission_manager, PermissionRequest
    try:
        work_dir = Path(cwd).expanduser().resolve()
        req = PermissionRequest(
            tool_name = "run_bash",
            action    = "Execute shell command",
            target    = str(work_dir),
            preview   = f"$ {command}",
            dangerous = True,
        )
        if not permission_manager.request(req):
            return "Action cancelled by user."
        result = subprocess.run(
            command,
            shell=True,
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            timeout=60,
        )
        out = (result.stdout + result.stderr).strip()
        if not out:
            out = f"(exit code {result.returncode}, no output)"
        if len(out) > 10_000:
            out = out[:10_000] + "\n…[truncated at 10,000 chars]"
        return out
    except subprocess.TimeoutExpired:
        return "Error: command timed out after 60 seconds."
    except Exception as e:
        return f"Error running bash: {e}"


# ── Task tool shims ───────────────────────────────────────────────────────────
# Imported here so they live in TOOL_REGISTRY alongside the file tools.

from .tasks import tasks_add, tasks_done, tasks_list  # noqa: E402


# ── External APIs ─────────────────────────────────────────────────────────────

def search_web(query: str, max_results: int = 5) -> str:
    """
    Search the web using DuckDuckGo.
    Returns snippets of the top search results. Useful for finding up-to-date real world information.
    """
    try:
        from ddgs import DDGS
        results = DDGS().text(query, max_results=max_results)
        if not results:
            return "No results found."
        
        output = []
        for i, res in enumerate(results, 1):
            title = res.get("title", "No Title")
            href = res.get("href", "")
            body = res.get("body", "")
            output.append(f"{i}. {title}\nURL: {href}\nSnippet: {body}\n")
            
        return "\n".join(output)
    except ImportError:
        return "Error: ddgs package is not installed."
    except Exception as e:
        return f"Web search error: {e}"

def search_arxiv(query: str, max_results: int = 3) -> str:
    """
    Search the ArXiv database for academic papers.
    Returns the title, authors, published date, and abstract for the top papers.
    """
    try:
        import arxiv
        client = arxiv.Client()
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.Relevance
        )
        
        output = []
        for i, paper in enumerate(client.results(search), 1):
            authors = ", ".join(a.name for a in paper.authors)
            output.append(
                f"{i}. {paper.title}\n"
                f"Authors: {authors}\n"
                f"Published: {paper.published.date()}\n"
                f"URL: {paper.entry_id}\n"
                f"Abstract: {paper.summary}\n"
            )
            
        if not output:
            return "No papers found."
        return "\n".join(output)
    except ImportError:
        return "Error: arxiv package is not installed."
    except Exception as e:
        return f"ArXiv search error: {e}"

def read_url(url: str) -> str:
    """
    Fetch and extract the main text content of a web page by its URL.
    Useful for reading full articles or documentation pages found via search_web.
    """
    try:
        import requests
        from bs4 import BeautifulSoup
        
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Remove script and style elements
        for script in soup(["script", "style", "nav", "footer", "header"]):
            script.extract()
            
        text = soup.get_text(separator="\n")
        
        # Clean up whitespace
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = "\n".join(chunk for chunk in chunks if chunk)
        
        # Truncate if too long
        if len(text) > 15000:
            text = text[:15000] + "\n...[Content truncated due to length]"
            
        return text
    except ImportError:
        return "Error: requests or beautifulsoup4 package is not installed."
    except Exception as e:
        return f"Failed to read URL: {e}"

def create_artifact(name: str, content: str) -> str:
    """
    Creates a Markdown artifact file for plans, designs, or research.
    Ensure 'name' is alphanumeric with underscores (e.g., 'database_schema').
    IMPORTANT: When creating an artifact, YOU MUST write a highly detailed, 
    comprehensive, and long document. Do not output short summaries.
    """
    import os
    from pathlib import Path
    
    artifact_dir = Path.home() / ".orchestra" / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    
    if not name.endswith(".md"):
        name += ".md"
        
    file_path = artifact_dir / name
    file_path.write_text(content, encoding="utf-8")
    return f"Artifact created successfully: {file_path}. The user can view it with /artifact view {name.replace('.md', '')}"

# ── Registry ──────────────────────────────────────────────────────────────────

TOOL_REGISTRY: dict[str, object] = {
    # Read-only
    "read_file":        read_file,
    "list_directory":   list_directory,
    "search_files":     search_files,
    # Write (yellow-border approval)
    "write_file":       write_file,
    "append_file":      append_file,
    "create_directory": create_directory,
    "move_file":        move_file,
    # Dangerous (red-border approval)
    "delete_path":      delete_path,
    "run_bash":         run_bash,
    # Task (no approval)
    "tasks_add":         tasks_add,
    "tasks_done":        tasks_done,
    "tasks_list":        tasks_list,
    # External API (read-only)
    "search_web":        search_web,
    "search_arxiv":      search_arxiv,
    "read_url":          read_url,
    "create_artifact":   create_artifact,
}

# List passed straight to ollama's tools= param.
TOOLS = list(TOOL_REGISTRY.values())
