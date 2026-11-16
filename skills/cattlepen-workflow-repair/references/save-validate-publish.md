# Symptoms before a workflow is published

Four symptoms, in the order a workflow lives: it will not save, it saves with diagnostics, it will not
validate, it will not publish. Each entry says what you see, how to confirm it is this case, the causes
from most to least likely, the fix, and the proof. The proof is always the server signal that showed the
fault, read again after the fix.

Terms used below:

- **Entry**: a named item in the library (a workflow, an agent or a deliverable). Each entry has numbered
  **versions**; a version is a **draft** until it is published, and a published version never changes.
- **Revision**: a counter on a draft that every save raises. Writes take it as `base_revision` so a write
  based on an old read is refused instead of overwriting someone else's change.
- **Action**: one `apply_workflow_operations` call. It carries `changes`, each a `path` plus the exact
  `before` value and the wanted `after` value, and it is applied whole or not at all.
- **Pin**: the line under `agents:` or `deliverables:` in a workflow that names the version of an agent
  or deliverable it uses, for example `check: {version: 2}`.
- **Binding**: a change at path `["bindings","agent:<name>"]` or `["bindings","deliverable:<name>"]` that
  points a pin at an unpublished draft (by its entry id, version and revision) so the workflow can be
  validated and published together with it.

Error replies look like `<METHOD> <route> -> <status>: {"error": "...", "message": "..."}`. Quote the
`message` and `error` fields when you report; the route shows which call failed. Names such as `check` or
`write` inside the quoted messages below are examples; the wording around them is the server's.

## 1. It will not save

### 1.1 `422` "new nodes require a stable UUID identity"

Confirm: the refused action adds something at `["declaration","nodes",<name>]` or
`["declaration","reworks",<name>]` with `before: null`, and that new value has no `id`.

Causes:
1. A new **rework** has no `id`. The message says "nodes", but the server applies the same rule to reworks.
   This is the most common case in practice: every node carries an `id` and only the rework lacks one.
2. A new node has no `id`.

Fix: give every new node and every new rework a fresh UUID in `id` (for example
`"id": "<a UUID you generate>"`, new for each item, never copied from another). Keep the `id` of every
existing node and rework exactly as the snapshot shows it.

Proof: the same action, resent with the ids, returns a reply with `revision` one higher than your
`base_revision`, and `get_workflow_editor_snapshot` shows the new items.

### 1.2 `409` `workflow.edit_conflict` "an affected item changed; preserve your input and reload the shared state"

The message suggests that someone else edited the workflow. Often nobody did, and reloading changes
nothing. Confirm by calling `get_workflow_editor_snapshot` and checking each cause below in order.

Causes:
1. **The action would leave a dangling reference.** The server refuses any action that adds one, and
   reports it with this conflict message. Measured forms:
   - a node whose `next` names a node that does not exist yet (refused again after a reload);
   - a node that `consumes` a deliverable from a node whose `produces` does not list it;
   - deleting a node (`"after": null`) while another node's `next` still names it.

   From the server source, the same check covers `entry`, switch routes, `consumes` sources, `$input`
   consumes of a deliverable missing from `inputs`, and a rework's `resume_from`, `on_exhausted`,
   `feedback.node` and feedback deliverable. Fix: make the action complete. Add the target node, the
   `produces` entry or the input in the same action; when you delete a node, repoint or delete everything
   that names it in the same action (measured: deleting `b` and changing `a.next` to `done` together
   succeeded).
2. **A `before` value that is not the stored value.** Copy every `before` from the snapshot you just read,
   field for field. Measured traps:
   - on a new workflow `entry` is the empty string, so its change is `"before": ""`, not `null`;
   - in a version opened from a published one, each pin is stored in full, for example
     `{"version": 1, "id": "<version id>", "sha256": "<hash>"}`; `"before": {"version": 1}` is refused;
   - adding an item that already exists (`"before": null` for a node that is in the snapshot);
   - a node `before` that differs from the stored node in any field (measured with a different `id`; the
     comparison is exact, so a missing field counts too).
3. **A binding you add or change is not current** (its `revision` is not the dependency's current draft
   revision). Read the dependency with `get_authoring` and use its `draft_revision`. (Read from source.)
4. **Someone else changed one of the items** since your snapshot. Reload, rebuild your change on the new
   values, and keep the user's intent.

A stale `base_revision` on its own is not refused when no other editing session (another person, or
another `client_id`) has changed an item you touch since that revision (measured; the rule is in the
server's source).
So a conflict that repeats after a reload is cause 1, 2 or 3, never "try again".

Two related refusals name their cause plainly: `422` "existing node identity cannot be replaced" (an
`after` that changes the `id` of an existing node or rework; keep the stored `id`) and `409`
`workflow.edit_reserved` "another participant is editing an affected node" (a person has that node open
in the web editor; wait and retry, or ask them). Both read from source.

Proof: the corrected action returns a new `revision`.

### 1.3 `422` "operation does not produce a workflow declaration"

Confirm: a change's `after` is a string of YAML text instead of a JSON object. Fix: send the node, rework or
field as a JSON object, with the same keys the YAML would have. Proof: the action returns a new `revision`.

### 1.4 `422` "duplicate or empty workflow change"

Confirm: the action lists the same `path` twice, or a change whose `after` equals its `before` (both
measured). Fix: one change per path, merging the two values into one `after`; drop changes that change
nothing. Proof: the action returns a new `revision`.

### 1.5 `409` "version N is published and immutable"

Confirm: `list_versions` shows `published_at` set on version N. Measured on `apply_workflow_operations`
and on `save_authoring`. Fix: open a new draft version and change that one; see
`change-published.md`. Proof: the new version's `get_workflow_editor_snapshot` (or `get_authoring`)
returns `"published": false` / `"published_at": null`, and the changed action or save succeeds there.

### 1.6 `409` "the shared draft has changed; preserve your input and reload before saving or publishing"

Confirm: your `base_revision` is lower than the draft's current revision. Read it with `get_authoring`
(`draft_revision`, for agents and deliverables) or `get_workflow_editor_snapshot` (`revision`, for
workflows). Measured on `save_authoring`, `publish_version`, `discard_workflow_version` and the
publication-plan create call.

Cause: the draft was saved after you read it, by you (a second save in the same session is the usual
case) or by someone else. Fix: read the draft again, check that its content is what you mean to save or
publish, then repeat the call with the current revision. Never send the current revision with content
you have not compared against it. Proof: the repeated call succeeds.

### 1.7 Creating an entry is refused

- `409` "deliverable name is already in use" (and the same wording for the other kinds): the name is
  taken. Find the entry with `search_library` and change it by a new version, or choose another name.
- "Deliverables require format: json, markdown or html. No entry was created.": pass `format`.

Proof: `create_library_entry` returns `{id, version: 1}`.

## 2. It saves, but the reply carries diagnostics

`save_authoring` stores the new revision even when the declaration has errors; the errors appear only in
the reply's `diagnostics`. `get_authoring` does not return diagnostics, so a later read looks clean.
Measured: an unknown key in a deliverable field saved as revision 1 with

```
{"code": "yaml.parse", "path": "line 6, column 43",
 "message": "fields.summary: unknown field `description`, expected one of `type`, `required`, `enum`, `items`, `fields` at line 6 column 43",
 "severity": "error"}
```

and the next `publish_version` was refused with `422` and the same diagnostics as its message.

Fix: correct the declaration (the message names the field and the keys that are allowed) and save again
with the new `base_revision`. Proof: the save reply has `"diagnostics": []`, and, for a dependency of a
workflow, `validate_workflow` on that workflow no longer shows the error.

The same trap exists in the workflow editor: the `diagnostics` in an `apply_workflow_operations` reply are
not a validation. Measured: the reply said `[]` while `validate_workflow` reported `pin.unresolved`, and
later `switch.unrouted-value`. Only `validate_workflow` counts.

## 3. It will not validate

`validate_workflow` returns `{"diagnostics": [...]}`. An entry with `"severity": "error"` blocks
publishing; a `"warning"` does not. The checks run in stages and a later stage runs only once the earlier
ones are clean, so fixing one error can reveal another. Repeat validate after every fix until no error is
left. Measured sequence on one draft: `agent.no-harness`, then (after adding the runtime)
`graph.unreachable-node` with `graph.unreachable-rework`, then `[]`; on another draft, `pin.unresolved`,
then (after binding) `switch.unrouted-value`, then `[]`.

The codes you will meet most, with the measured message and the fix. The full list is in `codes.md`.

| code | measured message | fix |
|---|---|---|
| `agent.no-harness` | "agent node names no runtime harness" (path `nodes.<node>.runtime.harness`) | add `runtime: {harness: claude-code}` or `codex` to that agent node |
| `pin.unresolved` | "no published version 1 of deliverable \"check\"" | publish that version first, or add a binding to its draft (below) |
| `switch.unrouted-value` | "value \"fail\" of check.result has no route — every value must be routed explicitly" | add a route for every enum value of the switched field |
| `graph.unreachable-node` | "node \"stop\" is not reachable from entry" | connect the node, or remove it; a cancel node used only by a rework's `on_exhausted` is reachable once that rework is |
| `graph.unreachable-rework` | "no reachable switch routes into rework \"redo\"" | route at least one switch value to the rework |
| `graph.unconsumed-deliverable` (warning) | "\"report\" produced by \"write\" is never consumed" | consume it, list it in `outputs`, or ignore: it does not block publishing |
| `yaml.parse` | names the field, the bad value and the allowed keys or values | correct the document the line and column belong to |

Two cases look alike and are not:

- **A `yaml.parse` from a dependency.** `validate_workflow` also checks the bound draft agents and
  deliverables, and reports their diagnostics without naming the document. Measured: a bound deliverable
  with `type: text` gave "fields.summary.type: unknown variant `text`, expected one of `string`, `int`,
  `float`, `bool`, `object`, `array` at line 6 column 19" on the workflow. If the line and column do not fit
  the workflow, open each bound draft with `get_authoring` and find the document they fit.
- **`409` `workflow.publication_changed` from `validate_workflow`.** The message is "Some selected
  dependencies changed or are unavailable. Check the listed dependencies before publishing again." and
  `dependencies[]` lists each binding with `"status": "stale"` and its `current_revision`. A binding
  records the revision of the draft it selected; saving that draft again makes the binding stale. Fix:
  change the binding's `revision` to `current_revision` (before: the binding as the snapshot's `bindings`
  shows it; after: the same object with the new revision). Proof: `validate_workflow` returns diagnostics
  again, without the 409.

To bind a draft dependency, add one change per dependency:

```json
{"path": ["bindings", "deliverable:check"], "before": null,
 "after": {"kind": "deliverable", "name": "check", "definition_id": "<entry id>", "version": 1, "revision": 1}}
```

Proof for this whole section: `validate_workflow` returns no entry with `"severity": "error"`.

## 4. It will not publish

`publish_version` takes `kind`, `entry_id`, `version` and `base_revision`.

### 4.1 `409` "this draft has authoring dependencies; use complete-set approval to publish them"

Cause: at least one binding points at an unpublished draft (also the case for every freshly imported
workflow). `publish_version` never publishes those; a **publication plan** does, publishing the workflow
and its draft dependencies in one step. Whenever the snapshot's `bindings` list is not empty, go to the plan
directly instead of trying `publish_version` first. Use the generic API tools:

1. `mutate_api_operation` with `operation: "POST /workflows/{id}/versions/{version}/publication-plans"` and
   `request: {path: {id: <workflow id>, version: <n>}, body: {base_revision: <snapshot revision>}}`. The
   reply's `data` holds `plan_id`, `declaration` (the exact YAML that will be published, with final pins)
   and `dependencies[]` with `action: "publish"` or `"reuse"` for each binding. Show the user what will be
   published: publishing cannot be undone.
2. Optionally `read_api_operation` with `operation: "GET /workflows/{id}/versions/{version}/publication-plans/{plan_id}"`.
3. `mutate_api_operation` with
   `operation: "POST /workflows/{id}/versions/{version}/publication-plans/{plan_id}/approve"` and
   `request: {path: {id, version, plan_id}, body: {idempotency_key: "<fresh UUID>"}}`. The reply has
   `published_at`. Repeating the approve with the same key returns the same result, so a lost reply is
   safe to retry with that key (measured).

Plan refusals:

- `422` with a diagnostics list as its message: an error in the workflow or a bound draft (section 3).
- `409` "the shared draft has changed; preserve your input and reload before saving or publishing": the
  `base_revision` is old (1.6).
- `409` `workflow.publication_changed` "Some selected dependencies changed or are unavailable. Check the
  listed dependencies before publishing again." with `"reason": "dependencies_not_ready"`: a stale binding
  (section 3).
- `409` `workflow.publication_changed` "A publication input changed after it was checked. Reload the
  affected editor, then publish again." with `"reason": "document_changed"`, `expected_revision` and
  `current_revision`, on approve: the draft changed after the plan was made. Create a new plan at the
  current revision and approve that one.

### 4.2 `422` with a diagnostics list as its message

The draft has an error diagnostic. Measured on a deliverable whose save had reported `yaml.parse`. Fix it
(section 2 or 3), then publish with the new revision.

### 4.3 `409` "the shared draft has changed; preserve your input and reload before saving or publishing"

As 1.6: read the current revision, compare, publish again.

### 4.4 Other publish refusals (read from source, not measured)

- `409` `workflow.publication_editing` "Publication is blocked by active edits. Finish editing in all open
  clients and try again; a disconnected client's edit lock expires after 20 seconds.": someone has the
  workflow open in the web editor. Retry after they finish.
- `409` "the draft has changed since it was checked; publish it again": a save landed during the publish.
  Read the revision again and repeat.
- `409` "<kind> name \"<name>\" is already in use": the declaration's `name:` differs from the entry name
  and the new name is taken. Publishing adopts the declared name, so put the entry's own name back.

### Proof that a workflow is published

`list_versions` with `kind: "workflows"` shows the version with `published_at` set, `launchable: true`
and `launch_diagnostics: []`. That is the server's verdict only. It is not proof that a runner will
accept the workflow: six published, `launchable: true` workflows with `[]` diagnostics were each refused
by the runner's own checks. Finish with `runner-only-rules.md` before you call a workflow fixed.
