# Controller-owned issue and PR fixture service

- Status: Implemented in `skillc/fixture_service.py` and
  `docker/fixture-service/skillc-gh-shim.py` (#276). The service and shim are proven
  host-side over a real socket. #434 wires them into a live attempt; see
  [Live attempts](#live-attempts-434)
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

- A trial profile installs `skillc-gh-shim.py` where `gh` would be. It lives
  in `docker/fixture-service/`, outside `docker/trial/`, so it does not enter
  the pinned flow-check build context
  (`tests/test_fixture_service_runtime_pin.py`); how it reaches a trial is
  #434's decision. The shim
  sends each invocation as an `op: "gh"` request over the attempt's one #183
  socket. Repository creation uses a prepare/complete pair around the local push.
- The service parses the request against a closed grammar, decides the answer,
  and appends an event to its own record. Only then does it reply.
- The subject sees gh-shaped stdout, stderr and an exit code. It never sees or
  writes the record.

A grader reads `finalize()`'s record. Anything the agent says about PRs,
merges or closures is a claim to compare against that record.

## Supported request semantics

The grammar covers the pinned CPP 86641e8 flow:auto lane and the project-init
and flow-wave surfaces at `87ecb0970f70aace9e0323feee00c9ca57dda133`.
[The additive wave inventory](fixture-service-wave-gh-inventory.json) records
source hashes, literal call sites, normalized extension cases and exclusions.
The legacy inventory stays frozen at its original pin.
[fixture-service-gh-inventory.txt](fixture-service-gh-inventory.txt) lists
every call with its `source:line`. Each subcommand accepts only the flags listed
below. Anything else is `unsupported` (see Coverage).

| Subcommand | Flags | Semantics |
|---|---|---|
| `auth status` | none | Logged in as `fixture-subject` |
| `repo create NAME` | `--private --public --source --push` | One declared pending repository; actual fixture push is verified before success |
| `label list` | `--repo --json --jq --limit` | Attempt-local name, color and description |
| `label create NAME` | `--repo --color --description` | Refuses duplicate names; color is six hexadecimal digits |
| `issue create` | `--repo --title --body --body-file --label` | Allocates the next shared issue/PR number; labels must exist |
| `issue edit N` | `--repo --title --body --body-file` | Preserves other fields; `--body-file -` reads stdin |
| `repo view` | `--repo --json --jq` | `nameWithOwner name owner url viewerPermission defaultBranchRef` |
| `api PATH` | `--jq --paginate -H` | GET only. `user` (fixture login/email), `repos/O/R`, `.../pulls/N/files`, `.../rules/branches/B` (`[]`), and `.../branches/B/protection/required_status_checks` (HTTP 404 "Branch not protected", printed raw with no jq applied, as gh does) |
| `issue view N` | `--repo --json --jq` | `number title body state url createdAt updatedAt closedAt labels comments author` |
| `issue list` | `--repo --state --search --limit --json --jq` | Newest first. Default state is open, default limit 30 |
| `issue close N` | `--repo --comment --reason` | OPEN to CLOSED, adding the comment first. An already-closed issue is a no-op with exit 0 and no effect |
| `issue comment N` | `--repo --body --body-file` | Appends a comment |
| `pr view [N\|BRANCH]` | `--repo --json --jq` | With no argument, uses the current branch's PR: the open one first, else the newest |
| `pr list` | `--repo --state --head --base --search --limit --json --jq` | `closed` includes merged, as on GitHub |
| `pr create` | `--repo --title --body --body-file --base --head` | Title and body are required, as in non-interactive gh. The head must exist on the remote and be ahead of the base |
| `pr edit N` | `--repo --base --title --body` | Open PRs only |
| `pr merge [N]` | `--repo --squash --subject --body --body-file --delete-branch --admin --match-head-commit` | Squash only; a mismatched live head refuses without a merge; see below |
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

### Project creation and attempt isolation (#636)

A pending fixture declares `repository.exists: false` and an empty bare remote,
with `repository.creation_transport_url` naming one of its `remote_urls` as an
absolute local path or local `file:` URL. Existing declarations still mean an
existing repository and preserve their state shape. Pending declarations cannot
seed issues or PRs. The fixture owner must provision a separate transport for
each attempt, as for the existing service; this service never creates a live
GitHub repository. Optional top-level `labels` entries declare `name`, six-digit
`color` and optional `description`. Labels already present on seeded issues are
also available with a default color and empty description.

`gh api user` and `gh auth status` work before an origin exists. Repository
creation accepts either the declared full name or its bare name, requires
exactly one of `--private`/`--public`, and requires `--source` and `--push`.
The shim sends the source HEAD and a prepare request. The controller checks
that the fixture remote is empty and returns its declared transport. The shim
configures a controller-derived `https://github.com/OWNER/NAME.git` logical
origin, installs a local `url.TRANSPORT.insteadOf` rewrite to the declared
fixture path, and pushes the source, including upstream tracking. Git fetch
and push therefore stay on the fixture transport, while workflow guards see
the expected logical origin. The derived logical URL is accepted only for this
pending fixture repository. A second
request completes only if it matches the preparation and the controller reads
the claimed HEAD from the remote's default branch. That event alone is
`applied` and records visibility and the observed commit. A failed local git
operation, missing ref, different origin, changed HEAD or duplicate creation
cannot manufacture a successful creation event. The controller never reads a
subject-supplied source path. Raw unrecorded pushes still trigger the existing
remote-integrity check.

Created issues, labels, edits, authority refusals and unsupported requests use
the same event sequence, before/after state digests and fault machinery as
existing operations. They are held by one service instance per attempt.
`tests/test_fixture_service_wave.py` exercises real shim/socket/Git effects and
the pinned converter plus its context helper, including creation immediately followed by conversion without an origin
substitution, dependency edits and a second conversion with no duplicates. It uses no model or GitHub connection.
The exact subject-specific jq strings live in packaged
`skillc/fixture_service_filters.json`; the generic controller executes them with
real jq. Both inventories are checked together, with committed unsupported
command/filter controls.

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
recorded as part of the merge's effect.

ONE matcher, `skillc.fixture_service.closing_references(text, repository)`,
implements GitHub's documented grammar. #277's hygiene scan imports the same
function. The source is GitHub Docs, "Linking a pull request to an issue"
(<https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/linking-a-pull-request-to-an-issue>):

- The keywords are `close`, `closes`, `closed`, `fix`, `fixes`, `fixed`,
  `resolve`, `resolves` and `resolved`, matched in any case.
- `KEYWORD #N` and `KEYWORD OWNER/REPOSITORY#N` both close.
- A colon is allowed after the keyword: "Closes: #10, CLOSES #10, or CLOSES:
  #10".
- Each issue needs its own keyword. In `Closes #1, #2`, only #1 closes.
- A reference to another repository is recorded as `foreign_closing_refs` and
  changes nothing here.
- GitHub matches the keyword wherever it appears in the text. A negated or
  incidental phrase such as "does not fix #3" therefore closes, as GitHub
  would. That is why CPP's gh-pr-merge.sh refuses such wording.
- Stated limit: the doc does not settle a reference with no whitespace before
  it (`Fixes:#42`, `Fixes#42`). Such a form is recorded as
  `ambiguous_closing_refs` and closes nothing, rather than guessing. These closure effects are what #277's "old closing
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

## Live attempts (#434)

`agent_trial.run_one_attempt(fixture=...)` runs a fixture-service task inside a
live attempt. The task supplies an `AttemptFixture` (`skillc/fixture_attempt.py`):
its case label, this declaration, the controller's build facts, and a `capture`
that reads the post-stop git state from an exported copy.

**Where every git call runs.** The controller never runs git on anything the
subject can write:

| When | What | How |
|---|---|---|
| before the attempt exists | build the repo and remote | the task's builder, host git, in a controller-owned directory |
| during the attempt | the service's decisions (resolve, diff, merge, CAS) | `ExecGitRemote`: `exec_in_attempt` as the candidate, `confine_root=/work`, fixed `env -i` environment, hooks and fsmonitor off |
| after the agent stops | finalize's divergence check, the source-unmodified capture | no git process: `git_snapshot` reads the exported bytes (`SnapshotGitRemote`, `finalize(remote=...)`) |

`ExecGitRemote` refuses a backend without `witness_io`, because each exec
would otherwise write `observations` and a pid marker into `/work`. It also
refuses a stopped attempt and incomplete output. Its answers are
subject-influenced, which is the detection-only bound above; grading reads
only the post-stop snapshot.

**One socket.** The gh route and the codex-guard route share the attempt's
one #183 socket with the gate witness, through `dispatch`. Each route has a
closed key set, so a mixed request is refused and reaches neither side.
`gate_entrypoint` is therefore required, and the witness uses the fixture's
own gate map and shim (`docker/fixture-service/flow-auto-gate-shim.py` for
flow:auto, gate `flow-auto-finish`).

**Overlays.** `skillc/fixture_overlay.py` places the gh shim at
`/usr/local/bin/gh` and the nested-codex guard at `/usr/local/sbin/codex`,
root-owned, after the surface is installed and before the agent starts. Each
placement is verified:
- the destination did not already exist;
- the bytes read back match;
- neither the file nor its directory is candidate-writable;
- the attempt's measured PATH finds it first.

**The nested-codex guard (D3).** A codex agent that reaches flow:auto's Step 6
may start a second codex as its reviewer, which under #442's provider-only
egress reaches an allowed host and spends.
- The guard refuses a codex started under a codex ancestor with exit 3, the
  unavailable contract. "Codex" is matched by exact exe and script identity,
  never by name.
- Unreadable ancestry fails closed.
- The harness's own launch passes through with argv and environment
  byte for byte.
- Every decision goes to a controller-held record (`skillc/codex_guard.py`).
  The count is `zero` only with a healthy channel and exactly one top-level
  launch; a second top-level launch is `suspected`.
- Bound: `zero` means no nested launch came THROUGH the guard, never that
  none happened. A subject that calls the real codex.js or native binary by
  absolute path never runs the guard, so that call leaves no record and the
  count can still read `zero`. A guard request the channel refuses (a foreign
  field included) marks the record unhealthy, so the count reads `unknown`.

**Grading.** The credit gate refuses credit in these cases, and the attempt
stays in every account:
- a failed binding or finalization;
- a missing service record;
- a nested-codex count that is observed, suspected or unknown.
Otherwise `verify` receives the case, the service record, the git capture, the
final report (the transcript's last assistant message) and the guard record as
`trusted_extras` beside the gate witness.

A fixture attempt on #442's egress keeps the default allowlist; a widened one
is refused before any container exists.

## Controller turns: the Step-3 approval (#279)

flow:auto pauses at Step 3 for a reviewer's approval and has no bypass. So an
unattended attempt ends there with a plan. To reach Step 6, the controller
sends a second user turn into the same client session (`skillc/controller_turns.py`).

- **Declared per case, never by default.** The turns object is
  `{"version": 1, "by_case": {<case>: [{"text": <literal>}, ...]}}`. It must
  name every case, with 0 to 3 literal texts each. No text may start with `-`:
  the client's argument parser reads options anywhere before `--`, so a text
  like `--enable=apps` would reopen a channel. A case with no turns (CLEAN)
  never receives one, even after a clean exit: an approval after "No longer
  needed" would push the agent toward implementing. The controller never
  interprets the agent's text. A turn is sent only after the previous one
  EXITED with code 0.
- **The resume argv, measured** on codex-cli 0.157.1 (offline, the #375 image).
  It is `[*turn-1 argv, "resume", <session id>, <text>]`. Exec's flags before
  `resume` take effect, `--sandbox` included. `--sandbox` after `resume` is
  refused. The resume appends to the same rollout. Every resume argv passes
  #442's server-side preflight before any container exists.
- **The session id is controller-held.** It comes only from the client's own
  stderr header, never from the agent-writable rollout. The header must be
  the initial output, with only the client's measured start-up warnings
  before it. It must hold only the measured `key: value` lines between its
  two separators, with exactly one `session id:`. Text the agent prints later
  cannot supply or replace it, and neither can a forged header or an unclosed
  one. With no unambiguous id, there is no further turn.
- **One container, one budget.** Each turn is `TurnCapableBackend.execute_turn`.
  A turn that exits leaves the container running for the next. A timeout or
  cancel stops it as before. `end_attempt` runs in a `finally`, so an
  exception between turns still ends in a confirmed stop. All turns share the
  attempt's one wall budget; a turn the budget cannot reach is recorded as
  undelivered. So is a turn after an operator cancel: cancellation is checked
  before each further turn. A turn counts as delivered only if the resume
  actually launched; `launch-failed` and `attempt-not-running` are not.
- **Background processes the agent started in an earlier turn keep running
  between turns**, as they would during one long session. The attempt-level
  stop at the end still confirms the whole container is gone, exactly as for a
  single-turn attempt.
- **The guard counts each turn.** Each resume is a fresh top-level `codex` launch.
  #434's nested-codex guard expects `1 + delivered` top-level launches. More
  is still `suspected`; fewer is `unknown`, because a delivered turn the guard
  never saw did not come through it.
- **The census, egress, guard, witness and snapshot run once, after the last
  turn**, over the whole session. The attempt result's `controller_turns`
  records what was declared and delivered, and why the turns stopped.

Without turns, an attempt runs through one plain `execute()` exactly as before.

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


### No-launch opt-in check and recorded transcript scan (#536)

`skillc level3-live <declaration> --preflight-launch-env` checks the real
client's exact declared model/effort-pinned argv against the current
`SKILLC_ALLOW_REAL_AGENT` environment. Only the exact value `1` permits it.
Run this in the environment intended for the later live launch. It reads the
declaration but touches no image, credential, private run store, backend or
client. It accepts an unapproved declaration because it authorizes no run.
It refuses combinations with rehearsal or judge-replay options.

Success establishes only that current opt-in condition. It does not establish
approval, budget, image or credential readiness, or promise a successful future
launch. The actual lifecycle driver checks the guard again at launch; changing
the environment after the check can therefore refuse the launch.

Each live-report attempt now retains `transcript_codex_invocations` and
`transcript_files_found` from its recorded observation, next to `nested_codex`.
An observed empty scan is `[]`; an observed zero file count is `0`. Missing
observations remain `null`. Building a report never rescans a transcript or
changes credit. A scan with an unreadable entry becomes `null`, preserving the
file count when known. Raw argv-derived scan content must pass the existing
transcript identity and credential retention checks before it is retained; an
unsafe scan becomes `null` in its entirety, never a filtered or empty scan.
`transcript_scan_retention` gives `coverage` (`complete`, `missing`, or
`refused`) and a fixed safe `reason`. These are additive report fields; the v2
record schema and original raw observation are unchanged.
