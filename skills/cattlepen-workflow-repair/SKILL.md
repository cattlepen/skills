---
name: cattlepen-workflow-repair
description: Diagnose and fix what Cattlepen refuses or gets wrong, through the Cattlepen MCP server. A workflow, agent or deliverable that will not save, validate or publish; a published workflow whose task shows a launch_problem; a run that stays pending, vanished with a 404 after a decline, halted, fails, loops, rejects an answer or completed with the wrong result. Maps each symptom and error (workflow.edit_conflict, "new nodes require a stable UUID identity", pin.unresolved, complete-set approval, launch_problem, pending_reason, halt_kind, rules only the runner checks) to its real cause, a fix, and the server check that proves the fix. Use when something in Cattlepen is refused, stuck or wrong. Not for building a workflow or changing what it does (cattlepen-workflow-authoring), setting up projects, repositories, tasks and runners (cattlepen-projects), or starting runs, watching them and answering their questions (cattlepen-orchestration).
---

# Repairing Cattlepen workflows and runs

Cattlepen runs **workflows** (graphs of agent, script, switch and human-gate nodes, stored as versioned
YAML in a library together with the **agents** and **deliverables** they use) as **runs** of **tasks**,
executed by **runners**: the `shepherd` program on connected machines. Each library item has numbered
versions; a version is a **draft** until it is published, and frozen after. Several error messages point
the wrong way, and some checks happen only on the runner, after a version is published. This skill takes
you from the symptom to the real cause, a fix, and a proof read from the same server signal that showed the
fault.

## Rules that always hold

- **Read the state, not the wording.** Four messages mislead. "new nodes require a stable UUID identity"
  is also about reworks (a rework is a workflow's declared loop back to an earlier agent node).
  `workflow.edit_conflict` "an affected item changed; preserve your input and reload
  the shared state" is often a dangling reference or a wrong `before` value, and reloading never fixes it.
  A save "succeeds" with error diagnostics. `publish_version` refuses any workflow with draft dependencies
  ("use complete-set approval"); the route that works is a publication plan.
- **A save is not a check.** `save_authoring` stores drafts with errors, and an `apply_workflow_operations`
  reply's `diagnostics` skip whole stages. Only `validate_workflow` (and, for agents and deliverables, the
  save reply's own `diagnostics`) tells you whether a draft can be published.
- **Published is not runnable.** `launchable: true`, `launch_problem: null` and `ready: true` pass
  workflows the runner refuses, with no runner online, and with a repository nobody can clone. Check the
  runner-only rules before you call a workflow fixed.
- **A published version never changes.** Every fix to one is a new version; tasks that follow the latest
  version pick it up, pinned tasks and existing runs do not.
- **After a refused write, read again before you retry.** A refusal that comes back unchanged after a
  reload is not a race; find the cause.
- **A run that answers `404` after it started was declined and deleted.** No tool returns the reason. Never
  report it as started or guess a reason; diagnose it.
- **One answer closes a wait.** Collect the answers to every question, then send them in one `answer_wait`.
- **Ask before you publish or answer for someone.** Publishing cannot be undone, every task without a
  version pin runs the new version from its next start, and an answer moves a person's run. Show what
  will happen, including which tasks will pick up a new version, and go ahead once the user agrees (or
  already asked for exactly that).
- **Do not start runs to test a fix** unless the user asks. They spend the user's model usage and can change
  their repository.

## Steps

1. **Name the symptom and collect the evidence.** Find the ids: the entry (`search_library`) and its
   versions (`list_versions`), the task (`list_tasks`), the run (`list_runs{task_id}`). Copy the exact
   server text: the error's `error` and `message`, the diagnostics, the field that is wrong. Then pick the
   row below and open the file it names.

   | what you see | where to confirm | open |
   |---|---|---|
   | a write refused: `apply_workflow_operations`, `save_authoring`, `create_library_entry` | the error | `references/save-validate-publish.md`, section 1 |
   | a save accepted with `diagnostics` | the save reply | same file, section 2 |
   | `validate_workflow` lists errors, or answers `409` `workflow.publication_changed` | `validate_workflow` | same file, section 3 |
   | `publish_version` or a publication plan refused | the error | same file, section 4 |
   | a published workflow whose task has a `launch_problem`, missing inputs, or a repository error | the task, `get_task_readiness` | `references/launch-and-dispatch.md`, section 5 |
   | a run stays `pending`, or a queued task gets no run | `get_run` `pending_reason`, the task's `queue_wait` | same file, section 6 |
   | a run answers `404` "run with id ... not found", or disappeared from `list_runs` | `get_run`, `list_runs` | same file, section 7 |
   | a run `halted` | `get_run` `halt_kind`, `outcome.reason`, `failed_node` | `references/run-time.md`, section 8 |
   | a run waits for an answer that was refused or keeps coming back, or is parked with no question (answering an ordinary wait belongs to `cattlepen-orchestration`) | `get_run` `open_waits`, `parked_reason`, `get_run_waits` | same file, section 9 |
   | a node fails, retries, or a rework loops | `get_run_events` | same file, section 10 |
   | a run completed with the wrong result | `get_run_events` | same file, section 11 |

   Look any code up in `references/codes.md`. Done when you can name one row and hold the ids and the exact
   server text.

2. **Confirm the cause before you change anything.** Run the "Confirm" check of that section and go
   through its causes in the order given. Done when the state you read matches one cause; if none matches,
   stop and report what you read instead of trying fixes.

3. **Apply the fix.** On a draft, edit it in place. On a published version, follow
   `references/change-published.md`: a new version seeded from the published one, node ids kept, pins bumped,
   then the tasks checked. A fix in project setup, repositories or runners belongs to `cattlepen-projects`;
   switch to it there. Done when the server accepted the write: a new `revision`, `draft_revision` or
   `published_at`.

4. **Prove the fix with the signal that showed the fault.** A refused write is now accepted; the same
   `validate_workflow` returns no error; `list_versions` shows `published_at` and `launchable: true`; the task
   shows `launch_problem: null` or `get_task_readiness` shows `ready: true` with `diagnostics: []`;
   `get_run_waits` no longer lists the wait. Each section names its proof. Done when that signal reads clean.

5. **Check what only the runner checks.** For any workflow you changed or published, follow
   `references/runner-only-rules.md`: export the version, build a bundle with `scripts/export_to_bundle.py`,
   run `shepherd validate`; or, without `shepherd`, test each rule by hand. Do it on the draft, before
   publishing, whenever you can. Done when `shepherd validate` prints `ok:`, or every manual rule passes, or
   you tell the user it was not checked.

6. **Report.** Done when the user has: what was wrong, quoted from the server; what you changed (entry,
   version, ids); the signal that proves it; and what stays unproven, such as "no run was started, so the
   runner's acceptance is not confirmed".

## Where other skills take over

- Designing or writing a new workflow, agent or deliverable, or first-time publishing:
  `cattlepen-workflow-authoring`.
- Projects, their repositories, tasks' repository selection beyond the fixes here, runners and their keys:
  `cattlepen-projects`.
- Queueing tasks, starting runs, answering their waits, driving a chain of runs and confirming what
  they delivered: `cattlepen-orchestration`.

## Checklist

- [ ] The symptom is one row of the table, and the exact server text is quoted.
- [ ] The cause was confirmed from server state before any change.
- [ ] A published version was changed only through a new version; node and rework ids were kept.
- [ ] `validate_workflow` returns no error for every workflow version you touched.
- [ ] The proof is the same server signal that showed the fault, read after the fix.
- [ ] The runner-only rules were checked (or the report says they were not).
- [ ] Nothing was published, answered or started without the user's agreement.
- [ ] The report names what remains unverified.

Where the server's diagnostics disagree with this skill, the server is right.
