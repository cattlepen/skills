# The model: tasks, versions, runs, runners, the task tree and the queue

Open this in steps 1 to 4. Field names and values below are the ones the server returns.

## The four objects

- **Task**: one piece of work in a project. `list_tasks` and `create_task` return, among others:
  - `status`: `pending`, `in_progress`, `done` or `cancelled`. Runs write it: a run turning `active` sets
    `in_progress`, a `completed` run sets `done`, a halted, cancelled or removed run puts it back to
    `pending`. `done` and `cancelled` are settled: no later run outcome changes them.
  - `repo` (the project repository its runs work in) and `readonly_repos` (the ones they may read).
  - `workflow_id`, `workflow_version` (a pinned version number, `null` for the latest) and
    `resolved_version` (the version a start now would use, `null` when nothing is published).
  - `launch_problem`: `null`, or why a start would be refused, such as `{"code": "process_not_selected"}` for
    a task with no workflow. It is checked against runner keys whether or not their runner is online, so
    `null` does not mean a runner will take the run.
  - `parent_id`, `container`, `readiness`, `priority`, `iteration_id`, and the queue fields below.
  - `frozen`: `true` while a run holds the task; its `repo` and `readonly_repos` cannot change then.
- **Workflow version**: a published, immutable version of a workflow. `list_versions` gives each one's `id`
  (the UUID `start_run` takes as `workflow_version_id`), `version`, `launchable` and `launch_diagnostics`.
  Without `workflow_version_id`, `start_run` uses the task's pinned version, else the latest published. If
  a new version is published in the middle of a chain, later runs pick it up; pass `workflow_version_id` to
  keep a chain on one version, and note in the state file which version each run used (`get_run` returns
  `workflow_version`).
- **Run**: one execution of a task's workflow version. `status` is one of `pending`, `active`,
  `completed`, `halted`, `cancelling`, `cancelled`. The vocabulary also has `declined`, kept for old rows:
  a run a runner refuses for good is now deleted, and `get_run` answers 404 for it.
- **Runner**: a `shepherd` process connected with a runner API key. Two reads:
  - `list_runners`: connected runners, each with `label`, `shared`, `capabilities`, `run_ids` (the runs it
    holds), `limits` (`backend`, `window`, `status`, `used_percent`, `resets_at`, `observed_at`) and
    `last_seen_at`, plus the account's `seat_count`.
  - `read_api_operation` with `operation: "GET /runners"`, `request: {query: {project_id: "<project id>"}}`
    (on a self-hosted installation the filter keeps only keys whose owner is a member of the project, the
    only ones that can take its runs; `request: {}` lists them all): every runner key you can see, each
    with `name`, `connection` (`never`, `online`, `offline`), `status` (`online`, `offline`, `invalid`,
    `limit`, `full`, `never`), `running`, `max_parallel_runs`, `manual_dispatch_only`,
    `enabled_harnesses`, `limited_until` and `invalid_reasons`.

## How many runs at once

The server places a pending run only when all of these hold:

1. A seat is free. `seat_count` comes from `whoami` or `list_runners`; every run that is `pending`
   (placed or not), `active` or `cancelling` holds one.
2. The project is under its run cap, when an installation sets one (the refusal names
   `max_concurrent_runs`).
3. An online runner key that enables every harness the workflow's agent nodes use (and offers their
   models) has `running` below its `max_parallel_runs`, and is not held back by a spent provider limit.
   A key with `manual_dispatch_only` takes only tasks pinned to it.
4. The task has no other run in progress: `start_run` refuses with 409 "task already has a run in
   progress".

A run that cannot be placed stays `pending`, and its `pending_reason` says which rule stopped it
(`references/watching.md`). Your plan's width is the smallest of free seats, the project cap and the free
`max_parallel_runs` of the keys that fit the workflow.

## Task tree

A task may have a parent (`parent_id`, same project). A parent starts only once every child is `done`. A
container (`container: true`, an epic) never runs: it becomes `done` by itself when it has children and all
are `done`, and goes back to `pending` when one is reopened.

`readiness` is computed on every read: `{state, open_children, children}`. `state` is `ready` (a leaf, or
every child done), `waiting` (a child is not done; also an epic with no children), `blocked` (a child was
cancelled), `running` or `done`. `open_children` counts direct children not done. Seen on one tree: an epic
with three children read `waiting`, `open_children: 3`; a parent with two leaf children read `waiting`,
`open_children: 2`; the leaves read `ready`.

`start_run` on a container is refused with 409 `task.container`, and on a task with open children with 409
`task.not_ready`, listing them under `open_children`.

To make the server hold B until A is done, put A under B. A task has one parent, so the tree expresses
chains and fan-in, not every graph. "Done" means A's run completed: if B needs A's change merged into the
base branch and A's workflow does not merge it, the server can start B too early. Pace such pairs yourself.

## The queue

Every task starts in the backlog. Queueing moves it to the execution queue; there is no MCP tool for it, so
use the generic operation:

```
mutate_api_operation(operation="POST /tasks/{id}/queue",
                     request={"path": {"id": "<task id>"}, "body": {"subtree": true}})
mutate_api_operation(operation="POST /tasks/{id}/dequeue",
                     request={"path": {"id": "<task id>"}, "query": {"subtree": true}})
```

Both answer 204 with no body; read `list_tasks` afterwards. What was seen on one project:

- Queueing a subtree is all or nothing. One child without a workflow made the whole call fail with 409
  `task.queue_subtree_invalid`, "some tasks cannot be queued; no tasks were changed", and a `tasks` list of
  `{task_id, title, problem}`; nothing was queued. After the child got a workflow the same call succeeded.
- Queueing a container alone (`"subtree": false`) was refused with 409 `task.launch_problem`
  (`process_not_selected`): a container needs `subtree: true`.
- Queueing a task that is already queued, with `"body": {"priority": 7}`, changed its priority and
  re-ordered the queue.
- Dequeue with `subtree: true` cleared `queued_at`, `queue_position` and `queue_wait` on the whole tree.

Order: deepest in the tree first, then higher `priority`, then earlier queue time, then id. Seen on a tree
of an epic, a parent with leaves A (priority 1) and B (priority 5), and two direct leaves of the epic (docs,
priority 9; changelog, priority 0):

| task | depth | priority | `queue_position` | `queue_wait` |
|---|---|---|---|---|
| B | 2 | 5 | 1 | `null` |
| A | 2 | 1 | 2 | `null` |
| docs | 1 | 9 | 3 | `null` |
| changelog | 1 | 0 | 4 | `null` |
| parent | 1 | 0 | `null` | `children` |
| epic | 0 | 0 | `null` | `container` |

`queue_position` is account-wide and only given to a queued task that could start; any other queued task
has `null` and a `queue_wait`:

| `queue_wait` | meaning |
|---|---|
| `container` | an epic; it never runs |
| `children` | a child is not done |
| `cancelled_child` | a child was cancelled; the parent is blocked |
| `iteration` | the project plans in iterations and the task is not in the active one |
| `repository` | its repository selection does not resolve (for example no `repo` in a project with several) |
| `project` | the task has no project |
| `project_full` | the project is at its run cap |
| `project_access_revoked` | whoever queued it is not a member of the project |
| `configuration` | the task has a `launch_problem` |
| `running` | a run holds the task |
| `workflow_deleting` | its workflow is being deleted |

Seen: `container`, `children`, `iteration`, and `null` with a position.

**The queue starts nothing by itself unless the account's queue execution is on.** That is the
`exhaust_queue` flag ("Exhaust queue" in the web app's task list), read with
`read_api_operation(operation="GET /accounts/{id}/settings", request={"path": {"id": "<account id>"}})`.
Its `queued_ready` counts the queued tasks it would start: it read 0, then 1 with one ready task queued,
then 0 after the dequeue, while `exhaust_queue` stayed `false` and no run was created. Only an owner may turn
it on, and turning it on starts up to the free seats at once, across the whole account.

While it is on, the server creates runs for queued tasks that can start, in the order above, up to the free
seats, on a regular tick and whenever a run ends or a task is queued. It leaves queued tasks waiting while
every runner they could use is held back by a provider limit. A run that halts takes its task out of the
queue and back to the backlog, so a retry is a deliberate act: queue the task again. A run a person cancels
leaves its task queued, so it goes back in line and can start again.

Iterations gate the queue: when a project has an iteration that is not closed, only tasks in its active
iteration start; the others read `queue_wait: "iteration"`. Planning iterations belongs to the
`cattlepen-projects` skill.

On a self-hosted installation, queued and automatic work needs explicit membership in the project, even for
an installation administrator: the queue call answers 403 without it.

## Queue or start_run?

`start_run(task_id)` creates a run now, queued or not. It returns `{id}`; the run is `pending` until a
runner accepts it. Refusals create no run:

- 409 "task already has a run in progress": read that run instead;
- 409 `task.container` or `task.not_ready` (see "Task tree");
- 409 `task.launch_problem` with `problem` (for example `no_runner_supports`, `no_published_version`);
- 409 "task has no project" or "task has no repo binding" (no `repo` while the project lists several, or a
  name the project does not list);
- 422 "task inputs are not ready", with the input diagnostics.

Use the queue when queue execution is on and the server's order (children first, then priority) is the
order you want. Use `start_run` when you pace the chain yourself, which is the usual case when a task may
start only after another task's change is merged.
