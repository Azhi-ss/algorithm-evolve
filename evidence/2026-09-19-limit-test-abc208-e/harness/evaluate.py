#!/usr/bin/env python3
"""Local ABC208 E gate. submit=0. Never talks to AtCoder."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CASES = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))
SOLVER_NAMES = ("solve.py", "solution.py", "main.py")
TOKEN_RE = re.compile(r"^-?\d+$")


def find_solver(candidate: Path) -> Path | None:
    for name in SOLVER_NAMES:
        path = candidate / name
        if path.is_file():
            return path
    return None


def run_case(solver: Path, text: str, timeout: float) -> dict:
    try:
        proc = subprocess.run(
            [sys.executable, str(solver)],
            input=text,
            text=True,
            capture_output=True,
            timeout=timeout,
            cwd=str(solver.parent),
        )
    except subprocess.TimeoutExpired:
        return {"status": "TLE", "got": None, "stderr": "timeout"}
    lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    got = lines[-1] if lines else ""
    if proc.returncode != 0:
        return {
            "status": "crash",
            "got": got or None,
            "stderr": (proc.stderr or "")[-400],
        }
    if not TOKEN_RE.fullmatch(got):
        return {"status": "illegal", "got": got or None, "stderr": (proc.stderr or "")[-200]}
    return {"status": "run", "got": got, "stderr": ""}


def evaluate(candidate: Path) -> dict:
    timeout = float(CASES.get("timeout_sec", 3.0))
    solver = find_solver(candidate)
    results = []
    passed = 0
    constraint_ok = True
    if solver is None:
        constraint_ok = False
        for case in CASES["cases"]:
            results.append(
                {
                    "id": case["id"],
                    "kind": case["kind"],
                    "expect": case["expect"],
                    "status": "missing_solver",
                    "got": None,
                    "ok": False,
                }
            )
    else:
        for case in CASES["cases"]:
            run = run_case(solver, case["input"], timeout)
            expect = str(case["expect"])
            got = run.get("got")
            status = run["status"]
            ok = status == "run" and got == expect
            if ok:
                status = "pass"
                passed += 1
            elif status == "run":
                status = "WA"
            if status in {"TLE", "crash", "illegal", "missing_solver"}:
                constraint_ok = False
            results.append(
                {
                    "id": case["id"],
                    "kind": case["kind"],
                    "expect": expect,
                    "status": status,
                    "got": got,
                    "ok": ok,
                    "stderr": run.get("stderr") or "",
                }
            )
    required_ids = {
        "official1",
        "official2",
        "official3",
        "adv_multizero_1010",
        "adv_overflow_then_zero",
        "adv_n1_positive",
    }
    required_ok = all(r["ok"] for r in results if r["id"] in required_ids)
    official_ok = all(r["ok"] for r in results if r["kind"] == "official")
    adversarial_ok = all(
        r["ok"] for r in results if r["kind"] in {"adversarial", "adversarial_extra"}
    )
    return {
        "candidate": str(candidate.resolve()),
        "solver": str(solver) if solver else None,
        "submit": 0,
        "score": float(passed),
        "max_score": float(len(CASES["cases"])),
        "passed_count": passed,
        "passed_constraints": constraint_ok,
        "required_all_green": required_ok,
        "official_all_green": official_ok,
        "adversarial_all_green": adversarial_ok,
        "all_green": passed == len(CASES["cases"]) and constraint_ok,
        "pass_vector": {r["id"]: r["ok"] for r in results},
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--out")
    args = parser.parse_args()
    report = evaluate(Path(args.candidate))
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["passed_constraints"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
