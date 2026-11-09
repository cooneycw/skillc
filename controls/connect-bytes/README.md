# CONNECT byte evidence controls (Refs #638)

`shapes.json` contains 30 wire/transport input levels and 255 malformed variants.
Tests also remove/add fields at all closed object levels and exercise persisted
report fields, raw decoding failures, boolean counters, overflow, whole-line and
every byte-prefix truncation, cross-generation records and counter regression.
Known valid twins cover zero, nonzero, multiple tunnels and interrupted lower
bounds. Valid counters are cumulative encrypted bytes observed including TLS.
HTTP request counts and response codes not measured.

`mutants.json` contains exact source deformations and witness names. Tests run
those actual changed parsers: always-zero loses on a planted nonzero stream;
ignoring the trailer, chain or regression accepts known incomplete evidence
that the intact parser reports UNKNOWN. The detector is required to fail on
each changed parser, not merely recognize a mutant's name.

Existing-consumer regressions import only APIs present on f16112e. On that
actual main, unchanged behavior and loopback stream files yield 10 failures and
3 preservation passes. Reds are missing byte outputs or missing stream records,
not missing new helpers/imports. Partial malformed JSON already produced the
controlled unavailable refusal; legacy summary and default report shape also
already pass. These are preservation controls, not new safety-failure claims.

Local byte/control files: 450 passing controls. Prior 377 policy controls remain
green. Real-Docker forwarding and absent-handler controls are in the existing
certification-floor file, skipped here because Docker is absent; the scheduled
merge-commit run is owed before forwarding can be called physically verified.
No live NHL execution or credential handling is enabled by these controls.


The corrected connection branch mutates the progress record, not the trailer.
A committed generation-blind parser witness proves that this table detects the
missing check. On actual cbe6c5f, the public recovery and table-instrument tests
produce 11 assertion failures: nine forged COMPLETE claims over absent/invalid
retained evidence, one ignored valid retained capture, and the blind table
witness. No missing API or setup failure is counted. After the fix all pass.

`retained-shapes.json` covers seven retained-binding fields (55 wrong-type
variants), plus missing/extra event fields, raw journal roots, duplicate keys,
symlink/nonregular/missing/corrupt objects, exact-size valid-log swapping,
reader/writer identity types and write-once retention. Recovery selects the
scheduled attempt's unique journal binding, rechecks bounded no-follow object
bytes against size and digest, and reruns chain/trailer completeness. Edited
outcome summaries are ignored. Absent or unverifiable capture stays UNKNOWN.


The loopback fixture waits for the parsed matching start record and a live
process under a fixed five-second deadline. File creation is not readiness:
the proxy opens its log before binding the listener. Committed controls reject
empty/partial/wrong-root/wrong-digest logs and a dead process; a file-exists
mutant loses the positive transition witness. This test-only correction follows
a real ConnectionRefusedError during startup on head 0d6deaa, before any byte
measurement assertions. Three isolated repeats passed, exposing the race rather
than a product byte-counter failure; the failed full gate remains a failure.
