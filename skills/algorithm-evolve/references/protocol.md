# Algorithm Evolve Protocol

## Task Contract

Translate the user's natural-language request into JSON and confirm it before initializing state:

```json
{
  "id": "faster-router",
  "goal": "Minimize p95 routing latency without changing route results",
  "artifact": "/absolute/path/to/source-copy",
  "evaluation": {
    "mode": "objective",
    "command": "python -m pytest && python benchmark.py --json result.json"
  },
  "direction": "minimize",
  "constraints": ["all tests pass", "no network access"],
  "budget": {
    "iterations": 20,
    "seconds": 3600,
    "model_calls": 80,
    "stagnation": 6,
    "target_score": 12.0
  }
}
```

`evaluation.mode` is one of:

- `objective`: require at least one numeric objective result before finalization.
- `hybrid`: require an objective result; store reviewer results as advisory evidence.
- `judgment`: require three distinct reviewer names and use their median score.

Provide at least one positive `iterations`, `seconds`, or `model_calls` budget. `stagnation` and `target_score` are optional. An objective score is always better when larger for `maximize` and smaller for `minimize`.

The state tool does not run `evaluation.command`. The execution subagent runs it through the host sandbox and records the result.

## Candidate Layout

Keep state outside candidate artifacts:

```text
.algorithm-evolve/<task-id>/
├── task.json
├── state.db
├── candidates/<unique-name>/
└── evidence/<unique-name>/
```

A candidate may contain source, prompts, configuration, dependency declarations, and a runnable entrypoint. Each candidate must be independently evaluable.

## State Commands

Resolve `search_state.py` from the Skill's `scripts/` directory:

```bash
STATE_TOOL="/absolute/path/to/this-skill/scripts/search_state.py"
TASK_ID="faster-router"
STATE_DIR=".algorithm-evolve/$TASK_ID"
DB="$STATE_DIR/state.db"
python3 "$STATE_TOOL" --db "$DB" init --task "$STATE_DIR/task.json"

python3 "$STATE_TOOL" --db "$DB" add-node \
  --task-id "$TASK_ID" --action refine --artifact "$CANDIDATE_DIR" \
  --idea "Replace linear scan with indexed lookup" --parent "$PARENT_ID"

python3 "$STATE_TOOL" --db "$DB" record \
  --node "$NODE_ID" --kind constraint --passed true \
  --evidence "$CONSTRAINT_EVIDENCE"

python3 "$STATE_TOOL" --db "$DB" record \
  --node "$NODE_ID" --kind objective --score 14.2 \
  --evidence "$OBJECTIVE_EVIDENCE"

python3 "$STATE_TOOL" --db "$DB" record \
  --node "$NODE_ID" --kind judgment --score 0.8 --judge reviewer-a \
  --evidence "$REVIEW_EVIDENCE"

python3 "$STATE_TOOL" --db "$DB" finalize --node "$NODE_ID"
python3 "$STATE_TOOL" --db "$DB" select --task-id "$TASK_ID"
python3 "$STATE_TOOL" --db "$DB" status --task-id "$TASK_ID"
python3 "$STATE_TOOL" --db "$DB" best --task-id "$TASK_ID"
python3 "$STATE_TOOL" --db "$DB" show --node "$NODE_ID"
python3 "$STATE_TOOL" --db "$DB" query --task-id "$TASK_ID" --text "indexed lookup"
```

Use `query --all-tasks` only after the user enables cross-task retrieval. All commands emit JSON.

`finalize` assigns a rollout reward of `1` for improvement over the best parent, `0.5` for equality or a parentless baseline, and `0` for regression or constraint rejection. It backpropagates once to each unique ancestor, including through fused branches. The deliberately coarse reward avoids pretending unrelated raw metric scales are comparable. Introduce task-specific normalization only when magnitude-sensitive selection is demonstrated to matter.

## Subagent Results

Require generator subagents to return:

```json
{
  "artifact": "/absolute/path/to/candidate",
  "idea": "Concise searchable rationale",
  "changed_files": ["router.py"],
  "known_risks": ["Higher memory use"]
}
```

Require execution and reviewer subagents to return:

```json
{
  "kind": "objective",
  "score": 14.2,
  "passed_constraints": true,
  "evidence": "/absolute/path/to/evidence.json",
  "summary": "Tests passed; benchmark median from five runs"
}
```

For judgment mode, replace `kind` with `judgment` and include a stable, distinct `judge` name. Reviewers must cite candidate content against every rubric item.
