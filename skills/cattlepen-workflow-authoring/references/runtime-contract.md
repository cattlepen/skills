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
  consume the review itself.
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
