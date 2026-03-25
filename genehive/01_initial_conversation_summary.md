Here's a summary of the conversation:

---

## Conversation Summary

This is a design conversation that builds **Genehive** — a general-purpose framework for autonomous codebase evolution using AI agents — from first principles, starting from Karpathy's `autoresearch` project.

### Phase 1: Naming (~first third)

The conversation starts with the user sharing Karpathy's [autoresearch](https://github.com/karpathy/autoresearch) repo and asking for a catchy name. Dozens of candidates are explored across themes: evolution (Darwinize), grinding (Grindstone), fermentation (Ferment), dreaming, and hive minds. The final winner is **Genehive** — gene pool meets hive mind.

### Phase 2: Theory and Architecture (middle third)

The user and Claude dig into the relationship between autoresearch, genetic algorithms, and Neural Architecture Search (NAS). Key insight: autoresearch is essentially a hill climber with an LLM as the mutation operator — it's missing **crossover** (breeding two solutions). Research on evolutionary graph theory reveals the **island model** (isolated populations with rare migration) is optimal for rugged fitness landscapes.

This leads to the design of a cast of named agents:

| Agent | Role |
|---|---|
| **Wallace** | Orchestrator — selection, population management, all decisions |
| **Mendel** | Mutator — edits the genome one change at a time |
| **Cupid** | Crossover — breeds two parent genomes into a child |
| **Reaper** | Evaluator — scores fitness, culls the weak |
| **Fossil** | Historian — passive log of all experiments (never signals, just records) |
| **Hermes** | Migrator — carries fittest individuals between islands |

Key vocabulary: **genome** (the code being optimised), **phenotype** (the running result), **p0** (root commit).

### Phase 3: Eval Schedule Design

A multi-stage eval curriculum is designed, inspired by curriculum learning in deep learning:

- **Stage 0**: Smoke test (does it run?)
- **Stage 1**: Proxy sprint (small noisy eval set, fast iteration)
- **Stage 2**: Capability unlocks (narrow high-fidelity evals, added sequentially)
- **Stage 3**: Blended pressure (multi-objective weighted scoring, Pareto frontier)
- **Stage 4**: Integration oracle (expensive full benchmark, top-K only)
- **Stage 5**: Human loop (optional)

Stage transitions are triggered by convergence (Wallace detects it by reading Fossil), not by time.

### Phase 4: Implementation Design (final third)

The conversation shifts to practical implementation:

- **Execution engine**: Cursor CLI in headless mode (`cursor-agent --yolo -p`), not custom agents
- **Stack**: Python + SQLite + git worktrees
- **Budget tracking**: Estimate-based via `tiktoken` (Cursor CLI doesn't expose per-call costs)
- **Worktrees**: Stored in `~/.genehive/workspaces/`, not inside the user's repo

The user defines the desired CLI UX:

```
gene init [path]    # Interactive setup, creates GENEHIVE.md config
gene check [path]   # Validate eval command works
gene start [path]   # Start evolution as background daemon
gene watch [path]   # TUI dashboard for real-time monitoring
gene stop [path]    # Graceful shutdown + grand tournament
gene status [path]  # One-line summary
gene report [path]  # Full Fossil log export
```

Key UX principles: zero friction (`pip install` + `gene init` + `gene start`), budget warnings by default, `GENEHIVE.md` as the single git-committable config file.

The final refinement simplifies evals: the developer provides only eval commands (no thresholds, no weights, no stages). Reaper becomes an LLM agent that interprets raw eval output. Wallace manages the schedule internally. The conversation ends with the single-island case crystallised: the developer provides eval commands, Genehive handles everything else.