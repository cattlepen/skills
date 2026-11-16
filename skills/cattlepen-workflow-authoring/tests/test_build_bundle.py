import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
import uuid

SKILL = pathlib.Path(__file__).resolve().parents[1]
BUILDER = SKILL / "scripts" / "build_bundle.py"

WORKFLOW = """schema_version: 2
id: REPLACE_WITH_ENTRY_ID
name: sample
agents:
  worker: {version: 1}
deliverables:
  report: {version: 1}
  verdict: {version: 1}
entry: write
nodes:
  write:
    type: agent
    label: Write the report
    agent: worker
    runtime: {harness: claude-code}
    produces: [report]
    next: check
  check:
    type: inline
    run:
      script: |
        printf '%s' "$SHEPHERD__REPORT" > /dev/null
        printf '{"result":"pass"}' > "$SHEPHERD_OUT/verdict.json"
    consumes: {report: write}
    produces: [verdict]
    next: done
  done:
    type: end
"""


class BuildBundleTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = pathlib.Path(temp.name)
        self.root = self.base / "source"
        self.write("workflow.yml", WORKFLOW)
        self.write("agents/worker/1/agent.yml",
                   "schema_version: 1\nid: REPLACE_WITH_ENTRY_ID\nname: worker\nprompt: {sha256: " + "0" * 64 + "}\n")
        self.write("agents/worker/1/prompt.md", "Write `report`: a short report. Café.\n")
        self.write("deliverables/report/1.yml",
                   "schema_version: 1\nid: REPLACE_WITH_ENTRY_ID\nname: report\nformat: markdown\n")
        self.write("deliverables/verdict/1.yml",
                   "schema_version: 1\nid: REPLACE_WITH_ENTRY_ID\nname: verdict\nformat: json\nfields:\n"
                   "  result: {type: string, required: true, enum: [pass, fail]}\n")

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def run_builder(self, *extra):
        return subprocess.run([sys.executable, str(BUILDER), str(self.root), *extra],
                              capture_output=True, text=True, encoding="utf-8", check=False)

    def test_builds_a_schema_3_bundle_and_an_identical_validation_copy(self):
        copy = self.base / "copy"
        result = self.run_builder("--validate-copy", str(copy))
        self.assertEqual(result.returncode, 0, result.stderr)
        bundle = json.loads(result.stdout)
        self.assertEqual(bundle["kind"], "cattlepen.workflow")
        self.assertEqual(bundle["schema_version"], 3)
        self.assertEqual(bundle["editor_state"], {"schema": 2, "nodes": {}, "groups": {}, "reroutes": {}})
        agent = bundle["dependencies"]["agents"][0]
        deliverables = bundle["dependencies"]["deliverables"]
        ids = [bundle["workflow"]["definition_id"], agent["definition_id"]] + [d["definition_id"] for d in deliverables]
        self.assertEqual(len(set(ids)), 4)
        for value in ids:
            uuid.UUID(value)
        self.assertIn("id: " + bundle["workflow"]["definition_id"] + "\n", bundle["declaration"])
        self.assertEqual(agent["declaration"].count("prompt:"), 1)
        self.assertIn(hashlib.sha256(agent["prompt"].encode("utf-8")).hexdigest(), agent["declaration"])
        self.assertEqual(sorted((b["kind"], b["name"]) for b in bundle["workflow"]["bindings"]),
                         [("agent", "worker"), ("deliverable", "report"), ("deliverable", "verdict")])
        for binding in bundle["workflow"]["bindings"]:
            self.assertEqual(binding["revision"], 0)
        expected = {"workflow.yml": bundle["declaration"],
                    "agents/worker/1/agent.yml": agent["declaration"],
                    "agents/worker/1/prompt.md": agent["prompt"]}
        for item in deliverables:
            expected[f"deliverables/{item['name']}/1.yml"] = item["declaration"]
        for relative, content in expected.items():
            self.assertEqual((copy / relative).read_bytes(), content.encode("utf-8"))

    def test_prefix_renames_references_scripts_and_backticked_prompt_names(self):
        result = self.run_builder("--prefix", "acme_")
        self.assertEqual(result.returncode, 0, result.stderr)
        bundle = json.loads(result.stdout)
        workflow = bundle["declaration"]
        self.assertIn("name: acme_sample\n", workflow)
        self.assertIn("  acme_worker: {version: 1}\n", workflow)
        self.assertIn('"$SHEPHERD__ACME_REPORT"', workflow)
        self.assertIn('"$SHEPHERD_OUT/acme_verdict.json"', workflow)
        self.assertIn("consumes: {acme_report: write}", workflow)
        self.assertIn("label: Write the report\n", workflow)
        agent = bundle["dependencies"]["agents"][0]
        self.assertEqual(agent["name"], "acme_worker")
        self.assertIn("Write `acme_report`:", agent["prompt"])
        self.assertEqual(sorted(d["name"] for d in bundle["dependencies"]["deliverables"]),
                         ["acme_report", "acme_verdict"])

    def test_prefix_refuses_a_name_that_is_also_a_field_name(self):
        self.write("deliverables/verdict/1.yml",
                   "schema_version: 1\nid: REPLACE_WITH_ENTRY_ID\nname: verdict\nformat: json\nfields:\n"
                   "  report: {type: string, required: true}\n")
        result = self.run_builder("--prefix", "acme_")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("cannot rename 'report'", result.stderr)

    def test_refuses_two_versions_of_one_dependency(self):
        self.write("deliverables/report/2.yml", "schema_version: 1\nid: REPLACE_WITH_ENTRY_ID\nname: report\n")
        result = self.run_builder()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("select exactly one version", result.stderr)

    def test_refuses_a_pin_that_disagrees_with_the_directory_and_writes_nothing(self):
        (self.root / "agents/worker/1").rename(self.root / "agents/worker/2")
        copy = self.base / "copy"
        result = self.run_builder("--validate-copy", str(copy))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("pins version 1", result.stderr)
        self.assertFalse(copy.exists())

    def test_refuses_an_unpinned_dependency(self):
        self.write("deliverables/extra/1.yml", "schema_version: 1\nid: REPLACE_WITH_ENTRY_ID\nname: extra\n")
        result = self.run_builder()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("present but not pinned ['extra']", result.stderr)

    def test_every_shipped_example_builds(self):
        for example in sorted((SKILL / "examples").iterdir()):
            if not (example / "workflow.yml").is_file():
                continue
            with self.subTest(example=example.name):
                result = subprocess.run([sys.executable, str(BUILDER), str(example)], capture_output=True,
                                        text=True, encoding="utf-8", check=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)["workflow"]["name"], example.name)


if __name__ == "__main__":
    unittest.main()
