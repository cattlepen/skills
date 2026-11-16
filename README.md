# Cattlepen skills

Agent skills for [Cattlepen](https://cattlepen.ai/), a workflow and agent orchestration product.
The skills teach a coding agent to work with Cattlepen through the Cattlepen MCP server. One
repository serves both [Claude Code](https://code.claude.com/) and the
[OpenAI Codex CLI](https://github.com/openai/codex): the same `skills/` directory is installed
by both.

| Skill | Use it to |
| --- | --- |
| `cattlepen-workflow-authoring` | design, write, validate, publish and prove a new workflow with its agents and deliverables, or change what an existing one does; ships example workflows and two scripts (build a bundle from files; check an exported version against the server's hashes and write it out for the runner's validator) |
| `cattlepen-projects` | set up a project so its tasks can start: the account, repositories and how runners reach them, tasks with their repository choice and input files, iterations, runner keys and members |
| `cattlepen-workflow-repair` | find the real cause of a refused save or publish, a `launch_problem`, a run that stays pending, vanished, halted, loops or delivered the wrong result, fix it and prove the fix |
| `cattlepen-orchestration` | carry several tasks through their runs: plan the order, write task text a pipeline can run alone, queue or start, watch, answer waits, retry or cancel, confirm each result where it lands |

> **Status:** all four skills are written and were checked against a running Cattlepen
> installation and the runner's own validator. Each `SKILL.md` holds the rules and the steps;
> details sit in its `references/`.

## How the four fit together

| The request | Open |
| --- | --- |
| "Build a workflow that ...", "add a review step to our workflow" | `cattlepen-workflow-authoring` |
| "My workflow will not publish", "the run vanished", "it halted at ..." | `cattlepen-workflow-repair` |
| "Set up a project for these repositories", "why will this task not start?" (no run yet) | `cattlepen-projects` |
| "Run these five tasks and tell me when they are merged", "answer the gate" | `cattlepen-orchestration` |

The skills hand over to each other by name: authoring sends a refused or stuck workflow to repair,
and each one sends project and runner setup to projects and the driving of many runs to
orchestration.

The authoring skill reports how far a workflow got on a five-rung ladder, and only a rung the
server (or the runner's validator) confirms counts:

1. **Draft saved clean**: `validate_workflow` returns no error.
2. **Published with every pin**: `list_versions` shows it published, `launchable: true`.
3. **Runner rules checked**: `shepherd validate` is clean, or every rule only the runner enforces
   was checked by hand.
4. **Task ready, runner online**: a task with its repository and inputs, no `launch_problem`, and a
   runner online that can take it.
5. **Trial run completed**: a run reached the end and delivered what the workflow promises.

The skills call Cattlepen MCP tools by their bare names (for example `start_run`), so they work
whatever name each harness gives the server. The plugin also connects the Cattlepen cloud MCP
server, `https://mcp.cattlepen.ai`; you sign in once (see
[Connect the Cattlepen MCP server](#connect-the-cattlepen-mcp-server)).

Tested with Claude Code 2.1.325 and codex-cli 0.156.1.

## Install in Claude Code

As a plugin (the skills load as `cattlepen:<skill>`):

```sh
claude plugin marketplace add cattlepen/skills
claude plugin install cattlepen@cattlepen-skills
```

From a local clone instead of GitHub, pass its path:
`claude plugin marketplace add /path/to/skills`. Start a new session afterwards.

As plain skills, without the plugin: copy (or symlink) the skill directories into
`~/.claude/skills/`. If you set `CLAUDE_CONFIG_DIR`, the directory is
`$CLAUDE_CONFIG_DIR/skills/` instead.

```sh
git clone git@github.com:cattlepen/skills.git ~/src/cattlepen-skills
mkdir -p ~/.claude/skills
cp -R ~/src/cattlepen-skills/skills/cattlepen-* ~/.claude/skills/
```

## Install in Codex

As a plugin (the skills load as `cattlepen:<skill>`):

```sh
codex plugin marketplace add cattlepen/skills
codex plugin add cattlepen@cattlepen-skills
```

From a local clone, pass its path: `codex plugin marketplace add /path/to/skills`. Start a new
Codex session afterwards; a running session keeps the skills it started with.

As plain skills: copy the skill directories into `~/.agents/skills/`, the user skill directory
of Codex 0.156 (`~/.codex/skills/` is still read but deprecated).

```sh
mkdir -p ~/.agents/skills
cp -R ~/src/cattlepen-skills/skills/cattlepen-* ~/.agents/skills/
```

Copy rather than symlink for Codex: a skill reached through a symlink into a clone of this
repository is named after the plugin manifest above its real path, so it loads as
`cattlepen:<skill>` instead of `<skill>`.

Install each harness one way only. A plugin plus plain copies loads every skill twice, once
with the `cattlepen:` prefix and once without.

## Connect the Cattlepen MCP server

**Installed as a plugin, on Cattlepen cloud:** the plugin brings the server; only sign in. In Claude
Code run `/mcp`, choose `plugin:cattlepen:cattlepen` and authenticate. In Codex run
`codex mcp login cattlepen`.

**Self-hosted Cattlepen.** In Claude Code, set `CATTLEPEN_MCP_URL` to your installation's MCP URL
before starting it; the plugin's server uses it instead of the cloud URL. Codex does not expand
variables in a plugin's server, so on a self-hosted installation install the skills as plain
skills for Codex (above) and add the server yourself with the commands below.

**Plain skills, or a server added by hand:**

| Installation | MCP URL |
| --- | --- |
| Cattlepen cloud | `https://mcp.cattlepen.ai` |
| Self-hosted Cattlepen | the installation's public MCP URL; ask its administrator |

On a self-hosted installation the web app publishes the same URL as `mcpUrl` in
`https://<your-app-host>/runtime-config.js`.

The server signs you in with OAuth through Cattlepen's identity provider, as the same user and
with the same permissions as in the web app. The provider does not register clients
dynamically, so give the client ID: `mcp` on Cattlepen cloud; on a self-hosted installation,
the OAuth client its administrator configured for MCP. Replace the URL below with your
installation's.

Claude Code (`--scope user` makes the server available in every project):

```sh
claude mcp add --scope user --transport http cattlepen https://mcp.cattlepen.ai --client-id mcp
```

Then sign in from a session: run `/mcp`, choose `cattlepen` and authenticate.

Codex:

```sh
codex mcp add cattlepen --url https://mcp.cattlepen.ai --oauth-client-id mcp
codex mcp login cattlepen
```

An MCP connection lets the agent coordinate Cattlepen work. Executing workflow steps also needs a
runner connected to Cattlepen; see the [Cattlepen documentation](https://cattlepen.ai/docs/).

## Update

| Route | Claude Code | Codex |
| --- | --- | --- |
| Plugin from GitHub | `claude plugin marketplace update cattlepen-skills`, then `claude plugin update cattlepen@cattlepen-skills` and restart | `codex plugin marketplace upgrade cattlepen-skills` (refreshes the clone and reinstalls installed plugins from it), then a new session |
| Plugin from a local clone | `git pull` in the clone; the plugin is read from the folder | `git pull`, then `codex plugin add cattlepen@cattlepen-skills` again: Codex serves its cached copy until reinstalled |
| Plain skills | `git pull`, then copy the directories again | same |

Uninstall with `claude plugin uninstall cattlepen@cattlepen-skills` or
`codex plugin remove cattlepen@cattlepen-skills`.

## Repository layout

```text
skills/<skill>/SKILL.md            the skills, one copy for both harnesses
skills/<skill>/references/         detail a SKILL.md opens when one of its steps needs it
skills/<skill>/scripts/            Python 3 standard-library helpers the steps call
.claude-plugin/plugin.json         Claude Code plugin manifest
.claude-plugin/marketplace.json    Claude Code marketplace "cattlepen-skills" (plugin source "./")
.codex-plugin/plugin.json          Codex plugin manifest
.agents/plugins/marketplace.json   Codex marketplace "cattlepen-skills" (plugin source "./")
.mcp.json                          the MCP server for Claude Code (URL overridable with CATTLEPEN_MCP_URL)
.codex-mcp.json                    the MCP server for Codex (referenced from .codex-plugin/plugin.json)
scripts/check.sh                   offline checks for skills and manifests
```

The repository root is the plugin for both harnesses. Each harness reads its own manifest:
Codex prefers `.codex-plugin/` and `.agents/plugins/` over the Claude Code files.

## Writing a skill

- Put it in `skills/<name>/SKILL.md`. The frontmatter `name` equals the directory name
  (lowercase letters, digits and hyphens, at most 64 characters); `description` is one line of
  at most 1024 characters saying what the skill does and when to use it. Quote the description
  if it contains `: ` or ` #`.
- Name MCP tools by their bare names. Each harness prefixes MCP tool names differently, and the
  prefix also depends on how the server was added, so a prefixed name breaks in some setups.
- Use regular files only. Codex does not copy symlinks when it installs a plugin.
- Add the skill to the table at the top of this README. The manifests need no change: both
  harnesses discover `skills/` on their own.

Before a pull request, run:

```sh
sh scripts/check.sh                 # offline; needs python3
claude plugin validate .            # Claude Code's validator
python3 ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .   # Codex's validator; needs PyYAML
```

`claude plugin validate .` warns that `.claude-plugin/plugin.json` has no `version`. The Codex
manifest requires one: bump `version` in `.codex-plugin/plugin.json` with each release.

## License

[Apache License 2.0](LICENSE).
