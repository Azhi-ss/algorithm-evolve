# ABC061 D Score Attack — Gemini-led contest-loop rerun

Status: **loop starting**. This README is updated after select→propose→eval→record finishes.

## Tip / env / models (no secrets)

| Field | Value |
|---|---|
| Repo | `github.com/Azhi-ss/algorithm-evolve` |
| Tip | `1b68978aa0206871f80a4e3f9bd12e9ef9fbfe5b` (main, PW-1 present) |
| Branch (evidence-only) | `cursor/abc061-d-gemini-rerun-1160` |
| Cloud run | `bc-e4e8121f-6b85-5f8b-8c31-4f2dbe021160` |
| Env public id | `77f55ea9-aab6-11f1-b532-320a589b8025` |
| Boot build | `bld-20260917-20bd9f86-2cef-4e5d-89aa-5574dd31a568` |
| Python | 3.12.3 |
| STATE_DIR | `.algorithm-evolve/abc061-d-gemini-rerun` (fresh; not `abc061-d-fixed`) |
| Selection | product default **`fixed_uct` only**. No `--selection-id` / Progressive / `#40` |
| submit | **0** (local fixtures only; no AtCoder) |
| NEWAPI host | `newapi.ai-modeling.top` (path `/v1`; do not double-prefix) |
| Model rotate (lead) | `gemini-3.8-flash` → `gemini-3.7-flash-high` → `gemini-flash-latest` |
| Optional Gemini | `gemini-3.6-flash-high`, `gemini-pro-agent` |
| Forbidden sole LONG propose | `coding-deepseek-*`, `deepseek-v4-*-ga` (RCA: LONG 524/timeout) |
| Product tree | skills / evoK / gates / runGoldenPath / Broker **unchanged** |
| `/workspace/company` | absent on this VM; loop uses this repo's `search_state.py` |

NEWAPI smoke (pre-loop): `GET /models` HTTP 200, 34 ids; short `gemini-3.8-flash` ping HTTP 200, content `PONG`, ~2.5s. Catalog includes DeepSeek ids; they are **not** used as sole LONG propose.

Context7 MCP: **not available** in this run's dynamic namespaces (yellow).

## Gate (official + adversarial)

Hardcoded expects. Score = pass count / 7.

| id | expect | why |
|---|---|---|
| official1 | `7` | official sample |
| official2 | `inf` | official +cycle through N |
| official3 | `-5000000000` | official 64-bit negative |
| adv_side_cycle_finite | `5` | +cycle from 1 cannot reach N; falsifies “any +cycle ⇒ inf” |
| adv_cycle_reaches_n | `inf` | +cycle from 1 can reach N |
| adv_int64 | `4000000000` | four +1e9; overflows int32 |
| adv_slow_pump_inf | `inf` | editorial 2024/2 weak-test; falsifies “N updated on 2N-th BF iter” |

Pre-loop scripted baselines (gate already useful):

| candidate | score | official | side finite | cycle→N | int64 | slow pump |
|---|---|---|---|---|---|---|
| baseline-naive-bf | 4 | T F T | T | F | T | F |
| control-any-pos-cycle | 6 | T T T | **F (got inf)** | T | T | T |

**Wrong baseline falsified:** yes — CONTROL passes all three official samples and still fails `adv_side_cycle_finite` (prints `inf` instead of `5`).

## parent_id sequence

_Filled after the loop._

## Propose summaries (cycle-affects-N?)

_Filled after the loop._

## Pass vectors

_Filled after the loop._

## First all-green / score

_Filled after the loop._

## Yellow notes

- Prior ABC061 tryout (`abc061-d-fixed`) showed DeepSeek LONG → HTTP 524 / empty content. This rerun forbids those ids as sole LONG propose.
- Cloudflare 1010 if chat lacks a User-Agent; helper uses curl + UA.
- `NEWAPI_BASE_URL` already ends with `/v1`.
- Context7 MCP missing.
- No product PR intended; this tree is evidence-only.

## Conclusion

_Pending live Gemini contest-loop._
