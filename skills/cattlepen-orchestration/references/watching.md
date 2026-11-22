# Watching runs, answering waits, handling stops

Open this in steps 5 to 7.

## One check of a run

`get_run(run_id)` returns, among others:

- `status`, and `outcome` (`{status, reason}`) once the run is terminal;
- `open_waits`: how many questions the run is parked on right now;
- `parked_reason`, present only while the run is parked, and `limit_wait` (`{backend, window, resets_at}`)
  while it waits on a provider usage limit;
- `pending_reason`, only while the run is `pending`: an object tagged by `code`, `null` before the first
  placement attempt;
- `halt_kind` and `failed_node` on a halted run;
- `dispatch_attempts`, `stopped_at`, `workflow_version`, `exec_profile` (the harness and model of each agent
  node, and of each of its partners under `pair`), `result_files`, `summary_only`.

Seen on three finished runs: a completed one with `outcome: {"status": "completed", "reason": null}`; a
halted one with `halt_kind: "runner"`, a `failed_node`, and `outcome.reason: "plan-directed halt"` (the
workflow routed itself to its own stop node, here after a download failed); a cancelled one with
`outcome: {"status": "cancelled", "reason": null}`.

`get_run_events(run_id, after=<seq>, limit=20)` returns `{"items": [...]}`, oldest first, each item
`{seq, id, event_type, node_id, occurred_at, received_at, payload}`. Always pass a small `limit`: one page
of an agent node's notes reached 86,996 characters at the default of 200 events, more than a client
accepts as one tool result. `after` is exclusive and there is no cursor field: page until `items` is
empty. `seq` grows but skips numbers within a run, so record the last
`seq` you saw; never count events.

Event types, in the order a run produces them:

- `run_dispatched` (a runner was offered the run), `run_started` (it accepted);
- `node_started` (`node_id`, `iteration`, `attempt`), then `node_event` rows while it works: the agent's
  messages (`payload.kind` `say`), its commands (`bash`), the model in use (`binding`), `publish`, and
  `delta` ("changed N files"). An agent node with partners (an adviser, a reviewer) adds their rows:
  each carries `payload.partner`, the partner's mode, and the runner adds `ask` (the agent's question to
  its adviser), `advice` (the answer, and any questions it left for a person) and `verdict` (one per
  review, and one with the outcome when the review loop ends);
- `node_completed`, whose `payload.deliverables` is a list of `{name, value}`. It also carries the node's
  tokens, every agent of the node together: `token_usage` (uncached input and output), `cache_read`,
  `cache_write`.
  On an agent node that spent any, `usage_by_role` splits the same tokens into shares
  `{role, harness, model, token_usage, cache_read, cache_write}`, one per role, harness and model:
  `role` is `executor` for the node's own agent or the partner's mode, and `model` is left out when the
  runner cannot name it. The shares add up to the totals;
- `awaiting_answer` (the run parked on a question) and `answer_recorded` (`answer`, `by`);
- `branch_routed` (`value`, `to`) and `rework_triggered` (`rework`): the workflow chose a path, or sent work
  back to an earlier node, which then runs again with the next `iteration`;
- the end: `run_completed`, `run_halted` (`failed_node`, `reason`), or `run_cancel_requested` then
  `run_cancelled`.

Progress means new events. An agent node can work for a long time, but it keeps writing `node_event` rows.
A run that is `active`, not parked, with `open_waits: 0`, and silent much longer than its nodes usually take
may be stuck: check in `list_runners` that its runner is still connected and still lists the run in
`run_ids`, then decide with the table below.

## What each state asks of you

| What `get_run` shows | Meaning | What to do |
|---|---|---|
| `pending`, `pending_reason: null` | not tried yet | check again shortly |
| `pending`, `runner_busy`, `all_matching_busy`, `account_full` with `seat_count` above 0, `project_full` | no free capacity | wait; do not start more runs |
| `pending`, `account_full` with `seat_count: 0` | the account has no seats: the plan grants none or, on a self-hosted installation, the licence has expired | tell the person; the run starts by itself once seats return |
| `pending`, `runner_limit_reached`, `all_matching_limit_reached` | runners are held back by a provider limit; `resets_at` says until when | wait until `resets_at` |
| `pending`, `awaiting_source_runner` | a resumed run waits for the runner that holds its working copy | wait; tell the person if that runner stays away |
| `pending`, `runner_offline`, `runner_invalid`, `runner_unsuitable`, `no_matching_runner`, `project_access_revoked` | no runner can take it as things are | tell the person what the reason names (runner, harness, model); fixing runners is setup (cattlepen-projects) |
| `active`, new events | working | keep watching |
| `active`, `open_waits` above 0 | parked on a question | "Waits" below |
| `active`, `parked_reason` and `limit_wait.resets_at` | a provider usage limit; the run resumes by itself | nothing until `resets_at` |
| `active`, a `parked_reason` naming `claude.login_required` or `codex.login_required` | the runner machine's CLI login has expired; the run re-checks every 5 minutes | tell the person at once: only the runner's operator can sign in again |
| `active`, another `parked_reason`, no `limit_wait` | parked for another reason, such as a retry after a rate limit | wait; tell the person if it lasts hours |
| `cancelling` | the runner has not yet acknowledged a cancel | wait |
| `completed` | the workflow reached its end | step 8 |
| `halted`, `halt_kind: "limit"` with `limit_wait.resets_at` | the run could not wait out a provider limit; the server resumes it by itself after the reset, as a new run on the same runner, once that runner is back (for up to eight days) | nothing; do not start a new run, which stops the automatic resume |
| `halted`, `halt_kind: "limit"` without `resets_at` | no automatic resume | treat as a failure you must handle |
| `halted`, `halt_kind: "runner"` | a node failed, or the workflow routed to its own stop | read `outcome.reason`, `failed_node` and the last events; then "Retry, resume, cancel" |
| `halted`, `halt_kind: "lease_expired"` | the runner stopped renewing its claim (gone or unreachable) | check `list_runners`; resume or retry once the runner is back |
| `halted`, `halt_kind: "undelivered"` | no runner ever confirmed the start | check the runners; retry once |
| `halted`, `halt_kind` `no_project`, `project_missing` or `no_repo` | the task lost its project or repository selection | fix the task (cattlepen-projects), then retry |
| `get_run` answers 404 | a runner refused the run for good and the server deleted it; no tool returns the reason | ask the person for the notification the web app showed; cattlepen-workflow-repair |

A halt also takes the task out of the queue and back to the backlog.

## Waits

`get_run_waits(run_id)` returns `{"items": [{"node_id", "at": {"iteration", "attempt", "round_index"},
"question", "created_at"}]}`. A wait with an empty `question` list is still a real wait. Answer with:

```
answer_wait(run_id="<run id>", node_id="<items[].node_id>",
            iteration="<at.iteration>", attempt=<at.attempt>, round_index=<at.round_index>,
            answer_json="<the answer as JSON text>")
```

`iteration` is a string (`"0"`, `"1"`); copy all four values from the wait you are answering. There are three
kinds of wait. A partner's question is never one of them: nobody answers it during the run, the node does
not wait for it, and it is attached to the result (`results.md`).

**A human gate.** A node the workflow author put there for a person. Its `question` is one entry,
`{"id": "prompt", "question": "<the gate's prompt>"}`. The answer is a JSON object of the gate's
deliverable; seen: `{"decision": "approve"}` and `{"decision": "reject", "note": "Too long. Cut
Alternatives to two lines."}`. That reject sent the work back, the writer ran again at `iteration` `"1"`,
and the gate opened a new wait at `"iteration": "1"`: copy `at` from the new wait each time. Decide a gate
only when the person told you how. A gate waits 24 hours unless the workflow sets another limit or none;
when that runs out the gate's node fails, so an unanswered gate is a deadline to report.

**An agent's question.** The node allowed its agent to ask; `question` lists `{id, question, context}`.
The answer is `{"answers": [{"id": "<question id>", "answer": "<non-empty text>"}, ...]}` with one entry for
every question. All of them go in one call: the server deletes the wait as soon as it relays an answer, and
the runner resumes the agent's session with what it got. A second call for the same address is refused with
409 "... is not awaiting an answer at node(...)". The question waits as long as the node allows, forever when
it sets no limit, and the run keeps its seat all that time. Answer from the task text and the decisions you
recorded; if the question is one only the person can settle (a product choice, money, credentials), ask
the person. Afterwards add the decision to the description of every task not yet started that it affects.

**A permission question.** Its ids start with `permission-` and its text names a tool and the input it
would run with. "yes" allows it, and that grant holds for every node of the run; any other answer denies it
and reaches the agent as the reason. Leave it to the person unless they delegated it.

After answering, read `get_run_waits` again. If a wait at the same address is back, the runner refused the
answer (a missing field, a value outside an enum, a wrong shape) and asks again; read the question and
answer once more. A 409 naming another iteration, attempt or round means you copied a stale address:
re-read and copy again.

## Retry, resume, cancel

**Retry** is a fresh run from the start: `start_run(task_id)` again, with the current task text. Use it
after runner trouble that is fixed (`lease_expired`, `undelivered`), or after you changed the task text
because the work itself went wrong. Once per cause; a task that fails twice goes to the person.

**Resume** continues a halted run on the runner that holds its working copy:

```
mutate_api_operation(operation="POST /runs/{id}/resume",
                     request={"path": {"id": "<halted run id>"}, "body": {}})
```

The body may name `resume_from`, a node id of that workflow version; after a plan-directed halt (the
workflow reached its own stop node) name it, since the runner refuses to pick a restart point itself
(`resume.plan-halted`). It answers with a new run id; the new run waits for that same runner and runs the
halted run's workflow version, so a fix published since reaches the task only through a fresh run. Refusals: 409 `not_resumable` (the run is not halted), 409
`readmission_unavailable` (that runner is gone, outside the run's pool, or cannot resume runs), 409 while
another run holds the task, 422 for a `resume_from` that is not a node of that version. Use it when the
cause was fixed outside the run, such as a runner that came back.

**Cancel** has no tool of its own:

```
mutate_api_operation(operation="PATCH /runs/{id}",
                     request={"path": {"id": "<run id>"}, "body": {"status": "cancelled"}})
```

It answers 202, 404 for an unknown run, 409 for a run past cancelling. A run not yet placed is deleted; a
placed or active one goes to `cancelling`, then `cancelled`. The task returns to `pending` and, if it was
queued, stays queued, so with queue execution on it starts again. To stop a task for good, dequeue it first,
or cancel the task itself with `update_task(task_id, status="cancelled")`, which also cancels its run.
Cancel a run you started when it works from wrong task text, repeats the same events without progress, or
its runner is gone for good; cancelling throws away the run's work in progress, so say so in the report.

**Stop and tell the person** when a task failed twice, when the table says so, when a question is theirs,
and before anything in the skill's "Not without the person's word" list.
