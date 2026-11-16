# Changing a published workflow safely

A published version never changes: `apply_workflow_operations` and `save_authoring` on it answer
`409` "version N is published and immutable". Every fix to a published workflow, agent or deliverable is
therefore a new version, published beside the old one. This page is the procedure, measured end to end on a
test installation: a workflow whose v1 the runner refused was fixed by a deliverable v2 and a workflow v2, and
the task bound to it moved to v2 without being touched.

## What a new version starts from

`create_version{kind, entry_id}` opens the next version as a draft, seeded from the latest published one.
Measured facts:

- An entry has at most one draft. If one is already open, `create_version` returns that draft (same `id`,
  same `version`, its current `draft_revision`) instead of opening another. Check `list_versions` first so
  you know whether you are continuing someone's draft.
- The draft starts at `draft_revision: 0` with the published content, including every node `id` and rework
  `id`, and with each pin in its full published form: `{"version": 1, "id": "<version id>", "sha256": "<hash>"}`.
- The draft has no bindings, even if the old draft had some before it was published.
- Version numbers are never reused: after discarding draft 3, the next draft was 4.
- An unpinned task keeps running the latest **published** version while a draft is open (measured
  `resolved_version` unchanged with a draft open).

## Procedure

1. **Read what is live.** `list_versions{kind: "workflows", entry_id}`; note the latest published version N
   and whether a draft exists. If a task is involved, read it (`list_tasks` with its project, or
   `read_api_operation{operation: "GET /tasks/{id}", request: {path: {id}}}`) and note `workflow_version`
   (the version the task is pinned to; `null` means "latest published") and `resolved_version` (the version a
   start would use now).
2. **Change the dependencies first, if the fix is in an agent or deliverable.** For each one:
   `create_version{kind: "deliverables" | "agents", entry_id}`, `get_authoring` for its `declaration` and
   `draft_revision`, `save_authoring` with the change, read the save reply's `diagnostics` (must hold no
   error). Then either publish it now (`publish_version`, route A) or leave it a draft and bind it in step 4
   (route B, published later by a plan).
3. **Open the workflow's new version.** `create_version{kind: "workflows", entry_id}`, then
   `get_workflow_editor_snapshot{workflow_id, version: N+1}`. Keep its `revision` and use its declaration as
   the source of every `before` value.
4. **Edit, keeping identities.**
   - Change an existing node or rework by replacing it whole, with `before` equal to the stored value and an
     `after` that keeps the same `id`. Changing the `id` of an existing node is refused ("existing node
     identity cannot be replaced").
   - Bump a pin: `{"path": ["declaration","deliverables","check"], "before": {"version": 1, "id":
     "<as stored>", "sha256": "<as stored>"}, "after": {"version": 2}}`. A short `before` of
     `{"version": 1}` is refused with `workflow.edit_conflict` (measured), because the stored pin is the
     long form.
   - Route B: add a binding change for each draft dependency (see `save-validate-publish.md`, section 3).
   - New nodes and reworks need a fresh UUID `id`, as on any draft.
5. **Validate twice.** `validate_workflow{workflow_id, version: N+1}` must return no error. Then run the
   runner's checks on the draft (`runner-only-rules.md`): `shepherd validate` on its export when
   `shepherd version` works, otherwise every manual rule. Checking the draft is the point: once published,
   a version the runner refuses stays in the version list for good.
6. **Publish, when the request needs a published fix.** A request such as "it will not publish, fix it" or
   "its runs vanish, fix it" is only met by a published version, so publish without asking again; ask first
   only when the user asked for a diagnosis or when the fix would change a route, prompt or output that
   already worked; routing a value that had no route is part of the fix (the rule in `../SKILL.md`).
   All dependencies published: `publish_version{kind: "workflows", entry_id, version: N+1, base_revision}`.
   Any draft binding: the publication plan (`save-validate-publish.md`, 4.1).
7. **Check the tasks and report them.** Read every task of the workflow (`list_tasks{workflow_id}`) and put
   each in the report:
   - `workflow_version: null` (unpinned): `resolved_version` is now N+1, and the next start runs it. Measured.
   - `workflow_version: M` (pinned): it keeps M, so the fix does not reach it. Name it in the report with
     what moving it would take: one call,
     `mutate_api_operation{operation: "PATCH /tasks/{id}", request: {path: {id}, body: {workflow_version: <n>}}}`
     with the new number, or `null` to follow the latest published version again. A pin is a deliberate
     choice, so leave it unless the user says to move it. Measured both ways; an
     unpublished number is refused with `422` `task.unknown_version` "version 9 is not a published version of
     the workflow". While a task has a run pending, active or cancelling it is `frozen`, and launch fields
     are refused with `409` `task.launch_frozen`.
   - Runs already created keep the version they were created with: a pending run is dispatched with its own
     version, and a resumed or readmitted run reuses its source run's version (read from source). A fix
     therefore reaches a halted run only through a new run, not through resume.

## Proof

- `list_versions` shows version N+1 with `published_at` set, `launchable: true` and
  `launch_diagnostics: []`.
- `shepherd validate` on the published (or the just-published draft's) export prints `ok:` and exits 0.
- Every task you meant to move shows `resolved_version: N+1` and `launch_problem: null`.

## Undoing a draft you opened by mistake

`discard_workflow_version{entry_id, version, base_revision}` deletes an unpublished workflow draft (a stale
`base_revision` gets the "shared draft has changed" 409). There is no discard for agent or deliverable
drafts; leave them, or reuse them on the next change, since `create_version` returns the open draft.
