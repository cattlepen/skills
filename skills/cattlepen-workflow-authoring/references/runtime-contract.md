# The runtime contract: what a node receives and must write

What the runner (`shepherd`) does with each node of a published workflow. Read it before writing an
agent prompt or an inline script. Paths below are examples: a node reads its real paths from its
prompt or its environment, never from a guess.

## Where a node runs

- **The working directory** is a git worktree of the task's repository (`repo`), checked out at the
  run's start commit with a detached HEAD. Each node also gets an exchange directory outside that
  tree, `in/` (inputs) and `out/` (outputs), so exchange files never show up in `git status` or a diff.
- **The runner never commits.** Edits stay in the working tree and carry over to later nodes. A failed
  agent attempt is rolled back to the tree the node started with (ignored files such as build output
  are kept). On a rework the tree is not reset: the previous pass's edits are still there.
- **Read-only repositories.** The task's `readonly_repos` are checked out once per run beside the
  working tree, each at a commit recorded when the run was accepted (the runner binding's base branch,
  else the project entry's, else the remote's default). After every attempt of every node, the runner
  puts each one back to that commit; a change there is discarded with a warning note and never fails
  the node. State passes between nodes only in deliverables. An agent's prompt names each read-only
  repository and its path, and tells it that repository's own instruction files do not govern this
  task.
- **After the run** the working trees are removed once the run reaches `end` or `cancel`, and the run's
  directory is deleted soon after a completed run. A halted or cancelled run's directory is kept for
  a retention period. Anything a person must keep (a diff, a report) has to be a deliverable.

## Inputs: `in/`

- `<name>.json` for each consumed deliverable: its stored fields, with an omitted optional field
  present as `null`.
- A markdown input also has `<name>.md`, the body, and its `.json` carries a `"$body"` reference
  (`{name, media_type, sha256, size}`) instead of the text. An html input has `<name>.html`, and its
  `.json` holds only the `"$body"` reference.
- An optional input with no value has no file. The prompt lists it as
  `- <name>: not provided — an optional input with no value in this run, so it has no file.`
- `_shepherd/run.json`:

  ```json
  {"run_id": "...", "base_sha": "<start commit>", "start_ref": "main",
   "repository_path": "<the operator's clone: never modify it>",
   "readonly_repositories": [{"name": "docs", "path": "<checkout to read>", "base_sha": "...",
                              "start_ref": "main", "repository_path": "<never modify>"}],
   "task": {"id": "...", "title": "...", "description": "..."}}
  ```

  `readonly_repositories` is always a list, sorted by name and `[]` when there are none; note the
  spelling differs from the task field `readonly_repos`. `task` can be `null`. Work in the current
  directory; never write to any `repository_path`.
- `_task_context.json`, when the run carries the task's attached files: one entry per file (`id`, `title`,
  `filename`, `media_type`, `input_name`, `path`, ...), where `path` is a local copy under
  `in/_task_context/`. Agents can read attachments that are not bound to an input from there.

## Outputs: `out/`

| format | files to write |
|---|---|
| json | `<name>.json` with exactly the declared fields: no extra keys, the declared types, no `null` in a required field |
| markdown | `<name>.md`, the body, **and** `<name>.json` with the front-matter fields, or `{}` when there are none; a missing `.json` fails even with no fields |
| html | `<name>.html`, a complete document, **and** `<name>.json` containing exactly `{}` |

- Declared markdown sections must appear in the body as `#` headings in the declared order, matched
  on level and exact title. Headings inside code fences do not count, and underlined (setext)
  headings are not recognised.
- Types are strict: `"1"` is not an int and `1` is not a bool; a whole number is accepted for a float.
- The stored json value is limited to 64 KiB. A markdown or html body is stored separately and only
  its short reference counts, so long text belongs in a body.
- Files that match no declared output are ignored. `out/` is emptied at the start of each attempt.

## Agent nodes

### What the runner adds to the prompt

Your prompt is sent verbatim (no templating), followed by the runner's own text:

- **On every turn, the status contract:** the answer must end with a line
  `SHEPHERD_STATUS: <token>` in plain text (in bold or backticks it does not count). A session that
  ends without one is continued at most twice, then fails with `agent.sentinel_missing`, which stops
  the run. The token is not routable. The same text tells the agent never to end its turn while work
  it started in the background is still running.
- **On the first turn of each attempt:** the task's title and description; each read-only repository
  as `- <name>: <path>`; every input with its path and fields; every output with its path, each
  field's type, whether it is required and its enum values, the required markdown headings, and the
  size bound; a command to upload a file and get a link, when the runner offers one; on a rework, for
  the head, the sentence naming the feedback files; after a refused attempt,
  `Your previous attempt was refused: <code>: <message>`.
- **When the node declares `escalation`:** how to ask a person (below).
- **When the node declares partners (`pair`):** what the executor may do with them ([Partners](#partners)).

So a prompt does not repeat paths, file names, field types or the status line. It says what the role
is and what good work looks like, what goes into each field, **when to choose each enum value** (that
is the routing), what to do when the work comes back, and what the agent must not do (for example:
do not commit, do not edit the repository).

### Retries and failure

- Attempts = `settings.max_agent_retries` + 1 (3 when absent), waiting 20, 40, 80, 160, then 300
  seconds between them.
- A missing, invalid or oversized output (`carrier.missing_output`, `carrier.invalid_payload`,
  `carrier.oversize_signal`) is retried, and the next attempt is told the refusal. A failed session
  (`agent.session_failed`) is retried without that line.
- Each attempt starts from the node's starting tree, with an empty `out/` and a fresh session that
  remembers nothing of the earlier attempt.
- When retries run out the node fails with `node.exhausted` and the run halts. Some failures stop the
  run at once: `agent.sentinel_missing` and the escalation errors below.
- Nothing in a declaration limits how long an agent turn takes.

### Escalation: an agent asks a person

With `escalation: {max_rounds: N}` on the node, the agent can stop and write `questions.json` next
to `in/` and `out/`:

```json
{"questions": [{"id": "scope", "question": "Should the export include archived items?", "context": "optional"}]}
```

No other keys, a non-empty `id` and `question`, at most 64 KiB, and it ends its turn without a status
line. The run shows a wait; the answer is `{"answers": [{"id": "scope", "answer": "<non-empty text>"}]}`
and returns to the same session. `max_rounds` counts rounds (stops to ask), not questions. Failures,
each of which halts the run: an empty list (`agent.malformed_escalation`), a question file from a node
without `escalation` (`agent.unexpected_escalation`), asking past `max_rounds`
(`agent.escalation_exhausted`), an expired `timeout_s` (`agent.escalation_timeout`). The injected
text does not say that an empty list is fatal: say so in the prompt of an agent that may ask, and that
"a question the repository can answer is a lookup, not a question".

If a runner's operator runs Claude Code under a permission mode other than bypass, each permission
prompt also becomes a question to a person.

## Partners

An agent node's `pair` (`dialect.md`, "Partners") adds second agents beside the node's own agent, the
*executor*, inside the same node. This section says what the runner does with an `advise` and a
`review` partner: what each agent is told, what a partner can do, how work passes between them, and
what a reader of the run sees. Which mode to use, and on which model, is in `patterns.md`, "Partners".

### What each agent is told

Each prompt has two layers. The author writes the partner's prompt as an agent document, and the runner
adds its own text for the mode after it, as it does after the executor's prompt:

- **The partner** receives its agent's prompt, then the runner's text: its role in the mode, the task the
  executor was given (the executor's prompt as written, the task's title and description, and where the
  executor's inputs are), what to look at (a plan, a question or the change), the rules it works by, and
  the shape of its reply.
- **The executor** receives, after its usual additions, what it may do with an adviser (`advise`, below)
  and, in a revise turn, the reviewer's findings and how to answer them (`review`, below). Its first
  turn is not told that a review follows.

So a partner's prompt says who the partner is, what it cares about and what the project requires:
conventions where they differ from what the repository shows, policies, facts about the environment.
It never restates the reply shape, the checkpoint, where the files are or that it must not edit: the
runner says all of that, and a second version in the prompt can only disagree with it. The executor's
prompt does not explain its partners either; the runner tells it what it can do.

### What a partner can do

- **It cannot write**, by its launch, not by its prompt. On `claude-code` it runs with only the tools
  that read, search and list files, and with no MCP server; on `codex` it runs in a read-only sandbox,
  whatever the runner's codex settings say about approvals and sandboxing. It works in the executor's
  working directory and reads the repository, the executor's inputs and the files the runner prepares
  for it. It cannot change a file, run the project's tests or run any command that writes, so a partner
  prompt asks it to read and judge, never to run the tests or fix anything.
- **It starts fresh for each call.** Each review and each adviser call is a new session that remembers
  nothing of the earlier ones; what it needs from them is in its prompt. The one exception: a reviewer
  whose reply is not a valid verdict is resumed once, in the same session, and asked for the verdict
  again.
- **It signs in as an agent node of its harness does** on the runner: the runner's Claude Code
  credentials and settings for the partner's agent name, or its codex configuration. Its model and
  effort are its declared `runtime`, or the task's partner override, fixed when the run is accepted; a
  resumed run keeps them. A runtime without a model or an effort passes none, so the harness's own
  default applies.

### `advise`: the executor asks

- **What the executor is told.** Every turn in which it may ask (the first turn of an attempt, a turn
  resumed with answers, a revise turn) ends with a section saying that a partner, another AI agent that
  does not see the session, is available; how many questions are left in the attempt (`max_calls` at the
  start); when to ask (when stuck after two failed tries at the same problem, and before a choice that
  is hard to undo); and how: write the question, the files it concerns and what was tried to
  `partner.json` in the exchange directory, beside `in/` and `out/`, then end the turn. The answer comes
  back as a new turn in the same session, with the work kept. When no question is left, one line says
  the channel is closed. A turn the runner continues because it ended without its status line carries
  none of this, and its file is not read.
- **An ask.** After such a turn the runner reads `partner.json` and consumes it. A question with a call
  left is put to the adviser and spends one call, and the executor's session resumes with the reply,
  framed as advice from another AI agent, not the user's instruction: how to do the task stays the
  executor's decision. A question past `max_calls`, or a file that is not JSON, is over 64 KiB or is not
  a question, is not asked and fails nothing: the runner logs a warning and handles the turn as one
  without a question.
- **The plan check (`plan: true`).** The first turn of every attempt, a retried attempt and one resuming
  a parked session included, is also asked to write its plan (its approach, the files it will change,
  what it is unsure of) to the same file and to end the turn without changing any file. The adviser
  comments on the plan, and the executor resumes with the comments and carries out the task. The plan
  check is not one of the `max_calls` questions. A plan turn that leaves no readable plan gets no plan
  check: the runner logs a warning and the node goes on.
- **The adviser's reply** has two parts, advice for the executor and questions only a person can settle,
  and the executor receives it whole. Its questions never reach a person during the run (below).
- **With `escalation` as well.** `partner.json` and the escalation's `questions.json` are separate: the
  executor may write both in one turn, each is answered on its own budget (`max_calls`,
  `escalation.max_rounds`), and the resumed turn carries the adviser's reply first, then the person's
  answers. A node with both keeps asking the person through `questions.json` in any turn that may ask.

### `review`: the change is reviewed inside the node

- **When.** Once the executor's turn has finished (with its status line, after any continuation) and
  before the node's change is recorded and its outputs published, the runner runs the reviewer. It reads
  the whole change since the attempt began as a diff the runner writes for it (untracked files included;
  on a rework iteration, that iteration's own change), from the second review also a diff of what
  changed since the previous review, and then the changed files themselves. Its prompt also carries the
  earlier rounds: its own reviews, what was sent back, and the executor's replies.
- **What it returns.** One JSON object: a verdict, `ship` or `revise`; findings, each with a severity
  (`blocker`, `major` or `minor`), an origin (`new`, `unresolved` or `regression`), a file and line, a
  claim and its evidence; and questions, each a point the task leaves open with two readings. The
  runner's rules ask the reviewer to rate a finding `blocker` when the change is broken or contradicts
  a sentence of the task in the common case, `major` when it contradicts a sentence of the task for an
  ordinary input or breaks what worked before, and `minor` when it cannot quote a sentence of the task
  that the change contradicts. The task is what the executor was given: its prompt as written and the
  task's title and description. So a rule the executor must be made to keep belongs in the executor's
  prompt or the task as well; written only in the reviewer's prompt, a breach of it can come back as a
  `minor` finding, which never reaches the executor. From the second review on, a finding is `blocker`
  or `major` only when it is still unresolved from an earlier round, a regression the fixes
  introduced, or a new blocker.
- **What goes back.** When the verdict is `revise` with a `blocker` or `major` finding and a round is
  left, the runner resumes the executor's own session with those findings verbatim, in the reviewer's
  order, presented as claims to check rather than orders, from another AI agent that cannot change the
  task. The executor answers each one as fixed, rejected or ambiguous and changes nothing the findings
  do not concern. Every distinct question the reviewer has asked so far is listed in that turn only as
  a point whose current behaviour must stay exactly as it is. `minor` findings never reach the
  executor. A revise turn is an ordinary turn of the executor: it ends with its status line, may be
  continued, may ask a person while the node declares `escalation` and has rounds left in the attempt,
  and may ask its adviser.
- **How the loop ends.** `max_rounds: N` allows N revise turns, so a loop runs at most N + 1 reviews,
  and the last one sends nothing back. It ends with one of five outcomes:

  | outcome | when |
  |---|---|
  | `ship` | the reviewer's verdict is `ship` |
  | `minor_only` | the verdict is `revise`, but no finding is `blocker` or `major` |
  | `round_cap` | the review after the last allowed revise turn still holds a `blocker` or `major` finding |
  | `needs_person` | as `round_cap`, and one of those findings is a `regression` |
  | `partner_unavailable` | the reviewer ran and returned no valid verdict, even when asked once more |

  The node completes whatever the outcome: neither running out of rounds nor an unavailable reviewer
  fails it, and the run goes on to the node's `next`. What an outcome means for the work is the
  workflow's decision: route the verdict through a switch on `outcome`.
- **The verdict deliverable.** When `verdict` names one, the runner writes it after the loop, replacing
  any file the executor wrote under that name; the executor is not asked to write it. It holds
  `outcome`; `rounds`, the reviews run; `findings`, those still open, which are the findings of the last
  valid review that were never sent to the executor (its `minor` ones, and at `round_cap` and
  `needs_person` its `blocker` and `major` ones too); and `questions`, the distinct questions of every
  review. A value over the 64 KiB bound has its longest texts cut, with a marker, until it fits. Its
  exact fields are in `dialect.md`, "Partners". Without `verdict`, the outcome and what is left open
  show only in the run's notes.

### A partner's questions

Nobody answers a partner's question while the run is going, and the node never waits for an answer: no
wait appears in `get_run_waits`.

- An adviser's questions are recorded in its `advice` note. When there are any, the executor is told
  that they were recorded for the task's owner and that nobody will answer them during the run, and to
  decide each one itself, keep working toward the task, take the option easiest to undo where the
  options are otherwise equal, and name every such choice in its final message.
- A reviewer's questions reach the executor only as points to leave as they are, and they land in the
  verdict deliverable and in the loop's last `verdict` note.

So a workflow that wants a person to decide routes the verdict through a switch to a human gate, or
declares `escalation` so the executor can ask for itself. Ask the executor to list the choices it made
alone in a deliverable: its final message is not one.

### Notes, tokens and failures

- **Notes.** Every note from a partner's own session (its messages, its reads, the model in use)
  carries `partner` with the mode, beside its `kind`. The runner adds:

  | kind | when | message | other fields |
  |---|---|---|---|
  | `ask` | the executor's question is put to the adviser (never for a plan, nor for a question that is not asked) | the question | `partner: advise` |
  | `advice` | after each adviser call | the advice's first line (`(no advice)` when there is none), then `questions:` and one `- <question>` line each | `partner: advise`, `call` (`plan`, or the question's number from 1), `questions` (a count) |
  | `verdict` | after each review that returned a valid verdict | `round <n>: <ship or revise> · <b> blocker · <m> major · <mi> minor · <q> question(s)` | `partner: review`, `round`, `verdict`, and the counts `blocker`, `major`, `minor`, `questions` |
  | `verdict` | once, when the review loop ends | `<outcome> after <n> review(s)`, then `open findings:` with one `- <severity> <file>:<line>: <claim>` line each, and `questions:` with one `- <point>` line each | `partner: review`, `outcome`, `rounds` |

- **Tokens.** The node's `node_completed` counts every agent of the node together: `token_usage`,
  `cache_read` and `cache_write` include each partner call, a reviewer's second ask included. Beside
  them, `usage_by_role` splits the same tokens into shares, one per role, harness and model: `role` is
  `executor` for the node's own agent and the partner's mode for a partner; `harness` is the one the
  tokens ran on, a partner's own; `model` is the one the harness reported for them, so a sub-agent on
  another model is a share of its own, and it is absent when it cannot be named. The shares add up to
  the three counters. A role that spent nothing has no share, a node that spent no tokens sends no
  `usage_by_role`, and a failed node reports neither.
- **Failures.** A partner's session fails like an agent session of its harness, with the same codes and
  under the same rule. What parks an executor parks the node here too (a provider usage limit, a lost
  login, a codex rate limit); when it resumes, the executor's session continues and the partner runs
  again. Any other failure spends one of
  the node's attempts, and the next attempt starts over, with a fresh executor session, partners
  included. An adviser session its harness reports failed is `agent.session_failed`, and its text
  reaches neither the executor nor a note. In a failure's detail, `session_id` is the executor's
  session and `partner_session_id` the partner's. A reviewer that runs but returns no valid verdict is
  not a failure: the loop ends `partner_unavailable` and the node completes.

## Inline nodes

| | `run: {script: ...}` | `run: {profile: <name>}` |
|---|---|---|
| runs | `sh -c '<script>'` in the node's working tree | the `argv` of that profile in the working tree's `.shepherd/profiles.yml`, with no shell unless `argv` names one |
| inputs | `SHEPHERD__<NAME>` per consumed deliverable: its stored JSON (name upper-cased, other characters `_`); and the files in `$SHEPHERD_IN` | files in `$SHEPHERD_IN` only |
| also | `SHEPHERD_IN`, `SHEPHERD_OUT`, the runner's environment | same |
| time limit | none | the profile's `timeout_s` |

- **The exit code is ignored.** The node succeeds when every declared output is written and valid. A
  missing, invalid or oversized output is not retried: the run halts, and the halt reason carries the
  script's exit code and the end of its stderr. A missing command (`command.not_found`) halts it too.
  A node with no `produces` always succeeds, so it can never stop anything.
- A markdown input's `SHEPHERD__<NAME>` holds the front-matter fields and the `"$body"` reference; read
  the body from `$SHEPHERD_IN/<name>.md`.
- The end of stdout (600 characters) becomes the node's note in the run; the end of stderr is kept
  with it.
- A profile the working tree does not define fails the node (`profile.missing`, `profile.unknown`,
  `profile.malformed`); a profile that times out fails it as `node.exhausted`. The runner also refuses
  a run at start when a profile is missing at the start commit (`runner-rules.md`).

How to write a script that the runner accepts and that routes:

```sh
set -u
log="$(mktemp)"
if sh ./scripts/check.sh >"$log" 2>&1; then result=pass; else result=fail; fi
tail -c 6000 "$log" | jq -Rs --arg r "$result" '{result: $r, summary: .}' > "$SHEPHERD_OUT/test_report.json"
```

- Write a verdict deliverable on **both** outcomes and let a switch route on it. Use `set -u` but not
  `set -e` in a check, so the failing branch still writes its file. Write each output last, in one go.
- In a side-effect step (commit, push, open a pull request), `set -eu` is right: on failure no output
  is written and the run halts with the stderr tail as the reason. Make the step idempotent (look for
  an existing pull request before creating one).
- Commit the change and nothing else. By the commit step the working tree also holds what the run's
  own checks left behind (`__pycache__/`, build output), and `git add -A` stages all of it in a
  repository whose `.gitignore` does not cover it. Stage tracked edits with `git add -u` and new files
  only from a list the developing agent writes into a deliverable, skipping ignored paths; the
  `publish` node of `examples/code_change` does exactly that.
- A markdown output needs both files:
  `printf '%s\n' "# Report" > "$SHEPHERD_OUT/report.md"; printf '{}' > "$SHEPHERD_OUT/report.json"`.
- Treat optional fields as possibly `null`: `jq -r '.note // ""'`.
- Read a read-only repository's path from `run.json`, never from a path you build:

  ```sh
  docs="$(jq -r '.readonly_repositories[] | select(.name == "docs") | .path' "$SHEPHERD_IN/_shepherd/run.json")"
  [ -n "$docs" ] || { echo "the task does not select the repository docs" >&2; exit 1; }
  ```

- Only POSIX `sh`: no `[[`, arrays or `<<<`. Commands the script calls (`jq`, `gh`, `git`) must exist on
  the runner; that is checked only when the node runs.

## Human gates

- The run waits with one question, `{"id": "prompt", "question": <the gate's prompt>}`; a gate with
  no prompt waits with no question at all. The prompt is all the person is told, so it says where to
  find what they judge (which node's deliverable among the run's results) and what each answer does.
- The answer is one JSON object matching the gate's deliverable, at most 64 KiB, for example
  `{"decision": "reject", "note": "Cover the export case too."}`. An answer that does not match is
  refused and the gate keeps waiting. An optional field left out is stored as `null`.
- When `timeout_s` runs out the run halts; `timeout_s: null` waits as long as it takes.

## Switches

A switch reads its field from the stored deliverable and takes that value's route. There is no
default route; a missing value halts the run, which is why the field must be required.

## Reworks

- A route into a rework with budget left sends the run back to `resume_from`: the head and everything
  after it run again; nodes before the head do not. With the budget spent, the run continues at
  `on_exhausted`; that is not a failure.
- **Only the head receives feedback:** the declared `feedback` deliverable and, when a switch routed
  into the rework, also the deliverable that switch read (unless the head consumes it anyway). Its
  prompt gains:
  ``This is rework iteration 1 of at most 2. Your previous result was sent back by `decide`; the
  reason is in `<in>/review.json` (from node `approve`). Address it.`` With two or more files it
  reads "the reasons are in A, B and C. Address them."
- Other nodes in the loop receive nothing extra. A second agent that must react to a review has to
  consume the review itself; inside one node, a `review` partner sends its findings straight to the
  node's agent ([Partners](#partners)).
- The head starts a fresh session. Its own previous output is not among its inputs, but its edits
  are still in the working tree: diff against `base_sha` from `run.json` to see the whole change.

## Run outcomes

| what happened | `get_run` status |
|---|---|
| the run reached `end` | `completed` |
| the run reached `cancel` | `halted`, reason "plan-directed halt" |
| a node failed | `halted`, reason `node '<id>' failed: <code>: <message>` (clipped to 2000 characters) |
| someone stopped it | `cancelled` |

`completed` only means "reached `end`". Route an exhausted loop or a "do not ship" decision to a gate
or to `cancel`, never to `end`, or failed work reports as success.
