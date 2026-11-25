---
name: cattlepen-projects
description: Set up a Cattlepen project so that its tasks can start, and check that honestly - the account a call lands in, the project's repository list, how a runner finds each repository (clone URL or local binding), tasks with repo and readonly_repos, parent and child tasks, input files, iterations, runner keys and project members. Use when creating or changing a project, its repositories or its tasks, attaching task inputs, planning iterations, connecting or configuring a runner for a project, or when a task will not start and no run exists yet because of its setup (no repo, missing inputs, no runner, a queue_wait). Not for writing or changing workflows (cattlepen-workflow-authoring), fixing a workflow that will not publish or a run that was declined or halted (cattlepen-workflow-repair), or queueing, starting and watching runs of several tasks (cattlepen-orchestration).
---

# Cattlepen projects

Cattlepen runs a workflow only inside a project: a named list of repositories, and tasks that
each choose one repository to work in and others to read. A run of a task goes to a runner, a
machine running `shepherd` with a runner key (a credential that ties the runner to a user and says
which harnesses and models it offers), and that runner must find every repository the run uses and
enable the harness (the coding-agent CLI, such as `claude-code` or `codex`) each agent node asks for. This skill builds that layer with the Cattlepen MCP tools and checks it with the
reads that really cover each part: several of the product's own signals look like a green light
and are not one.

## Rules that always hold

1. Every call acts as the signed-in user, in one account. Call `whoami` first; pass the same
   `account_id` on every call of the job when the work is not in the default account.
2. Names are exact. A task names a repository by its entry name, byte for byte (`App` is not
   `app`); a runner binding names the project's name and the entry's name the same way.
3. In a project with more than one repository, always pass `repo` to `create_task`. Without it
   the task is accepted with `launch_problem: null` and cannot start (`start_run` answers 409
   "task has no repo binding").
4. Omitting `readonly_repos` does not mean "none": it means every other repository of the project,
   resolved each time a run is dispatched. Pass `[]` for none, or the names you want.
5. Every repository a run uses, read-only ones included, needs a URL the runner machine can clone
   or a binding in that runner's configuration. No server call checks this; the runner checks it
   when it accepts the run, and a refused run is deleted.
6. Read each signal for what it covers, and only that:
   - `launch_problem` (on a task) compares the workflow with runner key settings, offline keys
     included; `null` does not mean a runner is online.
   - `get_task_readiness` covers the workflow's input files only.
   - a task's `readiness.state` is about its child tasks, not its inputs.
   - `queue_wait` and `queue_position` are filled only for a queued task.
7. Ask the user before an act that spends, exposes or removes: `start_run`, turning on the
   account's exhaust queue (the setting that lets the server start queued tasks by itself),
   `create_api_key`, `revoke_api_key`, any `delete_*`, membership
   changes. A new key's secret appears once in the create reply: hand it to the user once, never
   write it to a file, log or later message.
8. Some writes replace a whole object: `update_project` with `repos` replaces the list and always
   needs `name`; a runner-settings PUT replaces all settings. Read first, change, write back. After
   a refused write, read the object again before retrying: most refusals do not certify that
   nothing changed.

## Steps

### 1. Find the account and your rights

Call `whoami`: note `account_id`, `self_hosted`, `is_installation_admin` and `permissions`
(`manage_projects` to create or change projects, `start_run` to queue, `issue_own_key` for runner
keys). Call `list_accounts` when the user may mean another account, then `list_projects`. Open
`references/accounts-and-access.md` when several accounts or people are involved.

Done when: you can name the `account_id` you will pass and whether you may manage projects.

### 2. Create or update the project and its repository list

`create_project{name, repos:[{name, url, base_branch}]}`; `url` and `base_branch` are optional.
To change the list later, read `get_project`, then send `update_project{project_id, name, repos}`
with every entry to keep. Removing an entry that an unfinished task names is refused with 409
`project.repo_in_use`, which lists the tasks. Open `references/repositories.md` for the entry
rules and errors.

Done when: `get_project` returns each entry with the name, URL and base branch you meant.

### 3. Decide how each runner finds each repository

For each entry, the runner uses, first match wins: a binding in its own configuration, a checkout
it already has under its projects directory whose origin is the URL, or a fresh clone of the URL.
An entry with no URL works only on runners that bind it. Example: project `shop` lists `app` (URL
on the Git host) and `design-notes` (no URL, a folder on the operator's machine). Every runner
serving `shop` needs this in its configuration file, then a service restart:

```toml
[projects."shop".repos."design-notes"]
source = "/Users/me/code/design-notes"
base_branch = "main"
```

Details, decline codes and the operator's commands: `references/repositories.md`.

Done when: for every entry, either `git clone <url>` works on each runner machine, or each runner
serving the project has a binding for it. If you cannot check the machine, tell the user this is
unchecked; no server reply confirms it.

### 4. Create the tasks

`create_task{title, description, project_id, workflow_id, repo, readonly_repos}`. The title and
description go into every agent node's prompt, so write them as the work order. Pin a published
workflow version, or a runner key, with `mutate_api_operation` on `PATCH /tasks/{id}`. Build a
tree with `parent_id` (same project) and `container: true` for an epic that never runs. Open
`references/tasks.md` for the defaults table, pins and the task tree.

Done when: `list_tasks{project_id}` shows each task with `repo` set (or a project of exactly one
entry), `readonly_repos` equal to what you intended (`null` means all others), `resolved_version`
not null, and `launch_problem: null` on every task that should run.

### 5. Attach the input files the workflow needs

`get_task_readiness{task_id}` lists `requirements`. For each, read the expected fields with
`get_doc{sha256: <deliverable_sha256>}`, then `attach_task_file{task_id, filename, content,
input_name}`. A file that does not match is still attached and bound, and readiness shows
`input.invalid`; attach again with the same `artifact_id` (from `readiness.artifacts[].id`).

Done when: `get_task_readiness` returns `ready: true` and `diagnostics: []`.

### 6. Queue and plan, when the user wants a queue

Queue: `mutate_api_operation{operation:"POST /tasks/{id}/queue", request:{path:{id}, body:{subtree:
false}}}`; dequeue: `"POST /tasks/{id}/dequeue"` with `request.query.subtree`. A queued task starts
by itself only while the account's exhaust queue is on, and in a project with an open iteration
only tasks of the active one can start. `references/queue-and-iterations.md` has the details;
driving a queue of many tasks to results belongs to `cattlepen-orchestration`.

Done when: every queued task shows a `queue_position`, or a `queue_wait` you can explain to the user.

### 7. Make sure a runner can take the run

`read_api_operation{operation:"GET /runners", request:{query:{project_id}}}` lists the keys that
count for the project, connected or not. If none fits, propose a key (`create_api_key`) and the
`shepherd runner create` setup to the user. Open `references/runners-and-keys.md` for statuses,
key settings and what a key enables.

Done when: one listed runner has `status: "online"`, is yours (`own: true`) or `shared: true`, has
each harness the workflow uses, its nodes' partners included, in `enabled_harnesses`, and lists in
`models` any model a node or a partner pins.

### 8. Check that the task can start

Read, in this order: `get_project` (the task's repositories exist), `list_tasks{project_id}` (the
task's `repo`, `readonly_repos`, `launch_problem: null`, `frozen: false`), `get_task_readiness`
(`ready: true`), `GET /runners` with `project_id` (step 7), and step 3's reachability answer. Do
not call `start_run` to test it: a refused start changes nothing, but an accepted one is a real run.
Starting and watching belong to `cattlepen-orchestration`.

Done when: every box below is ticked from a server read made after your last change.

## Final checklist

- [ ] `account_id` known and used on every call of the job.
- [ ] `get_project` lists every repository the task works in or reads.
- [ ] The task names `repo`, or the project has exactly one repository.
- [ ] `readonly_repos` is the intended list; if `null`, every other entry is reachable too.
- [ ] Each of those repositories has a clonable URL or a binding on each serving runner (or the
      user was told this is unchecked).
- [ ] `resolved_version` is the version you meant; `launch_problem` is `null`.
- [ ] `get_task_readiness`: `ready: true`, `diagnostics: []`.
- [ ] A runner that counts for the project is `online`, enables the harnesses, offers pinned models.
- [ ] If queued: `queue_position` set, or each `queue_wait` explained; exhaust queue state known.
- [ ] No run started, no key created or revoked, nothing deleted without the user's yes.

Switch skills when the work leaves this layer: a workflow to write or change goes to
`cattlepen-workflow-authoring`; a workflow that will not publish or a run that was declined or
halted goes to `cattlepen-workflow-repair`; starting runs, watching them and answering parked
questions go to `cattlepen-orchestration`.

Where the server's diagnostics disagree with this skill, the server is right.
