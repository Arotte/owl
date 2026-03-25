#!/usr/bin/env python3
"""Convert a Claude conversation JSON export to OpenAI messages format."""

import json
import sys
from pathlib import Path

SENDER_TO_ROLE = {
    "human": "user",
    "assistant": "assistant",
}


def extract_text_parts(content_blocks: list[dict]) -> str:
    """Pull all text-type content blocks into a single string."""
    parts = []
    for block in content_blocks:
        if block.get("type") == "text" and block.get("text"):
            parts.append(block["text"])
    return "\n\n".join(parts)


def extract_tool_calls(content_blocks: list[dict]) -> list[dict]:
    """Convert Claude tool_use blocks to OpenAI function-call format."""
    calls = []
    for block in content_blocks:
        if block.get("type") != "tool_use":
            continue
        calls.append({
            "id": block.get("id", ""),
            "type": "function",
            "function": {
                "name": block.get("name", ""),
                "arguments": json.dumps(block.get("input", {})),
            },
        })
    return calls


def extract_tool_results(content_blocks: list[dict]) -> list[dict]:
    """Convert Claude tool_result blocks to OpenAI tool-response messages."""
    msgs = []
    for block in content_blocks:
        if block.get("type") != "tool_result":
            continue
        text_parts = []
        for inner in block.get("content", []):
            if inner.get("text"):
                text_parts.append(inner["text"])
        msgs.append({
            "role": "tool",
            "tool_call_id": block.get("tool_use_id", ""),
            "content": "\n\n".join(text_parts) if text_parts else "",
        })
    return msgs


def convert(claude_json: dict, *, include_tools: bool = True) -> list[dict]:
    messages: list[dict] = []

    for msg in claude_json.get("chat_messages", []):
        role = SENDER_TO_ROLE.get(msg["sender"])
        if role is None:
            continue

        content_blocks = msg.get("content", [])
        text = extract_text_parts(content_blocks)
        tool_calls = extract_tool_calls(content_blocks) if include_tools else []
        tool_results = extract_tool_results(content_blocks) if include_tools else []

        if tool_results:
            for tr in tool_results:
                messages.append(tr)

        if text or tool_calls:
            entry: dict = {"role": role}
            if text:
                entry["content"] = text
            if tool_calls:
                entry["tool_calls"] = tool_calls
                entry.setdefault("content", None)
            messages.append(entry)

    return messages


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("claude_conversation.json")
    dst = src.with_stem(src.stem + "_openai")

    include_tools = "--no-tools" not in sys.argv

    with open(src) as f:
        claude_data = json.load(f)

    openai_messages = convert(claude_data, include_tools=include_tools)

    with open(dst, "w") as f:
        json.dump(openai_messages, f, indent=2, ensure_ascii=False)

    print(f"Converted {len(openai_messages)} messages → {dst}")


if __name__ == "__main__":
    main()
