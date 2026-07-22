from pathlib import Path

PROMPTS_DIR = Path.home() / ".orchestra" / "prompts"

DEFAULT_PROMPTS = {
    "code_review": "You are an expert software architect and security auditor. Review the provided code thoroughly. Suggest improvements for modularity, performance, and readability. Point out any security vulnerabilities or edge cases that are not handled. Be concise and provide code snippets for your solutions.",
    "explain": "Explain the following code, concept, or error message as if I am a beginner. Use analogies if helpful. Break it down step-by-step and keep the tone encouraging and easy to understand.",
    "refactor": "Refactor the provided code. Your goals are to improve readability, reduce complexity, and follow modern best practices. Ensure that the original functionality remains exactly the same. Provide a brief summary of the changes you made before presenting the new code."
}

def init_prompts() -> None:
    """Initialize the prompts directory and create default templates if it's empty/missing."""
    if not PROMPTS_DIR.exists():
        PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
        
        for name, content in DEFAULT_PROMPTS.items():
            file_path = PROMPTS_DIR / f"{name}.txt"
            file_path.write_text(content, encoding="utf-8")

def list_prompts() -> dict[str, str]:
    """Returns a dictionary mapping prompt name to its content."""
    if not PROMPTS_DIR.exists():
        return {}
    
    prompts = {}
    for file_path in PROMPTS_DIR.glob("*.txt"):
        name = file_path.stem
        try:
            content = file_path.read_text(encoding="utf-8")
            prompts[name] = content
        except Exception:
            continue
    
    for file_path in PROMPTS_DIR.glob("*.md"):
        name = file_path.stem
        try:
            content = file_path.read_text(encoding="utf-8")
            prompts[name] = content
        except Exception:
            continue
            
    return prompts

def get_prompt(name: str) -> str | None:
    """Get the content of a specific prompt by name."""
    prompts = list_prompts()
    return prompts.get(name)
