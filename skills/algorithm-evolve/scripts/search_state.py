#!/usr/bin/env python3
"""Persist and select Algorithm Evolve candidates without executing them."""

from __future__ import annotations

import argparse
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
    }


def init_task(conn: sqlite3.Connection, task_path: Path) -> None:
    data = validate_task(json.loads(task_path.read_text(encoding="utf-8")))
    budget = data["budget"]
    conn.executescript(SCHEMA)
    conn.execute(
        """
        INSERT INTO tasks (
            id, goal, artifact, evaluation_mode, evaluation_json, direction,
            constraints_json, budget_iterations, budget_seconds,
            budget_model_calls, target_score, stagnation_limit, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

    for parent_id in parents:
        parent = row(conn, "nodes", parent_id)
        if parent["task_id"] != args.task_id:
            raise ValueError("Parents must belong to the same task")
        allowed = {"finalized", "rejected"} if args.action == "repair" else {"finalized"}
        if parent["status"] not in allowed:
            raise ValueError(f"Parent {parent_id} is not eligible for {args.action}")

    artifact = Path(args.artifact).resolve()
    if not artifact.is_dir():
        raise ValueError(f"Candidate artifact is not a directory: {artifact}")

    node_id = f"n-{uuid.uuid4().hex[:12]}"
    conn.execute(
        "INSERT INTO nodes (id, task_id, action, artifact, idea, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (node_id, args.task_id, args.action, str(artifact), args.idea, now()),
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
    emit({"node_id": node_id, "parents": parents})


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


def task_status(conn: sqlite3.Connection, task_id: str) -> None:
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
    emit(
        {
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
            conn.executescript(SCHEMA)
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
