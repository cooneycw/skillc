#!/usr/bin/env bash
# The /skill-gauntlet launcher (#763): runs `skillc gauntlet run` from any
# working directory. It finds skillc through its own real path, so it works
# when the skill is reached through the ~/.claude/skills/skill-gauntlet link
# that `make install-skill` creates. No path is written here: every path is
# derived at run time.
#
# When skillc cannot be used it prints one `SKILL_GAUNTLET: cannot find a
# usable skillc (...)` line and exits 2 - never a ROUND line, so never a
# verdict. Otherwise it runs the engine with the checkout's own environment
# (no PATH lookup, no uv needed), and its output and exit code are the
# engine's own (docs/specs/gauntlet.md).
set -u

refuse() {
    echo "SKILL_GAUNTLET: cannot find a usable skillc ($1)" >&2
    exit 2
}

self=$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null) || refuse "the launcher's own path cannot be resolved"
# <checkout>/.claude/skills/skill-gauntlet/scripts/gauntlet.sh
checkout=$(cd -- "$(dirname -- "$self")/../../../.." 2>/dev/null && pwd -P) || refuse "the checkout above the skill is missing"
[ -f "$checkout/pyproject.toml" ] && [ -f "$checkout/skillc/gauntlet.py" ] \
    || refuse "no skillc checkout with the gauntlet engine at the skill's location; reinstall with make install-skill"
# The checkout's own environment (uv's default, or UV_PROJECT_ENVIRONMENT, which
# uv resolves against the project root - so a relative one is resolved there too).
env_dir="${UV_PROJECT_ENVIRONMENT:-.venv}"
case "$env_dir" in /*) ;; *) env_dir="$checkout/$env_dir" ;; esac
python="$env_dir/bin/python"
[ -x "$python" ] || refuse "the checkout has no synced environment; run uv sync in the skillc checkout"
# A runnable python is not a usable skillc: ask THIS environment to import THIS
# checkout's engine (-P: never from the caller's directory).
# ... and the engine it imports must be THIS checkout's, not some other skillc.
(cd / && "$python" -P -c 'import sys, skillc.cli, skillc.gauntlet as g
sys.exit(0 if g.__file__.startswith(sys.argv[1] + "/") else 1)' "$checkout" >/dev/null 2>&1) \
    || refuse "the checkout's environment does not import this checkout's gauntlet engine; run uv sync in the skillc checkout"
# Invoked explicitly, never a bare `skillc` from PATH. Its output and exit code are the engine's.
exec "$python" -P -m skillc.cli gauntlet run "$@"
