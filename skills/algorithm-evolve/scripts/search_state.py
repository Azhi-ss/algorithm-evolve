#!/usr/bin/env python3
"""Persist and select Algorithm Evolve candidates without executing them."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
import statistics
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    goal TEXT NOT NULL,
    artifact TEXT NOT NULL,
    evaluation_mode TEXT NOT NULL CHECK (evaluation_mode IN ('objective', 'hybrid', 'judgment')),
    evaluation_json TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('maximize', 'minimize')),
    constraints_json TEXT NOT NULL,
    budget_iterations INTEGER,
    budget_seconds INTEGER,
    budget_model_calls INTEGER,
    target_score REAL,
    stagnation_limit INTEGER,
    methodology_json TEXT,
    created_at TEXT NOT NULL,
    model_calls INTEGER NOT NULL DEFAULT 0,
    finalized_nodes INTEGER NOT NULL DEFAULT 0,
    stagnation_count INTEGER NOT NULL DEFAULT 0,
    best_node_id TEXT,
    best_score REAL
);

CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    action TEXT NOT NULL CHECK (action IN ('baseline', 'propose', 'refine', 'repair', 'fuse')),
    artifact TEXT NOT NULL,
    idea TEXT NOT NULL,
    manifest_json TEXT,
    target_component TEXT CHECK (
        target_component IS NULL
        OR target_component IN ('feature_pipeline', 'oof_ensemble')
    ),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'finalized', 'rejected')),
    effective_kind TEXT,
    effective_score REAL,
    reward REAL,
    visits INTEGER NOT NULL DEFAULT 0,
    value_sum REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    finalized_at TEXT
);

CREATE TABLE IF NOT EXISTS edges (
    child_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    parent_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    PRIMARY KEY (child_id, parent_id),
    CHECK (child_id <> parent_id)
);

CREATE TABLE IF NOT EXISTS evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('objective', 'judgment', 'constraint')),
    score REAL,
    judge TEXT,
    passed INTEGER,
    evidence TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_nodes_task ON nodes(task_id);
CREATE INDEX IF NOT EXISTS idx_evaluations_node ON evaluations(node_id);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def emit(value) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    task_columns = {info[1] for info in conn.execute("PRAGMA table_info(tasks)")}
    if task_columns and "methodology_json" not in task_columns:
        conn.execute("ALTER TABLE tasks ADD COLUMN methodology_json TEXT")
    node_columns = {info[1] for info in conn.execute("PRAGMA table_info(nodes)")}
    if node_columns and "manifest_json" not in node_columns:
        conn.execute("ALTER TABLE nodes ADD COLUMN manifest_json TEXT")
    if node_columns and "target_component" not in node_columns:
        conn.execute("ALTER TABLE nodes ADD COLUMN target_component TEXT")


def row(conn: sqlite3.Connection, table: str, item_id: str) -> sqlite3.Row:
    if table not in {"tasks", "nodes"}:
        raise ValueError(f"Unsupported table: {table}")
    item = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (item_id,)).fetchone()
    if item is None:
        raise ValueError(f"Unknown {table[:-1]}: {item_id}")
    return item


def positive_int(value, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


_MISSING = object()
SPLIT_KINDS = frozenset({"kfold", "time", "group"})


def _copy_object(value, name: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return dict(value)


def _take_aliases(data: dict, canonical: str, *aliases: str):
    names = (canonical, *aliases)
    present = [name for name in names if name in data]
    if not present:
        return _MISSING
    first = data[present[0]]
    for name in present[1:]:
        if data[name] != first:
            raise ValueError(
                f"Conflicting aliases for {canonical}: {present[0]!r} and {name!r}"
            )
    for name in present:
        del data[name]
    return first


def _non_empty_string(value, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _non_negative_number(value, name: str):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(f"{name} must be a non-negative number")
    return value


def _named_items(items, name: str) -> list:
    if not isinstance(items, list):
        raise ValueError(f"{name} must be a list")
    canonical = []
    for index, item in enumerate(items):
        label = f"{name}[{index}]"
        if isinstance(item, str):
            canonical.append(_non_empty_string(item, label))
        elif isinstance(item, dict):
            canonical.append(item)
        else:
            raise ValueError(f"{label} must be a string or object")
    return canonical


def validate_split_contract(raw) -> dict:
    data = _copy_object(raw, "methodology.split_contract")
    kind = _take_aliases(data, "kind", "type")
    if kind not in SPLIT_KINDS:
        raise ValueError("methodology.split_contract.kind must be kfold, time, or group")

    purge = _take_aliases(data, "purge")
    purge = 0 if purge is _MISSING or purge is None else _non_negative_number(
        purge, "methodology.split_contract.purge"
    )
    embargo = _take_aliases(data, "embargo")
    embargo = 0 if embargo is _MISSING or embargo is None else _non_negative_number(
        embargo, "methodology.split_contract.embargo"
    )

    group_column = _take_aliases(data, "group_column", "groupColumn")
    if kind == "group":
        if group_column is _MISSING or group_column is None:
            raise ValueError(
                "methodology.split_contract.group_column is required when kind is group"
            )
        group_column = _non_empty_string(
            group_column, "methodology.split_contract.group_column"
        )
    elif group_column is not _MISSING and group_column is not None:
        group_column = _non_empty_string(
            group_column, "methodology.split_contract.group_column"
        )
    else:
        group_column = _MISSING

    n_splits = _take_aliases(data, "n_splits", "nSplits")
    if n_splits is not _MISSING and n_splits is not None:
        n_splits = positive_int(n_splits, "methodology.split_contract.n_splits")
    time_column = _take_aliases(data, "time_column", "timeColumn")
    if time_column is not _MISSING and time_column is not None:
        time_column = _non_empty_string(
            time_column, "methodology.split_contract.time_column"
        )

    result = {**data, "kind": kind, "purge": purge, "embargo": embargo}
    if group_column is not _MISSING:
        result["group_column"] = group_column
    if n_splits is not _MISSING and n_splits is not None:
        result["n_splits"] = n_splits
    if time_column is not _MISSING and time_column is not None:
        result["time_column"] = time_column
    return result


def _has_oof_protocol(oof) -> bool:
    if oof is True:
        return True
    if oof is False or oof is None:
        return False
    if isinstance(oof, dict):
        return bool(oof)
    raise ValueError("methodology.oof_ensemble.oof must be an object or boolean")


def validate_oof_ensemble(raw) -> dict:
    data = _copy_object(raw, "methodology.oof_ensemble")
    members = _take_aliases(data, "members", "ensemble_members", "ensembleMembers")
    if members is _MISSING or not isinstance(members, list) or len(members) < 2:
        raise ValueError("methodology.oof_ensemble.members must contain at least 2 members")
    members = _named_items(members, "methodology.oof_ensemble.members")

    method = _take_aliases(data, "method", "ensemble_method", "ensembleMethod")
    if method is _MISSING or method is None:
        raise ValueError("methodology.oof_ensemble.method is required")
    method = _non_empty_string(method, "methodology.oof_ensemble.method")

    oof = _take_aliases(data, "oof", "oof_protocol", "oofProtocol")
    declared = _take_aliases(data, "declared_equivalent", "declaredEquivalent")
    if declared is _MISSING:
        declared_value = False
        declared_present = False
    else:
        if not isinstance(declared, bool):
            raise ValueError(
                "methodology.oof_ensemble.declared_equivalent must be a boolean"
            )
        declared_value = declared
        declared_present = True

    has_oof = False if oof is _MISSING else _has_oof_protocol(oof)
    if not has_oof and not declared_value:
        raise ValueError(
            "methodology.oof_ensemble requires an oof protocol or declared_equivalent"
        )

    result = {**data, "members": members, "method": method}
    if oof is not _MISSING:
        result["oof"] = oof
    if declared_present:
        result["declared_equivalent"] = declared_value
    return result


def validate_feature_pipeline(raw) -> dict:
    data = _copy_object(raw, "methodology.feature_pipeline")
    steps = _take_aliases(data, "steps", "pipeline_steps", "pipelineSteps")
    if steps is _MISSING:
        raise ValueError("methodology.feature_pipeline.steps must be a list")
    return {**data, "steps": _named_items(steps, "methodology.feature_pipeline.steps")}


def validate_methodology(raw) -> dict | None:
    if raw is None:
        return None
    data = _copy_object(raw, "methodology")
    split = _take_aliases(data, "split_contract", "splitContract")
    ensemble = _take_aliases(data, "oof_ensemble", "oofEnsemble")
    pipeline = _take_aliases(data, "feature_pipeline", "featurePipeline")

    result = dict(data)
    if split is not _MISSING:
        result["split_contract"] = validate_split_contract(split)
    if ensemble is not _MISSING:
        result["oof_ensemble"] = validate_oof_ensemble(ensemble)
    if pipeline is not _MISSING:
        result["feature_pipeline"] = validate_feature_pipeline(pipeline)
    return result or None


def task_methodology(task: sqlite3.Row) -> dict | None:
    keys = set(task.keys())
    if "methodology_json" not in keys:
        return None
    raw = task["methodology_json"]
    if not raw:
        return None
    return json.loads(raw)


MANIFEST_FILENAMES = ("methodology.json", "methodology_manifest.json")


def split_contract_digest_summary(split_contract: dict) -> str:
    canonical = json.dumps(split_contract, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def canonicalize_split_ref(raw) -> dict:
    if isinstance(raw, str):
        digest = _non_empty_string(raw, "manifest.split_ref")
        return {"digest_summary": digest.lower()}
    data = _copy_object(raw, "manifest.split_ref")
    digest = _take_aliases(data, "digest_summary", "digestSummary", "digest", "sha256")
    if digest is _MISSING or digest is None:
        raise ValueError("manifest.split_ref.digest_summary must be a non-empty string")
    digest = _non_empty_string(digest, "manifest.split_ref.digest_summary")
    return {**data, "digest_summary": digest.lower()}


def canonicalize_manifest_ensemble(raw) -> dict:
    data = _copy_object(raw, "manifest.oof_ensemble")
    members = _take_aliases(data, "members", "ensemble_members", "ensembleMembers")
    method = _take_aliases(data, "method", "ensemble_method", "ensembleMethod")
    oof = _take_aliases(data, "oof", "oof_protocol", "oofProtocol")
    declared = _take_aliases(data, "declared_equivalent", "declaredEquivalent")
    result = dict(data)
    if members is not _MISSING:
        result["members"] = _named_items(members, "manifest.oof_ensemble.members")
    if method is not _MISSING and method is not None:
        result["method"] = _non_empty_string(method, "manifest.oof_ensemble.method")
    if oof is not _MISSING:
        result["oof"] = oof
    if declared is not _MISSING:
        if not isinstance(declared, bool):
            raise ValueError("manifest.oof_ensemble.declared_equivalent must be a boolean")
        result["declared_equivalent"] = declared
    return result


def validate_methodology_manifest(raw) -> dict:
    data = _copy_object(raw, "manifest")
    split_ref = _take_aliases(data, "split_ref", "splitRef", "split_reference", "splitReference")
    split_contract = _take_aliases(data, "split_contract", "splitContract")
    ensemble = _take_aliases(data, "oof_ensemble", "oofEnsemble", "ensemble")
    pipeline = _take_aliases(data, "feature_pipeline", "featurePipeline")
    oof = _take_aliases(data, "oof", "oof_protocol", "oofProtocol")
    declared = _take_aliases(data, "declared_equivalent", "declaredEquivalent")

    result = dict(data)
    if split_ref is not _MISSING:
        result["split_ref"] = canonicalize_split_ref(split_ref)
    if split_contract is not _MISSING:
        result["split_contract"] = validate_split_contract(split_contract)
    if ensemble is not _MISSING:
        result["oof_ensemble"] = canonicalize_manifest_ensemble(ensemble)
    if pipeline is not _MISSING:
        result["feature_pipeline"] = validate_feature_pipeline(pipeline)
    if oof is not _MISSING:
        result["oof"] = oof
    if declared is not _MISSING:
        if not isinstance(declared, bool):
            raise ValueError("manifest.declared_equivalent must be a boolean")
        result["declared_equivalent"] = declared
    return result


def node_manifest(node) -> dict | None:
    if isinstance(node, dict):
        parsed = node.get("manifest")
        if parsed is not None:
            return parsed
        raw = node.get("manifest_json")
    else:
        keys = set(node.keys())
        if "manifest_json" not in keys:
            return None
        raw = node["manifest_json"]
    if not raw:
        return None
    return json.loads(raw) if isinstance(raw, str) else raw


def load_candidate_manifest(args: argparse.Namespace, artifact: Path) -> dict | None:
    path = None
    if getattr(args, "manifest", None) is not None:
        path = Path(args.manifest)
        if not path.is_file():
            raise ValueError(f"Candidate manifest is not a file: {path}")
    else:
        for name in MANIFEST_FILENAMES:
            candidate = artifact / name
            if candidate.is_file():
                path = candidate
                break
    if path is None:
        return None
    return validate_methodology_manifest(json.loads(path.read_text(encoding="utf-8")))


def manifest_split_ref_digest(manifest: dict) -> str | None:
    split_ref = manifest.get("split_ref")
    if isinstance(split_ref, dict) and split_ref.get("digest_summary"):
        return str(split_ref["digest_summary"]).lower()
    if isinstance(split_ref, str) and split_ref.strip():
        return split_ref.strip().lower()
    split_contract = manifest.get("split_contract")
    if isinstance(split_contract, dict):
        return split_contract_digest_summary(split_contract)
    return None


def manifest_has_oof_protocol(manifest: dict) -> bool:
    if manifest.get("declared_equivalent") is True:
        return True
    if "oof" in manifest:
        try:
            if _has_oof_protocol(manifest.get("oof")):
                return True
        except ValueError:
            return False
    ensemble = manifest.get("oof_ensemble")
    if not isinstance(ensemble, dict):
        return False
    if ensemble.get("declared_equivalent") is True:
        return True
    if "oof" not in ensemble:
        return False
    try:
        return _has_oof_protocol(ensemble.get("oof"))
    except ValueError:
        return False


COMPONENT_ACTIONS = frozenset({"propose", "refine"})
TARGET_COMPONENTS = frozenset({"feature_pipeline", "oof_ensemble"})
COMPONENT_ALIASES = {
    "feature_pipeline": "feature_pipeline",
    "feature-pipeline": "feature_pipeline",
    "featurepipeline": "feature_pipeline",
    "fe": "feature_pipeline",
    "fe-only": "feature_pipeline",
    "fe_only": "feature_pipeline",
    "oof_ensemble": "oof_ensemble",
    "oof-ensemble": "oof_ensemble",
    "oofensemble": "oof_ensemble",
    "ensemble": "oof_ensemble",
    "ensemble-only": "oof_ensemble",
    "ensemble_only": "oof_ensemble",
}
SPLIT_COMPONENT_ALIASES = frozenset(
    {
        "split",
        "split_contract",
        "split-contract",
        "splitcontract",
        "split_ref",
        "split-ref",
        "splitref",
        "split_reference",
        "split-reference",
        "splitreference",
    }
)


def canonicalize_target_component(raw) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("component must be feature_pipeline or oof_ensemble")
    key = raw.strip().lower().replace(" ", "_")
    compact = key.replace("-", "_")
    if key in SPLIT_COMPONENT_ALIASES or compact in SPLIT_COMPONENT_ALIASES:
        raise ValueError(
            "split is a task-level immutable reference and is excluded from the "
            "propose/refine action space"
        )
    canonical = COMPONENT_ALIASES.get(key) or COMPONENT_ALIASES.get(compact)
    if canonical not in TARGET_COMPONENTS:
        raise ValueError("component must be feature_pipeline or oof_ensemble")
    return canonical


def _json_equal(left, right) -> bool:
    return json.dumps(left, sort_keys=True, separators=(",", ":")) == json.dumps(
        right, sort_keys=True, separators=(",", ":")
    )


def _region(manifest: dict | None, name: str):
    if not manifest:
        return None
    if name == "split_ref":
        return manifest_split_ref_digest(manifest)
    return manifest.get(name)


def _ensemble_without_members(ensemble):
    if not isinstance(ensemble, dict):
        return ensemble
    return {key: value for key, value in ensemble.items() if key != "members"}


def component_action_failures(
    action: str,
    component: str | None,
    parents: list,
    manifest: dict | None,
) -> list[str]:
    if component is None:
        return []
    if action not in COMPONENT_ACTIONS:
        return ["component targeting is only valid for propose and refine"]
    if not parents:
        return ["component-targeted propose/refine requires a parent"]
    parent_manifest = node_manifest(parents[0])
    if parent_manifest is None or manifest is None:
        return []
    failures = []
    if not _json_equal(_region(manifest, "split_ref"), _region(parent_manifest, "split_ref")):
        failures.append(
            "component-targeted action cannot change split_ref; split is immutable"
        )
    if component == "feature_pipeline":
        if not _json_equal(
            _region(manifest, "oof_ensemble"),
            _region(parent_manifest, "oof_ensemble"),
        ):
            failures.append(
                "feature_pipeline-only action cannot change oof_ensemble; rewrite the feature-pipeline region only"
            )
    else:
        if not _json_equal(
            _region(manifest, "feature_pipeline"),
            _region(parent_manifest, "feature_pipeline"),
        ):
            failures.append(
                "oof_ensemble-only action cannot change feature_pipeline; swap ensemble members only"
            )
        if not _json_equal(
            _ensemble_without_members(manifest.get("oof_ensemble")),
            _ensemble_without_members(parent_manifest.get("oof_ensemble")),
        ):
            failures.append(
                "oof_ensemble-only action can swap members only"
            )
    return failures


def methodology_finalize_failures(task: sqlite3.Row, node) -> list[str]:
    methodology = task_methodology(task)
    if methodology is None:
        return []
    manifest = node_manifest(node)
    if manifest is None:
        return ["candidate manifest is required when methodology contracts are injected"]
    failures = []
    split = methodology.get("split_contract")
    if split is not None:
        expected = split_contract_digest_summary(split)
        actual = manifest_split_ref_digest(manifest)
        if actual != expected:
            failures.append(
                "manifest split_ref digest summary does not match task split_contract"
            )
    if "oof_ensemble" in methodology and not manifest_has_oof_protocol(manifest):
        failures.append("manifest must declare an oof protocol or declared_equivalent")
    return failures


def validate_task(data: dict) -> dict:
    for key in ("id", "goal", "artifact", "evaluation", "direction", "budget"):
        if key not in data:
            raise ValueError(f"Task contract is missing {key!r}")
    for key in ("id", "goal", "artifact"):
        if not isinstance(data[key], str) or not data[key].strip():
            raise ValueError(f"{key} must be a non-empty string")

    evaluation = data["evaluation"]
    if not isinstance(evaluation, dict) or evaluation.get("mode") not in {
        "objective",
        "hybrid",
        "judgment",
    }:
        raise ValueError("evaluation.mode must be objective, hybrid, or judgment")
    if evaluation["mode"] in {"objective", "hybrid"} and not evaluation.get("command"):
        raise ValueError("Objective and hybrid tasks require evaluation.command")
    rubric = evaluation.get("rubric")
    if evaluation["mode"] == "judgment" and (
        not isinstance(rubric, list)
        or not rubric
        or not all(isinstance(item, str) and item.strip() for item in rubric)
    ):
        raise ValueError("Judgment tasks require a non-empty evaluation.rubric string list")
    if data["direction"] not in {"maximize", "minimize"}:
        raise ValueError("direction must be maximize or minimize")

    budget = data["budget"]
    if not isinstance(budget, dict):
        raise ValueError("budget must be an object")
    iterations = positive_int(budget.get("iterations"), "budget.iterations")
    seconds = positive_int(budget.get("seconds"), "budget.seconds")
    model_calls = positive_int(budget.get("model_calls"), "budget.model_calls")
    if not any((iterations, seconds, model_calls)):
        raise ValueError("At least one finite budget is required")

    stagnation = positive_int(budget.get("stagnation"), "budget.stagnation")
    target_score = budget.get("target_score")
    if target_score is not None and (
        isinstance(target_score, bool)
        or not isinstance(target_score, (int, float))
        or not math.isfinite(target_score)
    ):
        raise ValueError("budget.target_score must be a finite number")
    constraints = data.get("constraints", [])
    if not isinstance(constraints, list) or not all(isinstance(item, str) for item in constraints):
        raise ValueError("constraints must be a list of strings")
    methodology = validate_methodology(data.get("methodology"))

    return {
        **data,
        "constraints": constraints,
        "budget": {
            **budget,
            "iterations": iterations,
            "seconds": seconds,
            "model_calls": model_calls,
            "stagnation": stagnation,
            "target_score": target_score,
        },
        "methodology": methodology,
    }


def init_task(conn: sqlite3.Connection, task_path: Path) -> None:
    data = validate_task(json.loads(task_path.read_text(encoding="utf-8")))
    budget = data["budget"]
    ensure_schema(conn)
    methodology = data.get("methodology")
    conn.execute(
        """
        INSERT INTO tasks (
            id, goal, artifact, evaluation_mode, evaluation_json, direction,
            constraints_json, budget_iterations, budget_seconds,
            budget_model_calls, target_score, stagnation_limit,
            methodology_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data["id"],
            data["goal"],
            str(Path(data["artifact"]).resolve()),
            data["evaluation"]["mode"],
            json.dumps(data["evaluation"], sort_keys=True),
            data["direction"],
            json.dumps(data["constraints"], sort_keys=True),
            budget["iterations"],
            budget["seconds"],
            budget["model_calls"],
            budget.get("target_score"),
            budget["stagnation"],
            None if methodology is None else json.dumps(methodology, sort_keys=True),
            now(),
        ),
    )
    conn.commit()
    emit({"task_contract": str(task_path), "task_id": data["id"]})


def is_better(direction: str, candidate: float, incumbent: float) -> bool:
    return candidate > incumbent if direction == "maximize" else candidate < incumbent


def stop_reasons(conn: sqlite3.Connection, task: sqlite3.Row) -> list[str]:
    reasons = []
    iterations = conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE task_id = ? AND action <> 'baseline'",
        (task["id"],),
    ).fetchone()[0]
    elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(task["created_at"])).total_seconds()

    if task["budget_iterations"] is not None and iterations >= task["budget_iterations"]:
        reasons.append("iteration_budget")
    if task["budget_seconds"] is not None and elapsed >= task["budget_seconds"]:
        reasons.append("time_budget")
    if task["budget_model_calls"] is not None and task["model_calls"] >= task["budget_model_calls"]:
        reasons.append("model_call_budget")
    if task["stagnation_limit"] is not None and task["stagnation_count"] >= task["stagnation_limit"]:
        reasons.append("stagnation")
    if task["target_score"] is not None and task["best_score"] is not None:
        reached = (
            task["best_score"] >= task["target_score"]
            if task["direction"] == "maximize"
            else task["best_score"] <= task["target_score"]
        )
        if reached:
            reasons.append("target_score")
    return reasons


def add_node(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    task = row(conn, "tasks", args.task_id)
    reasons = stop_reasons(conn, task)
    if reasons:
        raise ValueError(f"Search is stopped: {', '.join(reasons)}")
    if not args.idea.strip():
        raise ValueError("--idea cannot be empty")

    parents = list(dict.fromkeys(args.parent or []))
    expected = {
        "baseline": (0, 0),
        "propose": (0, 1),
        "refine": (1, 1),
        "repair": (1, 1),
        "fuse": (2, None),
    }[args.action]
    if len(parents) < expected[0] or (expected[1] is not None and len(parents) > expected[1]):
        raise ValueError(f"Invalid parent count for {args.action}: {len(parents)}")
    if args.action == "baseline" and conn.execute(
        "SELECT 1 FROM nodes WHERE task_id = ? AND action = 'baseline'", (args.task_id,)
    ).fetchone():
        raise ValueError("A task can have only one baseline")

    parent_rows = []
    for parent_id in parents:
        parent = row(conn, "nodes", parent_id)
        if parent["task_id"] != args.task_id:
            raise ValueError("Parents must belong to the same task")
        allowed = {"finalized", "rejected"} if args.action == "repair" else {"finalized"}
        if parent["status"] not in allowed:
            raise ValueError(f"Parent {parent_id} is not eligible for {args.action}")
        parent_rows.append(parent)

    artifact = Path(args.artifact).resolve()
    if not artifact.is_dir():
        raise ValueError(f"Candidate artifact is not a directory: {artifact}")

    manifest = load_candidate_manifest(args, artifact)
    if task_methodology(task) is not None and manifest is None:
        raise ValueError("Task has methodology contracts; candidate manifest is required")

    component = canonicalize_target_component(getattr(args, "component", None))
    component_failures = component_action_failures(
        args.action, component, parent_rows, manifest
    )
    if component_failures:
        raise ValueError("; ".join(component_failures))

    node_id = f"n-{uuid.uuid4().hex[:12]}"
    conn.execute(
        """
        INSERT INTO nodes (
            id, task_id, action, artifact, idea, manifest_json, target_component, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            node_id,
            args.task_id,
            args.action,
            str(artifact),
            args.idea,
            None if manifest is None else json.dumps(manifest, sort_keys=True),
            component,
            now(),
        ),
    )
    conn.executemany(
        "INSERT INTO edges (child_id, parent_id) VALUES (?, ?)",
        [(node_id, parent_id) for parent_id in parents],
    )
    conn.execute(
        "UPDATE tasks SET model_calls = model_calls + ? WHERE id = ?",
        (args.model_calls, args.task_id),
    )
    conn.commit()
    payload = {"node_id": node_id, "parents": parents}
    if component is not None:
        payload["target_component"] = component
    emit(payload)


def record_evaluation(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    node = row(conn, "nodes", args.node)
    if node["status"] != "pending":
        raise ValueError("Evaluations can only be recorded on pending nodes")
    if args.kind in {"objective", "judgment"} and args.score is None:
        raise ValueError(f"{args.kind} evaluations require --score")
    if args.score is not None and not math.isfinite(args.score):
        raise ValueError("--score must be finite")
    if not args.evidence.strip():
        raise ValueError("--evidence cannot be empty")
    if args.kind == "judgment" and not args.judge:
        raise ValueError("Judgment evaluations require --judge")
    if args.kind == "constraint" and args.passed is None:
        raise ValueError("Constraint evaluations require --passed")
    if args.kind == "judgment" and conn.execute(
        "SELECT 1 FROM evaluations WHERE node_id = ? AND kind = 'judgment' AND judge = ?",
        (args.node, args.judge),
    ).fetchone():
        raise ValueError(f"Judge {args.judge!r} already scored this node")

    passed = None if args.passed is None else int(args.passed == "true")
    conn.execute(
        """
        INSERT INTO evaluations (node_id, kind, score, judge, passed, evidence, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (args.node, args.kind, args.score, args.judge, passed, args.evidence, now()),
    )
    model_calls = args.model_calls
    if model_calls is None:
        model_calls = 1 if args.kind == "judgment" else 0
    conn.execute(
        "UPDATE tasks SET model_calls = model_calls + ? WHERE id = ?",
        (model_calls, node["task_id"]),
    )
    conn.commit()
    emit({"kind": args.kind, "node_id": args.node, "recorded": True})


def ancestor_ids(conn: sqlite3.Connection, node_id: str, include_self: bool = True) -> set[str]:
    seen = {node_id} if include_self else set()
    stack = [node_id]
    while stack:
        child = stack.pop()
        for parent in conn.execute("SELECT parent_id FROM edges WHERE child_id = ?", (child,)):
            if parent["parent_id"] not in seen:
                seen.add(parent["parent_id"])
                stack.append(parent["parent_id"])
    return seen


def backpropagate(conn: sqlite3.Connection, node_id: str, reward: float) -> None:
    ids = ancestor_ids(conn, node_id)
    conn.executemany(
        "UPDATE nodes SET visits = visits + 1, value_sum = value_sum + ? WHERE id = ?",
        [(reward, item_id) for item_id in ids],
    )


def best_comparison_score(conn: sqlite3.Connection, node_id: str, direction: str) -> float | None:
    parent_ids = [item["parent_id"] for item in conn.execute(
        "SELECT parent_id FROM edges WHERE child_id = ?", (node_id,)
    )]
    scores = []
    for parent_id in parent_ids:
        parent = row(conn, "nodes", parent_id)
        if parent["effective_score"] is not None:
            scores.append(parent["effective_score"])
    if not scores:
        for ancestor_id in ancestor_ids(conn, node_id, include_self=False):
            ancestor = row(conn, "nodes", ancestor_id)
            if ancestor["effective_score"] is not None:
                scores.append(ancestor["effective_score"])
    if not scores:
        return None
    return max(scores) if direction == "maximize" else min(scores)


def update_task_after_rollout(
    conn: sqlite3.Connection,
    task: sqlite3.Row,
    node_id: str,
    score: float | None,
) -> None:
    improved = score is not None and (
        task["best_score"] is None or is_better(task["direction"], score, task["best_score"])
    )
    if improved:
        conn.execute(
            """
            UPDATE tasks
            SET finalized_nodes = finalized_nodes + 1, stagnation_count = 0,
                best_node_id = ?, best_score = ?
            WHERE id = ?
            """,
            (node_id, score, task["id"]),
        )
    else:
        conn.execute(
            """
            UPDATE tasks
            SET finalized_nodes = finalized_nodes + 1, stagnation_count = stagnation_count + 1
            WHERE id = ?
            """,
            (task["id"],),
        )


def finalize_node(conn: sqlite3.Connection, node_id: str) -> None:
    node = row(conn, "nodes", node_id)
    if node["status"] != "pending":
        raise ValueError("Node is already finalized")
    task = row(conn, "tasks", node["task_id"])
    evaluations = conn.execute(
        "SELECT * FROM evaluations WHERE node_id = ? ORDER BY id", (node_id,)
    ).fetchall()
    constraints = json.loads(task["constraints_json"])
    constraint_results = [item for item in evaluations if item["kind"] == "constraint"]
    if constraints and not constraint_results:
        raise ValueError("Record hard-constraint evidence before finalizing")

    rejected = any(item["passed"] == 0 for item in constraint_results)
    if not rejected:
        methodology_failures = methodology_finalize_failures(task, node)
        if methodology_failures:
            conn.execute(
                """
                INSERT INTO evaluations (node_id, kind, score, judge, passed, evidence, created_at)
                VALUES (?, 'constraint', NULL, NULL, 0, ?, ?)
                """,
                (node_id, "; ".join(methodology_failures), now()),
            )
            rejected = True
    if rejected:
        reward = 0.0
        conn.execute(
            """
            UPDATE nodes SET status = 'rejected', effective_kind = 'constraint', reward = ?,
                finalized_at = ? WHERE id = ?
            """,
            (reward, now(), node_id),
        )
        backpropagate(conn, node_id, reward)
        update_task_after_rollout(conn, task, node_id, None)
        conn.commit()
        emit({"node_id": node_id, "reward": reward, "status": "rejected"})
        return

    objective_scores = [item["score"] for item in evaluations if item["kind"] == "objective"]
    judgments = [item for item in evaluations if item["kind"] == "judgment"]
    if task["evaluation_mode"] in {"objective", "hybrid"}:
        if not objective_scores:
            raise ValueError(f"{task['evaluation_mode']} tasks require an objective score")
        kind = "objective"
        score = float(statistics.median(objective_scores))
    else:
        judges = {item["judge"] for item in judgments}
        if len(judges) < 3:
            raise ValueError("Judgment tasks require three distinct reviewers")
        kind = "judgment"
        score = float(statistics.median(item["score"] for item in judgments))

    comparison = best_comparison_score(conn, node_id, task["direction"])
    # ponytail: coarse ordinal reward; add task-specific normalization only when magnitude affects selection.
    if comparison is None:
        reward = 0.5
    elif score == comparison:
        reward = 0.5
    else:
        reward = 1.0 if is_better(task["direction"], score, comparison) else 0.0

    conn.execute(
        """
        UPDATE nodes SET status = 'finalized', effective_kind = ?, effective_score = ?,
            reward = ?, finalized_at = ? WHERE id = ?
        """,
        (kind, score, reward, now(), node_id),
    )
    backpropagate(conn, node_id, reward)
    update_task_after_rollout(conn, task, node_id, score)
    conn.commit()
    emit({"kind": kind, "node_id": node_id, "reward": reward, "score": score, "status": "finalized"})


def node_data(conn: sqlite3.Connection, node_id: str) -> dict:
    node = dict(row(conn, "nodes", node_id))
    raw_manifest = node.pop("manifest_json", None)
    if raw_manifest:
        node["manifest"] = json.loads(raw_manifest)
    if "target_component" in node:
        component = node.pop("target_component")
        if component:
            node["target_component"] = component
    node["parents"] = [item["parent_id"] for item in conn.execute(
        "SELECT parent_id FROM edges WHERE child_id = ? ORDER BY parent_id", (node_id,)
    )]
    evaluations = []
    for item in conn.execute("SELECT * FROM evaluations WHERE node_id = ? ORDER BY id", (node_id,)):
        value = dict(item)
        if value["passed"] is not None:
            value["passed"] = bool(value["passed"])
        evaluations.append(value)
    node["evaluations"] = evaluations
    return node


def select_node(conn: sqlite3.Connection, task_id: str, exploration: float) -> None:
    task = row(conn, "tasks", task_id)
    reasons = stop_reasons(conn, task)
    if reasons:
        emit({"selected": None, "stop_reasons": reasons})
        return
    nodes = conn.execute(
        "SELECT * FROM nodes WHERE task_id = ? AND status = 'finalized'", (task_id,)
    ).fetchall()
    if not nodes:
        emit({"selected": None, "stop_reasons": ["no_finalized_candidate"]})
        return

    rollouts = max(2, task["finalized_nodes"] + 1)
    scored = []
    for candidate in nodes:
        visits = max(1, candidate["visits"])
        uct = candidate["value_sum"] / visits + exploration * math.sqrt(math.log(rollouts) / visits)
        scored.append((uct, candidate["created_at"], candidate["id"]))
    uct, _, selected_id = max(scored, key=lambda item: (item[0], item[1]))
    emit({"selected": node_data(conn, selected_id), "uct": uct})


def task_status_data(conn: sqlite3.Connection, task_id: str) -> dict:
    task = row(conn, "tasks", task_id)
    iterations = conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE task_id = ? AND action <> 'baseline'", (task_id,)
    ).fetchone()[0]
    rejected = conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE task_id = ? AND status = 'rejected'", (task_id,)
    ).fetchone()[0]
    pending = conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE task_id = ? AND status = 'pending'", (task_id,)
    ).fetchone()[0]
    reasons = stop_reasons(conn, task)
    payload = {
        "best_node_id": task["best_node_id"],
        "best_score": task["best_score"],
        "iterations": iterations,
        "model_calls": task["model_calls"],
        "pending": pending,
        "rejected": rejected,
        "stagnation": task["stagnation_count"],
        "stop_reasons": reasons,
        "stopped": bool(reasons),
        "task_id": task_id,
    }
    methodology = task_methodology(task)
    if methodology is not None:
        payload["methodology"] = methodology
    return payload


def task_status(conn: sqlite3.Connection, task_id: str) -> None:
    emit(task_status_data(conn, task_id))


def pending_resume_action(task: sqlite3.Row, node: dict) -> dict:
    evaluations = node["evaluations"]
    constraints = json.loads(task["constraints_json"])
    constraint_results = [item for item in evaluations if item["kind"] == "constraint"]
    if constraints and not constraint_results:
        return {"action": "record_constraints"}
    if any(item["passed"] is False for item in constraint_results):
        return {"action": "finalize_rejection"}

    if task["evaluation_mode"] in {"objective", "hybrid"}:
        if not any(item["kind"] == "objective" for item in evaluations):
            return {"action": "run_objective_evaluation"}
    else:
        judges = {item["judge"] for item in evaluations if item["kind"] == "judgment"}
        if len(judges) < 3:
            return {"action": "run_judgment_reviews", "reviewers_needed": 3 - len(judges)}
    return {"action": "finalize_node"}


def resume_search(conn: sqlite3.Connection, task_id: str | None) -> None:
    task_ids = [item["id"] for item in conn.execute(
        "SELECT id FROM tasks ORDER BY created_at DESC"
    )]
    if not task_ids:
        raise ValueError("No Algorithm Evolve task exists in this database")
    if task_id is None and len(task_ids) > 1:
        emit({"requires_task_id": True, "task_ids": task_ids})
        return

    selected_task_id = task_id or task_ids[0]
    task = row(conn, "tasks", selected_task_id)
    status = task_status_data(conn, selected_task_id)
    pending = []
    for item in conn.execute(
        "SELECT id FROM nodes WHERE task_id = ? AND status = 'pending' ORDER BY created_at",
        (selected_task_id,),
    ):
        data = node_data(conn, item["id"])
        data["artifact_exists"] = Path(data["artifact"]).is_dir()
        data["resume"] = pending_resume_action(task, data)
        pending.append(data)

    valid_count = conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE task_id = ? AND status = 'finalized'",
        (selected_task_id,),
    ).fetchone()[0]
    node_count = conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE task_id = ?", (selected_task_id,)
    ).fetchone()[0]
    if status["stopped"]:
        next_action = "finish_or_request_new_budget"
    elif pending:
        next_action = "resume_pending_nodes"
    elif node_count == 0:
        next_action = "create_baseline"
    elif valid_count == 0:
        next_action = "repair_or_propose"
    else:
        next_action = "select_and_expand"

    last = conn.execute(
        "SELECT id FROM nodes WHERE task_id = ? ORDER BY created_at DESC LIMIT 1",
        (selected_task_id,),
    ).fetchone()
    task_payload = {
        "artifact": task["artifact"],
        "direction": task["direction"],
        "evaluation": json.loads(task["evaluation_json"]),
        "goal": task["goal"],
        "id": task["id"],
    }
    methodology = task_methodology(task)
    if methodology is not None:
        task_payload["methodology"] = methodology
    emit(
        {
            "best": None if task["best_node_id"] is None else node_data(conn, task["best_node_id"]),
            "last_node": None if last is None else node_data(conn, last["id"]),
            "next_action": next_action,
            "pending_nodes": pending,
            "status": status,
            "task": task_payload,
        }
    )


def best_node(conn: sqlite3.Connection, task_id: str) -> None:
    task = row(conn, "tasks", task_id)
    emit(None if task["best_node_id"] is None else node_data(conn, task["best_node_id"]))


def query_nodes(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    if not args.all_tasks and not args.task_id:
        raise ValueError("query requires --task-id unless --all-tasks is set")
    needle = f"%{args.text.lower()}%"
    results = conn.execute(
        """
        SELECT DISTINCT n.*
        FROM nodes n
        WHERE (? = 1 OR n.task_id = ?)
          AND (
            lower(n.idea) LIKE ? OR lower(n.artifact) LIKE ? OR EXISTS (
              SELECT 1 FROM evaluations e
              WHERE e.node_id = n.id AND lower(e.evidence) LIKE ?
            )
          )
        ORDER BY n.finalized_at DESC, n.created_at DESC
        LIMIT ?
        """,
        (int(args.all_tasks), args.task_id, needle, needle, needle, args.limit),
    ).fetchall()
    # ponytail: substring scan is enough for a local run; add FTS only when database size proves it necessary.
    emit([node_data(conn, item["id"]) for item in results])


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--db", type=Path, required=True)
    commands = result.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init")
    init.add_argument("--task", type=Path, required=True)

    add = commands.add_parser("add-node")
    add.add_argument("--task-id", required=True)
    add.add_argument("--action", choices=("baseline", "propose", "refine", "repair", "fuse"), required=True)
    add.add_argument("--artifact", required=True)
    add.add_argument("--idea", required=True)
    add.add_argument("--parent", action="append")
    add.add_argument("--manifest", type=Path)
    add.add_argument(
        "--component",
        help=(
            "Component-targeted propose/refine: feature_pipeline (FE-only) or "
            "oof_ensemble (ensemble-only). Split is excluded."
        ),
    )
    add.add_argument("--model-calls", type=int, default=1)

    record = commands.add_parser("record")
    record.add_argument("--node", required=True)
    record.add_argument("--kind", choices=("objective", "judgment", "constraint"), required=True)
    record.add_argument("--score", type=float)
    record.add_argument("--judge")
    record.add_argument("--passed", choices=("true", "false"))
    record.add_argument("--evidence", required=True)
    record.add_argument("--model-calls", type=int)

    finalize = commands.add_parser("finalize")
    finalize.add_argument("--node", required=True)

    select = commands.add_parser("select")
    select.add_argument("--task-id", required=True)
    select.add_argument("--exploration", type=float, default=math.sqrt(2))

    status = commands.add_parser("status")
    status.add_argument("--task-id", required=True)

    resume = commands.add_parser("resume")
    resume.add_argument("--task-id")

    best = commands.add_parser("best")
    best.add_argument("--task-id", required=True)

    show = commands.add_parser("show")
    show.add_argument("--node", required=True)

    query = commands.add_parser("query")
    query.add_argument("--task-id")
    query.add_argument("--all-tasks", action="store_true")
    query.add_argument("--text", required=True)
    query.add_argument("--limit", type=int, default=20)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        conn = connect(args.db)
        if args.command != "init":
            ensure_schema(conn)
        if args.command == "init":
            init_task(conn, args.task)
        elif args.command == "add-node":
            if args.model_calls < 0:
                raise ValueError("--model-calls cannot be negative")
            add_node(conn, args)
        elif args.command == "record":
            if args.model_calls is not None and args.model_calls < 0:
                raise ValueError("--model-calls cannot be negative")
            record_evaluation(conn, args)
        elif args.command == "finalize":
            finalize_node(conn, args.node)
        elif args.command == "select":
            if args.exploration < 0:
                raise ValueError("--exploration cannot be negative")
            select_node(conn, args.task_id, args.exploration)
        elif args.command == "status":
            task_status(conn, args.task_id)
        elif args.command == "resume":
            resume_search(conn, args.task_id)
        elif args.command == "best":
            best_node(conn, args.task_id)
        elif args.command == "show":
            emit(node_data(conn, args.node))
        elif args.command == "query":
            if args.limit <= 0:
                raise ValueError("--limit must be positive")
            query_nodes(conn, args)
        return 0
    except (FileNotFoundError, json.JSONDecodeError, sqlite3.Error, ValueError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
