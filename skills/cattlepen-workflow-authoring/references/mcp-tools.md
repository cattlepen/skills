# Creating, changing and publishing through the MCP

Every tool below is a Cattlepen MCP tool, named without any harness prefix. Arguments are JSON. Ids
in examples are placeholders: always use the ids the server returned to you. The `kind` argument of
library tools is plural (`workflows`, `agents`, `deliverables`); the `kind` inside a binding is
singular (`agent`, `deliverable`).

Contents: [scope and names](#scope-and-names) · [path A: a bundle](#path-a-a-bundle) ·
[path B: editor operations](#path-b-editor-operations) · [validate](#validate) ·
[publish](#publish) · [change a published workflow](#change-a-published-workflow) ·
[errors](#errors-and-what-to-do)

## Scope and names

- `whoami` tells you the account and whether the installation is self-hosted. Self-hosted Cattlepen
  has one organization with a shared library; a library entry can also belong to one project
  (`project_id` on `create_library_entry`, `preview_workflow_import`, `import_workflow`).
- A workflow name must be free in its scope: an import with a taken name is refused with 409
  "Workflow name is already in use in this scope". Check with `search_library` (`kind`, `q`).
- A dependency (agent or deliverable) whose name is taken is matched by the preview: an identical
  definition is `reuse`d (the new workflow shares the existing entry), a different one is `rename`d
  to `<name>_2`. A rename breaks the workflow: measured, the preview then reported an error
  (`link.unknown-deliverable` on a node's `produces`, which still named the old name), and inline
  scripts are never rewritten, so one that writes `$SHEPHERD_OUT/<name>.json` or reads
  `SHEPHERD__<NAME>` would use the wrong name.
- So name a new workflow's agents and deliverables for that workflow, with one prefix
  (`build_bundle.py --prefix release_notes_`), and preview until every dependency says `create`.
  The library is shared by the whole account: a generic name such as `task` or `review` collides
  with the next workflow that wants it, and an entry you publish under it is what that workflow
  then pins. When you do reuse an entry or copy another workflow, say so to the user.

## Path A: a bundle

Use it for a new workflow. One import creates the workflow and every agent and deliverable as
drafts, in one step that either happens completely or not at all.

1. Write the source directory (layout in `../examples/README.md`). Copy the closest example.
2. Build with the skill's script (Python 3, standard library only):
   `python3 <skill dir>/scripts/build_bundle.py <dir> --prefix <p> --validate-copy <copy> > bundle.json`.
   The script fills every `REPLACE_WITH_ENTRY_ID` with a fresh UUID, writes each agent's
   `prompt: {sha256: ...}` from its `prompt.md`, adds the bindings the bundle needs, and checks that
   the pins match the directories. Without a shell, the prompt hash comes from `put_doc{text}`,
   which returns `{sha256}` (a write).
3. Preview:

   ```json
   {"name": "acme_proposal_review", "bundle": <the JSON the script printed>}
   ```

   `preview_workflow_import` writes nothing and returns `token`, `dependencies[]` (each with `kind`,
   `source_name`, `target_name` and `action`: `create`, `reuse` or `rename`) and `diagnostics`. Fix
   every `error` diagnostic in the source and build again. Treat a `rename` as a name clash
   (see above). The `name` argument becomes the workflow's name.
4. Import right after the preview, with the same `name` and `bundle`, the preview's `token` and a
   new UUID: `import_workflow{name, bundle, preview_token, idempotency_key}`. It returns the
   workflow `id`, `version: 1` and the dependencies with their `version_id`. If anything in the
   library changed since the preview (another import, a save), the import is refused with 409
   "Import preview is stale; review a refreshed preview before importing": preview again and import
   with the new token. Repeating an import with the same key and the same body returns the first
   result instead of importing twice.
5. Everything the import created is a draft. Publish with the publication plan (below).

## Path B: editor operations

Use it to change an existing workflow, or to build a small new one step by step.

### Agents and deliverables

1. `create_library_entry{kind: "deliverables", name, format: "json"}` (`format` is required for a
   deliverable: `json`, `markdown` or `html`); `create_library_entry{kind: "agents", name}`. Each
   returns `{id, version: 1}`. A taken name is refused with 409.
2. `get_authoring{kind, entry_id, version: 1}` returns `draft_revision` (0 for a new entry).
3. `save_authoring{kind, entry_id, version: 1, base_revision: <draft_revision>, bindings: [],
   declaration: "<YAML>", prompt: "<text>"}`; `prompt` only for an agent. The YAML's `id` is the
   entry id. For an agent, the server stores the prompt and writes `prompt: {sha256: ...}` into the
   YAML itself; leave `prompt` out of the declaration you send.
4. Read the reply's `diagnostics`. A save succeeds even when they hold an error (an unknown key, for
   instance, is `yaml.parse`); such a draft cannot be published. Fix and save again with the new
   `draft_revision`.

Then either publish each of them now (`publish_version{kind, entry_id, version: 1, base_revision}`)
and pin them in the workflow as `{version: 1}`, or leave them as drafts and select each one with a
binding change in the workflow action (below), which makes the publication plan publish them
together with the workflow.

### The workflow

1. `create_library_entry{kind: "workflows", name}` returns `{id, version: 1}`.
2. `get_workflow_editor_snapshot{workflow_id, version: 1}` returns `revision` (0), the YAML
   `declaration` (for a new workflow `entry: ''`, `nodes: {}`, `schema_version: 2`) and `bindings`.
3. One `apply_workflow_operations` action with every change the graph needs. Each change is
   `{path, before, after}`; `before` is the exact current value (`null` when absent), `after` is
   JSON, never a YAML string. Example: an agent that writes a draft, an inline length check, a switch
   that sends a short draft back to the agent at most twice, then stops.

```json
{
  "workflow_id": "<workflow id>", "version": 1, "base_revision": 0,
  "client_id": "<one UUID for this editing session>", "operation_id": "<new UUID per action>",
  "changes": [
    {"path": ["declaration", "agents", "acme_writer"], "before": null, "after": {"version": 1}},
    {"path": ["declaration", "deliverables", "acme_draft"], "before": null, "after": {"version": 1}},
    {"path": ["declaration", "deliverables", "acme_check"], "before": null, "after": {"version": 1}},
    {"path": ["bindings", "agent:acme_writer"], "before": null,
     "after": {"kind": "agent", "name": "acme_writer", "definition_id": "<agent entry id>", "version": 1, "revision": 1}},
    {"path": ["bindings", "deliverable:acme_draft"], "before": null,
     "after": {"kind": "deliverable", "name": "acme_draft", "definition_id": "<entry id>", "version": 1, "revision": 1}},
    {"path": ["bindings", "deliverable:acme_check"], "before": null,
     "after": {"kind": "deliverable", "name": "acme_check", "definition_id": "<entry id>", "version": 1, "revision": 1}},
    {"path": ["declaration", "nodes", "write"], "before": null,
     "after": {"type": "agent", "id": "<new UUID>", "label": "Write the draft", "agent": "acme_writer",
               "runtime": {"harness": "claude-code"}, "produces": ["acme_draft"], "next": "check"}},
    {"path": ["declaration", "nodes", "check"], "before": null,
     "after": {"type": "inline", "id": "<new UUID>", "label": "Length check",
               "run": {"script": "set -u\nn=$(wc -c < \"$SHEPHERD_IN/acme_draft.md\" | tr -d ' ')\nif [ \"$n\" -ge 400 ]; then r=pass; else r=fail; fi\nprintf '{\"result\":\"%s\",\"summary\":\"the draft has %s bytes\"}' \"$r\" \"$n\" > \"$SHEPHERD_OUT/acme_check.json\"\n"},
               "consumes": {"acme_draft": "write"}, "produces": ["acme_check"], "next": "route"}},
    {"path": ["declaration", "nodes", "route"], "before": null,
     "after": {"type": "switch", "id": "<new UUID>", "consumes": {"acme_check": "check"}, "on": "result",
               "routes": {"pass": "done", "fail": "redo"}}},
    {"path": ["declaration", "nodes", "done"], "before": null, "after": {"type": "end", "id": "<new UUID>"}},
    {"path": ["declaration", "nodes", "stop"], "before": null,
     "after": {"type": "cancel", "id": "<new UUID>", "label": "Still too short"}},
    {"path": ["declaration", "reworks", "redo"], "before": null,
     "after": {"id": "<new UUID>", "resume_from": "write", "feedback": {"node": "check", "deliverable": "acme_check"},
               "max_reworks": 2, "on_exhausted": "stop"}},
    {"path": ["declaration", "entry"], "before": "", "after": "write"},
    {"path": ["declaration", "outputs"], "before": null, "after": ["acme_draft"]}
  ]
}
```

Here `acme_draft` is a markdown deliverable and `acme_check` a json one with `result` (a required
`string` enum `[pass, fail]`) and `summary`. With published dependencies, drop the three bindings.
A task input adds `{"path": ["declaration", "inputs"], "before": null, "after": ["<deliverable>"]}`
and a consume `"<deliverable>": "$input"`.

The rules this action follows, each learned from a refusal:

- **Every new node and every new rework has an `id`, a fresh UUID.** Without one the action is
  refused with 422 "new nodes require a stable UUID identity", also when only a rework lacks it.
- **On a new workflow `entry` is `""`, not absent**: its `before` is `""`.
- **A reference to a node or rework that does not exist yet goes in the same action as its
  target.** A `next`, route or consume naming something missing is refused with 409
  `workflow.edit_conflict` "an affected item changed; preserve your input and reload the shared
  state", the same message as a stale revision, and reloading does not help.
- **Node values are JSON objects.** A YAML string as a node value is refused with 422 "operation
  does not produce a workflow declaration".
- **A binding's `revision` is the dependency's `draft_revision`** after your last save, from
  `get_authoring`.

4. Keep the `revision` the reply returns; it is the next action's `base_revision`. The reply's
   `diagnostics` is not validation: call `validate_workflow`.
5. To change one thing later, read the snapshot, convert the node you change from the YAML into JSON,
   and send it whole as `before` with the new node as `after`, keeping its `id` (a changed `id` is
   refused with 422 "existing node identity cannot be replaced"). A change always replaces a whole
   entry: a node, a rework, a pin, a binding, or one of `entry`, `inputs`, `outputs`, `settings`,
   `input_options`, `name`. To delete an entry, send its current value as `before` and `null` as
   `after`, and in the same action change every node that referred to it. A wrong `before` gives
   the same 409 `workflow.edit_conflict`: read the snapshot again and rebuild the change from it.
   An old `base_revision` alone is accepted while nobody else has changed an item your action
   touches since that revision; when someone has, it is the same 409.
6. If a reply is lost, `get_workflow_operation{workflow_id, version, operation_id}` says whether the
   action was applied (404 means unknown). Retry only with the identical body and `operation_id`.
   `undo_workflow_operation` undoes one of your actions.
7. A workflow built through operations has no layout positions. If a person will open it in the web
   editor, call `format_workflow{workflow_id, version, base_revision, client_id, operation_id}` once
   on the draft before publishing; it lays the graph out on the server. Never compute a layout
   yourself.

## Validate

`validate_workflow{workflow_id, version}` returns `{diagnostics}`. Rung 1 is reached when none has
`severity: "error"`. With draft dependencies, every pin of a dependency that is neither published
nor selected by a binding reports `pin.unresolved`; add the binding or publish the dependency.
Validation covers the server's rules only; the runner's rules are in `runner-rules.md`.

## Publish

Choose by the snapshot's `bindings`, before calling anything:

- **`bindings` is empty and every pinned agent and deliverable is published** (path B with
  published dependencies, or a draft opened with `create_version`):
  `publish_version{kind: "workflows", entry_id, version, base_revision: <current revision>}`.
- **`bindings` is not empty** (an import always fills it; path B fills it when it selects draft
  dependencies): the publication plan. `publish_version` would be refused with 409 "this draft has
  authoring dependencies; use complete-set approval to publish them".

The publication plan, through the generic API tools:

```text
mutate_api_operation{operation: "POST /workflows/{id}/versions/{version}/publication-plans",
  request: {path: {id: <workflow id>, version: 1}, body: {base_revision: <current revision>}}}
  -> data.plan_id, data.declaration (exactly what will be published), data.dependencies[] with
     binding, version_id, declaration_sha, action "publish" or "reuse"
read_api_operation{operation: "GET /workflows/{id}/versions/{version}/publication-plans/{plan_id}",
  request: {path: {id, version: 1, plan_id}}}
mutate_api_operation{operation: "POST /workflows/{id}/versions/{version}/publication-plans/{plan_id}/approve",
  request: {path: {id, version: 1, plan_id}, body: {idempotency_key: <new UUID>}}}
  -> data.published_at, data.version_id, the dependencies as published
```

Read what the plan publishes (the workflow and each dependency) before approving it, and list it in
your report. A request to have this workflow working covers publishing it and the entries you
created for it; ask first when the plan would also publish something else. The
approval publishes them all together. A plan does not expire, but any new save to the workflow or to
one of its dependencies after the plan was created makes the approval fail with 409
`workflow.publication_changed`: create a new plan. The approval also waits for other people's open
editor reservations (409 `workflow.publication_editing`), and a dependency whose document `name`
differs from its library entry's name blocks the plan until they match.
A dependency published on its own:
`publish_version{kind: "agents" | "deliverables", entry_id, version, base_revision}`.

Afterwards `list_versions{kind: "workflows", entry_id}` lists each version with `id` (the version
UUID `start_run` and readiness accept), `published_at`, `launchable` and `launch_diagnostics`.
Publishing gives every node and rework an `id` if it had none, rewrites each pin to
`{version, id, sha256}`, and freezes the version. A task with no pinned version runs the latest
published version, so publishing a new version changes what such tasks run from their next start.
When you publish version 2 or later, list the workflow's tasks (`list_tasks{workflow_id}`; a
task's `workflow_version: null` means unpinned) and name in your report the ones that pick it up.
Ask before publishing when the new version changes behaviour the user did not ask to change. A
task can be held on the old version with `mutate_api_operation{operation: "PATCH /tasks/{id}",
request: {path: {id}, body: {workflow_version: <n>}}}`.

## Change a published workflow

1. `create_version{kind: "workflows", entry_id}` opens the next draft, seeded from the current
   version (or returns the open draft). Read it with `get_workflow_editor_snapshot` for that version.
2. Change it with path B. Keep every existing node `id`: task overrides are keyed by node id.
3. A changed prompt or deliverable is a new version of that entry: `create_version` on it,
   `get_authoring`, `save_authoring`, publish it, then point the workflow's pin at the new version.
   In a seeded draft a pin is `{version, id, sha256}`; that whole object is the `before`.
4. Validate, publish, check the runner rules again.

## Errors and what to do

Some refusals certify that nothing was written (the result carries
`_meta["cattlepen/mutationOutcome"] == "rejected"`): fix the input and send again. For every other
error of a write, read the state first. Measured:

| call | refusal | nothing written? |
|---|---|---|
| `create_library_entry` deliverable without `format` | argument error | yes |
| `create_library_entry` with a taken name | 409 "... name is already in use" | not certified |
| `save_authoring` with an old `base_revision` | 409 "the shared draft has changed..." | yes |
| `save_authoring` on a published version | 409 "version 1 is published and immutable" | not certified |
| `apply_workflow_operations` new node or rework without `id` | 422 "new nodes require a stable UUID identity" | yes |
| `apply_workflow_operations` wrong `before`, a reference to something missing (also a consume from a node that does not produce it), or an old `base_revision` after someone else changed an item it touches | 409 `workflow.edit_conflict` | yes |
| `apply_workflow_operations` YAML string as a value | 422 "operation does not produce a workflow declaration" | yes |
| `publish_version` of a draft with error diagnostics | 422 with the diagnostics | not certified |
| `publish_version` with an old `base_revision` | 409 "the shared draft has changed..." | not certified |
| `publish_version` with draft dependencies | 409 "... use complete-set approval ..." | not certified |
| `import_workflow` after the library changed | 409 "Import preview is stale ..." | not certified |
| `save_declaration` with `kind: "workflows"` | argument error: it takes agents and deliverables only | yes |

There is no tool that saves a whole workflow document or a whole layout: workflows change only
through `apply_workflow_operations` (or an import).
