"""
The agent loop: the orchestration logic that ties the local LLM to tools.

Flow per turn:
  1. Send full message history + tool schemas to the model.
  2. If the model responds with tool_calls, execute each one locally and
     append the results as `tool` role messages.
  3. Repeat until the model responds with plain content (no tool_calls),
     or we hit MAX_ITERATIONS (safety valve against infinite loops).
"""

import json
from ollama import chat
from .tools import TOOLS, TOOL_REGISTRY

MAX_ITERATIONS = 4

SYSTEM_PROMPT = """You are Orchestra, an autonomous local AI agent running on the user's device.

CRITICAL WORKFLOW:
1. When given a complex request or goal, DO NOT execute it immediately.
2. First, break the request down into smaller, logical steps.
3. Use the `todo_add` tool to add each step to your task list.
4. Execute the tasks one by one using your available file and terminal tools.
5. As you finish a task, use the `todo_done` tool to mark it complete before moving to the next.

You have full access to the file system and terminal. Use your tools to gather information—never guess.
Be concise in your verbal responses, let your tool actions do the work."""


def run_agent(user_input: str, model: str, history: list | None = None, verbose: bool = False, system_prompt: str | None = None, mood: str = "action") -> tuple[str, list]:
    """
    Run the agent loop for one user turn.

    Args:
        user_input: the user's message/question.
        model: Ollama model name (e.g. "qwen2.5:7b").
        history: prior conversation messages to continue from (for multi-turn CLI use).
        verbose: if True, print tool calls/results as they happen.
        system_prompt: Optional override for the system prompt.
        mood: "action" (default, full tools) or "plan" (read-only tools).

    Returns:
        (final_answer_text, updated_history)
    """
    messages = history[:] if history else [{"role": "system", "content": system_prompt or SYSTEM_PROMPT}]
    
    if mood == "plan":
        # Inject an architect prompt override if it's the first turn
        if not history:
            messages[0]["content"] = (system_prompt or SYSTEM_PROMPT) + "\n\nYou are in PLAN mood. Your job is to architect, reason, and create step-by-step plans. Do NOT write code or execute modifying tools."
        active_tools = [t for t in TOOLS if t["function"]["name"] in ["read_file", "list_dir", "grep_search", "view_file"]]
    else:
        active_tools = TOOLS

    messages.append({"role": "user", "content": user_input})

    for iteration in range(MAX_ITERATIONS):
        response = chat(
            model=model,
            messages=messages,
            tools=active_tools if active_tools else None,
        )
        msg = response["message"]

        # Normalize: ollama message may be an object or dict depending on version
        content = msg.get("content", "") if isinstance(msg, dict) else msg.content
        tool_calls = msg.get("tool_calls") if isinstance(msg, dict) else msg.tool_calls

        # Record the assistant's turn (including any tool_calls) in history
        messages.append(msg if isinstance(msg, dict) else msg.model_dump())

        if not tool_calls:
            # Model gave a final answer -- done.
            return content, messages

        # Execute each requested tool call
        for call in tool_calls:
            fn = call["function"] if isinstance(call, dict) else call.function
            name = fn["name"] if isinstance(fn, dict) else fn.name
            args = fn["arguments"] if isinstance(fn, dict) else fn.arguments

            if verbose:
                print(f"  \033[2m[tool] {name}({args})\033[0m")

            tool_fn = TOOL_REGISTRY.get(name)
            if tool_fn is None:
                result = f"Error: unknown tool '{name}'"
            else:
                try:
                    result = tool_fn(**args)
                except TypeError as e:
                    result = f"Error: bad arguments for '{name}': {e}"
                except Exception as e:
                    result = f"Error executing '{name}': {e}"

            if verbose:
                preview = result if len(result) < 300 else result[:300] + "...[truncated for display]"
                print(f"  \033[2m[result] {preview}\033[0m")

            messages.append({
                "role": "tool",
                "content": str(result),
            })

        # loop continues -> model sees tool results and decides next step

    # Safety valve: too many iterations without a final answer
    return (
        "I wasn't able to reach a final answer within the step limit. "
        "Try rephrasing your question or breaking it into smaller parts.",
        messages,
    )
