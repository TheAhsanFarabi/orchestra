<div align="center">
  <img src="assets/logo.png" alt="Orchestra Logo" width="120"/>
  <h1>Orchestra</h1>
  <p><i>A beautifully crafted, privacy-first, local AI agent powered by Ollama.</i></p>
  
  <img src="assets/screen_shot.png" alt="Orchestra Screenshot" width="800"/>
</div>

---

## Overview
Orchestra is a local, terminal-native AI agent designed for developers who want the power of systems like Claude Code or Cursor, but demand **100% privacy** and zero cloud dependencies. 

Powered entirely by [Ollama](https://ollama.com/), Orchestra operates directly on your machine. It can explore your codebase, reason about problems, execute bash commands, manage artifacts, and write code—all within a stunning Terminal User Interface (TUI).

## Features

- **100% Local & Private:** No API keys, no subscriptions, and your code never leaves your machine.
- **Agentic Tool Swarm:** Orchestra doesn't just chat. It uses tools to autonomously read files, list directories, and modify your codebase.
- **Artifact System (`/artifact`):** Ask the AI to draft complex architectural plans or documentation. It generates markdown artifacts that you can view natively and seamlessly inject into your future context.
- **Multi-Session Support (`/session`):** Manage multiple completely isolated chat sessions. Jump between a debugging session and a brainstorming session effortlessly.
- **Context Injection (`/add` & `!cmd`):** Type `/add path/to/file.py` to feed files into context, or prefix host commands with `!` (e.g. `!git status`) to instantly inject command outputs into the AI's memory.
- **Dynamic Theming (`/theme`):** Switch between beautiful UI themes (Dracula, Nord, Monokai, Synthwave) on the fly.
- **Prompt Library (`/prompt`):** Save your most used complex prompts in `~/.orchestra/prompts/` and instantly load them.
- **Ambient Focus:** Toggle background ambient music with `Shift+Tab` to stay in the zone while you and your agent work.
- **Gorgeous TUI:** Built with `prompt_toolkit` and `rich`, featuring custom ASCII art, native syntax highlighting, and an interactive context-window memory map.
- **Permission Gate:** Dangerous actions (like `write_file` or `run_bash`) are caught by a security gate, requiring your explicit `y/n` approval before execution.

---

## Getting Started

### Prerequisites
1. **Python 3.10+** installed on your system.
2. **Ollama** installed and running. ([Download Ollama here](https://ollama.com/download)).

### 1. Download a Model
Orchestra relies on local models. Before running it, pull a model using Ollama.

```bash
# Recommended for standard machines (4B - 8B parameters)
ollama pull qwen3:4b-instruct
ollama pull llama3
```

### 2. Installation
Clone the repository and set up a virtual environment:

```bash
git clone https://github.com/TheAhsanFarabi/orchestra.git
cd orchestra

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install Orchestra and its dependencies
pip install -e .
```

---

## Usage

To start Orchestra, simply run:
```bash
orchestra
```

### Slash Commands
Inside the Orchestra TUI, type `/` to access the command menu. Every command is self-documenting and shows contextual hints:

| Command | Description |
|---|---|
| `/help` | Show the help menu |
| `/session` | Manage isolated chat sessions (new, list, delete, switch) |
| `/artifact` | View and inject AI-generated architectural plans and documents |
| `/add <file>` | Inject a specific file into the AI's context for the next prompt |
| `/prompt <name>` | Load a saved prompt from your personal library |
| `/model <name>` | Switch the active Ollama model |
| `/theme <name>` | Switch the visual theme (e.g. dracula, nord) |
| `/tasks` & `/goal` | View and manage your persistent autonomous task list |
| `/context` | View your context window usage and a visual map of the conversation |

### Terminal Commands
You can execute standard host commands without leaving the chat by prefixing them with `!`.
```bash
you › ! ls -la
you › ! git diff
you › ! npm run test
```
The output is silently added to the AI's context, so your next message can be *"fix the error in those test results"* and Orchestra will know exactly what to do.

---

## 🏗️ Architecture
- **User Space Isolation:** All of your personal sessions, goals, prompts, and skills are saved privately in `~/.orchestra/`. Your data is never mixed with the global source code.
- **Core Loop:** The agent uses an iterative tool-call loop (`loop.py`) with a strict safety cutoff and automatic task enforcement to prevent infinite hallucination loops.
- **UI:** The TUI is powered by `prompt_toolkit` for async history/autocomplete and `rich` for markdown rendering, layout panels, and live spinners.

## Contributing
Contributions are welcome! Whether it's adding new tools (like Git integration), improving the UI, or optimizing the LLM prompts, feel free to open a Pull Request.

## 📄 License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
