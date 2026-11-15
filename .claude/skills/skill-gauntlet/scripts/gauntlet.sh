#!/usr/bin/env bash
# The /skill-gauntlet launcher (#763, #774): runs `skillc gauntlet run` from
# any working directory. In the COPY `make install-skill` writes to
# ~/.claude/skills/skill-gauntlet it finds skillc through the copy's locator,
# `.skillc-checkout` (written at install time, `~/` expanded here, never
# committed). In the repository, with no locator, it uses its own real path.
# No path is written in this file: every path is derived at run time.
#
# When skillc cannot be used it prints one `SKILL_GAUNTLET: cannot find a
# usable skillc (...)` line and exits 2 - never a ROUND line, so never a
# verdict. Otherwise it runs the engine with the checkout's own environment
# (no PATH lookup, no uv needed), and its output and exit code are the
# engine's own (docs/specs/gauntlet.md).
set -u
# -P keeps the caller's directory off sys.path, but PYTHONPATH would still be
# honoured, so a caller's PYTHONPATH could import another skillc for the check
# or the run (or the engine's round subprocesses, which inherit it). Drop it.
unset PYTHONPATH

refuse() {
    echo "SKILL_GAUNTLET: cannot find a usable skillc ($1)" >&2
    exit 2
}

self=$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null) || refuse "the launcher's own path cannot be resolved"
skill_dir=$(cd -- "$(dirname -- "$self")/.." 2>/dev/null && pwd -P) || refuse "the skill directory cannot be resolved"
locator="$skill_dir/.skillc-checkout"
if [ -f "$locator" ]; then
    # An installed copy: the locator names the main checkout, HOME-relative.
    IFS= read -r located < "$locator" || refuse "the locator .skillc-checkout cannot be read; re-run make install-skill"
    case "$located" in "~/"*) located="$HOME/${located#\~/}" ;; esac
    checkout=$(cd -- "$located" 2>/dev/null && pwd -P) \
        || refuse "the checkout the locator names is missing; re-run make install-skill from the skillc checkout"
else
    # <checkout>/.claude/skills/skill-gauntlet/scripts/gauntlet.sh
    checkout=$(cd -- "$skill_dir/../../.." 2>/dev/null && pwd -P) || refuse "the checkout above the skill is missing"
fi
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
# ... and the modules it imports must be EXACTLY this checkout's files (#765).
# "Somewhere under the checkout" also matches a non-editable install in the
# checkout's own .venv (site-packages/skillc/), which a git pull never updates.
# realpath on both sides; the checkout itself was derived with `pwd -P`.
# The reason names each module relative to the checkout, never an account path.
bad_import=
why=$(cd / && "$python" -P -c 'import os, sys
root = os.path.realpath(sys.argv[1])
try:
    import skillc.cli as c, skillc.gauntlet as g
except Exception as exc:
    print(f"the environment of the checkout cannot import skillc ({type(exc).__name__})"); sys.exit(1)
bad = []
for mod, rel in ((g, "skillc/gauntlet.py"), (c, "skillc/cli.py")):
    got = os.path.realpath(mod.__file__ or "")
    if got != os.path.join(root, rel):
        where = os.path.relpath(got, root) if got.startswith(root + os.sep) else "outside the checkout"
        bad.append(f"{mod.__name__} is {where}, not {rel}")
if bad:
    print("; ".join(bad)); sys.exit(1)' "$checkout" 2>/dev/null) || bad_import=1
why=${why:-the environment of the checkout does not import skillc}
[ -z "$bad_import" ] || refuse "$why; run uv sync in the skillc checkout (an editable install)"
# An installed copy that differs from the checkout's skill (a git pull since
# the install) is WARNED about, never blocked: the verdict and exit code below
# are the engine's whatever this prints.
if [ -f "$locator" ]; then
    "$python" -P -c 'import os, sys
def files(root):
    out = {}
    for d, _, names in os.walk(root):
        for n in names:
            rel = os.path.relpath(os.path.join(d, n), root)
            if rel not in (".skillc-checkout", ".skillc-install"):
                with open(os.path.join(d, n), "rb") as f:
                    out[rel] = f.read()
    return out
sys.exit(0 if files(sys.argv[1]) == files(sys.argv[2]) else 1)' "$skill_dir" "$checkout/.claude/skills/skill-gauntlet" \
        >/dev/null 2>&1 \
        || echo "SKILL_GAUNTLET: warning: this installed copy differs from the checkout's .claude/skills/skill-gauntlet; re-run make install-skill" >&2
fi
# Invoked explicitly, never a bare `skillc` from PATH. Its output and exit code are the engine's.
exec "$python" -P -m skillc.cli gauntlet run "$@"
