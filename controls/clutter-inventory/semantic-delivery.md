# Semantic delivery and cache replay

`semantic-delivery.json` drives `test_semantic_delivered_project_verdict` against
real disposable repositories, a pushed `nhl/api.py`, generated
`nhl/__pycache__/api.cpython-312.pyc`, and an explicitly allowed venv.

The same committed test runs against old main's public policy, Snapshot and
classifier APIs. It detects whether the classifier supports delivered captures
before supplying the new validated opt-ins. Old main gets no unsupported fields,
keywords or imports, and still reaches the classifier. Expected verdicts never
change with that capability check. This is a compatibility replay of the new
opt-in behavior, not a claim that existing declarations change automatically.

Each positive case isolates one semantic change: the delivered-tree case uses
the existing exact cache allowance; the cache-pattern case uses existing exact
product selectors. Negative twins use those existing selectors and allowances
on main, so unrelated missing features cannot manufacture their NOT_CLEAN.

Observed on unchanged main `19dc6ee7ff0fdd63650300968de43215b718a3c8`:

| Case | Main verdict | Fixed verdict |
|---|---|---|
| delivered-tree | NOT_CLEAN | CLEAN |
| cache-pattern | NOT_CLEAN | CLEAN |
| undelivered-stray | NOT_CLEAN | NOT_CLEAN |
| out-of-bounds-cache | NOT_CLEAN | NOT_CLEAN |

The old run fails two fixed CLEAN assertions and passes both negative twins.
The fixed run passes all four. The cache positive also requires an explicit
`not_inspected` report row. Neither run invokes Docker or a native client.
