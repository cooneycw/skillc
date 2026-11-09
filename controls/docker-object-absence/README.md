# Target-bound Docker inspect absence controls (#686)

These are synthetic CLI replies exercising the actual DockerBackend methods
and public confirmation paths. No Docker daemon is invoked. `cases.json`
records exact targets, process exits, both stdout contexts, diagnostics and
expected absence/presence/UNKNOWN. The test enumerates the required case IDs so
an empty or shortened population cannot quietly earn green.

The classifier requires exit 1 and a complete supported diagnostic for the
exact, case-sensitive requested name/ID. Only fixed diagnostic words ignore
case. Formatted status queries require empty stdout; unformatted inspect allows
empty stdout or the CLI's empty-array envelope `[]`, with outer whitespace
stripped. An empty array alone is never absence evidence. Success replies keep
the existing positive-observation behavior. Other exits, signals, start errors,
timeouts, unknown formats, wrong targets/kinds, extra messages and conflicting
stdout cannot earn confirmed absence.

## Grammar evidence inventory

| Accepted diagnostic | Evidence source | Evidence limits |
| --- | --- | --- |
| `error: no such object: <target>` | [#683](https://github.com/cooneycw/skillc/issues/683) quotes the Docker 29.9.2 reply from the operator's #613 qualification. [Recorded physical result](../../docs/flow-runs/issue-568.md#first-physical-result-and-narrow-cleanup-classifier-correction) also records lowercase object-absence wording and empty-array stdout; `controls/nhl-rerun-absence` retains synthetic representative cases. | The case uses a synthetic target; no private operator identity is copied. No new live qualification is claimed. |
| `Error: No such object: <target>` and other casing of its fixed words | Existing `tests/fixtures/docker-backend/fake_docker.py` and `controls/docker-absence`; legacy wording stated in #683. | Compatibility fixtures; no held raw pre-29 daemon transcript is claimed here. |
| `Error response from daemon: network <target> not found` and lowercase fixed words | Existing fake CLI network-inspect implementation and `controls/docker-absence`. | **Synthetic compatibility only. No held Docker 29 network reply or versioned upstream source citation establishes this grammar on that daemon.** |

The repository search for diagnostic replies found the existing synthetic
controls/fake CLI plus the recorded physical container result above. Its known
positive fixture hits establish that the search can extract this wording. It
did not supply a captured Docker 29 network diagnostic. Unsupported real
wording deliberately remains UNKNOWN until evidenced and tested.

## Negative controls and release condition

Before changing production code on pinned main `cf6c02b`, the new behavior
matrix produced 84 failures and 63 passes (two new-helper predicate mutants
excluded). Actual public `confirm_absent`/`confirm_stopped` cases reproduced
false CONFIRMED on unrelated `no such file` connection errors; auxiliary
container/network cases reproduced false absence on context errors and wrong
targets. The corrected classifier rejects these committed inputs.

Committed broad-substring and always-absent predicate mutants must each fail
the connection-error witness through the public auxiliary confirmation path.
Good twins preserve legacy/current container messages, synthetic network
messages, known-present states and stopped-state confirmation. Auxiliary
UNKNOWN prevents confirming the whole handle's cleanup even when its main
container has a valid absence reply.

An over-strict grammar can turn real absence into UNKNOWN. After merge, the
scheduled skillc/real-docker certification must run on the merge commit. If
any absence or cleanup test goes red, immediately revert the change and reopen
#686 under the orchestrator/operator routing. Unit/fake gates do not replace
that qualification and do not authorize this worker to run a daemon.
