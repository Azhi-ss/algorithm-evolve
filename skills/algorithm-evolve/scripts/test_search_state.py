import json
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
        path.mkdir()
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


if __name__ == "__main__":
    unittest.main()
