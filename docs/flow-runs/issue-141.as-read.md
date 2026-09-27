# Issue #141 as read by this run

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #141
- Read at:      2026-09-27T17:12:29Z
- updatedAt:    2026-09-27T14:31:40Z   (context only - moves on comments and labels)
- Body digest:  1db0346edf8d0851636bf032acee987bf97a951d31ef85e6eb1071bfd466e5b9   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2459 of 2459 (cap 16384)

## Body as read
Refs #12. Promotes the nit-store item https://github.com/cooneycw/skillc/issues/20#issuecomment-5856506955 (owner ruling 2026-09-27: file it, pin `gpt-6-astra`).

## Problem

A pilot's declared model is not passed to the client. `skillc pilot-run` launches `collection_conformance.DEFAULT_CLIENT_ARGV` (`codex exec --sandbox danger-full-access --skip-git-repo-check`) with no `-m`, so codex uses whatever its own default is at that moment.

On #12's live run (PR #140) the manifest declared `gpt-5.1-codex`, an unconfirmed assumption from the planning PR. Every attempt ran `gpt-6-astra`. The report records this after the fact (`model_matches_declaration: false`, `protocol_deviations`), but nothing prevented it.

Defaulting to "latest" is rejected. A pilot is only valid if every attempt runs the declared model. A floating default can change between arms or between runs without anyone seeing it. The pin has to be explicit, and it has to be checked.

## Owner ruling

Pin **`gpt-6-astra`**, the model codex resolves to today and the one #12's attempts actually ran (reasoning effort `high`, observed on all 6).

## Acceptance

- [ ] The run manifest declares the model, and the reasoning effort that was observed, and the runner passes both to the client at launch (`codex exec -m gpt-6-astra`, plus the effort setting codex 0.157.1 accepts). The launch argv is built from the declaration and never hardcoded, so the next change of pin is a one-line manifest edit in its own commit.
- [ ] Before the schedule, the runner refuses a client argv that overrides the declared model (for example `--client-argv ... -m other`).
- [ ] After each attempt, the observed model (`transcript_adapter.codex_run_metadata`) must equal the declared one. A mismatch, or no observed model at all, makes that attempt ineligible for the comparison and fails the run with a non-zero exit. It is recorded, never silently compared. Red cases: a scripted transcript naming another model, and a transcript with no `turn_context`.
- [ ] #12's own predeclaration is NOT edited. A re-run of the pilot declares `gpt-6-astra` in a new, dated declaration that says which run it supersedes, so the #12 deviation stays on the record as it happened.
- [ ] `evals/matched-pilot/README.md` and the evidence README state which declaration is current.

## Out of scope

Judge-tier model identity, which is a separate folded-in item on #12, and the codex version inside the image (nit store).

