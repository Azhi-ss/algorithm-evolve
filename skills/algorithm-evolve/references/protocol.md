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

An optional `methodology` block may be injected by an outer layer. It carries up to three T44-shaped contracts. Omit the block entirely for standalone use; search behavior then stays identical to a task without methodology, and no methodology field appears in `status` or `resume` output.

```json
{
  "methodology": {
    "split_contract": {
      "kind": "kfold",
      "n_splits": 5,
      "purge": 0,
      "embargo": 0
    },
    "oof_ensemble": {
      "members": ["baseline", "tree"],
      "method": "mean",
      "oof": {"protocol": "kfold"}
    },
    "feature_pipeline": {
      "steps": [{"name": "impute"}, {"name": "scale"}]
    }
  }
}
```

Field names accept snake_case and camelCase aliases (`splitContract`, `groupColumn`, `oofProtocol`, `declaredEquivalent`, `featurePipeline`, `pipelineSteps`, and the same pattern for the other fields). `split_contract.kind` is `kfold`, `time`, or `group`. Group splits require `group_column`. `purge` and `embargo` must be non-negative. `oof_ensemble.members` must have at least two entries, and the ensemble must declare an `oof` protocol or set `declared_equivalent` to true. Malformed methodology fail-closes at `init`. When present, the canonical contracts are persisted and echoed by `status` and `resume`.

## Methodology Manifest (generator protocol)

When methodology contracts are injected, the generator must emit a Methodology Manifest with **every** candidate. The four field classes are:

1. **FE steps** — `feature_pipeline.steps`
2. **ensemble members** — `oof_ensemble.members`
3. **OOF protocol** — `oof` / `declared_equivalent` (on the ensemble or the manifest root)
4. **split-ref digest summary** — `split_ref.digest_summary`

The manifest is a **declarative index**. The candidate artifact (directory) is the **source of truth**. `finalize` rejects a mismatch (ADR 0003): the split-ref digest must equal the SHA-256 of the task-level `split_contract`, and a task-declared `oof_ensemble` requires `oof` or `declared_equivalent`.

Standalone (no-contract) tasks do not require a manifest: it is optional and the methodology gates stay dormant. A missing manifest is accepted and `show` omits the field.

Pass the index to `add-node` as `--manifest <file>` or place `methodology.json` (or `methodology_manifest.json`) in the candidate directory.

```json
{
  "feature_pipeline": {
    "steps": [{"name": "impute"}, {"name": "scale"}]
  },
  "oof_ensemble": {
    "members": ["baseline", "tree"],
    "oof": {"protocol": "kfold"}
  },
  "split_ref": {
    "digest_summary": "<sha256 of the task split_contract>"
  }
}
```

The split-reference digest summary is the lowercase SHA-256 hex digest of the canonical JSON encoding of the task-level `split_contract` (`sort_keys=true`, compact separators `,` and `:`). A manifest may instead include the same `split_contract` object; `finalize` then derives the digest from it. Field names accept the same snake_case and camelCase aliases as the task block (`splitRef`, `digestSummary`, `oofEnsemble`, `declaredEquivalent`, `featurePipeline`, …).

`add-node` rejects a contract-injected task whose candidate has no manifest. `finalize` fail-closes on the existing constraint-reject path (`effective_kind=constraint`, reward `0`):

- manifest split-ref digest summary must equal the task-level `split_contract` digest summary
- when the task declares `oof_ensemble`, the manifest must declare an `oof` protocol or `declared_equivalent`

The state tool does not run `evaluation.command`. The execution subagent runs it through the host sandbox and records the result.

## Component-targeted propose / refine

`propose` and `refine` may target one mutable methodology component. Split is a task-level immutable reference and is **structurally excluded** from the action space (`--component split` is rejected).

| `--component` | Meaning | Allowed rewrite | Frozen |
|---|---|---|---|
| `feature_pipeline` (`fe`, `fe-only`) | FE-only | feature-pipeline region / steps | ensemble, split-ref |
| `oof_ensemble` (`ensemble`, `ensemble-only`) | ensemble-only | ensemble **members** only | feature-pipeline, OOF protocol / method, split-ref |

Component-targeted `propose`/`refine` require a parent. `add-node` compares the child manifest against that parent and rejects a rewrite of a frozen region. Full (untargeted) `propose`/`refine` remain available when the generator changes more than one mutable component.

`scripts/fake_generator.py` is a no-model scripted generator for CLI-level checks: it writes a candidate directory plus a four-field-class `methodology.json`, and its stdout matches the generator result object above. Drive it through `add-node` / `record` / `finalize` without calling a real model.

Example:

```bash
python3 "$STATE_TOOL" --db "$DB" add-node \
  --task-id "$TASK_ID" --action refine --component feature_pipeline \
  --artifact "$CANDIDATE_DIR" \
  --idea "FE-only: add mutual-info selection" --parent "$PARENT_ID" \
  --manifest "$CANDIDATE_DIR/methodology.json"
```

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
  --task-id "$TASK_ID" --action refine --component feature_pipeline \
  --artifact "$CANDIDATE_DIR" \
  --idea "Replace linear scan with indexed lookup" --parent "$PARENT_ID" \
  --manifest "$CANDIDATE_DIR/methodology.json"

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
python3 "$STATE_TOOL" --db "$DB" resume --task-id "$TASK_ID"
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
  "known_risks": ["Higher memory use"],
  "manifest": {
    "feature_pipeline": {"steps": [{"name": "impute"}]},
    "oof_ensemble": {"members": ["baseline", "tree"], "oof": {"protocol": "kfold"}},
    "split_ref": {"digest_summary": "<sha256 of the task split_contract>"}
  }
}
```

`manifest` is required only when the task contract includes a `methodology` block. The generator must then include all four field classes. Omit it for standalone (no-contract) tasks; the gates stay dormant. Component-targeted `propose`/`refine` also return the same `manifest` and must rewrite only the targeted region.

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
