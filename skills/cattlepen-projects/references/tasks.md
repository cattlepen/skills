# Tasks: repositories, workflow, pins, the task tree and input files

A task is the unit of work: a title and description, a project, a workflow to run, the
repository its runs change, the repositories they may read, and any input files the workflow
requires. Each run of the task is one attempt to carry it out.

## Creating and reading

`create_task{title, project_id, workflow_id, description, repo, readonly_repos, priority,
parent_id, iteration_id, container, issue}`; only `title` is required by the tool, and
self-hosted Cattlepen requires a project. The reply is the task, with these launch fields:

| Field | Meaning |
| --- | --- |
| `repo`, `readonly_repos` | The stored selection; see the defaults below. |
| `workflow_id`, `workflow_version` | The workflow, and the pinned version (`null`: latest published). |
| `resolved_version` | The version a launch now would use; `null` when nothing is published. |
| `runner_key_id`, `runner_name` | The pinned runner key (`null`: any matching runner). |
| `launch_problem`, `launch_note` | The first reason the task cannot launch as configured; a remark that does not stop it. |
| `readiness` | `{state, open_children, children}`: the task tree, not inputs. |
| `queued_at`, `queue_position`, `queue_wait` | Queue state; see `queue-and-iterations.md`. |
| `frozen` | A run is pending, active or cancelling; launch fields are read-only until it ends. |
| `status` | `pending`, `in_progress`, `done` or `cancelled`. A new task is `pending`. |

`list_tasks{project_id}` returns the same fields for every task (filters: `project_id`,
`workflow_id`, `unassigned`). One task by id: `read_api_operation{operation:"GET /tasks/{id}",
request:{path:{id}}}`.

### What the title and description are for

The runner puts the task into every agent node's prompt as "The task you are working on:",
the title, then the description (cut after its first 16 KiB, with a note saying so). Write the
description as the work order: the result wanted, acceptance criteria, files or commit ranges
that matter. Any step can also read the title and description from
`$SHEPHERD_IN/_shepherd/run.json`, under `task`.

## Which repository a run uses

Measured on a project listing `app` and `docs`, one listing only `site`, and one listing none.

| Project lists | `repo` sent | Stored | The run works in |
| --- | --- | --- | --- |
| exactly one entry | omitted | `null` | that entry |
| several entries | omitted | `null` | nothing: the task is accepted with `launch_problem: null`, `start_run` answers 409 "task has no repo binding", and a queued task shows `queue_wait: "repository"` |
| no entry | omitted | `null` | nothing, as above |
| any | a listed name, exact spelling | that name | that entry |
| any | `App` when the entry is `app`, or an unlisted name | refused | 422 `task.unknown_repo` with `names: ["App"]` |

| `readonly_repos` sent | Stored | The run reads |
| --- | --- | --- |
| omitted | `null` | every other entry the project lists when the run is dispatched, in name order |
| `[]` | `[]` | nothing |
| `["docs"]` | `["docs"]` | `docs` |
| a list holding the `repo` name | refused | 422 "readonly_repos[0] is the task's repo" |
| an unlisted name | refused | 422 `task.unknown_repo` with `names` |

So `null` is a moving target: a repository added to the project later is read by the task's next
run, and must be reachable by the runner (see `repositories.md`). Choose `[]` or an explicit list
unless the user wants the run to read everything.

Change the selection with `update_task{task_id, repo}` or `update_task{task_id, readonly_repos}`;
`update_task{task_id, read_all_other_repos: true}` stores `null` again. Both are refused with 409
`task.launch_frozen` while `frozen` is true.

## Workflow and version

`workflow_id` binds the task to a workflow; the task then launches its latest published version
(`resolved_version`). A task without a workflow reports `launch_problem: {code:
"process_not_selected"}`. Changing `workflow_id` with `update_task` clears the version pin, the
per-node overrides and the queue entry.

To pin a version, which neither `create_task` nor `update_task` offers, use the API operation:

```json
{"operation": "PATCH /tasks/{id}", "request": {"path": {"id": "<task id>"}, "body": {"workflow_version": 1}}}
```

through `mutate_api_operation`. The reply's `data` is the task with `workflow_version: 1`. A
version that is not published is refused: 422 `task.unknown_version` "version 2 is not a
published version of the workflow". `{"workflow_version": null}` returns to the latest.
Publishing a workflow belongs to `cattlepen-workflow-authoring`; `list_versions{kind:
"workflows", entry_id}` shows which versions are published and `launchable`.

## Runner pin

The same `PATCH /tasks/{id}` takes `runner_key_id` (a key id from `GET /runners`); the reply
names the key in `runner_name`. `null` returns to any matching runner. A revoked key, or one you
cannot see, is refused: 422 `task.unknown_runner` "runner key <id> is not visible or is revoked".
Pinning a key that is offline is accepted and leaves `launch_problem` `null`; the run would wait
for that runner. Pin only when the user wants the work on one machine, for example the only one
with a binding for a local repository.

## Parent and child tasks

- `parent_id` places a task under another task of the same project; another project's task is
  refused with 422 `task.parent_other_project`.
- A parent starts only after every child is `done`. Until then its `readiness` reads
  `{state: "waiting", open_children: 1, children: 1}`, and queued it shows `queue_wait:
  "children"`. A cancelled child blocks it (`state: "blocked"`, `queue_wait: "cancelled_child"`).
- `container: true` makes an epic: it never runs and becomes `done` by itself when its last child
  is done. A container with no workflow still shows `launch_problem: process_not_selected`; that
  is harmless, since it never launches. Queue it with `subtree: true`.
- `readiness.state` is one of `ready`, `waiting`, `blocked`, `running`, `done`. It says nothing
  about input files: a task whose required input is missing still reads `state: "ready"`.
- `update_task{task_id, parent_id}` moves a task (a move under itself or a descendant is refused
  with 409 `task.cycle`); `clear_parent: true` moves it to the top level.
- `priority` is an integer; a higher one is picked first among tasks at the same depth.

## Input files

A workflow that declares `inputs` runs only when every required input has a bound file whose
content matches the input's deliverable.

1. `get_task_readiness{task_id}` returns `{ready, workflow_version_id, workflow_sha256,
   requirements, artifacts, diagnostics}`. Each requirement names the input (`name`), whether it
   is `required`, and its deliverable (`deliverable_id`, `deliverable_version`,
   `deliverable_sha256`). Diagnostics are
   `{input, code, message}` with codes `input.missing` ("required input has no attachment
   binding"), `input.invalid` and `input.unknown` (a binding the version does not declare).
2. Read the deliverable's declaration with `get_doc{sha256: <deliverable_sha256>}` and write
   content that matches its `fields`. Do not pass `deliverable_id` to `get_declaration` or
   `get_library_entry`: it is the id of the deliverable's version, not of its library entry, and
   both answer 404.
3. `attach_task_file{task_id, filename, content, input_name, media_type}`; `media_type` defaults
   to `application/json`. The reply is `{artifact, url, readiness}`; `artifact` came back `null`,
   so take the file's id from `readiness.artifacts[].id` or from `list_task_artifacts{task_id}`.
4. Content that does not match (an extra key, for example) is still uploaded and
   bound; readiness then shows `input.invalid` "content does not match the pinned deliverable
   schema", without naming the field. Attach the corrected content with the same `artifact_id`
   to replace the file in place.
5. `bind_task_artifact{task_id, artifact_id, input_name}` rebinds an attached file (`null`
   unbinds); `detach_task_artifact` removes it and needs the user's yes.

`get_task_readiness` takes an optional `workflow_version_id`; without it, it checks the version
the task launches: its pinned version, else the latest published one. Queueing and
`start_run` refuse a task whose inputs are not ready: 422 "task inputs are not ready", with the
same diagnostics.
