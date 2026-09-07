#!/usr/bin/env python3
"""Scripted generator for Methodology Manifest protocol checks. No model calls.

Writes an isolated candidate directory plus a four-field-class manifest, then
prints the generator result JSON used by algorithm-evolve propose/refine.
"""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path


def emit(value) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def apply_component(manifest: dict, component: str | None) -> tuple[dict, list[str], str]:
    result = deepcopy(manifest)
    if component is None:
        pipeline = result.setdefault("feature_pipeline", {"steps": []})
        steps = list(pipeline.get("steps") or [])
        steps.append({"name": "scripted_full_rewrite"})
        pipeline["steps"] = steps
        result["feature_pipeline"] = pipeline
        return result, ["solution.py"], "Full scripted rewrite of the candidate"
    if component == "feature_pipeline":
        pipeline = deepcopy(result.get("feature_pipeline") or {"steps": []})
        steps = list(pipeline.get("steps") or [])
        steps.append({"name": "scripted_select"})
        pipeline["steps"] = steps
        result["feature_pipeline"] = pipeline
        return result, ["feature_pipeline.py"], "FE-only rewrite of the feature-pipeline region"
    if component == "oof_ensemble":
        ensemble = deepcopy(result.get("oof_ensemble") or {})
        members = list(ensemble.get("members") or ["baseline", "tree"])
        if "scripted_linear" not in members:
            members = members[:-1] + ["scripted_linear"] if len(members) >= 2 else members + ["scripted_linear"]
            if len(members) < 2:
                members = ["baseline", "scripted_linear"]
        ensemble["members"] = members
        result["oof_ensemble"] = ensemble
        return result, ["ensemble.py"], "Ensemble-only swap of members"
    raise ValueError(f"Unsupported component: {component}")


def write_candidate(out: Path, component: str | None, changed_files: list[str], idea: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    if component == "feature_pipeline":
        (out / "feature_pipeline.py").write_text(
            "# scripted FE-only rewrite of the feature-pipeline region\n",
            encoding="utf-8",
        )
    elif component == "oof_ensemble":
        (out / "ensemble.py").write_text(
            "# scripted ensemble-only member swap\n",
            encoding="utf-8",
        )
    else:
        (out / "solution.py").write_text("# scripted candidate\n", encoding="utf-8")
    readme = out / "CHANGED.txt"
    readme.write_text(f"{idea}\nfiles: {', '.join(changed_files)}\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="Candidate directory to write")
    parser.add_argument("--action", choices=("propose", "refine", "baseline"), default="propose")
    parser.add_argument(
        "--component",
        help="feature_pipeline (FE-only) or oof_ensemble (ensemble-only). Split is excluded.",
    )
    parser.add_argument("--parent-manifest", type=Path, help="Parent Methodology Manifest JSON")
    parser.add_argument("--idea", help="Override the generated idea summary")
    args = parser.parse_args()

    try:
        if args.component in {
            "split",
            "split_contract",
            "split-contract",
            "split_ref",
            "split-ref",
        }:
            raise ValueError(
                "split is a task-level immutable reference and is excluded from the "
                "propose/refine action space"
            )
        component = args.component
        if component in {"fe", "fe-only", "fe_only", "feature-pipeline"}:
            component = "feature_pipeline"
        elif component in {"ensemble", "ensemble-only", "ensemble_only", "oof-ensemble"}:
            component = "oof_ensemble"
        elif component not in {None, "feature_pipeline", "oof_ensemble"}:
            raise ValueError("component must be feature_pipeline or oof_ensemble")

        if args.parent_manifest is not None:
            parent = load_json(args.parent_manifest)
        else:
            parent = {
                "feature_pipeline": {"steps": [{"name": "impute"}]},
                "oof_ensemble": {
                    "members": ["baseline", "tree"],
                    "oof": {"protocol": "kfold"},
                },
                "split_ref": {"digest_summary": "0" * 64},
            }
        manifest, changed_files, default_idea = apply_component(parent, component)
        idea = args.idea or default_idea
        write_candidate(args.out, component, changed_files, idea)
        (args.out / "methodology.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        result = {
            "action": args.action,
            "artifact": str(args.out.resolve()),
            "changed_files": changed_files,
            "idea": idea,
            "known_risks": [],
            "manifest": manifest,
        }
        if component is not None:
            result["component"] = component
        emit(result)
        return 0
    except (FileNotFoundError, json.JSONDecodeError, ValueError, OSError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
