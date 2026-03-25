#!/usr/bin/env python3
"""Convert an OpenAI-format conversation JSON to readable Markdown."""

import json
import sys
from pathlib import Path


def truncate(text: str, max_chars: int = 500) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n\n*... ({len(text) - max_chars:,} characters truncated)*"


def format_tool_calls(tool_calls: list[dict]) -> str:
    parts = []
    for tc in tool_calls:
        fn = tc.get("function", {})
        name = fn.get("name", "unknown")
        args = fn.get("arguments", "{}")
        try:
            args_pretty = json.dumps(json.loads(args), indent=2)
        except (json.JSONDecodeError, TypeError):
            args_pretty = args
        parts.append(f"**Tool call:** `{name}`\n```json\n{args_pretty}\n```")
    return "\n\n".join(parts)


def convert(messages: list[dict], *, include_tool_results: bool = False) -> str:
    lines: list[str] = []
    turn = 0

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content") or ""
        tool_calls = msg.get("tool_calls", [])

        if role == "tool":
            if include_tool_results:
                tool_id = msg.get("tool_call_id", "")
                lines.append(f"> **Tool result** (`{tool_id}`):\n>")
                for line in truncate(content, 300).splitlines():
                    lines.append(f"> {line}")
                lines.append("")
            continue

        if role == "user":
            turn += 1
            lines.append(f"---\n\n### Turn {turn}\n")
            lines.append(f"**User:**\n\n{content}\n")

        elif role == "assistant":
            text = content.strip() if content else ""
            if tool_calls:
                lines.append(format_tool_calls(tool_calls))
                lines.append("")
            if text:
                lines.append(f"**Assistant:**\n\n{text}\n")

    return "\n".join(lines)


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("claude_conversation_openai.json")
    dst = src.with_suffix(".md")

    include_tool_results = "--tools" in sys.argv

    with open(src) as f:
        messages = json.load(f)

    md = convert(messages, include_tool_results=include_tool_results)

    with open(dst, "w") as f:
        f.write(md)

    msg_count = sum(1 for m in messages if m.get("role") in ("user", "assistant"))
    print(f"Converted {msg_count} messages → {dst}")


if __name__ == "__main__":
    main()
