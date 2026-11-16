#!/bin/sh
# Offline checks for the skills and the Claude Code / Codex plugin manifests.
# Usage: sh scripts/check.sh   (needs python3 for JSON; exits non-zero on any failure)
set -u

root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd) || exit 2
cd "$root" || exit 2

if ! command -v python3 >/dev/null 2>&1; then
  echo "check.sh: python3 is required to parse the JSON manifests" >&2
  exit 2
fi

failures=0
fail() {
  printf 'FAIL: %s\n' "$*" >&2
  failures=$((failures + 1))
}

strip_quotes() {
  sed -e 's/[[:space:]]*$//' -e 's/^"\(.*\)"$/\1/' -e "s/^'\\(.*\\)'\$/\\1/"
}

# 1. Skills: skills/<name>/SKILL.md with YAML frontmatter whose name equals the directory.
skill_count=0
if [ ! -d skills ]; then
  fail "skills/ directory is missing"
fi
for dir in skills/*; do
  [ -d "$dir" ] || continue
  dir_name=${dir#skills/}
  skill_count=$((skill_count + 1))
  file="skills/$dir_name/SKILL.md"
  if [ ! -f "$file" ]; then
    fail "$dir: no SKILL.md"
    continue
  fi
  frontmatter=$(awk '
    NR == 1 { if ($0 != "---") { bad = 1; exit } next }
    $0 == "---" { closed = 1; exit }
    { print }
    END { if (bad) exit 3; if (!closed) exit 4 }
  ' "$file")
  case $? in
    0) ;;
    3) fail "$file: first line must be '---' (YAML frontmatter, LF line endings)"; continue ;;
    *) fail "$file: frontmatter is not closed by a '---' line"; continue ;;
  esac

  name=$(printf '%s\n' "$frontmatter" | sed -n 's/^name:[[:space:]]*//p' | head -n 1 | strip_quotes)
  raw_description=$(printf '%s\n' "$frontmatter" | sed -n 's/^description:[[:space:]]*//p' | head -n 1 | sed 's/[[:space:]]*$//')
  description=$(printf '%s\n' "$raw_description" | strip_quotes)

  if [ -z "$name" ]; then
    fail "$file: frontmatter has no 'name'"
  elif [ "$name" != "$dir_name" ]; then
    fail "$file: name '$name' does not match its directory '$dir_name'"
  fi
  if ! printf '%s\n' "$dir_name" | grep -Eq '^[a-z0-9]+(-[a-z0-9]+)*$'; then
    fail "$dir: a skill name is lowercase letters, digits and single hyphens"
  fi
  if [ "${#dir_name}" -gt 64 ]; then
    fail "$dir: a skill name is at most 64 characters"
  fi

  case $raw_description in
    '' | '|'* | '>'*)
      fail "$file: 'description' must be a non-empty single-line value"
      ;;
    \"* | \'*) ;;
    *': '* | *' #'*)
      fail "$file: an unquoted description must not contain ': ' or ' #' (quote it)"
      ;;
  esac
  if [ "${#description}" -gt 1024 ]; then
    fail "$file: description is longer than 1024 characters"
  fi
done
if [ "$skill_count" -eq 0 ]; then
  fail "skills/ holds no skill directories"
fi

# 2. Manifests: valid JSON, consistent names, and every listed plugin resolves to this repository.
python3 - <<'PY'
import json
import re
import sys
from pathlib import Path

root = Path.cwd().resolve()
failures = []


def fail(message):
    failures.append(message)


def load(relative):
    path = root / relative
    if not path.is_file():
        fail(f"{relative}: missing")
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        fail(f"{relative}: not valid JSON ({error})")
        return None
    if not isinstance(data, dict):
        fail(f"{relative}: must hold a JSON object")
        return None
    return data


def manifest_name(path):
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("name")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        return None


def non_empty(value):
    return isinstance(value, str) and value.strip() != ""


def resolve_local(relative_path, owner):
    if not isinstance(relative_path, str) or not (relative_path in (".", "./") or relative_path.startswith("./")):
        fail(f"{owner}: plugin source path {relative_path!r} must start with './'")
        return None
    target = (root / relative_path).resolve()
    if target != root and root not in target.parents:
        fail(f"{owner}: plugin source path {relative_path!r} leaves the repository")
        return None
    if not target.is_dir():
        fail(f"{owner}: plugin source path {relative_path!r} is not a directory")
        return None
    return target


claude_plugin = load(".claude-plugin/plugin.json")
claude_market = load(".claude-plugin/marketplace.json")
codex_plugin = load(".codex-plugin/plugin.json")
codex_market = load(".agents/plugins/marketplace.json")

if claude_plugin is not None:
    if not non_empty(claude_plugin.get("name")):
        fail(".claude-plugin/plugin.json: 'name' is missing")
    extra_skills = claude_plugin.get("skills", [])
    for path in [extra_skills] if isinstance(extra_skills, str) else extra_skills:
        resolve_local(path, ".claude-plugin/plugin.json skills")

if codex_plugin is not None:
    for field in ("name", "version", "description"):
        if not non_empty(codex_plugin.get(field)):
            fail(f".codex-plugin/plugin.json: '{field}' is missing")
    version = codex_plugin.get("version")
    if isinstance(version, str) and not re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?", version):
        fail(f".codex-plugin/plugin.json: version {version!r} is not semver")
    skills = codex_plugin.get("skills")
    if skills is not None and str(skills).rstrip("/") != "./skills":
        fail(".codex-plugin/plugin.json: 'skills' must be './skills/' (the Codex plugin contract)")
    interface = codex_plugin.get("interface")
    if not isinstance(interface, dict):
        fail(".codex-plugin/plugin.json: 'interface' is missing")
    else:
        for field in ("displayName", "shortDescription", "longDescription", "developerName", "category"):
            if not non_empty(interface.get(field)):
                fail(f".codex-plugin/plugin.json: 'interface.{field}' is missing")

if claude_plugin is not None and codex_plugin is not None and claude_plugin.get("name") != codex_plugin.get("name"):
    fail("the Claude and Codex plugin manifests name different plugins")

if claude_market is not None:
    if not non_empty(claude_market.get("name")):
        fail(".claude-plugin/marketplace.json: 'name' is missing")
    plugins = claude_market.get("plugins")
    if not isinstance(plugins, list) or not plugins:
        fail(".claude-plugin/marketplace.json: 'plugins' must be a non-empty list")
        plugins = []
    for entry in plugins:
        owner = f".claude-plugin/marketplace.json plugin {entry.get('name')!r}"
        target = resolve_local(entry.get("source"), owner)
        if target is None:
            continue
        manifest = target / ".claude-plugin" / "plugin.json"
        if not manifest.is_file():
            fail(f"{owner}: {manifest.relative_to(root)} does not exist")
            continue
        if manifest_name(manifest) != entry.get("name"):
            fail(f"{owner}: name differs from {manifest.relative_to(root)}")
        if not (target / "skills").is_dir():
            fail(f"{owner}: the plugin has no skills/ directory")

if codex_market is not None:
    name = codex_market.get("name")
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        fail(".agents/plugins/marketplace.json: 'name' must match [A-Za-z0-9_-]+")
    plugins = codex_market.get("plugins")
    if not isinstance(plugins, list) or not plugins:
        fail(".agents/plugins/marketplace.json: 'plugins' must be a non-empty list")
        plugins = []
    for entry in plugins:
        owner = f".agents/plugins/marketplace.json plugin {entry.get('name')!r}"
        source = entry.get("source")
        if not isinstance(source, dict) or source.get("source") != "local":
            fail(f"{owner}: source must be {{'source': 'local', 'path': ...}}")
            continue
        policy = entry.get("policy") if isinstance(entry.get("policy"), dict) else {}
        if policy.get("installation") not in ("NOT_AVAILABLE", "AVAILABLE", "INSTALLED_BY_DEFAULT"):
            fail(f"{owner}: policy.installation is missing or unknown")
        if policy.get("authentication") not in ("ON_INSTALL", "ON_USE"):
            fail(f"{owner}: policy.authentication is missing or unknown")
        if not non_empty(entry.get("category")):
            fail(f"{owner}: 'category' is missing")
        target = resolve_local(source.get("path"), owner)
        if target is None:
            continue
        manifest = target / ".codex-plugin" / "plugin.json"
        if not manifest.is_file():
            fail(f"{owner}: {manifest.relative_to(root)} does not exist")
            continue
        if manifest_name(manifest) != entry.get("name"):
            fail(f"{owner}: name differs from {manifest.relative_to(root)}")
        if not (target / "skills").is_dir():
            fail(f"{owner}: the plugin has no skills/ directory")

if claude_market is not None and codex_market is not None:
    if claude_market.get("name") != codex_market.get("name"):
        fail("the Claude and Codex marketplaces have different names, so the install commands differ")
    claude_names = sorted(p.get("name") for p in claude_market.get("plugins") or [])
    codex_names = sorted(p.get("name") for p in codex_market.get("plugins") or [])
    if claude_names != codex_names:
        fail(f"the marketplaces list different plugins: Claude {claude_names}, Codex {codex_names}")

for message in failures:
    print(f"FAIL: {message}", file=sys.stderr)
sys.exit(min(len(failures), 100))
PY
failures=$((failures + $?))

# 3. No symlinks: Codex copies only regular files and directories when it installs a plugin.
links=$(find . -path ./.git -prune -o -type l -print)
if [ -n "$links" ]; then
  fail "symlinks are not installed by Codex; replace them with files: $(printf '%s ' $links)"
fi

# 4. No harness-specific MCP tool prefix: skills name MCP tools by their bare names.
prefix='mcp''__'
prefixed=$(grep -rIl --exclude-dir=.git -e "$prefix" . || true)
if [ -n "$prefixed" ]; then
  for file in $prefixed; do
    fail "$file: names an MCP tool with the harness prefix '$prefix'; use the bare tool name"
  done
fi

if [ "$failures" -ne 0 ]; then
  printf 'check.sh: %d problem(s)\n' "$failures" >&2
  exit 1
fi
printf 'check.sh: OK (%d skills, 4 manifests)\n' "$skill_count"
