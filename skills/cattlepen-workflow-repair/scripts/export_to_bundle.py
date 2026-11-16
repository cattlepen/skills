#!/usr/bin/env python3
"""Write the reply of the cattlepen `export_workflow` tool as a runner bundle directory.

Usage: python3 export_to_bundle.py EXPORT_JSON OUT_DIR [--workflow-sha SHA256]

EXPORT_JSON is a file holding the tool's reply exactly as returned: the whole object, bindings and all,
optionally wrapped as {"result": ...}. Text around the one JSON object (a heading copied with it) is
ignored. Do not edit the reply: this script is the only thing that should transform it. OUT_DIR must
not exist yet. The result is the layout `shepherd validate OUT_DIR` reads:

  OUT_DIR/workflow.yml
  OUT_DIR/agents/<name>/<version>/agent.yml
  OUT_DIR/agents/<name>/<version>/prompt.md
  OUT_DIR/deliverables/<name>/<version>.yml

Before writing, it checks the copy against the hashes the server wrote, and refuses a file that differs:
- every agent's prompt text against the `prompt: {sha256}` in its document;
- every dependency document against its pin's `sha256` in the workflow (a published version has them);
- with --workflow-sha (the version's `declaration_sha` from `list_versions`), the workflow document.
It prints which of these it could check.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
_PROMPT_SHA = re.compile(r"^prompt:[ \t]*(?:\{[ \t]*sha256:[ \t]*([0-9a-f]{64})[ \t]*\}|\n[ \t]+sha256:[ \t]*([0-9a-f]{64}))", re.M)


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


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load(source):
    try:
        raw = source.read_text(encoding="utf-8")
    except OSError as error:
        _fail(f"cannot read {source}: {error}")
    try:
        return json.loads(raw)
    except ValueError:
        pass
    start = raw.find("{")
    if start < 0:
        _fail(f"{source} holds no JSON object")
    try:
        data, end = json.JSONDecoder().raw_decode(raw, start)
    except ValueError as error:
        _fail(f"{source} is not the reply as returned: {error}")
    if raw[end:].strip().startswith("{"):
        _fail(f"{source} holds more than one JSON object; save one export_workflow reply")
    return data


def _pin_hashes(declaration):
    pins, section, name = {}, None, None
    for line in declaration.split("\n"):
        top = re.match(r"^(agents|deliverables):[ \t]*$", line)
        if top:
            section, name = top.group(1), None
            continue
        if line and not line.startswith((" ", "\t")):
            section = None
            continue
        if section is None:
            continue
        child = re.match(r"^  ([A-Za-z0-9_]+):[ \t]*(.*)$", line)
        if child:
            name = child.group(1)
            flow = child.group(2)
            pins[(section, name)] = {}
            for key in ("version", "sha256"):
                found = re.search(key + r":[ \t]*([0-9a-f]{64}|[0-9]+)", flow)
                if found:
                    pins[(section, name)][key] = found.group(1)
            continue
        nested = re.match(r"^    (version|sha256):[ \t]*(\S+)[ \t]*$", line)
        if nested and name is not None:
            pins[(section, name)][nested.group(1)] = nested.group(2)
    return pins


def _verify(data, workflow_sha):
    dependencies = data.get("dependencies") or {}
    agents = dependencies.get("agents") or []
    deliverables = dependencies.get("deliverables") or []
    prompts = 0
    for agent in agents:
        found = _PROMPT_SHA.search(agent.get("declaration") or "")
        if agent.get("prompt") is None or not found:
            _fail(f"agent {agent.get('name')} has no prompt or no prompt hash in the export")
        if _sha(agent["prompt"]) != (found.group(1) or found.group(2)):
            _fail(f"the prompt of agent {agent['name']} does not match its sha256: this is not the reply as returned")
        prompts += 1
    pins = _pin_hashes(data["declaration"])
    checked, total = 0, 0
    for section, items in (("agents", agents), ("deliverables", deliverables)):
        for item in items:
            total += 1
            pin = pins.get((section, item.get("name"))) or {}
            if "sha256" not in pin or str(pin.get("version")) != str(item.get("version")):
                continue
            if _sha(item.get("declaration") or "") != pin["sha256"]:
                _fail(f"the document of {section[:-1]} {item['name']} does not match its pin's sha256: "
                      "this is not the reply as returned")
            checked += 1
    if workflow_sha:
        if _sha(data["declaration"]) != workflow_sha.strip().lower():
            _fail("the workflow document does not match --workflow-sha: this is not the reply as returned")
        workflow_note = "matches --workflow-sha"
    else:
        workflow_note = "not checked (pass --workflow-sha <declaration_sha from list_versions>)"
    print(f"verified against the server's hashes: {prompts} of {len(agents)} prompts, {checked} of {total} "
          f"dependency documents (a draft's pins carry no hash), workflow document {workflow_note}")


def main(argv):
    args = argv[1:]
    workflow_sha = None
    if "--workflow-sha" in args:
        at = args.index("--workflow-sha")
        if at + 1 >= len(args):
            _fail("--workflow-sha needs a value")
        workflow_sha = args[at + 1]
        del args[at:at + 2]
    if len(args) != 2:
        _fail("usage: export_to_bundle.py EXPORT_JSON OUT_DIR [--workflow-sha SHA256]")
    source, out = Path(args[0]), Path(args[1])
    data = _load(source)
    if isinstance(data, dict) and set(data) == {"result"}:
        data = data["result"]
    if not isinstance(data, dict) or not isinstance(data.get("declaration"), str):
        _fail("the file holds no `declaration` string: save the export_workflow reply unchanged")
    if out.exists():
        _fail(f"{out} already exists; give a new directory")
    _verify(data, workflow_sha)
    dependencies = data.get("dependencies") or {}
    _write(out / "workflow.yml", data["declaration"])
    for agent in dependencies.get("agents") or []:
        folder = out / "agents" / _safe(agent["name"], "agent name") / _safe(agent["version"], "agent version")
        _write(folder / "agent.yml", agent["declaration"])
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
