#!/usr/bin/env bash
# The /skill-gauntlet launcher (#763): runs `skillc gauntlet run` from any
# working directory. It finds skillc through its own real path, so it works
# when the skill is reached through the ~/.claude/skills/skill-gauntlet link
# that `make install-skill` creates. No path is written here: every path is
# derived at run time.
#
# When skillc cannot be used it prints one `SKILL_GAUNTLET: cannot find a
# usable skillc (...)` line and exits 2 - never a ROUND line, so never a
# verdict. Otherwise it runs the engine, and its output and exit code are
# the engine's own (docs/specs/gauntlet.md).
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
command -v uv >/dev/null 2>&1 || refuse "uv is not on PATH"
[ -x "${UV_PROJECT_ENVIRONMENT:-$checkout/.venv}/bin/python" ] \
    || refuse "the checkout has no synced environment; run uv sync in the skillc checkout"
exec uv run --project "$checkout" --no-sync skillc gauntlet run "$@"
