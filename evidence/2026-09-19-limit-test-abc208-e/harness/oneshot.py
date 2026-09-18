#!/usr/bin/env python3
"""Arm B: one-shot Gemini propose. No search tree, no iterative falsify. submit=0."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/workspace/.algorithm-evolve/abc208-e-limit-fixed")
EVAL = ROOT / "evaluator" / "evaluate.py"
PROBLEM = (ROOT / "seed" / "problem.md").read_text(encoding="utf-8")

sys.path.insert(0, str(ROOT / "tools"))
from extract_candidate import extract, write_candidate  # noqa: E402
from llm_chat import chat, host_only  # noqa: E402

PRIMARY = "gemini-3.8-flash"
OPTIONAL = ["gemini-3.7-flash-high", "gemini-flash-latest"]
FORBIDDEN_SOLE_LONG = ("coding-deepseek-", "deepseek-v4-", "gpt-", "chatgpt")

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
This is a single shot: there is no parent, no search tree, and no hidden test feedback.
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    out_dir = ROOT / "oneshot"
    ev_dir = out_dir / "evidence"
    ev_dir.mkdir(parents=True, exist_ok=True)
    messages = [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": (
                PROBLEM
                + "\n\nAction: propose\nParent: none. One-shot control — write a complete correct solver.\n"
            ),
        },
    ]
    (ev_dir / "prompt.txt").write_text(messages[1]["content"], encoding="utf-8")
    yellows = []
    extracted = None
    used = None
    reply = None
    for model in [PRIMARY, *OPTIONAL]:
        lower = model.lower()
        if any(bad in lower for bad in FORBIDDEN_SOLE_LONG):
            raise RuntimeError(f"forbidden model leaked: {model}")
        reply = chat(model, messages, temperature=0.3, max_tokens=8000, timeout=180)
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
            yellows.append({"model": model, "note": "empty_or_http_fail", "http_code": reply["http_code"]})
            continue
        extracted = extract(reply["content"])
        if not extracted["ok"]:
            yellows.append({"model": model, "note": extracted["error"]})
            continue
        used = model
        break
    if extracted is None or not extracted["ok"]:
        summary = {
            "ok": False,
            "arm": "B_oneshot",
            "submit": 0,
            "host": host_only(),
            "yellows": yellows,
        }
        (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 2
    cand = out_dir / "candidate"
    write_candidate(
        cand,
        extracted,
        {
            "action": "oneshot_propose",
            "requested_model": used,
            "response_model": reply["response_model"] if reply else used,
            "host": host_only(),
            "submit": 0,
            "tree": False,
        },
    )
    ev = out_dir / "eval.json"
    subprocess.run(
        [sys.executable, str(EVAL), "--candidate", str(cand), "--out", str(ev)],
        text=True,
        capture_output=True,
    )
    report = json.loads(ev.read_text(encoding="utf-8"))
    official_ok = all(report["pass_vector"].get(k) for k in ("official1", "official2", "official3"))
    missed_by_official = {
        cid: ok
        for cid, ok in report["pass_vector"].items()
        if cid not in {"official1", "official2", "official3"}
    }
    fails_hidden = [cid for cid, ok in missed_by_official.items() if not ok]
    summary = {
        "ok": True,
        "arm": "B_oneshot",
        "submit": 0,
        "host": host_only(),
        "requested_model": used,
        "response_model": reply.get("response_model") if reply else used,
        "idea": extracted["idea"],
        "keeps_overflow_for_later_zero": extracted.get("keeps_overflow_for_later_zero"),
        "leading_zero_flag": extracted.get("leading_zero_flag"),
        "score": report["score"],
        "max_score": report["max_score"],
        "pass_vector": report["pass_vector"],
        "all_green": report.get("all_green"),
        "official_all_green": official_ok,
        "fails_adversarial_official_would_miss": fails_hidden,
        "missed_hidden_while_official_green": bool(official_ok and fails_hidden),
        "yellows": yellows,
        "ts": now(),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
