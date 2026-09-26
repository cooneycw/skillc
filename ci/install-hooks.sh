#!/usr/bin/env bash
# Install the pre-push secret scan (#47) into this repository's hooks.
#
# It installs into the COMMON git dir, so one install covers every worktree.
# It does not set core.hooksPath: that would switch off every hook already in
# .git/hooks (the CPP stash guard lives there). It installs a shim that runs the
# pushing worktree's own ci/hooks/pre-push, so the hook tracks the branch
# instead of going stale as a copy. It will not overwrite a pre-push it did not
# write.
set -euo pipefail

marker="skillc-pre-push-shim"
[[ -z "$(git config --get core.hooksPath)" ]] || {
  echo "install-hooks: core.hooksPath is set; hooks in .git/hooks would not run" >&2
  exit 1
}
hooks="$(git rev-parse --path-format=absolute --git-common-dir)/hooks"
target="$hooks/pre-push"
if [[ -e "$target" ]] && ! grep -q "$marker" "$target"; then
  echo "install-hooks: $target exists and is not ours; not overwriting" >&2
  exit 1
fi
mkdir -p "$hooks"
cat > "$target" << SHIM
#!/usr/bin/env bash
# $marker: installed by skillc ci/install-hooks.sh (#47)
hook="\$(git rev-parse --show-toplevel)/ci/hooks/pre-push"
[[ -x "\$hook" ]] || { echo "pre-push: REFUSED - \$hook missing; this branch predates the secret scan - rebase on main" >&2; exit 1; }
exec "\$hook" "\$@"
SHIM
chmod +x "$target"
echo "install-hooks: installed $target"
