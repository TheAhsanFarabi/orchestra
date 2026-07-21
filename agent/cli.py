"""
Orchestra CLI entrypoint.

Usage:
    python -m agent.cli              # launch the rich TUI  (default)
    python -m agent.cli tui          # launch the rich TUI  (explicit)
    python -m agent.cli ask "..."    # one-shot question
    python -m agent.cli chat         # plain multi-turn REPL
    python -m agent.cli tui --model llama3.1:8b --verbose
"""

import typer
from .loop import run_agent
from .tui import run_tui
from .config import Config
from .skills import skills_manager

app = typer.Typer(
    add_completion=False,
    help="Orchestra — a local, privacy-first AI agent powered by Ollama.",
    invoke_without_command=True,
)




@app.callback(invoke_without_command=True)
def default(ctx: typer.Context) -> None:
    """Launch the rich TUI when no subcommand is given."""
    if ctx.invoked_subcommand is None:
        run_tui()


@app.command()
def tui(
    model:   str  = typer.Option(None,  "--model",   "-m", help="Ollama model to use."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show tool calls and results."),
) -> None:
    """Launch the rich interactive TUI (default when no subcommand is given)."""
    run_tui(model=model, verbose=verbose)


@app.command()
def ask(
    question: str  = typer.Argument(...,   help="The question or task for the agent."),
    model:    str  = typer.Option(None, "--model", "-m", help="Ollama model to use."),
    verbose:  bool = typer.Option(False, "--verbose", "-v", help="Show tool calls and results."),
) -> None:
    """Ask the agent a single one-shot question."""
    cfg = Config.load()
    effective_model = model or cfg.model
    skills_manager.load()
    prompt = skills_manager.build_system_prompt()
    answer, _ = run_agent(question, model=effective_model, verbose=verbose, system_prompt=prompt)
    typer.echo(f"\n{answer}\n")


@app.command()
def chat(
    model:   str  = typer.Option(None, "--model", "-m", help="Ollama model to use."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show tool calls and results."),
) -> None:
    """Start a plain multi-turn chat session (no rich TUI)."""
    cfg = Config.load()
    effective_model = model or cfg.model
    skills_manager.load()
    prompt = skills_manager.build_system_prompt()
    typer.echo(f"Orchestra ready (model: {effective_model}). Type 'exit' or Ctrl+C to quit.\n")
    history = None

    while True:
        try:
            user_input = typer.prompt("you")
        except (EOFError, KeyboardInterrupt):
            typer.echo("\nGoodbye.")
            raise typer.Exit()

        if user_input.strip().lower() in {"exit", "quit"}:
            typer.echo("Goodbye.")
            raise typer.Exit()

        answer, history = run_agent(user_input, model=effective_model, history=history, verbose=verbose, system_prompt=prompt)
        typer.echo(f"orchestra: {answer}\n")


if __name__ == "__main__":
    app()
