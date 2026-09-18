# ABC208 E Digit Products — limit-test evidence pack

Status: **harness parked; Arm A/B not yet run.** Local evaluator + official/adversarial expects are cross-checked. Do **not** claim AtCoder AC. `submit=0`.

STATE_DIR is **new**: `.algorithm-evolve/abc208-e-limit-fixed` (did not reuse older ABC runs). Product files (`skills/`, evoK / gates / runGoldenPath / Broker / `search_state.py`) were not modified.

## Locks (pre-loop)

| Field | Value |
|---|---|
| Repo | `github.com/Azhi-ss/algorithm-evolve` |
| Tip | `1b68978` (main, PW-1 present) |
| Evidence branch | `cursor/abc208-e-limit-fixed-79b2` |
| Cloud run | `bc-71cbf5ad-d8ab-50d5-aa4e-b0b8cecf79b2` |
| STATE_DIR | `.algorithm-evolve/abc208-e-limit-fixed` |
| Selection | product default **`fixed_uct` only**. No Progressive. `#40` SelectionPolicy off. Elite ≠ promotion |
| submit | **0** |
| NEWAPI host | `newapi.ai-modeling.top` |
| Model rotate (lead) | `gemini-3.8-flash` → `gemini-3.7-flash-high` → `gemini-flash-latest` |
| Forbidden sole LONG | `coding-deepseek-*`, `deepseek-v4-*-ga`, GPT* — not in rotate |
| Company repo | absent |

Pre-loop smoke: `GET /models` HTTP 200 (34 ids). Short `gemini-3.8-flash` ping HTTP 200, content `PONG`.

## Local gate (expects cross-checked)

Official: `(13,2)→5`; `(100,80)→99`; `(10^18,10^9)→841103275147365677`.

Adversarial expects = brute (`N≤1010`) ∩ reference digit-DP (`leading_zero` + overflow bucket `K+1`):

| id | input | expect | intent |
|---|---|---|---|
| adv_multizero_1010 | 1010 1 | 194 | leading zeros / multi-zero tight bound |
| adv_overflow_then_zero | 290 5 | 75 | keep overflow; later 0 resets product |
| adv_n1_positive | 1 1 | 1 | do not count x=0 |
| official3 | sample 3 | 841103275147365677 | 64-bit |
| hold_overflow_590 | 590 4 | 129 | holdout overflow-then-0 |
| hold_n10 | 10 1 | 2 | holdout x=0 / small |

Seed pass vectors (scripted, no LLM):

| candidate | o1 | o2 | o3 | 1010 | ovf→0 | n=1 | hold590 | n=10 | score |
|---|---|---|---|---|---|---|---|---|---|
| baseline-nolead | F | F | F | F | F | F | F | F | 0 |
| control-discard-overflow | T | T | F | F | F | T | F | T | 4 |

Wrong-baseline falsified **before the loop**: CONTROL passes official 1–2 and still fails `adv_overflow_then_zero` (60 vs 75) and `adv_multizero_1010` (26 vs 194). Official 3 also differs (`779710487084330517`) — same discard bug at scale.

## Arm A / Arm B

To be filled after the live loop and the one-shot control.

## Layout

```
evidence/2026-09-19-limit-test-abc208-e/   # this report
.algorithm-evolve/abc208-e-limit-fixed/    # gitignored live tree
```
