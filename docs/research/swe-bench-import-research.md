# SWE-bench-style import: research on the six open problems

- Date: 2026-09-30
- Issue: [#210](https://github.com/cooneycw/skillc/issues/210), scoped RESEARCH ONLY
  by the owner's ruling comment on that issue (2026-09-30)
- skillc revision read: `main` at `4a2528e15fd53f69779ef927d1c10751b120d370`
- #204 calibration report read: branch `issue-204-calibration-report` at
  `4437f3e2ac69eeb40d05c6478118d6b667408a57`, `evals/calibration-204/report.md`
  ([PR #212](https://github.com/cooneycw/skillc/pull/212), open, recommends REDESIGN)
- Upstream sources and pins: see "Provenance and upstream pins" at the end

## What this document is

#210 asks whether SWE-bench-style instances could give skillc a floor-check task
family: evidence that installing CPP does not hurt an agent's raw fixing ability.
The owner ruled that #210 stays gated for building: "RESEARCH ONLY ... Build no
importer, import no instances, and make no live or paid run." This note is that
research. For each of the issue's six open problems it states what skillc's
contracts require (file and line), what upstream publishes (with source), and
where the two meet or conflict.

**Nothing was run, installed or downloaded.** No `swebench` package, no dataset
file and no Docker image was pulled or built, and no model was called. skillc
files were read from a clone. Upstream files were read through the GitHub API at
the pinned commits. Dataset metadata was read through the Hugging Face API
(`/api/datasets/<id>`) and the dataset cards. Papers and blog posts were read on
the web. Each claim is marked:

- **read**: seen directly in the named file, API response or page;
- **read (summary)**: taken from a web page's extracted text or a search result,
  not checked word for word;
- **inferred**: my conclusion from what was read;
- **open**: neither reading nor inference could settle it.

ADR 0003 applies throughout: skillc takes ideas, not code, and runs no external
evaluation runtime
([`docs/decisions/0003-no-external-evaluation-runtime.md` L32-49](../decisions/0003-no-external-evaluation-runtime.md)).
Paths below are skillc repository-root relative at `4a2528e` unless they name an
upstream repository.

## Summary

| # | Problem | Finding |
|---|---|---|
| 1 | Environments | Per-instance images can meet the digest rules only through a derived image, one per instance: the upstream instance image pinned by registry digest, with the trial layer (agent CLI, `candidate` user, `python3`) added. skillc declares ONE image per run (`shared.image`), so it would need a per-task image map or one declaration per instance. Upstream images are published under moving tags and their Dockerfiles use moving bases, so a rebuild cannot reproduce a digest |
| 2 | Contamination | SWE-bench Verified instances date from 2013 to 2023, and OpenAI has itself called Verified contaminated. SWE-rebench-V2's newest instance is dated 2025-10-31. Multi-SWE-bench publishes no instance date. skillc records a model name but no cutoff anywhere. Contamination pushes both arms toward ceiling, which is exactly why #212 recommends REDESIGN |
| 3 | Certification | `qualify.py` needs a failing fixture, a passing reference, at least one alternative, at least one wrong candidate (each with the exact violated criteria) and five broken-grader controls. The controls port unchanged. An empty patch and a revert both duplicate the fixture. A test-only edit is the useful wrong candidate. A partial gold patch is unsound unless it is measured per instance. Upstream provides no alternatives |
| 4 | Hidden-test integrity | The split fits: FAIL_TO_PASS test code belongs in the grader's probe inputs, and the expected test lists in the judge. Four things break it as built: capture drops `.git` and caps a capture at 1,000 files, the agent container has open egress to the public fix, candidate code shares the pytest process, and `qualify.py`'s grading path has no container backend |
| 5 | Cost and time (on paper) | #204's median was 140 s of agent time and 4.5 s of grading per attempt. Upstream's published per-instance evaluation cost is seconds to minutes, with a 1,800 s default timeout. At #204's 1,200 s per-attempt and 10,800 s total caps, 3-5 instances x 2 arms x 4 attempts can hit the total cap. Nothing was measured |
| 6 | Licences | SWE-bench and SWE-rebench-V2 code is MIT; Multi-SWE-bench and Terminal-Bench are Apache-2.0. Datasets: Verified declares no licence; SWE-rebench-V2 is CC-BY-4.0; Multi-SWE-bench is `other` (CC0 text plus a ByteDance IP clause). Source repositories range from BSD-3-Clause to GPL-2.0 (pylint) |
| - | Upstream pins | Re-pinned 2026-09-30 21:13 UTC. **None of the four HEADs moved** from the SHAs in #210's body |

## 1. Environments: can per-instance images meet skillc's image rules?

### What skillc requires (read)

- **One trial image, built from a moving base tag, identified by the digest of
  the image that ran.** `docker/trial/Dockerfile` L15-19 says so directly: "Base
  pinned by tag; digest pinning happens at BUILD time ... the identity claim is
  the digest of the image that RAN". `docker/trial/README.md` L104-112
  ("Provenance") makes the digest of the image that ran, not its tag, the recorded
  identity.
- **The declaration carries a sha256 digest.** `skillc/matched_pilot.py` L188-190
  refuses an `image_digest` that is not `sha256:<64 hex>`.
  `skillc/calibration.py` L266-273 lists `("shared", "image", "tag")` and
  `("shared", "image", "digest")` among the identities that must be present
  before a run is authorized. The #204 declaration carries one image under
  `shared` (`evals/calibration-204/run-manifest.json` L44-47), and so does the
  matched-pilot manifest (`evals/matched-pilot/run-manifest.json` L25, L93).
- **The measured image must equal the declared one, before any run.**
  `skillc/cli.py` L1515-1527 (`pilot-run`) and L1720-1727 (`calibration-run`)
  resolve the image's digest and refuse "a run on an image other than the
  declared one". The resolver `skillc/demo.py` L177-193 asks the daemon
  (`docker image inspect <image> --format {{.Id}}`) and returns `None` rather
  than guess.
- **Each attempt re-checks the image.** `docs/specs/evaluation-facility/capture.md`
  L38-43: a `backend-identity` event carries the running container's
  `image_digest`, the ledger's planned digest and `matches_ledger`. "A tag
  republished after planning is a `false`". `skillc/verify.py` L1073-1083
  refuses a receipt measured in another image.
- **The client version is pinned in one manifest, and a check proves the
  Dockerfile agrees.** `docker/trial/pinned-versions.json` L1-15 holds the
  claude-code and codex pins. `docker/trial/Dockerfile` L21-25 carries them as
  `*_VERSION` ARGs. `docker/trial/check_pins.py` L65-90 refuses any disagreement
  and any `*_VERSION` ARG the manifest lacks. The CLI also refuses a declared
  client version that differs from the image's pin
  (`skillc/cli.py` L1507-1513, L1711-1718).
- **The image must contain certain things.** Per `docker/trial/Dockerfile`:
  - `python3`, because the probe runs as `python3` inside the container (L31-48);
  - the pinned agent CLIs (L63-65) and the Codex sidecar check (L79-80);
  - no `docker` binary (L100-104);
  - a fixed, non-host `candidate` user (L114-115), which the backend requires
    (`skillc/docker_backend.py` L146-156).
- **The probe gets a separate container from the same image.**
  `skillc/collection_conformance.py` L189-200 (`agent_backends`) builds the
  agent backend and the grading backend from one `image`. The grading backend
  keeps the backend's default network, `none` (`skillc/docker_backend.py` L559).

### What upstream publishes (read)

- **SWE-bench at the pinned HEAD (`02e7a74`) no longer uses the
  base/env/instance layering.** Its v5.0.0 (2026-08-17, `CHANGELOG.md` L31-45)
  moved each instance's Dockerfile into a separate task repository
  ([SWE-bench/swe-bench-tasks](https://github.com/SWE-bench/swe-bench-tasks)),
  and the harness now assumes images exist ("`TestSpec` now assumes images
  already exist"). The image name is `sweb.eval.<arch>.<instance_id>:<tag>`,
  with `__` replaced by `_1776_` for a remote namespace
  (`swebench/image_builder/image_spec.py` L36-44).
- **The three layers, as of the last v4 tag** (`v4.1.0`, `726c546`), for anyone
  reading older docs:
  - base `sweb.base.<ext>.<arch>`, from `ubuntu:22.04` with unversioned apt
    packages and a pinned Miniconda installer
    (`swebench/harness/dockerfiles/python.py` L1-33;
    `swebench/harness/constants/__init__.py` L123, L127);
  - env `sweb.env.<ext>.<arch>.<sha256 of the setup script>[:22]`, built from a
    cached, fully pinned `environment.yml` per instance where one exists, and
    otherwise from loosely specified packages
    (`swebench/harness/test_spec/test_spec.py` L89-104;
    `swebench/harness/test_spec/python.py` L333-402);
  - instance `sweb.eval.<arch>.<instance_id>`
    (`swebench/harness/test_spec/test_spec.py` L106-111).
- **Nothing is pinned by digest.** `@sha256` does not occur in the harness at
  either version. An example task Dockerfile at swe-bench-tasks `3d07b46`
  (`tasks/django__django-11099/Dockerfile`):
  - starts `FROM ubuntu:jammy` (L2), a moving tag, and installs unpinned apt
    packages (L7-21);
  - pins Python dependencies through `environment.yml` (L38-101);
  - checks out the base commit and scrubs later tags and commits (L114-126).
- **Published images move.** The Verified row for `django__django-11099` names
  `swebench/sweb.eval.x86_64.django_1776_django-11099:latest`. Its `:latest` was
  re-pushed on 2026-08-16, beside older `v1` and `v2` tags (Docker Hub API).
- **The harness pulls a missing image** (`swebench/harness/run_evaluation.py`
  L89-101). When a local build fails, it falls back to the published image
  (L691-694).
- **SWE-rebench-V2** (`SWE-rebench/SWE-rebench-V2` @ `c71902a`):
  - builds `FROM python:3.11-slim`, a moving tag, with unpinned `pip install`
    (`base_dockerfiles/Dockerfile_python_3.11` L1, L31-32);
  - wraps each install step as `( cmd ) || true` (`combine.Dockerfile.j2`
    L6-18), so a failed install is swallowed;
  - publishes prebuilt images by tag in the `swerebenchv2` Docker Hub namespace
    (the dataset's `image_name` field).
- **Multi-SWE-bench** names images `mswebench/<org>_m_<repo>:{base|pr-N}`
  (`multi_swe_bench/harness/image.py` L92-103), with no digests in its image
  lists. At least one base uses `FROM golang:latest`
  (`multi_swe_bench/harness/repos/golang/zeromicro/go_zero.py` L22-23).

### Where they meet (inferred)

1. **A digest-pinned import is possible, but only by pulling.** A rebuild from
   the published Dockerfiles cannot reproduce a digest: the base tags move, and
   apt and pip resolve at build time. An import would therefore record the
   upstream image by registry digest (`<name>@sha256:<manifest digest>`), not by
   tag. It would not trust `:latest`, which has already been re-pushed once.
2. **The upstream image cannot be the trial image as it stands.** It has no
   agent CLI, no `candidate` user at the fixed logical id the backend requires, and possibly no `python3` on
   the default `PATH` (the probe runs with `PATH=os.defpath` only,
   `skillc/verify.py` L409-414). Whether `python3` is present is **open** per
   image. Each instance would need a **derived image**: `FROM <upstream>@sha256:...`
   plus the trial layer. That derived image's `{{.Id}}` is what skillc measures
   and must declare.
3. **Two digests, two meanings.** `demo.resolve_image_digest` records the local
   image ID (the config digest), while a registry pull names a manifest digest.
   A task's provenance should record both: the upstream manifest digest it was
   pulled by, and the derived image ID that ran.
4. **`check_pins` would not see the new pin.** It checks only ARGs ending in
   `_VERSION` (`docker/trial/check_pins.py` L36-39, L87-89). A per-instance base
   digest needs its own manifest entry and its own committed red case (ADR 0001).
5. **The trial Dockerfile cannot simply be layered on.** It starts
   `FROM node:22-bookworm-slim` (L19). SWE-bench bases are Ubuntu 22.04 with
   conda. Node and the CLIs would have to be installed onto the upstream base.
   That is a second Dockerfile to keep in step with `pinned-versions.json`.
6. **One image per declaration is the structural conflict.** `shared.image`
   (`skillc/calibration.py` L266-273) and the single `image_digest` of the
   matched pilot mean a family of N instances is N images. The options are:
   - (a) one declaration per instance;
   - (b) a declaration schema with a per-task image map, each entry checked by
     the same measured-equals-declared refusal;
   - (c) one fat image holding every instance's environment. Option (c) defeats
     per-instance pinning and is not recommended.
7. **Resources are a real difference.** skillc's container defaults are 1 GB of
   memory, 1 CPU and 256 pids (`skillc/docker_backend.py` L201-204). Upstream
   eval containers get no memory or CPU limit, and add `SYS_ADMIN`
   (`swebench/harness/run_evaluation.py` L115-124 @ `02e7a74`). Whether a given
   instance's test run fits in 1 GB is **open**.

## 2. Contamination

### What upstream publishes

- **SWE-bench Verified.**
  - The dataset rows carry `created_at` (read: card of
    [`SWE-bench/SWE-bench_Verified`](https://huggingface.co/datasets/SWE-bench/SWE-bench_Verified)
    L2-37).
  - Across the 500 rows the dates run from 2013-01-25 to 2023-08-07, median
    2020-12-27 (read: Hugging Face datasets-server statistics).
  - The dataset was human-filtered for well-specified issues and valid tests,
    not for contamination: 93 annotators, three labels per sample, 1,699
    candidates reduced to 500 (read (summary):
    [Introducing SWE-bench Verified](https://openai.com/index/introducing-swe-bench-verified/)).
  - OpenAI later wrote that Verified is "increasingly contaminated". The post
    reports a model reproducing the gold patch for `django__django-11099`
    verbatim from the task ID alone, and recommends another benchmark (read
    (summary):
    [Why SWE-bench Verified no longer measures frontier coding capabilities](https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/),
    2026-02-23).
  - "The SWE-Bench Illusion" ([arXiv 2506.12286](https://arxiv.org/abs/2506.12286))
    reports that models identify the file to change from the issue text alone
    far more often on SWE-bench repositories than on others (read (summary)).
- **SWE-rebench-V2.**
  - [`nebius/SWE-rebench-V2`](https://huggingface.co/datasets/nebius/SWE-rebench-V2)
    (dataset sha `475dd5e`, modified 2026-05-12) has 32,079 rows in 20
    languages, of which 7,243 are Python (read: card L171 and statistics).
  - `created_at` runs from 2014-11-10 to 2025-10-31 (read).
  - The card contradicts itself on the field's type: `string` in the YAML
    header (L21-22), "int64 Unix ms" in the field table (L195). The sample file
    holds millisecond integers (read). An importer must parse it defensively.
  - The paper ([arXiv 2602.23866](https://arxiv.org/abs/2602.23866)) describes
    continuous collection but makes no explicit decontamination claim (read
    (summary)).
  - The original SWE-rebench leaderboard handles contamination by flagging any
    evaluation on issues created before a model's release date (read (summary):
    [swe-rebench.com/about](https://swe-rebench.com/about)).
- **Multi-SWE-bench.**
  [`ByteDance-Seed/Multi-SWE-bench`](https://huggingface.co/datasets/ByteDance-Seed/Multi-SWE-bench)
  has **no `created_at` field** (read: card L26-44). An instance date would have
  to be recovered from the source PR through the GitHub API. The paper
  ([arXiv 2504.02605](https://arxiv.org/abs/2504.02605)) makes no contamination
  statement (read (summary)).

### What skillc records today (read)

A declaration names the model and nothing about its training data:
`"model": "gpt-6-astra"` (`evals/calibration-204/run-manifest.json` L39;
`evals/matched-pilot/run-manifest.json` L89). No skillc file records a model
cutoff; a search of `docs/` and `skillc/` for "cutoff" and "training" finds
nothing that does. "Contamination" in skillc means skill-surface contamination
of the baseline arm (`docs/specs/evaluation-facility/interfaces.md` L185), not
training-data leakage.

### How an instance date would be recorded (inferred proposal)

- **Per task, in `PROVENANCE.md` or a task manifest:**
  - `instance_created_at`: the dataset field, with the unit it was parsed from;
  - `fix_merged_at`: the upstream PR merge time, read from the GitHub API. This
    is the date the answer became public, which is what matters for leakage;
  - the dataset id and dataset sha it came from.
- **Per declaration:**
  - `model.cutoff`, with a `cutoff_source` URL;
  - `cutoff: UNKNOWN` when the provider publishes none. The cutoff of the model
    #204 ran (`gpt-6-astra`) is **open**: I found no published figure.
- **A declaration-time check** that reports each task as `after-cutoff`,
  `before-cutoff` or `unknown`. Following skillc's own rule that unknown is never
  a pass, `unknown` must never count as `after-cutoff`. The check needs a
  committed red case: a task dated before a declared cutoff must be reported
  `before-cutoff`.
- **Consequence:** at today's pins no published instance can be shown to
  post-date a current model's cutoff. Verified cannot. V2's newest row is
  2025-10-31, and the cutoff to compare it against is unpublished. "Newer than
  the cutoff" therefore needs either fresh collection, which is importer work
  outside this ruling, or an explicit acceptance that the family is
  contaminated. For a floor check contamination affects both arms, but it pushes
  both toward ceiling. **That is the #204 failure mode.** #212 found both arms at
  4/4, and a ceiling cannot show a regression either.

## 3. Certification: what `qualify.py` requires, and deriving wrong candidates

### What skillc requires (read)

`evals/level1/slug-small-fix/qualify.py` is the template; `finish-close-ref`'s
is the same harness with its own criteria. `evals/level3/slugkit-pipeline/qualify.py`
L1-59 adds a `benign/` population and a pipeline-validity gate.

- **Placement.** The fixture must FAIL, the reference PASS, every alternative
  PASS and every wrong candidate FAIL (`slug-small-fix/qualify.py` L117-123).
- **Non-empty populations.** A missing `alternatives/` or `wrong/` population
  refuses outright: "an empty population cannot certify a grader" (L110-116).
- **The exact violated set.** Every candidate carries an `expected.json` whose
  violated criteria must equal what the grader reports. "A FAIL for the wrong
  reason does not count as discrimination" (L9-12, L92-105, L76-77).
- **Five broken-grader controls.** Each replaces only the judge and must be
  refused with one named status on every candidate: `always_pass`,
  `always_fail`, `crash`, `no_output`, `omits_criterion` (L56-62, L135-147).
- **Grading through the real verifier.** `verify.grade_directory` (L88) is the
  same staged path a real attempt takes. Its signature
  (`skillc/verify.py` L975-976) takes **no backend**, so certification runs the
  probe as a bare host subprocess.

### What upstream supplies (read)

One gold `patch`, one `test_patch` and the `FAIL_TO_PASS` / `PASS_TO_PASS` test
lists per instance. It supplies no alternative solutions, no wrong candidates and
no broken graders.

The upstream grader's own rules (`swebench/harness/grading.py` @ `02e7a74`):

- an F2P test passes on PASSED or XFAIL, and SKIPPED counts as a failure
  (L85-109);
- `resolved` requires both F2P and P2P at 100% (L309-326, L387-388);
- a non-zero exit with no FAILED or ERROR in the log is rejected (L166-175).

Multi-SWE-bench adds a stricter validity rule: an instance is valid only if its
tests behave as expected across three runs (no patch, test patch only, test patch
plus fix) (`multi_swe_bench/harness/repos/golang/zeromicro/go_zero.py` L121-159;
`multi_swe_bench/harness/report.py` L90-140).

### A grader built on the test lists (inferred)

Suppose a grader with three criteria:

- `fail-to-pass`: every F2P test PASSED;
- `pass-to-pass`: every P2P test PASSED (or was skipped, as upstream allows);
- `tests-untouched`: the candidate changed no test or test-infrastructure file.

The five broken-grader controls are judge replacements, so they port to such a
grader unchanged. The candidate populations are the hard part:

| Derived candidate | Mechanical recipe | Expected verdict | Assessment |
|---|---|---|---|
| Empty patch | the fixture itself | FAIL on `fail-to-pass` | **Non-discriminating.** It is the fixture row already, so it adds no new evidence |
| Revert | gold patch applied, then reverted | FAIL on `fail-to-pass` | **Non-discriminating.** It is byte-identical to the fixture |
| Test-only edit | fixture plus edits to the F2P test files named in `test_patch` (delete, skip or weaken the assertions) | FAIL on `fail-to-pass` and `tests-untouched`, **provided the probe restores the test files before running**, as upstream does (`git checkout <base> <test files>`, then applies `test_patch`) | **Sound and discriminating.** It is the one mechanical wrong candidate that tests the grader's integrity, not just the fixture. Variants: a `conftest.py` that marks every test skipped (refused by the SKIPPED rule on F2P), or one whose `pytest_runtest_makereport` hook rewrites outcomes to passed. The second **passes** a grader that only reads pytest output. Only `tests-untouched` or a probe that neutralizes non-`test_patch` conftest files refuses it (see section 4) |
| Partial gold patch | a subset of the gold patch's hunks | Unknown until run | **Unsound as a placed candidate.** Some hunks are documentation or unexercised, so a subset can PASS, and a one-hunk patch has no subset. Its placement and `expected.json` must be measured per instance in the instance environment. That is certification by execution, not by construction |
| Gold plus breakage | gold patch plus a syntax error in a module a P2P test imports | FAIL on `pass-to-pass` only | **Sound and discriminating** for the `pass-to-pass` criterion, which otherwise has no committed wrong candidate. Choosing the module needs one run to confirm a P2P test imports it |
| Gold minus a line (mutation) | delete or negate one changed line of the gold patch | Unknown until run | Like the partial patch: useful, but only with a measured expectation per mutant |

**Alternatives.** `qualify.py` refuses an empty `alternatives/` population.
Upstream supplies none. The mechanical candidates available (a reformatted or
comment-only variant of the gold patch) are weak, near-duplicates of the
reference. A real alternative would be a different correct fix, for example
from public agent submissions that upstream marks resolved. Their licence and
provenance are **open**, and using one is a judgement per instance, not a
mechanical derivation.

**Certification cannot run on the host.** `grade_directory` has no backend
(`skillc/verify.py` L975-976), and the bare path runs the probe with the host's
`python3 -I -S -B` and `PATH=os.defpath` (`skillc/verify.py` L565-567, L409-414).
A Django or SymPy test suite needs the instance environment. A SWE-bench family
therefore needs `qualify.py` to grade through a container backend, which is new
verifier surface (inferred).

## 4. Hidden-test integrity

### How the split works in skillc (read)

- **The grader is `grader.json` plus three files: probe, inputs and judge**
  (`docs/specs/evaluation-facility/verification.md` L33-47; for example
  `evals/level3/slugkit-pipeline/grader.json`). Its digest is pinned in the
  ledger. The probe and judge run from the pinned bytes, never from files
  re-read from disk (verification.md L49-63).
- **The agent receives only the fixture.** `task_surface` delivers the fixture
  minus its `expected.json` answer key, and refuses symlinks
  (`skillc/collection_conformance.py` L453-475). Nothing from the grader
  directory reaches `/work`.
- **Capture freezes the agent's tree on the controller's side**, after a
  confirmed stop (capture.md L109-131; `skillc/trial.py` L1036-1060):
  - it never enters `SECRET_DIRS`, which includes `.git` (`skillc/trial.py` L100);
  - it is bounded to 1,000 files, 16 MiB per file and 64 MiB in total
    (`skillc/trial.py` L124-132);
  - it captures everything under the default `include=("*",)`, as
    `skillc/lifecycle.py` L460-463 calls it;
  - going over a bound makes the capture partial, never a silent truncation.
- **The probe is untrusted.** It runs in a fresh root containing a disposable
  copy of the frozen artifacts, the probe harness and its inputs, and "the answer
  key is not there" (verification.md L65-80). Given a backend, it runs in a fresh,
  separate container (verification.md L379-403). For agent attempts that
  container is built from the same image as the agent's, on network `none`
  (`skillc/collection_conformance.py` L189-200).
- **The judge is trusted and starts last,** holding the answers
  (verification.md L129-131).
- **Candidate code can write the probe's report.** Verification.md L123-127
  says so directly; the judge reads the report strictly.

### Where the FAIL_TO_PASS tests would live (inferred)

- **The test code is probe input, not answer key.** The `test_patch` (or the
  post-patch test files) belongs in the grader directory as the probe's
  `inputs`. The probe applies it to the disposable copy and runs the named
  tests in the instance environment. It reports per-test outcomes as
  observations.
- **The expected lists belong in the judge,** so the probe never holds the
  verdict: the F2P and P2P names, and which outcome counts.
- This keeps the tests out of the agent's container by construction, because
  the grader directory is never part of `task_surface`. It keeps them in the
  probe's container, which is where they must run.

### What breaks this as built

1. **Capture size and `.git`.** Django at its current HEAD has 7,091 files,
   SymPy 2,093 and Astropy 2,016 (read: GitHub tree API, default branch, not
   the instances' base commits). All exceed the 1,000-file bound. Capturing the
   whole tree would be partial for most Verified repositories. Because `.git` is
   not exported, the probe cannot diff against the base commit either. The
   inferred fix: the derived image carries the repository at the base commit,
   as upstream images do; capture is scoped by `include` to the source paths;
   and the probe overlays the captured files onto the image's copy. Whether an
   `include` scope can be set per task without new controller surface is
   **open**.
2. **The upstream fix is public, and the agent has egress.** The agent container
   runs on `bridge` under an owner ruling whose stated premise is "no hostile
   inputs" (`skillc/collection_conformance.py` L112-123). A SWE-bench instance is
   not hostile, but its answer (the merged PR) and its tests (in the public
   dataset row's `test_patch` and `eval_script`) are one search away. This is
   not the hazard the ruling's reversal trigger names, but it defeats hidden
   tests just as surely. A provider-only egress allowlist, which the ruling
   already names as the alternative, would be a precondition.
3. **Candidate code shares the test process.** A candidate `conftest.py`, pytest
   plugin or `sitecustomize` runs inside the probe's pytest and can rewrite
   outcomes. Upstream's defences are partial:
   - restoring the test files named in `test_patch`;
   - the exit-code check (`swebench/harness/grading.py` L166-175).
   The probe should restore or remove every test-infrastructure file the
   candidate changed, apply `test_patch` last, and report changed test files as
   an observation for the judge's `tests-untouched` criterion.
4. **Fixture history can leak the answer.** Upstream scrubs tags and commits
   newer than the base (swe-bench-tasks
   `tasks/django__django-11099/Dockerfile` L114-126). A fixture that carried
   `.git` would need the same scrub. A fixture without `.git` avoids this, but
   then CPP's git-workflow skills have nothing to act on. That is a floor-check
   trade-off, not a defect.
5. **The probe interpreter.** The backend probe runs `python3 -I -S -B`
   (`skillc/verify.py` L610-616, L721), and `-S` excludes site-packages. The
   probe must launch the instance environment's own interpreter by absolute
   path (for example the conda env's `python -m pytest`), because `PATH` is
   `os.defpath` only.
6. **Probe timeout.** `grader.json`'s `probe.timeout` is 240 s for
   slugkit-pipeline. Upstream's default evaluation timeout is 1,800 s
   (`swebench/harness/run_evaluation.py` L833-839).

## 5. Cost and time, on paper only

**Nothing here was measured.** The numbers are copied from #204's report and
from upstream publications.

**From #204** (`evals/calibration-204/report.md` on branch
`issue-204-calibration-report`, [PR #212](https://github.com/cooneycw/skillc/pull/212),
lines 75-91). This was one small task, `evals/level3/slugkit-pipeline`, on codex
0.157.1 / `gpt-6-astra` / effort `high`:

| | Median | Range |
|---|---|---|
| Agent time | 140 s | 96-184 s |
| Wall per attempt | 148 s | 107-229 s |
| Grading | 4.5 s | 4-36 s |
| Input tokens | 148,500 | 120k-240k, about 90% cached |
| Output tokens | 3,870 | 3.2k-4.4k |

Eight attempts took about 21 minutes against caps of 1,200 s per attempt and
10,800 s in total. The cost was subscription quota only, with no dollar price
(ADR 0005 section 6, `docs/decisions/0005-runtime-scope-and-cost-rulings.md`
L105-130).

**From upstream:**

- **Resource guidance:** x86_64, at least 120 GB free disk, 16 GB RAM and 8
  cores (read: SWE-bench `README.md` L122-128 @ `02e7a74`).
- **SWE-bench Lite:** about 30 minutes on 16 cores with 12 workers, or about 15
  minutes with instance images cached (read: `docs/reference/harness.md`
  L156-163). No Verified timing is published there.
- **SWE-bench Verified:** Epoch AI reports 62-73 minutes on one 32-core, 128 GB
  machine, about 8 s per instance amortised, with images reduced to 30 GiB in
  total (read (summary): [epoch.ai](https://epoch.ai/latest/swebench-docker),
  2025-07-10).
- **Human effort:** the Verified annotation labels 194 instances as under 15
  minutes of human work, 261 as 15 minutes to 1 hour, 42 as 1-4 hours and 3 as
  over 4 hours (read: datasets-server `difficulty` statistics).
- **SWE-rebench-V2:** publishes build time only, 2.71 minutes per image build
  (read (summary): the paper). No per-instance evaluation time is published
  (**open**).

**Sizing on paper (inferred):**

- **Attempt count:** a first family of 3-5 instances in #204's shape (2 arms x
  4 attempts) is 24-40 attempts.
- **At #204's median** of 148 s, 24-40 attempts would take 59-99 minutes of wall
  time. #204's 10,800 s total cap fits about 73 such attempts.
- **SWE-bench instances are not #204's size.** The repositories are 100 to 7,000
  files, and the declared per-attempt cap (1,200 s) may bind. At the cap, 40
  attempts are 48,000 s, over four times the total cap. The true agent time per
  instance is **unknown** without a measured run, which is what #210's
  "measure on 3-5 instances" step was for.
- **Grading:** upstream's amortised seconds per instance suggest seconds to
  minutes per attempt, before any image pull.
- **Disk:** pulling the images is a one-off cost, in the gigabytes per instance
  (inferred from the 30 GiB for 500).
- **Quota:** input tokens scale with how much of the repository the agent
  reads. Expect a multiple of #204's 148,500 median. The multiple is **open**.

## 6. Licences and provenance

**Code repositories** (read: `gh api repos/<o>/<r>/license`, 2026-09-30):

| Repository | Licence |
|---|---|
| SWE-bench/SWE-bench | MIT |
| SWE-rebench/SWE-rebench-V2 | MIT |
| multi-swe-bench/multi-swe-bench | Apache-2.0 |
| harbor-framework/terminal-bench-1 | Apache-2.0 |
| SWE-bench/swe-bench-tasks (holds v5's per-instance Dockerfiles) | **no licence file** (the API returns none) |

**Instance datasets** (read: Hugging Face API `cardData.license`, 2026-09-30):

| Dataset | Dataset sha | Licence and terms |
|---|---|---|
| `SWE-bench/SWE-bench_Verified` | `78f471b` (2026-08-16) | **none declared**. No licence tag and no stated terms (**open**) |
| `princeton-nlp/SWE-bench_Verified` | `c104f84` (2025-02-18) | **none declared** |
| `nebius/SWE-rebench-V2` | `475dd5e` (2026-05-12) | `cc-by-4.0`. The card asks users to respect each source repository's licence (L205-206) |
| `nebius/SWE-rebench` | `89cdfba` (2025-12-23) | `cc-by-4.0` |
| `ByteDance-Seed/Multi-SWE-bench` | `56ff018` (2026-07-08) | `other`. The card's prose says CC0, "subject to any intellectual property rights ... owned by Bytedance", and requires compliance with each source project's licence (L60-62) |

**Per-instance source licences.**

- **Which datasets record one:** SWE-rebench-V2 has a per-row `license` field
  (card L199), and SWE-rebench v1 has a free-text `license_name`. Verified and
  Multi-SWE-bench have none (read).
- **V2's field contradicts its paper:** the paper says only permissively
  licensed repositories were kept, but the field includes `AGPL-3.0` (54 rows),
  `GPL-3.0` (5) and 348 nulls (read: datasets-server statistics). The field
  cannot be trusted without re-checking each repository.
- **The 12 Verified source repositories, at their current HEAD, not at each
  base commit** (read: GitHub licence API):

| Repository | Licence |
|---|---|
| astropy, django, seaborn, flask, scikit-learn | BSD-3-Clause |
| requests, xarray | Apache-2.0 |
| pytest | MIT |
| pylint | **GPL-2.0** |
| sphinx | GitHub reports NOASSERTION; `LICENSE.rst` reads as 2-clause BSD (inferred) |
| sympy | NOASSERTION; the text reads as 3-clause BSD (inferred) |
| matplotlib | its PSF-based "Matplotlib License" file (read); the SPDX identifier is **open** |

**What this means for a public repository (inferred).** #210's mapping puts
"repository at base commit" in `fixture/`. Committing it copies the source
repository into skillc, which is public. For permissive licences that is
allowed with notice retention. For pylint (GPL-2.0), or any copyleft V2 row, it
would put copyleft code into skillc; such instances should be excluded. The
issue text in `goal.md` is authored by third parties on GitHub, and Verified
declares no dataset terms for it. A lighter alternative is to reference the
fixture rather than vendor it: repository URL, base commit and image digest,
with the tree living only in the pinned image. That would fit the digest rules
of section 1 as well.

## What this means for #210 when its gate opens

**The gate has not opened.** #210 is to be picked up for building only after
#204's calibration report recommends "go". The report
([PR #212](https://github.com/cooneycw/skillc/pull/212)) recommends **REDESIGN**:
both arms were at ceiling, and the CPP arm never opened a skill. Nothing below
authorizes an importer, an import or a run.

When the gate opens:

1. **Pick SWE-rebench-V2 Python rows, not Verified.** Verified is
   self-described as contaminated, dates from 2013 to 2023, and declares no
   dataset licence. V2 is CC-BY-4.0 and dated through 2025-10-31. Re-verify each
   row's licence against its repository, and exclude copyleft rows.
2. **Record dates against a declared cutoff before sizing anything.**
   - Add `model.cutoff` and `cutoff_source` to the declaration.
   - Add `instance_created_at` and `fix_merged_at` to each task.
   - Add a check with a committed red case that reports `unknown`, never
     `after-cutoff`, when the cutoff is unpublished.
3. **Decide the image shape first:** one derived image per instance, pulled by
   upstream manifest digest and extended with the trial layer. Then pick one
   declaration per instance, or a per-task image map under the existing
   measured-equals-declared refusal. Extend `check_pins` to the new base-digest
   pin, with its own red case.
4. **Close the four integrity gaps before any live run:**
   - scoped capture with an overlay probe;
   - a provider-only agent egress allowlist, per the #11 ruling's own stated
     alternative;
   - a probe that neutralizes candidate test infrastructure, plus a
     `tests-untouched` criterion;
   - a container backend for `qualify.py`'s grading path.
5. **Certify with sound mechanical candidates only.**
   - Use test-only edits (including an outcome-rewriting `conftest.py`) and
     gold-plus-breakage, each with a measured `expected.json`.
   - Do not use the empty patch or a revert as wrong candidates; both duplicate
     the fixture.
   - Treat partial-gold and mutant candidates as measured, not constructed.
   - Plan to hand-select at least one real alternative per instance, because
     `qualify.py` refuses an empty population.
6. **Expect the #204 ceiling problem to recur.** A floor check at ceiling cannot
   show harm. Calibrate the family with the #204 two-arm procedure before any
   comparison, as PR #212's "What #203 needs" item 4 already requires.

## Provenance and upstream pins

Re-pinned 2026-09-30 at 21:13 UTC through
`gh api repos/<o>/<r>/commits/<default branch> --jq .sha` and
`gh api repos/<o>/<r>/license`:

| Repository | Default branch | HEAD (2026-09-30) | Commit date | Licence | Moved from #210's body? |
|---|---|---|---|---|---|
| [SWE-bench/SWE-bench](https://github.com/SWE-bench/SWE-bench/tree/02e7a74ffd0b707aab73d203fe87bdc7c76afc8e) | main | `02e7a74ffd0b707aab73d203fe87bdc7c76afc8e` | 2026-09-02 | MIT | No |
| [SWE-rebench/SWE-rebench-V2](https://github.com/SWE-rebench/SWE-rebench-V2/tree/c71902a8cf8d2b725f63d51f199f4d3e56f68d2d) | main | `c71902a8cf8d2b725f63d51f199f4d3e56f68d2d` | 2026-03-12 | MIT | No |
| [multi-swe-bench/multi-swe-bench](https://github.com/multi-swe-bench/multi-swe-bench/tree/24f493f8a103e72312ded4f6b9c89f081d69cb09) | main | `24f493f8a103e72312ded4f6b9c89f081d69cb09` | 2025-12-18 | Apache-2.0 | No |
| [harbor-framework/terminal-bench-1](https://github.com/harbor-framework/terminal-bench-1/tree/d28711d0da2675d0bb1d56de45ae5df6082438a3) | main | `d28711d0da2675d0bb1d56de45ae5df6082438a3` | 2026-07-11 | Apache-2.0 | No |

Also read, for identification only:

- SWE-bench `v4.1.0` (`726c546`), for the older three-layer image model;
- SWE-bench/swe-bench-tasks at `3d07b46`, for one task Dockerfile and `eval.sh`;
- the Hugging Face dataset shas listed in section 6.

Note for later readers: SWE-bench's pinned HEAD is after its v5.0.0 restructure
(2026-08-17). Documentation describing base and env images, or a
`--cache_level` flag, describes v4. At `02e7a74`, `--cache_level` is still
documented but no longer accepted (a search of `run_evaluation.py` finds it at
`v4.1.0` L279 and not at the pin).

Web sources were read on 2026-09-30 and are living pages; a later reader may see
different text. The "read (summary)" claims above come from those pages'
extracted text and were not checked word for word.

**Evidence and limits.** Everything here is static reading. No upstream code was
run, installed, imported or vendored. No dataset file was downloaded; row
statistics come from the Hugging Face datasets-server API. No image was pulled
or built, and no model was called. File counts come from the GitHub tree API at
each repository's current default branch, not at any instance's base commit.
Per ADR 0003, a design note that later adopts an idea from any upstream named
here names that upstream and links this document.
