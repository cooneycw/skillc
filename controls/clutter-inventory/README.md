# Clutter inventory controls (#619)

Every `not_clean` case is a planted surviving addition on a required surface.
The instrument must return `NOT_CLEAN`, `clean: false`, and a nonzero clutter
count for each one. Their declaration, baseline and unrelated surfaces remain
identical to the positive twin. A no-CPP baseline is not required to have CPP
state, but added undeclared CPP state receives the same clutter verdict.

Both clean orders must return `CLEAN`: the actual Git fixture exercises removing
the worktree before dropping its stash, and dropping the stash before removing
the worktree. The resulting delivered product is the same. These are different
cleanup sequences, not merely reordered JSON fields.

`missing-controls.json` is the qualification-population negative control. It is
refused, so deleting the planted-input population cannot quietly turn the
instrument's tests into an empty success.

The targeted tests also exercise real fixture refs, worktree registrations,
stash reflogs, ignored files, state files/entries, kernel process identities and
deleted/recreated cwd. Daemon transport is fake in local qualification; missing,
partial, duplicate and foreign inspection populations remain UNKNOWN. Physical
multi-container qualification and live workflows are separate from these controls.
