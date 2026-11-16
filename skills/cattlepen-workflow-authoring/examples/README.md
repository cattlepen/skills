# Example bundles

Three complete workflows in the source layout that `scripts/build_bundle.py` reads. Each one was
built with that script, previewed with no diagnostic, imported, published through a publication
plan, and checked clean by `shepherd validate`, both as source and as published. These three have
not been run end to end; a different workflow of the same shape as `proposal_review` (agent, gate,
switch, rework) completed a run on a test installation. The prerequisites below are what a run needs.

| example | shape | needs at run time |
|---|---|---|
| `proposal_review` | agent writes a proposal, the owner approves or rejects it, a reject sends the note back (bounded rework), exhaustion stops the run | a repository the agent can read; a `brief` input file |
| `code_change` | plan, implement, inline lint and test, review, inline commit and pull request (it commits tracked edits and the new files the developer lists in `change.files`, never untracked build output); a failing check and a reviewer's `rework` both route into one rework; exhaustion goes to an owner gate | `scripts/check.sh` in the repository, `jq` and an authenticated `gh` on the runner, an `origin` remote the runner can push to; a `task` input file |
| `staged_build` | design and design review (one rework), build an html page and play-test it (a second rework), the owner plays it | a headless browser on the runner for the builder and the tester; a `concept` input file |

Layout:

```text
<example>/
  workflow.yml                         workflow document, schema 2, id REPLACE_WITH_ENTRY_ID
  agents/<name>/<version>/agent.yml    agent document, schema 1 (the script adds the prompt hash)
  agents/<name>/<version>/prompt.md    the prompt text
  deliverables/<name>/<version>.yml    deliverable document, schema 1
```

Build a bundle (Python 3.10 or newer, standard library only):

```sh
python3 scripts/build_bundle.py examples/proposal_review --prefix acme_ \
  --validate-copy /tmp/acme-proposal > /tmp/acme-proposal.json
shepherd validate /tmp/acme-proposal     # only where the runner CLI is installed
```

`--prefix` renames the workflow and every agent and deliverable it defines, including the names
inline scripts read and write, so the import creates new entries instead of colliding with entries
already in the library. Always pass one that names your workflow: the example names (`task`,
`change`, `review`) are generic, and the library is shared by the whole account. Then follow "Path A" in `../references/mcp-tools.md`: preview, import, and
publish through the publication plan.

Adapt before use: the runtimes (read the harness and model catalogs first), the prompts, and in
`code_change` the check command and the push and pull-request steps. The examples work in the run's
own repository; a workflow that reads another repository of the project takes its path from
`readonly_repositories` (see `../references/runtime-contract.md`).
