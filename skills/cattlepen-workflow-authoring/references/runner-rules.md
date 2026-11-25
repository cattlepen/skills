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
| A review partner's `verdict` deliverable is `format: json` and declares exactly the fields the runner writes (the server checks only that the node produces it) | `validate.pair-verdict-unusable`, whose message prints the fields to declare | copy the block in `dialect.md`, "Partners"; change no name, type, `required` or enum value |
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
  (`workspace.submodule-relative-url`);
- a node with a `guard` or a `watch` partner whose executor the run puts on a harness other than
  `claude-code` or `codex` (`dispatch.unresolvable`, naming the mode and the harness): the server
  checks a task's node override only when it is written, so an override written before the node had
  its partner can still move it;
- on a Windows runner, a node with a `guard` or a `watch` partner whose executor runs on `codex`
  (`dispatch.unresolvable`, naming the platform);
- on a runner whose operator turned on the runner's own guard, any agent node on `cursor-cli` or
  `opencode`, or on `codex` on a Windows runner (`dispatch.unresolvable`, saying that the runner guards
  every agent node), because that guard cannot sit there.

The last three depend on the runner and the run, not on the workflow alone, so `shepherd validate`
does not see them; `shepherd preflight` on the runner machine does. The server does not check them
before it places a run: it deletes the declined run, and a task queued again can be placed on the
same runner.

A command an inline script calls is not looked up in advance: a missing `jq` or `gh` fails at that
node, not at the start.

## Checking with `shepherd validate`

Where the runner CLI is installed (`shepherd version` prints a version), `shepherd validate <dir>`
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
- **After publishing, when the version came from those local documents.** The `--validate-copy` check
  above covers the published version on one condition: nothing was changed on the server after the
  import except what publishing itself rewrites (pins to `{version, id, sha256}`, minted node ids). Any
  editor action, save or re-import after it voids that; then use the export route. Say in the report
  that the source documents were validated before import.
- **For a version that exists only on the server** (changed in the editor, imported by someone else,
  or a draft), the export route. It works on a draft as well as on a published version (the
  `cattlepen-workflow-repair` skill ships the same `export_to_bundle.py`):
  1. `get_workflow_editor_snapshot{workflow_id, version}` for its `revision`, and
     `list_versions{kind: "workflows", entry_id}` for that version's `declaration_sha`.
  2. `export_workflow{workflow_id, version, base_revision: <revision>}`. No tool saves a tool result to
     a file, so write the reply to `export.json` with your harness's file-writing tool: the whole reply,
     bindings included, unedited. The script is the only thing that may transform it; an export edited
     or retyped by hand proves nothing about what the server holds.
  3. `python3 <skill dir>/scripts/export_to_bundle.py export.json <dir> --workflow-sha <declaration_sha>`
     checks the copy against the hashes the server wrote (each prompt always, each dependency document
     when the pins carry a hash, as a published version's do, and the workflow document against
     `--workflow-sha`), refuses a copy that differs, and writes the layout above (Python 3 standard
     library only; `<dir>` must not exist yet).
  4. Run `shepherd validate <dir>`.

  Measured on the examples, each reply saved exactly as returned: an imported `proposal_review` draft
  with its bindings passed the prompt and workflow checks and printed `ok: 6 plan node(s)`; the published
  `code_change` passed every hash check and printed `ok: 12 plan node(s)`. When
  a reply is too long to copy whole and exactly, do not shorten it: check by hand (below) and say so.

## Checking by hand, without the CLI

A published workflow pins each agent and deliverable as `{version, id, sha256}`. That `id` is the id of
the version, not of the library entry, and `get_declaration` answers 404 for it: read a pinned document
with `get_doc{sha256: <the pin's sha256>}`, or find its entry id with `search_library{kind, q: <name>}`
and call `get_declaration{kind, entry_id, version}`.

Walk the published YAML (`get_declaration`) and its pinned documents, and confirm each line:

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
- [ ] every review partner's `verdict` deliverable is `format: json` and declares exactly the fields
      in `dialect.md`, "Partners";
- [ ] no inline node uses `run: {profile: ...}` unless the target repository defines that profile;
- [ ] every repository the task selects has a `url` the runner can clone or a runner binding.

One of these checks always happens. Tell the user which one covers the published version;
"checked by hand" is rung 3 only when every line was confirmed, and a report that names none
stops at rung 2.
