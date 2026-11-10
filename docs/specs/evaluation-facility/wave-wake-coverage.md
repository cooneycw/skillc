# Issue #622 delivery map

Baseline: main `5e10683e3b942049dd312b7fe0b5f5c7b2169551`, including PR #664.
The file:line references below name that baseline, so later parser additions do
not obscure what was already delivered. This is a scope map, not new physical
qualification. Test names are in `tests/test_wave_wake.py` unless qualified.

| #622 requirement | Baseline delivery and proof | Remaining work |
|---|---|---|
| Arm-neutral trigger | Delivered model-free: `wave_wake.py:219` runs fixed observer source; `wave_snapshot.py:26,83` hash opaque files and refs. `test_scripted_arms_receive_identical_controller_pokes`, `test_snapshot_finds_file_ref_and_permission_changes_without_parsing_messages`. | Retain independent replay custody; no native wake claim. |
| Observe outside roles; only resume an idle role | Delivered model-free: `wave_wake.py:150,166,236` eligibility and acting-time checks; `docker_wave.py:246` lock-time session fence. `test_committed_wake_conditions`, `test_session_change_between_offer_and_execution_is_fenced_and_recorded`, `tests/test_docker_wave.py::test_resume_rechecks_expected_session_under_the_role_lock`. | Strict malformed-input refusal added by the first incremental slice. |
| Declared literal; no interpretation of agent text | Partially delivered: `controller_turns.py:170,217` reads only the initial client header and builds measured argv; `wave_wake.py:44,236` binds a supplied literal to its generated runtime declaration. `test_literal_and_every_policy_axis_are_bound_to_digest`, existing controller-turn header/argv controls. | First slice requires the separately approved caller declaration binding before prepare/turn. No new live caller is authorized. |
| Declared policy identical across arms | Partially delivered: `wave_wake.py:44` immutable policy, `:117,150,166` failure/cap/spacing, parity controls. | Closed explicit schema and whole-declaration fence in the first slice; final study declaration remains caller work. |
| Record each poke and report counts | Producer delivered, replay custody partial: `wave_wake.py:166,195,202` records attempts/revisions/time, joins turn exits and projects per-role counts. `test_spacing_watermark_and_attempts_are_distinct_from_receipt`, `test_count_projection_has_explicit_session_binding_and_unobserved_null`, `test_known_attempt_counts_survive_journal_error_without_null_fallback`. | Sealed content-addressed capture and verifier adapter in the second slice. Mutable projections are not replay authority. |
| Never poke a running watch | Delivered model-free: `wave_wake.py:150,166,236`. `test_running_blocking_role_is_not_poked_while_sibling_activity_changes`. | Preserve the witness and its known idle/live twin. |
| No-CPP arm gets equal pokes | Delivered model-free: `wave_wake.py:236` has no arm/mailbox eligibility input. `test_scripted_arms_receive_identical_controller_pokes` covers both arms. | Preserve parity under identical controlled activity. |
| Lost poke reaches declared endpoint | Delivered model-free: `wave_wake.py:195,236`. `test_suppressed_poke_reaches_original_deadline_never_pass`; consumed revisions are not receipt. | Preserve original deadline and separate capped/STOPPED from task success. |
| Wrong role/stale session refused and recorded | Delivered for well-formed tokens: `wave_wake.py:166`, `docker_wave.py:246`. `test_cap_ends_role_and_forged_role_does_not_consume_legitimate_token`, stale-session controls and lock fence. | First slice closes malformed constructor/transition inputs. |
| Poke cap ends role as declared | Delivered model-free: `wave_wake.py:117,150`. `test_cap_ends_role_and_forged_role_does_not_consume_legitimate_token`, `test_cap_also_refuses_a_second_revision_after_an_unconfirmed_attempt`. | Preserve cap and count semantics. |
| Borrowing conditions | Delivered as design attribution, no copied text: existing `wave-wake.md` cites source path/line/SHA. | Preserve attribution; any future copying requires its own private-identity/secret scan. No dependency on the source repository. |
| Native wake | Deferred by the issue. Existing report states UNOBSERVED. | Later phase, outside these two slices. |
| No live model trials | Compliant: all focused wake evidence is scripted. | Separate approval is required for any live study. |

The existing real-Docker wave tests exercise fixed scripted resumed turns and
physical transport/retirement, not `wave_wake.drive`. Issue #621 records its
successful fixed-wave qualification at `3632e39a`. That does not qualify dynamic
wake. Therefore this map does not recommend issue closure on that evidence.
The final closure decision needs both remaining-scope review and a truthful
statement of which dynamic-wake path was qualified. No new real-Docker run is
part of the first incremental input-validation slice.
