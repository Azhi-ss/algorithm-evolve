#!/usr/bin/env python3
"""Parse a generator JSON / fenced block into idea + solve.py."""

from __future__ import annotations

import json
import re
from pathlib import Path

FENCE_JSON = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)
FENCE_PY = re.compile(r"```(?:python)?\s*(.*?)```", re.S)


def _looks_like_solver(text: str) -> bool:
    return "print" in text and ("input" in text or "stdin" in text)


def extract(content: str) -> dict:
    text = (content or "").strip()
    if not text:
        return {
            "ok": False,
            "error": "empty_content",
            "idea": "",
            "solve_py": "",
            "keeps_overflow_for_later_zero": None,
            "leading_zero_flag": None,
        }

    candidates: list[dict] = []
    raw_json = text
    fence = FENCE_JSON.search(text)
    if fence:
        raw_json = fence.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            raw_json = text[start : end + 1]
    try:
        obj = json.loads(raw_json)
        if isinstance(obj, dict):
            candidates.append(obj)
    except json.JSONDecodeError:
        pass

    idea = ""
    solve_py = ""
    keeps = None
    lead = None
    for obj in candidates:
        idea = str(obj.get("idea") or obj.get("summary") or idea)
        solve_py = str(obj.get("solve_py") or obj.get("code") or obj.get("solve.py") or solve_py)
        if "keeps_overflow_for_later_zero" in obj:
            keeps = bool(obj.get("keeps_overflow_for_later_zero"))
        if "leading_zero_flag" in obj:
            lead = bool(obj.get("leading_zero_flag"))
    if not solve_py:
        py = FENCE_PY.search(text)
        if py and _looks_like_solver(py.group(1)):
            solve_py = py.group(1).strip()
    if solve_py and not _looks_like_solver(solve_py):
        return {
            "ok": False,
            "error": "extracted_code_missing_io",
            "idea": idea,
            "solve_py": solve_py,
            "keeps_overflow_for_later_zero": keeps,
            "leading_zero_flag": lead,
        }
    if not solve_py:
        return {
            "ok": False,
            "error": "no_solve_py",
            "idea": idea,
            "solve_py": "",
            "keeps_overflow_for_later_zero": keeps,
            "leading_zero_flag": lead,
        }
    return {
        "ok": True,
        "error": "",
        "idea": idea or "LLM candidate",
        "solve_py": solve_py if solve_py.endswith("\n") else solve_py + "\n",
        "keeps_overflow_for_later_zero": keeps,
        "leading_zero_flag": lead,
    }


def write_candidate(directory: Path, extracted: dict, meta: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "solve.py").write_text(extracted["solve_py"], encoding="utf-8")
    (directory / "IDEA.txt").write_text(extracted.get("idea") or "", encoding="utf-8")
    payload = dict(meta)
    payload["idea"] = extracted.get("idea")
    payload["keeps_overflow_for_later_zero"] = extracted.get("keeps_overflow_for_later_zero")
    payload["leading_zero_flag"] = extracted.get("leading_zero_flag")
    payload["extract_ok"] = extracted.get("ok")
    payload["extract_error"] = extracted.get("error")
    (directory / "meta.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
