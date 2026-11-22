# Symptoms between publishing and the first node

Three symptoms: the workflow is published but its task shows a `launch_problem` or is not ready; a run
stays pending or a queued task never gets a run; a run was declined or vanished. A **task** is the unit of
work a run belongs to; it names a workflow, a project, the repository its runs work in (`repo`) and the
ones they may read (`readonly_repos`). A **run** is one execution of a task's workflow on a **runner**, the
`shepherd` program on a connected machine. Setting up projects, repositories and runners belongs to the
`cattlepen-projects` skill; switch to it when the fix is there.

## 5. Published, but the task shows a `launch_problem` or is not ready

Three different signals say "ready", and none of them checks the others' ground:

| signal | where you read it | what it covers |
|---|---|---|
| `readiness.state` | the task (`list_tasks`, `create_task` and `update_task` replies) | the task tree only: `ready`, `waiting` (open children), `blocked` (a child was cancelled), `running`, `done` |
| `ready` | `get_task_readiness{task_id}` | the workflow's input files only |
| `launch_problem` | the task | the workflow version and runner keys; only the first problem found |

Measured on one task: `readiness.state: "ready"` while `get_task_readiness` said `ready: false` with
`input.missing`. None of the three checks that a runner is online, that the repository can be cloned, or
the runner-only rules (`runner-only-rules.md`).

### 5.1 `launch_problem` is set

Read the task; `launch_problem` is an object with a `code` (all codes and fields: `codes.md`, section 3).
`start_run` on such a task is refused with `409` `task.launch_problem` "the task cannot be launched as it
is configured", carrying the same object as `problem`.

| code | fix |
|---|---|
| `no_runner_supports` | the node's `runtime` names a harness or model no runner key you can use offers. List what is offered with `read_api_operation{operation: "GET /catalog/models", request: {}}` (items: `harness`, `model`, `runners`, `online`). Change the node's runtime in a new version (`change-published.md`), or have a runner that offers it connected (`cattlepen-projects`) |
| `version_not_launchable` | the version has a runtime error (its `diagnostics` say which, usually `agent.no-harness`): fix it in a new version |
| `no_published_version` | publish the workflow (`save-validate-publish.md`) |
| `version_missing` | the task is pinned to a version that is gone: re-pin or unpin it (`change-published.md`, step 7) |
| `model_required` | the harness (`cursor-cli`, `opencode`) needs `runtime.model`: add it in a new version |
| `process_not_selected` | the task has no workflow: `update_task{task_id, workflow_id}` |
| `runner_revoked`, `harness_disabled_on_runner`, `model_missing_on_runner` | the task is pinned to a runner key that is gone or lacks the harness or model: change the key or the task's runner (`cattlepen-projects`) |

**A problem that names a `mode`** is about a partner of the node (`node_name`, `node_id`), not about the
node's own runtime: `no_runner_supports`, `harness_disabled_on_runner` and `model_missing_on_runner` carry
`mode` (`advise`, `review`, `guard` or `watch`) when the partner's runtime is at fault, and so does the
diagnostic path of a `version_not_launchable` (`nodes.<name>.pair.<mode>.runtime...`, or
`nodes.<name>.pair.<mode>` for `pair.harness-unsupported`). `model_required` is never a partner's. Two
fixes:

- **For every task:** change the partner's `runtime` in a new version of the workflow
  (`change-published.md`): a harness and model the catalog lists, on `claude-code` or `codex`.
- **For this task only:** override the partner's runtime by node id and mode, without a new version:

  ```json
  {"operation": "PATCH /tasks/{id}", "request": {"path": {"id": "<task id>"}, "body": {"partner_overrides":
   {"<node_id from the problem>": {"review": {"harness": "claude-code", "model": "<a model the catalog lists>"}}}}}}
  ```

  through `mutate_api_operation`. The value is a whole runtime (`harness` required; an absent model or
  effort is the harness's own default), and the body replaces the whole map: send every partner override
  the task keeps, or `{}` to clear them. A partner override never changes its node, and the node's own
  `exec_overrides` never change its partners. Refusals: 422 `task.override_unknown_node` with `mode` (the
  launched version has no such agent node, or the node has no partner in that mode),
  `task.override_harness_unsupported` (a partner runs on `claude-code` or `codex` only), and the
  `task.override_unknown_harness`, `_unknown_effort` and `_invalid_model` codes with `mode`
  (`codes.md`, section 3). A workflow change resets the map, and an entry whose node or mode the version
  no longer declares is dropped.

Proof for a partner: the task's `launch_problem` is `null`, and `read_api_operation{operation:
"GET /tasks/{id}/exec-profile", request: {path: {id}}}` shows, for that node, `pair.<mode>.effective` with
the runtime you meant.

Measured example: a node with `runtime: {harness: claude-code, model: claude-example-9}` published
with `launchable: true`; its task showed
`{"code": "no_runner_supports", "node_name": "write", "harness": "claude-code", "model": "claude-example-9"}`.
Version 2 used a model the catalog listed; after publishing it the task showed `resolved_version: 2`,
`launch_problem: null`.

`launch_problem` is computed over runner keys whether their runner is connected or not. `null` therefore
does not mean a run will start; read section 6 if it stays pending.

Proof: read the task again; `launch_problem` is `null`.

### 5.2 Inputs are not ready

`get_task_readiness{task_id}` returns `ready`, `requirements[]` (each input's `name`, `required`,
`deliverable_id`, `deliverable_version`, `deliverable_sha256`), `artifacts[]` (the attached files, with `id` and `input_name`) and `diagnostics[]`.
`start_run` on a task that is not ready is refused with `422` "task inputs are not ready", carrying the
readiness object in `details`.

| code | message | fix |
|---|---|---|
| `input.missing` | "required input has no attachment binding" | `attach_task_file{task_id, filename, content, input_name}` |
| `input.invalid` | "content does not match the pinned deliverable schema" | the file is attached and bound but wrong; see below |
| `input.unknown` | "binding is not declared by the selected workflow version" | the file is bound to a name the version does not list in `inputs`: rebind it (`bind_task_artifact`) or unbind it (`input_name: null`) |

`input.invalid` names no field. Read the deliverable the input is pinned to with
`get_doc{sha256: <the requirement's deliverable_sha256>}`, which returns its document (measured). Do not
pass the requirement's `deliverable_id` to `get_declaration`: it is the id of the deliverable's version, not
of its library entry, and the call answers 404 (measured). A JSON input must be one
object with no keys the deliverable does not declare, every `required: true` field present and not null,
and types and enum values matching (from source; an extra key was measured to make it invalid). A markdown
input needs the declared front-matter fields and every declared section heading, in order.

Fix: send the corrected content with `attach_task_file` and the same `artifact_id` (from
`readiness.artifacts[].id`); that replaces the file in place instead of attaching a second one. Measured: the
reply's `readiness` changed from `input.invalid` to `ready: true`.

Proof: `get_task_readiness` returns `ready: true` and `diagnostics: []`.

### 5.3 The repository selection is wrong

- `create_task` or `update_task` refused with `422` `task.unknown_repo` "the task's project lists no
  repository of that name" and `names`: use an entry name exactly as `get_project` lists it in `repos`.
- `start_run` refused with `409` "task has no repo binding": the project lists several repositories and the
  task's `repo` is `null`. A queued task in that state shows `queue_wait: "repository"`; an unqueued one
  shows nothing until you start it. Fix: `update_task{task_id, repo: <entry name>}`.
- `409` `task.launch_frozen`: the task has a run pending, active or cancelling, and its launch fields
  (`repo`, `readonly_repos`, workflow version, runner, `exec_overrides`, `partner_overrides`) are
  read-only until that run ends.

Proof: the task shows the intended `repo` and `readonly_repos`, and a queued task's `queue_wait` is no longer
`repository`.

## 6. The run stays pending, or a queued task gets no run

### A run exists and is `pending`

`get_run{run_id}` has `pending_reason` while the run is pending: `null` before the first placement attempt,
then an object with a `code`. Codes and their fields are in `codes.md`, section 4. What to do:

| code | what to do |
|---|---|
| `runner_busy`, `all_matching_busy` | wait: the run dispatches when a runner finishes one (seen: `{"code": "runner_busy", "running": 3, "max": 3, ...}` on a waiting run) |
| `runner_limit_reached`, `all_matching_limit_reached` | a model provider's usage limit; `resets_at` says until when. `list_runners` shows each runner's `limits` (`backend`, `window`, `status`, `used_percent`, `resets_at`) and `limited_until` |
| `runner_offline`, `no_matching_runner` | no connected runner can take it. `no_matching_runner` is also what every runner being offline looks like. Check `list_runners` (`last_seen_at`) and the harness and model the run needs (`harness`, `model` in the reason; it may be a partner's, and the reason does not say which: the run's `exec_profile` lists each node's partners under `pair`); start or configure a runner (`cattlepen-projects`) |
| `runner_unsuitable`, `runner_invalid` | the task is pinned to a runner that lacks the harness or model, or reports a problem (`reasons[].text`) |
| `account_full` | all seats are taken; `{"used": 0, "seat_count": 0}` means no seats at all, for example a self-hosted installation without a valid license |
| `project_full` | the project's concurrent-run cap; wait, or raise it |
| `project_access_revoked` | the person who started the run is no longer a project member |
| `awaiting_source_runner` | a resumed run waits for the runner that holds the original run |

Proof: call `get_run` again until `status` is `active`; `get_run_events` (in small pages, `limit: 20`; see
`run-time.md`, "Reading a run") then shows `run_dispatched`
followed by `run_started` (the order seen on completed runs).

### A task is queued but no run appears

Read the task: `queue_wait` says why a queued task is held, and `queue_position` its place in line (values in
`codes.md`, section 3). `configuration` means `launch_problem` is set (5.1); `repository` means the repo
selection does not resolve (5.3); `iteration` usually means the task is not in the project's active
iteration. Queueing and iterations belong to the `cattlepen-orchestration` and `cattlepen-projects` skills.

Proof: `list_runs{task_id}` lists a run for the task.

## 7. The run was declined, or it vanished (`404`)

What you see: `start_run` returned an `id`; later `get_run` and `get_run_events` answer `404` "run with id
<id> not found", and `list_runs{task_id}` no longer lists the run. Measured: a run whose repository URL
could not be cloned was declined `workspace.fetch` three times, then removed.

Why: when a runner refuses a run permanently, the server deletes the run together with its events and
waits, and puts the task back to `pending`, out of the queue. The reason goes only to the web app's live
notification and to the server's and runner's logs. **No MCP tool can read why a removed run was
declined**, so do not report "the run started" or guess a reason; say it was declined and removed, then
diagnose.

Before a run vanishes you may catch transient declines: while it is still `pending`, `get_run_events` (small pages, `limit: 20`) shows
`run_declined` events (read from source). `workspace.fetch`, `bundle.download`, `capacity.busy`,
`resume.busy` and `accept.timeout` are transient: the server offers the run again at once. After three in a
row the runner declines it permanently with `accept.retries-exhausted` "declined transiently <n> times in a
row by this runner; the latest refusal was <code>: <message>".

Diagnose by elimination, cheapest first:

1. **The workflow.** Export the version the run used (the task's `resolved_version`, unless a newer
   version was published since the start) and run the runner's validator (`runner-only-rules.md`). A
   `bundle.invalid` or `script.syntax` decline is exactly what it prints.
2. **The repositories.** For the task's `repo` and each `readonly_repos` entry, `get_project` shows `url` and
   `base_branch`: the runner machine must be able to clone the URL with its own credentials, and the branch
   must exist (`workspace.fetch`, `workspace.unbound`). A read-only repository with no URL needs a binding
   in the runner's configuration.
3. **Profiles.** Each inline node with `run: {profile: <name>}` needs `<name>` defined in
   `.shepherd/profiles.yml` of the repository at its base branch, and the commands it names installed on the
   runner (`profile.unbound`, `profile.command-missing`).
4. **Git features.** A repository that uses Git LFS needs `git-lfs` on the runner
   (`workspace.lfs-unavailable`); a relative submodule URL needs an `origin` remote
   (`workspace.submodule-relative-url`).
5. **Input files.** The runner checks them again and, unlike the server, names the field: "$input <name>
   does not match its schema: <n> error(s): ..." (`input.invalid`).
6. **Harnesses.** `dispatch.unresolvable` "<node> cannot be dispatched: <cause>", for example a harness
   the runner is not configured for, or a partner on a harness other than `claude-code` or `codex`. A
   run that carries no runtime for a declared partner is `exec-profile.invalid` (`codes.md`, section 5).

If you or the user can reach the runner machine, its log has one line per refusal,
`shepherd: run <run id> declined — <code>: <message>`, and `shepherd preflight` reproduces the start checks
(`runner-only-rules.md`). The decline codes and messages are in `codes.md`, section 5.

Fix the cause found (a new workflow version, a project or runner change). Proof without starting a run:
`shepherd validate` prints `ok:` on the export, and each repository, profile and input check above holds
(`shepherd preflight` clean where you can run it). The final proof is a run that reaches `active` with
`run_started` in its events; start one only when the user asks.
