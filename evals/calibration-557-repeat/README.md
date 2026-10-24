# #557: fresh historical B/N/P repeat

Approval checkpoint (2026-10-24): **launch authorized; trials not yet started
at this checkpoint**. The owner requested 18 new attempts; the wave
orchestrator reviewed the exact declaration under delegated authority. Its
`approval` records that real review at canonical digest
`sha256:e89f5ae9fd71e69a60701bce8295036c0c0c06b2276188caea92e635956980ee`.
This directory does not restore `calibration-09960aea` or its missing private
source. Its original [report](../calibration-203-c3/report.md) remains historical.

## Inputs and interpretation

| Input | Original | Repeat |
|---|---|---|
| Task | `helper-different-question` revision 1 at `fc02838` | Exact 188-file byte/mode archive in `historical-task-v1` |
| Task tree | `2321b8cfd1dc45ce10449e87df2e373a02a2629c` | Same source tree, verified file by file |
| CPP | `85e9b03ad2af1c41020ff6d92d36fa257bdacd2b` | Same full `cpp-codex` surface, no profile |
| Client | Codex `0.157.1` | Replacement image actually reports `codex-cli 0.157.1` |
| Model/effort | `gpt-6-astra`, `high` | Same declared request; observed facts reported separately |
| Image | `sha256:eb17e8c7995f69c4f849d6d8a9165eddfd0ccc8065b5425e0bdc2e3595a86d44` (unavailable) | `sha256:b9816879e22d1f62dc6b8614c787e7666c1d9f438437c3d03d3c622513d1a563` |
| Controller | Historical checkout | Reviewed source `5f302a0619dfc88a53025bd177489214353eed0f` after #547; frozen |
| Evidence | Historical report; complete source not located | New durable private run store; no old attempt identities reused |

Revision 1 has an interpretation ambiguity: its public goal requests the exact
approved change, while the grader requires fixing duplicated step numbering
inside the approved text. Keep that ambiguity explicit. Revision 2 clarified
this and remains untouched at `evals/level3/helper-different-question`.
Certifying revision 1's grader proves it discriminates its committed examples;
it does not resolve this ambiguity or prove the task measures general skill
value. A repeated floor or ceiling cannot establish an improvement. A new
failure is not guaranteed, and is not obtained by adding attempts.

`historical-task-v1` is a verbatim archive, including its old README and
provenance. Historical commands or claims inside that archive describe the old
task. The commands and limitations here govern the new repeat.

## Schedule and bounds

The declaration preserves the original arms, instructions, primary endpoint,
six attempts per arm and seed `20261005` sequence:

```
B B N B N P B N P P N P P N N P B B
```

B installs nothing; N installs the whole pinned CPP native Codex skill surface;
P installs exactly that same surface and adds the original instruction to read
`flow-auto` and `flow-check`. No workflow profile, extra prompt guidance or
runtime-supply profile receipt is added. Current CLI refuses a runtime receipt
for this generic subject. Do not copy the old live controller just to obtain
the old task.

Each attempt has at most 1200 seconds; the schedule cap is 21600 seconds. This
is a scheduling budget, not an absolute setup/grading/cleanup deadline. Report
setup, agent/schedule and cleanup wall time separately. Keep all 18 slots,
including failed/unavailable/non-started attempts. No automatic retries,
replacement attempts, added arms or hidden exclusions are authorized.

Use the normal rotating local subscription login, never an API key. The only
judge is the deterministic historical grader; there is no API judge spend.
Report measured token/quota usage, and missing cost as unknown. Do not convert
quota usage into a measured dollar charge or missing cost into zero.

## Preparation and source freeze

Use this directory's isolated repository checkout. The preflight prepends that
checkout to Python's import path and verifies the loaded `skillc` modules and
runtime root. Before importing controller modules it selects a fresh private
Python bytecode cache, so stale or unchecked-hash `.pyc` files beside verified
source cannot substitute different executable code. The launch wrapper below
does the same for the trial process; `-B` alone would still read old bytecode.
The committed divergent-cache control proves both that its bad bytecode is
loadable normally and that the production fresh-cache boundary executes source.
`controller` binds the reviewed source commit and Git objects
for `skillc`, all `docker` bootstrap/steward/shim sources, the generic subject
descriptor, `pyproject.toml` and `uv.lock`. It compares the actual working
files, population and executable bits against that source, including untracked
files (except Python bytecode caches). A changed source is a refusal, even if
a later source tree would independently pass its tests.

Source freeze approved by the wave orchestrator on 2026-10-24: controller
`5f302a0619dfc88a53025bd177489214353eed0f`, containing reviewed retention merge
`c80455538d4412391a375b76202f8c4ec6338be7`. The declaration records its five
source objects and `retention_547_reviewed: true`; the separate launch ruling
is recorded in the approval field.
Later wave merges must not replace this runtime.

The source commit is the reviewed controller base, rather than the commit
containing this manifest, which would make its identity self-referential. After
#547 merges, incorporate that reviewed source, update the source commit/objects,
and set `retention_547_reviewed` true only after root reviews the prerequisite.
Then freeze an isolated run checkout at the reviewed preparation commit. Do not
pull, merge, edit controller dependencies or reuse another run's Python
installation there during the experiment. Other wave merges are not a reason
to silently update this run. If frozen source drifts, stop and return the new
declaration and evidence to the orchestrator.

The historical goal/grader/fixture fingerprints live in
`historical_source.content` and are recomputed with the production identity
function. The reserved top-level `task_content` is coupled to the newer
`outcome_endpoint` experiment kind, whose image receipt requirements differ;
this repeat preserves the original calibration's endpoint and generic image
path. The whole-declaration approval binds these historical fingerprints,
controller objects, image, egress allowlist, schedule and store together.

From the isolated checkout root, these commands spend no model quota:

```bash
python3 evals/calibration-557-repeat/preflight.py --stage prepare --image --credential --qualify
python3 evals/calibration-557-repeat/preflight.py --stage launch-ready
```

The first must finish `PREPARED; NOT AUTHORIZED TO LAUNCH`; it exercises every
committed negative input in `controls.json`, and must reject unexpectedly
accepted controls. The second must exit nonzero while approval is absent.
The image probe is `docker run --rm --network none --entrypoint codex <digest>
--version`, with no credential/home mounts. It verifies the actual executable
and resolved image, not a tag or label. No normal model invocation or model
listing is hidden in these controls. Credential selection/lifetime eligibility
prints no secret or local identity and does not claim the login will remain
fresh indefinitely; runtime rereads it before each trial.

## Exact declaration review and launch

Send the orchestrator the final canonical declaration digest printed by
preflight, reviewed controller source identity, image probe, full grader/control
results and private retention location. The owner's request authorizes these
18 attempts under the stated bounds; the orchestrator reviews the exact
replacement identities under delegated authority. Record the actual reviewer,
date, request source, six attempts per arm and `declaration_digest` in
`approval`. Do not claim the owner reviewed an unseen digest. Within this
scope no repeated owner prompt is needed. Preparation approval alone is not
launch approval, and no code here manufactures an approval for the real file.
Synthetic approvals exist only in memory in model-free negative controls.

The runtime already supplies separate disposable homes/workspaces, twin-container
skill discovery for treated arms, provider-only egress, server-side tool opt-outs,
credential stewardship and nested-Codex containment. These apply to the empty
baseline too; only installing the skills and the P instruction differ. The
grader is contained without provider egress. Keep these mechanisms enabled; no
host config changes or credential transfer to another machine is required.
Check the relevant runtime tests/negative controls after the #547 merge, and
inspect each actual attempt's network, credential/guard, client/model and
observation evidence. A prep check or dry rehearsal cannot establish those
runtime facts. The declared reasoning effort is not proof of observed effort;
report the raw observed field if available, otherwise unknown.

Only after the exact declaration ruling, from the frozen checkout, with its
own locked environment and source imports:

```bash
uv sync --locked --extra dev
SKILLC_ALLOW_REAL_AGENT=1 uv run --no-sync python evals/calibration-557-repeat/preflight.py --stage launch-ready --image --credential --qualify
```

If and only if this exits zero, invoke the approved run once:

```bash
SKILLC_ALLOW_REAL_AGENT=1 PYTHONPATH="$PWD" uv run --no-sync python - <<'PY'
import subprocess
import sys
import tempfile

with tempfile.TemporaryDirectory(prefix="skillc-557-launch-cache-") as cache:
    command = [
        sys.executable, "-X", f"pycache_prefix={cache}", "-m", "skillc.cli",
        "calibration-run", "evals/calibration-557-repeat/run-manifest.json",
        "--image", "sha256:b9816879e22d1f62dc6b8614c787e7666c1d9f438437c3d03d3c622513d1a563",
    ]
    result = subprocess.run(command, check=False)
raise SystemExit(result.returncode)
PY
```

The deliberate opt-in is required. Do not pass a profile runtime-supply receipt,
override the model/effort, pass `--private-dir` to a different store, or launch
from the shared moving main checkout. Ordinary `--rehearse` accounts the slots
but skips the actual client/image checks; if reviewed separately, retain its
output as rehearsal and never report it as behavioral evidence.

## Retention and publication

`run_store` names `~/.local/share/skillc/calibration-557-repeat`, using `~/` to
avoid committing a machine identity. It is outside temp/session/worktree
storage, and the production validator refuses temporary destinations. Runtime
creates a unique private run directory. Never remove it during checkout
cleanup. Preserve the frozen declaration/controller identity, planned ledger,
all attempt lifecycle records, source manifests, artifact object bytes,
transcripts including failed attempts, observations and final summaries with
their original hashes. Preserve unavailable and interrupted slots too.
Verify object bytes/manifests against the source store before reporting
coverage complete; retaining a summary alone is insufficient. Store full raw
output privately and publish only privacy-checked derived evidence.

Update [report.md](report.md) with all 18 planned identities and separate
outcome, uptake, readiness, evaluability, duration, guard/egress eligibility and
usage facts. Cite private source manifests/objects by logical identity/hash,
not machine paths. Exercise the leak check on its committed bad fixture before
trusting clean output. Assess each failure's lineage for #28; if none qualifies,
state that and stop. Do not reconstruct old identities or repeat until a desired
failure appears. Issue #557 remains open until the separately gated run and its
complete privacy-checked report are delivered.
