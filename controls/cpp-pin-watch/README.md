# CPP pin-watch controls

`cases.json` is the committed input/expected-verdict table. The tests build tiny
local Git histories and a normal verified profile inventory; all source reads,
source identity checks, closure derivation and classification use the real code.
No network is required by `tests/test_cpp_pin_watch.py`.

The cases distinguish self/none, contract prose and gate changes, structural
removal/addition, unrelated library edits, the silent-success gate implementation
and receipt schema 5. Additional tests cover corrupt evidence, missing objects,
file modes/types, privacy seeds, posting opt-in, remote retry, classification-only
deduplication, exclusive local locks and matching author/receipt checks.

The public-consumer blind-classifier and historical-control tests deliberately
substitute none for a real contract change and require the expected-verdict
assertion/control to fail. External mutation verification also produced ten
failing changed cases and one passing self case; suppressing additions lost the
new selected-root-file case. These are controls for an instrument, not claims
that a pre-existing classifier had a regression.

`historical.json` is the immutable real CPP pair (86641e8 -> 63e0698) with exact
expected paths: four changed, twenty-six removed and one added. It is replayed
with `--historical-control` against a CPP Git clone, never against vendored CPP
code or as a network dependency of `make verify`. A partial clone can fetch
missing immutable objects. The command refuses unavailable or mismatched evidence
and never posts. Default-policy and historical readings do not repin anything.
