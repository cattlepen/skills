#!/usr/bin/env python3
"""Write the reply of the cattlepen `export_workflow` tool as a runner bundle directory.

Usage: python3 export_to_bundle.py EXPORT_JSON OUT_DIR

EXPORT_JSON is a file holding the tool's reply exactly as returned (an object with
`declaration` and `dependencies`, optionally wrapped as {"result": ...}). OUT_DIR must not
exist yet. The result is the layout `shepherd validate OUT_DIR` reads:

  OUT_DIR/workflow.yml
  OUT_DIR/agents/<name>/<version>/agent.yml
  OUT_DIR/agents/<name>/<version>/prompt.md
  OUT_DIR/deliverables/<name>/<version>.yml
"""
import json
import re
import sys
from pathlib import Path

_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")


def _fail(message):
    print(f"export_to_bundle: {message}", file=sys.stderr)
    sys.exit(2)


def _safe(value, what):
    text = str(value)
    if not _NAME.match(text) or text in (".", ".."):
        _fail(f"refusing {what} {text!r}: not a plain name")
    return text


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def main(argv):
    if len(argv) != 3:
        _fail("usage: export_to_bundle.py EXPORT_JSON OUT_DIR")
    source, out = Path(argv[1]), Path(argv[2])
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        _fail(f"cannot read {source}: {error}")
    if isinstance(data, dict) and set(data) == {"result"}:
        data = data["result"]
    if not isinstance(data, dict) or not isinstance(data.get("declaration"), str):
        _fail("the file holds no `declaration` string: save the export_workflow reply unchanged")
    if out.exists():
        _fail(f"{out} already exists; give a new directory")
    dependencies = data.get("dependencies") or {}
    _write(out / "workflow.yml", data["declaration"])
    for agent in dependencies.get("agents") or []:
        folder = out / "agents" / _safe(agent["name"], "agent name") / _safe(agent["version"], "agent version")
        _write(folder / "agent.yml", agent["declaration"])
        if agent.get("prompt") is None:
            _fail(f"agent {agent['name']} has no prompt in the export")
        _write(folder / "prompt.md", agent["prompt"])
    for deliverable in dependencies.get("deliverables") or []:
        name = _safe(deliverable["name"], "deliverable name")
        version = _safe(deliverable["version"], "deliverable version")
        _write(out / "deliverables" / name / f"{version}.yml", deliverable["declaration"])
    files = sorted(str(path.relative_to(out)) for path in out.rglob("*") if path.is_file())
    print(f"wrote {len(files)} files to {out}")
    for name in files:
        print(f"  {name}")


if __name__ == "__main__":
    main(sys.argv)
