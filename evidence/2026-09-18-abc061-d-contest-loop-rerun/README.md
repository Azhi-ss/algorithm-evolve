# ABC061 D Score Attack — Gemini-led contest-loop rerun

Success on the **local** criterion: reviewable cycle-affects-N strategy, and the adversarial gate falsifies the wrong baseline. **Not** AtCoder AC. `submit=0`.

STATE_DIR is **new**: `.algorithm-evolve/abc061-d-gemini-rerun` (did not reuse `abc061-d-fixed`). `/workspace/company` was absent; the loop used this repo’s `skills/algorithm-evolve/scripts/search_state.py` only. Product files (evoK / gates / runGoldenPath / Broker / `search_state.py`) were not modified.

## Tip / env / models (no secrets)

| Field | Value |
|---|---|
| Repo | `github.com/Azhi-ss/algorithm-evolve` |
| Tip | `1b68978aa0206871f80a4e3f9bd12e9ef9fbfe5b` (main, PW-1 present) |
| Evidence branch | `cursor/abc061-d-gemini-rerun-1160` |
| Cloud run | `bc-e4e8121f-6b85-5f8b-8c31-4f2dbe021160` |
| Env public id | `77f55ea9-aab6-11f1-b532-320a589b8025` |
| Boot build | `bld-20260917-20bd9f86-2cef-4e5d-89aa-5574dd31a568` |
| Python | 3.12.3 |
| STATE_DIR | `.algorithm-evolve/abc061-d-gemini-rerun` |
| Selection | product default **`fixed_uct` only**. Every live `select` payload keys = `{selected, uct}`. No `--selection-id`, no Progressive, `#40` off |
| submit | **0** |
| NEWAPI host | `newapi.ai-modeling.top` (base path already `/v1`) |
| Chat helper | `curl` + User-Agent (avoids Cloudflare 1010) |
| Model rotate (lead) | `gemini-3.8-flash` → `gemini-3.7-flash-high` → `gemini-flash-latest` |
| Optional (not needed) | `gemini-3.6-flash-high`, `gemini-pro-agent` |
| Forbidden sole LONG | `coding-deepseek-*`, `deepseek-v4-*-ga` — **never invoked** |
| Gateway remaps | request `gemini-3.7-flash-high` → response `gemini-3.7-flash`; request `gemini-flash-latest` → response `gemini-3.8-flash` |
| Live LLM nodes | 8 (`model_calls=8`); wall **84.9s** |
| Tree size | 10 finalized (1 baseline + 1 CONTROL + 8 Gemini) |
| Best | `n-a8da5ab309b3` score **7.0** |
| Company repo | absent |

Pre-loop smoke: `GET /models` HTTP 200 (34 ids). Short `gemini-3.8-flash` ping HTTP 200, content `PONG`, ~2.5s.

## parent_id sequence

Single spine. `select` always default UCT; first expansion chose CONTROL (reward 1.0 vs baseline 0.5).

```
n-3c3139c2291a  baseline     score 4  reward 0.5  baseline-naive-bf
 └─ n-afce586694ab  propose  score 6  reward 1.0  control-any-pos-cycle
     └─ n-a8da5ab309b3  refine   score 7  reward 1.0  refine-01-gemini   ★ first all-green / best
         └─ n-444f77f82b35  refine  score 7  reward 0.5  refine-02-gemini
             └─ n-4353106fa4a1  propose score 7  reward 0.5  propose-03-gemini
                 └─ n-7e4331b57487  propose score 7  reward 0.5  propose-04-gemini
                     └─ n-3d9a1fbe3522  propose score 6  reward 0.0  propose-05-gemini  (slow-pump WA)
                         └─ n-626241106819  propose score 7  reward 1.0  propose-06-gemini
                             └─ n-700e6ac54adf  refine  score 7  reward 0.5  refine-07-gemini
                                 └─ n-c459218b7168  propose score 6  reward 0.0  propose-08-gemini  (2N-iter WA)
```

| step | action | parent_id | child_id | UCT | requested model |
|---|---|---|---|---|---|
| seed | baseline | — | `n-3c3139c2291a` | — | scripted |
| seed | propose | `n-3c3139c2291a` | `n-afce586694ab` | — | scripted CONTROL |
| 1 | refine | `n-afce586694ab` | `n-a8da5ab309b3` | 2.482 | `gemini-3.8-flash` |
| 2 | refine | `n-a8da5ab309b3` | `n-444f77f82b35` | 2.665 | `gemini-3.7-flash-high` |
| 3 | propose | `n-444f77f82b35` | `n-4353106fa4a1` | 2.294 | `gemini-flash-latest` |
| 4 | propose | `n-4353106fa4a1` | `n-7e4331b57487` | 2.393 | `gemini-3.8-flash` |
| 5 | propose | `n-7e4331b57487` | `n-3d9a1fbe3522` | 2.473 | `gemini-3.7-flash-high` |
| 6 | propose | `n-3d9a1fbe3522` | `n-626241106819` | 2.039 | `gemini-flash-latest` |
| 7 | refine | `n-626241106819` | `n-700e6ac54adf` | 3.096 | `gemini-3.8-flash` |
| 8 | propose | `n-700e6ac54adf` | `n-c459218b7168` | 2.646 | `gemini-3.7-flash-high` |

Post-loop default `select` still returns only `{selected, uct}`.

## Propose summaries (cycle-affects-N check?)

| node | checks_cycle_affects_n | idea |
|---|---|---|
| baseline | n/a (false in code) | N−1 longest-path BF; no inf rule |
| CONTROL | **no** | any +cycle reachable from 1 ⇒ `inf` |
| refine-01 ★ | **true** | filter `from1 ∩ toN`, then BF extra-relax ⇒ `inf` |
| refine-02 | true | same filter + induced-subgraph BF |
| propose-03 | true | SPFA on negated weights; count≥N only if vertex can reach N |
| propose-04 | true | reverse-BFS to N, then N BF iters on remaining graph |
| propose-05 | claimed true, **weak** | extra N rounds; `inf` only if **dist[N] itself** keeps rising |
| propose-06 | true | forward+backward BFS path vertices, then BF |
| refine-07 | true | two BFS + induced BF |
| propose-08 | claimed true, **weak** | negate weights; `inf` iff dist[N] changes between iter N and 2N |

Winner strategy (reviewable): BFS from 1; reverse-BFS from N; keep edges whose both ends are in the intersection; longest-path Bellman-Ford; one extra relaxation on that subgraph prints `inf`, else `dist[N]`. That is exactly “positive cycle only counts if it can still affect N”.

## Pass vectors (official + adversarial)

Case order: official1=`7` · official2=`inf` · official3=`-5000000000` · side-cycle finite=`5` · cycle→N=`inf` · int64=`4000000000` · slow-pump=`inf`.

| candidate | o1 | o2 | o3 | side finite | cycle→N | int64 | slow pump | score |
|---|---|---|---|---|---|---|---|---|
| baseline-naive-bf | T | **F** | T | T | **F** | T | **F** | 4 |
| control-any-pos-cycle | T | T | T | **F (got inf)** | T | T | T | 6 |
| refine-01-gemini ★ | T | T | T | T | T | T | T | **7** |
| refine-02-gemini | T | T | T | T | T | T | T | 7 |
| propose-03-gemini | T | T | T | T | T | T | T | 7 |
| propose-04-gemini | T | T | T | T | T | T | T | 7 |
| propose-05-gemini | T | T | T | T | T | T | **F** | 6 |
| propose-06-gemini | T | T | T | T | T | T | T | 7 |
| refine-07-gemini | T | T | T | T | T | T | T | 7 |
| propose-08-gemini | T | T | T | T | T | T | **F** | 6 |
| winner-clean-copy | T | T | T | T | T | T | T | **7** |

Official trio is included on every node. Adversarial trio is included on every node. Extra editorial `adv_slow_pump_inf` caught the “2N-th iteration only watches N” class (propose-05 / propose-08).

## First all-green step / score

- **Step 1 / `refine-01` / `n-a8da5ab309b3`**
- Model: `gemini-3.8-flash` (requested = response)
- Score: **7.0 / 7**
- Reward: 1.0 (improved CONTROL 6 → 7)
- Stored `best_node_id` remains this node
- Clean re-eval of a copied `solve.py` matches the stored vector and score exactly

## Wrong baseline falsified?

**Yes.** CONTROL `n-afce586694ab` passes official `7` / `inf` / `-5000000000` and still fails `adv_side_cycle_finite` (prints `inf`, expect `5`). That is the intended “any +cycle ⇒ inf” counterexample: cycle `2↔3` is reachable from 1 but cannot reach N=4; the only finishing path is `1→4` score 5.

Naive baseline additionally fails official2 and both +cycle-reaches-N fixtures.

## Yellow notes

- `/workspace/company` was not on the VM. Loop is algorithm-evolve live-tree + local evaluator + NEWAPI Gemini. No evoK / Broker / runGoldenPath edits.
- Context7 MCP is not in this run’s dynamic namespaces.
- `coding-deepseek-*` and `deepseek-v4-*-ga` were catalog-present but **not called** (prior RCA: LONG HTTP 524 / empty 200). No DeepSeek yellow this run because they were never the sole LONG propose.
- `gemini-flash-latest` is remapped by the gateway to `gemini-3.8-flash`. Optional `gemini-3.6-flash-high` / `gemini-pro-agent` were not needed (primary rotate never exhausted).
- Two Gemini proposes (05, 08) claimed `checks_cycle_affects_n=true` but only watched whether **vertex N** updated in a bounded extra window — official samples + the side-cycle case still pass; editorial slow-pump fails. Gate is doing work.
- Action heuristic treated “any positive cycle” as a CONTROL marker, so step 2 stayed `refine` even after all-green. Later steps did `propose` and produced SPFA / 2N-iter variants.
- Wall time **~85s** (under the 30–60 min envelope) because Gemini returned code in ~6–16s and no DeepSeek LONG waits occurred. Candidate count **10** is inside 8–12.
- Host loop replaces skill-text “generator subagents” with NEWAPI curl, same as the prior ABC061/ABC088 tryouts. Evaluator never talks to AtCoder.
- Evidence-only Git commit. Product `skills/` tree unchanged. Prefer no product PR; this folder is the deliverable.

## Conclusion

Reasonable Gemini-led strategy exists (filter 1-reach ∩ N-reach, then BF). The local gate **does** kill the official-passing “any +cycle ⇒ inf” control and the “watch N on iteration 2N” class. Do not claim AtCoder AC.

## Layout

```
evidence/2026-09-18-abc061-d-contest-loop-rerun/   # this report (committed)
.algorithm-evolve/abc061-d-gemini-rerun/           # gitignored live tree
  task.json  state.db  evaluator/  candidates/  evidence/  tools/  logs/
/opt/cursor/artifacts/abc061-d-gemini-rerun/       # artifact copy
```
