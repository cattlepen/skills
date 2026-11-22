# Rules only the runner checks

The **runner** is the program (`shepherd`) that executes runs on a machine connected to Cattlepen. When it
is offered a run, it compiles the published workflow again with its own compiler and checks it against the
machine. Some rules exist only there. A workflow that breaks one of them saves, validates, publishes and
reads `launchable: true`, and then every run of it is declined at dispatch and deleted, so `get_run`
answers 404 and no tool can tell you why (see `launch-and-dispatch.md`, section 7).

So before you call a workflow fixed, check these rules. There are two ways.

## Way 1: run the runner's validator (preferred)

This needs the `shepherd` command on the machine you work on (it is installed where a runner runs; check
with `shepherd version`, which prints a version when it is). It reads a **bundle directory**:

```
<dir>/workflow.yml
<dir>/agents/<name>/<version>/agent.yml
<dir>/agents/<name>/<version>/prompt.md
<dir>/deliverables/<name>/<version>.yml
```

1. `get_workflow_editor_snapshot{workflow_id, version}` for its `revision`, and
   `list_versions{kind: "workflows", entry_id}` for that version's `declaration_sha`.
2. `export_workflow{workflow_id, version, base_revision: <revision>}`. It works on a draft as well as on a
   published version, so you can check before publishing. No tool saves a tool result to a file: write the
   reply to `export.json` with your harness's file-writing tool, whole (bindings included) and unedited.
   The script is the only thing that may transform it; an export edited or retyped by hand proves nothing.
3. `python3 <skill dir>/scripts/export_to_bundle.py export.json bundle-dir --workflow-sha <declaration_sha>`
   checks the copy against the hashes the server wrote (every prompt, every dependency document whose pin
   carries a hash, and the workflow document), refuses a copy that differs, and writes the layout above
   (Python 3 standard library only; the output directory must not exist yet).
4. `shepherd validate bundle-dir`.

Measured: the replies of a draft with bindings and of a published version, saved exactly as returned,
passed the hash checks and validated clean. When a reply is too long to copy whole and exactly, do not
shorten it: use way 2 and say so in the report.

This works for any version on the server. A version built in the same session from local files that were
validated before import (the `cattlepen-workflow-authoring` skill's `build_bundle.py --validate-copy`) is
covered by that check only if nothing changed on the server after the import except what publishing
rewrites (pins and minted node ids).

A clean bundle prints a summary starting `ok:` and exits 0, for example:

```
ok: 3 plan node(s)
required connections: (none)
$input deliverables: (none)
may park on: (none)
required profiles (.shepherd/profiles.yml): (none)
```

A bundle with a problem prints `compile failed at <stage>: <n> diagnostic(s)`, one line per diagnostic as
`<code> [workflow <path>] <message>`, and exits non-zero (3 for diagnostics). The summary also names each
inline profile the target repository's `.shepherd/profiles.yml` must define and each connection the runner
needs; check those against the repository and the runner.

`shepherd validate` checks the workflow alone. A runner operator can also run
`shepherd preflight <bundle-dir> --project <name> --repo <name> ...` on the runner machine: it applies the
checks a dispatch applies against that runner's configuration and checkouts (repository bindings, profiles,
Git LFS, submodules, harnesses) and prints the problems a decline would list. Its options are in
`shepherd preflight --help`. This page did not exercise it.

## Way 2: check by hand

Without `shepherd`, read the workflow (`get_workflow_editor_snapshot`, or `get_declaration` for a published
version) and its deliverables, and test each rule below. A published workflow pins each agent and
deliverable as `{version, id, sha256}`. That `id` is the id of the version, not of the library entry, and
`get_declaration` answers 404 for it: read a pinned document
with `get_doc{sha256: <the pin's sha256>}`, or find its entry id with `search_library{kind, q: <name>}`
and call `get_declaration{kind, entry_id, version}`.

Each row was measured: a workflow breaking the rule published on a test installation with `launchable: true`
and no error diagnostic (`[]` or warnings only), and `shepherd validate` on its export printed the line shown.

| rule | how to test | what the runner prints |
|---|---|---|
| A switch's field must be `required: true` in its deliverable | for every `type: switch`, open the deliverable it consumes and find the field named by `on:`; it must have `required: true` | `validate.branch-field-not-required [workflow nodes.sw.on] switch field 'result' of 'check' is not required; an omitted field publishes as null and no route covers null (mark it required: true)` |
| A rework's feedback node must be inside the loop | `feedback.node` must be `resume_from` or a node reached from it before the switch that routes back; never a node upstream of `resume_from` | `rework.feedback-outside-span [workflow reworks.loop] feedback node 'pre' is outside the loop span — it cannot carry feedback` |
| A loop is entered only through `resume_from` | the loop is the nodes from `resume_from` up to the switch that routes into the rework; no node outside it may route or `next` into a node inside it other than `resume_from` | `validate.structure [workflow nodes] flow has a cycle not explained by rework back-edges` and `rework.side-entry [workflow nodes.sw2.routes.approve] 'sw2' enters span node 'chk' of rework 'loop' from outside the loop body; a span is entered only through its resume_from 'a'` |
| A human gate produces a JSON deliverable | every `type: human_gate` has `produces` naming deliverables with `format: json` | `validate.gate-artifact-unsupported [workflow nodes.g.produces] human_gate deliverable 'answer' is 'format: markdown'; ...` |
| A dynamic group's template is not a human gate | `template.type` of every `type: dynamic_group` is `agent` or `inline` | `validate.member-kind-unsupported [workflow nodes.grp.template] template type 'human_gate' is not one of [...]` |
| An inline script parses as `sh` | save each `run.script` to a file and run `sh -n file`; it must print nothing and exit 0 | `script.syntax [workflow nodes.s.run.script] the script does not parse: sh: -c: line 3: syntax error: unexpected end of file` |

These three were measured on drafts: `validate_workflow` returned `[]` (the same checks a publish runs), and
`shepherd validate` on the draft's export printed the line shown.

| rule | how to test | what the runner prints |
|---|---|---|
| A human gate produces exactly one deliverable | every `type: human_gate` has exactly one name in `produces` | `validate.produces-cardinality [workflow nodes.gate.produces] a human_gate produces exactly one deliverable, not 0 ...` |
| A dynamic group's `for_each` field must be `required: true` | for every `type: dynamic_group`, the array field named by `for_each.field` has `required: true` in its deliverable | `validate.for-each-field-not-required [workflow nodes.grp.for_each.field] for_each field 'items' of 'item_list' is not required; an omitted array publishes as null and a fan-out cannot size null (mark it required: true)` |
| No YAML anchors or aliases in any document | search every agent and deliverable declaration for `&name` and `*name` used as YAML anchors, and for `<<:` merge keys | `parse.anchor-unsupported [deliverable:pair@1 line 6, column 10] anchor '&s': anchors and aliases are not part of this dialect` |

The runner's compiler also refuses the following, which the server's own checks let through (read from
both sources, not measured). Test them by hand the same way:

- a consume `<deliverable>: <node>` whose node does not list that deliverable in `produces`
  (`validate.consumes-not-produced`). The editor refuses an action that adds one (409
  `workflow.edit_conflict`), but a bundle import accepts it;
- a rework whose feedback deliverable is also an input the `resume_from` node already consumes
  (`validate.feedback-duplicates-input`);
- a rework whose `on_exhausted` lies inside its own loop (`rework.on-exhausted-in-span`), or a loop that
  encloses a dynamic group (`rework.span-crosses-map`);
- in an agent or deliverable document, a merge key `<<:` (`parse.merge-key-unsupported`), a `=` key
  (`parse.value-key-unsupported`), the same key twice in one mapping (`parse.duplicate-key`), or a key
  that YAML reads as a non-string, such as an unquoted `on`, `yes` or `1` (`parse.non-string-key`);
- a review partner's `verdict` deliverable that is not `format: json`, or whose fields are not exactly
  the ones the runner writes into it (`validate.pair-verdict-unusable` at
  `nodes.<node>.pair.review.verdict`, whose message prints the fields to declare). The server checks
  only that the node produces it. Compare every field's name, `type`, `required` and enum values, nested
  fields included, with the block in the `cattlepen-workflow-authoring` skill's `references/dialect.md`,
  "Partners" (`codes.md`, section 5);
- a `watch` partner on a node whose executor runs on `codex` (`validate.pair-mode-unsupported` at
  `nodes.<node>.pair.watch`, or `nodes.<group>.template.pair.watch`). The server accepts a `watch` beside
  an executor on `claude-code` or `codex`; the runner runs one only beside `claude-code`, and its message
  says so and tells you to remove the mode from the node or run the node's executor on `claude-code`.
  Test: every node or template with `pair.watch` has `runtime.harness: claude-code`. Fix: a new version
  with that node's executor on `claude-code`, or without the `watch` (`codes.md`, section 5).

### Checks that depend on the runner machine

These are applied when a run is offered, against the runner and the repositories, so `shepherd validate`
cannot see them (`shepherd preflight` can, on that machine). Test them by reading the project, the task
and the repository:

| decline code | the run needs |
|---|---|
| `profile.unbound` | every `run: {profile: <name>}` defined in `.shepherd/profiles.yml` of the working repository at its base branch |
| `profile.command-missing` | the commands those profiles name installed on the runner |
| `workspace.unbound`, `workspace.fetch` | every selected repository reachable: a URL the runner can clone and a base branch that exists, or a binding in the runner's configuration |
| `workspace.lfs-unavailable` | `git-lfs` installed and configured on the runner, if a repository uses Git LFS |
| `workspace.submodule-relative-url` | an `origin` remote, if `.gitmodules` uses relative URLs |
| `input.invalid` | every input file valid against its deliverable (the server checks this too, see `launch-and-dispatch.md`, 5.2) |
| `dispatch.unresolvable` | a runner configured for each harness the workflow names; on a Windows runner, no node with a `guard` partner whose executor runs on `codex`; on a runner whose operator turned on the runner's own guard, which judges every agent node, no agent node on `cursor-cli` or `opencode`, nor on `codex` when that runner is on Windows; and no task node override (`exec_overrides`) that puts a guarded node on a harness other than `claude-code` or `codex`, or a watched node on one other than `claude-code` (the server checks an override only when it is written, and accepts a watched node on `codex`). Causes, messages and fixes: `codes.md`, section 5 |

## Fix and proof

Fix the rule in a new version (`change-published.md`) or, better, in the draft before it is ever
published. The proof is `shepherd validate` printing `ok:` on the export of the fixed version, or, without
`shepherd`, the manual test passing for every row. Measured: the first row's workflow was fixed by making
the field required in a new deliverable version and bumping the pin; the export of the new workflow
version then printed `ok: 3 plan node(s)`.

A run that reaches `active` with a `run_started` event in `get_run_events` is the final proof that the
runner accepted the workflow. Start one only when the user asks for it.
