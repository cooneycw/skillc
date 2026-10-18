- **A pure-Python reader of an exported attempt's git state** (#434, PR 2a).
  A live attempt's repository and remote are subject-writable, so after the
  attempt stops the controller must not run git on them, even on an exported
  copy: subject config, hooks, replace refs or grafts would run or steer code
  on the host.
  - `skillc/git_snapshot.py` reads the raw bytes instead and starts no git
    process. It reads:
    - refs and packed-refs, including each worktree's private refs;
    - each worktree's HEAD, cross-checked both ways against its registration;
    - loose objects: one complete zlib stream, hash-checked, size-capped;
    - index v2/v3: checksummed, extensions walked and a mandatory one
      refused, merge stages and intent-to-add kept as their own states;
    - file bytes and modes.
    Commits must have a well-formed header; tree entries, packed refs and
    index entries must be unique; index name lengths and padding are checked.
    Commit, tree and filesystem walks share depth, entry and byte budgets.
  - It opens every path component with `O_NOFOLLOW` and files with
    `O_NONBLOCK`, so a planted FIFO cannot block it.
  - Anything it cannot read faithfully raises `Unreadable`, which reads as
    UNKNOWN: a packed object, index v4, a symlink, FIFO or oversize file,
    alternates, a redirected `commondir`, or a `gitdir` outside the root.
  - `SnapshotGitRemote` serves it as a read-only `GitRemote` for the fixture
    service's finalize; every write raises.
  - `builder/build.py`'s `capture_snapshot` gives PR 1's capture shape. An
    equivalence instrument checks it against host git on all 43 PR 1
    candidate states plus 7 extra ones (a linked worktree's HEAD, an
    index-only change, a mode change, a deleted file, a commit parked on a
    worktree-private ref or on the remote's detached HEAD, an intent-to-add
    entry). A reader that ignores
    the index is caught as non-equivalent.
  - Each of 36 reader mutations goes red.
  - The pack trigger for PR 3 is recorded in the task README.
