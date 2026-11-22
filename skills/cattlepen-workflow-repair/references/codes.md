# Code reference

Every code below is copied from the server's or the runner's source, or from a reply on a test installation.
**M** marks a code seen in a reply there; the others are read from source. Messages are templates: `<x>` is
filled in. Use this page to look a code up; the symptom pages say what to do about the common ones.

## 1. Server diagnostics (save, `validate_workflow`, publish, publication plan)

Shape: `{code, path, message, severity}`; `severity` is `error` (blocks publishing) or `warning`.
When they run:

- **On save** (`save_authoring`, `apply_workflow_operations`): parsing and field rules, then graph rules.
  No pin lookup and no checks across documents, which is why an apply reply can say `[]` on a workflow that
  does not validate.
- **On validate, publish and plan:** all of the above plus pin resolution, then the checks that need the
  pinned documents (switch fields, bundle completeness). With draft bindings, validate checks the whole set
  a plan would publish, including the dependencies' own diagnostics.
- Each stage runs only when the earlier one has no error, so `pin.unresolved` and `switch.*` never appear
  next to structural errors.

### Any document

| code | sev | message | |
|---|---|---|---|
| `yaml.parse` | E | the parser's text: unknown key (it lists the allowed ones), wrong type, unknown variant, missing field; or `unknown node type "<t>" (expected agent, dynamic_group, inline, switch, human_gate, end or cancel)` | M |
| `doc.too-large` | E | `document is <n> bytes; the limit is 1048576 bytes` | |
| `doc.unsupported-schema-version` | E | `unsupported workflow schema_version <n> (supported: 2)`; agents and deliverables: `(supported: 1)` | |
| `doc.invalid-name` | E | `invalid workflow name "<n>"` / `invalid name "<k>"` (names are lowercase letters, digits and `_`, starting with a letter, at most 64 characters) | |
| `doc.id-mismatch` | E | `document id <doc> does not match <workflow\|agent\|deliverable> <id>` | |
| `doc.name-mismatch` | W | `document name "<n>" differs from <kind> name "<row>"; publishing adopts it` | |
| `doc.empty-draft` | E | `the draft has no declaration` | |

### Workflow: fields and links

| code | sev | message |
|---|---|---|
| `name.collision` | E | `"<k>" names both a node and a rework` |
| `pin.invalid-version` | E | `"<k>" pins version <v> (versions run from 1 to 32767)` |
| `node.duplicate-id` | E | `id <uuid> is already used by node "<prev>"` |
| `node.missing-id` | W | `node has no id yet` (the editor refuses a new node without an id; an imported draft may lack them, and publishing mints the missing ones) |
| `link.unknown-node` | E | `entry names unknown node "<e>"`, `consumes from unknown node "<src>"`, `next names unknown node "<n>"`, `route targets unknown node or rework "<t>"`, `resume_from names unknown node "<n>"`, `on_exhausted names unknown node "<n>"`, `feedback names unknown node "<n>"` |
| `link.unknown-deliverable` | E | `"<d>" is not a pinned deliverable` (in `inputs`, `outputs`, `consumes`, `produces`, rework feedback) |
| `link.unknown-agent` | E | `"<a>" is not a pinned agent` |
| `input.duplicate` | E | `input names must be unique` |
| `input.undeclared-options` | E | `options must name a declared input` |
| `graph.undeclared-input` | E | `consumes "<d>" from $input, which the workflow does not declare among its inputs` |
| `graph.unconsumed-input` | W | `input "<d>" is consumed by no node` |
| `validate.optional-binding-unsupported` | E | `optional bindings are not supported for switch selectors or $input` |
| `pin.unused` | W | `agent "<k>" is pinned but never used` / `deliverable "<k>" is pinned but never used` (M) |
| `settings.legacy-field` | W | `settings.<f> is no longer used: each agent node names its own runtime, and the field is dropped on the next save` |

### Workflow: node rules

| code | sev | message |
|---|---|---|
| `agent.no-harness` | E | `agent node names no runtime harness` (M) |
| `agent.unknown-harness` | E | `unknown harness "<h>" (expected one of: claude-code, codex, cursor-cli, opencode)` |
| `agent.unknown-effort` | E | `effort "<e>" is not on the <harness> scale (<efforts>)` |
| `agent.effort-without-harness` | E | `` runtime sets `<field>` but names no harness to apply it to `` |
| `agent.invalid-model` | E | `model is 1 to 128 characters with no whitespace or control characters` |
| `agent.legacy-model` | W | `` the node-level `model` is no longer used: set `runtime` instead; the field is dropped on the next save `` |
| `agent.escalation-missing-max-rounds` | E | `` escalation declares no `max_rounds` `` |
| `agent.escalation-invalid-max-rounds` | E | `` escalation `max_rounds` is 0; a round budget starts at 1 `` |
| `agent.escalation-invalid-timeout` | E | `` escalation `timeout_s` is <t>; it is a finite number above zero `` |
| `agent.escalation-unknown-field` | E | `` unknown escalation field "<f>" (expected `max_rounds` or `timeout_s`) `` |
| `inline.run-empty` | E | `` inline run declares neither `profile` nor `script` `` |
| `inline.run-ambiguous` | E | `` inline run declares both `profile` and `script`; it carries exactly one `` |
| `inline.script-nul` | E | `script text carries an embedded NUL (U+0000), which cannot ride an argv argument` |
| `inline.script-too-large` | E | `script text is <n> bytes; must be under 131072 bytes (the per-argument argv limit)` |
| `gate.invalid-timeout` | E | `` human gate `timeout_s` is 0; a wait starts at 1 second, and `null` waits indefinitely `` |
| `switch.single-consume` | E | `a switch consumes exactly one deliverable` |
| `switch.empty-routes` | E | `a switch declares at least one route` |
| `dynamic-group.invalid-limit` | E | `limit must be positive` |
| `dynamic-group.invalid-source` | E | `for_each must name a node and a deliverable it produces` |
| `dynamic-group.invalid-template` | E | `template must be an agent, inline or human_gate node` (the runner then refuses a `human_gate` template, see section 5) |
| `dynamic-group.template-control` | E | `template must not carry next` |
| `rework.resume-not-agent` | E | `resume_from must name an agent node, "<n>" is <type>` |
| `rework.feedback-not-produced` | E | `node "<n>" does not produce "<d>"` |
| `rework.missing-budget` | E | `rework has no max_reworks and settings.max_rework_iterations is not set` |

### Workflow: partners (`pair` on an agent node)

Reported at `nodes.<name>.pair.<mode>...`, or `nodes.<group>.template.pair.<mode>...` for a dynamic
group's agent template. The fix for each is in the authoring skill's `references/dialect.md`, "Common
server diagnostics".

| code | sev | path | message |
|---|---|---|---|
| `pair.unknown-mode` | E | `<node>.pair.<key>` | ``unknown partner mode "<key>" (expected `advise`, `review`, `guard` or `watch`)`` |
| `pair.unknown-field` | E | `<node>.pair.<mode>.<field>` | ``a `<mode>` partner takes no field "<field>"`` |
| `pair.missing-bound` | E | `<node>.pair.<mode>` (absent), `<node>.pair.<mode>.<field>` (0) | ``the `<mode>` partner declares no `<field>` `` / ``the `<mode>` partner's `<field>` is 0; a bound starts at 1`` |
| `pair.harness-unsupported` | E | `<node>.pair.<mode>.runtime.harness` | ``the `<mode>` partner runs on <harness>; a partner runs on claude-code or codex`` |
| `pair.harness-unsupported` | E | `<node>.pair.<mode>` | ``a `<mode>` partner sits only on an executor running on claude-code or codex; this node runs on <harness>`` (`guard` and `watch` only) |
| `pair.verdict-not-produced` | E | `<node>.pair.review.verdict` | ``the review verdict "<d>" is not among the node's `produces` `` |
| `pair.same-model` | W | `<node>.pair.review.runtime` | `the review partner runs on the executor's own harness and model; a reviewer no stronger than the executor finds few of its defects` (also when both name no model) |

A partner also draws codes of the node rules, at its own path: `link.unknown-agent` at
`<node>.pair.<mode>.agent` (its agent is not pinned, or it names none), and `agent.no-harness`
(``the `<mode>` partner names no runtime harness``), `agent.effort-without-harness`,
`agent.unknown-harness`, `agent.unknown-effort` and `agent.invalid-model` at
`<node>.pair.<mode>.runtime.<field>`, judged against the partner's own harness. A runtime whose harness
is missing or unknown draws only its `agent.*` code, never `pair.harness-unsupported` as well, and a
reviewer on the executor's own unknown harness draws no `pair.same-model`. A
partner's type error (a negative or non-integer bound, a mode that is not a mapping, an unknown key in
its `runtime`) is `yaml.parse`.

### Workflow: graph rules

| code | sev | message |
|---|---|---|
| `graph.entry-terminal` | E | `entry "<e>" is a terminal node` |
| `graph.unreachable-node` | E | `node "<k>" is not reachable from entry` (M) |
| `graph.unreachable-rework` | E | `no reachable switch routes into rework "<k>"` (M) |
| `graph.no-success-path` | W | `no end node is reachable — every run can only cancel or halt` |
| `graph.cycle` | E | `cycle through "<t>" — loops are only expressible as reworks` |
| `graph.unconsumed-deliverable` | W | `"<d>" produced by "<p>" is never consumed` (M) |
| `graph.binding-not-dominated` | E | `"<c>" cannot consume from itself` / `"<c>" is reachable without "<src>" having run — the binding is not guaranteed on every path` |
| `graph.unproduced-output` | E | `output "<d>" is produced by no node` |
| `graph.output-not-dominated` | E | `end node "<end>" is reachable without "<d>" having been produced — the output is not promised on every success path` |
| `rework.shared-head` | E | `reworks "<a>" and "<b>" share resume_from "<n>"` |
| `rework.trigger-not-downstream` | E | `switch "<s>" routes into "<k>" but is not reachable from resume_from "<n>"` |
| `rework.feedback-not-dominated` | E | `trigger "<s>" is reachable without feedback producer "<n>" having run` |
| `rework.overlap` | E | `reworks "<a>" and "<b>" overlap at node "<n>" — loops may not nest or share nodes` |

### Workflow: pins and pinned documents (validate, publish and plan only)

| code | sev | message |
|---|---|---|
| `pin.unresolved` | E | `no published version <v> of <agent\|deliverable> "<k>"` (M) |
| `pin.out-of-scope` | E | `<agent\|deliverable> "<k>" belongs to a project; an account-wide workflow cannot pin it` |
| `bundle.missing-agent-doc` / `bundle.missing-deliverable-doc` | E | `no agent document provided for pinned agent "<k>"` / `no deliverable document provided for pinned deliverable "<k>"` |
| `bundle.unpinned-doc` | E | `agent document "<k>" was provided but is not pinned` (import preview) |
| `switch.unknown-field` | E | `deliverable "<d>" has no field "<f>"` |
| `switch.field-not-enum` | E | `field "<f>" of "<d>" is not an enum string — a switch requires a closed value set` |
| `switch.unknown-route-value` | E | `"<v>" is not a value of <d>.<f> (values: <a, b>)` |
| `switch.unrouted-value` | E | `value "<v>" of <d>.<f> has no route — every value must be routed explicitly` (M) |
| `dynamic-group.invalid-field` | E | `for_each must select an array of objects` |

### Agent and deliverable documents

| code | sev | message |
|---|---|---|
| `agent.invalid-prompt-sha` | E | `prompt.sha256 must be 64 lowercase hex characters` |
| `agent.unknown-prompt` | E | `prompt doc <sha> is not stored` (publish only) |
| `deliverable.format-mismatch` | E | `document format <stated> does not match deliverable format <held>` |
| `deliverable.fields-on-html` | E | `an html deliverable is a whole document with no front matter, so it declares no fields` |
| `deliverable.sections-on-non-markdown` | E | `sections describe a markdown outline and are only valid on markdown deliverables` |
| `section.empty-title` | E | `a section needs a title — it is the heading text` |
| `section.level-out-of-range` | E | `heading level <n> is outside 1..=6` |
| `section.level-skipped` | E | `<###> cannot follow <#> — an outline deepens one level at a time` |
| `section.duplicate-title` | E | `duplicate top-level section title "<t>"` / `duplicate section title "<t>" under "<parent>"` |
| `field.invalid-name` | E | `invalid field name "<n>"` |
| `field.enum-on-non-string` | E | `enum is only valid on string fields` |
| `field.empty-enum` | E | `enum must list at least one value` |
| `field.duplicate-enum-value` | E | `duplicate enum value "<v>"` |
| `field.items-on-non-array` / `field.items-missing` | E | `items is only valid on array fields` / `array fields must declare items` |
| `field.fields-on-non-object` / `field.fields-missing` | E | `fields is only valid on object fields` / `object fields must declare fields` |

## 2. Version launchability (`list_versions`)

`launchable` is true when the published declaration has no runtime error. `launch_diagnostics` can hold only
`agent.no-harness`, `agent.effort-without-harness`, `agent.unknown-harness`, `agent.unknown-effort` and
`agent.invalid-model`, at a node's runtime or at a partner's (`<node>.pair.<mode>.runtime.<field>`), and
`pair.harness-unsupported`; the path names the partner's mode. The other `pair.*` errors refuse publishing
and are not checked again here. A draft always reads `launchable: false`. Nothing else is checked: six workflows that
the runner refuses all read `launchable: true` (M).

## 3. Task level

### `launch_problem` (on the task; only the first problem is reported)

| code | fields | meaning |
|---|---|---|
| `process_not_selected` | | the task has no workflow |
| `no_published_version` | | the workflow has no published version |
| `version_not_launchable` | `version, diagnostics` | the version the task would run has a runtime error (section 2), a partner's included |
| `version_missing` | `version` | the task is pinned to a version that no longer exists |
| `model_required` | `node_id, node_name, harness` | the harness needs a model and the node names none; never raised for a partner, whose two harnesses take a default model |
| `runner_revoked` | `runner_key_id` | the task is pinned to a runner key you can no longer see |
| `harness_disabled_on_runner` | `runner_key_id, runner_name, node_id, node_name, mode?, harness` | the pinned key does not enable that harness |
| `model_missing_on_runner` | the same plus `model` | the pinned key does not offer that model |
| `no_runner_supports` | `node_id, node_name, mode?, harness, model?` | no runner key you can use enables that harness or offers that model (M) |

It is computed over runner keys whether or not their runner is connected, and over the keys of whoever is
looking (for a queued task, of whoever queued it). `null` does not mean a runner is online. The runtimes are
checked node by node in document order, each node's own runtime first and then its partners' in byte order
of the mode name (`advise`, `guard`, `review`, `watch`), each after the task's overrides. `mode` is present
when the runtime at fault is a partner's, and absent when it is the node's own. `launch_note:
{code: "sole_runner"}` is raised for a partner's model as for a node's.

### Override refusals (`POST /tasks`, `PATCH /tasks/{id}`)

A task overrides a node's runtime in `exec_overrides` (keyed by node id) and a partner's in
`partner_overrides` (keyed by node id, then mode); neither `create_task` nor `update_task` takes them, so
they are written through `mutate_api_operation`. Each override is checked against the version the task
launches when it is written, and nowhere else.

| code | status | fields | message (template) |
|---|---|---|---|
| `task.override_unknown_node` | 422 | `node_id, mode?` | `<id> is not an agent node of the version the task launches`; with `mode`: `` <id> is not an agent node of the version the task launches with a "<mode>" partner `` |
| `task.override_unknown_harness` | 422 | `node_id, harness, mode?` | `"<h>" is not a known harness` |
| `task.override_unknown_effort` | 422 | `node_id, effort, mode?` | `effort "<e>" is not on the <harness> scale` |
| `task.override_invalid_model` | 422 | `node_id, model, mode?` | `a model is 1 to 128 characters with no whitespace or control characters` |
| `task.override_harness_unsupported` | 422 | `node_id, mode, harness` | a partner override off the two partner harnesses: `a partner runs on claude-code or codex, not on <h>`; a node override that puts a node with a `guard` or `watch` partner on another harness (`mode` names the first such mode): `` a "<mode>" partner sits only on an executor running on claude-code or codex; the override runs the node on <h> `` |
| `task.launch_frozen` | 409 | | the task has a run pending, active or cancelling; no launch field (pin, runner, either override map, `repo`, `readonly_repos`) can change |

`mode` is present when the override is a partner's. A node override written while it was valid is not
checked again when the launched version later gains a `guard` or `watch` on that node; for a `guard`,
the runner then declines the run (`dispatch.unresolvable`, section 5).

### Input readiness (`get_task_readiness` diagnostics)

| code | message |
|---|---|
| `input.missing` | `required input has no attachment binding` (M) |
| `input.invalid` | `content does not match the pinned deliverable schema` (M; names no field) |
| `input.unknown` | `binding is not declared by the selected workflow version` |

### `queue_wait` (only on a queued task; the first that applies)

| value | meaning |
|---|---|
| `running` | the task already has a pending, active or cancelling run |
| `container` | the task is an epic and never runs |
| `cancelled_child` | a child task was cancelled |
| `children` | children are still open |
| `project` | the task has no project |
| `project_access_revoked` | the person who queued it is not a project member (self-hosted) |
| `repository` | the repository selection does not resolve (typically no `repo` in a project with several) |
| `workflow_deleting` | the workflow is being deleted |
| `configuration` | `launch_problem` is set |
| `project_full` | the project's run cap is reached (self-hosted) |
| `iteration` | anything else, mainly "not in the active iteration" |

`null` with a `queue_position` means it waits its turn. Not shown by `queue_wait`: queue draining switched
off for the account, no free seat, every candidate runner at its usage limit.

## 4. Run level

### `status`

`pending` (waiting for a runner), `active` (accepted; a parked run is still `active`), `cancelling`,
`completed`, `halted`, `cancelled`. `declined` exists in the schema but is no longer produced: a permanently
declined run is deleted.

### `pending_reason` (only while `pending`; `null` before the first placement attempt)

| code | fields | meaning |
|---|---|---|
| `runner_offline` | `runner_key_id, runner_name` | the task is pinned to a key whose runner is not connected |
| `runner_invalid` | `runner_key_id, runner_name, reasons[]` | the pinned runner reports a problem; `reasons[].kind` is `harness_not_reported`, `harness_error`, `runner_too_old` or `no_harness_enabled`, with a `text` |
| `runner_unsuitable` | `runner_key_id, runner_name, harness, model?` | the pinned runner lacks the harness or model |
| `runner_busy` | `runner_key_id, runner_name, running, max` | the pinned runner is at its parallel-run cap (M) |
| `runner_limit_reached` | `runner_key_id, runner_name, harness, resets_at` | the pinned runner is over a provider usage limit |
| `no_matching_runner` | `harness, model?` | no online runner suits the run; also what you see when every runner is offline |
| `all_matching_limit_reached` | `harness, resets_at` | every suitable runner is over its usage limit |
| `all_matching_busy` | `runners` | every suitable runner is at its cap |
| `account_full` | `used, seat_count` | all seats are in use; `{0, 0}` means no seats, for example no valid self-hosted license |
| `project_full` | `used, max_concurrent_runs` | the project's run cap (self-hosted) |
| `project_access_revoked` | | the run's creator is no longer a project member, or the project is gone |
| `awaiting_source_runner` | `runner_id` | a resumed run waits for the runner that holds the original |

A partner's harness and model count like the node's own: a reason that names a `harness` or a `model`
may name a partner's, and no field says which node or mode it belongs to. Compare it with the run's
`exec_profile`, where each agent node lists its partners' runtimes under `pair`.

### `halt_kind` (with `status: halted`)

| kind | `outcome.reason` | meaning |
|---|---|---|
| `runner` | the runner's text, for example `plan-directed halt` (M) | the runner stopped the run: a `cancel` node was reached (that is what "plan-directed halt" means, with `failed_node` the cancel node), or a node failed |
| `limit` | the runner's text | a provider usage limit; `limit_wait` says which and when it resets. The server starts a new run by itself (below) |
| `lease_expired` | none | the runner stopped reporting (crashed, lost its connection) for longer than the lease |
| `undelivered` | `no runner confirmed the start after <n> attempts` | the run was offered several times (three by default) and never accepted |
| `no_project` | `task has no project` | |
| `project_missing` | `project <id> for this run was not found` | |
| `no_repo` | `task has no repo binding` | the repository selection stopped resolving before dispatch |
| `input_snapshot_missing` | `run predates validated input snapshots; create a new run` | |
| `resume.execution-unpinned` | `this agent run predates execution snapshots; start a new run instead of resuming it` | |

Kinds written for workflow deletion (`cancel_lease_expired`, `fleet_quiescence`, `deletion_unclaimed`,
`deletion_administrative`) come with `status: cancelled`.

A `limit` halt is readmitted automatically, about a minute after `limit_wait.resets_at`, when the halt is
less than 8 days old, the source runner is connected and not limited, no later run of the task exists and
(self-hosted) the creator is still a project member. The new run carries `source_run_id` of the halted one.
A `limit` halt without `resets_at` is never readmitted automatically.

### Run refusals

| call | status | message |
|---|---|---|
| `start_run` | 409 | `task.launch_problem` "the task cannot be launched as it is configured", with `problem` (M) |
| `start_run` | 409 | "task has no repo binding" (M) |
| `start_run` | 422 | "task inputs are not ready", with the readiness object in `details` (M) |
| `start_run` | 409 | "task already has a run in progress" |
| `start_run` | 409 | `task.container` "task <id> is a container and never runs" |
| `start_run` | 409 | `task.not_ready` "task <id> has <n> open children" |
| `get_run`, `get_run_events` | 404 | "run with id <id> not found" (M: the run was declined and removed, or never existed) |
| `answer_wait` | 409 | "run(<id>) is not awaiting an answer at node(<node>)" |
| `answer_wait` | 409 | "node(<node>) of run(<id>) is awaiting an answer at iteration <i>, attempt <a>, round <r> — not at iteration <i>, attempt <a>, round <r>" |
| `answer_wait` | 409 | "run(<id>) has no runner" |
| cancel (`PATCH /runs/{id}`) | 409 | "run <id> is not cancellable in status <status>" |
| resume (`POST /runs/{id}/resume`) | 409 | "run <id> is <status>, and only a halted run can be resumed", or a `readmission_unavailable` text such as "run <id> names no runner, so there is no worktree to resume from" |

## 5. Runner codes

### Declines: the runner refuses a run before any node starts

A permanent decline deletes the run; a transient one sends it back to `pending` and the server offers it
again at once. The reason text is not readable through the tools once the run is deleted; it appears in the
runner's log as `shepherd: run <id> declined — <code>: <message>`.

| code | kind | message (template) or meaning |
|---|---|---|
| `bundle.invalid` | permanent | the workflow does not compile: `<stage>: <n> diagnostic(s): <code> [<document> <where>] <message>; ...` (at most five, then `; and <n> more`) |
| `script.syntax` | permanent | `<where>: the script does not parse: <error>` |
| `profile.unbound` | permanent | `<n> profile(s) the plan names are not defined at the run's start commit: ...` |
| `profile.command-missing` | permanent | a profile's command or script is not on the runner's PATH or does not exist |
| `workspace.unbound` | permanent | for example `the server lists no URL for project '<p>' repo '<r>', and this runner has no binding for it: add [projects.<p>.repos.<r>] to the runner config to bind a checkout of your own` |
| `workspace.fetch` | transient | cloning or fetching a repository failed for a reason that may pass, such as the network; a clone that cannot succeed (no such repository, no access) is `workspace.unbound` instead, naming the URL and the binding to add |
| `workspace.lfs-unavailable` | permanent | the repository uses Git LFS and git-lfs is missing or unconfigured on the runner |
| `workspace.submodule-relative-url` | permanent | a relative submodule URL and no `origin` remote |
| `input.invalid` | permanent | `$input '<name>' does not match its schema: <n> error(s): ...` or `missing $input payload for '<name>': ...` |
| `exec-profile.invalid` | permanent | `execution profile must identify agent node '<name>' (<id>) exactly once`; for a partner, `execution profile entry for agent node '<name>' (<id>) gives no runtime for its declared '<mode>' partner` |
| `dispatch.unresolvable` | permanent | `<node> cannot be dispatched: <cause>`, for example `harness '<h>' requires a [<section>] runner configuration`, or for a partner `the '<mode>' partner runs on harness '<h>'; a partner runs on: claude-code, codex` |
| `bundle.download` | transient | fetching the workflow failed |
| `bundle.hash-mismatch` | permanent | a fetched document does not match its hash |
| `capacity.busy` | transient | `All <n> executor processes are still occupied; retry this run.` |
| `resume.busy`, `accept.timeout` | transient | |
| `accept.retries-exhausted` | permanent | `declined transiently <n> times in a row by this runner; the latest refusal was <code>: <message>` (after three transient declines; M in a server log) |
| `runner.internal` | permanent | `the runner failed to execute this run (<type>): <error>` |
| `resume.*` | permanent | readmissions only, for example `resume.plan-halted` `the run halted itself; pick a node to restart from` |

With several permanent problems the message is `<code>: <message>; <code>: <message>`, cut at 2000
characters; the first code is the decline's code.

The two partner declines should not happen: the server sends a runtime for every declared partner, and
it refuses a partner off `claude-code` and `codex` when the version is published, when a task is
launched and when an override is written. A run that meets one was sent by a server older than partners
(after a rollback, say) or outside those checks: tell the server's operator, and put the partner's
runtime, or the task's partner override, on `claude-code` or `codex`. `shepherd preflight` prints the
same two problems.

A node with a `guard` partner is declined `dispatch.unresolvable` with the cause `its 'guard' partner
runs here only on an executor running on claude-code, and the execution snapshot puts the executor on
harness '<h>'` when the run puts its executor on another harness. The server checks a task's node
override only when it is written (section 3), so an override written before the node had its guard can
do that. Fix: remove or change the task's override for that node in `exec_overrides`.

<!-- UNFINISHED(codex-executor): the cause above names claude-code only; re-read it once the runner
guards a codex executor, and add the decline of a guarded Codex node on Windows, which names the
platform. -->

### Compile diagnostics (inside `bundle.invalid`, and printed by `shepherd validate`)

The runner's compiler repeats most server rules under its own codes (`parse.*`, `link.*`, `validate.*`,
`rework.*`). The ones the server does not apply are in `runner-only-rules.md`. `shepherd validate` adds
`publish.*` (the server's publish rules, as a local preview) and `script.*` (`script.syntax`,
`script.unconsumed-input`, `script.undeclared-output`); those never decline a run, except `script.syntax`.

One partner code is the runner's alone: `validate.pair-verdict-unusable` at
`nodes.<node>.pair.review.verdict`, ``the runner writes the review loop's verdict into deliverable
'<d>': the node must produce it, and it must be a JSON deliverable whose fields are exactly these (its
name, id and sections are yours): fields: {...}``. The server checks only that the node produces the
verdict deliverable, so a version whose verdict deliverable declares other fields publishes and every
run of it is declined `bundle.invalid` with this code. Fix: a new version of that deliverable with
exactly the fields the message prints (the authoring skill's `references/dialect.md`, "Partners", has
them as a block), and a new workflow version that pins it.

### Node failures (halt reason `node '<name>' failed: <code>: <message>`)

| code | message (template) |
|---|---|
| `node.exhausted` | the last attempt's message; the underlying code is `detail.last.code` |
| `carrier.missing_output` | `declared output '<d>' has no <d>.json in out/`; `markdown output '<d>' has no <d>.md body` |
| `carrier.invalid_payload` | `output '<d>' does not match its schema: <n> error(s): <d>.<field>: ...`; `output '<d>' lacks section '<heading>' (outline position <n>)`; `output '<d>' (<d>.json) is not parseable`; `output '<d>' is not an object`; `html output '<d>' has fields; its <d>.json must be {}` |
| `carrier.oversize_signal` | `deliverable '<d>' is <n> bytes serialized (> <limit>...); ...` |
| `agent.sentinel_missing` | `no SHEPHERD_STATUS: line in the ... result tail or full result after <n> continuation turn(s)` |
| `agent.session_failed` | `<harness> failed (<subtype>) before emitting SHEPHERD_STATUS:` |
| `agent.unexpected_escalation` | `` the agent wrote questions.json but node '<node>' declares no escalation block; add `escalation:` to let it ask `` |
| `agent.malformed_escalation` | `the escalation carrier questions.json <problem>` |
| `agent.escalation_exhausted` | `the agent asked in round <n> but node '<node>' declares max_rounds: <m>` |
| `agent.escalation_timeout` | `no escalation answer on topic '<topic>' within <n>s` |
| `claude.no_envelope` | `claude produced no result envelope (exit code <n>)` |
| `codex.failed` | `codex session failed (exit code <n>): <text>` |
| `codex.quota` | `codex account has no quota left: <text>` |
| `command.not_found` | `executable not found: '<argv0>'` |
| `profile.missing` / `profile.unknown` | `.shepherd/profiles.yml not found in the checked-out tree` / `profile '<name>' is not defined in .shepherd/profiles.yml; has: <names>` |
| `signal.timeout` | `no signal on topic '<topic>' within <n>s` (a gate's `timeout_s`) |
| `map.over-limit` / `map.member_failed` | `map '<id>' sized <n> members over its limit <m> ...` / `map members failed: <ids>` |
| `node.park_exhausted` / `node.park_churn` | parked past the 48-hour budget / re-parked too often |
| `guard.breaker` | `the workflow's guard denied <n> action(s) in this attempt, the last <k> in a row, so the turn was stopped; the last denied action was <tool> <command or path>: <reason>` |
| `guard.unwitnessed` | `the executor's call <id> (<tool> <command or path>) ran with no decision from the workflow's guard: the guard's hook did not fire (a managed policy or a broken hook can switch it off)`; or `the executor's call <id> (<tool> <command or path>) ran although the workflow's guard denied it` |
| `node.internal_error` | an unexpected error inside the runner |

Outside this pattern: `plan-directed halt` (a `cancel` node was reached, M) and
`switch '<node>': value '<v>' of '<field>' has no route and no default`.

**A partner's failures.** An adviser or a reviewer runs as a session of its own harness and fails with
that harness's codes (`claude.*`, `codex.*`), under the rule an executor's session follows: what parks an
executor parks the node (below), anything else spends one of the node's attempts, and the next attempt
starts over, executor and partners alike. An adviser session its harness reports failed is
`agent.session_failed` `the advise partner's session failed (<subtype>) before it replied`. In the
failure's `detail`, `session_id` is the executor's session and `partner_session_id` the partner's. A
reviewer that runs but returns no valid verdict, even when asked once more, is not a failure: the review
loop ends `partner_unavailable` and the node completes. The same goes for running out of review rounds:
it ends `round_cap` or `needs_person`, never a node failure.

**A guard's denies and failures.** A guard never parks the node and never fails it with its harness's
codes: a decision that misses the runner's deadline, a guard session that fails, parks or cannot start,
and an answer that is not the decision object are each a deny, whose reason says which: `the guard gave
no decision within <n>s`, `the guard's session failed (<subtype>, exit code <n>)`, `the guard could not
decide: <code>: <message>`, `the guard's answer was not the JSON object the runner asked for: <text>`,
`the guard's hook gave no answer, so the CLI blocked the call`, and, from the runner itself, `the runner
could not ask the guard: <type>: <error>` or `the runner could not record the guard's decision: <error>`.
Denies fail the node through `guard.breaker`, after three in a row or ten in one attempt, at once and
with no further attempt; its `detail` holds `denied`, `in_a_row`, `tool`, `action` and `reason`. Read
the node's `deny` notes (`run-time.md`, "A node with partners"):

- denies whose reasons are the guard's own judgement: the executor kept trying what the policy forbids,
  so state the policy in the executor's prompt or the task, or change the policy if it forbids ordinary
  work;
- denies whose reasons the runner wrote (a deadline, a failed session, a provider limit or lost login, an
  answer that was not the object): put the guard on a model that answers within the deadline, or fix
  its harness on the runner. The deadline (`[guard] decision_timeout_s` in the runner's configuration,
  30 s by default) also counts the wait for a free partner slot on a busy runner.

`guard.unwitnessed` (`detail`: `tool_use_id`, `tool`) means Claude Code on the runner machine ran a call
without asking the guard, or ran one the guard denied: a managed Claude Code policy or a broken hook
switched the hook off. Only the runner's operator can fix that machine's Claude Code configuration;
until then run the task on another runner, or publish a version without the guard.

### Park codes (the start of `parked_reason`)

`claude.budget`, `codex.budget` (provider usage limits, with `limit_wait`), `codex.rate_limited`,
`opencode.rate_limited` (short rate limits), `claude.login_required`, `codex.login_required`,
`cursor_cli.login`, `opencode.auth` (the harness on the runner needs a login; retried every 300 s). Other park
codes exist. An adviser's or a reviewer's session parks the node with the same codes, for its own
harness; when the node resumes, the executor's session continues and the partner runs again. A guard's
session never parks it: that decision is a deny (above).
