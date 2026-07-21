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
from typing import Callable, Any
from ollama import chat
from .tools import TOOLS, TOOL_REGISTRY
from .tasks import TaskList

MAX_ITERATIONS = 12
MAX_TOOL_RETRIES = 1

# Tools allowed in Plan mood (non-destructive only)
PLAN_TOOLS = {"read_file", "list_directory", "search_files", "tasks_add", "tasks_list"}


def _trim_context(messages: list[dict], context_limit: int = 32_768) -> list[dict]:
    """
    Trim old messages if estimated tokens exceed the context limit.
    Always keeps the system prompt (messages[0]) and recent messages.
    """
    estimated = sum(len(str(m.get("content", ""))) // 4 for m in messages)
    if estimated <= context_limit:
        return messages

    # Keep system prompt + as many recent messages as we can fit
    system = messages[0]
    system_tokens = len(str(system.get("content", ""))) // 4
    budget = context_limit - system_tokens
    
    trimmed = []
    for msg in reversed(messages[1:]):
        msg_tokens = len(str(msg.get("content", ""))) // 4
        if budget - msg_tokens < 0:
            break
        trimmed.insert(0, msg)
        budget -= msg_tokens

    return [system] + trimmed


def run_agent(
    user_input: str,
    model: str,
    system_prompt: str,
    history: list | None = None,
    verbose: bool = False,
    mood: str = "action",
    context_limit: int = 32_768,
    on_tool_call: Callable[[str, dict, str], None] | None = None,
) -> tuple[str, list]:
    """
    Run the agent loop for one user turn.

    Args:
        user_input: the user's message/question.
        model: Ollama model name (e.g. "qwen2.5:1.5b").
        system_prompt: The system prompt (from skills_manager).
        history: prior conversation messages to continue from.
        verbose: if True, print tool calls/results as they happen.
        mood: "action" (default, full tools) or "plan" (read-only tools).
        context_limit: max estimated tokens before trimming old messages.
        on_tool_call: callback(tool_name, args, result) for live UI updates.

    Returns:
        (final_answer_text, updated_history)
    """
    effective_prompt = system_prompt

    # Always ensure the system prompt is present and up-to-date
    messages = history[:] if history else []
    if not messages or messages[0].get("role") != "system":
        messages.insert(0, {"role": "system", "content": effective_prompt})
    else:
        messages[0]["content"] = effective_prompt

    if mood == "plan":
        # Inject an architect prompt override
        messages[0]["content"] = effective_prompt + "\n\nYou are in PLAN mood. Your job is to architect, reason, and create step-by-step plans. Do NOT write code or execute modifying tools."
        active_tools = [t for t in TOOLS if getattr(t, "__name__", "") in PLAN_TOOLS]
    elif mood == "chat":
        messages[0]["content"] = effective_prompt + "\n\nYou are in CHAT mood. You do not have access to any tools. Respond quickly and directly to the user."
        active_tools = []
    else:
        active_tools = TOOLS

    messages.append({"role": "user", "content": user_input})

    # Trim context if it exceeds the limit
    messages = _trim_context(messages, context_limit)

    # Load current tasks state to see if we are already mid-plan
    has_pending_tasks = any(i.status == "pending" for i in TaskList.load().items)

    for iteration in range(MAX_ITERATIONS):
        current_tools = active_tools
        # Force planning ONLY if we are in action mood, it's the very first iteration,
        # AND there are no pending tasks (meaning it's a brand new goal).
        if mood == "action" and iteration == 0 and not has_pending_tasks:
            current_tools = [t for t in active_tools if getattr(t, "__name__", "") in PLAN_TOOLS]
            
            # Inject a silent reminder for this turn only so the LLM doesn't stop and wait
            if len(messages) > 0 and messages[-1]["role"] == "user":
                messages[-1]["content"] += "\n\n(System Note: You must use tasks_add to break this down now. Do not return plain text only. You must output tool calls.)"
        elif mood == "action" and iteration == 0 and has_pending_tasks:
            if len(messages) > 0 and messages[-1]["role"] == "user":
                messages[-1]["content"] += "\n\n(System Note: You have pending tasks. You MUST use `tasks_done` when a step is finished, and `tasks_list` to check your remaining tasks. Do not respond with plain text without addressing the tasks!)"

        response = chat(
            model=model,
            messages=messages,
            tools=current_tools if current_tools else None,
        )
        msg = response["message"]

        # Normalize: ollama message may be an object or dict depending on version
        content = msg.get("content", "") if isinstance(msg, dict) else msg.content
        tool_calls = msg.get("tool_calls") if isinstance(msg, dict) else msg.tool_calls

        # Record the assistant's turn (including any tool_calls) in history
        messages.append(msg if isinstance(msg, dict) else msg.model_dump())

        if not tool_calls:
            if mood == "action" and iteration < MAX_ITERATIONS - 1:
                t_list = TaskList.load()
                if any(i.status == "pending" for i in t_list.items):
                    prev_user = messages[-2] if len(messages) >= 2 else {}
                    if not ("System Auto-Intercept:" in str(prev_user.get("content", ""))):
                        pending_ids = [i.id for i in t_list.items if i.status == "pending"]
                        intercept = f"System Auto-Intercept: You returned a text response but there are still pending tasks {pending_ids}. If you just finished a step, you MUST call `tasks_done` with the correct ID. Do not narrate your intentions in text—actually output the tool call."
                        messages.append({"role": "user", "content": intercept})
                        continue

            # Model gave a final answer -- done.
            return content, messages

        # Execute each requested tool call
        for call in tool_calls:
            fn = call["function"] if isinstance(call, dict) else call.function
            name = fn["name"] if isinstance(fn, dict) else fn.name
            args = fn["arguments"] if isinstance(fn, dict) else fn.arguments

            if verbose:
                print(f"  \033[2m[tool] {name}({args})\033[0m")

            allowed_names = [getattr(t, "__name__", "") for t in current_tools]
            if name not in allowed_names:
                result = f"Error: Tool '{name}' is not allowed in the current phase. Please yield and use it in the next turn."
                tool_fn = None
            else:
                tool_fn = TOOL_REGISTRY.get(name)
                
            if tool_fn is None and name in allowed_names:
                result = f"Error: unknown tool '{name}'"
            elif tool_fn is not None:
                # Retry logic for failed tool calls
                for attempt in range(MAX_TOOL_RETRIES + 1):
                    try:
                        result = tool_fn(**args)
                        break
                    except TypeError as e:
                        result = f"Error: bad arguments for '{name}': {e}"
                        break  # Don't retry argument errors
                    except Exception as e:
                        if attempt == MAX_TOOL_RETRIES:
                            result = f"Error executing '{name}' (after {attempt + 1} attempts): {e}"

            if verbose:
                preview = result if len(result) < 300 else result[:300] + "...[truncated for display]"
                print(f"  \033[2m[result] {preview}\033[0m")

            # Notify the TUI so it can show live tool activity
            if on_tool_call:
                on_tool_call(name, args, result)

            result_str = str(result)
            if mood == "action" and name not in ("tasks_add", "tasks_done", "tasks_list"):
                t_list = TaskList.load()
                pending_ids = [i.id for i in t_list.items if i.status == "pending"]
                if pending_ids:
                    result_str += f"\n\n(System Note: You have pending tasks {pending_ids}. If you just completed one, you MUST call `tasks_done` immediately. Do not speak to the user until you mark it done!)"

            messages.append({
                "role": "tool",
                "content": result_str,
            })

        # loop continues -> model sees tool results and decides next step

    # Safety valve: too many iterations without a final answer
    return (
        "I wasn't able to reach a final answer within the step limit. "
        "Try rephrasing your question or breaking it into smaller parts.",
        messages,
    )
