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
# Never write inside the checkout (#774, Kyle containers): it may be a pinned,
# READ-ONLY checkout. No bytecode caches; the engine writes only the collection.
export PYTHONDONTWRITEBYTECODE=1

refuse() {
    echo "SKILL_GAUNTLET: cannot find a usable skillc ($1)" >&2
    exit 2
}

self=$(readlink -f -- "${BASH_SOURCE[0]}" 2>/dev/null) || refuse "the launcher's own path cannot be resolved"
skill_dir=$(cd -- "$(dirname -- "$self")/.." 2>/dev/null && pwd -P) || refuse "the skill directory cannot be resolved"
locator="$skill_dir/.skillc-checkout"
if [ -n "${SKILLC_CHECKOUT:-}" ]; then
    # Kyle containers (#774, owner 2026-11-16): Kyle provides the checkout and
    # names it here, read BEFORE the locator. An absolute path only; the exact
    # module check below still decides whether it is usable.
    case "$SKILLC_CHECKOUT" in /*) ;; *) refuse "SKILLC_CHECKOUT must be an absolute path" ;; esac
    checkout=$(cd -- "$SKILLC_CHECKOUT" 2>/dev/null && pwd -P) || refuse "SKILLC_CHECKOUT names a missing directory"
elif [ -f "$locator" ]; then
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
# The runtime (#774, Kyle's contract): SKILLC_RUNTIME when set (an ABSOLUTE
# path), else the checkout's own .venv - Kyle stages its frozen runtime there.
# The caller's UV_PROJECT_ENVIRONMENT is IGNORED and never passed on: uv applies
# it to every project, so a session-wide one points at the worker's project,
# never at this checkout.
unset UV_PROJECT_ENVIRONMENT
if [ -n "${SKILLC_RUNTIME:-}" ]; then
    case "$SKILLC_RUNTIME" in /*) ;; *) refuse "SKILLC_RUNTIME must be an absolute path" ;; esac
    env_dir="$SKILLC_RUNTIME"
else
    env_dir="$checkout/.venv"
fi
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
# The CHECKOUT side is its git-TRACKED skill files only (#738), so an untracked
# file there (the owner's GAUNTLET.json record) is not drift. Three cases:
#   - a git work tree: `git ls-files`;
#   - NOT a repository at all (no .git up the tree: Kyle's `git archive`
#     export): walked in full - an export holds exactly its commit's tracked files;
#   - a .git is there but git is missing or fails on it (it refuses a repository
#     another user owns): SKIPPED, said in one note. Never a walk, which would
#     count untracked files, and never `-c safe.directory`: such a repository's
#     config can name a program for git to run (core.fsmonitor).
# The INSTALLED side is walked in full: an extra file there is drift.
if [ -f "$locator" ]; then
    # Only REGULAR files are opened (lstat first): a FIFO or a link is never read,
    # so the check cannot block the engine; it, or any read error, is a warning.
    # Exit 0: no drift; 3: not checked (the reason on stdout); anything else: drift.
    drift_note=$("$python" -P -c 'import os, stat, subprocess, sys
def oops(exc):
    raise exc
def walk(root):
    out = []
    for d, dirs, names in os.walk(root, onerror=oops):
        for n in dirs:
            if stat.S_ISLNK(os.lstat(os.path.join(d, n)).st_mode):
                raise OSError(f"{n} is a directory link")  # os.walk lists it, never enters it
        out += [os.path.relpath(os.path.join(d, n), root) for n in names]
    return out
def git(src, *args):
    # The caller'"'"'s GIT_* variables (GIT_DIR, GIT_WORK_TREE, ...) never steer it.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(["git", "-C", src, *args], capture_output=True, env=env, check=False)
def tracked(src):
    """The checkout side: its git-TRACKED files, or None with the reason printed."""
    try:
        inside = git(src, "rev-parse", "--is-inside-work-tree")
        if inside.returncode == 0 and inside.stdout.strip() == b"true":
            done = git(src, "ls-files", "-z", "--cached", "--", ".")
            if done.returncode == 0:
                return [r.decode() for r in done.stdout.split(b"\0") if r]
            print("git cannot list the checkout'"'"'s tracked files"); sys.exit(3)
    except FileNotFoundError:
        missing = True
    else:
        missing = False
    d = os.path.abspath(src)
    while True:
        if os.path.lexists(os.path.join(d, ".git")):
            print("git is not installed" if missing else "git cannot read the checkout'"'"'s repository")
            sys.exit(3)
        if os.path.dirname(d) == d:
            return walk(src)  # an export (`git archive`): exactly its commit'"'"'s tracked files
        d = os.path.dirname(d)
def files(root, rels):
    out = {}
    for rel in rels:
        if os.sep not in rel and rel.startswith("."):
            continue  # top-level dotfiles belong to the installer
        path = os.path.join(root, rel)
        mode = os.lstat(path).st_mode
        if not stat.S_ISREG(mode):
            raise OSError(f"{rel} is not a regular file")
        with open(path, "rb") as f:
            out[rel] = (f.read(), bool(mode & 0o100))
    return out
copy, src = sys.argv[1], sys.argv[2]
listed = tracked(src)
try:
    a, b = files(copy, walk(copy)), files(src, listed)
except OSError:
    sys.exit(1)
sys.exit(0 if a == b and "SKILL.md" in a else 1)' "$skill_dir" "$checkout/.claude/skills/skill-gauntlet" 2>/dev/null)
    case $? in
        0) ;;
        3) echo "SKILL_GAUNTLET: note: drift not checked (${drift_note:-no reason given}); the engine still runs" >&2 ;;
        *) echo "SKILL_GAUNTLET: warning: this installed copy differs from the checkout's .claude/skills/skill-gauntlet; re-run make install-skill" >&2 ;;
    esac
fi
# Invoked explicitly, never a bare `skillc` from PATH. Its output and exit code are the engine's.
exec "$python" -P -m skillc.cli gauntlet run "$@"
