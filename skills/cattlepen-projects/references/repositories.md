# Repositories: the project's list, and how a runner finds each one

A project's repository list is the menu its tasks choose from. The server stores names, URLs and
base branches and checks nothing about them beyond the name rules; whether a repository can
actually be checked out is decided by the runner, on its own machine, when it accepts a run.

## The project's list

`create_project{name, repos, max_concurrent_runs?}` returns `{id}`. `get_project{project_id}`
returns `{id, name, repos, file_retention_days}` (plus `max_concurrent_runs` when a self-hosted
cap is set). Every entry comes back with all three keys, `null` where nothing was given:

```json
{"name": "shop", "repos": [
  {"name": "app", "url": "https://git.example.com/acme/app.git", "base_branch": "main"},
  {"name": "docs", "url": null, "base_branch": null}]}
```

| Key | Meaning | Rules |
| --- | --- | --- |
| `name` | What tasks and runner bindings call the repository. | 1 to 100 characters of letters, digits, `.`, `_`, `-`; starts with a letter or digit; no `..`; unique in the project ignoring case. Compared exactly everywhere else. |
| `url` | What a runner clones when it has no binding. | Optional. The server checks no host or scheme. A runner clones only `https`, `http`, `ssh`, `git`, `file` URLs or the `user@host:path` form. |
| `base_branch` | The branch a run starts from, and the commit a read-only repository is read at. | Optional. Blank is stored as `null`. The server checks no branch. |

Refusals seen on create (each is a 422 from the server unless marked):

- two names equal ignoring case: "repos[0].name equals another entry's name ignoring case";
- a name with a space or other character: "repos[0].name may hold only ASCII letters, digits, '.', '_' and '-'";
- any key other than `name`, `url`, `base_branch` in an entry: refused by the MCP tool before any request.

`list_projects` returns the projects you can see, each with its `repos`. A new project's
`file_retention_days` is 7 (allowed values 1, 3, 7, 14, 30, 90; change it with `update_project`).

## Changing the list

`update_project{project_id, name, repos}` replaces the whole list with what you send, in the
order you send it. `name` is required on every call, even when only the list changes (the tool
refuses the call before sending anything when it is missing). Omit `repos` to leave the list
alone; `[]` empties it.

To add `lib` to a project that lists `app` and `docs`: read `get_project`, then send all three.

```json
{"project_id": "<id>", "name": "shop", "repos": [
  {"name": "app", "url": "https://git.example.com/acme/app.git", "base_branch": "main"},
  {"name": "docs"},
  {"name": "lib", "url": "git@git.example.com:acme/lib.git", "base_branch": "develop"}]}
```

Removing or renaming an entry (a rename is a removal plus an addition) is refused while a task
that is `pending` or `in_progress` names it as its `repo` or in an explicit `readonly_repos`
list. The reply is 409 with the tasks, and nothing is changed:

```json
{"error": "project.repo_in_use", "message": "a pending or in-progress task names a repository this list drops; nothing was changed",
 "tasks": [{"status": "pending", "task_id": "<id>", "title": "Update the docs"}]}
```

Point those tasks elsewhere (`update_task{task_id, repo}` or `readonly_repos`) and send the list
again. A task whose `readonly_repos` is `null` does not block a removal.

Adding an entry changes later runs too: every task whose `readonly_repos` is `null` reads
the new repository from its next run on. If the new entry has no URL, those runs are declined on
every runner that lacks a binding for it.

Renaming the project itself (the `name` argument) breaks every runner binding written under the
old name; update the runners' configuration in the same change.

## How a runner finds a repository

When a runner accepts a run, it resolves the task's repository and each read-only one, one at a
time, the task's first. For each it takes the first of these that applies:

1. **A binding** in its own configuration file:

   ```toml
   [projects."<project name>".repos."<repository name>"]
   source = "/absolute/path/to/a/checkout"
   base_branch = "main"
   ```

   Both keys are required. `source` is the top level of a Git checkout on that machine; write an
   absolute path (the setup wizard resolves `~` and relative paths when it asks). It is used as it
   is, never cloned or replaced, even when the entry has a URL. A Git URL as `source` is
   refused (`workspace.unbound`): a binding is always a local path. The table names are the
   project's name and the entry's name, exactly as `get_project` shows them; under any other name
   the binding never applies.
2. **An existing checkout** at `<projects_dir>/<project>/<repository>`, adopted only if its
   `origin` is the entry's URL. `projects_dir` is a top-level key of the runner configuration;
   without it the directory is `projects` under the runner's data directory.
3. **A clone** of the entry's URL into that path, with the machine's own Git credentials.

The run starts from the binding's `base_branch`; for rungs 2 and 3, from the entry's
`base_branch`; else from the remote's default branch. A read-only repository is read at that
same branch's commit, recorded once per run.

What the runner refuses, and what the user sees:

| Situation | Decline code | Kind |
| --- | --- | --- |
| No binding and no URL | `workspace.unbound` (the reason names `[projects.<project>.repos.<name>]`) | permanent |
| Clone refused: not found, access denied, no credentials, host key | `workspace.unbound` | permanent |
| Clone failed for a network reason (DNS, timeout, TLS, HTTP 5xx) | `workspace.fetch` | transient; after 3 in a row the runner sends `accept.retries-exhausted`, permanent |
| Binding `source` is not a directory, or is a URL | `workspace.unbound` | permanent |
| The repository uses Git LFS and git-lfs is not usable there | `workspace.lfs-unavailable` | permanent |
| A submodule has a relative URL and the checkout has no `origin` | `workspace.submodule-relative-url` | permanent |

A permanent decline removes the run: `get_run` then answers 404, and the reason is not readable
through the MCP tools (the web app shows it in a notification). That is why steps 3 and 8 of the
skill check reachability before a run exists. For a run that was already declined, switch to
`cattlepen-workflow-repair`.

### What the operator does on the runner machine

These are `shepherd` commands from the public runner docs
(https://cattlepen.ai/docs/guides/connect-runner/); give them to the user, who runs them there.

- New runner: `shepherd runner create` asks "Add a repository binding?" and then, per binding,
  the project name, the repository name, the local checkout and the base branch.
- Existing runner: add the table above to its configuration file (`shepherd service status`
  shows where each runner's files are), then `shepherd service restart` while the runner is idle;
  a restart stops runs in progress. Shepherd never edits an existing configuration by itself.
- `shepherd doctor` checks Git, the agent CLIs and the runner's configuration.
- Without a binding, check that `git clone <url>` works in an empty folder on that machine, as
  the user the service runs as.

A repository without a URL needs a binding on every runner that serves the project, so prefer a
URL whenever the repository has a remote; keep bindings for local-only repositories, or for an
operator who wants runs to use a checkout they already have.

### Read-only repositories inside a run

Each repository the run reads gets one checkout per run, beside the working tree (`../ro/<name>`
from the tree), at the commit recorded when the run was accepted. After every step the runner
puts it back at that commit and discards what the step changed there (ignored files stay); the
step does not fail, its events carry a `repositories` note. Agent prompts name each read-only
checkout and its path, and `$SHEPHERD_IN/_shepherd/run.json` lists them under
`readonly_repositories`. A workflow declares nothing for this: the task chooses.
