# The queue and iterations

Queueing marks a task for execution. It does not start a run by itself: the server starts queued
tasks automatically only while the account's exhaust queue is on. Iterations are a project's
planning periods; once a project uses them, only the active one feeds the queue.

## Queueing and dequeueing

There is no dedicated queue tool; `queue_task` and `dequeue_task` are API operation ids. Call
them through the generic tools:

```json
{"operation": "POST /tasks/{id}/queue", "request": {"path": {"id": "<task id>"}, "body": {"subtree": false}}}
{"operation": "POST /tasks/{id}/dequeue", "request": {"path": {"id": "<task id>"}, "query": {"subtree": false}}}
```

Both go through `mutate_api_operation` and answer `{"status": 204}`. `subtree: true` takes the
task and every pending task below it, keeping each one's priority and settings; queue an epic
this way. The queue body also takes `priority`, which changes this task's priority only.

Refusals:

| Situation | Reply |
| --- | --- |
| The task has no workflow | 409 `task.launch_problem` "Process not selected", `problem: {code: "process_not_selected"}` |
| Another `launch_problem` | 409 `task.launch_problem` with that problem |
| Required inputs missing or invalid | 422 "task inputs are not ready", with the readiness diagnostics |
| Some task of a subtree cannot be queued | 409 `task.queue_subtree_invalid` "some tasks cannot be queued; no tasks were changed", listing each task and its problem |
| The task is not `pending` | 409 |
| Self-hosted, and you are not an explicit member of the project | 403 "queueing requires explicit project membership" |

A task without a repository choice is accepted into the queue; it then waits (below).

## Reading the queue

`list_tasks{project_id}` shows `queued_at`, `queue_position` and `queue_wait` on each task. The
queue alone, in its own order:

```json
{"operation": "GET /tasks", "request": {"query": {"project_id": "<project id>", "queued": true}}}
```

through `read_api_operation`. A task that is queued and could start has a `queue_position` and
`queue_wait: null`. One that cannot start yet has `queue_position: null` and one `queue_wait`,
the first that applies in this order:

| `queue_wait` | Meaning | What to do |
| --- | --- | --- |
| `running` | A run of this task is already pending or active. | Watch it (`cattlepen-orchestration`). |
| `container` | An epic; it never runs. | Nothing; it closes with its last child. |
| `cancelled_child` | A child task was cancelled. | Decide with the user about that child. |
| `children` | Children are not all `done`. | Wait, or work on the children. |
| `project` | The task has no project. | Move it into one (`PATCH /tasks/{id}` with `project_id`). |
| `project_access_revoked` | The person who queued it is no longer a project member. | Re-grant, or have a member queue it. |
| `repository` | The selection does not resolve: no `repo` in a project of several or no entries, or a named repository the project no longer lists. | `update_task{task_id, repo}` or `readonly_repos`; add an entry to the project. |
| `workflow_deleting` | Its workflow is being deleted. | Ask the user; the deletion decides what happens to the workflow's tasks. |
| `configuration` | `launch_problem` is set. | Fix what it names (see `runners-and-keys.md`). |
| `project_full` | The project's run cap is reached. | Wait, or raise `max_concurrent_runs`. |
| `iteration` | The project plans in iterations and the task is not in the active one. | Plan it into the active iteration, or start its iteration. |

`queue_position` is an estimate across the whole account: deepest tasks first (children before
parents), then higher `priority`, then earlier queue time. Measured: two children at depth 1 with
priorities 5 and 3 got positions 1 and 2, a top-level task got 3. Capacity and runner
availability decide what actually starts.

## The exhaust queue (automatic starts)

Read the account setting:

```json
{"operation": "GET /accounts/{id}/settings", "request": {"path": {"id": "<account id>"}}}
```

It returns `{exhaust_queue, queued_ready}`; `queued_ready` counts queued tasks the server would
start now if seats allowed. While `exhaust_queue` is `false`, queued tasks wait for someone to
start them (`start_run`), however ready they are. `PATCH /accounts/{id}/settings` with
`{"exhaust_queue": true}` makes the server create runs for ready queued tasks at once, as far as
the account's runner seats allow, and keep doing so as seats free up. Only an account owner (the
`manage_projects` permission) may change it. Turning it on starts runs: ask the user first, and
tell them how many (`queued_ready`).

## Iterations

| Tool | Effect |
| --- | --- |
| `list_iterations{project_id, include_closed}` | The project's iterations in order: `name`, `starts_on`, `ends_on`, `status` (`planned`, `active`, `closed`), `tasks_total`, `tasks_done`. |
| `create_iteration{project_id, name, starts_on, ends_on}` | A planned iteration. Omitted name: "Iteration N". Omitted dates: from the day after the last iteration ends (or today), 14 days long. |
| `update_iteration{iteration_id, name, starts_on, ends_on}` | Rename or re-date; a closed iteration cannot change. |
| `start_iteration{iteration_id}` | Makes it the active one. Refused while another is active: 409 `iteration.active_exists`, naming it. |
| `close_iteration{iteration_id, carry_to, start_next}` | Closes the active iteration; tasks not done move to `carry_to` (an iteration id, `"new"` or `"backlog"`). Returns `{closed, target, moved}`. A closed iteration cannot reopen. |
| `delete_iteration{iteration_id}` | Planned iterations only; their tasks return to the backlog. Ask first. |

A task joins an iteration through `create_task{iteration_id}` or `update_task{task_id,
iteration_id}` (the whole subtree moves); `update_task{task_id, clear_iteration: true}` returns it
to the backlog.

How iterations gate the queue, measured on one queued, ready task:

1. The project had a planned iteration and the task was in the backlog: `queue_wait: "iteration"`.
2. Planned into that iteration, still planned: `queue_wait: "iteration"`.
3. After `start_iteration`: `queue_position: 1`, `queue_wait: null`.

So as soon as a project has any iteration that is not closed, backlog tasks and tasks in planned
iterations do not start from the queue; a project whose iterations are all closed queues as if it
had none. `start_iteration` makes the active iteration's queued tasks startable, and with the
exhaust queue on the server creates their runs at once.
