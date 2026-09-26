# Trial image (issue #78, Refs #10)

The image every Docker-backed trial runs inside. Built from operating lessons
measured on a sibling platform (issue #10's "Operating lessons" comment,
sections A and B) - every one of them was, at least once, a silent no-op that
exited 0 and would have been graded.

## What this directory is

- `Dockerfile` - the pinned trial image.
- `pinned-versions.json` - the single source of truth for the pinned Claude
  Code and Codex CLI versions. The Dockerfile's `ARG` defaults are a second
  literal by construction (a `Dockerfile` cannot import JSON), so
  `check_pins.py` is the committed control that keeps them from drifting
  apart - the same drift #73 closed for skillc's own version, one level down.
- `check_pins.py` - run it directly (`python3 docker/trial/check_pins.py`)
  or through `tests/test_trial_bootstrap.py`. Needs no Docker daemon and no
  network. Derives each required Dockerfile `ARG` from its
  `pinned-versions.json` key mechanically (`claude_code` ->
  `CLAUDE_CODE_VERSION`), so a new pin needs no second, hand-maintained
  mapping kept in sync, and only flags an untracked `ARG` when its OWN name
  looks like a version pin (`*_VERSION`) - an unrelated build argument is
  none of this check's business.
- `verify_codex_sidecar.js` - run inside the image build (`node
  verify_codex_sidecar.js`) right after the pinned npm installs. Resolves
  the REAL native `codex` executable and its `codex-code-mode-host` sidecar
  through Node's own module resolution against the platform-specific
  `@openai/codex-<platform>-<arch>` package - the same way the npm
  package's own `bin/codex.js` launcher does - rather than searching beside
  the launcher script itself, which is a different package entirely.
  Confirmed by extracting the pinned 0.157.1 tarballs directly: the sidecar
  ships at `vendor/x86_64-unknown-linux-musl/bin/codex-code-mode-host`,
  beside the native `codex` binary, not beside `bin/codex.js`. Requires the
  sidecar to be a regular, executable file - a same-named directory or a
  non-executable placeholder both fail the build. Testable without Docker,
  against a synthetic `NODE_PATH` layout
  (`tests/test_trial_bootstrap.py`).

## What is proven here vs. owed to the live run

Matching issue #78's own evidence rule:

- **Provable without Docker, in this repository:** the pins agree
  (`check_pins.py`); `skillc/trial_bootstrap.py`'s home/seed/MCP-config/
  invocation/canary composition (`tests/test_trial_bootstrap.py`).
- **Provable with Docker, no live agent needed:** the image builds; the
  pinned CLIs install at their exact pinned versions; `codex-code-mode-host`
  lands beside `codex` (issue #10 lesson A2 - installing only `codex` yields
  fluent prose, token spend, exit 0, and zero tool calls, with `codex doctor`
  still reporting all-ok); no `docker` binary is reachable from inside the
  image (lesson C12).
- **Owed to the live run** (#10 closes only on the operator's live run, not
  on this PR): whether a real Claude Code or Codex process, seeded and
  invoked the way `skillc/trial_bootstrap.py` composes, actually starts
  un-wedged inside this image and does the trial's real work.

This session could not build or run the image at all: no `docker` binary is
reachable from here, so the Dockerfile is authored and reviewed but its
build-time claims above are unverified by this PR's own gates. `check_pins.py`
and `skillc/trial_bootstrap.py`'s tests are the parts this PR actually proves.

## Identity and data transfer (owner ruling, 2026-09-26)

The image creates a real `candidate` user and group, `10001:10001`, with a
passwd/group entry - not a bind mount owned by the host caller's real uid.
That design was considered (in an earlier draft of `skillc/docker_backend.py`,
#77) and rejected: hiding the numeric uid from `describe()`'s claims does not
stop the *container's own* `id`, file listings and transcripts from carrying
it, and transcripts are evidence. `~/.claude` and `~/.codex` are pre-created
here, empty and owned by `candidate` - only the empty directories are baked
in, never their contents. The per-trial seed content
(`skillc/trial_bootstrap.py`'s composed `~/.claude.json` and MCP config)
arrives per trial, preferably by copying it in (`docker cp` or a tar stream)
after the container exists; a per-trial directory the controller makes
writable for `10001` only, bind-mounted, is an acceptable fallback. This
image works under either transfer scheme, as long as `/home/candidate` and
`/work` end up owned by `candidate` - it does not itself choose between them;
that choice belongs to `skillc/docker_backend.py` (#77/#79).

## The sandbox decision

Codex runs **unsandboxed** (`--sandbox danger-full-access`) inside the trial
container; bubblewrap is deliberately not installed. Recorded in both the
Dockerfile and `skillc.trial_bootstrap.BWRAP_DECISION`, so #77's Docker
backend can surface it through `describe()`'s `isolation`/`unobserved`
claims once it lands, rather than re-deciding it. Rationale: bubblewrap needs
user namespaces, commonly unavailable or double-nested inside a container
runtime's own container (measured on a sibling platform: the same prompt
wrote its file under `danger-full-access` and wrote nothing under
`workspace-write` without `bwrap` - issue #10 lesson A3), and the trial
container is already the isolation boundary - it has no host filesystem or
credential in reach to sandbox further against.

## Provenance

Recording the digest of the image that RAN (not its tag) plus a provenance
label naming the source commit is #10/#77's responsibility at the point the
backend actually runs `docker build`/`docker run` - this issue only prepares
the image definition those steps will build. `skillc/provenance.py` already
carries the equivalent pattern for skillc's own version/commit/dirty stamp
(#76); the Docker backend should reuse that convention rather than inventing
a second one.
