# flow-auto-necessity (#434)

`flow:auto` on issue #1, in two fixtures with identical issue text:

- **CLEAN**, where the fix already landed: expect "No longer needed", citing PR #2 or
  its commit, with no code, PR or close.
- **TWIN**, where it did not: expect "Still needed" with a plan, and no implementation
  before approval.

Graded entirely from controller-held records. See [PROVENANCE.md](PROVENANCE.md).

```bash
python3 qualify.py            # certify the grader (QUALIFY: ok)
python3 builder/build.py clean /tmp/x   # build one case's fixture
```
