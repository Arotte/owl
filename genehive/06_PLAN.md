# Genehive — MWE Build Plan

> A general-purpose framework for autonomous codebase evolution. Point it at a
> git repo, give it a goal and one or more eval commands, and it runs a closed
> loop: mutate → evaluate → judge → keep or revert → repeat.
>
> This document is the concrete build plan for **v0 (the MWE)**. It is the
> crystallisation of files `00`–`05` in this folder. Everything deferred to
> post-MWE is listed in [§10 Deferred](#10-deferred).

---

## 1. Scope of v0

A single-island hill climber. One repo, one git worktree (in
`~/.genehive/worktrees/`, see §3a), one dedicated branch
(`genehive/main`), one lineage. The user's own working tree is never
touched while Genehive runs. The loop is:

```
MUTATE  → Claude Code full agent session edits the code and commits
EVALUATE → shell runs each eval command, captures stdout/stderr/exit
JUDGE   → one cheap structured LLM call: KEEP or CULL (never sees the code)
ACT     → on KEEP, amend commit with eval+verdict
          on CULL, amend then `git revert` with reasoning
BUDGET  → exact from `total_cost_usd`; stop when exhausted
```

What makes v0 sharp:

- **Git is the database.** No SQLite, no sidecar state file. Mutation
  reasoning, eval output, and judge verdicts all live in commit messages in
  a structured block. `gene watch` reads the git log as its single source
  of truth.
- **Three cleanly separated concerns.** The mutator never judges its own
  work. The judge never sees the code. The evaluator is just `subprocess`.
  Each step is independently testable and replaceable.
- **Zero friction UX.** `pip install genehive`, `gene init`, `gene start`,
  walk away. `gene watch` gives a polished TUI over the git log.

## 2. Non-negotiables (guiding principles)

1. **Mutator / Judge / Evaluator separation.** No shortcuts. The judge is
   *always* a separate LLM call with a structured schema.
2. **Git is the only source of truth.** If a piece of state matters and
   isn't reconstructible from `git log`, it doesn't exist. No caches, no
   `.genehive/state.json` with mutable runtime data. (Config is fine — it's
   not runtime state.)
3. **Every run must be replayable from `git log` alone.** `gene report`
   should produce the full narrative from commits, nothing else.
4. **One-file-change discipline for the mutator.** Mendel (the mutator) is
   instructed to make one clearly-scoped change per iteration. Diff size is
   logged; large diffs are flagged but allowed.
5. **Budget is a hard stop.** When the accumulated `total_cost_usd` hits
   the limit, the loop exits cleanly. No silent continuation. If the user
   didn't set a budget, `gene start` refuses to start without
   `--yes-unlimited`.
6. **Pluggable engines from day one.** v0 ships with Claude Code only,
   used in two modes: full-agent for the mutator, single-response with
   tools disabled for the judge. Both `mutator.py` and `judge.py`
   expose protocols so Cursor CLI (or anything else) can implement
   either role later without touching the rest of the loop.

## 3. Architecture (one page)

Two filesystem locations matter: the **user's repo** (where config and
the git database live, and where the user works) and the **worktree**
(where mutations actually happen, off in a sibling directory the user
rarely looks at). They share one `.git/` — the git object database — via
`git worktree`. See §3a for the rationale.

```
┌─────────────────── USER'S REPO (the one they cd into) ────────────┐
│                                                                   │
│   .genehive/                                                      │
│     config.yaml          ← goal, eval commands, budget, model     │
│     prompts/             ← editable prompt templates              │
│       mutate.md                                                   │
│       judge.md                                                    │
│     daemon.pid           ← only non-git mutable file (lockfile)   │
│     daemon.log           ← stdout/stderr of the background loop   │
│     worktree.path        ← absolute path of the mutation worktree │
│                                                                   │
│   <user's code>          ← untouched while Genehive runs          │
│   .git/                  ← the shared object database             │
│                           (holds genehive/<island> branch too)    │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
                                    │
                                    │  git worktree add
                                    ▼
┌──────────── MUTATION WORKTREE (~/.genehive/worktrees/...) ────────┐
│                                                                   │
│   <user's code>          ← the genome; Mendel edits it here       │
│   .git                   ← a file pointing back to the main       │
│                           repo's .git/ (not a directory)          │
│                                                                   │
│   Branch checked out: genehive/<island>    (default: genehive/main)│
│                                                                   │
└───────────────────────────────────────────────────────────────────┘

┌────────────────────────── `gene` package ─────────────────────────┐
│                                                                   │
│   cli.py          Typer-based entrypoint (init/check/start/...)   │
│   loop.py         The mutate→eval→judge→act loop                  │
│   mutator.py      Claude Code full-agent wrapper (Mendel)         │
│   evaluator.py    Runs eval commands, captures output (Reaper.run)│
│   judge.py        Claude Code single-response, tools-off (Reaper.judge)│
│   commit.py       Parse/emit structured commit messages (Fossil)  │
│   budget.py       accumulates total_cost_usd from each call       │
│   config.py       Load/validate .genehive/config.yaml             │
│   worktree.py     Create/find/remove the mutation worktree        │
│   watch.py        Rich/Textual TUI dashboard                      │
│   daemon.py       Background process management                   │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

Note the loose correspondence to the named-agent cast from the long-term
vision: Mendel = `mutator.py`, Reaper = `evaluator.py` + `judge.py`, Fossil
= `commit.py` (git log), Wallace = `loop.py` (trivial in v0 — just runs
the loop; becomes intelligent scheduling later). Cupid and Hermes are
deferred.

## 3a. Git worktrees — why and how

**Why worktrees at all.** The user's repo is their workspace. If Genehive
mutates files directly in it, we stomp on their working tree and HEAD.
They can't edit, branch-switch, or even `git status` cleanly while the
daemon runs. A worktree gives us full filesystem isolation while still
sharing the git object database, so every commit Genehive makes is
immediately visible to the user from their main checkout as commits on
the `genehive/<island>` branch.

**Why a worktree in v0.** The MWE is a single-island hill climber, so in
principle we could get away without one. We ship one anyway because (a)
the isolation benefit alone justifies it, and (b) it locks in the
shape that multi-island needs — adding island #2 becomes "another
`git worktree add` on another branch", not a rearchitecture.

**Layout.** One worktree per `(repo, island)` pair, stored outside the
user's repo:

```
~/.genehive/worktrees/
  <repo-slug>/
    main/                     ← island "main", checked out on
                                genehive/main branch
```

- `<repo-slug>` is `<parent-dir-name>-<repo-name>-<sha8>` where `sha8`
  is the first 8 chars of the user-repo's absolute-path hash. This keeps
  distinct checkouts of the same repo from colliding.
- `main` is the island name — hard-coded in v0, configurable later.

**Branch.** `genehive/main`. Forked off the user's `HEAD` at
`gene init` time. Never force-pushed, never rebased. The user's own
branches are never touched.

**Lifecycle.**

| Event | What happens |
|---|---|
| `gene init` | `git worktree add <path> -b genehive/main`. Records `<path>` in `.genehive/worktree.path`. |
| `gene check` | Runs evals inside the worktree on the current `genehive/main` HEAD. |
| `gene start` | Daemon `chdir`s into the worktree and runs the loop there. |
| `gene watch` | Runs from the user's repo. Reads `git log genehive/main` via the shared object db — never touches the worktree. |
| `gene stop` | Stops the daemon. Leaves the worktree and branch in place so the user can inspect, merge, cherry-pick, or discard. |
| `gene init --clean` | `git worktree remove` + deletes `genehive/main` branch. Explicit teardown. |

**Merging back is the user's call.** Genehive never auto-merges
`genehive/main` into the user's working branch. When the run is done
the user decides: `git merge genehive/main`, cherry-pick individual
KEEP commits, or throw it all away.

**`worktree.py` responsibilities:**

- `create(repo_path, island="main") -> Path` — idempotent; if the
  worktree already exists and points at the right branch, returns its
  path; if it's missing or stale, recreates it.
- `path(repo_path, island="main") -> Path` — resolves by reading
  `.genehive/worktree.path` and verifying `git worktree list` agrees.
- `destroy(repo_path, island="main")` — teardown.
- Handles the edge cases: worktree directory deleted but git still
  thinks it exists (`git worktree prune`), branch exists but worktree
  doesn't, worktree exists on a different branch than expected.

## 4. The commit message schema (load-bearing)

Because git is the database, the commit message schema *is* the data
model. It must be parseable and forward-compatible.

```
<short summary line written by Mendel>

## mutation
<Mendel's plain-English reasoning for the change, 1–5 sentences>

## files
- path/to/changed_file.py
- path/to/other_file.py

<!-- ═══ everything below this line is appended by `gene` after the eval+judge ═══ -->

## eval
```yaml
commands:
  - cmd: "pytest -q"
    exit_code: 0
    duration_s: 12.4
    stdout: |
      .....
      5 passed in 11.9s
  - cmd: "python bench.py"
    exit_code: 0
    duration_s: 3.1
    stdout: |
      score=0.847
```

## judge
```yaml
verdict: KEEP   # or CULL or NOOP (NOOPs skip the judge entirely)
engine: claude-code
model: claude-haiku-4
reasoning: |
  Score improved 0.812 → 0.847 and tests still pass.
score: 0.847   # advisory scalar extracted from eval output; null if none
cost_usd: 0.0023   # from Claude Code's total_cost_usd for this call
```

## budget
```yaml
iteration: 14
spent_usd: 1.73          # exact, summed from Claude Code's total_cost_usd
limit_usd: 10.00
mutator_cost_usd: 1.68   # split across mutator and judge for transparency
judge_cost_usd: 0.05
```
```

Reverts get their own commit in the standard `git revert` form, with the
judge's reasoning copy-pasted into the revert message body so the log is
self-describing.

**NOOP iterations.** When the mutator produces nothing parseable (timeout,
empty output, malformed commit message) we still record the iteration so
it shows up in `gene watch` and `gene report`. This is an empty commit
(`git commit --allow-empty`) with `## mutation` set to the failure
reason, no `## eval`, no `## judge`, and `verdict: NOOP` in a
`## iteration` block plus a `## budget` block (the mutator call still
cost money even if it produced nothing). NOOPs are never reverted —
they're already no-ops.

**Parsing contract.** `commit.py` exposes:

- `parse(commit_sha) -> CommitRecord` (structured)
- `emit(record) -> str` (round-trippable)
- `last_kept(repo) -> CommitRecord` (walks `HEAD` backwards, skipping any
  commit that has been reverted; returns the previous best)

This is the one module that absolutely cannot be sloppy. Everything else
depends on it.

## 5. Config schema — `.genehive/config.yaml`

```yaml
goal: |
  Improve the val_bpb score in train.py without breaking tests.
  The genome is train.py only; do not modify evaluation code.

evals:
  - name: tests
    cmd: "pytest -q"
    required: true          # exit 0 is mandatory for KEEP

  - name: benchmark
    cmd: "python bench.py"

budget:
  limit_usd: 10.00          # exact; sum of total_cost_usd across calls
  warn_at: 0.80             # show prominent warning at 80%
  max_iterations: 500       # secondary cap

mutator:
  engine: claude-code       # only option in v0 (Cursor CLI planned)
  model: claude-sonnet-4    # full agent session — tools enabled
  timeout_s: 600            # kill the session after 10 min
  allow_large_diffs: true   # just warn, don't block

judge:
  engine: claude-code       # same binary, single-response mode, no tools
  model: claude-haiku-4     # cheap model; judge task is small
  timeout_s: 60             # judge calls should be fast
  max_retries: 2            # on JSON schema violation; then default CULL

worktree:
  island: main              # branch name will be genehive/<island>
  # root defaults to ~/.genehive/worktrees/<repo-slug>/<island>/
  # override only if you need to (e.g. different disk)
  # root: /mnt/fast/genehive

# prompts are in .genehive/prompts/*.md, editable
```

`gene init` writes this file interactively, creates `prompts/mutate.md`
and `prompts/judge.md` from built-in defaults, and provisions the
worktree (see §3a).

## 6. The CLI surface

| Command | What it does |
|---|---|
| `gene init [path]` | Interactive setup. Writes `.genehive/config.yaml` + default prompts. Creates the mutation worktree at `~/.genehive/worktrees/<repo-slug>/main/` on a fresh `genehive/main` branch. Adds `.genehive/daemon.*` and `.genehive/worktree.path` to `.gitignore`. `--clean` tears the worktree and branch down first. |
| `gene check [path]` | Dry-run validation. Loads config, verifies `claude` is reachable, confirms the worktree exists and is healthy, runs each eval command once on `genehive/main`, prints parsed output. Fails loudly if anything is wrong. |
| `gene start [path]` | Spawns the loop as a background daemon that `chdir`s into the worktree. Writes `daemon.pid`. Refuses to start if `daemon.pid` exists and the PID is live, or if the worktree is missing. |
| `gene watch [path]` | TUI dashboard over `git log genehive/main`, run from the user's repo. Never enters the worktree. See §7. |
| `gene status [path]` | One-line summary: `iter 42 · kept 17 · $3.14/$10.00 · last: KEEP (+0.013)`. Scriptable. |
| `gene stop [path]` | SIGTERM the daemon. Wait for graceful shutdown (finish current iteration). Leaves the worktree and `genehive/main` branch in place for the user to inspect/merge/discard. |
| `gene report [path]` | Dump full history of `genehive/main` as markdown. |

All commands default to `.` when `path` is omitted.

## 6a. Walkthrough — from `pip install` to a live run

Every step the user takes and every internal action Genehive performs,
in order. Intended as both a mental model and a checklist for
implementation. "User" = the human, "gene" = the CLI, "daemon" = the
background loop process.

### Stage 0 — Prerequisites (before `gene` enters the picture)

1. The user has a working Python 3.11+ environment.
2. The user has `git` ≥ 2.5 on PATH (worktrees need ≥ 2.5, subcommands
   we lean on need ≥ 2.15 — we target 2.15 as the floor).
3. The user has `claude` (Claude Code CLI) installed and authenticated.
   Verified once interactively by running `claude -p "hi"` and getting
   a response. Genehive never prompts for API keys; it trusts Claude
   Code's own auth. Both the mutator and the judge go through this
   single binary (see §5 — the judge runs Claude Code in
   single-response, tools-disabled mode).
4. The user has a git repository they want to optimise. Its working
   tree is clean (`git status` shows nothing) and it has at least one
   committed state we can branch from.
5. The user has at least one shell command that meaningfully
   evaluates that repo — tests, a benchmark script, anything that
   prints something a language model can reason about.

### Stage 1 — Install (`pip install genehive`)

1. User runs `pip install genehive` (or `pipx install genehive` for
   isolation — recommended in the README).
2. Pip resolves and installs dependencies: `typer`, `pydantic`,
   `pyyaml`, `textual`, `rich`. No LLM SDK needed — both the mutator
   and the judge shell out to the `claude` CLI. No heavy ML deps.
3. The `gene` console script is placed on PATH.
4. `gene --version` works. `gene --help` shows all commands from §6.

### Stage 2 — `cd my-repo && gene init`

1. `gene init` confirms the working directory is a git repo
   (`git rev-parse --show-toplevel`); aborts with a clear message
   if not.
2. Checks for an existing `.genehive/config.yaml`. If found:
   refuses unless `--force` was passed.
3. **Preflight checks** (fail fast, before asking any questions):
   - `which claude` → error if missing.
   - `claude -p --bare --output-format json "reply OK"` → parse JSON,
     confirm `total_cost_usd` key exists. Error with install/auth hint
     otherwise.
   - `git --version` ≥ 2.15.
   - Working tree is clean (`git status --porcelain` empty). If dirty,
     refuse and tell the user to commit or stash first — the worktree
     base commit must be deterministic.
4. **Interactive wizard** (one prompt at a time, Ctrl-C safe):
   - Shows the repo path and current `HEAD` sha. Confirms this is the
     state to branch `genehive/main` from.
   - **Goal**: opens `$EDITOR` (defaults to `vi`) on a tmp file with
     a template comment. User writes the goal in plain English. Saves
     the buffer → file becomes the `goal:` block in config.
   - **Eval commands**: loops asking for (name, command, required?).
     Empty name ends the loop. Must provide ≥ 1 eval command.
   - For each eval command, offers to run it right now against the
     current HEAD as a sanity check. On first failure, offers to
     edit the command or skip. This is the "does it even run
     today?" check — far better to catch it now than on iteration 1.
   - **Budget**: asks for `limit_usd` (required unless
     `--yes-unlimited`), `max_iterations` (default 500),
     `warn_at` (default 0.80).
   - **Models**: shows defaults (`mutator: claude-code`,
     `judge: claude-sonnet-4`), lets user override.
   - **Island name**: shows default `main`, lets user override. v0
     supports only one island so this is cosmetic, but reserves the
     name.
5. **Write config**: `.genehive/config.yaml` materialised from answers.
6. **Write prompts**: `.genehive/prompts/mutate.md` and
   `.genehive/prompts/judge.md` copied from package resources. User
   can edit later without touching code.
7. **Compute worktree path**:
   - `repo_slug = f"{parent_dir}-{repo_name}-{sha1(abs_path)[:8]}"`.
   - `worktree_path = ~/.genehive/worktrees/<repo_slug>/<island>/`.
8. **Create the worktree**:
   - `mkdir -p ~/.genehive/worktrees/<repo_slug>/`.
   - `git worktree add <worktree_path> -b genehive/<island> HEAD` run
     from inside the user's repo. This creates the branch
     `genehive/main` at the current HEAD *and* checks it out in the
     new worktree directory in one shot.
9. **Record the path**: write absolute `<worktree_path>` to
   `.genehive/worktree.path`.
10. **Update `.gitignore`**: append (creating if absent) the lines
    `.genehive/daemon.pid`, `.genehive/daemon.log`,
    `.genehive/worktree.path`. These are runtime artifacts, not state.
11. **Summary banner**: prints the worktree path, the budget, the goal
    (truncated), and the two next commands: `gene check`, then
    `gene start`.
12. Exits 0.

### Stage 3 — `gene check`

Non-mutating, cheap, idempotent. Designed to be run any time the user
changes config or worries something has drifted.

1. Loads and validates `.genehive/config.yaml` with Pydantic.
2. Re-runs the claude / git / worktree preflight checks from Stage 2.3.
3. **Worktree health**:
   - Read `.genehive/worktree.path`.
   - Confirm the directory exists and is a git worktree
     (`git rev-parse --show-toplevel` from inside it succeeds).
   - Run `git worktree list --porcelain` in the user's repo; confirm
     the path is listed and on branch `genehive/<island>`.
   - Recover on mismatch: if the directory is gone but git still lists
     it, run `git worktree prune` and recreate. If the branch is gone
     but the dir exists, abort with a clear message (user probably
     wants `gene init --clean`).
4. **Eval probe**:
   - `chdir` into the worktree.
   - For each eval in config: run it with the configured timeout,
     capture exit / stdout / stderr / duration. Print a one-line
     summary (`✓ tests  pytest -q  11.9s` etc.) plus the first 20
     lines of stdout.
5. **Judge model probe**: since the judge runs through the same
   `claude` binary we already validated in step 2, auth is assumed
   good. We still make one tiny single-response judge call (cost ≈
   $0.001) against a fixed fixture to confirm (a) `judge.model` is a
   valid model name for the local Claude Code install, (b) tools-
   disabled mode works, and (c) the structured-JSON contract in
   `prompts/judge.md` is respected. Prints the cost.
6. Prints a final tally: *all checks passed* or *N checks failed*.
   Exit 0 on full green, non-zero otherwise.

### Stage 4 — `gene start`

1. Loads config. Re-runs the cheap worktree health check (not the
   full eval probe — that's `gene check`'s job).
2. Budget guard: if `limit_usd` is unset and `--yes-unlimited` wasn't
   passed, refuse with a loud message.
3. Concurrency guard: if `.genehive/daemon.pid` exists, read it and
   check the PID. If live, refuse ("already running, PID 12345"). If
   stale, remove and continue.
4. **Fork the daemon**:
   - Parent process: writes the child PID to `.genehive/daemon.pid`,
     prints `Started. Watch with 'gene watch' or 'gene status'.`, and
     exits 0 immediately.
   - Child process:
     - `os.setsid()` to detach from the controlling terminal.
     - Redirect `stdin` to `/dev/null`, `stdout` and `stderr` to
       `.genehive/daemon.log` (append mode, line-buffered).
     - `chdir` into the worktree path from `.genehive/worktree.path`.
     - Install a `SIGTERM` handler that sets a `shutdown_requested`
       flag (so the current iteration can finish cleanly).
     - Log `[daemon start · pid N · iter 0]` with timestamp.
     - Initialise `budget.py` from config.
     - Enter the main loop.

### Stage 5 — One iteration of the loop (what the daemon actually does)

This is the innermost step, repeated until budget exhausted or
`gene stop` is called. Numbering restarts for clarity.

1. **Iteration bookkeeping**:
   - `iter_n = git rev-list --count genehive/main` (monotonic
     counter, stable across restarts).
   - Log `[iter iter_n · start]` with timestamp.
2. **Mutator prompt assembly**:
   - Read `prompts/mutate.md` template.
   - Substitute placeholders: `{{ goal }}`, `{{ recent_commits }}`
     (last 5 commit messages on `genehive/main` formatted as a
     numbered list), `{{ iter_n }}`.
   - Write the rendered prompt to a tmp file for reproducibility and
     so it can be shown in the TUI's detail modal if needed.
3. **Mutator invocation**:
   - `subprocess.run(["claude", "-p", rendered_prompt, "--bare",
     "--allowedTools", "Bash,Read,Edit", "--output-format", "json"],
     cwd=worktree, timeout=config.mutation.timeout_s)`.
   - On timeout: kill the process group, continue to step 5 with
     `commit_sha = None` and reason `timeout`.
   - On non-zero exit: continue to step 5 with `commit_sha = None`
     and reason `exited non-zero`.
4. **Parse mutator output**:
   - JSON-parse stdout. If parsing fails → step 5 with reason
     `malformed JSON output`.
   - Extract `total_cost_usd` (warn + use `0.0` if missing — schema
     drift warning, see §9). Add to `budget.py`.
   - Compute what Mendel actually committed: run
     `git rev-parse genehive/main` and compare with the sha from
     before the call. If it advanced by one commit whose message
     parses into a `CommitRecord`, use that. Otherwise → step 5 with
     reason `no parseable commit`.
5. **NOOP branch** (if `commit_sha is None`):
   - `git commit --allow-empty -m <noop message with reason and
     budget block>` — the commit message has `## mutation` with the
     reason, no `## eval`, no `## judge`, a `## iteration` block with
     `verdict: NOOP`, and a `## budget` block recording the mutator
     cost.
   - Log `[iter iter_n · NOOP: <reason>]`.
   - Skip to step 10 (budget check + sleep).
6. **Evaluator**:
   - For each eval command in config: `subprocess.run(cmd,
     shell=True, cwd=worktree, timeout=per_eval_timeout,
     capture_output=True)`. Build an `EvalResult` list.
   - Log `[iter iter_n · evals done · N/M passed]`.
7. **Previous-best resolution**:
   - `previous_best = commit.last_kept(repo, branch="genehive/main",
     before=commit_sha)` — walks the log backwards skipping reverted
     commits and NOOPs.
   - For iteration 1 there is no previous best; judge gets a
     special "first mutation" prompt telling it KEEP unless the
     evals clearly regress an implicit baseline.
8. **Judge**:
   - Render `prompts/judge.md` with goal, previous-best eval block,
     new eval block. The prompt ends with an explicit instruction to
     reply with only a JSON object matching a given schema.
   - `subprocess.run(["claude", "-p", rendered_prompt, "--bare",
     "--model", judge.model, "--allowedTools", "",
     "--output-format", "json"], timeout=judge.timeout_s)`.
     - `--allowedTools ""` disables every agent tool: this is what
       enforces the architectural rule that "the judge never sees the
       code". It's a single-response call, not a session — the judge
       has no way to read files, run shell, or modify anything.
     - `--model` picks the cheap model from config (default
       `claude-haiku-4`).
   - JSON-parse stdout. Extract the assistant's text result and
     parse *it* as the verdict JSON (verdict, reasoning, score).
     Retry up to `judge.max_retries` on schema violation, then
     default to CULL with a loud warning.
   - Extract `total_cost_usd` and add to `budget.py` under the
     judge-cost bucket. Uniform with the mutator accounting.
9. **Amend the commit**:
   - Load the new commit's message via `commit.parse`.
   - Append `## eval` block, `## judge` block, `## budget` block.
   - `git commit --amend -m <new message> --no-edit` (actually
     `--message=...` since `--no-edit` + `--message` are mutually
     exclusive — we fully rewrite).
   - If verdict is CULL:
     - `git revert --no-edit HEAD` to produce the revert commit.
     - `git commit --amend -m <revert message with judge reasoning
       copied in>` so the revert commit is self-describing.
   - Log `[iter iter_n · KEEP +0.013]` or `[iter iter_n · CULL
     -0.008]`.
10. **Budget + shutdown check**:
    - If `budget.spent >= budget.limit`: log
      `[budget exhausted · $X.XX / $Y.YY]`, break out of the loop.
    - If `iter_n >= max_iterations`: log and break.
    - If `shutdown_requested`: log `[graceful shutdown]`, break.
11. **Sleep** for `iteration_delay_s` (default 2s) to avoid hot-looping
    if something is returning instantly.
12. Go to step 1.

### Stage 6 — Shutdown

1. Loop exits (budget, max iterations, or SIGTERM).
2. Daemon removes `.genehive/daemon.pid`.
3. Logs `[daemon stop · reason=<...>  iter=<N>  spent=<$...>]`.
4. Exits 0.
5. The worktree and `genehive/main` branch are left untouched for the
   user to inspect, `git merge`, cherry-pick, or throw away.

### Stage 7 — Meanwhile, in another terminal: `gene watch`

Runs any time after Stage 4, during or after Stage 5, even after
Stage 6 (post-mortem inspection). Details in §7.

1. `gene watch` starts a Textual app from the user's repo.
2. On mount, reads `git log genehive/main --format=...` once, parses
   every commit with `commit.py`, builds the initial `CommitRecord`
   list.
3. Schedules a 2s-interval refresh that re-reads `git log` (fast — git
   pack files are cached) and a 500ms tail of `.genehive/daemon.log`.
4. Renders the UI per §7.1. Every displayed value is a derivation
   over those two data sources, nothing else.
5. User presses `q`. Watch exits; daemon keeps running.

## 7. `gene watch` — the TUI

Built with **Textual** (not plain Rich) so it's keyboard-navigable and
refreshes cleanly. Single source of data: `git log` + `daemon.log` tail.

### 7.1 Layout

Five stacked regions inside a Textual `Screen`:

1. **Header bar** — project, branch, iteration, elapsed wall-clock, and
   a budget gauge that changes colour past 80% / 95%.
2. **Goal line** — one truncated line showing what's being optimised.
   Press `g` to expand to a modal with the full goal text.
3. **Top strip** — four fixed-width panels side by side: score plot,
   run stats, latest-eval status, cost split.
4. **Middle** — recent-iterations table (the main navigable element).
5. **Live panel** — what the daemon is doing *right now*: current stage,
   elapsed, and a tail of `daemon.log`.
6. **Footer** — keybindings + any active warnings.

```
┌─ Genehive · owl · genehive/main · iter 42 · 02h 17m ───────── $3.14/$10.00 ████░░ 31% ─┐
│ goal: "Improve val_bpb in train.py without breaking tests."                     [g …] │
├──── score — val_bpb ─────────────┬─── stats ──────────┬── evals (last) ─┬── cost ─────┤
│ ★ 0.863 best  (iter 39)          │ kept    17 / 42    │ ✓ tests   11.9s │ mutator 91% │
│  0.85 ┤         ╭─────────       │ culled  22   52%   │ ✓ bench    3.1s │ ████████▏   │
│  0.80 ┤     ╭──╮╭╯               │ noops    3         │   score=0.847   │ judge    9% │
│  0.75 ┤  ╭──╯  ╰╯                │ $ / iter  $0.074   │                 │ ▊           │
│  0.70 ┤──╯                       │ iter / hr 18.3     │                 │             │
│       └──────────────────────    │ ETA $       4h 35m │                 │ $2.87 / 0.27│
│        0   10   20   30   40     │ since best  7 iter │                 │             │
├──────────────────────────────────┴───┬────────────────┴─────────────────┴─────────────┤
│ recent iterations (↑↓ to navigate, enter for detail)                    │ sparkline   │
│  iter  verdict  Δ        summary                            cost   dur  │             │
│  42  ▶ KEEP    +0.013   "use layernorm instead of batchnorm"$0.08 3:21  │ ▁▂▃▃▅▆▆▇▇█ │
│  41    CULL    −0.008   "try larger batch size"  (reverted) $0.09 2:54  │             │
│  40    KEEP    +0.004   "tune learning rate warmup"         $0.07 3:02  │             │
│  39    KEEP    +0.021   "add dropout after attention"  ★    $0.08 3:45  │             │
│  38    NOOP     —       (mutator timed out at 10m)          $0.02 10:00 │             │
│  37    CULL    −0.002   "swap gelu for silu"     (reverted) $0.06 2:48  │             │
├─────────────────────────────────────────────────────────────────────────┴─────────────┤
│ live · mutate · 00:03:21                                                   [▼ tail]   │
│  > reading train.py (lines 1–260)                                                     │
│  > analysing attention block                                                          │
│  > editing lines 45–62                                                                │
│  > running pytest -q to self-check                                                    │
├───────────────────────────────────────────────────────────────────────────────────────┤
│ ⚠ plateau: 7 iterations since last improvement                                        │
│ q quit · r refresh · ↑↓ select · ⏎ detail · l log · c diff · b best · g goal · ? help│
└───────────────────────────────────────────────────────────────────────────────────────┘
```

### 7.2 What each panel shows

**Header bar**

- Repo name (derived from the user's repo path), branch (`genehive/main`).
- Current iteration number (from `gene report`-able commit count on
  `genehive/main`).
- Wall-clock elapsed since `gene start` (derived from the first
  Genehive commit's timestamp, not from `daemon.pid` age — so it
  survives daemon restarts).
- **Budget gauge**: `$spent / $limit`, a filled bar, and a percentage.
  Colour rules: green < 80%, yellow 80–95%, red ≥ 95%. Applies to the
  whole header background so it's impossible to miss.

**Goal line**

- Truncated single line. `g` pops a modal with the full
  `config.yaml` goal text (and the current prompt templates, tabbed).

**Score panel**

- Multi-line ASCII plot of the fitness scalar the judge reports in its
  reasoning — v0 assumption: judge emits a `score:` key in its YAML
  verdict (new, see §7.4). Fallback: use iteration-number on x-axis and
  KEEP/CULL as +/−1 on y-axis for goals without a numeric score.
- Annotations: `★ best` marker at the high point with the iteration
  number. Colour segments: green for segments trending up, red for
  trending down, grey for NOOPs.

**Stats panel**

- `kept / total · XX%`, `culled · XX%`, `noops`.
- `$ / iter` rolling average (last 20 iters).
- `iter / hr` rolling average (last 20 iters).
- `ETA $` — projected time until budget exhausted at current $/iter
  rate.
- `since best` — number of iterations since the current best score.
  This is the plateau detector's input (see warnings below).

**Evals panel**

- One row per eval command from config. Each shows: ✓/✗ (exit code),
  short command, duration of the last run, and the *parsed* result
  line (first line of stdout that looks like `key=value` or `score:
  X`). If an eval is slow (> 60s or > 2× its historical median) its row
  is dimmed with a `⏱` marker so the user can tell it's a bottleneck.

**Cost panel**

- Split between mutator and judge with percent bars and raw totals.
  Visually confirms that mutator cost dominates (expected) and the
  judge is staying cheap as designed.

**Recent iterations table**

- Scrollable. Columns: iter, marker (`▶` selected, `★` current best),
  verdict (KEEP / CULL / NOOP, colour-coded), Δ score vs. previous
  best, summary (Mendel's commit title), cost, wall-clock duration.
- Keybindings operate on the selected row:
  - `⏎` Enter — open a detail modal with the full commit message
    (mutation reasoning, eval blocks, judge reasoning).
  - `c` — show the diff (`git show --stat` then full diff in a pager).
  - `l` — open a full-screen log view scrolling all iterations.
- Verdict sparkline in the right rail: last 30 iterations as
  `▁▂▃▄▅▆▇█` glyphs based on score, or dots/`×` for NOOP/CULL.

**Live panel**

- Stage indicator: `mutate` / `evaluate` / `judge` / `amend` / `revert`,
  with per-stage colour.
- Elapsed in current stage.
- Last 4 lines of `.genehive/daemon.log`. Press `▼` (down arrow while
  focused on this panel, or `t` from anywhere) to expand it into a
  full-screen tail view.
- When idle between iterations, shows `idle · sleep 2s` so the user
  knows the loop is alive.

**Footer / warnings**

- Persistent keybindings line.
- Above it, a stack of zero-to-three active warnings, auto-dismissed
  when the condition clears. Triggers:
  - **⚠ plateau**: `since best` exceeds a threshold (default 10 iters).
  - **⚠ budget 80%**: spent ≥ 80% of limit.
  - **🛑 budget 95%**: spent ≥ 95% of limit.
  - **⚠ noop streak**: 3+ consecutive NOOPs (mutator is probably
    stuck; user may want to edit `prompts/mutate.md`).
  - **⚠ schema drift**: Claude Code JSON missing expected keys (see
    §9 risks).
  - **🛑 auth**: Claude Code returning auth errors.
  - **⚠ eval flapping**: same eval command exit code flips run-to-run
    on unchanged code (seen at iter boundaries via `gene check` probes
    — optional, phase 9).

### 7.3 Keybindings

| Key | Action |
|---|---|
| `q` | Quit watch (daemon keeps running) |
| `r` | Force refresh (normally auto every 2s) |
| `↑` `↓` `k` `j` | Select row in recent iterations |
| `⏎` | Open detail modal for selected iteration |
| `c` | Show diff for selected iteration |
| `l` | Full-screen log of all iterations (scrollable) |
| `b` | Jump selection to current best iteration |
| `g` | Show full goal text + prompt templates |
| `t` | Toggle full-screen tail of `daemon.log` |
| `e` | Show full last-run output of a chosen eval |
| `?` | Help overlay with all bindings |

All modals are dismissable with `esc`.

### 7.4 Data pipeline

Watch is a pure read-only view over three data sources:

1. **`git log genehive/main`** (refreshed every 2s or on `r`). Parsed
   via `commit.py` into `List[CommitRecord]`. Everything the table,
   stats panel, score plot, and cost panel show is derived from this.
2. **`.genehive/daemon.log` tail** (last ~100 lines, refreshed every
   500ms while focused). Feeds the live panel and the `t` modal.
3. **`.genehive/daemon.pid`** (stat, not read). Just a liveness check
   for the header — a red dot next to the iteration count if the
   daemon isn't actually running.

No long-lived socket between daemon and watch. No shared state file.
This is deliberate: `gene watch` works on a fully offline repo, which
means it also works for post-hoc inspection (read a Genehive repo
someone else ran, `gene watch` still tells the full story up to the
last commit).

### 7.5 Score extraction — judge emits a score

Several panels need a numeric score, not just KEEP/CULL. Small
addition to the judge contract: the judge is asked to extract a
single scalar (if one is identifiable in the eval output) and emit it
as `score: <float>` in the `## judge` block alongside its reasoning.
If it can't identify one, `score: null` — watch falls back to
KEEP/CULL as +1/−1 on the y-axis. The field is advisory only; the
KEEP/CULL verdict remains the source of truth for the loop.

## 8. Build phases / milestones

Each phase ends with something runnable. Don't move on until the previous
phase's demo works end-to-end.

### Phase 0 — Scaffolding (half a day)

- Python 3.11+ project, `pyproject.toml`, `src/gene/` layout.
- Typer CLI with stubs for every command in §6.
- `pytest` + `ruff` + `mypy` on green CI.
- `gene --help` shows all commands.

**Demo:** `pip install -e .` then `gene --help`.

### Phase 1 — Config + worktree + `gene init` + `gene check` (1.5 days)

- `config.py`: load+validate with Pydantic.
- `worktree.py`: `create` / `path` / `destroy` per §3a. Unit-tested
  against a tmp git repo covering all four edge cases (missing dir,
  stale git metadata, wrong branch, healthy).
- Default prompt templates committed as resources.
- `gene init`: interactive wizard (goal, eval commands, budget), writes
  `.genehive/config.yaml` and prompts, then calls `worktree.create`.
  Records the worktree path in `.genehive/worktree.path` and appends to
  `.gitignore`.
- `gene check`: loads config, verifies `claude` on PATH and returns
  valid JSON for a trivial prompt, confirms the worktree is healthy,
  runs evals inside the worktree on `genehive/main`, parses, prints.

**Demo:** `gene init` on a toy repo creates the worktree; `ls
~/.genehive/worktrees/` shows it; `gene check` runs evals against it.

### Phase 2 — Commit schema (1 day)

- `commit.py`: `parse`, `emit`, `last_kept`. Supports all three verdict
  types (KEEP, CULL, NOOP); NOOP commits are empty and skip the eval
  and judge blocks.
- Round-trip tests on hand-written fixtures for each verdict type.
- Integration test: create commits in a tmp repo, amend with eval blocks,
  revert some, mix in NOOP empty commits; confirm `last_kept` skips
  reverted commits *and* NOOPs.

**Demo:** unit tests green. This is the foundation for everything else.

### Phase 3 — Evaluator (half a day)

- `evaluator.py`: run a list of eval commands in the **worktree's**
  working directory (not the user's repo), capture stdout / stderr /
  exit / duration, with per-command timeout.
- Returns a structured `EvalResult` that `commit.py` can serialise.

**Demo:** `python -m gene.evaluator .genehive/config.yaml` prints a
parsed result.

### Phase 4 — Judge (1 day)

- `judge.py`: mirrors `mutator.py`'s engine/result shape so the two
  feel like peers. Defines a `Judge` protocol with one method:
  `evaluate(goal, prev_eval, new_eval) -> JudgeResult` where
  `JudgeResult` carries `verdict` (KEEP|CULL), `reasoning`, optional
  `score`, and exact `cost_usd`.
- v0 implementation: `ClaudeCodeJudge`. Shells out to
  `claude -p --bare --model <cfg.judge.model> --allowedTools ""
  --output-format json` with a rendered prompt instructing a strict
  JSON reply (see §6a Stage 5 step 8). `--allowedTools ""` is the
  enforcement mechanism for the "judge never sees the code" rule —
  the CLI literally cannot touch files or run shell in this mode.
- Parses the outer Claude Code JSON for `total_cost_usd`, then parses
  the inner assistant text as the verdict JSON.
- Retry on schema violation (up to `cfg.judge.max_retries`, then
  default to CULL with a loud log line).
- Unit tested with a mocked `subprocess.run`. Fixtures cover: clean
  KEEP response, clean CULL response, `score: null` path,
  malformed-JSON retry-then-default path, timeout path.

**Demo:** fixture eval blocks in, verdict + optional score + exact
cost out. Total spend across mutator and judge now comes from one
source: summed `total_cost_usd` from the `claude` CLI.

### Phase 5 — Mutator (1 day)

- `mutator.py` defines a small `Mutator` protocol with one method:
  `run(repo, prompt) -> MutatorResult` where `MutatorResult` carries the
  new commit sha (or `None`), the tool's self-reported `cost_usd`, and
  the raw transcript for logging.
- v0 implementation: `ClaudeCodeMutator`. Shells out to
  `claude -p --bare --allowedTools "Bash,Read,Edit" --output-format json`
  with a rendered prompt that includes (a) the goal, (b) the last 5
  commit messages, (c) an instruction to commit the change with the
  `## mutation` + `## files` schema. Parses the JSON output for
  `total_cost_usd` and per-model `modelUsage`. Timeout-enforced.
- `budget.py`: accumulates `cost_usd` from each `MutatorResult` and each
  judge call; exposes `spent`, `remaining`, `would_exceed(next_estimate)`.

**Demo:** single invocation produces a commit on a toy repo whose message
parses cleanly, and `budget.py` logs the exact dollar cost.

### Phase 6 — The loop (1 day)

- `loop.py`: stitches Phases 3–5 together. At startup it resolves the
  worktree via `worktree.path(user_repo)` and runs everything inside it.
  - Run mutator (cwd = worktree, branch = `genehive/main`).
    - If mutator returns no commit sha (timeout / empty / malformed),
      write an empty NOOP commit with the failure reason, record
      `mutator_cost_usd` against the budget, skip straight to the
      budget check.
  - Run evaluator (cwd = worktree).
  - Load previous-best via `commit.last_kept` (walking `genehive/main`,
    skipping reverted *and* NOOP commits).
  - Run judge.
  - Amend the new commit with `## eval` + `## judge` + `## budget`.
  - If CULL: `git revert --no-edit <new_sha>`, then amend revert message
    with reasoning.
  - Check budget. Exit if exhausted.
  - Sleep briefly, loop.

**Demo:** `python -m gene.loop .` run from the user's repo drives 5
iterations on `genehive/main` in the worktree; `git log genehive/main`
from the user's repo tells the whole story.

### Phase 7 — Daemon wrap (half a day)

- `daemon.py`: detach, redirect stdout/stderr to `.genehive/daemon.log`,
  write pidfile, handle SIGTERM for graceful shutdown (finish current
  iteration).
- Wire up `gene start` / `gene stop` / `gene status`.

**Demo:** `gene start && gene status && gene stop` works cleanly.

### Phase 8 — `gene watch` TUI (3 days)

Split into three sub-phases because there's a lot here (see §7). Each
ends with a demoable, dogfoodable build.

**8a — skeleton (1 day)**

- Textual app, run from the user's repo. Reads `git log genehive/main`
  every 2s, parses with `commit.py`, builds `List[CommitRecord]`.
  Never touches the worktree — the shared object db means every
  commit is already visible.
- Implement header bar, goal line, recent-iterations table (navigable),
  and live panel tailing `.genehive/daemon.log`.
- Footer with minimal keybindings (`q`, `r`, `↑↓`, `⏎`, `?`).

**Demo:** run the loop, watch it in real time, navigate the table,
open a detail modal for any iteration.

**8b — stats & score panels (1 day)**

- Score plot with best-marker, colour-segmented by trend.
- Stats panel: kept/culled/noop counts, $ /iter, iter/hr, ETA,
  since-best — all derived from `CommitRecord` list, no extra data
  sources.
- Evals panel: per-eval latest status + duration, with flagging for
  abnormally slow runs.
- Cost panel: mutator/judge split with bars.
- Sparkline column in the recent-iterations table.

**Demo:** every panel in §7.1 is populated with real data from a
running loop.

**8c — polish, warnings, modals (1 day)**

- Warning banners: plateau, budget 80% / 95%, noop streak, schema
  drift, auth. Each is a predicate over `CommitRecord` list +
  `daemon.log` tail.
- Budget gauge colour in header bar.
- Modals: `c` diff, `l` full log, `b` jump-to-best, `g` goal +
  prompts, `t` full-screen tail, `e` eval output.
- Resize-safe layout (test at 80×24 and 200×60).

**Demo:** deliberately stall the loop → plateau banner. Lower the
budget → 80% banner goes yellow, 95% goes red. Kill the daemon →
pid-liveness dot turns red. Resize the terminal — layout stays
readable.

### Phase 9 — Dogfooding (1–2 days)

- Pick a toy optimisation problem (e.g. a small `train.py` on a tiny
  dataset with a clear scalar metric).
- Run Genehive on it overnight with a $5 budget.
- Fix every rough edge encountered.
- Write the `gene report` output as the README demo.

## 9. Risks & open questions

- **Claude Code auth + availability.** Single point of dependency for
  both mutator and judge. `gene check` verifies `claude` is on PATH
  and that `claude -p --bare "hi"` returns a parseable JSON result
  before `gene start` is allowed. Good news: one failure mode instead
  of two (no separate Anthropic SDK auth path).
- **Judge-tool-isolation contract.** The architectural rule "the judge
  never sees the code" is enforced by passing `--allowedTools ""` to
  Claude Code. `judge.py` must always construct the command with that
  flag present. Worth a unit test that asserts the exact argv rather
  than just the result. If a future Claude Code release renames or
  removes that flag, the test fails loudly.
- **Mutator non-determinism.** Mendel may commit nothing, may commit
  with a broken message, may time out. The loop must treat "mutator
  produced no parseable commit" as a NOOP iteration (logged, not
  crashed). Cost from such iterations still counts against the budget.
- **Claude Code JSON schema drift.** Both `mutator.py` and `judge.py`
  depend on `total_cost_usd` and `modelUsage` keys in the outer CLI
  JSON. Both validate on every call; missing keys → loud warning +
  fall back to `0.0` cost (so the budget guard becomes advisory
  rather than exact until fixed). One check, applied in two places.
- **Judge inner-JSON schema violations.** The assistant's text reply
  must parse as the verdict JSON. Handled with `judge.max_retries`
  retries then default-to-CULL. Worth an integration test that
  simulates a malformed inner response.
- **Cheap-model capability.** Using `claude-haiku-4` for the judge
  keeps judge cost at a few cents an iteration, but a cheap model may
  be bad at following the JSON schema or at nuanced
  better-or-worse reasoning. Mitigation: the retry-then-default-CULL
  path is safe (pessimistic by design), and users can override
  `judge.model` in config. Worth benchmarking during Phase 9
  dogfooding.
- **Git reflog growth.** Unbounded over long runs. Not a v0 blocker but
  note for later: periodic `git gc`.
- **Concurrent `gene start` invocations.** Pidfile check, fail fast.
- **Worktree drift.** If the user does something exotic (deletes the
  worktree directory, force-deletes `genehive/main`, moves the repo on
  disk) between `init` and `start`, we have to detect and recover
  cleanly. `worktree.py` tests cover this; `gene check` is the first
  line of defence.
- **User on a different branch than `genehive/main`.** Intentional — the
  worktree is entirely separate. The only time this matters is if the
  user wants mutations to rebase onto their latest work; that's a future
  `gene rebase` command, not v0.
- **Windows support.** Deferred. Tested on macOS + Linux only.

## 10. Deferred (explicitly out of scope for v0)

From the long-term Genehive vision (files 00, 01, 03) — we will get here,
but not in the MWE:

- **Cursor CLI as an alternative engine.** The `Mutator` and `Judge`
  protocols (§8 Phases 4–5) both abstract over "LLM execution engine",
  so a `CursorCliMutator` (and, if useful, a `CursorCliJudge`) can be
  dropped in post-v0 without touching the loop. Cursor has better
  codebase indexing for multi-file repos; the trade-off is weaker
  budget (tiktoken lower-bound estimates instead of exact
  `total_cost_usd`). Planned, not v0.
- **Direct Anthropic SDK engine.** If we want finer-grained control
  or lower latency for the judge specifically, a third engine that
  calls the Anthropic Messages API directly (no subprocess overhead)
  is a small add — but it brings back an extra auth path, which is
  exactly what this revision was simplifying away. Only if there's a
  measured reason.
- **Cupid** (crossover / breeding two genomes).
- **Hermes** (migration between islands).
- **Multi-island topology.** The whole point of the biology metaphor —
  island model, rugged landscapes. v0 is one island.
- **Wallace as an intelligent LLM orchestrator.** In v0, Wallace is just
  a `while True:` loop.
- **Eval curriculum** (the 5-stage schedule: smoke → proxy → unlocks →
  blended → oracle). v0 runs all eval commands every iteration.
- **SQLite + Fossil.** Git is the database in v0. When we need richer
  queries (e.g. cross-island migration decisions) we'll revisit.
- **Grand tournament on `gene stop`.** Nice-to-have, not v0.
- **Human-in-the-loop stage.** v0 is fully autonomous.

## 11. Definition of done for v0

1. `pip install genehive && cd my-repo && gene init && gene start` runs
   an overnight loop on a real problem, unattended, within budget.
2. `gene watch` shows live progress that's genuinely informative.
3. `git log` is a complete, parseable, human-readable record of every
   mutation attempt, its evaluation, and the judge's reasoning.
4. A stranger can `git clone` the evolved repo and reconstruct the story
   with `gene report`.
5. The three concerns (mutate / evaluate / judge) are in three files
   and can be swapped independently without touching each other.

When all five are true, we ship v0 and start on Cupid.
