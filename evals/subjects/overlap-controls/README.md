# Overlap controls (#726 acceptance 1)

Two planted collections for `skillc charter overlap`:

| case | planted | a working comparator must report |
|---|---|---|
| `shared-paraphrase` | `alpha.always-1` and `beta.always-1` state ONE duty in different words (the owner approves a plain-language plan before any edit) | `shared` for that pair, and nothing else |
| `distinct-vocabulary` | `gamma.always-1` and `delta.always-1` share words on purpose (owner, summary, plan, approval, edit) but are different duties (a post-merge report, and editing a template) | nothing |

The second duty in each charter is filler that shares no meaning across the
pair. In `distinct-vocabulary`, `gamma.always-2` and `delta.always-2` do repeat
the filler of `shared-paraphrase`, but they are different from each other.

These cases are what make the comparison a **meaning** test. A word-overlap
comparator gets both of them wrong (`tests/test_overlap.py` shows this): it
misses the paraphrase and flags the shared vocabulary.

Their **live** verdict needs a model, which is sized, not run (#747). That run
is a separate step after PR B merges, and it reports the model, the replicate
count and the agreement rate. Until it runs, `tests/test_overlap.py` proves only
that the machinery reports what a comparator says, including `UNKNOWN` when
replicates disagree.
