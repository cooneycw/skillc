# New wake-capture instrument qualification

The capture tests introduce a new instrument. Old main lacks the API; an import
or missing method there is not a regression red and is never counted as one.

The committed healthy controller stream has two observed roles and one poke.
The complete count adapter re-derives 1 and 0 from bytes even if a report claims
999. Missing/truncated/modified/post-seal objects, same-size valid sealed swaps,
symlinks, directories and FIFOs refuse. Separate same-hash synthetic stores
exercise malformed schemas, ordering, identity, duplicate nonces/keys, and
missing results without unrelated digest mismatch hiding the intended check.

The actual compiled mutants are in `test_wave_wake_capture.py`:

| Blind variant | Committed witness | Intact / blind result |
|---|---|---|
| Always accept capture | Missing retained object | UNKNOWN / CAPTURED |
| Ignore both object hash checks | Same-size valid sealed swap under old object name | UNKNOWN / CAPTURED |
| Trust report counts | Projection claims 999 over retained 1/0 | 1/0 / 999/999 |
| Ignore poke ordinal | First poke claims ordinal 2 with a valid byte digest | UNKNOWN / CAPTURED |
| Ignore initial binding | Initial exit names a different bound session | UNKNOWN / CAPTURED |

A stream with an unobserved role binding can be retained but is incomplete; it
cannot supply the #620 complete count adapter. A capture-write failure prevents
resume dispatch and still closes the wave. A refused queue records unconfirmed
transport, preserves the known count and yields UNKNOWN. Existing session-lock,
blocking-watch, suppressed-poke/deadline, cap, arm-parity and previous-sample
watermark tests remain preservation evidence.

`capture-shapes.json` freezes 95 parsed levels and 743 malformed variants across
context, separately held receipt, start/seal, final sessions and all nine event
kinds. Missing/extra keys, overflow/nonfinite times, invalid UTF-8/deep/duplicate
JSON, technical bounds and reader/writer boundary types supplement the table.
Tests use authored bytes, injected clocks and scripted actors only. Private root
diagnostics are excluded; a seeded leak proves that absence check can fail.

The durability witness tracks the actual open event-stream descriptor and marks
each nonce only after its real `os.fsync` returns successfully. It requires that
mark before both the transport callback and executor submission; later object
or seal flushes cannot satisfy it. Compiled omitted and deferred-event-barrier
variants must make that same witness fail. On actual head `2704974`, its old
visibility-only body accepted both variants, so the two committed witness tests
fail there with `DID NOT RAISE AssertionError`, without setup/API failures. The
strengthened witness rejects both. A direct event-fsync `OSError` prevents the
resume, preserves the known attempted count with UNKNOWN evidence and still
performs owned cleanup. This qualifies the barrier call/order; it is not a
physical power-loss qualification of storage hardware.
