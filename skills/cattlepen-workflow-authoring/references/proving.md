# Proving a workflow: task, readiness, launch check, trial run

A published workflow is not yet a working one. This file takes it from rung 2 to rung 5 of the
ladder in `../SKILL.md`. Project and task management in depth, and driving many runs, belong to the
projects and orchestration skills; this file covers only what proving one workflow needs.

## 1. The project and its repository

A run works in one repository of a project and can read the project's other repositories. Read the
list with `get_project{project_id}` (`repos[]`, each `{name, url, base_branch}`). If the user has no
project yet: `create_project{name, repos: [{name, url, base_branch}]}`. A repository entry without a
`url` must be bound in the runner's own configuration; one with a `url` the runner cannot clone makes
the run fail to start (below).

## 2. The task

```json
{"title": "Explain the repository", "project_id": "<project id>", "workflow_id": "<workflow id>",
 "repo": "app", "readonly_repos": [], "description": "What the run should do, in the user's words."}
```

`create_task` returns the task with `repo`, `readonly_repos`, `resolved_version` (the published
version a run would use), `launch_problem` and `readiness` (whose `state` is about the task's child
tasks, not its input files).

- **Always pass `repo`** when the project lists more than one repository. Without it the task is
  created, `launch_problem` stays `null`, and `start_run` is refused with 409 "task has no repo
  binding". A name the project does not list is refused with 422 `task.unknown_repo`.
- `readonly_repos`: `null` (the default) means every other repository of the project, `[]` none, a
  list those. Every repository a run reads must be reachable by the runner, so narrow it to what the
  workflow needs.
- The agents see the task's title and description; put what the run should do there.

## 3. Inputs

For each name in the workflow's `inputs`, attach a file. `get_task_readiness{task_id}` lists them as
`requirements`, and `get_doc{sha256: <the requirement's deliverable_sha256>}` returns each one's
deliverable document with its fields (the requirement's `deliverable_id` is a version id: the
library tools answer 404 for it).

```json
{"task_id": "<task id>", "filename": "brief.json", "input_name": "brief",
 "media_type": "application/json", "content": "{\"title\": \"Next quarter\", \"description\": \"...\"}"}
```

`attach_task_file` binds the file to that input. `media_type` is a bare `type/subtype`
(`application/json`, the default, or `text/markdown`); parameters such as `; charset=utf-8` are
refused. A json file holds exactly the deliverable's declared fields, with the declared types;
an extra key makes it invalid. A file that does not match is still attached and bound, and
readiness reports `input.invalid` without naming the field: fix the content and attach again with
`artifact_id` set to the attached file's id (from `get_task_readiness` `artifacts[]` or
`list_task_artifacts`), which replaces it.

## 4. Readiness and the launch check (rung 4)

1. `get_task_readiness{task_id}` returns `ready`, `workflow_version_id`, `requirements`,
   `artifacts` and `diagnostics` (`input.missing`, `input.invalid`, `input.unknown`). It covers the
   inputs only. Wanted: `ready: true` and no diagnostics.
2. Read the task again (`list_tasks{project_id}`) for `launch_problem`. It must be `null`. Its codes:
   `no_published_version`, `version_not_launchable` (an agent node's runtime, or a partner's, is
   invalid: publish a fixed version), `model_required` (a harness that needs a model has none),
   `no_runner_supports` (no runner key enables that harness or model), and codes for a task pinned to
   an unusable runner. A problem that carries `mode` is about that partner of the node, not the node's
   own runtime.
3. Check that a runner that can take the task is online, because `launch_problem` counts runner keys
   whether or not the runner is connected; a run with no online runner stays `pending`:
   - `read_api_operation{operation: "GET /runners", request: {query: {project_id: <project id>}}}`
     lists the runner keys you can see (on a self-hosted installation, only those whose owner is a
     member of the project). One of them needs `status: "online"`, `own: true` or `shared: true`,
     every harness the workflow uses in `enabled_harnesses`, and every model a node names in
     `models[<harness>]`, counting each node's partners (`pair`) with their own runtimes;
   - for a quick count, `read_api_operation{operation: "GET /catalog/models", request: {}}` gives
     each `{harness, model}` with `runners` (keys) and `online` (connected now), across the account.
   A node or partner without a model takes its harness's default model. The full runner check,
   and creating a runner key, belong to the `cattlepen-projects` skill.

Rung 4 holds when all three pass. If no runner is online, say so and stop here: the user has to start
one (`shepherd` on their machine).

## 5. The trial run (rung 5), only when the user asks

`start_run{task_id}` returns the run `id`. It is refused, without creating a run, with:
409 `task.launch_problem` `{problem: {code, node_id, node_name, mode?, harness}}`; 409 "task has no repo
binding"; 422 "task inputs are not ready" with the readiness diagnostics. A run can also stay
`pending`; `get_run` then gives a `pending_reason`.

Follow it by calling the tools again until it ends. How you wait between checks is your harness's
business (a shell `sleep`, run in the background where the harness requires it); never poll in a tight
loop, and do not end your turn while the run is live unless a wait you started will bring you back.

- `get_run{run_id}`: `status` is `pending`, `active`, then `completed`, `halted` or `cancelled`.
- `get_run_events{run_id, after: <last seq>, limit: 20}`: the journal in order. Keep `limit` small and
  page forward, `after` set to the last `seq` you read, until a page comes back empty: one page of an
  agent node's notes reached 86,996 characters at the default of 200 events, more than a client
  accepts as one tool result. A healthy run reads
  `run_dispatched`, `run_started`, then per node `node_started`, `node_event` notes and
  `node_completed` (which carries the node's deliverables), `branch_routed` at each switch,
  `rework_triggered` when work is sent back, and finally `run_completed`, or `run_halted` with
  `failed_node` and `reason`.
- A human gate shows `awaiting_answer` with one question `{"id": "prompt", "question": <the gate's
  prompt>}`. `get_run_waits{run_id}` lists open waits. Ask the user for the decision; do not decide it
  for them. Then `answer_wait{run_id, node_id, iteration, attempt, round_index, answer_json}`, copying
  the first four from the wait, with `answer_json` a JSON string matching the gate's deliverable,
  for example `"{\"decision\": \"approve\"}"`. The user can also answer on the run's page.

What one completed run looked like on a test installation (an agent writes a markdown proposal, a
gate, a switch): `run_dispatched`, `run_started`, `node_started` for the agent, notes for the restore
of the working tree, the model binding, the agent's shell commands and its final message, a
`publish` note for the deliverable, `node_completed` with the proposal, `node_started` and
`awaiting_answer` at the gate, `answer_recorded` `{"decision": "approve"}`, `node_completed` with
`{"decision": "approve", "note": null}`, `branch_routed` to the end node, `run_completed`.

Answering waits, retrying, resuming and cancelling across several runs are covered in depth by the
`cattlepen-orchestration` skill; a run that halts on a defect or vanishes, by
`cattlepen-workflow-repair`. What follows is what one trial run needs.

## 6. When the run does not complete

- **`get_run` answers 404 "run ... not found" after the run was dispatched.** The runner refused it
  at start and the server deleted it, events included. No MCP tool can read the reason. The usual
  causes: a runner-only rule (`runner-rules.md`; run `shepherd validate` on the published documents),
  a repository the runner cannot clone or has no binding for (refused after a few retries), an inline
  profile the repository lacks. Tell the user the reason is visible in the web app and in the
  runner's log, and check the causes you can.
- **`halted` with `reason` "plan-directed halt"**: the run reached a `cancel` node, which is how the
  graph says "stop". Check which route led there; it may be correct behaviour.
- **`halted` at a node**: the reason names the node and a code. An inline node that did not write a
  declared output (`carrier.missing_output`) stops the run at once, and its stderr tail is in the
  reason. An agent node that failed every attempt is `node.exhausted`. A switch value with no route,
  a gate that timed out: see `runtime-contract.md`. Fix the workflow in a new version
  (`create_version`), publish, and start a new run when the user asks.
- **`pending` for long**: read `pending_reason` and the runner check in section 4.
- **To cancel a run** (only when the user asks), there is no dedicated tool:
  `mutate_api_operation{operation: "PATCH /runs/{id}", request: {path: {id: <run id>},
  body: {status: "cancelled"}}}`. A 409 means the run is already past cancelling.

## 7. Report

Tell the user the rung reached, the run id if there was one, and the next step. For example: "Rung 4:
the task is ready and a runner with claude-code is online. A trial run needs your go-ahead." or
"Rung 3: published and checked; no runner is online, so no task can start yet."
