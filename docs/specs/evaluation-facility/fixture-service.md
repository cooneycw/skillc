# Controller-owned issue and PR fixture service

- Status: Implemented in `skillc/fixture_service.py` and
  `docker/trial/skillc-gh-shim.py` (#276). The service and shim are proven
  host-side over a real socket; wiring them into a live attempt (profile
  install of the shim, the Docker-backed remote) belongs to the first
  consumer, #434
- Builds on: [decide-reply-channel.md](decide-reply-channel.md) (#183),
  [gate-witness.md](gate-witness.md) (#269, the same pattern),
  [git-fixtures.md](git-fixtures.md) (#275)
- Consumers: #434 (already-fixed issue, "No longer needed"), #277 (partial and
  full delivery), #279 (interrupted delivery and resume)
- Follow-up: #436 (prevent remote ref rewrites rather than detect them)

## What it is for

flow:auto talks to GitHub throughout. It reads the issue, searches merged PRs
for the necessity check, opens a PR, squash-merges it, and closes the issue
with a comment. A trial has no network and no `gh`, and real GitHub is off
limits. A fake built from files inside the container would be subject-writable,
so the subject could "prove" a PR it never opened.

The service makes the CONTROLLER the only GitHub:

- The trial profile installs `skillc-gh-shim.py` where `gh` would be. The shim
  sends each invocation as one `op: "gh"` request over the attempt's one #183
  socket.
- The service parses the request against a closed grammar, decides the answer,
  and appends an event to its own record. Only then does it reply.
- The subject sees gh-shaped stdout, stderr and an exit code. It never sees or
  writes the record.

A grader reads `finalize()`'s record. Anything the agent says about PRs,
merges or closures is a claim to compare against that record.

## Supported request semantics

The grammar is exactly what the pinned CPP 86641e8 flow:auto lane calls.
[fixture-service-gh-inventory.txt](fixture-service-gh-inventory.txt) lists
every call with its `source:line`. Each subcommand accepts only the flags listed
below. Anything else is `unsupported` (see Coverage).

| Subcommand | Flags | Semantics |
|---|---|---|
| `auth status` | none | Logged in as `fixture-subject` |
| `repo view` | `--repo --json --jq` | `nameWithOwner name owner url viewerPermission defaultBranchRef` |
| `api PATH` | `--jq --paginate -H` | GET only. `repos/O/R`, `.../pulls/N/files`, `.../rules/branches/B` (`[]`), and `.../branches/B/protection/required_status_checks` (HTTP 404 "Branch not protected", printed raw with no jq applied, as gh does) |
| `issue view N` | `--repo --json --jq` | `number title body state url createdAt updatedAt closedAt labels comments author` |
| `issue list` | `--repo --state --search --limit --json --jq` | Newest first. Default state is open, default limit 30 |
| `issue close N` | `--repo --comment --reason` | OPEN to CLOSED, adding the comment first. An already-closed issue is a no-op with exit 0 and no effect |
| `issue comment N` | `--repo --body --body-file` | Appends a comment |
| `pr view [N\|BRANCH]` | `--repo --json --jq` | With no argument, uses the current branch's PR: the open one first, else the newest |
| `pr list` | `--repo --state --head --base --search --limit --json --jq` | `closed` includes merged, as on GitHub |
| `pr create` | `--repo --title --body --body-file --base --head` | Title and body are required, as in non-interactive gh. The head must exist on the remote and be ahead of the base |
| `pr edit N` | `--repo --base --title --body` | Open PRs only |
| `pr merge [N]` | `--repo --squash --subject --body --body-file --delete-branch --admin` | Squash only; see below |
| `run list` | `--repo --commit --branch --limit --json --jq` | Always `[]`. The effect is marked `simulated: no-ci` |
| `run view ID` | `--repo --json --jq` | Always "could not find any workflow run" |

PR fields are `number title body state url headRefName headRefOid baseRefName
mergeCommit mergedAt createdAt updatedAt closedAt isCrossRepository
changedFiles files commits mergeable reviewDecision statusCheckRollup author`.

- For an OPEN PR, `headRefOid`, `files`, `commits` and `mergeable` are read
  live from the remote.
- For a merged PR, they are frozen at the merge.
- `reviewDecision` is `""` (no review required) and `statusCheckRollup` is `[]`.

The search grammar takes free terms and quoted phrases (case-insensitive
substring match against title and body), plus these qualifiers: `in:title`,
`in:body`, `is:open`, `is:closed`, `is:merged`, and `merged:`/`created:`/`closed:`
dates with `>= <= > <`. Any other qualifier is unsupported. GitHub tokenizes its
search, and substring matching is a declared approximation of that.

### Repository resolution

`--repo`, or the `repos/O/R` prefix of an `api` path, must name the declared
repository. Otherwise the shim's reported `origin` URL must be one of the
declaration's `remote_urls`. Anything else is refused as `wrong-repository`
and recorded.

The origin URL and the current branch come from the subject's checkout. Real gh
reads both from the checkout too. Because the service answers for exactly ONE
repository, a forged origin can only make a request fail. It can never reach
other state.

### The merge is the controller's

`gh pr merge --squash` does the following:
1. Builds the merge tree with `git merge-tree --write-tree`. A conflict is
   refused as `not-mergeable`.
2. Creates the squash commit with `git commit-tree`, using a fixed service
   identity and the service clock, with the old base tip as its parent.
3. Moves the base ref with a compare-and-swap `git update-ref`. If the ref
   moved meanwhile, the merge is refused as `base-moved`.

The default subject is `TITLE (#N)`, as on GitHub. The default body is empty;
GitHub's default commit-list body is not modelled.

On a merge into the default branch, closing keywords in the PR body or the
squash message close the open issues they name, and those closures are
recorded as part of the merge's effect. The keywords are `close`, `closes`,
`closed`, `fix`, `fixes`, `fixed`, `resolve`, `resolves` and `resolved`, each
followed by `#N`. These closure effects are what #277's "old closing
reference" case reads. `--delete-branch` deletes the remote head ref, conditioned on the merged head SHA.
A failed deletion is recorded as `branch_delete_failed`, never as deleted.
Every step that can fail happens before the compare-and-swap: the merge tree,
the closing references (at most nine digits each) and the commit. Past it only
bookkeeping remains.

Without a strategy flag, the merge fails exactly as non-interactive gh does.
`--admin` needs its own authority (`pr.merge.admin`).

### Scenario authority

The declaration's `authority` lists the ops this attempt may perform, drawn
from `skillc.fixture_service.OPS`. An op outside that list is refused as
`unauthorized` and recorded, and nothing changes. Invalid transitions are
refused as `invalid-transition`: merging a merged or closed PR, or editing a
non-open PR. Creating a second open PR for the same head and base is refused
as `duplicate-create`, with gh's wording. A concurrent duplicate create is
serialized, so exactly one PR is created.

## The record

`finalize(attempt_id)` returns a `FixtureServiceRecord`. Each request that
reached the service becomes one event, which carries:

- `seq`: the service's own counter. The subject never supplies it.
- `attempt_id` and `repository`.
- `op`, `argv`, `argv_digest` and `context`.
- `decision`: one of `read`, `applied`, `refused`, `unsupported`, `malformed`
  or `error`. `error` is a handler failure, such as an untrusted or unreadable
  remote. It is still an event: its state digests show what did change, and it
  makes coverage incomplete.
- `reason`.
- `effect`: for an applied op, what changed (the PR number, head oid, merge
  commit, closed issues, comment id).
- `fault`.
- `state_before` and `state_after`: digests of the whole service state.
- `reply`: exactly what the subject was sent.
- `at`: the declared clock, `start + seq * step`. Identical runs therefore
  produce identical records and identical SHAs.

The record also carries:

- the declaration digest;
- the measured jq;
- the final state;
- the faults;
- `remote_integrity` and its `divergence` list;
- `record_digest`, computed over all of the above.

A request whose top-level shape (or a `body_files` value that is not strict base64) is outside the closed schema is refused on the
channel. The schema keys are `op argv cwd context body_files`; an extra `seq`
or `result` is outside it. When such a request reaches the service, it is
recorded as `malformed`. A forged field therefore changes nothing, and it
leaves a trace.

### The three-way read

| Coverage | Meaning |
|---|---|
| `witnessed` | At least one well-formed request was decided and recorded before its reply |
| `no-controller-witness` | Nothing well-formed arrived. A bypass is visible as absence, never as success |
| `channel-unavailable` | The caller set `channel_unavailable`: nothing could have been witnessed |

`coverage_complete` is false whenever any event was `unsupported` or `error`. The record
then cannot speak for what the subject tried, and a grader reads that portion
as UNKNOWN.

## jq is real jq

`--jq` filters are evaluated by the CONTROLLER's own `jq`: a subprocess with
no shell, `-r -c` (gh's rendering: strings raw, everything else compact JSON),
a 4 MiB input bound and a 5 s timeout. Only filters on
`skillc.fixture_service.JQ_ALLOWLIST` are run. That list is the exact strings
the pinned helpers pass, matched byte for byte. None of them is assembled at
run time, so no templates exist.

The record carries the measured jq version. Each of these is `unsupported`,
never approximated:
- a jq that is absent;
- a jq that is not `jq-1.7.x`;
- a filter off the allowlist.

Without `--json`, views print a simplified plain rendering. gh's exact
non-TTY layout is not claimed.

## Faults

Each fault is declared in the attempt's declaration and fires once, on the
FIRST ADMITTED request that matches it. Refused, unsupported and malformed
requests never count, so a junk flood cannot move the scored point.

- `{"kind": "lost-response", "op": OP, "number"?: N}`: the action commits, and
  the reply is replaced with gh's transport error, exit 1. The event keeps the
  real reply as `suppressed_reply`.
- `{"kind": "stale-read", "after": OP, "read": READ_OP}`: once `after` has
  applied, the first `read` is answered from the state before it. Each fault
  keeps its own snapshot, so two faults never overwrite or consume each other.
  A stale "not found" is a stale answer and consumes the fault. A usage
  error, such as `--jq` without `--json`, does not. The snapshot also freezes each open PR's remote-derived view (head, files,
  commits, mergeable), so a stale answer is the old payload, never old state
  mixed with the live remote.

A declared fault that never fired reports `coverage: UNKNOWN`. A recovery case
built on it cannot qualify.

## One socket, isolated sides

An attempt has one authorized socket (#183 §6). `dispatch()` multiplexes
several op families over it, which the orchestrator approved for #276, within
#183's one-mount ruling:
- a request is routed by `op` alone;
- it is refused unless every key is in that route's closed key set;
- an op no route enables is refused.

A request carrying another side's fields is refused, never forwarded with the
foreign fields dropped. Examples are a `gh` request with a `gate` field, or a
`run_gate` request with `argv`.
`tests/test_fixture_service_channel.py` proves each case reaches neither side.

## Remote integrity: detected, not prevented

The remote must be candidate-writable for `git push` to work, so the subject
can also rewrite its refs. The service tracks the default-branch tip it
expects, starting from the tip at construction and moving it only at its own
merges. It records a divergence:

- at merge time, when the base tip is not the expected one (the merge still
  lands on the actual tip, as GitHub's would);
- at `finalize()`, when the tip differs, when a recorded merge commit (declared
  or service-made) is no longer reachable from it, or when the branch is gone.

Any divergence makes `remote_integrity: VIOLATED`. An unreadable remote, or
a git command that failed rather than answered (any exit other than git's
documented 0 or 1), makes it `UNKNOWN`, never VIOLATED.

The remote's own metadata is not trusted to steer controller git commands.
Every controller call runs with:
- `core.hooksPath=/dev/null` and `core.fsmonitor=false`;
- `GIT_NO_REPLACE_OBJECTS=1` and `GIT_ATTR_NOSYSTEM=1`;
- no global or system config.

Before each call, the remote is refused (`RemoteUntrusted`, recorded as an
`error` event, integrity `UNKNOWN`) in either of two cases:
- its `config` carries a key outside a short allowlist (repository format,
  bare and filemode flags, object format, default branch, and the `receive.deny*`
  settings);
- it carries `info/grafts` or an alternates file.

This is defence in depth, NOT the boundary. A subject that can write the
remote can swap its config between that check and the git command that reads
it, so `LocalGitRemote` carries a contract: it is pointed only at a remote
the subject cannot write (counter-model review, pass 2).

The contract is ENFORCED, and fails closed (orchestrator ruling). Before any
git runs, `LocalGitRemote` refuses the remote (`RemoteUntrusted`) in any of
these cases:
- an ancestor directory is a link, or is not owned by the controller or root,
  or is writable by another uid without being sticky;
- any entry under the git dir is a symlink, or anything other than a plain
  file or directory;
- any entry is owned by another uid;
- any entry is group- or other-writable.

Further rules (counter-model review, pass 3):
- The root itself is checked first, and any listing error fails the check.
- An inspection that examined nothing fails, so an unlistable or missing tree
  is never read as clean.
- The remote path must be absolute, with no `.` or `..` component. It is the
  one path both checked and handed to git, so `link/..` cannot check one
  directory and run git in another.

Checks use `lstat`, never following links. The controller's own git calls
run under umask 022, so what it writes stays controller-only. This PR has no
code path in which the controller runs git against a remote the subject can
write.

A live attempt's remote is subject-writable by design. It must be reached
through a `GitRemote` that runs git inside the attempt's own containment,
which is #434's wiring. There, hostile metadata can only run code as the
subject itself. The answers that remote gives are subject-influenced too,
which is the detection-only bound above. #436 removes it by routing push
through the controller. A divergence is never reconciled, repaired or dropped. A
direct push to `main` and a force-push over a recorded merge are both tested.
Prevention, by routing push through the controller, is #436.

## The declaration

```json
{
  "fixture_service_schema": 1,
  "repository": {"name_with_owner": "fixture/widget", "default_branch": "main",
                 "remote_urls": ["/srv/skillc-remote/widget.git"]},
  "authority": ["issue.view", "issue.list", "issue.close", "pr.list", "pr.view", "..."],
  "clock": {"start": "2026-10-17T00:00:00Z", "step_seconds": 60},
  "issues": [{"number": 1, "title": "...", "body": "...", "state": "OPEN",
              "created_at": "2026-10-01T00:00:00Z", "labels": []}],
  "pull_requests": [{"number": 2, "title": "...", "body": "Fixes #1", "state": "MERGED",
                     "head_ref": "issue-1-fix", "merge_commit": "<sha on main>",
                     "created_at": "...", "merged_at": "..."}],
  "faults": []
}
```

Only already-MERGED pull requests may be declared. Each one's `merge_commit`
must be on the default branch of the actual remote (`declared-merge-not-in-remote`
otherwise), so the resolving PR in #434's clean case is real history, not an
invented citation. Issue and PR numbers share one sequence, as on GitHub.

## Simulator limits (no GitHub conformance claim)

- No CI. `run list` is empty, `run view` finds nothing, required checks are
  absent and branches are unprotected. The Woodpecker `curl` calls in
  gh-pr-merge.sh and flow-ci-status.sh never reach a server under
  `network=none`. They take their own fail-open path.
- No reviews, labels-as-objects beyond `{name}`, assignees, milestones,
  projects, reactions, forks, drafts, or merge or rebase strategies.
- Search is substring-based and the plain renderings are simplified.
- Ref rewrites are detected, not prevented (#436).
- Nothing in-container proves the shim is the only path. A subject that
  bypasses it shows up as missing requests (`no-controller-witness`) or as
  divergence, never as a recorded success.
- `LocalGitRemote` reaches a remote by host path, as the controller, and
  only a remote the subject cannot write may be given to it. The remote for a
  live attempt runs the same calls inside the attempt's containment, and that
  wiring is #434's.
