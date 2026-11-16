#!/usr/bin/env bash
# The /charter-create launcher (#778): runs `skillc charter evidence` or
# `skillc charter create` from any working directory. It finds skillc through
# its own real path, exactly as the /skill-gauntlet launcher does (#763). No
# path is written here: every path is derived at run time.
#
# When skillc cannot be used it prints one `CHARTER_CREATE: cannot find a
# usable skillc (...)` line and exits 2. Otherwise it runs the command with the
# checkout's own environment (no PATH lookup, no uv needed), and its output and
# exit code are the command's own (docs/specs/charter-create.md).
set -u
# A caller's PYTHONPATH could import another skillc. Drop it.
unset PYTHONPATH

refuse() {
    echo "CHARTER_CREATE: cannot find a usable skillc ($1)" >&2
    exit 2
}

case "${1:-}" in
    evidence|create) ;;
    *) echo "CHARTER_CREATE: usage: charter.sh evidence|create <collection> <skill> ..." >&2; exit 2 ;;
esac

self=$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null) || refuse "the launcher's own path cannot be resolved"
# <checkout>/.claude/skills/charter-create/scripts/charter.sh
checkout=$(cd -- "$(dirname -- "$self")/../../../.." 2>/dev/null && pwd -P) || refuse "the checkout above the skill is missing"
[ -f "$checkout/pyproject.toml" ] && [ -f "$checkout/skillc/charter_create.py" ] \
    || refuse "no skillc checkout with charter create at the skill's location"
env_dir="${UV_PROJECT_ENVIRONMENT:-.venv}"
case "$env_dir" in /*) ;; *) env_dir="$checkout/$env_dir" ;; esac
python="$env_dir/bin/python"
[ -x "$python" ] || refuse "the checkout has no synced environment; run uv sync in the skillc checkout"
# A runnable python is not a usable skillc: this environment must import THIS
# checkout's charter create (-P: never from the caller's directory).
(cd / && "$python" -P -c 'import sys, skillc.cli, skillc.charter_create as c
sys.exit(0 if c.__file__.startswith(sys.argv[1] + "/") else 1)' "$checkout" >/dev/null 2>&1) \
    || refuse "the checkout's environment does not import this checkout's charter create; run uv sync in the skillc checkout"
exec "$python" -P -m skillc.cli charter "$@"
