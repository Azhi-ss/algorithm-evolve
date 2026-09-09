import hashlib
import json
import math
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import search_state


TOOL = Path(__file__).with_name("search_state.py")
FAKE_GENERATOR = Path(__file__).with_name("fake_generator.py")


class SearchStateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / "state.db"

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *args, ok=True, extra_env=None):
        env = os.environ.copy()
        if extra_env:
            env.update(extra_env)
        result = subprocess.run(
            [sys.executable, str(TOOL), "--db", str(self.db), *args],
            check=False,
            capture_output=True,
            text=True,
            env=env,
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

    def write_task(self, task_id, mode="objective", methodology=None, **budget):
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
        if methodology is not None:
            task["methodology"] = methodology
        path = self.root / "task.json"
        path.write_text(json.dumps(task), encoding="utf-8")
        self.run_cli("init", "--task", str(path))

    def add(
        self,
        action,
        artifact,
        idea,
        *parents,
        model_calls="1",
        manifest=None,
        component=None,
        ok=True,
    ):
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
        if manifest is not None:
            if isinstance(manifest, dict):
                path = self.root / f"{Path(artifact).name}-manifest.json"
                path.write_text(json.dumps(manifest), encoding="utf-8")
                args.extend(("--manifest", str(path)))
            else:
                args.extend(("--manifest", str(manifest)))
        if component is not None:
            args.extend(("--component", component))
        result = self.run_cli(*args, ok=ok)
        if not ok:
            return result
        return result["node_id"]

    def run_fake_generator(
        self,
        out,
        action="propose",
        component=None,
        parent_manifest=None,
        idea=None,
        ok=True,
    ):
        args = [sys.executable, str(FAKE_GENERATOR), "--out", str(out), "--action", action]
        if component is not None:
            args.extend(("--component", component))
        if parent_manifest is not None:
            path = self.root / f"{Path(out).name}-parent-manifest.json"
            path.write_text(json.dumps(parent_manifest), encoding="utf-8")
            args.extend(("--parent-manifest", str(path)))
        if idea is not None:
            args.extend(("--idea", idea))
        result = subprocess.run(args, check=False, capture_output=True, text=True)
        if ok and result.returncode != 0:
            self.fail(result.stderr)
        if not ok:
            self.assertNotEqual(result.returncode, 0)
            return json.loads(result.stderr)
        return json.loads(result.stdout)

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

    def split_digest(self, split_contract):
        payload = json.dumps(split_contract, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def matching_manifest(self, methodology=None, **overrides):
        methodology = methodology or self.valid_methodology()
        manifest = {
            "feature_pipeline": methodology.get("feature_pipeline", {"steps": []}),
            "oof_ensemble": {
                "members": methodology.get("oof_ensemble", {}).get("members", ["a", "b"]),
                "oof": methodology.get("oof_ensemble", {}).get("oof", {"protocol": "kfold"}),
            },
            "split_ref": {
                "digest_summary": self.split_digest(methodology["split_contract"]),
            },
        }
        if "declared_equivalent" in methodology.get("oof_ensemble", {}):
            manifest["oof_ensemble"]["declared_equivalent"] = methodology["oof_ensemble"][
                "declared_equivalent"
            ]
            if "oof" not in methodology["oof_ensemble"]:
                manifest["oof_ensemble"].pop("oof", None)
        manifest.update(overrides)
        return manifest

    def test_standalone_node_without_manifest_omits_the_field(self):
        self.write_task("demo")
        node = self.add("baseline", self.artifact("baseline"), "linear scan", model_calls="0")
        shown = self.run_cli("show", "--node", node)
        self.assertNotIn("manifest", shown)
        self.assertNotIn("manifest_json", shown)

    def test_add_node_accepts_candidate_manifest(self):
        methodology = self.valid_methodology()
        self.write_task("demo", methodology=methodology)
        manifest = self.matching_manifest(methodology)
        node = self.add(
            "baseline",
            self.artifact("baseline"),
            "linear scan",
            model_calls="0",
            manifest=manifest,
        )
        shown = self.run_cli("show", "--node", node)
        self.assertEqual(shown["manifest"]["split_ref"]["digest_summary"], manifest["split_ref"]["digest_summary"])
        self.assertEqual(shown["manifest"]["feature_pipeline"], manifest["feature_pipeline"])
        self.assertEqual(shown["manifest"]["oof_ensemble"]["members"], ["baseline", "tree"])
        self.assertEqual(shown["manifest"]["oof_ensemble"]["oof"], {"protocol": "kfold"})

    def test_add_node_reads_manifest_from_candidate_directory(self):
        methodology = self.valid_methodology()
        self.write_task("demo", methodology=methodology)
        artifact = Path(self.artifact("baseline"))
        (artifact / "methodology.json").write_text(
            json.dumps(self.matching_manifest(methodology)),
            encoding="utf-8",
        )
        node = self.add("baseline", str(artifact), "linear scan", model_calls="0")
        shown = self.run_cli("show", "--node", node)
        self.assertEqual(
            shown["manifest"]["split_ref"]["digest_summary"],
            self.split_digest(methodology["split_contract"]),
        )

    def test_add_node_rejects_missing_manifest_when_contracts_injected(self):
        self.write_task("demo", methodology=self.valid_methodology())
        error = self.add(
            "baseline",
            self.artifact("baseline"),
            "linear scan",
            model_calls="0",
            ok=False,
        )
        self.assertIn("methodology contracts", error["error"])
        self.assertIn("manifest is required", error["error"])

    def test_add_node_accepts_camel_case_manifest_aliases(self):
        methodology = self.valid_methodology()
        self.write_task("demo", methodology=methodology)
        digest = self.split_digest(methodology["split_contract"])
        node = self.add(
            "baseline",
            self.artifact("baseline"),
            "linear scan",
            model_calls="0",
            manifest={
                "featurePipeline": {"pipelineSteps": [{"name": "impute"}]},
                "oofEnsemble": {
                    "ensembleMembers": ["a", "b"],
                    "oofProtocol": {"protocol": "kfold"},
                },
                "splitRef": {"digestSummary": digest},
            },
        )
        shown = self.run_cli("show", "--node", node)
        self.assertEqual(shown["manifest"]["split_ref"]["digest_summary"], digest)
        self.assertEqual(shown["manifest"]["feature_pipeline"]["steps"], [{"name": "impute"}])
        self.assertEqual(shown["manifest"]["oof_ensemble"]["members"], ["a", "b"])

    def test_finalize_rejects_split_digest_mismatch_as_constraint(self):
        methodology = self.valid_methodology()
        self.write_task("demo", methodology=methodology)
        manifest = self.matching_manifest(
            methodology,
            split_ref={"digest_summary": "0" * 64},
        )
        node = self.add(
            "baseline",
            self.artifact("baseline"),
            "linear scan",
            model_calls="0",
            manifest=manifest,
        )
        result = self.score_objective(node, 10)
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reward"], 0.0)
        shown = self.run_cli("show", "--node", node)
        self.assertEqual(shown["status"], "rejected")
        self.assertEqual(shown["effective_kind"], "constraint")
        self.assertEqual(shown["reward"], 0.0)
        evidence = " ".join(item["evidence"] for item in shown["evaluations"])
        self.assertIn("split_ref digest summary", evidence)
        self.assertEqual(self.run_cli("status", "--task-id", "demo")["best_node_id"], None)

    def test_finalize_accepts_matching_split_digest_and_oof(self):
        methodology = self.valid_methodology()
        self.write_task("demo", methodology=methodology)
        node = self.add(
            "baseline",
            self.artifact("baseline"),
            "linear scan",
            model_calls="0",
            manifest=self.matching_manifest(methodology),
        )
        result = self.score_objective(node, 10)
        self.assertEqual(result["status"], "finalized")
        self.assertEqual(result["score"], 10)
        shown = self.run_cli("show", "--node", node)
        self.assertEqual(shown["effective_kind"], "objective")
        self.assertEqual(self.run_cli("best", "--task-id", "demo")["id"], node)

    def test_finalize_accepts_manifest_split_contract_digest(self):
        methodology = self.valid_methodology()
        self.write_task("demo", methodology=methodology)
        manifest = self.matching_manifest(methodology)
        manifest.pop("split_ref")
        manifest["split_contract"] = methodology["split_contract"]
        node = self.add(
            "baseline",
            self.artifact("baseline"),
            "linear scan",
            model_calls="0",
            manifest=manifest,
        )
        result = self.score_objective(node, 9)
        self.assertEqual(result["status"], "finalized")

    def test_finalize_rejects_missing_oof_when_task_declares_ensemble(self):
        methodology = self.valid_methodology()
        self.write_task("demo", methodology=methodology)
        manifest = {
            "feature_pipeline": methodology["feature_pipeline"],
            "split_ref": {"digest_summary": self.split_digest(methodology["split_contract"])},
        }
        node = self.add(
            "baseline",
            self.artifact("baseline"),
            "linear scan",
            model_calls="0",
            manifest=manifest,
        )
        result = self.score_objective(node, 10)
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reward"], 0.0)
        shown = self.run_cli("show", "--node", node)
        self.assertEqual(shown["effective_kind"], "constraint")
        evidence = " ".join(item["evidence"] for item in shown["evaluations"])
        self.assertIn("oof protocol or declared_equivalent", evidence)

    def test_finalize_accepts_declared_equivalent_oof_protocol(self):
        methodology = self.valid_methodology(
            oof_ensemble={
                "members": ["a", "b"],
                "method": "mean",
                "declared_equivalent": True,
            }
        )
        self.write_task("demo", methodology=methodology)
        node = self.add(
            "baseline",
            self.artifact("baseline"),
            "linear scan",
            model_calls="0",
            manifest=self.matching_manifest(methodology),
        )
        result = self.score_objective(node, 8)
        self.assertEqual(result["status"], "finalized")
        self.assertEqual(self.run_cli("show", "--node", node)["manifest"]["oof_ensemble"]["declared_equivalent"], True)

    def test_feature_pipeline_only_task_finalizes_with_manifest(self):
        methodology = {"feature_pipeline": {"steps": [{"name": "impute"}]}}
        self.write_task("demo", methodology=methodology)
        node = self.add(
            "baseline",
            self.artifact("baseline"),
            "linear scan",
            model_calls="0",
            manifest={"feature_pipeline": {"steps": [{"name": "impute"}]}},
        )
        result = self.score_objective(node, 7)
        self.assertEqual(result["status"], "finalized")

    def test_legacy_database_without_manifest_column_stays_compatible(self):
        self.write_task("demo")
        node = self.add("baseline", self.artifact("baseline"), "linear scan", model_calls="0")
        conn = sqlite3.connect(self.db)
        conn.execute("ALTER TABLE nodes DROP COLUMN manifest_json")
        conn.commit()
        conn.close()
        shown = self.run_cli("show", "--node", node)
        self.assertNotIn("manifest", shown)
        self.assertEqual(shown["id"], node)

    def test_component_split_is_structurally_excluded(self):
        methodology = self.valid_methodology()
        self.write_task("demo", methodology=methodology)
        parent = self.add(
            "baseline",
            self.artifact("baseline"),
            "linear scan",
            model_calls="0",
            manifest=self.matching_manifest(methodology),
        )
        self.score_objective(parent, 10)
        for name in ("split", "split_contract", "split-ref", "split_ref"):
            with self.subTest(component=name):
                error = self.add(
                    "refine",
                    self.artifact(f"bad-{name}"),
                    "try to change split",
                    parent,
                    manifest=self.matching_manifest(methodology),
                    component=name,
                    ok=False,
                )
                self.assertIn("immutable", error["error"])
                self.assertIn("excluded", error["error"])

    def test_component_rejected_on_non_propose_refine_actions(self):
        methodology = self.valid_methodology()
        self.write_task("demo", methodology=methodology)
        error = self.add(
            "baseline",
            self.artifact("baseline"),
            "linear scan",
            model_calls="0",
            manifest=self.matching_manifest(methodology),
            component="feature_pipeline",
            ok=False,
        )
        self.assertIn("only valid for propose and refine", error["error"])

    def test_component_requires_a_parent(self):
        methodology = self.valid_methodology()
        self.write_task("demo", methodology=methodology)
        error = self.add(
            "propose",
            self.artifact("orphan"),
            "FE-only without parent",
            manifest=self.matching_manifest(methodology),
            component="fe-only",
            ok=False,
        )
        self.assertIn("requires a parent", error["error"])

    def test_fe_only_refine_rewrites_pipeline_and_freezes_ensemble(self):
        methodology = self.valid_methodology()
        self.write_task("demo", methodology=methodology)
        parent_manifest = self.matching_manifest(methodology)
        parent = self.add(
            "baseline",
            self.artifact("baseline"),
            "linear scan",
            model_calls="0",
            manifest=parent_manifest,
        )
        self.score_objective(parent, 10)
        child_manifest = deepcopy(parent_manifest)
        child_manifest["feature_pipeline"] = {
            "steps": [{"name": "impute"}, {"name": "scale"}, {"name": "select"}]
        }
        node = self.add(
            "refine",
            self.artifact("fe-only"),
            "FE-only rewrite",
            parent,
            manifest=child_manifest,
            component="fe",
        )
        added = self.run_cli("show", "--node", node)
        self.assertEqual(added["target_component"], "feature_pipeline")
        self.assertEqual(
            added["manifest"]["feature_pipeline"]["steps"][-1],
            {"name": "select"},
        )
        self.assertEqual(added["manifest"]["oof_ensemble"], parent_manifest["oof_ensemble"])
        result = self.score_objective(node, 11)
        self.assertEqual(result["status"], "finalized")

    def test_unknown_component_is_rejected(self):
        methodology = self.valid_methodology()
        self.write_task("demo", methodology=methodology)
        parent = self.add(
            "baseline",
            self.artifact("baseline"),
            "linear scan",
            model_calls="0",
            manifest=self.matching_manifest(methodology),
        )
        self.score_objective(parent, 10)
        error = self.add(
            "refine",
            self.artifact("unknown-component"),
            "not a real component",
            parent,
            manifest=self.matching_manifest(methodology),
            component="architecture",
            ok=False,
        )
        self.assertIn("feature_pipeline or oof_ensemble", error["error"])

    def test_fe_only_rejects_split_ref_mutation(self):
        methodology = self.valid_methodology()
        self.write_task("demo", methodology=methodology)
        parent_manifest = self.matching_manifest(methodology)
        parent = self.add(
            "baseline",
            self.artifact("baseline"),
            "linear scan",
            model_calls="0",
            manifest=parent_manifest,
        )
        self.score_objective(parent, 10)
        mutated = deepcopy(parent_manifest)
        mutated["feature_pipeline"] = {"steps": [{"name": "impute"}, {"name": "new"}]}
        mutated["split_ref"] = {"digest_summary": "a" * 64}
        error = self.add(
            "refine",
            self.artifact("fe-mutates-split"),
            "FE-only but changed split digest",
            parent,
            manifest=mutated,
            component="feature_pipeline",
            ok=False,
        )
        self.assertIn("cannot change split_ref", error["error"])

    def test_fe_only_rejects_ensemble_mutation(self):
        methodology = self.valid_methodology()
        self.write_task("demo", methodology=methodology)
        parent_manifest = self.matching_manifest(methodology)
        parent = self.add(
            "baseline",
            self.artifact("baseline"),
            "linear scan",
            model_calls="0",
            manifest=parent_manifest,
        )
        self.score_objective(parent, 10)
        mutated = deepcopy(parent_manifest)
        mutated["oof_ensemble"]["members"] = ["baseline", "swapped"]
        error = self.add(
            "refine",
            self.artifact("fe-mutates-ensemble"),
            "FE-only but swapped members",
            parent,
            manifest=mutated,
            component="feature_pipeline",
            ok=False,
        )
        self.assertIn("cannot change oof_ensemble", error["error"])

    def test_ensemble_only_rejects_pipeline_mutation_and_non_member_ensemble_edits(self):
        methodology = self.valid_methodology()
        self.write_task("demo", methodology=methodology)
        parent_manifest = self.matching_manifest(methodology)
        parent = self.add(
            "baseline",
            self.artifact("baseline"),
            "linear scan",
            model_calls="0",
            manifest=parent_manifest,
        )
        self.score_objective(parent, 10)
        pipeline_changed = deepcopy(parent_manifest)
        pipeline_changed["feature_pipeline"]["steps"].append({"name": "extra"})
        error = self.add(
            "propose",
            self.artifact("ens-mutates-fe"),
            "ensemble-only but rewrote FE",
            parent,
            manifest=pipeline_changed,
            component="ensemble-only",
            ok=False,
        )
        self.assertIn("cannot change feature_pipeline", error["error"])

        method_changed = deepcopy(parent_manifest)
        method_changed["oof_ensemble"]["method"] = "rank"
        error = self.add(
            "refine",
            self.artifact("ens-mutates-method"),
            "ensemble-only but changed method",
            parent,
            manifest=method_changed,
            component="oof_ensemble",
            ok=False,
        )
        self.assertIn("members only", error["error"])

    def test_scripted_generator_e2e_produces_manifest_bearing_nodes(self):
        methodology = self.valid_methodology()
        self.write_task("demo", methodology=methodology)
        parent_manifest = self.matching_manifest(methodology)

        baseline_dir = Path(self.artifact("gen-baseline"))
        (baseline_dir / "solution.py").write_text("# baseline\n", encoding="utf-8")
        (baseline_dir / "methodology.json").write_text(
            json.dumps(parent_manifest, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        baseline = self.add(
            "baseline",
            str(baseline_dir),
            "scripted baseline with four-field manifest",
            model_calls="0",
        )
        result = self.score_objective(baseline, 10)
        self.assertEqual(result["status"], "finalized")
        shown = self.run_cli("show", "--node", baseline)
        self.assertEqual(
            set(shown["manifest"]),
            {"feature_pipeline", "oof_ensemble", "split_ref"},
        )
        self.assertIn("steps", shown["manifest"]["feature_pipeline"])
        self.assertIn("members", shown["manifest"]["oof_ensemble"])
        self.assertIn("oof", shown["manifest"]["oof_ensemble"])
        self.assertIn("digest_summary", shown["manifest"]["split_ref"])

        fe = self.run_fake_generator(
            self.root / "gen-fe",
            action="refine",
            component="feature_pipeline",
            parent_manifest=parent_manifest,
        )
        self.assertEqual(fe["component"], "feature_pipeline")
        self.assertEqual(fe["changed_files"], ["feature_pipeline.py"])
        self.assertNotEqual(fe["manifest"]["feature_pipeline"], parent_manifest["feature_pipeline"])
        self.assertEqual(fe["manifest"]["oof_ensemble"], parent_manifest["oof_ensemble"])
        fe_node = self.add(
            "refine",
            fe["artifact"],
            fe["idea"],
            baseline,
            component="feature_pipeline",
        )
        fe_final = self.score_objective(fe_node, 11)
        self.assertEqual(fe_final["status"], "finalized")
        fe_shown = self.run_cli("show", "--node", fe_node)
        self.assertEqual(fe_shown["target_component"], "feature_pipeline")
        self.assertEqual(
            fe_shown["manifest"]["split_ref"]["digest_summary"],
            parent_manifest["split_ref"]["digest_summary"],
        )

        ens = self.run_fake_generator(
            self.root / "gen-ens",
            action="propose",
            component="ensemble",
            parent_manifest=parent_manifest,
        )
        self.assertEqual(ens["component"], "oof_ensemble")
        self.assertEqual(ens["manifest"]["feature_pipeline"], parent_manifest["feature_pipeline"])
        self.assertNotEqual(
            ens["manifest"]["oof_ensemble"]["members"],
            parent_manifest["oof_ensemble"]["members"],
        )
        ens_node = self.add(
            "propose",
            ens["artifact"],
            ens["idea"],
            baseline,
            component="oof_ensemble",
        )
        ens_final = self.score_objective(ens_node, 12)
        self.assertEqual(ens_final["status"], "finalized")
        self.assertEqual(
            self.run_cli("show", "--node", ens_node)["target_component"],
            "oof_ensemble",
        )
        self.assertEqual(self.run_cli("best", "--task-id", "demo")["id"], ens_node)

        split_error = self.run_fake_generator(
            self.root / "gen-split",
            action="refine",
            component="split",
            parent_manifest=parent_manifest,
            ok=False,
        )
        self.assertIn("immutable", split_error["error"])

    def test_standalone_task_still_omits_optional_manifest_and_gates_stay_dormant(self):
        self.write_task("demo")
        node = self.add("propose", self.artifact("standalone"), "no contract, no manifest")
        shown = self.run_cli("show", "--node", node)
        self.assertNotIn("manifest", shown)
        self.assertNotIn("target_component", shown)
        result = self.score_objective(node, 6)
        self.assertEqual(result["status"], "finalized")
        self.assertEqual(result["score"], 6)

    def reference_fixed_uct(self, nodes, exploration, rollouts):
        # Verbatim copy of the pre-PW-1 select_node UCT formula.
        scored = []
        for candidate in nodes:
            visits = max(1, candidate["visits"])
            uct = candidate["value_sum"] / visits + exploration * math.sqrt(
                math.log(rollouts) / visits
            )
            scored.append((uct, candidate["created_at"], candidate["id"]))
        uct, _, selected_id = max(scored, key=lambda item: (item[0], item[1]))
        return uct, selected_id

    def build_uct_vs_elite_graph(self, iterations=10):
        """UCT prefers a fresh mid-score leaf; Elite prefers the high-score hub."""
        self.write_task("demo", iterations=iterations)
        baseline = self.add("baseline", self.artifact("baseline"), "linear scan", model_calls="0")
        self.score_objective(baseline, 10)
        star = self.add("refine", self.artifact("star"), "high metric hub", baseline)
        self.score_objective(star, 20)
        for index in range(6):
            child = self.add(
                "refine",
                self.artifact(f"star-child-{index}"),
                f"regressing child {index}",
                star,
            )
            self.score_objective(child, 10.5)
        bait = self.add("propose", self.artifact("bait"), "fresh mid-score leaf", baseline)
        self.score_objective(bait, 11)
        return {"baseline": baseline, "star": star, "bait": bait}

    def test_default_select_matches_fixed_uct_reference_formula(self):
        ids = self.build_uct_vs_elite_graph()
        default = self.run_cli("select", "--task-id", "demo")
        explicit = self.run_cli("select", "--task-id", "demo", "--selection-id", "fixed_uct")
        self.assertEqual(default["selected"]["id"], ids["bait"])
        self.assertEqual(explicit["selected"]["id"], ids["bait"])
        self.assertEqual(set(default), {"selected", "uct"})
        self.assertEqual(default["selected"]["id"], explicit["selected"]["id"])
        self.assertEqual(default["uct"], explicit["uct"])

        conn = search_state.connect(self.db)
        try:
            task = search_state.row(conn, "tasks", "demo")
            nodes = conn.execute(
                "SELECT * FROM nodes WHERE task_id = ? AND status = 'finalized'",
                ("demo",),
            ).fetchall()
            rollouts = max(2, task["finalized_nodes"] + 1)
            expected_uct, expected_id = self.reference_fixed_uct(
                nodes, math.sqrt(2), rollouts
            )
        finally:
            conn.close()
        self.assertEqual(expected_id, ids["bait"])
        self.assertEqual(default["selected"]["id"], expected_id)
        self.assertEqual(default["uct"], expected_uct)
        self.assertEqual(search_state.resolve_selection_id(), search_state.SELECTION_FIXED_UCT)
        self.assertEqual(
            search_state.resolve_selection_id(selection_id="fixed_uct"),
            search_state.SELECTION_FIXED_UCT,
        )

    def test_progressive_t0_matches_uct_parent(self):
        ids = self.build_uct_vs_elite_graph()
        default = self.run_cli("select", "--task-id", "demo")
        progressive = self.run_cli(
            "select",
            "--task-id",
            "demo",
            "--selection-id",
            "progressive_mcgs_optin",
            "--progressive-t",
            "0",
            "--progressive-horizon",
            "10",
            "--progressive-seed",
            "99",
        )
        flag = self.run_cli(
            "select",
            "--task-id",
            "demo",
            "--progressive-mcgs-optin",
            "--progressive-t",
            "0",
        )
        self.assertEqual(default["selected"]["id"], ids["bait"])
        self.assertEqual(progressive["selected"]["id"], ids["bait"])
        self.assertEqual(flag["selected"]["id"], ids["bait"])
        self.assertEqual(progressive["selection_mode"], "uct")
        self.assertEqual(progressive["selection_id"], "progressive_mcgs_optin")
        self.assertEqual(progressive["progressive_uct_weight"], 1.0)
        self.assertEqual(progressive["uct"], default["uct"])

    def test_progressive_after_tau_can_take_elite_topk(self):
        ids = self.build_uct_vs_elite_graph()
        default = self.run_cli("select", "--task-id", "demo")
        self.assertEqual(default["selected"]["id"], ids["bait"])
        self.assertEqual(search_state.progressive_uct_weight(0, 10), 1.0)
        self.assertLess(search_state.progressive_uct_weight(7, 10), 1.0)

        conn = search_state.connect(self.db)
        try:
            elite_payload = None
            for seed in range(200):
                payload = search_state.choose_select_parent(
                    conn,
                    "demo",
                    math.sqrt(2),
                    selection_id="progressive_mcgs_optin",
                    progressive_t=7,
                    progressive_horizon=10,
                    progressive_seed=seed,
                )
                if (
                    payload.get("selection_mode") == "elite"
                    and payload["selected"]["id"] == ids["star"]
                ):
                    elite_payload = payload
                    elite_seed = seed
                    break
            self.assertIsNotNone(
                elite_payload,
                "expected a seeded Elite top-K draw of the high-score hub for t≥τ",
            )
            self.assertEqual(elite_payload["selected"]["id"], ids["star"])
            self.assertEqual(elite_payload["elite_rank"], 1)
            replay = search_state.choose_select_parent(
                conn,
                "demo",
                math.sqrt(2),
                progressive_mcgs_optin=True,
                progressive_t=7,
                progressive_horizon=10,
                progressive_seed=elite_seed,
            )
            self.assertEqual(replay["selection_mode"], "elite")
            self.assertEqual(replay["selected"]["id"], ids["star"])
            cli = self.run_cli(
                "select",
                "--task-id",
                "demo",
                "--selection-id",
                "progressive_mcgs_optin",
                "--progressive-t",
                "7",
                "--progressive-horizon",
                "10",
                "--progressive-seed",
                str(elite_seed),
            )
            self.assertEqual(cli["selection_mode"], "elite")
            self.assertEqual(cli["selected"]["id"], ids["star"])
        finally:
            conn.close()

    def test_bait_env_vars_cannot_flip_default_to_progressive(self):
        ids = self.build_uct_vs_elite_graph()
        bait_env = {
            "SELECTION_ID": "progressive_mcgs_optin",
            "PROGRESSIVE_MCGS": "1",
            "PROGRESSIVE_MCGS_OPTIN": "true",
            "EVOK_SELECTION_ID": "progressive_mcgs_optin",
            "SEARCH_SELECTION": "progressive",
        }
        default = self.run_cli("select", "--task-id", "demo", extra_env=bait_env)
        self.assertEqual(default["selected"]["id"], ids["bait"])
        self.assertEqual(set(default), {"selected", "uct"})
        self.assertNotIn("selection_id", default)
        self.assertNotIn("selection_mode", default)

    def test_selection_id_is_a_closed_enum_not_selection_policy(self):
        with self.assertRaises(ValueError):
            search_state.resolve_selection_id(selection_id="SelectionPolicy")
        with self.assertRaises(ValueError):
            search_state.resolve_selection_id(selection_id="annealing")
        self.assertFalse(hasattr(search_state, "SelectionPolicy"))


if __name__ == "__main__":
    unittest.main()
