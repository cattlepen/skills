import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

SKILL = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = SKILL / "scripts" / "export_to_bundle.py"


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


PROMPT = "# Worker\n\nWrite `report`.\n"
AGENT = f"schema_version: 1\nid: 11111111-1111-4111-8111-111111111111\nname: worker\nprompt:\n  sha256: {sha(PROMPT)}\n"
REPORT = "schema_version: 1\nid: 22222222-2222-4222-8222-222222222222\nname: report\nformat: markdown\n"
WORKFLOW = (
    "schema_version: 2\nid: 33333333-3333-4333-8333-333333333333\nname: sample\n"
    f"agents:\n  worker:\n    version: 1\n    id: 44444444-4444-4444-8444-444444444444\n    sha256: {sha(AGENT)}\n"
    f"deliverables:\n  report:\n    version: 1\n    id: 55555555-5555-4555-8555-555555555555\n    sha256: {sha(REPORT)}\n"
    "entry: write\nnodes:\n  write:\n    type: agent\n    agent: worker\n"
)


def export():
    binding = {"kind": "agent", "name": "worker", "definition_id": "x", "version": 1, "revision": 0}
    return {
        "kind": "cattlepen.workflow", "schema_version": 3, "exported_at": "now",
        "workflow": {"definition_id": "33333333-3333-4333-8333-333333333333", "revision": 0,
                     "bindings": [binding], "name": "sample", "version": 1},
        "declaration": WORKFLOW, "editor_state": {},
        "dependencies": {
            "agents": [{"definition_id": "a", "revision": 0, "bindings": [], "name": "worker", "version": 1,
                        "declaration": AGENT, "prompt": PROMPT}],
            "deliverables": [{"definition_id": "d", "revision": 0, "name": "report", "version": 1,
                              "declaration": REPORT}],
        },
    }


class ExportToBundleTest(unittest.TestCase):
    def run_script(self, text, *extra):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        source = self.tmp / "export.json"
        source.write_text(text, encoding="utf-8")
        return subprocess.run([sys.executable, str(SCRIPT), str(source), str(self.tmp / "out"), *extra],
                              capture_output=True, text=True)

    def test_reply_as_returned_is_verified_and_written(self):
        text = "export_workflow result:\n" + json.dumps({"result": export()}, indent=2) + "\n"
        result = self.run_script(text, "--workflow-sha", sha(WORKFLOW))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("1 of 1 prompts, 2 of 2 dependency documents", result.stdout)
        self.assertIn("matches --workflow-sha", result.stdout)
        out = self.tmp / "out"
        self.assertEqual((out / "workflow.yml").read_text(encoding="utf-8"), WORKFLOW)
        self.assertEqual((out / "agents/worker/1/prompt.md").read_text(encoding="utf-8"), PROMPT)
        self.assertEqual((out / "deliverables/report/1.yml").read_text(encoding="utf-8"), REPORT)

    def test_an_edited_copy_is_refused(self):
        edits = {
            "prompt": lambda data: data["dependencies"]["agents"][0].update(prompt=PROMPT + "x"),
            "deliverable": lambda data: data["dependencies"]["deliverables"][0].update(declaration=REPORT + "\n"),
        }
        for what, edit in edits.items():
            with self.subTest(what=what):
                data = export()
                edit(data)
                result = self.run_script(json.dumps(data))
                self.assertEqual(result.returncode, 2)
                self.assertIn("not the reply as returned", result.stderr)
                self.assertFalse((self.tmp / "out").exists())

    def test_wrong_workflow_sha_is_refused(self):
        result = self.run_script(json.dumps(export()), "--workflow-sha", sha(WORKFLOW + " "))
        self.assertEqual(result.returncode, 2)
        self.assertIn("--workflow-sha", result.stderr)


if __name__ == "__main__":
    unittest.main()
