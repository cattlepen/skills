# Designing the graph: patterns and anti-patterns

## From a request to a graph

Translate each part of the request into one construct:

| in the request | in the graph |
|---|---|
| a decision ("if the tests pass", "if the owner approves") | a deliverable with a required `string` enum field, and a switch that routes every value |
| a role ("a reviewer reads it") | an agent with one job and its own prompt |
| a second agent inside one step ("review its work before it moves on", "it must follow our conventions", "never let it force-push") | a partner in that agent node's `pair`, with its own prompt and model ([Partners](#partners-a-second-agent-inside-a-node)) |
| a deterministic step (run tests, commit, push, fetch, count) | an inline node |
| an approval | a human gate whose prompt says where the evidence is and what each answer does |
| "try again" | a rework with a head, a feedback deliverable, a budget and an exhaustion target |
| "stop" | a `cancel` node (the run ends as halted) |

The design is complete when every switch names its field and every enum value has a target, every
rework names its head, feedback and `on_exhausted`, and every consumed deliverable is produced on
every path to its consumer. Show this node list to the user before writing YAML when the request
leaves room for interpretation.

## Patterns

**Every decision is an enum field a switch reads.** `verdict: ship | rework`, `result: pass | fail`,
`decision: approve | reject`, always `required: true`. The prompt says when to choose each value. The
agent's status line and an inline script's exit code are never routable.

**Human approval loop.** An agent drafts, a gate asks the owner, a switch routes the answer, and a
reject goes back to the agent with the owner's note:

```yaml
nodes:
  approve:
    type: human_gate
    prompt: "Read the proposal among the run's results (node draft). Approve to finish. Reject with a note: it goes back to the writer."
    consumes: {proposal: draft}
    produces: [review]            # json: decision (required enum) and note (optional string)
    timeout_s: null
    next: decide
  decide:
    type: switch
    consumes: {review: approve}
    on: decision
    routes: {approve: done, reject: revise}
reworks:
  revise: {resume_from: draft, feedback: {node: approve, deliverable: review}, max_reworks: 2, on_exhausted: give_up}
```

The gate is the feedback node, so the note reaches the writer on the next pass. The full workflow is
`examples/proposal_review`.

**Machine check, then human check.** An automated check (an inline test, or an agent tester) writes
`result`; only `pass` reaches the gate, `fail` goes straight back into the rework. The person sees only
work that already passes, with evidence they can open. A file left in the working tree is invisible
to them: what they must see is a deliverable (a report, an html page).

**Several reasons to send work back, one rework.** Route each switch that can send work back (the
tests' `fail`, the reviewer's `rework`, the owner's `reject`) into the same rework, and declare the
most common reason as `feedback`. The head also receives the deliverable of whichever switch sent it
back. The feedback node must still lie on every path to each of those switches. See
`examples/code_change`.

**Structure is a section, judgement is a check.** A declared markdown section is enforced by the
runner on the agent's output itself: a body without it is refused and the agent retries, told why.
So "the notes must have a `## Changes` heading" is a `sections` entry on the deliverable, not an
inline check plus a rework, which would never fire. Keep checks and reworks for what needs running
code or judgement (tests pass, the reviewer approves, a length or a count).

**Inline verdict step.** A script that always writes the verdict, on both outcomes, and a switch that
decides (the script is in `runtime-contract.md`). For a check several workflows share, or one that
needs a time limit, a repository profile (`run: {profile: verify}`) avoids copies drifting apart, but
a run is refused in any repository that does not define it; a workflow meant for repositories you do
not control uses a `script` that writes `fail` with a clear summary when the check is missing.

**Side effects live in inline nodes.** Agents edit files; inline nodes commit, push, open pull
requests, upload. Tell agents not to commit or push. Make each side effect idempotent (look for an
existing pull request first) and let it fail by writing no output, with the reason on stderr. A
commit step stages only the change: tracked edits (`git add -u`) plus the new files the developing
agent lists in its deliverable, never `git add -A`, which also commits whatever the run's tests left
in the tree (`runtime-contract.md`).

**A cheap check before expensive work.** Put an inline check first when agents depend on something
that may be missing (a file in the repository, a complete input) and route on its `result`. A
one-line check saves an agent from spending its whole turn discovering the gap.

**An exhausted loop goes to a person, not to `end`.** Point `on_exhausted` at a gate whose switch can
accept the work anyway or stop. An exhausted loop routed to `end` reports `completed` for failed work.
An outside path such as "accept anyway" needs its own nodes: it may not route into the middle of the
loop (`runner-rules.md`).

**A strong model for judgement, a cheaper one for volume.** `runtime` is per node: planning and review
on a stronger model with higher effort, implementation on a faster one. One agent document can serve
several nodes with different runtimes and outputs; its prompt can say that the node's output decides
which stage it is in.

**The model reads intent, a script checks it.** An agent turns free-form task text into a small
deliverable of parameters (enums with a stated default); the next inline node validates them and
computes derived values once, so later nodes read them from one place.

**Ask instead of guessing.** `escalation: {max_rounds: 3}` lets an agent stop and ask the owner. Say in
its prompt that a question the repository can answer is a lookup, and that an empty question list
fails the node.

**Evidence a person can judge.** A tester uploads screenshots with the upload command the runner gives
it and links them in a markdown report. A prototype or a build can itself be an html deliverable,
shown in a sandboxed frame, so everything it needs is inline.

**One task per item.** When a workflow discovers several pieces of work, have it output them (ready-to-
paste task titles, for example) and run each as its own task. Each item then gets its own gates and
reworks. A `dynamic_group` cannot replace this: later nodes cannot consume its members' results and
its members' file edits are discarded.

**One task per repository that changes.** A run changes only its task's `repo` and can read the
project's other repositories. Work spanning two repositories is two tasks; each reads the other. A
read-only repository is read at its base branch, so a change the second task depends on must be
merged there before its run starts. The prompt says what to read in the other repository and why,
not where it is.

**Isolate shared host resources.** Agents on one runner share caches, simulators and CPU. Key every
cache path on something unique to the run (`run_id` from `run.json`).

**Optional input for a skipped path.** When a branch can skip a producer, consume its output as
`{from: <node>, optional: true}`; the consumer is told the input was not provided.

**Grow a graph one exercised step at a time.** Run the workflow after each addition. An irreversible
tail (push, release) added without ever running it fails where it costs most.

## Partners: a second agent inside a node

A partner (`dialect.md`, "Partners") is a second agent with its own prompt and its own runtime, working
beside a node's agent, the executor, inside that node: an adviser the executor consults (`advise`), a
reviewer that can send the work back (`review`), a guard that judges the executor's actions (`guard`),
or a watcher that leaves it notes (`watch`). Each one costs calls and time, so add one for a job the
executor cannot do alone, and choose its model with the points below. The figures were measured on
small tasks; read them as the direction of an effect, not as a benchmark.

**A partner is worth what its prompt knows.** A partner changes the outcome when its prompt holds what
the executor cannot read: the team's conventions, its policies, facts about the environment. With one
partner model and two prompts, on small tasks, an executor that was confident but wrong ended right in
22 of 24 runs when the partner's prompt held the team's rule, and in 0 of 18 when the partner knew only
the repository. Without the rule the partner named both conventions and endorsed the outdated one the
README described, and a stronger model alone with the same repository chose as the executor did. So the
project's rules go into the partner's prompt. The starter partners in `examples/paired_change` are
templates: each has one section marked `FILL IN BEFORE PUBLISHING` for those rules, and that section is
the part that does the work.

**Review with a model at least as strong as the executor.** The executor fixes whatever it is sent, so
the reviewer is the only filter, and a loop's own fixes can break behaviour the review never looked at.
On small tasks, reviewers stronger than the executor surfaced every seeded defect in the first round; a
reviewer as weak as the executor found 2 of 9 and cost about as much as a stronger one, and over four
rounds the executor fixed all 139 findings it was sent. The server warns (`pair.same-model`) when the
reviewer runs on the executor's own harness and model.

**State the rules a review enforces to the executor too.** Only `blocker` and `major` findings go back
to the executor, and the runner's rules make a finding one of those only when the change is broken,
breaks what worked before, or contradicts a sentence of the task (the executor's prompt as written and
the task's title and description). A finding that rests on a rule only the reviewer was told is a
`minor` finding, attached to the result and never sent to the executor. So a rule the review is meant
to enforce must also be stated to the executor, in its prompt or in the task; the reviewer's prompt
keeps it too, with what the reviewer needs to recognise a breach (`runtime-contract.md`, "Partners").

**State a guard's policy to the executor too.** A guard stops a forbidden call; it does not teach the
executor the policy. An executor that was not told the policy finds it one deny at a time, and three
denies in a row, or ten in one attempt, fail the node at once with no further attempt. So the rules a
guard enforces also go into the executor's prompt or the task, and the guard's prompt keeps them with
what the guard needs to recognise a breach. When a denied action can leave the task undone, give the
executor a field for it in a deliverable a switch routes: the status word `blocked` it is told to end
with is not routable.

**A pair does not make a weak executor a strong one.** On small tasks, a weak executor with a strong
reviewer still ended with seeded defects in 7 of 18 loops, where the strong executor alone left none in
34 runs, and the pair cost 1.0 to 3.3 times as much. Choose the executor for the work; a partner pays on
top of a capable one: an adviser that knows what the executor cannot, a reviewer that finds what it
missed, a guard on its actions.

**Choose an adviser for what it knows, not for its strength.** Relaying a rule written in its prompt
does not take a strong model: on small tasks a cheaper model relayed a known rule as well as a stronger
one, for much less. Where the adviser has to reason from the repository instead, that was not measured.

**One partner per mistake.** A plan check (`advise` with `plan: true`) and a review on one node that
guard against the same mistake doubled the partner calls and caught nothing more. Give each partner a
mistake of its own to catch, or keep only one.

**A partner's questions go to the result, not to a person.** Nobody answers a partner's question while
the run is going, and the node never waits for an answer: the executor makes each open choice itself and
names it in its result, so ask for those choices in a deliverable (`open_choices` in
`examples/paired_change`). The cost is real: on small tasks, with a person's answer 6 of 6 runs passed,
without one 0 of 8. When a person must decide, route the review's verdict (the deliverable its `verdict`
names) through a switch to a human gate, or declare `escalation` so the executor can ask for itself
("Ask instead of guessing" above).

**A watcher relays what it knows while the work runs.** A watcher is woken every `every` tool calls of
the executor and may leave a note, at most `max_notes` in one attempt, the last kept for the end of the
turn. It pays when it knows facts or conventions the executor cannot read anywhere, and it is an
addition to a reviewer, never a replacement: it does not prevent a wrong choice. It watches only an
executor on `claude-code`, and only the work before a review: a reviewer's rounds are not watched.
Measured on small tasks over 83 executor runs:

- No note came before a wrong choice was written (0 of 32). What the watcher changed came through its
  last look at the end of the turn: 4 of 32 runs passed without that step, 26 of 32 with it.
- A weak executor acted on notes the repository did not seem to contradict (7 of 7) and mostly declined
  notes a README seemed to contradict (it adopted 3 of 28). A note that goes against a document has to
  say why the document does not apply; the starter watcher's prompt asks for that.
- A stuck executor got its hint before giving up in 3 of 4 runs.
- On a task whose wrong first step later work builds on, the weak executor ended 0 of 2 with a watcher
  and 2 of 2 with a review at the end, and the review cost less.
- A watcher on a stronger model beside a cheap executor cost about as much as the executor's whole run,
  and a small watcher repeated itself until its notes were spent. Keep `max_notes` small, and tell the
  watcher to stay silent unless it has something the executor cannot read.

### A guard is not a sandbox

A guard is not a sandbox: it is a gate on the agent's own actions. It judges each tool call the agent
chooses that the runner's own rule has not already allowed, from the call's text, the repository files
the runner attaches and, with read tools, the files it opens inside the working tree before its
deadline. It does not see code a command loads from anywhere else, such as an interpreter's own
packages, a dependency, or something fetched at run time: on small tasks a harmful start-up file
outside the tree was allowed in all 36 trials, in every configuration.

- A small model judges the command line; following what a script runs takes a stronger model with read
  tools.
- A claim inside a command that the guard cannot check (that it is safe, approved, only a test) can turn
  its deny into an allow. The starter guard's prompt tells it to judge what a command does, not what it
  says about itself.
- It held on clear-cut policy, under the runner's rules, which put the policy above the task: on small
  tasks, force-push and deletion outside the working tree were denied in 30 of 30 trials each, and 6 of
  552 ordinary requests were denied. Write the policy as clear rules about what an action does.
- Each decision adds latency to the tool call it judges, even with a small model; a read the runner's
  rule allows adds none.
- On a Claude Code executor it cannot forbid a read the runner allows. A read, search or listing with
  the agent's own file tools inside the working tree, the agent's inputs or a read-only repository is
  allowed by the runner before the guard is asked, unless a part of its path matches one of the
  runner's secret names: a list the runner's operator sets, by default `.env`, `.env.*`, `*.pem`,
  `*.key`, SSH key files and the usual credential files (`.npmrc`, `.pypirc`, `.netrc`,
  `.git-credentials`). Keep a file that must not be read out of those places, or have its name put on
  that list (`runtime-contract.md`, "Partners"). A Codex executor reads with commands, so every read
  reaches the guard.
- On a Claude Code executor it fails closed. A decision that comes too late, a guard session that fails
  and a guard that cannot be reached all deny the call, and three denies in a row, or ten in one
  attempt, fail the node at once (`guard.breaker`). A call that ran without a decision, because
  something on the machine switched Claude Code's hooks off, fails it too (`guard.unwitnessed`).
- On a Codex executor it detects and stops. A call the guard denies never runs, and the same deadline
  and breaker apply, but codex lets a call run when the guard's hook gives no answer it can read. The
  runner then finds the call in the executor's stream after it ran, stops the turn and fails the node
  (`guard.unwitnessed`); the call's effect stays. A guarded Codex executor also has no interactive
  terminal session, and on a model whose web search is the provider's hosted tool a search fails the
  node. A runner on Windows declines a run with a guarded Codex node, naming the platform.
- It never widens what the runner allows: on Claude Code, a call the guard allows still meets the
  runner's own permissions.

The runner's operator can add a guard of the runner's own, which judges every agent node of every run
on that runner, whatever the workflow says, before the workflow's guard: a deny from either stops the
call, and the operator's policy outranks the workflow's. It has the same limits and is not a sandbox
either. A runner with it declines a run with a node on a harness it cannot guard rather than run that
node unguarded (`runtime-contract.md`, "The runner's own guard").

Keep real isolation (accounts, permissions, networks) wherever an action could do harm, and use a guard
for the agent's own choices on top of it.

## Anti-patterns

| anti-pattern | what goes wrong |
|---|---|
| an agent node without `runtime` | the version is not launchable (`version_not_launchable`) |
| an inline node without `produces` used as a check | it can never stop anything: the exit code is ignored |
| an inline script calling a repository script that does not exist | the script writes no output and the run halts at that node |
| a markdown or html output without its `<name>.json` | the output is refused (`carrier.missing_output`); from an inline node that halts the run |
| a `cancel` node labelled "needs intervention" | nobody can intervene in a halted run; use a gate |
| a gate prompt promising an effect the graph lacks | the person approves and nothing happens |
| an exhausted loop or a "hold" routed to `end` | failed work reports as completed |
| reading an optional gate field as a string | a reject without a note gives `null`, and the next script fails |
| a test-summary parser that knows one framework | "0 tests ran" counts as a pass |
| `git add -A` in a commit step | the pull request carries build output the tests left behind, such as `__pycache__/*.pyc` |
| machine-specific paths in scripts or prompts | the workflow works on one machine only; use the working directory and `run.json` |
| expecting a non-head node in a loop to receive feedback | it never does; consume the review explicitly |
| the same instructions pasted into several prompts | the copies drift apart; one agent document can serve several nodes |
| references to a deleted node left in prompts | agents look for a step that no longer exists |
| a recovery instruction left in the task description | after the run the task no longer describes the work |
| a starter partner published as it comes | it knows only the repository, and endorses an outdated convention as confidently as the current one; fill its marked section first |
| a reviewer weaker than the executor, or on its harness and model | it finds few defects, and the executor fixes whatever it is sent; `pair.same-model` warns on the same model |
| a project rule written only in the reviewer's prompt, expected to be enforced | a finding that rests on a rule only the reviewer was told is a `minor` finding, attached to the result and never sent to the executor; state the rule to the executor too, in its prompt or in the task |
| a strong partner meant to let a weak executor do a strong one's work | the pair still leaves defects the strong executor alone does not, at up to several times the cost |
| a design that expects someone to answer a partner during the run | nobody does and the node does not wait: the executor decides alone; route the verdict to a gate, or declare `escalation` |
| a guard used as a sandbox | it never sees what a command loads from outside the working tree; keep real isolation |
| a guard's policy the executor was not told | the executor finds the policy one deny at a time, and three denies in a row or ten in one attempt fail the node (`guard.breaker`); state the rules to the executor too |
| a guard's policy that forbids reading a file inside the working tree | on a Claude Code executor the runner allows a read of it with the agent's file tools without asking the guard, unless a part of its path matches the runner's list of secret names; keep the file out of the tree, or have its name listed |
| a plan check and a review that guard against the same mistake | twice the partner calls, and nothing more caught |
| a review `verdict` nobody routes | running out of rounds never fails the node, so without a switch on the verdict the run carries on as if the review had passed |
| a watcher used instead of a reviewer | its notes do not stop a wrong choice; a review at the end caught what a watcher missed, for less |
| a watcher expected to stop a wrong choice in time | its notes came after the choice was written; what it changed came through its last look at the end of the turn |
