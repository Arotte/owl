# Budget Control for Genehive: Research Summary

## Context

The Genehive design conversation identified budget tracking as a key concern: when running autonomous agents overnight (potentially hundreds of invocations), you need precise cost control. The original design proposed `tiktoken`-based estimation because the planned execution engine (Cursor CLI in headless mode) doesn't expose per-call token costs.

This conversation investigated whether that's still the best approach.

## Key Finding: Cursor CLI Does Not Expose Token Usage

The Cursor CLI (`cursor-agent --yolo -p`) supports `--output-format json` and `--output-format stream-json`, but the output metadata is limited to:

- `duration_ms` / `duration_api_ms` (wall-clock and API time)
- `session_id`
- `result` (full assistant text)
- Tool call start/complete events

**No token counts, no cost data, no model-per-turn breakdown.** This is a known gap — there are open community feature requests for per-request token/cost display, but nothing is planned.

### Other Cursor mechanisms considered

- **Usage Dashboard (web UI):** Aggregate spend per billing period only, no per-session granularity.
- **Admin API:** Teams/enterprise only. Provides audit logs and member info, not per-session token consumption.
- **Analytics API:** Enterprise only, sparse documentation, unclear if per-session data is available.
- **Cloud Agents API:** Lets you launch full Cursor agents against GitHub repos via HTTP. Useful for orchestration, but also returns no token usage data. Also requires GitHub (no local worktrees).

## Alternatives Evaluated

### Option A: `tiktoken` estimation (original plan)

Count tokens in prompts and responses using `tiktoken`. Can't account for Cursor's internal system prompt or context injection, so it's a lower bound. Viable but imprecise.

### Option B: Raw model API calls with custom tool loop

Call Anthropic/OpenAI APIs directly, implement your own file read/write/shell tool loop (~100-150 LOC). The API response `usage` object gives exact token counts per call. Full budget control, but you lose Cursor's agent loop and codebase indexing, and you have to build/maintain the tool-use loop yourself.

### Option C: Claude Code (the winner)

Claude Code (`claude -p`) gives you both:

1. **A full built-in agent loop** — file read, edit, shell commands, non-interactive, just like `cursor-agent --yolo -p`.
2. **Exact token and cost data** — the JSON output includes `total_cost_usd`, per-model `modelUsage` breakdowns, and full `usage` objects with `input_tokens`, `output_tokens`, `cache_read_input_tokens`, and `cache_creation_input_tokens`.

#### Claude Code headless invocation

```bash
claude -p "Apply this mutation to train.py: ..." \
  --allowedTools "Bash,Read,Edit" \
  --output-format json \
  --bare
```

#### JSON result includes cost data

```json
{
  "type": "result",
  "total_cost_usd": 0.0347,
  "usage": {
    "input_tokens": 12847,
    "output_tokens": 1023,
    "cache_read_input_tokens": 3906,
    "cache_creation_input_tokens": 8941
  },
  "modelUsage": {
    "claude-sonnet-4-20250514": {
      "costUSD": 0.0347,
      "inputTokens": 12847,
      "outputTokens": 1023
    }
  },
  "session_id": "uuid",
  "duration_ms": 5234
}
```

#### Python SDK for programmatic control

```python
from claude_agent_sdk import query, ResultMessage

total_spend = 0.0
budget = 10.0

async for message in query(
    prompt="Mutate train.py to improve val_bpb...",
    allowed_tools=["Bash", "Read", "Edit"],
):
    if isinstance(message, ResultMessage):
        total_spend += message.total_cost_usd or 0
        if total_spend >= budget:
            raise BudgetExhausted(f"${total_spend:.2f} / ${budget:.2f}")
```

#### Additional features

- **Session continuity** via `--resume <session_id>` — agents can maintain context across multi-step workflows.
- **`--bare` mode** — deterministic behavior, no local config leakage. Recommended for automation.
- **`--allowedTools`** — fine-grained tool permissions (e.g. `Bash(git diff *)` for prefix matching).

## Updated Design Recommendation

Replace the two original lines:

> Execution engine: Cursor CLI in headless mode (`cursor-agent --yolo -p`)
> Budget tracking: Estimate-based via `tiktoken`

With:

> Execution engine: Claude Code in headless mode (`claude -p --bare --allowedTools "Bash,Read,Edit"`)
> Budget tracking: Exact, from `total_cost_usd` in JSON output

The only trade-off is losing Cursor's codebase indexing, which is irrelevant when the genome is a single file (`train.py`) with a single instruction file (`program.md`).
