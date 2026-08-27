---
name: algorithm-evolve-resume
description: Inspect and continue an interrupted Algorithm Evolve search from its local SQLite state. Use when the user asks to resume, continue, recover, or report progress for an algorithm optimization previously started with algorithm-evolve, or explicitly invokes $algorithm-evolve-resume.
---

# Resume Algorithm Evolve

Recover the search from persisted state, not conversation memory. Resume existing work without reinitializing the task or duplicating completed evaluations.

## Locate State

1. Work from the target project's root. Find `.algorithm-evolve/*/state.db` without searching outside the current workspace.
2. If no database exists, report that no search can be resumed. Do not create a new task unless the user asks to start one.
3. If several databases exist and the user did not identify a task, show their task IDs and status, then ask which one to continue.
4. Resolve the shared state tool and original workflow relative to this file:

```text
../algorithm-evolve/scripts/search_state.py
../algorithm-evolve/SKILL.md
../algorithm-evolve/references/protocol.md
```

Read the original Skill and protocol before continuing the search.

## Reconstruct The Next Step

Run:

```bash
python3 "$STATE_TOOL" --db "$DB" resume
```

Use `--task-id` when a database contains more than one task. Treat the returned `next_action` as authoritative:

- `resume_pending_nodes`: continue each pending node from its `resume.action`.
  - `record_constraints`: run and record the confirmed hard constraints.
  - `run_objective_evaluation`: run the task's existing evaluator in the host sandbox and record its evidence.
  - `run_judgment_reviews`: spawn only the reported number of missing independent reviewers.
  - `finalize_rejection` or `finalize_node`: finalize without rerunning completed work.
- `create_baseline`: create and evaluate the baseline using the original Skill.
- `repair_or_propose`: inspect the last rejected node, then perform one bounded repair or create a fresh proposal.
- `select_and_expand`: run `select`, then continue the original MCGS loop from the selected node.
- `finish_or_request_new_budget`: do not start new work. Report the best result and stop reasons; require user confirmation before creating a new budgeted task.

If `artifact_exists` is false, do not evaluate that pending node. Report the missing candidate path and ask whether to reconstruct or abandon it.

## Continue Safely

- Do not attempt to resume an old subagent process. Recreate only the missing action from SQLite evidence.
- Do not rerun an evaluation already recorded unless its artifact changed or its evidence is missing.
- Do not add a second node for an existing pending candidate.
- After every resumed action, run `resume` again and follow the new snapshot until the task stops or the user interrupts it.
- Preserve the original source project; keep all candidates isolated as required by `algorithm-evolve`.
