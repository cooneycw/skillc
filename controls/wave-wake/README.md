# Controller wake controls

`cases.json` declares known-good file/ref changes and known-bad or unavailable
conditions: unchanged state, a running turn, unknown/busy idleness, wrong role,
stale session/revision, missing session, nonzero/timeout exit and unknown/ended
liveness. The transition tests consume the actual conditions with a healthy
baseline, so an unrelated failed prerequisite cannot mask each refusal.

`tests/test_wave_wake.py` additionally drives trusted scripted plain-file and
CPP-diagnostic arms through identical actual file-byte changes. Both must issue
the same two session-bound poke attempts. The suppressed-transport input must
reach its original declared endpoint with an unconfirmed result, never a task
PASS. A stale session planted between dispatch and execution is refused under
the role lock; missing or incompatible binding yields a null count. A running
blocking role receives no poke while its sibling changes the shared files.

The observer controls change opaque bytes and real git refs, keep an unchanged
surface stable, modify link targets outside the surface without following them,
and reject missing, over-budget or unsupported entries. The exact isolated
source used in the controller helper is executed over authored fixtures, with a
missing-remote negative case. These are model-free tests, not daemon or native
wake qualification.
