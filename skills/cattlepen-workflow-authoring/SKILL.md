---
name: cattlepen-workflow-authoring
description: "Design, write, validate, publish and prove Cattlepen workflows, agents (with their prompts) and deliverables through the Cattlepen MCP server, so that the workflow actually runs: bundle import or editor operations, the publication plan, the rules only the runner checks, a ready task and a trial run. Use when the user wants a new workflow, wants to change what an existing one does (add a step, an agent, a review, a route, a prompt), wants a second agent inside a step (pair an agent node with an adviser, reviewer, guard or watcher partner), or wants one ported or reviewed. Not for a workflow or run that is refused, stuck or wrong, such as a save or publish refused, a launch_problem, or a run pending, vanished, halted or looping (cattlepen-workflow-repair); not for projects, repositories, tasks and runners (cattlepen-projects); not for queueing, starting and watching runs of several tasks (cattlepen-orchestration)."
---

# Cattlepen workflow authoring

Cattlepen runs workflows: graphs of nodes (agents, inline shell scripts, human gates, switches) that
pass typed documents, called deliverables, to each other. A workflow, each agent (a prompt) and each
deliverable is a library entry with versions; the workflow pins the version of every agent and
deliverable it uses, and only published versions run. A run executes on a runner (the `shepherd`
program on a user's machine) in one repository of a project, and the runner applies rules of its own
that no server tool checks, so a published workflow can still be refused or stop on its first run.

## Rules that are always true

- Work through the Cattlepen MCP tools only, by their bare names. Never invent a tool: there is no
  `cancel_run`; anything without a dedicated tool goes through `read_api_operation` or
  `mutate_api_operation`, after `describe_api_operation`.
- A server reply is the truth, not this skill and not your memory: read every `diagnostics` list.
- Names are `^[a-z][a-z0-9_]*$`, at most 64 characters, for entries, nodes, reworks and fields.
- The library is one namespace for everyone in the account (on a self-hosted installation, the whole
  organization), and a workflow pins its agents and deliverables by name. Give a new workflow's agents
  and deliverables names that belong to it, with a common prefix such as `release_notes_` (the build
  script's `--prefix` does this), never generic ones like `task`, `change` or `review` that another
  workflow already uses or will want. Reuse an existing entry only on purpose, and tell the user
  which entries or which other workflow you reused or started from.
- Every agent node needs `runtime: {harness: ...}`: the harness is the coding-agent program that runs
  the node on the runner (`claude-code`, `codex`, ...). Every decision is a required string enum field
  that a switch routes, every value routed. Every loop is a rework: a declared route back to an
  earlier agent node, with a budget of passes and a node to continue at when it is spent.
- A partner (an agent node's `pair`: an adviser, a reviewer, a guard or a watcher beside the node's
  own agent) has its own runtime on `claude-code` or `codex`, and its agent is pinned in `agents:`
  like the node's own. A starter partner is a template: fill its section marked
  `FILL IN BEFORE PUBLISHING` with the project's rules before it is published, because a partner is
  worth what its prompt knows. Choose each partner's model with `references/patterns.md`
  ("Partners"): a reviewer at least as strong as the executor, an adviser for what it knows. A guard
  is not a sandbox (`references/patterns.md`, "A guard is not a sandbox"), and nobody answers a
  partner's question during the run.
- A run changes only the repository its task names (`repo`). The project's other repositories it may
  read (`readonly_repos`) are reset after every node, so nodes pass state only in deliverables.
- In editor operations every new node and every new rework carries an `id` that is a fresh UUID.
- Publish what the user asked to have working (a workflow that is meant to run is only usable once
  published), and start a run only when the user asked for one. A task without a version pin runs
  the latest published version, so a new version of a workflow that already has a published one
  reaches its unpinned tasks from their next start: name those tasks in your report
  (`list_tasks{workflow_id}`). Ask before publishing when the new version would change behaviour the
  user did not ask to change.
- After an error that is not certified as "nothing was written", read the state before you retry:
  a taken name, every publish refusal and every `start_run` refusal come back uncertified
  (`references/mcp-tools.md`, "Errors").
- Report the highest rung of the ladder below that the server confirms, never a rung a call merely
  seemed to reach.

## The ladder: what done means

| rung | the server confirms |
|---|---|
| 1. Draft saved clean | every entry saved; `validate_workflow` returns no `error` diagnostic |
| 2. Published with every pin | `list_versions` shows the version with `published_at`, `launchable: true` and empty `launch_diagnostics`; every pinned agent and deliverable is published |
| 3. Runner rules checked | `shepherd validate` is clean on the published documents, or every item of the written list in `references/runner-rules.md` was checked by hand (say which) |
| 4. Task ready, runner online | a task in a project with its `repo` set: `get_task_readiness` says `ready: true` with no diagnostics (the input files), the task's `launch_problem` (why a start would be refused) is `null`, and a runner that counts for the project is online with every harness and model the workflow uses, its partners' included |
| 5. Trial run completed | `get_run` reports `completed`, and the deliverables in the run's events are what the workflow promised |

End every piece of work by telling the user the highest rung reached and what the next one needs (for
example "published; to prove it, a task with a brief attached and a runner online").

## Steps

1. **Orient.** Call `whoami` (account, self-hosted or not). Find what exists:
   `search_library{kind, q}` for each kind (`workflows`, `agents`, `deliverables`) with `q` set to
   the names you plan, and `list_projects` / `get_project` for the project and its repositories.
   If a published workflow already does the job, offer it to the user instead of building a copy.
   Reuse a fitting published agent or deliverable instead of copying it. Create entries in the shared
   library unless the user wants them private to one project (then pass `project_id`; see
   `references/mcp-tools.md`, "Scope and names"). To change an existing workflow, read it with
   `list_versions` and `get_workflow_editor_snapshot`, then go to step 5, path B.
   Done when you know the account, the scope, the prefix of the new names and that `search_library`
   finds none of them, what you will reuse, and which project and repository the workflow's tasks will
   use (a task setting, needed in step 8).

2. **Design the graph** before any YAML. Open `references/patterns.md`. Write the node list down
   for the user: for each node its kind, what it consumes and produces, where it goes next; for each
   switch its field and the target of every value; for each rework its head, feedback and exhaustion
   target. Agree on it when the request is open to interpretation. For a second agent inside a step
   (advice, a review, a guard on its actions, notes while it works), read "Partners" in
   `references/patterns.md` before choosing the mode and each model, and say for each partner what it
   knows that the executor cannot.
   Done when every switch routes every enum value, every rework has head, feedback and
   `on_exhausted`, and every consumed deliverable is produced on every path to its consumer.

3. **Write the deliverables, agents and workflow.** Open `references/dialect.md` for the documents
   and `references/runtime-contract.md` before writing a prompt or an inline script: it says what each
   node receives and must write, which the prompt must not repeat. For anything larger than three
   nodes, start from the closest example in `examples/`. For partners, write `pair` from "Partners" in
   `references/dialect.md`; a partner's prompt says who the partner is and what the project requires,
   and how it talks with the executor is the runner's contract ("Partners" in
   `references/runtime-contract.md`), which the prompt does not restate. Start a partner from the
   starters in `examples/paired_change`.
   Done when each document uses only keys the dialect lists, and each prompt says what good work is,
   when to choose each enum value and what to do when work comes back.

4. **Check the runner's rules before creating anything.** This check always happens; only its means
   depend on the machine. Run `shepherd version`. If it prints a version, write the documents in the
   source layout of `examples/`, build a local copy with `scripts/build_bundle.py <dir>
   --validate-copy <copy>` (on either path) and run `shepherd validate <copy>`. If it does not, walk
   every item of the hand checklist in `references/runner-rules.md` over the documents.
   Done when `shepherd validate` prints `ok:` on the copy, or every item of the checklist was checked
   and holds; note which (step 7 may rest on it).

5. **Create it through the MCP.** Open `references/mcp-tools.md` and take one path:
   - **Path A, a bundle** (a new workflow of any size): build it with this skill's script,
     `python3 scripts/build_bundle.py <dir> --prefix <p> [--validate-copy <copy>] > bundle.json`,
     then `preview_workflow_import`, then `import_workflow` with the preview's `token`. A preview
     dependency with `action: "reuse"` (an identical entry exists and would be shared) or `"rename"`
     (another entry holds the name) means a name is taken: tell the user, and change the prefix
     rather than import.
   - **Path B, editor operations** (a change to an existing workflow, or a small new one built step by
     step): `create_library_entry` and `save_authoring` for agents and deliverables, then one
     `apply_workflow_operations` action carrying every node and rework with its UUID `id`.
   Done when `validate_workflow` returns no `error` (rung 1). The apply reply's own `diagnostics: []`
   does not count.

6. **Publish** in the order `references/mcp-tools.md` gives. A workflow draft's `bindings` select
   unpublished (draft) versions of its agents and deliverables. With no bindings and every pinned
   dependency published, `publish_version` publishes the workflow. With bindings (an import always
   has them; so does path B with draft dependencies), publish through the publication plan (create,
   read, approve), which publishes the workflow and those drafts together; do not call
   `publish_version` first. For version 2 or later, follow the publishing rule above.
   Done when `list_versions` shows the new version published and `launchable: true` (rung 2).

7. **Check the published version against the runner rules.** Always, by one of these
   (`references/runner-rules.md`, "Checking with `shepherd validate`"):
   - built in this session from local documents that step 4 validated, and nothing changed on the
     server since the import except what publishing rewrites (pins, minted ids): that check covers it;
   - otherwise, with the CLI: `export_workflow`, the reply written whole and unedited to a file with your
     harness's file-writing tool, `python3 scripts/export_to_bundle.py export.json <dir> --workflow-sha
     <declaration_sha from list_versions>` (it refuses a copy that differs from the server's hashes; an
     edited export proves nothing), then `shepherd validate <dir>`;
   - without the CLI, or when the export is too long to copy whole: every item of the hand checklist
     against the published YAML from `get_declaration`.
   Done when the one used is clean (rung 3) and your final message names it ("source documents
   validated before import", "export validated", "checked by hand"); a report that cannot name it stops
   at rung 2. A failure means a new draft (`create_version`), a fix and a new publish.

8. **Prove it.** Open `references/proving.md`. Create or pick a task in the project with `repo`
   set, attach every required input with `attach_task_file`, read `get_task_readiness`, the task's
   `launch_problem` and whether a runner that counts for the project is online. Start a trial run
   only if the user asks, then follow it with `get_run` and `get_run_events` (small pages, as
   `references/proving.md` says, which also says how to wait between checks) until it ends; fix and
   republish if it halts.
   Done when rung 4 holds, and rung 5 if the user asked for a run.

## Final checklist

- [ ] Every new agent and deliverable has a name that belongs to this workflow; the user knows what
      was reused.
- [ ] `validate_workflow` has no error; every switch routes every value of a required enum field.
- [ ] Every agent node has a `runtime` with a harness and a model the runners offer, or no model; so
      does every partner, on `claude-code` or `codex`.
- [ ] Every partner's agent is pinned; no starter partner's prompt still holds
      `FILL IN BEFORE PUBLISHING`; each partner's model follows "Partners" in `references/patterns.md`
      (no `pair.same-model` warning); a review's `verdict` declares exactly the fields in "Partners"
      of `references/dialect.md` (only the runner checks them) and is routed by a switch, and nothing
      in the design waits for an answer to a partner's question. A guard's rules are stated to the
      executor too, and none of them relies on the guard seeing a read inside the working tree, which
      on a Claude Code executor the runner allows without it ("A guard is not a sandbox" in
      `references/patterns.md`). A `watch` sits only on a node whose executor runs on `claude-code`:
      the server refuses one beside `cursor-cli` or `opencode`, and only the runner refuses one beside
      `codex`.
- [ ] Every new node and rework in an editor action had a UUID `id`.
- [ ] Every inline script writes every declared output on every path, markdown and html with their
      `.json` file too, and parses with `sh -n`.
- [ ] The workflow and every pinned dependency are published; `list_versions` says `launchable`.
- [ ] For a second or later version, the report names the unpinned tasks that now run it, and a
      change of behaviour the user did not ask for was asked about before publishing.
- [ ] The runner rules were checked for the published version (source documents validated before an
      unchanged import, an unedited export validated, or every item by hand), and the final message
      says which; without that, the report says rung 2.
- [ ] The task has `repo`, its inputs attached and `ready: true`, `launch_problem: null`, a runner
      online.
- [ ] The user was told the highest rung reached and what the next one needs.

Where the server's diagnostics disagree with this skill, the server is right.
