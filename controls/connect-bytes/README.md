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

Local byte/control files: 401 passing controls. Prior 377 policy controls remain
green. Real-Docker forwarding and absent-handler controls are in the existing
certification-floor file, skipped here because Docker is absent; the scheduled
merge-commit run is owed before forwarding can be called physically verified.
No live NHL execution or credential handling is enabled by these controls.
