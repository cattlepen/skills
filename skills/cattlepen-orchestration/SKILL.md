---
name: cattlepen-orchestration
description: "Carry several Cattlepen tasks through their pipelines to confirmed results through the Cattlepen MCP server: plan the order from dependencies and shared files, write task text a pipeline can run without asking anyone, queue or start runs, watch them, answer parked questions, tell waits that resolve themselves from ones that need you, retry or cancel, and verify each result where it lands. Use when a person hands you a batch of tasks, a feature split into issues or a set of changes across repositories to drive through Cattlepen runs, or asks you to watch, unblock or finish runs already started. Not for writing or publishing workflows (cattlepen-workflow-authoring), setting up projects, repositories or runners (cattlepen-projects), or diagnosing a workflow that will not publish or a run that was declined or halted by a defect (cattlepen-workflow-repair)."
---

# Orchestrating Cattlepen tasks

Cattlepen runs workflows, graphs of agent, script and human-review steps called nodes, on runners: a
`shepherd` process on someone's machine that takes work from the server. A task is one piece of work in a
project; starting it creates a run, one execution of a published version of the task's workflow in one of
the project's repositories. This skill is for the session that carries a chain of tasks to confirmed
results while the person does something else: you choose the order, start the runs, answer what they ask,
deal with stops, and check each result where it lands instead of trusting a run's status. Where no MCP tool
exists, `read_api_operation` (GET) and `mutate_api_operation` reach the public API; the references give the
exact calls.

## Rules that always hold

- A run's status is not the result. `completed` means the workflow reached its end; a change exists for the
  person only once it is where it was meant to land (merged, delivered). Step 8 checks that.
- The pipeline's agents see the task's title and description (only the first 16 KiB of it), the files
  attached to the task and the repositories. They never see this conversation. Whatever you decide goes into
  the task text before the run starts, or into an answer while it runs.
- A task has at most one run in progress. A run checks out its start branch when a runner accepts it and
  sees only what is on that branch then. So a task that needs another task's change starts only once that
  change is on its start branch, and whether the workflow puts it there (it may merge, open a pull request,
  push a branch or leave the change in a deliverable) is found out before planning (step 1). When it does
  not, say so in the plan and wait for the person to merge, merge yourself only with their word, or report
  that these tasks cannot be chained as they are.
- Two tasks that edit the same files without needing each other's change can still collide when both are
  merged. Where the workflow merges, run them one after the other; where it does not, they may run
  together, and the plan and the report tell the person that both changes touch those files.
- A wait (a run parked on a question for a person: a human gate, or an agent asking) closes on its first
  answer. Answer every question of a wait in one `answer_wait` call, copying `node_id` and the `at` fields
  exactly as `get_run_waits` gives them.
- Read the server before each decision. Runs, queues and runners change without you; a value you read ten
  minutes ago is a guess.
- Keep the chain's state in a file outside the conversation and update it after every change, so a context
  reset loses nothing (`references/chain-state.md`).

## Steps

### 1. Read the ground

Call `whoami` (account, `self_hosted`, `seat_count`: how many runs of the account may be in progress at
once, one seat each), `list_runners` (connected runners and the runs they hold), `read_api_operation` with
`GET /runners` and `query: {project_id}` (each runner key that counts for the project: `status`, `running`,
`max_parallel_runs`, `enabled_harnesses`), `read_api_operation` with `GET /accounts/{id}/settings`
(`exhaust_queue`, `queued_ready`), `list_tasks` for the project and `list_runs` with
`statuses: ["pending","active","cancelling"]`. Open `references/model.md` for what each field means and how
they combine into capacity. Then read where the workflow leaves its change: the last nodes of the version
the tasks will run (`get_declaration`), or a completed run's deliverables (`references/results.md`).

Done when you can say how many runs can be placed now, whether queued tasks start by themselves
(`exhaust_queue`), which runs hold seats, and where a change ends up: merged into the start branch, a pull
request, a pushed branch, or a deliverable only.

### 2. Plan the order

For each pair of tasks ask: does one need the other's change, and do they touch the same files? Apply the
two rules above to where step 1 found this workflow leaves its change. Independent tasks on disjoint files
can run together, up to the capacity from step 1. Write the plan into the state file with the reason for
every "after" and who merges (for example "B after A is merged: B calls the function A adds; this workflow
only opens a pull request, so the person merges it first"). The task tree can hold a parent until its
children are done (`references/model.md`, "Task tree"), but done means the child's run completed, not that
its change merged.

Done when every task has a slot (now, after a named task for a stated reason, or held for the person's
merge) and no slot runs more tasks at once than step 1 allows.

### 3. Write each task so nobody has to ask

Open `references/task-text.md`. Create or update each task (`create_task`, `update_task`) with a description
that states the goal and why, the expected observable result, what is in and out of scope, decisions already
made and how done is checked. Pass `repo` whenever the project lists more than one repository. Attach required
inputs with `attach_task_file`. Project and runner setup belong to cattlepen-projects.

Done when, for each task, `get_task_readiness` says `ready: true` with `diagnostics: []`, the task's
`launch_problem` is `null`, a runner key that enables the workflow's harnesses is online (step 1), and its
description answers the questions a pipeline agent would otherwise ask.

### 4. Start

Either queue the tasks and let the server start them in order (only while `exhaust_queue` is on), or call
`start_run(task_id)` yourself when a task's slot comes. A chain whose steps wait on merges is usually paced
by hand. `references/model.md` ("Queue or start_run") has both, with the refusals. A refused `start_run`
creates no run. Record each run id in the state file at once.

Done when every task due now has a run that `get_run` shows as `pending` or `active`, recorded in the state
file, or, for queued tasks, `list_tasks` shows a `queue_position` or a `queue_wait` you can explain.

### 5. Watch

For each live run in the state file: `get_run`, then `get_run_events` with `after` set to the last `seq` you
recorded and a small `limit` (20; a page at the default 200 can exceed what a tool result may hold), paging
until a page is empty, then record the new last `seq`. Space the checks: every one to two minutes while runs
are active, at once after you answer a wait, seldom while everything waits on a provider limit. How you wait
is your harness's business (a shell `sleep`, run in the background where the harness requires it); never
poll in a tight loop, and do not end your turn while runs you are responsible for are live unless a wait you
started will bring you back. Open `references/watching.md` for the fields, the event types and the table
of states.

Done when every run is terminal (`completed`, `halted`, `cancelled`) or gone (`get_run` answers 404), and
every state that needed you was acted on.

### 6. Answer waits

When `get_run` shows `open_waits` above 0, read `get_run_waits` and answer with `answer_wait`. A human gate
answer is a JSON object of the gate's deliverable, for example `{"decision": "approve"}`; an agent's question
is answered with `{"answers": [{"id": "<question id>", "answer": "<text>"}]}`, one entry for every question
in the wait. Search the task text and your recorded decisions before answering, and write the answer into
the state file. `references/watching.md` ("Waits") has the shapes, the permission questions and what to
leave to the person.

Done when `get_run_waits` no longer lists the address you answered and the journal shows `answer_recorded`
for it; if the same wait comes back, your answer was refused: read the question again.

### 7. Deal with stops

Tell apart what resolves itself (a provider usage limit with `limit_wait.resets_at`, a pending run waiting for
a free seat or a busy runner) from what needs you (an open wait, a halt that is not a limit, a login park, a
pending run whose runner is offline, a run that vanished). The full table and the retry, resume and cancel
calls are in `references/watching.md`. Retry a task once when the cause was outside the work; when the work
itself failed, change the task text or ask the person first. For a halt caused by the workflow or a declined
run, switch to cattlepen-workflow-repair.

Done when every stopped run is running again, waiting on something that ends by itself at a time you noted,
or reported to the person with its cause.

### 8. Confirm the result where it lands

Open `references/results.md`. Read the deliverables from the run's `node_completed` events and its
`result_files`; for a code change, find the pull request or branch the workflow made and read its state with
your own tools (the code host's CLI, `git`). Only then mark the task delivered in the state file and start
what depended on it.

Done when, for each task, you can name the evidence: the deliverable you read, or the pull request and its
merge state as the code host reports it.

### 9. Report

Report in outcomes: what was delivered or merged (with links), what waits on the person and until when, what
failed, why, and what you tried, and how many runs you started.

Done when the person can act on every open item from the report alone.

## Not without the person's word

- Answering a human gate on your own judgement. The workflow put a person there; answer only when the person
  told you how to decide that gate.
- Answering a permission question with "yes": the grant holds for every node of that run.
- Publishing a workflow version, or editing a workflow (cattlepen-workflow-authoring).
- Starting runs beyond what was asked, or re-running the same failed task more than once: every run spends
  the runner's subscription.
- Turning on the account's queue execution (`exhaust_queue`): it starts queued, ready tasks across the whole
  account at once (`queued_ready` of them), up to the free seats.
- Merging into a default branch; cancelling a run you did not start; deleting tasks; starting, stopping or
  reconfiguring a runner.

## Final checklist

- [ ] The state file lists every task, its run ids, the last `seq` read, its state and what is owed.
- [ ] The plan says where the workflow leaves its change, and every "after" has a reason (shared files or
      a needed change) and names who puts that change on the start branch.
- [ ] Every task description states goal, expected result, scope, decisions and the done check.
- [ ] No run sits with `open_waits` above 0 unanswered and not reported.
- [ ] Every halted run is retried once, reported, or handed to cattlepen-workflow-repair.
- [ ] Every "delivered" rests on evidence read where the result lands, not on `completed`.
- [ ] The report names what waits on the person.

Where the server's diagnostics disagree with this skill, the server is right.
