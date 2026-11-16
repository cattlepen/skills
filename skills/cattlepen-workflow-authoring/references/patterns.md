# Designing the graph: patterns and anti-patterns

## From a request to a graph

Translate each part of the request into one construct:

| in the request | in the graph |
|---|---|
| a decision ("if the tests pass", "if the owner approves") | a deliverable with a required `string` enum field, and a switch that routes every value |
| a role ("a reviewer reads it") | an agent with one job and its own prompt |
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
