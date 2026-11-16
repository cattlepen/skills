# Rules only the runner enforces

The server validates and publishes a workflow by its own rules. The runner (`shepherd`) compiles the
published workflow again when a run is dispatched, with stricter rules. A workflow that breaks one of
them publishes with `launchable: true` and empty server diagnostics, and then every run of it is
refused before the first node starts. The server then deletes that run, so `get_run` answers 404 and
no tool shows why. Six such workflows (the switch, feedback, side-entry, gate, template and script
rows) were published with `launchable: true` and then refused by the runner's compiler with the code
shown; the other rows are read from the runner's source.

## The rules

| rule | what the runner reports | how to comply |
|---|---|---|
| A switch's field is `required: true` | `validate.branch-field-not-required` | mark the enum field required in the deliverable |
| A `dynamic_group`'s `for_each` field is `required: true` | `validate.for-each-field-not-required` | mark the array field required |
| A rework's feedback node is inside the rework's span (the nodes reachable from `resume_from` that can reach a switch routing into the rework) | `rework.feedback-outside-span` | take feedback from a node between the head and the switch |
| A span is entered only through its `resume_from` | `rework.side-entry`, usually with `validate.structure` ("a cycle not explained by rework back-edges") | give a path from outside (an override gate after exhaustion, say) its own nodes instead of routing into the middle of the loop |
| A rework's `on_exhausted` lies outside its own span | `rework.on-exhausted-in-span` | send exhaustion to a node after the loop (a gate, a `cancel`) |
| A span contains no `dynamic_group` | `rework.span-crosses-map` | keep a fan-out before the loop's head or after its switch |
| A human gate produces exactly one deliverable, and it is json | `validate.produces-cardinality`, `validate.gate-artifact-unsupported` | give the gate one `format: json` deliverable |
| A `dynamic_group` template is an agent or inline node, never a human gate | `validate.member-kind-unsupported` | move the gate after the group |
| Every consume names a node that produces that deliverable | `validate.consumes-not-produced` | point the consume at the producing node; the editor refuses such a consume (409 `workflow.edit_conflict`), a bundle import accepts it |
| A rework's feedback deliverable is not also consumed by its head | `validate.feedback-duplicates-input` | drop that consume from the head; the head receives the feedback anyway |
| Every inline `script` parses as POSIX `sh` | `script.syntax` (checked before the run starts) | run `sh -n` on the script text |
| No YAML anchors, aliases or `<<` merge keys in any document | `parse.anchor-unsupported`, `parse.merge-key-unsupported` | write every value out |
| No key twice in one mapping, no `=` key, and no key YAML reads as a non-string (an unquoted `on`, `yes`, `1`) in an agent or deliverable document | `parse.duplicate-key`, `parse.value-key-unsupported`, `parse.non-string-key` | quote such keys, write each key once |

When a run starts, the runner also refuses it for:

- an inline `run: {profile: <name>}` that the repository's `.shepherd/profiles.yml` does not define at
  the run's start commit (`profile.unbound`), or whose command that commit cannot start
  (`profile.command-missing`). A workflow meant for repositories you do not control uses `script`;
- a task input file that does not match its deliverable (`input.invalid`);
- a selected read-only repository with neither a `url` in the project nor a binding in the runner's
  configuration (`workspace.unbound`);
- a repository it cannot clone: `workspace.unbound` at once when the clone cannot succeed (no such
  repository, or this machine has no access to it), `workspace.fetch` for any other failure, such as
  the network, retried a few times and then permanent;
- a repository using Git LFS on a runner without `git-lfs` (`workspace.lfs-unavailable`), or a
  submodule with a relative url while the runner's clone has no `origin` remote
  (`workspace.submodule-relative-url`).

A command an inline script calls is not looked up in advance: a missing `jq` or `gh` fails at that
node, not at the start.

## Checking with `shepherd validate`

Where the runner CLI is installed (`shepherd --version` prints a version), `shepherd validate <dir>`
compiles a workflow directory with the runner's own compiler, applies the server's publish rules (`publish.*` codes), and checks each inline
script: `sh -n` must parse it, it may read only the inputs its node consumes, and it may write only
`$SHEPHERD_OUT/<name>.json` (and the body file) for a deliverable its node produces
(`script.unconsumed-input`, `script.undeclared-output`). It needs `sh` on PATH. It prints
`ok: <n> plan node(s)` and exits 0 when clean, otherwise every diagnostic with its code. It does not
check repositories, profiles or runners; those need a real run.

The directory layout:

```text
<dir>/workflow.yml
<dir>/agents/<name>/<version>/agent.yml
<dir>/agents/<name>/<version>/prompt.md
<dir>/deliverables/<name>/<version>.yml
```

- **Before creating anything** (either path): write the documents in the source layout of
  `../examples/README.md` (ids `REPLACE_WITH_ENTRY_ID`, no `prompt:` line in `agent.yml`), run
  `build_bundle.py <source> --validate-copy <dir>`, which fills the ids and the prompt hash the
  runner's parser requires, and run `shepherd validate <dir>`. On path A the same JSON is the bundle;
  on path B ignore it.
- **After creating or publishing** (either path), validate what will actually run with the export
  route (the `cattlepen-workflow-repair` skill ships the same `export_to_bundle.py`). It works on a
  draft as well as on a published version:
  1. `get_workflow_editor_snapshot{workflow_id, version}` for its `revision`.
  2. `export_workflow{workflow_id, version, base_revision: <revision>}`; save the reply unchanged
     as a JSON file.
  3. `python3 <skill dir>/scripts/export_to_bundle.py export.json <dir>` writes the layout above
     (Python 3 standard library only; `<dir>` must not exist yet).
  4. Run `shepherd validate <dir>`.

  Measured on the `code_change` example: the export of its imported draft and of its published
  version both printed `ok: 12 plan node(s)`.

## Checking by hand, without the CLI

Walk the published YAML (`get_declaration`) and confirm each line:

- [ ] every switch's `on` field is `required: true`, `type: string`, with an `enum`, in the
      deliverable the switch consumes;
- [ ] every `dynamic_group` `for_each` field is a required array of objects;
- [ ] for every rework, its `feedback.node` lies on a path from `resume_from` to a switch that routes
      into the rework;
- [ ] no route, `next` or `on_exhausted` from a node outside a rework's span points at a node inside
      it other than `resume_from`;
- [ ] every rework's `on_exhausted` is outside its span, and no span contains a `dynamic_group`;
- [ ] every human gate produces exactly one deliverable, and it is `format: json`;
- [ ] no `dynamic_group` template is a `human_gate`;
- [ ] every consume `<deliverable>: <node>` names a node whose `produces` lists that deliverable;
- [ ] no rework's head consumes the rework's feedback deliverable;
- [ ] every inline script is valid `sh` (no bash-only syntax such as `[[`, arrays or `<<<`), reads
      only `SHEPHERD__<NAME>` or `$SHEPHERD_IN/<name>.*` for deliverables its node consumes, and writes
      `$SHEPHERD_OUT/<name>.json` (plus `<name>.md` or `<name>.html`) for every deliverable it produces;
- [ ] no document uses `&anchor`, `*alias` or `<<:`, repeats a key in one mapping, or leaves a key
      such as `on`, `yes` or `1` unquoted;
- [ ] no inline node uses `run: {profile: ...}` unless the target repository defines that profile;
- [ ] every repository the task selects has a `url` the runner can clone or a runner binding.

One of the two checks always happens. Tell the user which one you ran on the published version;
"checked by hand" is rung 3 only when every line was confirmed, and a report that names neither
stops at rung 2.
