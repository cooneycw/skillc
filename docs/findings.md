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

`ci/clean-install-check.sh` proves both halves in a disposable, network-free
environment:

1. **Absent packaged controls refuse certification.** `skillc selftest` from a
   wheel install exits `2` and names the absent `controls` directory. It does
   not silently skip (which would read as "nothing to prove, so nothing is
   wrong") and it does not crash (which is not a refusal). This is the
   supported answer to "can a clean installation of the distributed checker
   prove its own rules": no, and it says so.
2. **The packaged rule code still discriminates.** `skillc check` against one
   committed known-bad `SKILL.md` and one committed known-good one - copied in,
   not the whole `controls/` tree - fires and stays silent exactly as it does
   from a repo checkout. This is the thing an author actually needs working.

Run it: `bash ci/clean-install-check.sh`. It builds a wheel with `uv build`,
installs it into a fresh `uv venv` with nothing from the source tree on
`PATH`, and fails loudly (naming which half broke) on any deviation. It is
**not** wired into Woodpecker - #27's own scope note says CI expansion is not
required here, and the build+venv round trip is slower than the four gates CI
already runs on every push - so run it by hand before a release, or from a
local pre-release checklist.

**Limit:** this proves the wheel round-trips through `uv build` + `uv venv` +
`uv pip install` on this host. It does not certify every installer (a plain
`pip install`, a different Python, a different OS) and does not replace
`skillc selftest` against the real `controls/` tree in a repo checkout, which
CI still runs on every push.
