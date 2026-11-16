# Confirming a result where it lands

Open this in step 8. A run's `completed` status says the workflow reached its end node. It does not say that
the change exists where the person needs it. Confirm that before you mark a task delivered or start a task
that depends on it.

## What the run itself leaves

- **Deliverables.** Each `node_completed` event carries `payload.deliverables`, a list of
  `{name, value}`: a JSON object for a json deliverable, the text for a markdown one. Seen: a 2.3 KB
  markdown proposal as one string; a review gate's `{"decision": "approve", "note": null}`. When work was
  sent back, the same node completes again with a higher `iteration`; the last one on the path to the end
  is the final one.
- **Result files.** `get_run` returns `result_files`. They expire with the project's file retention
  (`file_retention_days` on `get_project`); a reference does not keep the bytes alive.
- **Nothing on the runner.** As soon as a successful run has reported its end, the runner deletes the run's
  working directory. Whatever the workflow did not deliver, push or publish is gone.
- **A deleted workflow.** When `get_run` shows `summary_only: true`, the run's workflow was deleted: only
  the summary and the files remain, and its events and waits cannot be read.

## Where a change is meant to land

Read the published declaration, `get_declaration(kind="workflows", entry_id=<workflow id>,
version=<version>)`, with the version from `get_run`. It shows whether a script node pushes a branch, opens a
pull request, or whether the run ends at deliverables someone applies by hand. That decides what to check:

- **A pull request or a pushed branch.** Find it in the run: a deliverable may carry its URL or branch
  name, and a script node's `node_event` rows (`payload.kind` `run`) carry the script's output. Read its state with your own tools, for example GitHub's `gh pr view <url> --json
  state,mergedAt,baseRefName` or `git fetch` followed by `git log origin/<base branch>`. Delivered means
  merged into the intended base branch. An open pull request is waiting on review: report it as waiting on
  the person; merging into a default branch is their call unless they said otherwise.
- **Deliverables only.** Read the values and check them against the task's expected result. A report that
  merely says "pass" is not evidence of what was checked.
- **An outside system** (a ticket, a document, a deployment). Check there, with the person's own tools,
  that the item exists.

## Record the evidence

In the state file, next to the task: the run id, the evidence (pull request URL and merge commit, or the
deliverable names you read) and when you read it. Start a dependent task only after its dependency's
evidence says its change is on the branch the dependent run starts from. When the workflow leaves the change
only in a pull request, a branch or a deliverable, that never happens by itself: the dependent task waits for
the person to merge (or for your merge, with their word), or you report that the chain cannot continue as it
is. Starting it anyway gives it a tree without the change it needs. If the evidence contradicts the run (the
run completed but no pull request exists, or it was closed unmerged), the task is not delivered: read the
run's last events, then retry or report.
