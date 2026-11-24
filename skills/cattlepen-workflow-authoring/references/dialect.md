# The declaration dialect

What the server accepts in a workflow, agent and deliverable document. The runner applies further
rules at dispatch (`runner-rules.md`), and what a node receives at run time is in
`runtime-contract.md`.

Four layers carry version numbers, and they differ: the workflow document is schema 2, agent and
deliverable documents are schema 1, the portable bundle envelope is schema 3, and the editor layout
is schema 2.

## Rules for every document

- **Names** of workflows, agents, deliverables, nodes, reworks, pins and fields match
  `^[a-z][a-z0-9_]*$`, 1 to 64 characters (`doc.invalid-name`, `field.invalid-name`). A node and a
  rework cannot share a name (`name.collision`).
- **Unknown keys are errors.** A misspelt or invented key is `yaml.parse`, and it hides every other
  diagnostic until fixed. The exceptions are `escalation`, whose unknown keys report
  `agent.escalation-unknown-field`, and an agent node's `pair`, whose unknown modes and fields report
  `pair.unknown-mode` and `pair.unknown-field`; a partner's `runtime` is as strict as the node's.
  There is no `description` or `default` on a field.
- **Size.** A document is at most 1 MiB (`doc.too-large`); an inline script is under 128 KiB with no
  NUL character (`inline.script-too-large`, `inline.script-nul`).
- **No YAML anchors, aliases or merge keys** (`&a`, `*a`, `<<:`): the runner refuses them.
- Quote any key or value that YAML could read as a boolean, null or number, for example an enum value
  `yes` or a route key `"1"`.
- A diagnostic is `{code, path, message, severity}`. Only `error` blocks publishing. A save checks
  the parse, the field rules and the graph; switch coverage and pin resolution are checked only by
  `validate_workflow`, publishing, the publication plan and the import preview.

## The workflow document

```yaml
schema_version: 2
id: <the workflow entry id>
name: proposal_review
settings: {max_agent_retries: 1}      # optional
agents:
  strategist: {version: 1}            # pins: <entry name>: {version: N}
deliverables:
  brief: {version: 1}
  proposal: {version: 1}
  review: {version: 1}
inputs: [brief]                        # deliverables a task supplies as files
input_options:                         # optional
  brief: {description: "What to propose for", required: true}
outputs: [proposal]                    # what a run promises
entry: draft
nodes: {...}
reworks: {...}
```

- Required: `schema_version`, `id`, `name`, `entry`, `nodes`. There are no other top-level keys.
- `id` is the workflow entry's id (`doc.id-mismatch`). If `name` differs from the entry's name
  (`doc.name-mismatch`, a warning), publishing renames the entry, or fails with 409 when the name is
  taken.
- `settings`: `max_agent_retries` (retries after an agent's first attempt; absent means 3 attempts,
  `0` means one) and `max_rework_iterations` (the budget of any rework without `max_reworks`). The
  legacy keys `model`, `backend` and `tool_mode` only warn (`settings.legacy-field`).
- **Pins** are written `{version: N}`, N from 1 to 32767 (`pin.invalid-version`). A pin resolves to
  a published version, or to a draft that the workflow's `bindings` select; otherwise
  `pin.unresolved`. Publishing rewrites each pin to `{version, id, sha256}` (the version row's id and
  its document's hash); a draft opened from a published version carries that form, and it is fine to
  keep. An unused pin warns (`pin.unused`).
- `inputs`: every `$input` consume must be listed (`graph.undeclared-input`). An input is required
  unless `input_options.<name>.required` is `false`.
- `outputs`: pinned deliverables the run promises. Declare them here, never on `end` nodes.
- `entry`: the first node; not an `end` or `cancel` (`graph.entry-terminal`).
- `nodes`: at most 2000; `reworks`: at most 200. Every node must be reachable from `entry`
  (`graph.unreachable-node`).

## Nodes

Every node has `type` and may have `label` (display text) and `id` (a UUID). In editor operations a
new node must bring its own `id`; publishing mints one for a node without it.

### `agent`

```yaml
draft:
  type: agent
  agent: strategist                    # a key of agents:
  runtime: {harness: claude-code, model: claude-opus-5-5, effort: high}
  pair: {...}                          # optional: second agents beside this one, one per mode
  consumes: {brief: $input}
  produces: [proposal]
  escalation: {max_rounds: 2, timeout_s: 86400}   # optional: the agent may ask a person
  next: approve                        # required; a node, never a rework
```

- `runtime` is required (`agent.no-harness`). `harness` is `claude-code`, `codex`, `cursor-cli` or
  `opencode`; `model` and `effort` are optional for the first two. See [runtimes](#runtimes).
- `pair` names partners, each with its own agent and runtime: see [Partners](#partners).
- `consumes` and `produces` are optional; an agent with no `consumes` still sees the task's title
  and description.
- `escalation`: `max_rounds` at least 1; `timeout_s`, if given, above 0. Without `timeout_s` a question
  waits forever.
- A legacy node-level `model:` only warns (`agent.legacy-model`) and selects nothing.

### `inline`

```yaml
verify:
  type: inline
  run:
    script: |
      set -u
      ...
  consumes: {change: develop}
  produces: [test_report]
  next: check
```

`run` is exactly one of `{script: <sh text>}` or `{profile: <name>}` (`inline.run-empty`,
`inline.run-ambiguous`). A profile names a command in the target repository's
`.shepherd/profiles.yml`; use it only for repositories that define it. `next` is required.

### `human_gate`

```yaml
approve:
  type: human_gate
  prompt: "Read the proposal among the run's results (node draft). Approve to finish; reject with a note to send it back."
  consumes: {proposal: draft}
  produces: [review]                   # exactly one json deliverable (a runner rule)
  timeout_s: null                      # default 86400; null waits forever; 0 is refused
  next: decide
```

The person answers with the gate's single deliverable. Declare the fields you route on, for example
`decision: {type: string, required: true, enum: [approve, reject]}` and `note: {type: string}`.
`timeout_s: 0` is `gate.invalid-timeout`; when a timeout expires the run halts.

### `switch`

```yaml
decide:
  type: switch
  consumes: {review: approve}          # exactly one entry, not optional
  on: decision                         # a top-level string field with an enum
  routes: {approve: done, reject: revise}   # every enum value, nothing else; a node or a rework
```

A switch has no `next`, `default` or `produces`. Codes: `switch.single-consume`, `switch.empty-routes`,
`switch.unknown-field`, `switch.field-not-enum`, `switch.unknown-route-value`,
`switch.unrouted-value`. The server accepts an optional field; the runner refuses it, so always mark
it `required: true`.

### `dynamic_group`

```yaml
fan_out:
  type: dynamic_group
  for_each: {node: plan, deliverable: work_list, field: items}   # a required array of objects
  limit: 10
  template: {type: agent, agent: worker, runtime: {harness: claude-code}, consumes: {work_item: $member}}
  next: after
```

The template is an agent or inline node with no `next`; it reads its item as `$member`. An agent
template may declare partners like any agent node; its diagnostics read `nodes.<group>.template.pair`.
Know the
limits before using one: later nodes cannot consume the members' results in a published workflow,
each member works in its own copy of the repository whose edits are discarded after the group, a
list longer than `limit` halts the run, and any failed member halts it. For one piece of work per item,
create one task per item instead (`patterns.md`).

### `end` and `cancel`

Only `type`, `id` and `label`. Reaching `end` completes the run; reaching `cancel` halts it ("plan-
directed halt"), which is how a graph says "stop here".

## Consumes

| form | meaning |
|---|---|
| `d: <node>` | required: read deliverable `d` from that node |
| `d: $input` | the task's input file; `d` must be in `inputs` |
| `d: $member` | the current item, inside a `dynamic_group` template only |
| `d: {from: <node>, optional: true}` | the source may not have run on every path; the file is then absent |

- For a required consume, every path from `entry` to the consumer passes the source
  (`graph.binding-not-dominated`); paths through reworks count. Use `optional` when a branch can skip
  the producer. `optional` is refused on a switch and on `$input`
  (`validate.optional-binding-unsupported`).
- `validate_workflow` does not check that the source produces `d`. The editor refuses an action
  that adds such a consume (409 `workflow.edit_conflict`), but a bundle import accepts it, and the
  runner then refuses every run (`validate.consumes-not-produced`). Check it yourself.

## Reworks

```yaml
reworks:
  revise:
    resume_from: draft                 # an agent node, the head of the loop
    feedback: {node: approve, deliverable: review}   # that node produces it
    max_reworks: 2                     # or settings.max_rework_iterations
    on_exhausted: give_up              # any node; the run continues there
```

- Only a switch route enters a rework. `next`, `entry` and `on_exhausted` cannot name one
  (`link.unknown-node`); a rework nothing routes into is `graph.unreachable-rework`.
- The span of a rework is every node reachable from `resume_from` that can reach a switch routing
  into it. Spans of two reworks may not overlap (`rework.overlap`), two reworks may not share a head
  (`rework.shared-head`), each routing switch is downstream of the head
  (`rework.trigger-not-downstream`), and the feedback node is on every path to it
  (`rework.feedback-not-dominated`). The runner adds: the feedback node is inside the span, the span
  is entered only through its head, `on_exhausted` is outside the span, the span holds no
  `dynamic_group`, and the head does not consume the feedback deliverable (`runner-rules.md`).
- `max_reworks: 2` means two passes back; the third route into the rework goes to `on_exhausted`.
  `0` sends the first route straight there. A rework without a budget is `rework.missing-budget`.
- Any other cycle is `graph.cycle`: loops are reworks only.

## Partners

An agent node, top-level or a dynamic group's agent template, may name second agents that work beside
its own agent (the *executor*) inside the same node: one partner per mode, in an optional `pair` map
keyed by the mode. The modes are `advise`, `review`, `guard` and `watch`; being map keys, a second
partner in one mode cannot be written. Which mode to use, and on which model, is in `patterns.md`
("Partners"); what each partner does at run time is in `runtime-contract.md`.

This section was written on 2026-11-22 from unreleased versions of Cattlepen and the runner, brought up
to date with the runner on 2026-11-24, and was checked against no running installation.

```yaml
agents:
  developer: {version: 1}
  conventions_adviser: {version: 1}
  strict_reviewer: {version: 1}
  policy_guard: {version: 1}
  observer: {version: 1}
deliverables:
  task: {version: 1}
  change: {version: 1}
  review_verdict: {version: 1}
nodes:
  develop:
    type: agent
    agent: developer
    runtime: {harness: claude-code, model: claude-sonnet-5-5, effort: high}
    pair:
      advise:
        agent: conventions_adviser
        runtime: {harness: claude-code, model: claude-haiku-5-5}
        max_calls: 4
        plan: true                     # optional: the partner comments on a first-turn plan
      review:
        agent: strict_reviewer
        runtime: {harness: claude-code, model: claude-opus-5-5, effort: high}
        max_rounds: 3
        verdict: review_verdict        # optional: a deliverable of this node's produces
      guard:
        agent: policy_guard
        runtime: {harness: claude-code, model: claude-haiku-5-5}
      watch:
        agent: observer
        runtime: {harness: claude-code, model: claude-haiku-5-5}
        every: 5
        max_notes: 3
    consumes: {task: $input}
    produces: [change, review_verdict]
    next: review_passed
  review_passed:                       # running out of rounds never fails the node: route the verdict
    type: switch
    consumes: {review_verdict: develop}
    on: outcome
    routes:
      ship: done
      minor_only: done
      round_cap: owner                 # a human gate (not shown) that decides what happens next
      needs_person: owner
      partner_unavailable: owner
```

| mode | field | required | meaning |
|---|---|---|---|
| every mode | `agent` | yes | a key of `agents:`, pinned like the node's own agent; the partner runs that agent's prompt |
| every mode | `runtime` | yes | the partner's own `{harness, model, effort}`, under the rules of a node's runtime and judged against the partner's own harness |
| `advise` | `max_calls` | yes | how many questions the executor may ask the partner in one attempt |
| `advise` | `plan` | no (default `false`) | the executor's first turn produces a plan, and the partner comments on it before any change |
| `review` | `max_rounds` | yes | how many times the partner may send the work back in one attempt; running out of rounds never fails the node |
| `review` | `verdict` | no | the name of a deliverable in the node's own `produces`, which receives the loop's final verdict |
| `guard` | none | | takes no other field; its decision deadline and the list of secret names whose reads always reach it are settings of the runner, not of the workflow (`runtime-contract.md`, "Partners") |
| `watch` | `every` | yes | how many of the executor's tool calls pass between two wakes of the partner (at least that many; a sub-agent's calls do not count) |
| `watch` | `max_notes` | yes | how many notes the partner may leave in one attempt; the last one is kept for the end of the turn |

- **Bounds** (`max_calls`, `max_rounds`, `every`, `max_notes`) are integers of at least 1, with no
  upper limit beyond the integer type, as for `escalation.max_rounds`. Absent or `0` is
  `pair.missing-bound`; a negative or non-integer value is `yaml.parse`.
- **Harnesses.** A partner runs on `claude-code` or `codex` (`pair.harness-unsupported` at
  `<node>.pair.<mode>.runtime.harness`). `guard` and `watch` sit only on an executor whose own harness
  is one of those two (`pair.harness-unsupported` at `<node>.pair.<mode>`); `advise` and `review` sit
  on an executor of any harness. A partner's model is optional on both partner harnesses; without one
  the harness's own default applies. An executor and its partner may share a harness and a model;
  for `review` that draws the warning `pair.same-model`, because a reviewer no stronger than the
  executor finds few of its defects.
- **On the runner.** A `guard` and a `watch` run beside an executor on either of the two harnesses.
  On `codex` a guard detects and stops: a call that got past the guard's hook, or a command that ran in
  another directory than the one the guard judged, is found after it ran, and the node fails with its
  effect left in place (`runtime-contract.md`, "Partners"). A runner on Windows declines a run with a
  guarded or watched Codex node (`dispatch.unresolvable`, naming the platform).
- **The partner's agent** is a pin in `agents:` (`link.unknown-agent` at `<node>.pair.<mode>.agent`,
  also when `agent` is missing), and a pin used only by a partner is a used pin (no `pin.unused`). The
  declaration carries no prompt or protocol text: the partner's prompt is its agent's prompt, and how
  the partner and the executor talk is the runner's contract.
- **The verdict deliverable** must be among the node's `produces` (`pair.verdict-not-produced`). The
  runner writes it after the review loop, so declare it as a `format: json` deliverable with exactly
  these fields (its `name` and `id` are yours):

  ```yaml
  fields:
    outcome:
      type: string
      required: true
      enum: [ship, minor_only, round_cap, needs_person, partner_unavailable]
    rounds:
      type: int
      required: true
    findings:
      type: array
      required: true
      items:
        type: object
        fields:
          severity: {type: string, required: true, enum: [blocker, major, minor]}
          origin: {type: string, required: true, enum: [new, unresolved, regression]}
          file: {type: string, required: true}
          line: {type: int}
          claim: {type: string, required: true}
          evidence: {type: string, required: true}
    questions:
      type: array
      required: true
      items:
        type: object
        fields:
          point: {type: string, required: true}
          reading_a: {type: string, required: true}
          reading_b: {type: string, required: true}
  ```

  A switch routes on `outcome`, every one of its five values (what each means: `runtime-contract.md`,
  "Partners"). The server checks only that the node produces the verdict; the runner compares the
  declared fields with these by name, type, `required` (absent reads as `false`), enum values (in any
  order) and the nested fields, and refuses anything else when it compiles the workflow
  (`validate.pair-verdict-unusable` at `<node>.pair.review.verdict`). Its message prints the fields to
  declare on one line. A version with such a verdict publishes, and every run of it is then declined
  (`runner-rules.md`).
- `pair` and `escalation` are independent: a node may declare either, both or neither. A null `pair`
  or a null mode (`review: ~`) reads as absent.
- **Launchability.** A partner's runtime errors (`agent.*` at `<node>.pair.<mode>.runtime.<field>`) and
  every `pair.harness-unsupported` are launch diagnostics, so a version carrying one is not
  launchable and its task's `version_not_launchable` shows the partner's path. The other `pair.*`
  errors refuse publication only.
- A task can override a partner's runtime by node id and mode (`partner_overrides`, beside the node's
  own `exec_overrides`); the partner's agent and bounds cannot be overridden.

Diagnostics are reported at `nodes.<name>.pair...`, or `nodes.<group>.template.pair...` for a
template. A runtime whose harness is missing or unknown draws only its `agent.*` code, never
`pair.harness-unsupported` as well; that also holds for the executor of a `guard` or `watch`. Nor does
a reviewer on the executor's own unknown harness draw `pair.same-model`.

## The agent document

```yaml
schema_version: 1
id: <the agent entry id>
name: strategist
prompt: {sha256: <64 lowercase hex>}
```

`save_authoring` with `prompt=` stores the text and writes the `prompt` line for you. In a bundle the
hash is the SHA-256 of the exact UTF-8 prompt text (the build script computes it). At publish the hash
must name a document stored in the same account (`agent.unknown-prompt`; a malformed one is
`agent.invalid-prompt-sha`). Optional `expects` and `yields` lists are hints for the editor and are
not checked. The prompt reaches the model verbatim; there is no templating.

## The deliverable document

```yaml
schema_version: 1
id: <the deliverable entry id>
name: review
format: json                           # json | markdown | html
fields:
  decision: {type: string, required: true, enum: [approve, reject]}
  note: {type: string}
  score: {type: float}
  tags: {type: array, items: {type: string}}
  owner: {type: object, fields: {name: {type: string}}}
```

- A field has exactly `type`, `required`, `enum`, `items` and `fields`. `type` is `string`, `int`,
  `float`, `bool`, `object` or `array`; `enum` only on strings; `array` needs `items`; `object` needs
  `fields`. Codes: `field.empty-enum`, `field.duplicate-enum-value`, `field.items-on-non-array`,
  `field.fields-on-non-object`.
- `markdown` may add `fields` (the front matter) and `sections`:
  `- {title: Options, level: 2, description: "shown to the writer"}`. Titles are non-empty and unique
  among siblings; `level` is 1 to 6 (default 2) and at most one deeper than the section before
  (`section.empty-title`, `section.duplicate-title`, `section.level-out-of-range`,
  `section.level-skipped`). Sections are allowed on markdown only
  (`deliverable.sections-on-non-markdown`).
- `html` has neither fields nor sections (`deliverable.fields-on-html`).
- A markdown deliverable with neither is free text.
- The format is frozen once a version is published (409 "deliverable format is frozen by a published
  version"): a new format needs a new deliverable.

## Runtimes

Read what the installation offers before choosing:

- `read_api_operation{operation: "GET /catalog/harnesses", request: {}}` lists each harness with
  `efforts`, `requires_model` and `base_models`.
- `read_api_operation{operation: "GET /catalog/models", request: {}}` lists each `{harness, model}`
  the runner keys offer, with `runners` and `online` counts.

| harness | `effort` values | model |
|---|---|---|
| `claude-code` | `low`, `medium`, `high`, `xhigh`, `max` | optional |
| `codex` | `none`, `low`, `medium`, `high`, `xhigh`, `max` | optional |
| `cursor-cli` | none (omit `effort`) | required (`requires_model`) |
| `opencode` | none (omit `effort`) | required, as `provider/model` |

Use the `model` value exactly as `GET /catalog/models` spells it (for example `claude-sonnet-5-5`),
not the `base_models` names of the harness catalog. The server checks a model's shape only (1 to 128
characters, no whitespace); whether a runner offers
it shows up as the task's `launch_problem`. A node without a model runs the runner's default model for
that harness. Codes: `agent.unknown-harness`, `agent.unknown-effort`, `agent.invalid-model`,
`agent.effort-without-harness`. A harness that requires a model and has none passes validation and
fails at launch (`model_required`). A partner's `runtime` follows the same rules on its own harness,
which is `claude-code` or `codex` ([Partners](#partners)).

## Common server diagnostics

| code | fix |
|---|---|
| `yaml.parse` | bad YAML, a wrong type or an unknown key; the message names the expected keys |
| `doc.id-mismatch` | the document's `id` must be the entry id |
| `doc.empty-draft` | the version was never saved |
| `link.unknown-node`, `link.unknown-agent`, `link.unknown-deliverable` | a dangling name: a `next` to a rework, an unpinned agent or deliverable, a typo |
| `node.duplicate-id` | two nodes share an `id` (a copy and paste) |
| `graph.undeclared-input` | add the deliverable to `inputs` |
| `graph.binding-not-dominated` | the source is not on every path; move the consumer or use `optional` |
| `graph.cycle` | turn the loop into a rework |
| `graph.unreachable-node`, `graph.unreachable-rework` | wire it in or delete it |
| `graph.unconsumed-input`, `graph.unconsumed-deliverable`, `graph.no-success-path`, `pin.unused` | warnings: dead weight, or a graph that cannot reach `end` |
| `agent.no-harness` | add `runtime: {harness: ...}`; at `<node>.pair.<mode>.runtime.harness`, to that partner |
| `agent.unknown-harness`, `agent.unknown-effort`, `agent.invalid-model`, `agent.effort-without-harness` at a `pair` path | fix that partner's `runtime` against its own harness's scale (Runtimes) |
| `link.unknown-agent` at `<node>.pair.<mode>.agent` | pin the partner's agent in `agents:`, or give the partner an `agent` |
| `pair.unknown-mode` | a key of `pair` that is not `advise`, `review`, `guard` or `watch`: fix the spelling |
| `pair.unknown-field` | a field the mode does not take (for example `max_calls` under `review`): move it to its mode or delete it |
| `pair.missing-bound` | add the mode's bound, at least 1: `max_calls` (advise), `max_rounds` (review), `every` and `max_notes` (watch) |
| `pair.harness-unsupported` | at `...runtime.harness`: put the partner on `claude-code` or `codex`; at `<node>.pair.<mode>`: a `guard` or `watch` needs the node itself on one of those two |
| `pair.verdict-not-produced` | add the `verdict` deliverable to the node's `produces`, or name one it produces |
| `pair.same-model` | warning: the reviewer runs on the executor's harness and model; give it a model at least as strong as the executor's and a different one (`patterns.md`) |
| `pin.unresolved` | publish the dependency, or select its draft with a binding |
| `switch.unrouted-value` | route every enum value |
| `rework.*` | see Reworks above |

## What publishing changes

Publishing a workflow mints an `id` for every node, template and rework that lacks one, rewrites each
pin to `{version, id, sha256}`, writes `timeout_s` on every gate (86400 when omitted), drops legacy
keys and an empty or null `pair`, and re-emits the YAML with its own key order (a node's `pair` right
after its `runtime`) and without comments. Agent and deliverable
documents are stored as saved. A published version never changes: the next change is a new version
(`create_version`), seeded from this text, which keeps the node ids.
