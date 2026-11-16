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
  diagnostic until fixed. The exception is `escalation`, whose unknown keys report
  `agent.escalation-unknown-field`. There is no `description` or `default` on a field.
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
  consumes: {brief: $input}
  produces: [proposal]
  escalation: {max_rounds: 2, timeout_s: 86400}   # optional: the agent may ask a person
  next: approve                        # required; a node, never a rework
```

- `runtime` is required (`agent.no-harness`). `harness` is `claude-code`, `codex`, `cursor-cli` or
  `opencode`; `model` and `effort` are optional for the first two. See [runtimes](#runtimes).
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

The template is an agent or inline node with no `next`; it reads its item as `$member`. Know the
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
fails at launch (`model_required`).

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
| `agent.no-harness` | add `runtime: {harness: ...}` |
| `pin.unresolved` | publish the dependency, or select its draft with a binding |
| `switch.unrouted-value` | route every enum value |
| `rework.*` | see Reworks above |

## What publishing changes

Publishing a workflow mints an `id` for every node, template and rework that lacks one, rewrites each
pin to `{version, id, sha256}`, writes `timeout_s` on every gate (86400 when omitted), drops legacy
keys, and re-emits the YAML with its own key order and without comments. Agent and deliverable
documents are stored as saved. A published version never changes: the next change is a new version
(`create_version`), seeded from this text, which keeps the node ids.
