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
- **A fix the user cannot get without publishing is published.** When the request names an outcome only a
  published version delivers ("X will not publish, fix it"; its runs are declined, vanish or halt because
  of the workflow), publishing the fix is part of the request: a fixed draft changes nothing for the user.
  Publish it, then report exactly what was published, which tasks now run it (those without a version
  pin) and which do not (pinned tasks, named, with what moving each pin would take). Ask first only when
  the request was to diagnose or explain, when the fix changes what the workflow does beyond removing the
  fault, or when the choice between several fixes is the user's.
- **Ask before you answer a wait for someone.** An answer moves a person's run; it stays their decision.
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

   Read `get_run_events` in small pages (`limit: 20`, `after` the last `seq`, until a page is empty): a
   page at the default 200 events can exceed what a tool result may hold. Look any code up in
   `references/codes.md`. Done when you can name one row and hold the ids and the exact
   server text.

2. **Confirm the cause before you change anything.** Run the "Confirm" check of that section and go
   through its causes in the order given. Done when the state you read matches one cause; if none matches,
   stop and report what you read instead of trying fixes.

3. **Apply the fix to a draft.** On a draft, edit it in place. On a published version, follow
   `references/change-published.md`: a new version seeded from the published one, node ids kept, pins bumped.
   A fix in project setup, repositories or runners belongs to `cattlepen-projects`; switch to it there. Done
   when the server accepted the write (a new `revision` or `draft_revision`) and `validate_workflow` returns
   no error.

4. **Check what only the runner checks, on the draft.** Always, for any workflow you changed. Run
   `shepherd version`: if it prints a version, export the draft, write the reply whole and unedited to a file
   with your harness's file-writing tool, turn it into a bundle with `scripts/export_to_bundle.py` (which
   refuses an altered copy) and run `shepherd validate` (`references/runner-only-rules.md`, way 1); otherwise,
   or when the reply is too long to copy whole, test every rule of that page by hand (way 2). Done when
   `shepherd validate` prints `ok:` or every manual rule passes, and you can say which of the two you did.

5. **Publish the fix when the request needs it** (the rule above): the publication plan when the draft has
   bindings, `publish_version` otherwise (`references/save-validate-publish.md`, section 4). Then read every
   task of the workflow (`list_tasks{workflow_id}`). Done when `list_versions` shows the new version with
   `published_at` and `launchable: true`, and you know which tasks follow it (`workflow_version: null`) and
   which are pinned elsewhere; or, when the rule says to ask first, when the user has the question.

6. **Prove the fix with the signal that showed the fault.** A refused write is now accepted; the same
   `validate_workflow` returns no error; `list_versions` shows `published_at` and `launchable: true`; the task
   shows `launch_problem: null` or `get_task_readiness` shows `ready: true` with `diagnostics: []`;
   `get_run_waits` no longer lists the wait. Each section names its proof. Done when that signal reads clean.

7. **Report.** Done when the user has: what was wrong, quoted from the server; what you changed and published
   (entry, version, ids); which tasks now run it and which pinned tasks do not, with what moving each pin
   would take (`references/change-published.md`, step 7); how the runner rules were checked; the signal that
   proves the fix; and what stays unproven, such as "no run was started, so the runner's acceptance is not
   confirmed".

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
- [ ] The runner-only rules were checked on the draft, by `shepherd validate` when `shepherd version`
      works, else by hand, and the report says which.
- [ ] A fix whose outcome needs a published version was published; the report names what was published,
      the tasks that now run it and the pinned tasks that do not.
- [ ] Nothing beyond that fix was published, no wait was answered and no run was started without the
      user's agreement.
- [ ] The report names what remains unverified.

Where the server's diagnostics disagree with this skill, the server is right.
