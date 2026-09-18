#!/usr/bin/env python3
"""Gemini-led ABC208 E contest-loop. Product-default fixed_uct only. submit=0."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/workspace/.algorithm-evolve/abc208-e-limit-fixed")
STATE_TOOL = Path("/workspace/skills/algorithm-evolve/scripts/search_state.py")
TASK_ID = "abc208-e-limit-fixed"
DB = ROOT / "state.db"
EVAL = ROOT / "evaluator" / "evaluate.py"
PROBLEM = (ROOT / "seed" / "problem.md").read_text(encoding="utf-8")

sys.path.insert(0, str(ROOT / "tools"))
from extract_candidate import extract, write_candidate  # noqa: E402
from llm_chat import chat, host_only  # noqa: E402

PRIMARY_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.7-flash-high",
    "gemini-flash-latest",
]
OPTIONAL_MODELS = [
    "gemini-3.6-flash-high",
    "gemini-pro-agent",
]
FORBIDDEN_SOLE_LONG = (
    "coding-deepseek-",
    "deepseek-v4-",
    "gpt-",
    "chatgpt",
    "o1-",
    "o3-",
    "o4-",
)
TARGET_NODES = 10
MAX_NODES = 12
TIME_BUDGET_SEC = 55 * 60
LLM_TIMEOUT = 180
LLM_MAX_TOKENS = 8000

FORBIDDEN_SELECT_FLAGS = (
    "--selection-id",
    "--progressive-mcgs-optin",
    "--progressive-t",
    "--progressive-horizon",
    "--progressive-seed",
    "progressive_mcgs_optin",
)

SYSTEM = """You are generating an isolated Python 3 solution for AtCoder ABC208 E Digit Products.
Hard locks: no network, no AtCoder submit, stdin/stdout only.
Write a complete solve.py that reads "N K" and prints one integer: how many positive integers x<=N have digit-product <=K.
Return JSON only with keys:
  idea: one-sentence strategy
  keeps_overflow_for_later_zero: true if a state with product already >K is kept because a later digit 0 resets the product to 0<=K
  leading_zero_flag: true if leading zeros are NOT multiplied into the product
  solve_py: full Python source
Do not wrap the JSON in markdown.
Use Python int (unlimited). Do not cast the answer to 32-bit.
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_event(kind: str, payload: dict) -> None:
    path = ROOT / "logs" / "loop.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = {"ts": now(), "kind": kind, **payload}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(rec, sort_keys=True) + "\n")


def run_state(*args: str) -> dict:
    for flag in args:
        for banned in FORBIDDEN_SELECT_FLAGS:
            if banned in flag:
                raise RuntimeError(f"progressive/selection flag forbidden: {flag}")
    cmd = [sys.executable, str(STATE_TOOL), "--db", str(DB), *args]
    proc = subprocess.run(cmd, text=True, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"state {' '.join(args)} failed: {proc.stderr or proc.stdout}")
    return json.loads(proc.stdout)


def evaluate(candidate: Path, out: Path) -> dict:
    subprocess.run(
        [sys.executable, str(EVAL), "--candidate", str(candidate), "--out", str(out)],
        text=True,
        capture_output=True,
    )
    return json.loads(out.read_text(encoding="utf-8"))


def record_finalize(node_id: str, report: dict, evidence: Path) -> dict:
    constraint = run_state(
        "record",
        "--node",
        node_id,
        "--kind",
        "constraint",
        "--passed",
        "true" if report["passed_constraints"] else "false",
        "--evidence",
        str(evidence),
    )
    objective = run_state(
        "record",
        "--node",
        node_id,
        "--kind",
        "objective",
        "--score",
        str(report["score"]),
        "--evidence",
        str(evidence),
    )
    finalized = run_state("finalize", "--node", node_id)
    return {"constraint": constraint, "objective": objective, "finalize": finalized}


def seed_scripted() -> None:
    if not DB.exists():
        run_state("init", "--task", str(ROOT / "task.json"))
    status = run_state("status", "--task-id", TASK_ID)
    if (status.get("iterations") or 0) > 0 or (status.get("pending") or 0) > 0 or status.get("best_node_id"):
        return
    base_art = ROOT / "candidates" / "baseline-nolead"
    base = run_state(
        "add-node",
        "--task-id",
        TASK_ID,
        "--action",
        "baseline",
        "--artifact",
        str(base_art),
        "--idea",
        "BASELINE: digit DP without leading_zero; leading zeros are multiplied into the product",
        "--model-calls",
        "0",
    )
    ev = ROOT / "evidence" / "baseline-nolead.json"
    report = evaluate(base_art, ev)
    rec = record_finalize(base["node_id"], report, ev)
    log_event(
        "baseline",
        {
            "node_id": base["node_id"],
            "score": report["score"],
            "pass_vector": report["pass_vector"],
            "reward": rec["finalize"].get("reward"),
        },
    )
    ctrl_art = ROOT / "candidates" / "control-discard-overflow"
    ctrl = run_state(
        "add-node",
        "--task-id",
        TASK_ID,
        "--action",
        "propose",
        "--artifact",
        str(ctrl_art),
        "--idea",
        "CONTROL: digit DP with leading_zero but discards overflow product; does not keep overflow for later zero",
        "--parent",
        base["node_id"],
        "--model-calls",
        "0",
    )
    ev2 = ROOT / "evidence" / "control-discard-overflow.json"
    report2 = evaluate(ctrl_art, ev2)
    rec2 = record_finalize(ctrl["node_id"], report2, ev2)
    official = report2["pass_vector"]
    log_event(
        "control",
        {
            "node_id": ctrl["node_id"],
            "parent_id": base["node_id"],
            "score": report2["score"],
            "pass_vector": report2["pass_vector"],
            "reward": rec2["finalize"].get("reward"),
            "falsifies_discard_overflow": (
                official.get("official1")
                and official.get("official2")
                and official.get("adv_overflow_then_zero") is False
            ),
        },
    )


def choose_action(parent: dict, step: int, have_all_green: bool) -> str:
    idea = (parent.get("idea") or "").lower()
    score = parent.get("effective_score")
    if parent.get("status") == "rejected":
        return "repair"
    if "discard" in idea or "does not keep overflow" in idea:
        return "refine"
    if have_all_green:
        return "propose"
    if score is not None and score < 6:
        return "refine"
    return "propose" if step % 3 == 1 else "refine"


def rotate_models(step: int) -> list[str]:
    start = (step - 1) % len(PRIMARY_MODELS)
    ordered = PRIMARY_MODELS[start:] + PRIMARY_MODELS[:start] + OPTIONAL_MODELS
    for name in ordered:
        lower = name.lower()
        if any(bad in lower for bad in FORBIDDEN_SOLE_LONG):
            raise RuntimeError(f"forbidden model leaked into rotate: {name}")
    return ordered


def build_user_prompt(action: str, parent: dict, step: int, have_all_green: bool) -> str:
    parent_idea = parent.get("idea") or ""
    parent_art = Path(parent.get("artifact") or "")
    parent_code = ""
    if parent_art:
        for name in ("solve.py", "solution.py", "main.py"):
            p = parent_art / name
            if p.is_file():
                parent_code = p.read_text(encoding="utf-8")
                break
    extra = ""
    if action == "refine" and ("discard" in parent_idea.lower() or "does not keep overflow" in parent_idea.lower()):
        extra = (
            "The parent discards a digit-DP state when the running product already exceeds K. "
            "That is wrong: a later digit 0 resets the product to 0, which is still <=K, "
            "so those numbers must be counted. Keep an overflow bucket (or equivalent) "
            "instead of dropping the state. Also keep a leading_zero flag so padded zeros "
            "are not multiplied into the product, and do not count x=0. Use Python int."
        )
    elif have_all_green:
        flavors = [
            "Digit DP on (pos, tight, leading_zero, compressed product); overflow bucket survives for a later 0.",
            "Iterate number length, then unrestricted product DP for shorter lengths plus a tight pass for |N|.",
            "Factor-exponent state (2,3,5,7) plus a seen-zero flag, with an overflow/inf bucket.",
            "Memoized DFS over digits with product capped at K+1; leading zeros keep product=1.",
            "Count complement: total positives <=N minus those whose digit product is >K and contain no zero.",
        ]
        extra = (
            "Parent already scores well. Write a materially different correct implementation. "
            + flavors[(step - 1) % len(flavors)]
        )
    return (
        f"{PROBLEM}\n\nAction: {action}\nParent idea: {parent_idea}\n"
        f"Parent score: {parent.get('effective_score')}\n"
        f"{extra}\n\nParent solve.py:\n{parent_code}\n"
    )


def propose_with_gemini(step: int, action: str, parent: dict, have_all_green: bool) -> dict:
    models = rotate_models(step)
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": build_user_prompt(action, parent, step, have_all_green)},
    ]
    arm = f"{action}-{step:02d}"
    ev_dir = ROOT / "evidence" / arm
    ev_dir.mkdir(parents=True, exist_ok=True)
    (ev_dir / "prompt.txt").write_text(messages[1]["content"], encoding="utf-8")
    yellows = []
    for model in models:
        reply = chat(
            model,
            messages,
            temperature=0.35 if action == "propose" else 0.25,
            max_tokens=LLM_MAX_TOKENS,
            timeout=LLM_TIMEOUT,
        )
        (ev_dir / f"reply-{model}.txt").write_text(reply.get("content") or "", encoding="utf-8")
        (ev_dir / f"meta-{model}.json").write_text(
            json.dumps(
                {
                    "requested_model": reply["requested_model"],
                    "response_model": reply["response_model"],
                    "http_code": reply["http_code"],
                    "elapsed_sec": reply["elapsed_sec"],
                    "content_len": reply["content_len"],
                    "usage": reply.get("usage") or {},
                    "ok": reply["ok"],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        if not reply["ok"]:
            yellows.append(
                {
                    "model": model,
                    "http_code": reply["http_code"],
                    "content_len": reply["content_len"],
                    "elapsed_sec": reply["elapsed_sec"],
                    "note": "empty_or_http_fail",
                }
            )
            continue
        extracted = extract(reply["content"])
        if not extracted["ok"]:
            yellows.append({"model": model, "note": extracted["error"]})
            continue
        cand = ROOT / "candidates" / f"{arm}-{model.split('-')[0]}"
        write_candidate(
            cand,
            extracted,
            {
                "action": action,
                "step": step,
                "requested_model": model,
                "response_model": reply["response_model"],
                "usage": reply.get("usage") or {},
                "yellows": yellows,
                "host": host_only(),
                "submit": 0,
            },
        )
        (ev_dir / "llm_reply.txt").write_text(reply["content"], encoding="utf-8")
        return {
            "ok": True,
            "candidate": cand,
            "idea": extracted["idea"],
            "keeps_overflow_for_later_zero": extracted["keeps_overflow_for_later_zero"],
            "leading_zero_flag": extracted["leading_zero_flag"],
            "model": model,
            "response_model": reply["response_model"],
            "yellows": yellows,
            "arm": arm,
        }
    return {"ok": False, "yellows": yellows, "arm": arm, "models": models}


def main() -> int:
    started = time.time()
    ROOT.joinpath("logs").mkdir(parents=True, exist_ok=True)
    seed_scripted()
    have_all_green = False
    first_green = None
    step = 0
    while True:
        status = run_state("status", "--task-id", TASK_ID)
        finalized = int(status.get("iterations") or 0) + (1 if status.get("best_node_id") else 0)
        elapsed = time.time() - started
        if finalized >= TARGET_NODES or elapsed >= TIME_BUDGET_SEC or finalized >= MAX_NODES:
            log_event(
                "stop",
                {
                    "reason": "budget",
                    "finalized_nodes": finalized,
                    "elapsed_sec": elapsed,
                    "status": status,
                },
            )
            break
        if status.get("stopped"):
            log_event("stop", {"reason": "state_stopped", "status": status, "elapsed_sec": elapsed})
            break
        selected_payload = run_state("select", "--task-id", TASK_ID)
        extra_keys = set(selected_payload) - {"selected", "uct"}
        if extra_keys & {"selection_id", "progressive_t", "selection_mode", "progressive"}:
            raise RuntimeError(f"select payload leaked progressive keys: {sorted(extra_keys)}")
        parent = selected_payload.get("selected")
        if not parent:
            log_event("stop", {"reason": "no_parent", "payload": selected_payload})
            break
        step += 1
        action = choose_action(parent, step, have_all_green)
        log_event(
            "select",
            {
                "step": step,
                "parent_id": parent.get("id"),
                "parent_score": parent.get("effective_score"),
                "action": action,
                "select_keys": sorted(selected_payload),
                "uct": selected_payload.get("uct"),
            },
        )
        proposed = propose_with_gemini(step, action, parent, have_all_green)
        if not proposed["ok"]:
            log_event("llm_fail", {"step": step, "action": action, "yellows": proposed.get("yellows")})
            if step >= 8:
                break
            continue
        added = run_state(
            "add-node",
            "--task-id",
            TASK_ID,
            "--action",
            action,
            "--artifact",
            str(proposed["candidate"]),
            "--idea",
            proposed["idea"][:400],
            "--parent",
            parent["id"],
            "--model-calls",
            "1",
        )
        ev = ROOT / "evidence" / f"{proposed['candidate'].name}.json"
        report = evaluate(proposed["candidate"], ev)
        rec = record_finalize(added["node_id"], report, ev)
        if report.get("all_green") and first_green is None:
            have_all_green = True
            first_green = {
                "node_id": added["node_id"],
                "step": step,
                "score": report["score"],
                "arm": proposed["arm"],
                "model": proposed["model"],
            }
        log_event(
            "expand",
            {
                "step": step,
                "action": action,
                "parent_id": parent["id"],
                "child_id": added["node_id"],
                "model": proposed["model"],
                "response_model": proposed["response_model"],
                "idea": proposed["idea"],
                "keeps_overflow_for_later_zero": proposed.get("keeps_overflow_for_later_zero"),
                "leading_zero_flag": proposed.get("leading_zero_flag"),
                "score": report["score"],
                "pass_vector": report["pass_vector"],
                "all_green": report.get("all_green"),
                "reward": rec["finalize"].get("reward"),
                "yellows": proposed.get("yellows") or [],
            },
        )
    status = run_state("status", "--task-id", TASK_ID)
    try:
        best = run_state("best", "--task-id", TASK_ID)
    except RuntimeError as exc:
        best = {"error": str(exc)}
    summary = {
        "task_id": TASK_ID,
        "host": host_only(),
        "submit": 0,
        "selection": "fixed_uct_default",
        "primary_models": PRIMARY_MODELS,
        "optional_models": OPTIONAL_MODELS,
        "forbidden_sole_long": list(FORBIDDEN_SOLE_LONG),
        "elapsed_sec": time.time() - started,
        "status": status,
        "best": best,
        "first_all_green": first_green,
        "tip": subprocess.check_output(["git", "-C", "/workspace", "rev-parse", "HEAD"], text=True).strip(),
    }
    (ROOT / "logs" / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
