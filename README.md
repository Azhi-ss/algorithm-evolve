# Algorithm Evolve

[中文](README.zh-CN.md)

Algorithm Evolve is a Codex plugin for bounded algorithm search. It uses Monte Carlo Graph Search (MCGS), isolated candidate directories, objective evaluators, hard-constraint gates, and independent reviewer subagents to explore, score, and retain algorithm ideas.

It is especially useful for Kaggle and other deep-learning competitions, where an agent must iterate on data processing, feature engineering, model architecture, training strategy, validation, and ensemble ideas under a fixed compute or submission budget. The same workflow also applies to non-ML algorithms, optimization routines, prompts, configurations, and multi-step agent workflows.

The plugin includes two skills:

- `$algorithm-evolve` starts and runs a measurable search.
- `$algorithm-evolve-resume` reconstructs and continues an interrupted search from its local SQLite state.

## Installation

### Option A: Install as an official Codex plugin (recommended)

Codex installs GitHub plugins through a marketplace snapshot. This repository includes the required `.agents/plugins/marketplace.json` entry.

```bash
codex plugin marketplace add Azhi-ss/algorithm-evolve
codex plugin add algorithm-evolve --marketplace algorithm-evolve
```

Open a new Codex thread after installation. Verify the installation with:

```bash
codex plugin list
```

To update the marketplace snapshot and reinstall the latest version:

```bash
codex plugin marketplace upgrade algorithm-evolve
codex plugin add algorithm-evolve --marketplace algorithm-evolve
```

### Option B: Install the skills directly

This is the simplest installation and works in any Codex environment with local skill discovery.

```bash
export CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
git clone https://github.com/Azhi-ss/algorithm-evolve.git /tmp/algorithm-evolve
mkdir -p "$CODEX_HOME/skills"
cp -R /tmp/algorithm-evolve/skills/algorithm-evolve "$CODEX_HOME/skills/"
cp -R /tmp/algorithm-evolve/skills/algorithm-evolve-resume "$CODEX_HOME/skills/"
```

Start a new Codex thread after installation so the skills are discovered. Check that both directories exist:

```bash
ls "$CODEX_HOME/skills/algorithm-evolve" \
   "$CODEX_HOME/skills/algorithm-evolve-resume"
```

### Option C: Use it as a local plugin checkout

Keep the repository in a stable location when you want to update it with Git:

```bash
git clone https://github.com/Azhi-ss/algorithm-evolve.git ~/plugins/algorithm-evolve
```

The plugin manifest is at `.codex-plugin/plugin.json`, and the skills are under `skills/`. If your Codex installation uses a personal or team marketplace, add this checkout as the marketplace's `algorithm-evolve` source, then install `algorithm-evolve` from that marketplace. Follow your Codex version's `codex plugin marketplace` and `codex plugin add` commands for that configured marketplace.

To update a checkout:

```bash
git -C ~/plugins/algorithm-evolve pull --ff-only
```

If skills were copied into `$CODEX_HOME/skills`, repeat the two `cp -R` commands after pulling.

## Usage

### Start a search

Invoke the main skill with a concrete algorithm task, evaluator, and budget:

```text
$algorithm-evolve

Optimize this Kaggle image-classification solution. Compare the current baseline
with stronger augmentation, a different backbone, and a calibrated ensemble.
Use 10 iterations, a 30-minute evaluation budget, and maximize validation AUC.
Hard constraints: training must fit in the available GPU memory, inference must
finish within the submission limit, and every candidate must pass the smoke test.
Keep each candidate isolated and return the best candidate with evidence.
```

Before searching, the skill confirms a task contract in `.algorithm-evolve/<task-id>/task.json`. The contract should define:

- the goal and baseline;
- the evaluator, metric, or reviewer rubric;
- score direction (`maximize` or `minimize`);
- hard constraints;
- iteration, model-call, time, or compute budget.

For Kaggle, point the evaluator at a local validation split or a reproducible cross-validation command. Keep the competition test labels and any hidden evaluator data outside the generator subagents' context.

### Search lifecycle

The main skill coordinates the following loop:

1. Inspect the project, tests, benchmark, and current baseline.
2. Initialize a task-scoped SQLite database.
3. Add a baseline or first proposal as an isolated candidate.
4. Select a finalized node with UCT.
5. Ask generator subagents to propose, refine, repair, or fuse one bounded idea.
6. Evaluate the candidate with an execution subagent, or with three independent judgment reviewers.
7. Record constraint and score evidence, then finalize the node.
8. Backpropagate a coarse rollout reward and continue until the budget, target, stagnation, or another stop reason is reached.

The state tool never executes candidate code. Candidate execution stays in the host sandbox and follows the project's permissions.

### Resume an interrupted search

Use the resume skill in a new turn or after an interrupted run:

```text
$algorithm-evolve-resume
Continue the interrupted Kaggle model search in this workspace.
```

The skill reads `.algorithm-evolve/*/state.db` and reports the next required action. It can continue pending constraint checks, objective evaluations, reviewer calls, finalization, or the next MCGS expansion without reinitializing the task or duplicating recorded evaluations.

The command behind the skill is:

```bash
python3 skills/algorithm-evolve/scripts/search_state.py \
  --db .algorithm-evolve/<task-id>/state.db resume \
  --task-id <task-id>
```

State is local and queryable:

```text
.algorithm-evolve/<task-id>/
  task.json       # confirmed task contract
  state.db        # tasks, nodes, edges, and evaluations
  candidates/     # isolated candidate artifacts
  evidence/       # evaluator and reviewer evidence
```

### Inspect state manually

```bash
STATE_TOOL="skills/algorithm-evolve/scripts/search_state.py"
DB=".algorithm-evolve/<task-id>/state.db"

python3 "$STATE_TOOL" --db "$DB" status --task-id <task-id>
python3 "$STATE_TOOL" --db "$DB" resume --task-id <task-id>
python3 "$STATE_TOOL" --db "$DB" best --task-id <task-id>
python3 "$STATE_TOOL" --db "$DB" query --task-id <task-id> --text "augmentation"
```

All commands emit JSON. The database is the source of truth for recovery; conversation history is not required.

## Kaggle Guidance

- Use a fixed local validation split or deterministic cross-validation seed.
- Record the exact dataset version, preprocessing configuration, seed, hardware, and evaluator command as evidence.
- Treat GPU memory, runtime, package versions, and submission format as hard constraints.
- Compare every candidate with the same evaluation protocol; do not transfer scores between unrelated tasks.
- Keep generated candidates and notebooks isolated so a failed experiment cannot overwrite the source project.
- Use `fuse` only after independent branches have evidence that their mechanisms are compatible.
- Rerun the winning candidate from a clean copy before claiming an improvement.

## Repository Layout

```text
.codex-plugin/plugin.json
.agents/plugins/marketplace.json
skills/
  algorithm-evolve/
    SKILL.md
    agents/openai.yaml
    references/protocol.md
    scripts/search_state.py
  algorithm-evolve-resume/
    SKILL.md
    agents/openai.yaml
```

## Development Checks

Run the state lifecycle tests and plugin validator from the repository root:

```bash
python3 -m unittest discover -s skills/algorithm-evolve/scripts -p 'test_*.py'
python3 /path/to/skill-creator/scripts/quick_validate.py skills/algorithm-evolve
python3 /path/to/skill-creator/scripts/quick_validate.py skills/algorithm-evolve-resume
python3 /path/to/plugin-creator/scripts/validate_plugin.py .
```

## License

Apache-2.0. See `.codex-plugin/plugin.json` for plugin metadata.
