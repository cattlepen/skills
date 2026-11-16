# Symptoms once a run has started

Four symptoms: the run halted; it is parked on a question; a node fails or loops through its reworks; it
completed but the result is wrong. Do not start runs to test a theory: each start costs the user model usage
and can change their repository. Read the run with `get_run`, `get_run_events` and `get_run_waits`; start a
run only when the user asks.

Most of this page is read from the runner's and the server's source. What was seen on recorded runs of a
test installation is marked **seen**: runs halted at a `cancel` node, human gates answered (including a
reject that sent the work round a rework), an agent node retried after a missing output, and completed
runs. Halt kinds other than `runner`, provider limits and parks, escalation questions, and a node failing
for good were not seen.

## Reading a run

- `get_run{run_id}`: `status`, `outcome` (`{status, reason}` once it ended), `failed_node` and `halt_kind`
  on a halt, `limit_wait`, `parked_reason`, `open_waits` (the number of questions waiting), `pending_reason`,
  `source_run_id` (set on a resumed or readmitted run), `workflow_version` (the version it runs; a run never
  changes version).
- `get_run_events{run_id, after?}`: the journal, oldest first; page with `after` set to the last `seq`.
  Event types seen: `run_dispatched`, `run_started`, `node_started` (with `iteration`, from `"0"`, and
  `attempt`, from 0), `node_event` (narration: `payload.kind` such as `run`, `bash`, `say`, `agent`,
  `publish`, `delta`, and `retry`), `node_completed` (with the produced `deliverables[]{name, value}`),
  `branch_routed` (a switch's `value` and the node it went `to`), `rework_triggered` (with the `rework`
  name), `awaiting_answer`, `answer_recorded`, `run_halted`, `run_completed`. From source also
  `node_failed` (reason `<code>: <message>`), `run_declined`, `dispatch_failed`.
- Node ids in events are the UUIDs in each node's `id`; map them to node names with
  `get_declaration{kind: "workflows", entry_id, version}` of the run's version.

## 8. The run halted

`status: "halted"`. Read `halt_kind`, `outcome.reason` and `failed_node`.

### `halt_kind: "runner"`, reason "plan-directed halt" (seen)

The workflow reached a `type: cancel` node; `failed_node` is that cancel node's id. This is the workflow
doing what it says, not a crash, and the reason says nothing more. Find the path in the events: the last
`branch_routed` before `run_halted` names the switch value and target, and the `node_completed` event of the
node that produced the switched deliverable holds the explanation in its value. Seen twice: an inline fetch
step wrote a failure message into its deliverable, the switch routed `{"value": "failed", "to":
"fetch_failed"}`, and `fetch_failed` was a cancel node.

Usual causes: a rework ran out (`max_reworks` reached, `on_exhausted` points at the cancel node); a check
step judged the input bad; a person rejected at a gate and the route leads to cancel. Fix the input or the
step that produced the routed value, or the routing if it is wrong. A fix that changes the workflow goes
into a new version (`change-published.md`).

### `halt_kind: "runner"`, reason "node '<name>' failed: <code>: <message> detail: {...}"

A node failed after its attempts ran out. `failed_node` is the node; `get_run_events` has a `node_failed`
event for it. The code says what failed; section 10 lists the common ones. An unrouted switch value
halts with the bare reason "switch '<node>': value '<value>' of '<field>' has no route and no default".

### `halt_kind: "limit"`

A model provider's usage limit stopped an agent node and the reset is too far away to wait in place.
`limit_wait` is `{backend, window?, resets_at?}`. The server readmits the run by itself, as a new run with
`source_run_id` set to this one, about a minute after `resets_at`, when: the halt is less than 8 days old,
the same runner is connected and no longer limited, no later run of the task exists, and (self-hosted) the
creator is still a project member. Do not start another run of the task: any later run of the task
prevents the automatic readmission. Check later with `list_runs{task_id}`. Without `resets_at` there is no
automatic readmission; resume by hand after the limit resets (below).

### Other halt kinds

| kind | what happened | what to do |
|---|---|---|
| `lease_expired` | the runner stopped reporting for longer than its lease (900 s by default): it crashed, lost its connection or was stopped | bring the runner back, then resume |
| `undelivered` | the run was offered several times (three by default) and no runner confirmed the start ("no runner confirmed the start after <n> attempts") | check the runner (`list_runners`); start a new run |
| `no_project`, `project_missing`, `no_repo` | the task lost its project or repository selection before dispatch | fix the task (`launch-and-dispatch.md`, 5.3); start a new run |
| `input_snapshot_missing`, `resume.execution-unpinned` | the run predates the current snapshot rules | start a new run |

### Resuming a halted run

`mutate_api_operation{operation: "POST /runs/{id}/resume", request: {path: {id: <run id>}, body:
{resume_from: <node id or null>}}}` creates a new run on the same runner, continuing from the halted run's
worktree; the halted run stays halted. Only a `halted` run can be resumed ("run <id> is <status>, and only
a halted run can be resumed"), the runner that holds it must be connected and support readmission, and a
halt the server made (the table above, where no runner holds the run) cannot be resumed ("run <id> names no
runner, so there is no worktree to resume from"). After a plan-directed halt name the node to restart from.
A resumed run uses the halted run's workflow version, so a fix published in a new version reaches the task
only through a new run.

Proof for this section: the new run (readmitted, resumed or started) reaches `active`, and later
`completed`, in `get_run`.

## 9. The run is parked on a question

A run waiting for a person has `status: "active"` and `open_waits` above 0. `get_run_waits{run_id}` lists
each wait as `{node_id, at: {iteration, attempt, round_index}, question, created_at}`; an empty `question`
list is still a real wait.

Two kinds of node ask:

- **A human gate** (`type: human_gate`) asks with `question: [{"id": "prompt", "question": <the gate's
  prompt>}]` (seen) and waits for a JSON object that matches the gate's deliverable.
- **An agent node with `escalation`** asks the questions the agent wrote, each with an `id`, and waits
  for `{"answers": [{"id": "<question id>", "answer": "<non-empty text>"}]}`.

Answer with `answer_wait{run_id, node_id, iteration, attempt, round_index, answer_json}`, copying `node_id`
and the three `at` fields exactly. They change: after a rework the same gate asks again with
`iteration: "1"` (seen), so never reuse the address of an earlier answer. `answer_json` is the JSON as a
string, for example `"{\"decision\": \"approve\"}"` for a gate whose deliverable has a required
`decision` enum. Seen: that
answer produced `answer_recorded`, then `node_completed` with `{"decision": "approve", "note": null}`, a
`branch_routed` on `approve`, and `run_completed`.

**One answer closes the wait.** The first answer the runner accepts ends the gate or the escalation round;
a later answer to the same wait is never read. So collect every question's answer first and send them all
in one `answer_wait`: one entry per question `id` in `answers`.

When an answer is refused:

- `409` "run(<id>) is not awaiting an answer at node(<node>)": the wait is gone (already answered, or the
  node moved on). Read `get_run_waits` again.
- `409` "node(<node>) of run(<id>) is awaiting an answer at iteration <i>, attempt <a>, round <r> — not at
  ...": you sent another address; copy `at` again.
- The server does not check the answer's shape. An answer the runner rejects (not an object, not matching
  the deliverable, malformed `answers`) leaves the wait open at the same address, and no reason reaches the
  tools. If the wait is still listed after you answered, check the shape against the gate's deliverable
  (`get_declaration`) and answer again.

Time limits: a gate's `timeout_s` (`null` waits forever) and an escalation's `timeout_s` end the wait by
failing the node (`signal.timeout` "no signal on topic <topic> within <n>s", `agent.escalation_timeout`),
which halts the run. An agent that asks more rounds than `max_rounds` fails with
`agent.escalation_exhausted`.

Proof: `get_run_waits` no longer lists the wait, and `get_run_events` shows `answer_recorded` followed by
`node_completed` for that node (seen).

### Parked without a question

`parked_reason` set while `status` stays `active` means every live node waits on something outside
Cattlepen: `<code>: resumes at <time>`, or `<code>: waiting for the <backend> <window> usage limit to reset
at <time>` with `limit_wait`. `claude.budget` and `codex.budget` are provider usage limits and resume by
themselves. `claude.login_required` and `codex.login_required` mean the harness on the runner machine needs a
login; they retry every 300 s and only the runner's operator can fix them (for codex the message names the
`codex login --device-auth` command to run on the runner machine). A node parked longer than 48 hours in
total fails with `node.park_exhausted`. The proof is `parked_reason` gone from `get_run`.

## 10. A node fails, or loops through its reworks

### How retries work

An agent node gets 3 attempts by default, 20 s apart and doubling (at most 300 s). Each new attempt is told
"Your previous attempt was refused: <code>: <message>". A retry shows as a `node_event` with
`payload.kind: "retry"` and then a `node_started` with the next `attempt`. Seen: a node agent said it had
written its output but had not; the event read `{"kind": "retry", "code": "carrier.missing_output",
"message": "attempt 1 in 20 s · carrier.missing_output", "max_attempts": 3}`, the runner's log line was
"node summarize#0 attempt 0 failed with carrier.missing_output: declared output '<name>' has no
<name>.json in out/ — retrying in 20.0s (1 of 3 attempt(s) spent)", and attempt 1 completed. A retry that
succeeds needs no fix; the same code on every attempt does. When the attempts run out the node fails with
`node.exhausted`, carrying the last message; the underlying code is in the halt `detail` as `last.code`. An
inline node gets one attempt.

### Common failure codes

| code | message (template) | usual cause and fix |
|---|---|---|
| `carrier.missing_output` | "declared output '<name>' has no <name>.json in out/" | an agent must write `<name>.json` for every deliverable it produces, also for markdown (`<name>.json` with the fields, or `{}`, beside `<name>.md`) and html (`{}` beside `<name>.html`); an inline script must write `$SHEPHERD_OUT/<name>.json`. Say so in the agent's prompt |
| `carrier.missing_output` | "markdown output '<name>' has no <name>.md body" | the markdown body file is missing |
| `carrier.invalid_payload` | "output '<name>' does not match its schema: <n> error(s): <name>.<field>: ..." | the message names the field: fix the prompt, or make the field optional if it can be absent |
| `carrier.invalid_payload` | "output '<name>' lacks section '<heading>' (outline position <n>)" | a declared markdown section is missing or out of order |
| `carrier.invalid_payload` | "output '<name>' (<name>.json) is not parseable" / "output '<name>' is not an object" | invalid JSON |
| `carrier.oversize_signal` | "deliverable '<name>' is <n> bytes serialized (> <limit>...); ..." | a value above 64 KiB |
| `agent.sentinel_missing` | "no SHEPHERD_STATUS: line in the ... result tail or full result after <n> continuation turn(s)" | the agent never ended with its status line; usually it stopped early or asked a question in prose. Not retried |
| `agent.session_failed`, `claude.no_envelope`, `codex.failed` | the harness session failed or crashed | look at the node's `node_event` narration; often the harness on the runner |
| `agent.unexpected_escalation` | "the agent wrote questions.json but node '<node>' declares no escalation block; add `escalation:` to let it ask" | allow escalation, or tell the agent not to ask |
| `command.not_found` | "executable not found: '<argv0>'" | an inline command missing on the runner |
| `profile.missing`, `profile.unknown` | ".shepherd/profiles.yml not found in the checked-out tree" / "profile '<name>' is not defined in .shepherd/profiles.yml; has: ..." | define the profile in the repository |
| `signal.timeout` | "no signal on topic '<topic>' within <n>s" | a gate's `timeout_s` passed |
| `node.park_exhausted`, `node.park_churn` | | parked too long (login, limits) |

An inline script's exit code is ignored; only the files it writes count. A script that prints an error and
writes nothing fails `carrier.missing_output`; a script that writes a failure into its deliverable succeeds
(seen: exit code 0, the deliverable said the fetch failed, and the run routed to its cancel node).

### Loops

A rework (`reworks:` entry) sends the run back to its `resume_from` agent when a switch routes into it, at
most `max_reworks` times, then continues at `on_exhausted`. Each round writes a `rework_triggered` event
and raises the `iteration` of the nodes it runs again (seen: a gate reject routed to the rework, the writer
ran again as iteration `"1"`, the gate asked again, and an approve finished the run). If every round loops:

1. Read the feedback the head received: the `node_completed` event of the `feedback.node` carries the
   deliverable value. Empty or generic feedback cannot be acted on.
2. Read the head's prompt (`get_doc` with the agent's `prompt.sha256`): it must tell the agent to read the
   feedback input and change its output in response.
3. Check that the check can pass: an inline check with an impossible threshold, or a reviewer prompt with
   no pass criterion, loops until `on_exhausted`.

Fix the prompt, the check or the budget in a new version (`change-published.md`). Proof needs a run; without
one, show the user the corrected prompt and check next to the evidence from the events.

### Stopping a run

There is no cancel tool. With the user's agreement, send
`mutate_api_operation{operation: "PATCH /runs/{id}", request: {path: {id: <run id>}, body: {status:
"cancelled"}}}`. From source: a pending run no runner has claimed is deleted; a claimed or active run turns
`cancelling` and then `cancelled` once the runner stops it; any other status answers `409` "run <id> is not
cancellable in status <status>". Not exercised on the test installation. Proof: `get_run` shows `cancelled`
(or `404` for a deleted pending run).

## 11. It completed, but the result is wrong

`status: "completed"`, `outcome.reason: null`. The run did what the workflow says; the workflow or its inputs
say the wrong thing.

1. Find what was produced: the `node_completed` events carry each deliverable's value (seen), and
   `result_files` lists files the run returned (it was empty on the runs seen).
2. Find the path: `branch_routed` events show which way every switch went.
3. Compare with the declaration of the run's version: does `outputs` list the deliverable you expected; did
   the switch route on the field you meant; does the agent's prompt ask for what the user wants; did the task's
   input file say what the user meant (`list_task_artifacts`)?

Fix the prompt, the deliverable's fields, the routing or the input; workflow changes go into a new version.
The proof of a better result is a new run, on the user's word; before that, show the user the change and the
evidence that motivated it.
