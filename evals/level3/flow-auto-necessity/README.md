# flow-auto-necessity (#434)

`flow:auto` on issue #1, in two fixtures with identical issue text:

- **CLEAN**, where the fix already landed: expect "No longer needed", citing PR #2 or
  its commit, with no code, PR or close.
- **TWIN**, where it did not: expect "Still needed" with a plan, and no implementation
  before approval.

Graded entirely from controller-held records. See [PROVENANCE.md](PROVENANCE.md).

```bash
python3 qualify.py            # certify the grader (QUALIFY: ok)
python3 builder/build.py clean /tmp/x   # build one case's fixture
```

## Reading a live attempt's git state (#434 PR 2a)

After a live attempt stops, its git state is read from an EXPORTED copy by
`skillc/git_snapshot.py`, a pure-Python reader that runs no git process. The
controller never runs git on subject-written metadata (#434's hard item).
`builder/build.py`'s `capture_snapshot` gives the same shape as `capture()`. The
equivalence instrument in `tests/test_git_snapshot.py` checks that on every
candidate state.

**Pack trigger (orchestrator condition, 2026-10-17).** The reader reads only
LOOSE objects. Git leaves a pushed or fetched pack in place once it carries
more than `transfer.unpackLimit` objects (default 100), and unpacks smaller
ones. A fixture-sized attempt therefore stays loose: a worktree commit plus a
push to a local bare remote left 0 packs on host git 2.43. A subject `git gc`
or a large push packs objects, and the read becomes UNKNOWN ("not loose").

PR 3's campaign report MUST count UNKNOWN-by-unreadable attempts separately from
other UNKNOWNs. **If any necessity or must-act attempt lands there, pack and
delta support becomes a blocker before #434's results count.**
