# Exposure evidence: a synthetic surface exercising truncation

- Declaration: [subject.json](subject.json) - a small fixture collection
  authored for this PR, not a real project
- Collection: [collection/](collection/) - one trivial skill (`greet`), an
  `AGENTS.md`, and an on-demand index (`docs/memory-index.md` naming
  `docs/topic-a.md`)
- Adapter: `skillc exposure` ([skillc/exposure.py](../../../skillc/exposure.py), #55)
- Evidence: [evidence/report.json](evidence/report.json), produced 2026-09-26,
  real `codex-cli 0.157.1`, `--snapshot collection`

This is #55's synthetic-surface evidence bullet: a fixture built specifically
to exercise all three declarable layers at once (always-loaded file with a
claimed size limit, an index with an on-demand target, and a skill listing).

**The real result, honestly, not the predicted one:** `AGENTS.md` declares a
`claimed_limit_bytes: 2000`. The real 169-byte `AGENTS.md` is preserved in
full (never replaced by synthetic filler - a cross-model review finding on
an earlier draft, PR #90), with an inside marker planted right after it to
end at byte 2000, and an outside marker planted beyond that boundary. Both
are reported `EXPOSED` - real `codex-cli 0.157.1` did NOT truncate at this
boundary. This is itself the finding, not an instrument failure: `skillc
exposure`'s job is to report the real cut point (if any) against a claimed
limit, never to force a chosen outcome. Separately verified up to a 30 KB
`AGENTS.md` during this PR's own development (not committed as evidence,
since it used a throwaway scratch fixture) - no truncation observed there
either, which does not match
[ADR 0004](../../../docs/decisions/0004-evaluate-the-exposed-knowledge-surface.md)'s
original ~25 KB observation. That discrepancy may reflect a different client
version, a different file, or a different mechanism (a memory index, not
`AGENTS.md`) - owed to the live run, not resolved here.

The index file and its one on-demand target are both `HIDDEN`: real Codex's
`debug prompt-input` auto-loads `AGENTS.md` specifically, but nothing makes it
surface an arbitrary declared index file on its own. This is also a real,
useful finding, not a check defect - an index a client never actually shows
the model is exactly the exposure gap #55 exists to catch, even for a file the
author fully intended to be always-visible.

Refs #55, not Closes.
