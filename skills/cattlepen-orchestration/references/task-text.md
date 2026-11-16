# Writing a task a pipeline can run without asking

Open this in step 3.

## What the pipeline's agents receive

An agent node's prompt gets the workflow author's prompt plus, from the runner:

- the task's title and description, the description cut after its first 16 KiB with a note that the rest
  is not available;
- an index of every file attached to the task (`_task_context.json`), each with a local copy to open;
- the workflow inputs bound to task files;
- the names and paths of the read-only repositories, beside the working copy of the task's repository.

The task as it was when the run was dispatched is what the run uses: editing the description afterwards
does not reach a run already under way. Nothing else reaches the agents: not your conversation, not the
person's chat, not an issue tracker unless the workflow itself fetches it. An agent that lacks a decision
either guesses or, when its node allows questions, parks the run until someone answers. Both cost more than
a sentence in the description.

## What every description states

1. **The goal and why.** One or two sentences. The why lets the agent choose well where the text is silent.
2. **The expected observable result.** What a person will see when it works: a command's output, a
   file, a passing check, a page. Concrete enough to test.
3. **Scope.** What is in (files, modules, behaviours) and what is out, especially work that a neighbouring
   task of the chain owns. This is also what keeps parallel tasks off each other's files.
4. **Decisions already made.** Libraries, names, formats, trade-offs the person settled. Every answer you
   gave to an earlier run's question that applies here belongs in this list.
5. **How done is checked.** The command or observation that proves it, run where the agents can run it.
6. **What to do when unsure.** Usually: take the smaller change and state the assumption in the final
   report, rather than asking.

Long material (a specification, logs, a design) goes into an attached file, named in the description,
rather than past the 16 KiB cut.

## Worked example

A feature, "export reports", split into three tasks in a project whose repository is `app`. The CSV and
JSON writers touch different files and do not depend on each other, so they run in parallel; the CLI flag
needs both writers merged, so it runs after them.

Title: `Add a CSV writer for reports`

```
Goal: users paste reports into spreadsheets and today have to re-type them. Add a CSV writer next to the
existing table writer.

Expected result:
- `write_csv(rows, out)` in src/report/formats/csv_writer.py writes a header line `date,amount,category`
  and one line per row.
- A value containing a comma or a quote is quoted as a spreadsheet expects (the default dialect of Python's csv
  module).
- An empty report writes the header line only.

In scope: src/report/formats/csv_writer.py (new), tests/test_csv_writer.py (new).
Out of scope: the JSON writer and the `--format` flag (separate tasks), how rows are computed, new
dependencies, any change to the table writer.

Decisions: Python's csv module only; line ending "\n"; amounts written as they are stored, no
currency formatting.

Done when: the project's test command passes, and tests cover an empty report, a value with a comma and a
value with a quote.

If something here is unclear, choose the smaller change and state what you assumed in your final report.
```

The third task's description then says, under Decisions: "The CSV and JSON writers already exist on the
base branch (`write_csv`, `write_json`); call them, do not change them."

Before creating the third task's run, confirm both writers are merged (`references/results.md`): its run
fetches the base branch when a runner accepts it and sees nothing that is not merged by then.

## Checks before the run

- `get_task_readiness(task_id)` returns `ready: true` and `diagnostics: []`. It checks the workflow's inputs
  only.
- The task's `launch_problem` is `null` (read the task again after any change).
- `repo` is set when the project lists more than one repository; otherwise `start_run` answers 409 "task
  has no repo binding".
- A runner key that enables the workflow's harnesses is online (`references/model.md`, "How many runs at
  once").
