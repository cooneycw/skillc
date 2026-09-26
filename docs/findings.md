# Machine-readable findings, and the packaged checker's own install (#27)

Two things an author needs beyond the human-readable CLI: something a script can
read without parsing terminal prose, and confidence that installing the
distributed checker gives them a real one, not a name that happens to import.

## `skillc check --json`

`--json` prints one JSON document to stdout instead of the human report - never
both, so `json.loads(stdout)` cannot land on a run that also printed prose. The
human-readable CLI is unchanged; this is an alternative rendering of the same
findings, not a second source of truth.

```json
{
 "schema": 1,
 "skills_checked": 1,
 "errors": 0,
 "warnings": 1,
 "findings": [
  {
   "rule": "trigger-shape",
   "severity": "warn",
   "path": "productivity/example/SKILL.md",
   "detail": "description states a capability but no triggering condition - the model reads this to decide whether to fire the skill"
  }
 ],
 "field_rules": {"target": "portable", "checked": 1, "total": 1}
}
```

- `rule` is the STABLE identity from `skillc rules` (`skillc/checks.py`'s
  `RULES`). Key a consumer's own logic on this field, never on `detail`, which
  is prose and can be reworded without notice.
- `path` is relative to the scanned root when the finding is under it, the same
  fallback the human report already uses.
- `field_rules` is `null`, with a `field_rules_reason` string, exactly when the
  human report would have printed "field rules NOT checked" instead of a count -
  a named rule scoped to one rule only, or no skill's frontmatter parsed.
- A refusal (`--json` given a path that does not exist, or a tree with no
  `SKILL.md`) is still exactly one JSON document: `{"schema": 1, "error":
  "..."}`. A consumer never has to fall back to parsing stderr for this case.
- `schema` is an integer, bumped on a breaking change to this shape, the same
  discipline `records.py`'s envelope `version` already uses.

## What a finding does, and does not, establish

A finding is a **static** claim about one `SKILL.md`'s frontmatter and body. It
says nothing about whether a client actually reaches the skill, whether the
model obeys the description's trigger, or whether the skill's instructions
produce a good outcome when followed - those are the invocation and outcome
facts `records.md`'s `installation-receipt` and `skill-invocations` observation
own, not this one. `skillc check` proves a document is well formed; it never
proves the document is a good idea.

## `scripts/repair_hint.py`: one local author consumer

The smallest useful consumer of the JSON above: it runs `skillc check --json`,
matches each finding's `rule` against a small guidance table, and prints one
line of repair advice per finding.

```bash
python3 scripts/repair_hint.py path/to/skills/tree
```

This is deliberately not a general findings API or a parallel database - one
script, one table, keyed on the rule id so a reworded `detail` string never
breaks it (`tests/test_repair_hint.py` pins a renamed/removed rule as a test
failure, not a silent guidance gap). A finding whose rule the table does not
name still prints, with a pointer to `skillc rules`, rather than silence.

`tests/test_repair_hint.py` demonstrates the full loop on one committed
fixture: `controls/trigger-shape/bad/rotate-credential/SKILL.md` is diagnosed
with a repair hint, and applying that exact hint (adding a triggering
condition to the description) makes the rule fall silent on the repaired copy.

## The checker's own installation (distinct from #7's subject materialization)

`skillc check` and `skillc selftest` answer different questions about
installation. `check` validates someone else's `SKILL.md` files; `selftest`
validates skillc's OWN rules, using skillc's own committed redcases
(`controls/`). Only the first one is a normal thing to run installed - `controls/`
is fixture data for skillc's own CI, and `pyproject.toml` deliberately does not
package it (see `[tool.hatch.build.targets.wheel]`).

`ci/clean-install-check.sh` proves three things in a disposable, network-free
environment - showing only the first would prove half the claim: an installed
checker that could never certify under any condition would refuse identically
to one that correctly refuses only when its redcases are missing.

1. **Absent packaged controls refuse certification.** `skillc selftest` from a
   wheel install exits `2` and names the absent `controls` directory. It does
   not silently skip (which would read as "nothing to prove, so nothing is
   wrong") and it does not crash (which is not a refusal).
2. **Supplied controls DO certify.** A fresh copy of `controls/` - never the
   source tree's own copy, which would prove the SOURCE rules work, not the
   installed package's - handed to the installed `skillc selftest --controls`,
   must report the identical `N/N rule(s) discriminate` the source checkout's
   own `skillc selftest` reports. This is the supported answer to "can a clean
   installation of the distributed checker prove its own rules": yes, when
   given its redcases; no, and it says so, otherwise.
3. **The packaged rule code matches the source baseline.** `skillc check`
   against one committed known-bad `SKILL.md` and one committed known-good one
   - copied in, not the whole `controls/` tree - is compared against the SAME
   fixtures checked by the source checkout (via `--json`), rule for rule and by
   `skills_checked` count. Not a hardcoded "trigger-shape must fire"
   expectation: that cannot tell a packaging regression from an unrelated rule
   change to the fixture itself, and codex cross-model review (#27) found the
   hardcoded form failed to draw that distinction.

Run it: `bash ci/clean-install-check.sh`. It builds a wheel with `uv build`,
installs it into a fresh `uv venv` with nothing from the source tree on
`PATH` **or on the current working directory** (`python -c` prepends CWD to
`sys.path`; an early draft of this script called the venv's Python with the
repo checkout as CWD and silently read the SOURCE package instead of the
installed one - see the script's own `neutral_cwd` comment for what that
broke), and fails loudly (naming which half broke) on any deviation. It is
**not** wired into Woodpecker - #27's own scope note says CI expansion is not
required here, and the build+venv round trip is slower than the four gates CI
already runs on every push - so run it by hand before a release, or from a
local pre-release checklist.

**Retained identity record.** Every run prints one JSON document to stdout
before the checks: the wheel's own content digest (`wheel_sha256`), the
installed `skillc_version`, the venv's `python_version`, the host's
`uv_version`, and the `source_commit` this build came from. Logical values
only (issue #63's rule for this public repository) - no scratch paths, no
hostnames, no usernames. A caller who wants the record kept redirects this
script's stdout to a file of their own naming; the script itself retains
nothing.

**Committed negative control.** `CLEAN_INSTALL_CONTROL=<mode> bash
ci/clean-install-check.sh` inverts the script's own verdict - the mode's job
is to break what step 2 or step 3 checks and require the script to notice, so
the control run exits `0` only when the underlying probe correctly failed:

- `neuter-installed-rule` sabotages `trigger-shape` in the **installed**
  package only (by regex, after install; the script refuses to proceed if the
  target it resolves is not under the scratch venv, exactly the guard the
  `neutral_cwd` incident above shows is needed) and requires step 3's
  bad-fixture comparison to disagree with the source baseline.
- `delete-scratch-controls` deletes the controls copy right before step 2's
  certifying run and requires that run to reproduce step 1's "controls
  directory absent" refusal rather than a false certify.

Verified by hand (not in CI - the whole script is not): both modes correctly
report `CONTROL FAILED` when the underlying probe is blind and `CONTROL ok`
when it catches the planted defect.

**Limit:** this proves the wheel round-trips through `uv build` + `uv venv` +
`uv pip install` on this host. It does not certify every installer (a plain
`pip install`, a different Python, a different OS) and does not replace
`skillc selftest` against the real `controls/` tree in a repo checkout, which
CI still runs on every push.
