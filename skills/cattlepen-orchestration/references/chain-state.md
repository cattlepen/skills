# The chain's state file

Open this in step 2, and again whenever the conversation was reset or compacted.

A chain of runs outlives a conversation's context. After a reset you would otherwise have to rediscover
which tasks belong to the chain, re-read every run's journal from the beginning, and guess which questions
you already answered and why. Three things in particular cannot be recovered from the server cheaply or at
all:

- the last journal `seq` you read for each run, which lets `get_run_events(after=<seq>, limit=20)` bring a run up
  to date from there instead of paging its whole journal again;
- why the plan orders tasks as it does (which files they share, which change another needs);
- what you decided in answers and why, so a later question gets a consistent answer, and so you never post
  a second answer to an address already answered (it is refused with 409).

Keep the file outside every repository a run works in (for example `cattlepen-chain.md` in your own working
directory), never commit it to the repository the pipeline changes, and rewrite it after every change of
state: a run started, a wait answered, a run finished, evidence read.

## Template

```markdown
# Chain: <short name>          updated <UTC time>

Project: <project id>   Workflow: <name> version <n> (<version id>)
Capacity when planned: <free seats> seats; runner keys <name running/max_parallel_runs>; queue execution <on|off>
The person asked: <the request in one line>. Delegated to me: <gates or questions they let me decide, or none>.
Run budget: <how many runs they agreed to; runs started so far>

## Plan
| # | task | task id | after | why |
|---|------|---------|-------|-----|
| 1 | CSV writer | <id> | - | - |
| 2 | JSON writer | <id> | - | disjoint files with 1 |
| 3 | --format flag | <id> | 1 and 2 merged | calls both writers |

## Runs
| task | run id | state | last seq | evidence or next action |
|------|--------|-------|----------|-------------------------|
| 1 | <run id> | active | <seq> | check again |
| 2 | <run id> | completed | <seq> | pull request <url> open; waiting on review |

## Decisions and answers
- <time> run <run id>, node <node id>, at <iteration>/<attempt>/<round>: answered <answer>, because
  <source: task text, the person's words>. Added to the description of task 3: yes.

## Owed to the person
- <what to tell or ask them, and by when; for example a gate that times out at <time>>
```

## Resuming after a reset

1. Read the file before calling any tool.
2. For each run whose state is not terminal: `get_run`, then `get_run_events(after=<last seq>, limit=20)`, paging
   until a page is empty; update the row.
3. For a run with `open_waits` above 0, read `get_run_waits` and compare the address with "Decisions and
   answers" before answering anything.
4. Continue from the first plan row that is not delivered, and tell the person anything in "Owed" that is
   now due.
