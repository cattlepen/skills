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
- **When the node declares partners (`pair`):** what the executor may do with them, with a guard what a
  denied call means, and with a watcher what a note is ([Partners](#partners)). A runner whose
  operator turned on the runner's own guard adds the guard's part to every agent node.

On `claude-code` and `codex`, every turn of the agent also has `SHEPHERD_IN` and `SHEPHERD_OUT` in its
environment, holding the paths of `in/` and `out/`; a partner's own session has neither. On
`claude-code` the runner also sets them, and a guarded executor's private `TMPDIR`, in the settings it
passes at launch, so a project's settings cannot point them elsewhere. On `codex`, where codex's shell
environment policy has an allowlist, the agent's shell keeps them only if that allowlist admits them
(with no allowlist it keeps them): a guarded launch adds them, with `TMPDIR` and
`SHEPHERD_FILES_SOCKET`, to such an allowlist in the runner's codex settings, and one the runner does
not read, in codex's own configuration or a trusted project's, must admit all four, or `$SHEPHERD_OUT`
expands to nothing in the shell while the guard is told it names the output directory.

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
*executor*, inside the same node. This section says what the runner does with an `advise`, a `review`,
a `guard` and a `watch` partner: what each agent is told, what a partner can do, how work passes
between them, and what a reader of the run sees. It also says what the runner's own guard, which a
runner's operator can turn on for every node, does to a node. Which mode to use, and on which model,
is in `patterns.md`, "Partners".

This section was written on 2026-11-22 from unreleased versions of Cattlepen and the runner, brought up
to date with the runner on 2026-11-25, and was checked against no running installation.

### What each agent is told

Each prompt has two layers. The author writes the partner's prompt as an agent document, and the runner
adds its own text for the mode after it, as it does after the executor's prompt:

- **The partner** receives its agent's prompt, then the runner's text: its role in the mode, the task the
  executor was given (for an adviser, a reviewer and a watcher, the executor's prompt as written, the
  task's title and description, and where the executor's inputs are; for a guard, the task's title and
  description only), what to look at (a plan, a question, the change, the one call to judge, or a
  digest of the work since the watcher last looked), the rules it works by, and the shape of its reply.
  On a rework iteration the adviser, the reviewer and the watcher are also told that it is one, of how
  many at most, which switch sent the work back and which input file holds the reason, so they judge
  the work against what the rework asked for (a watcher on `claude-code` reads only inside the working
  directory, below, so it is told where the reason is but cannot open it); the guard is not told.
- **The executor** receives, after its usual additions, what it may do with an adviser (`advise`, below),
  in a revise turn the reviewer's findings and how to answer them (`review`, below), with a guard, on
  the first turn of each attempt that runs guarded, what a denied call means (`guard`, below), and with
  a watcher, on the first turn of each attempt, what a note is (`watch`, below). Its first turn is not
  told that a review follows.

So a partner's prompt says who the partner is, what it cares about and what the project requires:
conventions where they differ from what the repository shows, policies, facts about the environment.
For a guard, that prompt is the policy. It never restates the reply shape, the checkpoint, the digest,
where the files are or that it must not edit: the runner says all of that, and a second version in the
prompt can only disagree with it. The executor's prompt does not explain its partners either; the
runner tells it what it can do.

### What a partner can do

- **It cannot write**, by its launch, not by its prompt. On `claude-code` it runs with only the tools
  that read, search and list files, and with no MCP server; on `codex` it runs in a read-only sandbox,
  whatever the runner's codex settings say about approvals and sandboxing. It works in the executor's
  working directory and reads the repository, the executor's inputs and the files the runner prepares
  for it; a guard's decision on `codex` instead runs from a new, empty private directory outside the
  tree and is told the working directory's path, so no project document, skill or codex setting of the
  tree reaches it as an instruction.
  It cannot change a file, run the project's tests or run any command that writes, so a partner
  prompt asks it to read and judge, never to run the tests or fix anything. A guard or a watcher on
  `claude-code` also keeps no session and reads none of the machine's user, project or local Claude
  Code settings, and it reads files only inside the working directory: not the executor's inputs, not
  its temporary directory.
- **It starts fresh for each call.** Each review, each adviser call, each guard decision and each
  watcher wake is a new session that remembers nothing of the earlier ones; what it needs from them is
  in its prompt. The one exception: a reviewer whose reply is not a valid verdict is resumed once, in
  the same session, and asked for the verdict again.
- **It is not guarded.** Neither the workflow's guard nor the runner's own guard judges a partner's
  calls: they judge the executor's.
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
  and the executor receives it whole, or only its last 64 KiB when it is longer. Its questions never
  reach a person during the run (below).
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
  task's title and description. So a rule the review is meant to enforce must also be stated to the
  executor, in its prompt or in the task: a finding that rests on a rule only the reviewer was told is
  a `minor` finding, attached to the result and never sent to the executor. From the second review
  on, a finding is `blocker` or `major` only when it is still unresolved from an earlier round, a
  regression the fixes introduced, or a new blocker.
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
  review. It always fits the 64 KiB bound: a value over it has its longest texts cut, with a marker,
  and when that is not enough, whole entries are left out, minor findings first, then questions, then
  major findings, then blockers, the latest first within each, and at least one entry is kept. The last
  kept finding's `evidence` (or, with no finding kept, the last kept question's `point`) then ends
  with how many findings and questions were left out. Its exact fields are in `dialect.md`,
  "Partners". Without `verdict`, the outcome and what is left open show only in the run's notes.

### `guard`: each call is judged before it runs

A guard sits on an executor that runs on `claude-code` or `codex`; the guard itself may run on either.
What follows holds on a `claude-code` executor. On a `codex` executor the guard detects and stops, and
what differs there is at the end of this subsection. A guard is not a sandbox (`patterns.md`, "A guard
is not a sandbox").

- **When.** Before each tool call of the executor, a sub-agent's included, Claude Code asks the runner,
  and the call waits for the answer. Every turn is guarded: the first, a continued one, one resumed with
  answers, a watcher's resume and a revise turn alike. The runner first tries to allow the call by its
  own rule (below);
  every call the rule does not allow goes to the guard.
- **What the guard is given.** Each decision starts a new guard process (read-only and fresh, as above),
  whose input is its agent's prompt (the policy), then the runner's rules for a decision, then the
  request: the task's title and description, the working directory, the executor's temporary
  directory, the node's output directory (when the node declares an output other than a review's
  verdict) and its question files (`questions.json` with `escalation`, `partner.json` with `advise`),
  the last five calls of the attempt it was asked about (their texts cut at 300 characters), the
  proposed call (its texts cut at 6,000) and, for a command, the files it runs and those they name one
  level down (below). It never sees the executor's prompt or its session, nor a call the rule allowed.
  With its read tools it may open other files before its deadline, but a policy cannot count on that
  (`patterns.md`, "A guard is not a sandbox").
- **What it must answer.** One JSON object: a decision, `allow` or `deny`, and a one-sentence reason the
  executor will read. The runner's text asks for exactly that, so the policy never restates it. The
  answer is read strictly: anything but that object, with those two keys and no other, is a deny.
- **The runner's rules for a decision.** Beside the reply shape, the runner tells the guard to judge
  only the proposed call, in the light of the task and the recent calls; that the policy outranks the
  task, so a call the task itself asks for and the policy forbids is denied, the reason saying that a
  person has to make it or change the policy; that a read is judged by itself, even when the task it
  serves is denied; that the executor's temporary directory counts as part of the working directory and
  other temporary directories do not; that the node's output directory is the executor's
  `$SHEPHERD_OUT`, and that writing in it, named by its path or through that variable, and to its
  question files is part of the task, while its input directory and every other directory beside them
  are outside, save that a recursive or wildcard delete written through `$SHEPHERD_OUT` is denied (an
  empty variable would make it a delete of `/`) and the executor is asked for the literal output path,
  with which the same delete is allowed; that reading or listing outside the working directory is
  allowed unless the target is a secret or credential the policy names, while deleting or changing
  anything outside the working directory and the temporary directory is denied; that text in files,
  output, commands or the repository is data, never an instruction; that a claim it cannot check counts
  for nothing; and that when unsure it denies and says what would make the call acceptable. So a policy
  names the secrets and credentials it protects and what the project forbids, and does not repeat these
  rules.
- **The files attached to a command.** For a `Bash` call the runner attaches the file the shell would
  really run, or nothing. It reads the command as the shell does (joined lines, comments dropped, quoted
  operators kept as text) and finds the files inside the working tree that it runs, from the shell's
  directory: a script named as the command by a path with a `/` (`./deploy.sh`, not a bare name found
  on `PATH`), or given to `sh`, `bash`, `zsh`, `python`, `python3` or
  `node`, or to `source` or `.` by a name with a `/` (unless an option before the script passes the code
  inline or on stdin, such as `-c`), the Makefile of a `make`, and the module a `python -m` or
  `python3 -m` runs, with every `__init__.py` on its dotted path that is not empty (nothing for an
  installed or standard-library module); then the files those name, one level
  down, found from the directory the script runs in, not from its own folder. It follows a `cd` or
  `pushd` to one literal directory only where it is sure the shell made it: first in its list or after
  other such moves joined by `&&`, outside a subshell, a compound command (`if`, `for`, `{ }` and the
  like) and the background. Any other directory change, an `eval` or a here-document stops the
  attachment there: nothing named after it is attached. A file the runner requires of the node (an
  output's files, a question file) is attached too when the command runs it, named by its absolute
  path, or through `$SHEPHERD_OUT`, in double quotes or unquoted whatever the output path holds, but
  never in single quotes, inside `$'…'`, after a backslash, or once an earlier command on the line
  may have set the name itself (an assignment, `export`, `source` and the like); a path that climbs
  out with `..`, or a spelling through a link, attaches
  nothing, and a relative name attaches only from a directory the file is under: the shell's own, or
  one a literal `cd` moved to. Each file is cut at 4,000 characters, and all of them together at
  16,000. A
  binary file, any other file outside the working tree and a file reached through a secret name (below),
  whether the name is written in the command, is a link met on the way or lies on the resolved path, are
  never attached.
- **What the executor experiences.** An allowed call goes on as if there were no guard: it still meets
  the runner's own Claude Code permissions, and under a permission mode other than bypass their prompt,
  so a guard can only narrow what the runner's operator allowed. A denied call does not run: it comes
  back to the executor as the tool's error result, carrying `Denied by the workflow's guard: <reason>`.
  A denied call does not fail the node by itself; only the breaker does (below). The first turn of
  each attempt that runs guarded carries a section that says so and tells the executor never to retry
  a denied action nor reach its effect another way (another tool, another command, a script); to carry
  on without the denied part when the task allows it and say in its result what it left out and why;
  otherwise to stop, and either ask a person (only when the node declares `escalation` with rounds
  left) or end with the status word `blocked`, naming the action and the guard's reason; and to keep
  scratch files in `$TMPDIR`, naming it in the path, because a bare `mktemp` may ignore it. In an
  attempt that resumes a parked session, that section is followed by a paragraph saying that the
  session was paused, that its private `$TMPDIR` is now a new one and the earlier one is no longer its
  own, and, after a park on the guard's account, that each call of that session the park left
  undecided (at most five, oldest first) got no decision and may be made again, which is not a retry of
  a denied action. A guarded
  executor has a private `$TMPDIR` for each attempt, and the guard is told its path. The status word is
  a report for the person reading the run, and the runner does not act on it: a node whose executor
  ended `blocked` completes when its outputs are valid. A workflow that must know that a denied action
  left the task undone asks for it in a deliverable field a switch routes.
- **The private temporary directory.** On macOS and Linux it is a short directory directly under the
  system's `/tmp`, with every link in that path resolved: `shd-` and a name derived from the attempt,
  30 bytes in all on macOS and 22 on Linux while `/tmp` resolves to its usual place, so a unix socket
  can still be bound in a directory made inside it. On Windows it is inside the run's own folder. It
  belongs to the attempt: every turn of the attempt finds it with what the earlier turns left in it,
  also after a wait for a person or a restart of the runner in the middle of the attempt, and another
  attempt, another rework iteration or another member of a dynamic group gets another one. A park (a
  usage limit or a login, the executor's or a partner's) ends the attempt, so the next attempt gets a
  new, empty directory even when it resumes the executor's session. A halted run
  resumed from a node (`POST /runs/{id}/resume`, after a failed node or at a node you name) restarts
  that node at its first attempt and finds that attempt's directory emptied. The runner makes it
  readable by its own user only. An attempt that finds at its path something that is not a
  directory, or is a link, or, on macOS and Linux, a directory of another user or with a mode other
  than `0700`, fails with `guard.tmpdir_refused` and is retried, in a new directory. It is deleted
  with the run's state, never before, but the operating system's own cleaning of `/tmp` can remove its
  files, or the directory, while an attempt waits a long time for a person: by default macOS deletes
  what has not been touched for three days, systemd's default configuration ages `/tmp` out after ten,
  and a `/tmp` held in memory is empty after a reboot.

- **Calls the runner allows without the guard.** A `Read`, a `Grep` of one file or a `Glob` is allowed
  by the runner's rule, with no model and nothing published, when its target, followed through every
  link, lies inside the working directory, the attempt's whole exchange directory (`in/` and `out/`) or
  a read-only repository's checkout, and neither a part of its path nor a link met on the way matches a
  secret name; a `Grep`'s `glob` must not be able to match a secret name, and a `Glob`'s pattern must
  not be able to list one. A `Write` or `Edit` is allowed by the rule only when its target is exactly
  one of the files the runner requires of the node: an output's `.json` and its body file,
  `questions.json` when the node declares `escalation`, `partner.json` when it declares `advise` (never
  a review's verdict, which the runner writes), and only when no link (on Windows, no junction either)
  is at that path or on its way. The rule only ever allows. Everything else goes to the guard: every
  command, every other write and edit, a `Grep` of a directory, every other tool (the session's own,
  such as its to-do list, included), a read in the temporary directory or outside those places, a read
  through a link that leads outside them, a path that opens with `~` or holds `$`, and every call the
  rule cannot clear. So a policy cannot forbid a read the rule allows: the guard never sees it.
- **The secret names** are a list on the runner, set by its operator (`[guard] secret_patterns` in the
  runner's configuration): by default `.env`, `.env.*`, `*.pem`, `*.key`, `id_rsa*`, `id_ed25519*`,
  `.npmrc`, `.pypirc`, `.netrc` and `.git-credentials`, matched against each part of a path without
  regard to case. An operator's list replaces the default whole. A read of a name on the list always
  goes to the guard, so with the default list the policy decides, for example, whether `.env.example`
  may be read. A file off the list that the executor must not read stays out of those places, or its
  name goes onto the list; a command that reads it reaches the guard either way.
- **The deadline.** One decision may take `[guard] decision_timeout_s` of the runner's configuration
  (30 seconds by default), counted from when the runner receives the call (for the workflow's guard
  behind the runner's own, from the runner's guard's allow), including any wait for a
  free partner slot (a runner process runs `partner_max_concurrent` decisions at once, 3 by default;
  an operator who raises `claude_max_concurrent` or `codex_max_concurrent` raises it with them:
  otherwise calls wait past the deadline on a busy runner and are denied). A decision past it is a
  deny. So is a guard session that fails, a launch that fails in a way a retry may cure (a session
  that ended without its result, say), and an answer that is not the object; the reason says
  which. A call Claude Code cannot ask the runner about is blocked by Claude Code itself, and the
  runner counts it as a deny. A guard that cannot be reached therefore denies every call: it fails
  closed, never open.
- **A guard whose launch fails.** The guard's launch is handled by the kind of its error, as an agent
  session of its harness is. An error that parks a session parks the node (a provider usage limit, a
  lost login, the provider offline, a codex rate limit); an error that can never succeed fails the
  node at once, with no further attempt, with that error's code and a message naming the guard (a
  missing CLI, `claude.not_found` or `codex.not_found`, credentials the runner cannot obtain, a request
  the provider refuses); only an error a retry may cure is a deny the breaker counts (above). When the
  node parks or fails this way, the call is answered as a deny, the turn stops, no `deny` note is sent
  and the breaker counts nothing; after a park the executor's session goes on and the call is decided
  when it is made again.
- **The breaker.** Three denies in a row, or ten in one attempt, stop the executor's turn, and the node
  fails at once with `guard.breaker`, with no further attempt, so the run halts. Its message says how
  many calls were denied in the attempt and how many of them got no decision (a late or failed decision,
  an unreadable answer). Any allow, the rule's included, ends a row. The counts carry across the
  attempt's turns and start again in a new attempt.
- **The witness.** Every call whose result comes back to the executor must have had a decision. A call
  that ran with none (the guard's hook did not fire: a managed Claude Code policy or a broken hook can
  switch hooks off), or a denied call that ran anyway, stops the turn, and the node fails at once with
  `guard.unwitnessed`, naming the call. A call Claude Code refused for its input before asking needs no
  decision.
- **What runs with no decision.** The guard judges the executor's tool calls, nothing else. A
  repository's own Claude Code hooks run with no decision, because Claude Code starts them outside
  the tool calls (measured on Claude Code 2.1.330: a project's `SessionStart` hook ran and the guard
  was never asked). Arming a guard or a watcher on Claude Code also turns back on the hooks that a
  user, project or local `disableAllHooks: true` switched off; a managed policy's setting still wins.
  A skill's inline shell command does not run at all on a guarded executor: the skill keeps its text.
- **Nothing is cached.** A turn that runs again, in a new attempt or a resumed run, has its calls decided
  again. In a dynamic group each member is guarded on its own, with its own deny counts and temporary
  directory.

**On a `codex` executor: detect and stop.** Codex also asks the runner before each tool call, and a call
the guard denies never runs. But codex lets a call run when its hook never answers, so the runner also
reads the executor's stream, and codex's own record of where each command ran, and checks every call
they show against an allow the guard gave. What differs from the above:

- **What it guarantees, and what it does not.** A denied call never runs, whatever the hook's shell
  prints as it starts (a shell start-up file that prints does not undo a deny). A call of the executor's
  own that got past the hook (its client never started), and a shell command that ran in another
  directory than the one the guard judged it in (below), are found only after they ran: the turn is
  stopped and the node fails at once with `guard.unwitnessed`, saying that the call has already run,
  but the call's effect stays. Some are not found: a sub-agent's call that got past its hook
  runs unseen; an allow that no call of the stream used (a sub-agent's allowed call, one that failed to
  start) covers a later call of the same content that got past the hook; a web search or a
  collaboration call that got past its hook is not reliably found; and a command still running when the
  turn ends is not checked for where it ran. On `claude-code`, a hook that cannot answer blocks the call
  instead.
- **Where a command runs.** Codex lets its model pass a `workdir` with a shell command and runs the
  command there, and the guard is shown the command alone, which it judges as run in the working
  directory. So the first turn's section tells the executor never to pass `workdir`, and to put
  `cd <dir> && ` in front of a command instead, which the guard follows. A sub-agent never sees that
  turn, so the runner also passes the rule to codex as the executor's developer instructions, which a
  sub-agent inherits (measured on codex-cli 0.156.1) unless something replaces them for that
  sub-agent, such as the role it is started in setting its own, which a trusted project's codex
  configuration can do; on a guarded Codex executor they replace the developer instructions that
  codex's own configuration (its home or a trusted project) sets. A command that ran in another
  directory anyway fails the node with `guard.unwitnessed`, naming the directory it ran in; so does a
  completed command whose directory codex did not record.
- **Every call goes to the guard.** Codex reads, searches and lists files with commands, and the
  runner's rule allows only Claude Code's own file tools, so every call is a decision of the guard, with
  its latency.
- **A denied call** comes back to the executor as the tool's output, which for a shell command codex
  words `Command blocked by PreToolUse hook: <reason>. Command: <command>` (measured on codex-cli
  0.156.1; the wording differs by tool), the reason opening `Denied by the workflow's guard: `; a line
  the hook's shell prints on stderr as it starts can come before the reason. The first turn's section
  says so. A call the runner could not be asked about is blocked by codex itself: it has no `deny`
  note and does not count toward the breaker.
- **No interactive sessions.** A guarded Codex executor cannot open an interactive terminal session and
  runs every command with its input closed, because input typed into such a session would reach no
  guard. Work that needs one (an interactive database shell, a REPL fed line by line) cannot be done
  there.
- **A web search can fail the node.** On a Codex model whose web search is the provider's own hosted
  tool (with the codex version the runner was checked against, `gpt-5.5` and `gpt-5.4` among them), the
  search reaches no hook, so a guarded executor that
  searches fails its node with `guard.unwitnessed`, the reason naming the hosted search. Run such an
  executor on a model whose search goes through codex's own tool, which the guard decides like any
  call, or have the runner's operator turn Codex's web search off in the runner's codex settings.
- **Hooks run without codex's trust check, outside its sandbox.** Arming a guard or a watcher on a Codex
  executor makes codex run, without asking, every enabled hook whose trust it never recorded or that
  changed since, among them the hooks a repository declares for codex when codex's configuration
  trusts that project, and codex runs a hook outside its sandbox. It also turns codex's hooks feature
  on where the operator's codex settings turned it off, so these hooks run then too, the guard's and
  the watcher's among them. Measured on codex-cli 0.156.1: under
  a `workspace-write` sandbox policy in the runner's codex settings, which a guarded executor keeps, a
  trusted repository's own never-trusted hook ran before each call and wrote outside the sandbox's
  writable roots, where the executor's own write was refused. The runner allows this: the guard judges
  the executor's calls, not the hooks.
- **A sub-agent's calls** reach the guard but never the executor's stream, so the stream cannot show
  them; the guard still decides them.
- **The rest is as on `claude-code`:** the request and its attached files, the deadline, a guard
  whose launch fails, the breaker, the `deny` notes, the private `$TMPDIR` and the first-turn section.
- **On a Windows runner** a guarded Codex node does not run: the runner declines the run before any
  node starts (`dispatch.unresolvable`, naming the platform). The server does not know that rule, so it
  deletes the run, and the task can be placed on the same runner again (`runner-rules.md`).

### The runner's own guard

A runner's operator can give the runner a guard of its own: `[guard] policy_file` in the runner's
configuration names the policy, the guard's prompt, and `harness` (`claude-code` or `codex`), `model`
and `effort` its runtime. Every attempt of every agent node of every run that runner executes then
passes through it, on a `claude-code` or a `codex` executor, whatever the workflow declares: nothing
in a workflow turns it off, and the operator's policy outranks the workflow's. It is the mechanism of
`guard` above with the same limits (the rule, the deadline, the breaker, the witness, the private
`$TMPDIR`, the first-turn section, detect and stop on `codex`), and it is not a sandbox either.

- **With the workflow's guard as well**, a call goes to the runner's guard first and to the workflow's
  only once the runner's has allowed it; a deny from either is the call's answer. Each has its own
  deadline, and the breaker counts the denies of both together. A read the runner's rule allows asks
  neither.
- **The executor is told which guard denied:** `Denied by the runner's guard: <reason>` or `Denied by
  the workflow's guard: <reason>` (on `codex` inside codex's own `Command blocked by PreToolUse hook:`).
  On `claude-code` its first-turn section quotes the lines its node can receive; on `codex` it quotes
  only codex's wrapping. So an executor whose workflow declares no partner can still be told about a
  guard, and be stopped by one.
- **Where it cannot sit.** With its own guard, a runner declines a run with an agent node on
  `cursor-cli` or `opencode`, or on `codex` on a Windows runner, before any node starts
  (`dispatch.unresolvable`): it never runs a node unguarded. A run it takes up again after its operator
  turned the guard on is not checked again at its start: a node that already finished keeps its
  result, and the next node on such a harness fails at once, before any agent starts and with no
  further attempt (`agent.runtime_unsupported`, with the same sentence as the decline), which halts the
  run naming the node. A node on such a harness that was in the middle of an attempt replays the turns
  it recorded and fails the same way at its first executor turn that runs live, before that turn's
  agent starts; an adviser's or a reviewer's step that comes first still runs, and a review loop that
  ends with no live executor turn completes the node. An executor first guarded in the middle of an
  attempt is told about the guard on the first turn it runs guarded.
- **Its tokens** are a share of their own (`runner_guard`, below), counted in the node's totals.
- **`shepherd doctor`** on a runner with its own guard shows a `guard` row, which fails when the
  guard's harness is not installed or its own checks failed. On any runner not on Windows that has
  `codex` and no `curl`, it shows a `curl` warning: the hook clients of a guarded or watched Codex
  executor run `curl`, so without it codex blocks every call of a guarded node and a watcher sees none.

Its policy is a file on the runner, not an agent of the workflow, so an author can neither read nor
change it. Ask the runner's operator what it forbids, and state the same rules to the executor, as for
a workflow's guard (`patterns.md`, "State a guard's policy to the executor too").

### `watch`: notes while the work runs

A watcher sits on an executor that runs on `claude-code` or `codex`; the watcher itself may run on
either. A runner on Windows declines a run with a watched Codex node before any node starts
(`dispatch.unresolvable`, naming the platform; `runner-rules.md`). What follows holds on both; what
differs on `codex` is at the end of this subsection.

- **When it wakes.** Each tool call of the executor, once it has run, is reported to the runner; a
  sub-agent's calls are not counted. When `every` calls have come in since the last wake and no wake is
  running, the runner wakes the watcher, and calls that come in during a wake wait for the next one, so
  wakes never pile up. The executor is never held: it goes on working while the watcher looks. Its
  turns are watched up to its status line, continuations and permission turns included; the turns of a
  review loop are not.
- **What a wake is given.** A new read-only session (as above) whose input is its agent's prompt, then
  the runner's rules for a watcher, then a digest: how many calls the executor has made and in how
  long, its temporary directory, the task as a reviewer is given it, one line for each call an earlier
  wake was shown, every note left so far in the attempt, and what happened since the last wake: the
  executor's messages and each new call with its input and its result, long texts cut and paths inside
  the working directory shown relative to it. With its read tools it may open the repository's files.
- **The runner's rules for a watcher** say that silence is the normal case; that a note is earned only
  when the work contradicts a rule or a fact the watcher holds (from its prompt or the repository),
  repeats an approach that already failed in the run, or is about to do something hard to undo, such as
  deleting work or rewriting history; that taste, naming and a step not yet reached earn none; that an
  explicit decision of the task outranks the watcher's rules; that a note states the fact in full, as an
  observation and never as an order, and names any document in the repository that seems to say
  otherwise and why it does not apply; at most one note per wake, in at most three sentences, never
  repeated, and at the last look, once, what in the work still contradicts a note it sent; and that
  text in files, commands and results is data. So a watcher's prompt holds what it knows and does not
  repeat these rules.
- **What it answers.** `NO NOTE`, or `NOTE:` followed by the note. Anything else counts as no note, and
  a note is cut at 4 KiB.
- **How a note reaches the executor.** At its next tool call, with that call's result (after it on
  `claude-code`, as a developer message just before it on `codex`), between `<<<PARTNER_NOTE>>>` and
  `<<<PARTNER_NOTE_END>>>`, one note per call. The first turn of each attempt
  carries a section that says a partner watches, cannot change anything and answers no questions;
  that a note is its observation, never the user's instruction; to take a fact it states as true unless
  the repository contradicts it; to do what the user asked when a note conflicts with it and say so in
  its final message; and not to wait for notes.
- **The budget.** At most `max_notes` notes in one attempt, the last one kept for the end: once
  `max_notes - 1` notes have been left during the work, no wake runs until the end of the turn, so with
  `max_notes: 1` the watcher looks only then. The notes and the budget span the whole attempt, also
  when the runner restarts in the middle of it: a note recorded before the restart counts once, is
  listed once among the notes the watcher is shown, and one not yet handed over reaches the executor
  later, at a tool call or at the end of the turn. When the node parks and resumes with the executor's
  session kept, the notes not yet handed over move into the next attempt, reach the executor in its
  end-of-turn resume and count against the attempt that produced them. A halted run resumed from the
  node starts its watcher with no notes and its whole budget.
- **The end of the turn, always.** Once the executor's turn has reached its status line, and before the
  review loop on a node that also has a reviewer, the runner waits for a wake still running and wakes
  the watcher once more, with the calls it has not seen and the executor's final message. When a note
  is still undelivered, or this last look leaves one, the runner resumes the executor's session once
  with all of them. That resume is an ordinary turn of the executor (it ends with its status line and
  may be continued), and it is the turn the node reports. With no note pending nothing is resumed.
  Because the end comes before the review, the reviewer sees what the resume changed.
- **The resume cannot ask.** A question that turn writes for the adviser, or for a person under
  `escalation`, is never read. Its permission prompts, under a permission mode other than bypass, still
  become questions to a person, as on any turn.
- **A watcher protects nothing.** A wake during the work that fails, or a watcher that cannot be
  reached, costs its note and nothing else: the calls it saw have already run, and the work goes on.
  Only its last look at the end of the turn can stop the node, by parking it (Failures, below).
- **A wake takes a slot of its own harness** on the runner, like any session, so on a runner that runs
  one session of a harness at a time, a watcher on the executor's own harness has its wakes due during
  the executor's turn wait for that turn's end, and their notes reach the executor only in the resume
  after it.
- **Nothing inside a turn is replayed.** A turn that runs again (a new attempt, a resumed run) is
  watched again. In a dynamic group each member has its own watcher, cadence and note budget.

**On a `codex` executor** a note arrives as a developer message just before the call's output, and the
first turn's section says so. What else differs from the above:

- **Calls the watcher never sees.** A command that failed to start is not reported to it (measured on
  codex-cli 0.156.1). A failed command is shown in the digest as failed, with its exit code.
- **A shell start-up file that prints to standard output loses the note.** Codex runs the hook through
  the account's shell and reads the hook's whole standard output as the answer, so such a line spoils
  it: the note is lost, and the call runs on (measured on codex-cli 0.156.1). The runner still records
  such a note as delivered: it publishes its `note` with `delivery: hook`, counts it against
  `max_notes` and does not hand it over at the end of the turn.
- **Hooks run without codex's trust check.** Arming a watcher makes codex run every enabled hook it has
  not trusted, outside its sandbox, and turns codex's hooks feature on, as arming a guard does (`guard`,
  above, with what was measured). A node with both carries the guard's hook and the watcher's on every
  call.

### A partner's questions

Nobody answers a partner's question while the run is going, and the node never waits for an answer: no
wait appears in `get_run_waits`.

- An adviser's questions are recorded in its `advice` note. When there are any, the executor is told
  that they were recorded for the task's owner and that nobody will answer them during the run, and to
  decide each one itself, keep working toward the task, take the option easiest to undo where the
  options are otherwise equal, and name every such choice in its final message.
- A reviewer's questions reach the executor only as points to leave as they are, and they land in the
  verdict deliverable and in the loop's last `verdict` note.
- A guard asks none: its reason goes to the executor and into its `deny` note.
- A watcher asks none and answers none: the executor is told not to wait for it, and its notes are
  observations the executor weighs alone.

So a workflow that wants a person to decide routes the verdict through a switch to a human gate, or
declares `escalation` so the executor can ask for itself. Ask the executor to list the choices it made
alone in a deliverable: its final message is not one.

### Notes, tokens and failures

- **Notes.** Every note from a partner's own session (its messages, its reads, the model in use)
  carries `partner` with the mode, beside its `kind`. The runner adds:

  | kind | when | message | other fields |
  |---|---|---|---|
  | `ask` | the executor's question is put to the adviser (never for a plan, nor for a question that is not asked) | the question | `partner: advise` |
  | `advice` | after each adviser call | the advice's first line (`(no advice)` when there is none), then `questions:` and one `- <question>` line each; at most 2,000 characters, the questions kept first (the adviser is told a length per question at which three fit; past the bound, `(<n> more question(s) not listed)`) and the advice line cut with `…` | `partner: advise`, `call` (`plan`, or the question's number from 1), `questions` (a count, all of them) |
  | `verdict` | after each review that returned a valid verdict | `round <n>: <ship or revise> · <b> blocker · <m> major · <mi> minor · <q> question(s)` | `partner: review`, `round`, `verdict`, and the counts `blocker`, `major`, `minor`, `questions` |
  | `verdict` | once, when the review loop ends | `<outcome> after <n> review(s)`, then `open findings:` with one `- <severity> <file>:<line>: <claim>` line each, and `questions:` with one `- <point>` line each | `partner: review`, `outcome`, `rounds` |
  | `deny` | after each call a guard denied, and each call Claude Code blocked because the guard's hook gave no answer; never for an allow, nor for a read the runner's rule allowed, nor for a call codex blocked because the runner could not be asked | `<tool> <command or path>: <reason>`, the first part cut at 200 characters and the reason at 500 | `partner: guard`, `guard` (`workflow` or `runner`: the guard that denied; for a block no single guard decided, `runner` when the runner's own guard is on), `tool` (the first part), `reason`, and the counts `in_a_row` and `denied` (the attempt's denies so far, both guards together) |
  | `note` | each note the watcher leaves: when the runner sends it in its answer to the hook of a tool call, or before the resume that carries it; never for a wake that left no note or failed | the note | `partner: watch`, `delivery` (`hook` or `resume`) |

  A guard publishes nothing for an allow. Each decision that starts a guard, the runner's own included,
  and each watcher wake add the notes of their own session (`session`, `say` and the like) with
  `partner: guard` or `partner: watch`.

- **Tokens.** The node's `node_completed` counts every agent of the node together: `token_usage`,
  `cache_read` and `cache_write` include each partner call, a reviewer's second ask, every guard
  decision and every watcher wake included. Beside them, `usage_by_role` splits the same tokens into
  shares, one per role, harness and model: `role` is `executor` for the node's own agent, the partner's
  mode for a partner (`advise`, `review`, `guard`, `watch`) and `runner_guard` for the runner's own
  guard; `harness` is the one the tokens ran on, a partner's own; `model` is the one the harness
  reported for them, so a sub-agent on another model is a share of its own, and it is absent when it
  cannot be named. The shares add up to the three counters. A role that spent nothing has no share (a
  read the rule allowed costs no tokens), a node that spent no tokens sends no `usage_by_role`, and a
  failed node reports neither. With the runner's own guard on, an agent node whose calls it decided
  carries a `runner_guard` share, a node without partners included, and its totals are higher by that
  share.

- **Failures.** An adviser's or a reviewer's session fails like an agent session of its harness, with
  the same codes and under the same rule. What parks an executor parks the node here too (a provider
  usage limit, a lost login, a codex rate limit); when it resumes, the executor's session continues and
  the partner runs again. What can never succeed (a missing CLI, say) fails the node at once, with no
  further attempt. Any other failure spends one of the node's attempts, and the next attempt
  starts over, with a fresh executor session, partners included. An adviser session its harness reports
  failed is `agent.session_failed`, and its text reaches neither the executor nor a note. In a failure's
  detail, `session_id` is the executor's session and `partner_session_id` the partner's. A reviewer that
  runs but returns no valid verdict is not a failure: the loop ends `partner_unavailable` and the node
  completes. A guard's late or failed decision is a deny (`guard`, above), and denies fail the node
  only through the breaker (`guard.breaker`), at once; the witness (`guard.unwitnessed`) also fails it
  at once. A guard whose launch meets an error a retry cannot cure parks the node or fails it at once by
  the kind of the error, as an agent session of its harness would (`guard`, "A guard whose launch
  fails"); one a retry may cure is a deny. Apart from those, a
  guarded attempt fails, and is retried, only when its private temporary directory cannot be made,
  recorded or kept private (`guard.tmpdir_refused`, checked once in each runner process, by the first
  turn of the attempt that actually runs there). A watcher
  never fails the node: a wake whose session fails or cannot start leaves no note, and the work goes
  on. Only its last look at the end of the turn can stop the node: when that session meets what parks
  a session (a provider usage limit, a lost login), the node parks.

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
