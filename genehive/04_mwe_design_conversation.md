# Genehive MWE Design Conversation

## Context

After reviewing the full design corpus (files 00–03), we stripped Genehive down to a minimal working example. The goal: an elegant, end-to-end working system with the smallest possible surface area.

## Key Design Decisions

### Execution engine: Cursor CLI (not Claude Code)
Start with Cursor CLI (`cursor-agent --yolo -p`). Budget estimation via `tiktoken`. Claude Code migration is a future option but not needed for v0.

### No eval schedule
The user provides one or more eval commands. For the MWE, all eval commands run every iteration. Scheduling, weighting, and curriculum are deferred to a future Wallace implementation.

### Single island, single worktree
One island = one git worktree = one branch. No population, no crossover (Cupid), no migration (Hermes). Just a hill climber.

### Git is the database — no SQLite, no Fossil
All state lives in git. Mutation reasoning, eval results, and judge verdicts are stored in commit messages using a structured format. There is zero mutable state outside of git history. `gene watch` reads the git log as its single source of truth.

### Reaper is an LLM, not a numeric comparator
Even for v0, the judge is a single LLM call (cheap, fast — not a Cursor CLI session). It receives the new eval output and the previous best eval output (parsed from the last non-reverted commit message) and returns a structured KEEP or CULL verdict with reasoning.

### Config lives in `.genehive/` directory
Not a single `GENEHIVE.md` file. A `.genehive/` directory in the target repo, containing a master YAML config file (editable) and room to grow (prompt templates, etc.).

### `gene watch` is part of the MWE
A CLI command center: simple but polished, informative, with a graph and live status. Built with a rich terminal UI library.

## The Loop

```
1. MUTATE
   Cursor CLI session reads the code + goal + recent git log,
   makes a change, commits with reasoning.

2. EVALUATE
   Shell runs each eval command, captures output.

3. JUDGE
   Single LLM call receives:
   - new eval output
   - previous best eval output (parsed from last non-reverted commit)
   Returns KEEP or CULL + reasoning.

4. ACT
   KEEP → amend commit to append eval results + judgment.
   CULL → amend commit to append eval results + judgment,
          then git revert with reasoning in revert message.

5. BUDGET CHECK
   Estimate cost via tiktoken, stop if exhausted.

6. goto 1
```

## Separation of Concerns

| Step     | What              | How                                            |
|----------|-------------------|------------------------------------------------|
| Mutate   | Change the code   | Cursor CLI — full agent session                |
| Evaluate | Run evals         | Shell subprocess — no LLM                      |
| Judge    | Keep or cull      | Single LLM API call — structured input/output  |

The mutator never judges its own work. The judge never sees the code. The evaluator is just a shell command. Each step is independently testable, replaceable, and debuggable.

## What's Deferred

- Cupid (crossover / breeding)
- Hermes (migration between islands)
- Wallace as an LLM agent (intelligent scheduling, strategy)
- Multi-island topology
- Eval curriculum / staged schedule
- Claude Code as execution engine
- Exact budget tracking (waiting on Claude Code's `total_cost_usd`)
