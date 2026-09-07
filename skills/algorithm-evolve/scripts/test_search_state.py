import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


TOOL = Path(__file__).with_name("search_state.py")


class SearchStateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / "state.db"

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *args, ok=True):
        result = subprocess.run(
            [sys.executable, str(TOOL), "--db", str(self.db), *args],
            check=False,
            capture_output=True,
            text=True,
        )
        if ok and result.returncode != 0:
            self.fail(result.stderr)
        if not ok:
            self.assertNotEqual(result.returncode, 0)
            return json.loads(result.stderr)
        return json.loads(result.stdout)

    def artifact(self, name):
        path = self.root / name
        path.mkdir(exist_ok=True)
        return str(path)

    def write_task(self, task_id, mode="objective", **budget):
        evaluation = (
            {"mode": "judgment", "rubric": ["correct", "simple"]}
            if mode == "judgment"
            else {"mode": mode, "command": "python benchmark.py"}
        )
        task = {
            "id": task_id,
            "goal": "Improve the example algorithm",
            "artifact": self.artifact("source"),
            "evaluation": evaluation,
            "direction": "maximize",
            "constraints": ["tests pass"] if mode != "judgment" else [],
            "budget": {"iterations": 10, **budget},
        }
        path = self.root / "task.json"
        path.write_text(json.dumps(task), encoding="utf-8")
        self.run_cli("init", "--task", str(path))

    def add(self, action, artifact, idea, *parents, model_calls="1"):
        args = [
            "add-node",
            "--task-id",
            "demo",
            "--action",
            action,
            "--artifact",
            artifact,
            "--idea",
            idea,
            "--model-calls",
            model_calls,
        ]
        for parent in parents:
            args.extend(("--parent", parent))
        return self.run_cli(*args)["node_id"]

    def score_objective(self, node_id, score):
        self.run_cli(
            "record",
            "--node",
            node_id,
            "--kind",
            "constraint",
            "--passed",
            "true",
            "--evidence",
            "tests passed",
        )
        self.run_cli(
            "record",
            "--node",
            node_id,
            "--kind",
            "objective",
            "--score",
            str(score),
            "--evidence",
            "benchmark.json",
        )
        return self.run_cli("finalize", "--node", node_id)

    def test_objective_dag_lifecycle(self):
        self.write_task("demo", target_score=13)
        baseline = self.add("baseline", self.artifact("baseline"), "linear scan", model_calls="0")
        self.score_objective(baseline, 10)

        indexed = self.add("refine", self.artifact("indexed"), "indexed lookup", baseline)
        self.score_objective(indexed, 12)
        cached = self.add("propose", self.artifact("cached"), "cache repeated lookup", baseline)
        self.score_objective(cached, 11)
        fused = self.add("fuse", self.artifact("fused"), "combine index and cache", indexed, cached)
        self.score_objective(fused, 13)

        baseline_data = self.run_cli("show", "--node", baseline)
        self.assertEqual(baseline_data["visits"], 4)
        self.assertEqual(baseline_data["value_sum"], 3.5)
        self.assertEqual(self.run_cli("best", "--task-id", "demo")["id"], fused)
        self.assertEqual(
            self.run_cli("query", "--task-id", "demo", "--text", "combine")[0]["id"],
            fused,
        )
        self.assertEqual(
            self.run_cli("status", "--task-id", "demo")["stop_reasons"],
            ["target_score"],
        )

    def test_judgment_requires_three_reviewers(self):
        self.write_task("demo", mode="judgment")
        node = self.add("propose", self.artifact("candidate"), "new search policy")
        for judge, score in (("a", 0.6), ("b", 0.9)):
            self.run_cli(
                "record",
                "--node",
                node,
                "--kind",
                "judgment",
                "--judge",
                judge,
                "--score",
                str(score),
                "--evidence",
                f"{judge}.json",
            )
        error = self.run_cli("finalize", "--node", node, ok=False)
        self.assertIn("three distinct reviewers", error["error"])

        self.run_cli(
            "record",
            "--node",
            node,
            "--kind",
            "judgment",
            "--judge",
            "c",
            "--score",
            "0.7",
            "--evidence",
            "c.json",
        )
        finalized = self.run_cli("finalize", "--node", node)
        self.assertEqual(finalized["score"], 0.7)

    def test_resume_reports_the_next_pending_step(self):
        self.write_task("demo")
        node = self.add("baseline", self.artifact("baseline"), "linear scan", model_calls="0")

        snapshot = self.run_cli("resume")
        self.assertEqual(snapshot["next_action"], "resume_pending_nodes")
        self.assertEqual(snapshot["pending_nodes"][0]["resume"]["action"], "record_constraints")

        self.run_cli(
            "record",
            "--node",
            node,
            "--kind",
            "constraint",
            "--passed",
            "true",
            "--evidence",
            "tests passed",
        )
        snapshot = self.run_cli("resume")
        self.assertEqual(snapshot["pending_nodes"][0]["resume"]["action"], "run_objective_evaluation")

        self.run_cli(
            "record",
            "--node",
            node,
            "--kind",
            "objective",
            "--score",
            "10",
            "--evidence",
            "benchmark.json",
        )
        snapshot = self.run_cli("resume")
        self.assertEqual(snapshot["pending_nodes"][0]["resume"]["action"], "finalize_node")

        self.run_cli("finalize", "--node", node)
        snapshot = self.run_cli("resume")
        self.assertEqual(snapshot["next_action"], "select_and_expand")
        self.assertEqual(snapshot["best"]["id"], node)

    def valid_methodology(self, **overrides):
        methodology = {
            "split_contract": {
                "kind": "kfold",
                "n_splits": 5,
                "purge": 0,
                "embargo": 1,
            },
            "oof_ensemble": {
                "members": ["baseline", "tree"],
                "method": "mean",
                "oof": {"protocol": "kfold"},
            },
            "feature_pipeline": {
                "steps": [{"name": "impute"}, {"name": "scale"}],
            },
        }
        methodology.update(overrides)
        return methodology

    def write_raw_task(self, task, ok=True):
        path = self.root / "task.json"
        path.write_text(json.dumps(task), encoding="utf-8")
        return self.run_cli("init", "--task", str(path), ok=ok)

    def base_task(self, task_id="demo", methodology=None):
        task = {
            "id": task_id,
            "goal": "Improve the example algorithm",
            "artifact": self.artifact("source"),
            "evaluation": {"mode": "objective", "command": "python benchmark.py"},
            "direction": "maximize",
            "constraints": ["tests pass"],
            "budget": {"iterations": 10},
        }
        if methodology is not None:
            task["methodology"] = methodology
        return task

    def test_status_without_methodology_omits_the_block(self):
        self.write_task("demo")
        status = self.run_cli("status", "--task-id", "demo")
        self.assertNotIn("methodology", status)
        self.assertEqual(
            set(status),
            {
                "best_node_id",
                "best_score",
                "iterations",
                "model_calls",
                "pending",
                "rejected",
                "stagnation",
                "stop_reasons",
                "stopped",
                "task_id",
            },
        )
        snapshot = self.run_cli("resume")
        self.assertNotIn("methodology", snapshot["status"])
        self.assertNotIn("methodology", snapshot["task"])
        self.assertEqual(
            set(snapshot["task"]),
            {"artifact", "direction", "evaluation", "goal", "id"},
        )

    def test_methodology_block_is_canonicalized_and_exposed(self):
        methodology = self.valid_methodology()
        self.write_raw_task(self.base_task(methodology=methodology))

        status = self.run_cli("status", "--task-id", "demo")
        self.assertEqual(status["methodology"], methodology)
        snapshot = self.run_cli("resume")
        self.assertEqual(snapshot["status"]["methodology"], methodology)
        self.assertEqual(snapshot["task"]["methodology"], methodology)

    def test_methodology_accepts_camel_case_aliases(self):
        self.write_raw_task(
            self.base_task(
                methodology={
                    "splitContract": {
                        "kind": "group",
                        "groupColumn": "user_id",
                        "purge": 2,
                        "embargo": 3,
                    },
                    "oofEnsemble": {
                        "ensembleMembers": ["a", "b"],
                        "ensembleMethod": "rank",
                        "oofProtocol": {"protocol": "group"},
                        "declaredEquivalent": False,
                    },
                    "featurePipeline": {"pipelineSteps": ["impute", {"name": "scale"}]},
                }
            )
        )
        methodology = self.run_cli("status", "--task-id", "demo")["methodology"]
        self.assertEqual(
            methodology["split_contract"],
            {"kind": "group", "group_column": "user_id", "purge": 2, "embargo": 3},
        )
        self.assertEqual(
            methodology["oof_ensemble"],
            {
                "declared_equivalent": False,
                "members": ["a", "b"],
                "method": "rank",
                "oof": {"protocol": "group"},
            },
        )
        self.assertEqual(
            methodology["feature_pipeline"],
            {"steps": ["impute", {"name": "scale"}]},
        )

    def test_declared_equivalent_allows_missing_oof_protocol(self):
        methodology = self.valid_methodology(
            oof_ensemble={
                "members": ["a", "b"],
                "method": "mean",
                "declared_equivalent": True,
            }
        )
        self.write_raw_task(self.base_task(methodology=methodology))
        self.assertEqual(
            self.run_cli("status", "--task-id", "demo")["methodology"]["oof_ensemble"],
            {"declared_equivalent": True, "members": ["a", "b"], "method": "mean"},
        )

    def test_init_fail_closes_on_malformed_methodology(self):
        cases = [
            (
                {"split_contract": {"kind": "random", "purge": 0, "embargo": 0}},
                "kfold, time, or group",
            ),
            (
                {"split_contract": {"kind": "kfold", "purge": -1, "embargo": 0}},
                "non-negative number",
            ),
            (
                {"split_contract": {"kind": "time", "purge": 0, "embargo": -2}},
                "non-negative number",
            ),
            (
                {"split_contract": {"kind": "group", "purge": 0, "embargo": 0}},
                "group_column",
            ),
            (
                {
                    "oof_ensemble": {
                        "members": ["only"],
                        "method": "mean",
                        "declared_equivalent": True,
                    }
                },
                "at least 2 members",
            ),
            (
                {"oof_ensemble": {"members": ["a", "b"], "method": "mean"}},
                "oof protocol or declared_equivalent",
            ),
        ]
        for methodology, needle in cases:
            with self.subTest(needle=needle, methodology=methodology):
                self.db.unlink(missing_ok=True)
                error = self.write_raw_task(
                    self.base_task(methodology=methodology),
                    ok=False,
                )
                self.assertIn(needle, error["error"])

    def test_legacy_database_without_methodology_column_stays_compatible(self):
        self.write_task("demo")
        conn = sqlite3.connect(self.db)
        conn.execute("ALTER TABLE tasks DROP COLUMN methodology_json")
        conn.commit()
        conn.close()
        status = self.run_cli("status", "--task-id", "demo")
        self.assertNotIn("methodology", status)
        self.assertEqual(status["task_id"], "demo")


if __name__ == "__main__":
    unittest.main()
