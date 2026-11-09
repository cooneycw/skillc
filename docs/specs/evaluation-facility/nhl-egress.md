# Declaration-bound NHL egress (Refs #638)

This slice is infrastructure and synthetic qualification only. The current
`APPROVED_LIVE_DECLARATIONS` registry is empty, and the live permit/window join
is explicitly unavailable. No declaration JSON, environment variable, copied
permit or raw backend host tuple enables real NHL execution. A later reviewed
#639 freeze and its owner approval must supply the exact live identity and
controller authority join. This slice does not approve sizing, host operations
or any live/model run, and does not remove #630's credential dispatch hold.

## Closed declaration and provenance

An optional top-level `nhl_egress` object has exactly these fields:

```json
{
  "version": 1,
  "purpose": "synthetic-control",
  "hosts": ["api-web.nhle.com", "api.nhle.com"],
  "port": 443,
  "stop_on_denied": true
}
```

The other recognized purposes are `sizing` and `live`, each requiring its own
future exact frozen approval. Parsing a purpose is not permission. Only the
two named NHL hosts extend the existing provider hosts; no wildcard, suffix,
additional host, alternate port or ad hoc override is accepted. Server-side
channels remain disabled. `shared.agent_network` binds the
`nhl-declaration-egress` document digest and existing server-side-off flags.
The whole-declaration approval binds the new object and its purpose. Removing
or changing a field after recorded approval invalidates that provenance.
Discrimination declarations do not silently acquire this opt-in.

`Session` copies and validates the declaration and recorded approval provenance.
Its synthetic permits register an exact object, attempt ID and backend instance.
Because the backend is immutable, issue the permit, construct the backend with
it, and bind that backend once. A copied permit, a lookalike issuer, another
backend/attempt, duplicate binding, revocation or changed declaration is refused.
This is a trusted-controller provenance contract, not isolation against Python
code executing inside that controller process.

A registered synthetic permit can qualify the fixture policy seam in both arms.
It cannot prepare or execute a Docker container: real backend entry points
reject it before subprocess I/O. The future live issuer must join ordinary
`require_approved`, exact frozen authority and admitted window dispatch; changing
the registry alone is insufficient. No such issuer is enabled here. Non-NHL
legacy declarations retain their default policy and record shape.

## Strict stop and retained interpretation

The policy and proxy use the same shipped CONNECT decision for exact hosts on
port 443. The compiled document identifies the NHL policy rather than claiming
that the historical provider-only measurement qualified these extra hosts.
Grading backends remain isolated and gain no new egress.

The strict opt-in treats a positive denied request to an undeclared host as a
stop, as well as any successfully allowed off-list target. Missing/malformed
policy evidence or a mismatched proxy digest is unavailable, never an empty
clean census. The selected execution path attaches this observation to its
existing cancel callback, polling between bounded proxy-log reads. A controller
stop latches for that attempt, survives a later readable log, and is retained
beside the raw proxy evidence. Actual cancellation/retirement still follows the
existing owned lifecycle; no global process or resource sweep is added.

Native scheduling skips later attempts after that retained stop. It stores the
whole declaration with each opted-in trial configuration. Reporting and recovery
derive policy from the uniform verified launch binding, not participant output
or a caller-supplied replacement. They reject partial/mixed bindings, changed
approval or a stop marker inconsistent with observed evidence. A read-only
report is not a live permit. Historical observation alone never proves an old
controller stopped its schedule.

Legacy provider-only traffic keeps its existing behavior, including harmless
denied traffic that formerly continued. In particular the historical denied
provider telemetry host is not silently exempted in the new strict policy:
an eventual rehearsal may stop on it. Any desired change needs a newly approved
declaration, not a hidden allowlist addition.

## Evidence and remaining scope

The unchanged existing-consumer behavior file gives 14 meaningful failures and
eight passing preservation controls on pre-fix main e22a436. Failures concern
allowed NHL scheduling, undeclared-request continuation, ignored closed-policy
fields and unfrozen approval. New-API import failures are not red evidence.
The schedule harness replaces approval and expensive attempt/backend boundaries
only for synthetic observations; separate unpatched checks refuse every NHL
purpose at live approval, preparation and execution. The permit and cancellation
controls use fake I/O boundaries. None is a real-daemon qualification.

Committed allow-all, ignore-denied and always-issue variants expose known-bad
continuation/admission. Legacy policy/digest and denied-traffic classification
are pinned byte for byte in a parent-derived fixture. Public recovery, checkpoint
immutability and refusal controls accompany those policy cases.

HTTP request counts and response codes are **not measured** by encrypted CONNECT
tunnels. The byte telemetry below observes encrypted transport only. No TLS
interception or fetch seam is added. Declared limit modes, long-window parameters and the
owner-run headroom helper are PR-C. Credential validity/coverage and any auth
material remain separate #630 work; no credential code is changed here.
Physical proxy/deny/cancellation qualification, actual VM and role wiring,
approved sizing and the final frozen execution declaration remain deferred.

## Complete input-shape qualification

The committed 42-level table covers null, scalar, list, string and missing/extra
object shapes at all new fixed-data and permit/session boundaries. Invalid
observations raise PolicyRefused at the validator; execution, scheduling and
fixture observers convert that to a retained unavailable-evidence stop. No
TypeError/AttributeError/KeyError is treated as a valid policy verdict. Optional
summary fields and connection counters have explicit types; legacy config
dictionaries without the NHL opt-in remain extensible. The table distinguishes
new explicit error contracts from older fail-closed diagnostic returns. It also
qualifies the top-level and nested stored-declaration refusal guards.


## CONNECT bytes observed (PR-B)

The strict NHL proxy observes bytes at each directional read boundary, before
write/drain, including TLS overhead. These are **bytes observed**, not bytes
confirmed delivered. A connection can carry many application requests. Every
byte report states: **HTTP request counts and response codes not measured**.
CONNECT denials/upstream failures remain distinct from application failures.

Each strict proxy process gets a generation ID. Successful tunnels get ordered
connection IDs, independent cumulative directional counters and monotone
connection sequences. A one-second progress checkpoint preserves lower bounds
for an active long tunnel; EOF closes it with a final record. Read/write errors
or cancellation mark the tunnel incomplete. Every strict log line carries a
monotone global sequence and SHA256 of its predecessor's exact bytes.

At the existing pre-teardown observation boundary, the controller sends
`docker kill --signal SIGUSR1` to its owned proxy. The handler closes the
listener, briefly allows pending handlers to finish, then cancels remaining
handlers and writes one trailer containing the record count, last hash,
generation and final connection census. It remains alive solely for capture
until ordinary teardown removes it. A second signal or a late connection cannot
extend or erase the sealed log. The whole controller signal/read wait has a
three-second budget. Signal failure, missing handler, timeout, unreadable or
oversized capture never prevents existing destroy/absence confirmation.

Only a verified chain, matching policy document/digest and generation, complete
connection sequence/census and matching shutdown trailer can yield COMPLETE.
A complete zero-byte tunnel or a complete empty connection population can
truthfully report zero. Missing finals/trailer, counter regression, overflow,
malformed fields, broken/reordered/replayed records or truncated evidence yield
UNKNOWN with null totals. Valid pre-interruption checkpoints can remain as
explicit lower bounds, never as complete totals. No mid-run byte total admits
work or controls the policy stop. Policy observation retains its existing
strict deny/bypass rules separately from byte completeness.

Strict capture reads at most 8 MiB, with an extra byte to detect overflow;
oversized logs become unavailable rather than a partial zero. This is a
technical capture bound, not an approved study traffic budget. Logs are still
retained only in the owned proxy and capture store; this does not establish a
disk reservation or a multi-hour storage budget. Legacy provider-only proxy
source, argv, logs and report shape remain unchanged.

The committed existing-consumer controls on actual pre-fix main f16112e give
10 failures (missing measurement outputs and stream records) and three
preservation passes. They import only existing APIs. The new parser tests also
qualify malformed raw JSON, nested field shapes, every prefix truncation of a
fixed stream and four blind variants. Loopback subprocess tests drive the
shipped script with fixed/chopped streams and repeated signals. They are not
proof of Docker signal forwarding.

Two real-Docker cases live in `tests/test_agent_egress_live.py`, already in the
scheduled runner's declared file floor: actual `--init` forwarding and an
absent-handler negative twin. They make no external requests and use no client
or credential. Local Docker absence is an honest skip. After merge, the
scheduled real-Docker certification on the merge commit must execute the new
nodes (the previous 49-node population grows by two); only that run qualifies
actual init forwarding. Live NHL admission remains held by PR-A and #630.
