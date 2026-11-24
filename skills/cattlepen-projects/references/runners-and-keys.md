# Runners and runner keys

A runner is a machine running `shepherd`, connected to Cattlepen with a runner key. The key
belongs to one user and decides what the runner is given: which harnesses, which models, how many
runs at once, and whether only the owner's runs (private) or anyone's in the account (shared)
reach it. The runner itself, on its machine, decides whether it can check out the repositories
(`repositories.md`).

## Three reads, three answers

| Call | What it lists | Use it for |
| --- | --- | --- |
| `read_api_operation{operation: "GET /runners", request: {query: {project_id}}}` | Every key you can see (yours, and shared ones), connected or not, each with its runner: `name`, `own`, `shared`, `connection`, `status`, `enabled_harnesses`, `models`, `max_parallel_runs`, `manual_dispatch_only`, `invalid_reasons`, `harnesses`, `limits`. In self-hosted Cattlepen, `project_id` keeps only keys whose owner is a member of the project. | The launch check: is a runner that counts for this project online and able? |
| `list_runners` | Runners connected right now: `label`, `user_id`, `shared`, `run_ids`, `limits`, `connected_at`; plus `seat_count` and `stale_after_secs`. | A quick look at who is online and what they hold. It shows no harnesses. |
| `list_api_keys` | Your own keys: `name`, `prefix`, `created_at`, `last_used_at`, `revoked_at`, and the same runner view as `GET /runners` under `runner` (`null` for a revoked key). | Managing your keys. |

`read_api_operation{operation: "GET /catalog/models", request: {}}` counts, per harness and
model, how many visible keys offer it (`runners`) and how many of those are connected (`online`).
`GET /catalog/harnesses` lists the harness ids: `claude-code`, `codex`, `cursor-cli`, `opencode`.

`connection` is `never`, `online` or `offline`. `status` says more:

| `status` | Meaning |
| --- | --- |
| `online` | Connected, valid, not limited, below its parallel-run limit. |
| `full` | Connected, but running `max_parallel_runs` runs already. |
| `limit` | Connected, but an enabled harness is waiting out a provider usage limit (`limited_until` says until when). |
| `invalid` | Connected, but takes no runs; `invalid_reasons` says why (`harness_error`, `harness_not_reported`, `runner_too_old`, `no_harness_enabled`). |
| `offline` | Has connected before, not now. |
| `never` | The key has never been used by a runner. |

## When a runner can take a task's run

All of these at once:

- `status` is `online`;
- the key is the requester's own (`own: true` for the user you act as) or `shared: true`;
- in self-hosted Cattlepen, the key's owner is a member of the task's project (the `project_id`
  filter above applies this);
- every harness the workflow's agent nodes use is in `enabled_harnesses`, and every model a node
  pins is in `models[harness]`; a node's partners (its `pair`: an adviser, a reviewer, a guard or a
  watcher, each with its own runtime on `claude-code` or `codex`) count the same way, so the key
  must also enable each partner's harness and offer each model a partner pins;
- `manual_dispatch_only` is `false`, or the task pins this key (`runner_key_id`);
- the runner can reach every repository the run uses (checked only by the runner);
- the runner can run every node where the run puts it (checked only by the runner, which declines the
  run otherwise): on a Windows runner, no node with a `guard` or a `watch` partner runs its agent on
  `codex`; and
  on a runner whose operator turned on the runner's own guard (`[guard] policy_file` in its
  configuration), which judges every agent node of every run it takes, no agent node runs on
  `cursor-cli` or `opencode`, nor on `codex` when the runner is on Windows. The server does not know
  either rule and keeps placing such runs there, each declined and deleted, so the operator of a
  runner with its own guard removes those harnesses from its key's `enabled_harnesses`.

When a run starts without a pin, it goes to the requester's own runner when one of theirs is
online, otherwise to the shared pool. `GET /tasks/{id}/exec-profile` (through
`read_api_operation`) shows, per agent node of the version the task launches, the harness, model
and effort it will run with (`effective`), including task overrides, and under `pair` the same for
each of its partners, keyed by mode: `{agent, default, override, effective}` (`pair` is `{}` on a
node without partners). While the task has a live run, `effective` is what that run was frozen
with.

## What `launch_problem` checks

`launch_problem` compares the task's workflow version with the settings of the visible keys,
whether their runners are online or not. Measured: a task read `launch_problem: null` while the
only key enabling its harness was offline. Codes, first found wins:

| Code | Meaning |
| --- | --- |
| `process_not_selected` | The task has no workflow. |
| `no_published_version` | The workflow has no published version. |
| `version_not_launchable` | The version has launch diagnostics (`diagnostics`). |
| `version_missing` | The pinned version is gone. |
| `model_required` | The node's harness requires a model and none is set (never a partner's). |
| `runner_revoked` | The pinned key was revoked. |
| `harness_disabled_on_runner` | The pinned key does not enable the node's harness. |
| `model_missing_on_runner` | The pinned key does not offer the node's model. |
| `no_runner_supports` | No visible key (without `manual_dispatch_only`) enables the harness or offers the model. |

The last three carry `mode` (`advise`, `review`, `guard`, `watch`) when the runtime at fault is one
of the node's partners, and omit it when it is the node's own. `launch_note: {code: "sole_runner"}`
is not a problem: only one runner offers a model a node or one of its partners pins.

## Creating a key (ask first)

A key is a credential: whoever holds it can run work as its owner. Propose it, say what it will
enable, and create it only on the user's yes.

1. `create_api_key{name, enabled_harnesses}`: a private key for the listed harness ids (at least
   one; each from `GET /catalog/harnesses`). The reply is `{id, key}`; `key` is the secret, shown
   this once (a runner key starts with `rk_`).
2. Give the secret to the user once, with what to do: on the runner machine, run
   `shepherd runner create` and paste it at the `API key` prompt; for a script,
   `printf '%s\n' "$RUNNER_KEY" | shepherd runner create <name> --api-key-stdin --no-service`.
   Do not write it to a file, a log, a task, a commit or a later message. A lost key is revoked
   and replaced, never recovered.
3. After the runner starts, `GET /runners` shows the key `online` within about a minute. A key not
   yet used shows `connection: "never"`, `max_parallel_runs: 1`, and the harness's base models.

A shared key takes runs from anyone in the account: `mutate_api_operation{operation:
"PATCH /api-keys/{id}", request: {path: {id}, body: {shared: true}}}`; refused with 409 while a
privately placed run is executing on it. `revoke_api_key{key_id}` disables a key; runners using
it are refused on their next connect. Both need the user's yes.

## Runner settings: harnesses, models, parallel runs

Read: `read_api_operation{operation: "GET /api-keys/{id}/runner-settings", request: {path: {id}}}`
returns `{api_key_id, editable, settings, runner}`; only the key's owner may save (`editable`).

Write: `mutate_api_operation{operation: "PUT /api-keys/{id}/runner-settings", request: {path:
{id}, body: <settings>}}`. The body replaces all settings, and `enabled_harnesses` and
`max_parallel_runs` are required (a body without them is refused before sending). Example that
enables Codex beside Claude Code, allows one Codex model id the runner does not report (put the
real id in place of the placeholder), and keeps one run at a time:

```json
{"enabled_harnesses": ["claude-code", "codex"], "max_parallel_runs": 1, "manual_dispatch_only": false,
 "models": {"codex": {"custom": ["<codex model id>"], "denied": []}}}
```

`models.<harness>.denied` hides reported models; `custom` adds model ids the runner may be given
even when it does not report them. The reply carries the recomputed runner view, whose `models`
is the effective list per enabled harness. Refusals are 422 `runner_settings.no_harness`,
`runner_settings.unknown_harness`, `runner_settings.invalid_max`, `runner_settings.invalid_model`
(each names its `field`), 403 `runner_settings.not_owner`, 409 `api_key.revoked`.

`max_parallel_runs` is what the server sends; the machine also caps itself with `executors` in its
own configuration file. Raise both when a runner reads `full` too often.

## Seats

`whoami` and `list_runners` report `seat_count`: the most runs of the account the server keeps
dispatched at once. Self-hosted dispatch also needs a valid installation licence. A run that waits
for seats or a licence stays pending with a `pending_reason`; reading and acting on that belongs to
`cattlepen-orchestration`.
