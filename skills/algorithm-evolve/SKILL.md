---
name: algorithm-evolve
description: Evolve executable algorithms, optimization routines, prompts, configurations, or agent workflows with Monte Carlo graph search and independently scored subagents. Use when Codex must search several candidate approaches under explicit tests, metrics, rubrics, constraints, and a time or iteration budget while preserving a queryable evidence trail.
---

# Algorithm Evolve

Run a bounded Monte Carlo graph search (MCGS) over isolated candidate directories. Keep the existing project unchanged and return the best candidate as a directory or patch with evidence.

## Preserve These Boundaries

- Require a confirmed task contract and at least one finite budget before searching.
- Treat hard constraints as gates. Prefer objective scores over reviewer opinions.
- Never let a candidate-generating subagent judge its own candidate.
- Execute candidates only through the host's sandbox and permissions. This skill's script never executes candidate code.
- Keep retrieval task-scoped unless the user explicitly requests cross-task ideas. Never transfer old scores between tasks.
- Do not overwrite the source project. Apply a winning patch only after explicit confirmation.

## Prepare The Search

1. Inspect the project, its runnable entrypoint, tests, benchmark, and current baseline. Discover facts from the workspace; ask the user only for decisions that cannot be inferred.
2. Read [references/protocol.md](references/protocol.md) before creating the task. It defines the task contract, scoring rules, state commands, and subagent result format.
3. If `.algorithm-evolve/*/state.db` already contains this task, use `algorithm-evolve-resume` instead of initializing it again.
4. Convert the request into `.algorithm-evolve/<task-id>/task.json`. Confirm the goal, evaluator or rubric, score direction, constraints, and budget with the user. If an outer layer injected a `methodology` block (`split_contract`, `oof_ensemble`, `feature_pipeline`), keep it on the contract; `init` validates it fail-closed and `status`/`resume` echo the canonical form. Omit the block when none was injected. When the block is present, every candidate must include a Methodology Manifest (FE steps / ensemble members / OOF protocol / split-ref digest summary) via `add-node --manifest` or `methodology.json` in the candidate directory. `finalize` fail-closes if the split-ref digest does not match the task `split_contract`, or if a declared `oof_ensemble` lacks `oof` / `declared_equivalent`.
5. Resolve `scripts/search_state.py` relative to this file, then initialize the database:

```bash
STATE_TOOL="/absolute/path/to/this-skill/scripts/search_state.py"
TASK_ID="faster-router"
STATE_DIR=".algorithm-evolve/$TASK_ID"
python3 "$STATE_TOOL" --db "$STATE_DIR/state.db" init --task "$STATE_DIR/task.json"
```

6. Copy the initial artifact into a candidate directory, add it as `baseline`, record its constraint and score evidence, then finalize it. If no implementation exists, add the first generated candidate as `propose` without a parent.

## Run The MCGS Loop

Repeat until `status` returns a stop reason:

1. Run `select` to choose a finalized node by UCT.
2. Run task-scoped `query` using the selected node's weakness or intended improvement. Use `--all-tasks` only when explicitly allowed.
3. Pick one action:
   - `propose`: explore a materially different algorithm, optionally from one selected parent.
   - `refine`: improve one valid parent without changing its core approach.
   - `repair`: fix one rejected or valid parent's concrete failure.
   - `fuse`: combine compatible mechanisms from at least two finalized branches. Use after stagnation, not merely because two candidates exist.
4. Spawn a generator subagent with only the confirmed contract, selected artifacts, relevant retrieved evidence, action, and output directory. Require an idea summary and changed files. When methodology contracts are injected, also require a Methodology Manifest that indexes the candidate. Do not reveal hidden evaluator data.
5. Add the candidate with `add-node`. Keep it in a separate directory. Pass `--manifest` or write `methodology.json` into the candidate when the task has methodology contracts; `add-node` rejects a missing manifest in that case.
6. Delegate evaluation:
   - For objective or hybrid tasks, use an execution subagent to run the confirmed evaluator inside the host sandbox and return raw score plus evidence.
   - Record every hard constraint. A single record may cover the complete constraint set when its evidence names each check.
   - For judgment tasks, spawn three independent reviewer subagents with the same rubric. Take no reviewer score from the generator.
7. Record results with `record`, then run `finalize`. Objective scores become authoritative; judgment scores remain advisory when objective evidence exists.
8. Run `status`. Stop on target, budget, stagnation, user cancellation, or when no valid or repairable candidate remains.

Use a repair attempt before returning to UCT only when a rejected candidate has a specific, bounded failure. Do not create unbounded debug loops.

## Finish

Run `best`, inspect its artifact, rerun the evaluator once from a clean candidate copy, and report:

- baseline and final score;
- hard-constraint and test evidence;
- winning ancestry and fused parents;
- reviewer disagreement;
- useful failed ideas;
- candidate directory and optional patch.

Do not claim success when the final clean evaluation differs from the stored winning score.
