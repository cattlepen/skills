#!/usr/bin/env python3
"""Build a Cattlepen portable workflow bundle (schema 3) from a source directory.

Usage:
    python3 build_bundle.py SOURCE_DIR [--prefix PREFIX] [--validate-copy DIR] > bundle.json

SOURCE_DIR holds:
    workflow.yml
    agents/<name>/<version>/agent.yml
    agents/<name>/<version>/prompt.md
    deliverables/<name>/<version>.yml

What it does:
- replaces every REPLACE_WITH_ENTRY_ID with a fresh UUID (one per document);
- writes `prompt: {sha256: <hash of prompt.md>}` into each agent document;
- checks that the workflow pins exactly the agents and deliverables in the directory, at the
  directory's version, with one version per name;
- with --prefix, renames the workflow and every agent and deliverable it defines, everywhere
  they are referenced, including inline scripts ($SHEPHERD_OUT/<name>.json, SHEPHERD__<NAME>)
  and a partner's `agent` and a review partner's `verdict`; one-line `label:` and `prompt:`
  values are prose and keep their words, and an agent's prompt.md is renamed only where a name
  stands alone in backticks;
- never renames a key of the dialect: with --prefix it refuses, writing nothing, a name that is
  also a dialect key, a deliverable field name or an enum value, and, when a node of the
  workflow carries `pair`, a name that is also a key of that block (`pair`, a mode such as
  `review`, or a field such as `verdict`); rename such an entry in the source instead;
- prints the bundle JSON for preview_workflow_import and import_workflow on stdout;
- with --validate-copy, also writes the filled documents in the runner's local bundle layout,
  ready for `shepherd validate DIR`.

Python 3.10 or newer, standard library only. The YAML is read line by line, so documents must use
block style at the top level and write pins as `<name>: {version: N}`.
"""

import argparse
import hashlib
import json
import pathlib
import re
import sys
import uuid

NAME = re.compile(r"[a-z][a-z0-9_]{0,63}")
PLACEHOLDER = "REPLACE_WITH_ENTRY_ID"

# Keys of the workflow, node, agent and deliverable documents. A name equal to one of these
# cannot be renamed by text substitution without changing the document's structure.
DIALECT_WORDS = {
    "schema_version", "id", "name", "settings", "agents", "deliverables", "inputs", "input_options",
    "outputs", "entry", "nodes", "reworks", "type", "label", "agent", "runtime", "harness", "model",
    "effort", "consumes", "produces", "escalation", "max_rounds", "timeout_s", "next", "inline",
    "run", "script", "profile", "human_gate", "prompt", "switch", "on", "routes", "dynamic_group",
    "for_each", "node", "deliverable", "field", "limit", "template", "end", "cancel", "resume_from",
    "feedback", "max_reworks", "on_exhausted", "max_rework_iterations", "max_agent_retries",
    "from", "optional", "format", "fields", "sections", "title", "level", "description", "required",
    "enum", "items", "string", "int", "float", "bool", "object", "array", "json", "markdown", "html",
    "expects", "yields", "version", "sha256", "true", "false", "null",
}

# Keys of an agent node's `pair` block: the block itself, its four modes, each mode's fields and a
# partner runtime's keys. Outside a workflow that declares `pair` these words are free entry names
# (several examples have a deliverable `review`); inside one they are keys as well.
PAIR_WORDS = {
    "pair", "advise", "review", "guard", "watch", "agent", "runtime", "harness", "model", "effort",
    "max_calls", "plan", "max_rounds", "verdict", "every", "max_notes",
}
PAIR_KEY = re.compile(r"(?:^|[{,])\s*[\"']?pair[\"']?\s*:")
BLOCK_SCALAR = re.compile(r":\s*[|>][-+0-9]*\s*(?:#.*)?$")


class BundleError(Exception):
    pass


def top_level_value(text, key):
    match = re.search(r"^" + re.escape(key) + r":[ \t]*(.*?)[ \t]*$", text, re.M)
    if not match:
        return None
    value = match.group(1)
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value


def identity(text, where):
    name = top_level_value(text, "name")
    ident = top_level_value(text, "id")
    if not name or not NAME.fullmatch(name):
        raise BundleError(f"{where}: needs a top-level `name:` matching ^[a-z][a-z0-9_]*$ (at most 64)")
    try:
        ident = str(uuid.UUID(ident or ""))
    except ValueError:
        raise BundleError(f"{where}: needs a top-level `id:` that is a UUID or {PLACEHOLDER}")
    return name, ident


def fill_ids(text):
    return text.replace(PLACEHOLDER, str(uuid.uuid4()))


def with_prompt_hash(declaration, prompt):
    line = "prompt: {sha256: " + hashlib.sha256(prompt.encode("utf-8")).hexdigest() + "}"
    lines = declaration.rstrip("\n").split("\n")
    out, skipping = [], False
    for current in lines:
        if skipping and (current.startswith((" ", "\t")) or not current.strip()):
            continue
        skipping = False
        if re.match(r"^prompt:", current):
            skipping = True
            continue
        out.append(current)
    out.append(line)
    return "\n".join(out) + "\n"


def pins(workflow, section):
    lines = workflow.split("\n")
    starts = [i for i, line in enumerate(lines) if re.match(r"^" + section + r":", line)]
    if not starts:
        return {}
    index = starts[0]
    rest = re.match(r"^" + section + r":[ \t]*(.*?)[ \t]*$", lines[index]).group(1)
    if rest == "{}":
        return {}
    if rest:
        raise BundleError(f"workflow.yml: write `{section}:` as a block of `<name>: {{version: N}}` lines")
    found, child_indent, current = {}, None, None
    for line in lines[index + 1:]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0:
            break
        if child_indent is None:
            child_indent = indent
        if indent == child_indent:
            match = re.match(r"^\s+([a-z][a-z0-9_]*):[ \t]*(.*?)[ \t]*$", line)
            if not match:
                raise BundleError(f"workflow.yml: cannot read the pin line {line.strip()!r} under {section}")
            current = match.group(1)
            flow = re.fullmatch(r"\{\s*version:\s*([0-9]+)\s*\}", match.group(2))
            if flow:
                found[current] = int(flow.group(1))
            elif match.group(2):
                raise BundleError(f"workflow.yml: write the pin {current} as `{current}: {{version: N}}`")
        else:
            nested = re.match(r"^\s+version:\s*([0-9]+)\s*$", line)
            if nested and current is not None:
                found[current] = int(nested.group(1))
    for pin_name, version in found.items():
        if not 1 <= version <= 32767:
            raise BundleError(f"workflow.yml: {section} pin {pin_name} must be a version from 1 to 32767")
    return found


def one_version(entry, suffix):
    candidates = sorted(p for p in entry.iterdir() if not p.name.startswith("."))
    if len(candidates) != 1:
        raise BundleError(f"{entry}: select exactly one version (found {len(candidates)})")
    stem = candidates[0].name[: -len(suffix)] if suffix else candidates[0].name
    if not stem.isdigit() or not 1 <= int(stem) <= 32767:
        raise BundleError(f"{candidates[0]}: the version must be a number from 1 to 32767")
    return candidates[0], int(stem)


def declares_pair(workflow):
    section, scalar_indent = None, None
    for line in workflow.split("\n"):
        indent = len(line) - len(line.lstrip(" "))
        if scalar_indent is not None:
            if not line.strip() or indent > scalar_indent:
                continue
            scalar_indent = None
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if indent == 0:
            top = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:", line)
            section = top.group(1) if top else None
        if BLOCK_SCALAR.search(line):
            scalar_indent = indent
        if section != "nodes" or re.match(r"^\s*(label|prompt):", line):
            continue
        if PAIR_KEY.search(line.strip()):
            return True
    return False


def renamer(names, prefix, field_words, paired):
    mapping = {name: prefix + name for name in names}
    for name in names:
        new = mapping[name]
        if not NAME.fullmatch(new):
            raise BundleError(f"--prefix makes the name {new!r}, which is not a valid name")
        if name in DIALECT_WORDS or name in field_words:
            raise BundleError(
                f"cannot rename {name!r} by prefix: it is also a dialect key, field name or enum value;"
                " rename it in the source instead")
        if paired and name in PAIR_WORDS:
            raise BundleError(
                f"cannot rename {name!r} by prefix: the workflow declares `pair`, where {name!r} is also"
                " a key; rename it in the source instead")
    order = sorted(mapping, key=len, reverse=True)

    def rename_line(line):
        if re.match(r"^\s*(label|prompt):", line):
            return line
        for old in order:
            line = re.sub(r"(?<![A-Za-z0-9_])" + re.escape(old) + r"(?![A-Za-z0-9_])", mapping[old], line)
            line = re.sub(r"(?<![A-Za-z0-9_])SHEPHERD__" + re.escape(old.upper()) + r"(?![A-Za-z0-9_])",
                          "SHEPHERD__" + mapping[old].upper(), line)
        return line

    def everywhere(text):
        return "\n".join(rename_line(line) for line in text.split("\n"))

    def backticked(text):
        for old in order:
            text = text.replace("`" + old + "`", "`" + mapping[old] + "`")
        return text

    return mapping, everywhere, backticked


def field_words_of(texts):
    words = set()
    for text in texts:
        for line in text.split("\n"):
            words.update(re.findall(r"([a-z][a-z0-9_]*)\s*:", line))
            enum = re.search(r"enum:\s*\[([^\]]*)\]", line)
            if enum:
                words.update(re.findall(r"[a-z][a-z0-9_]*", enum.group(1)))
            item = re.match(r"^\s*-\s*([a-z][a-z0-9_]*)\s*$", line)
            if item:
                words.add(item.group(1))
    return words


def build(source, prefix, validate_copy):
    workflow_path = source / "workflow.yml"
    if not workflow_path.is_file():
        raise BundleError(f"{workflow_path} is missing")
    workflow = workflow_path.read_text(encoding="utf-8")
    agents_src, deliverables_src = [], []
    if (source / "agents").is_dir():
        for entry in sorted(p for p in (source / "agents").iterdir() if p.is_dir()):
            folder, version = one_version(entry, "")
            agent_yml, prompt_md = folder / "agent.yml", folder / "prompt.md"
            if not agent_yml.is_file() or not prompt_md.is_file():
                raise BundleError(f"{folder}: needs agent.yml and prompt.md")
            agents_src.append((entry.name, version, agent_yml.read_text(encoding="utf-8"),
                               prompt_md.read_text(encoding="utf-8")))
    if (source / "deliverables").is_dir():
        for entry in sorted(p for p in (source / "deliverables").iterdir() if p.is_dir()):
            path, version = one_version(entry, ".yml")
            deliverables_src.append((entry.name, version, path.read_text(encoding="utf-8")))

    workflow_name = top_level_value(workflow, "name") or ""
    if prefix:
        names = [workflow_name] + [a[0] for a in agents_src] + [d[0] for d in deliverables_src]
        words = field_words_of([d[2] for d in deliverables_src])
        mapping, everywhere, backticked = renamer(names, prefix, words, declares_pair(workflow))
        workflow = everywhere(workflow)
        agents_src = [(mapping[n], v, everywhere(doc), backticked(p)) for n, v, doc, p in agents_src]
        deliverables_src = [(mapping[n], v, re.sub(r"(?m)^name:.*$", "name: " + mapping[n], doc))
                            for n, v, doc in deliverables_src]

    workflow = fill_ids(workflow)
    name, workflow_id = identity(workflow, "workflow.yml")
    files = {"workflow.yml": workflow}
    agents, deliverables, bindings = [], [], []
    for dir_name, version, doc, prompt in agents_src:
        doc = with_prompt_hash(fill_ids(doc), prompt)
        agent_name, ident = identity(doc, f"agents/{dir_name}")
        if agent_name != dir_name:
            raise BundleError(f"agents/{dir_name}: the document is named {agent_name}")
        agents.append({"definition_id": ident, "revision": 0, "bindings": [], "name": agent_name,
                       "version": version, "declaration": doc, "prompt": prompt})
        files[f"agents/{agent_name}/{version}/agent.yml"] = doc
        files[f"agents/{agent_name}/{version}/prompt.md"] = prompt
    for dir_name, version, doc in deliverables_src:
        doc = fill_ids(doc)
        deliverable_name, ident = identity(doc, f"deliverables/{dir_name}")
        if deliverable_name != dir_name:
            raise BundleError(f"deliverables/{dir_name}: the document is named {deliverable_name}")
        deliverables.append({"definition_id": ident, "revision": 0, "name": deliverable_name,
                             "version": version, "declaration": doc})
        files[f"deliverables/{deliverable_name}/{version}.yml"] = doc

    for kind, items in (("agent", agents), ("deliverable", deliverables)):
        pinned = pins(workflow, kind + "s")
        present = {item["name"]: item for item in items}
        if set(pinned) != set(present):
            missing = sorted(set(pinned) - set(present))
            extra = sorted(set(present) - set(pinned))
            raise BundleError(f"workflow.yml pins and {kind}s/ differ: pinned but absent {missing},"
                              f" present but not pinned {extra}")
        for pin_name in sorted(pinned):
            item = present[pin_name]
            if pinned[pin_name] != item["version"]:
                raise BundleError(f"{kind} {pin_name}: workflow.yml pins version {pinned[pin_name]},"
                                  f" the directory holds version {item['version']}")
            bindings.append({"kind": kind, "name": pin_name, "definition_id": item["definition_id"],
                             "version": item["version"], "revision": 0})
    identities = [workflow_id] + [item["definition_id"] for item in agents + deliverables]
    if len(set(identities)) != len(identities):
        raise BundleError("the workflow and every dependency need distinct ids")

    if validate_copy:
        for relative, content in files.items():
            target = validate_copy / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
    return {
        "kind": "cattlepen.workflow",
        "schema_version": 3,
        "exported_at": "local",
        "workflow": {"definition_id": workflow_id, "revision": 0, "bindings": bindings, "name": name,
                     "version": 1},
        "declaration": workflow,
        "editor_state": {"schema": 2, "nodes": {}, "groups": {}, "reroutes": {}},
        "dependencies": {"agents": agents, "deliverables": deliverables},
    }


def main(argv):
    parser = argparse.ArgumentParser(description="Build a Cattlepen schema-3 workflow bundle.")
    parser.add_argument("source", type=pathlib.Path, help="directory with workflow.yml, agents/, deliverables/")
    parser.add_argument("--prefix", default="", help="prefix for the workflow and every agent and deliverable name")
    parser.add_argument("--validate-copy", type=pathlib.Path, help="also write the filled documents here")
    args = parser.parse_args(argv)
    try:
        bundle = build(args.source, args.prefix, args.validate_copy)
    except (BundleError, OSError, UnicodeDecodeError) as error:
        print(f"build_bundle: {error}", file=sys.stderr)
        return 1
    json.dump(bundle, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
