# Wake capture origin controls (#622, #620 PR-B B8a)

`capture/` and `binding.json` are a sealed wake capture in the ORIGINAL
six-field context shape (no `origin_ns`). A standalone generator wrote them
from the documented format without running `skillc/wave_wake_capture.py`.
`tests/test_wave_wake_origin.py` requires them to still verify. Adding
`origin_ns` must therefore leave old contexts' serialization and digests
untouched.

The same test covers the new shape:

- an origin-bearing context round-trips and has a different digest;
- a capture must start at its recorded origin;
- an origin capture does not verify against another origin or against the
  old shape;
- malformed origins are refused.

For the task-protocol adapter's clock join:

- a matching origin joins;
- an old-shape capture or a different origin gives `clock-join-unavailable`;
- a source mutant of the real adapter that drops the origin comparison must
  be caught.
