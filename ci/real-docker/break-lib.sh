#!/bin/bash
# Pure break-mode logic for the <agent-host> real-Docker runner (#315
# follow-up, orchestrator review during #269's merge). Split out of
# run-real-docker so tests/test_run_real_docker_break.py can `source` it
# directly and exercise the parsing and context-routing decisions without
# any of the runner's own infra (a config file, docker, git, curl) - none
# of that is needed to answer "what does this --break argument mean" or
# "which GitHub status context does this break mode post to."
#
# CLOSED TABLE (orchestrator review): a new break family or mode means
# editing this file AND ci/real-docker/README.md's step 8, never only one
# of the two - an entry here with no README line is undocumented, and a
# README line with no entry here is not actually enforced.
set -u

#: #183's channel break modes - unchanged from before this file existed.
#: Kept as the BARE (unprefixed) spelling too, because the README already
#: documented `--break omit-mount` etc. to the operator before family
#: prefixes existed (R2 compatibility, orchestrator review: "keep the bare
#: form working only if the README already documents it").
_BREAK_CHANNEL_MODES="omit-mount wrong-uid flip-decision"

#: #269's gate-witness break modes - no bare form was ever documented for
#: these, so (unlike the channel modes) they are refused outside the
#: `witness:` prefix; see resolve_break_spec's legacy-bare branch below.
_BREAK_WITNESS_MODES="stale-confirm-lie kill-wrong-pid gate-in-fresh-container"

#: #332's flow-check-gate-shim break modes - same no-bare-form rule as
#: witness (no bare spelling was ever documented for these either).
_BREAK_GATESHIM_MODES="synthesizes-output drops-cwd exits-zero-on-channel-failure wrong-env"

#: #266's cold-container-install break modes - no bare form, same as
#: witness. skill-mount/home-mount/mcp-mount/secret-mount each plant one
#: decoy bind mount the shared mount-emptiness oracle must catch;
#: cold-cache runs an image built without the pre-warmed uv cache layer,
#: where the offline `uv sync` must fail - the negative control proving
#: the cache is what makes the intact run work.
_BREAK_COLDINSTALL_MODES="skill-mount home-mount mcp-mount secret-mount cold-cache"

#: #343's trial-image break modes - no bare form, same as witness. `no-uv`
#: selects the `no-uv` Dockerfile stage (docker/trial/Dockerfile), where
#: the uv probe must fail - the negative control proving the pinned
#: multi-stage COPY is what makes the intact image's uv probe work.
_BREAK_TRIALIMAGE_MODES="no-uv"

#: #334's installed-closure break modes - no bare form, same as witness.
#: missing-closure omits one closure-only file from delivery entirely;
#: tampered-closure delivers it with different bytes than the bound
#: inventory's own digest expects. Both must make the real in-container
#: preflight (`agent_trial._preflight_in_container`) refuse the attempt.
#: #360 runtime faults are planted only after normal runtime validation;
#: consuming preflight must refuse the selected dependency with its specific
#: cache-miss, cache-write, or project-venv permission diagnostic.
#: shim-alters-output (#334) installs a gate shim that drops one byte of the
#: forwarded stderr; the subject-vs-controller byte-identity check must fail.
_BREAK_CLOSURE_MODES="missing-closure tampered-closure empty-runtime-cache runtime-cache-permissions project-venv-permissions shim-alters-output"

#: #338's cwd-confinement break mode - no bare form, same as witness.
#: confine-root-omitted runs the identical swapped-cwd exec WITHOUT
#: confine_root, so the real daemon's `-w` must follow the swap outside the
#: workspace root - the negative control proving confine_root is what makes
#: the intact run refuse it.
_BREAK_CWD_MODES="confine-root-omitted"

#: #442's provider-only egress break modes - no bare form, same as witness.
#: allow-all widens the per-attempt proxy to GitHub, so the "proxy denies
#: GitHub" property must fail; bridge-network also attaches the agent to the
#: default bridge, so the "a proxy-ignoring client has no route out" property
#: must fail; dns-hosts maps github.com in the agent's /etc/hosts (no route
#: added), so the "names do not resolve" property must fail. There is no
#: DNS-server mode: an --internal network resolves no external name even with
#: --dns set (measured on the runner), so it could never break anything.
_BREAK_EGRESS_MODES="allow-all bridge-network dns-hosts"

#: #280's local CI/CD profile break modes - no bare form, same as witness.
#: no-curl removes curl and old-curl replaces it with a 6.1.0 stub after
#: runtime validation, so the in-container preflight must refuse tool-curl;
#: service-down never starts the loopback health service, so the
#: healthy-deploy property (health passes, verify PROCEEDs) must fail;
#: no-probes ships templates/cicd.yml.example's shape (claude-power-pack
#: #1476), so the configured-probes property must fail; broken-build makes
#: the project's build recipe `false`, so the build-artifact property must fail.
_BREAK_CICDPROFILE_MODES="no-curl old-curl service-down no-probes broken-build"

#: #282's baseline-aware deploy-verification break modes - no bare form, same
#: as witness. regression-unprobed drops the calc smoke test from the
#: certified config, so the regressed deploy verifies PROCEED and "a
#: regression never PROCEEDs" must fail; baseline-after-deploy captures the
#: regression's baseline AFTER the deploy, so it reads as pre-existing (REVIEW)
#: and "a regression ROLLBACKs against a pre-deploy baseline" must fail;
#: restart-skipped skips the healthy deploy's restart, so "a deploy serves the
#: release it meant to" must fail.
_BREAK_CICDVERIFY_MODES="regression-unprobed baseline-after-deploy restart-skipped"

# Resolves a --break argument to ELEVEN lines on stdout: the NORMALIZED spec
# ("none", or "<family>:<mode>" - a bare legacy channel mode is normalized
# to its "channel:<mode>" form here, so every caller downstream has exactly
# one spelling to compare against "none"), the value to export as
# SKILLC_LIVE_TEST_BREAK, the value to export as SKILLC_GATE_WITNESS_
# LIVE_BREAK, the value to export as SKILLC_GATE_SHIM_LIVE_BREAK, the value
# to export as SKILLC_COLDINSTALL_LIVE_BREAK, the value to export as
# SKILLC_TRIAL_IMAGE_BREAK, the value to export as SKILLC_CLOSURE_
# PREFLIGHT_LIVE_BREAK, the value to export as SKILLC_CWD_
# CONFINEMENT_LIVE_BREAK, the value to export as SKILLC_EGRESS_LIVE_BREAK,
# (#280) the value to export as SKILLC_CICD_PROFILE_LIVE_BREAK, and (#282)
# the value to export as SKILLC_CICD_DEPLOY_VERIFY_LIVE_BREAK
# - ALL TEN FAMILY VALUES ALWAYS PRESENT, exactly
# one of them equal to the resolved mode and the other nine the literal
# string "none" (never empty, never left for the caller to infer from an
# empty field).
#
# codex:code_review finding (HIGH, this file's own follow-up review): an
# earlier draft returned only the SELECTED family's env var name and
# value, so run-real-docker's invocation set just that one variable and
# left the OTHER family's variable exactly as inherited from the runner's
# own process environment - a `--break none` run with a stale
# SKILLC_LIVE_TEST_BREAK=omit-mount already in the environment (left over
# from a prior by-hand invocation, say) would silently run that break
# while posting to the CERTIFYING context, the exact failure this whole
# mechanism exists to prevent. Emitting an explicit value for every
# family, every time, makes "the non-selected families are always clean"
# true by construction rather than by a caller remembering to unset it.
#
# Prints a reason to STDERR and returns 2 for anything the closed table
# below does not name - an unknown family, an unknown mode inside a known
# family, or a bare spelling outside the three legacy channel modes
# (including every witness/gateshim/coldinstall/cwd mode, none of which has a
# bare form) - nothing is printed to stdout on refusal.
resolve_break_spec() {
    local spec="${1:-}" family mode m
    if [ "$spec" = "none" ]; then
        printf 'none\nnone\nnone\nnone\nnone\nnone\nnone\nnone\nnone\nnone\nnone\n'
        return 0
    fi
    case "$spec" in
        *:*)
            family="${spec%%:*}"
            mode="${spec#*:}"
            ;;
        *)
            family="channel"
            mode="$spec"
            ;;
    esac
    case "$family" in
        channel)
            for m in $_BREAK_CHANNEL_MODES; do
                if [ "$m" = "$mode" ]; then
                    printf 'channel:%s\n%s\nnone\nnone\nnone\nnone\nnone\nnone\nnone\nnone\nnone\n' "$mode" "$mode"
                    return 0
                fi
            done
            echo "run-real-docker: unknown channel break mode '$mode' (must be one of: $_BREAK_CHANNEL_MODES)" >&2
            return 2
            ;;
        witness)
            for m in $_BREAK_WITNESS_MODES; do
                if [ "$m" = "$mode" ]; then
                    printf 'witness:%s\nnone\n%s\nnone\nnone\nnone\nnone\nnone\nnone\nnone\nnone\n' "$mode" "$mode"
                    return 0
                fi
            done
            echo "run-real-docker: unknown witness break mode '$mode' (must be one of: $_BREAK_WITNESS_MODES)" >&2
            return 2
            ;;
        gateshim)
            for m in $_BREAK_GATESHIM_MODES; do
                if [ "$m" = "$mode" ]; then
                    printf 'gateshim:%s\nnone\nnone\n%s\nnone\nnone\nnone\nnone\nnone\nnone\nnone\n' "$mode" "$mode"
                    return 0
                fi
            done
            echo "run-real-docker: unknown gateshim break mode '$mode' (must be one of: $_BREAK_GATESHIM_MODES)" >&2
            return 2
            ;;
        coldinstall)
            for m in $_BREAK_COLDINSTALL_MODES; do
                if [ "$m" = "$mode" ]; then
                    printf 'coldinstall:%s\nnone\nnone\nnone\n%s\nnone\nnone\nnone\nnone\nnone\nnone\n' "$mode" "$mode"
                    return 0
                fi
            done
            echo "run-real-docker: unknown coldinstall break mode '$mode' (must be one of: $_BREAK_COLDINSTALL_MODES)" >&2
            return 2
            ;;
        trialimage)
            for m in $_BREAK_TRIALIMAGE_MODES; do
                if [ "$m" = "$mode" ]; then
                    printf 'trialimage:%s\nnone\nnone\nnone\nnone\n%s\nnone\nnone\nnone\nnone\nnone\n' "$mode" "$mode"
                    return 0
                fi
            done
            echo "run-real-docker: unknown trialimage break mode '$mode' (must be one of: $_BREAK_TRIALIMAGE_MODES)" >&2
            return 2
            ;;
        closure)
            for m in $_BREAK_CLOSURE_MODES; do
                if [ "$m" = "$mode" ]; then
                    printf 'closure:%s\nnone\nnone\nnone\nnone\nnone\n%s\nnone\nnone\nnone\nnone\n' "$mode" "$mode"
                    return 0
                fi
            done
            echo "run-real-docker: unknown closure break mode '$mode' (must be one of: $_BREAK_CLOSURE_MODES)" >&2
            return 2
            ;;
        cwd)
            for m in $_BREAK_CWD_MODES; do
                if [ "$m" = "$mode" ]; then
                    printf 'cwd:%s\nnone\nnone\nnone\nnone\nnone\nnone\n%s\nnone\nnone\nnone\n' "$mode" "$mode"
                    return 0
                fi
            done
            echo "run-real-docker: unknown cwd break mode '$mode' (must be one of: $_BREAK_CWD_MODES)" >&2
            return 2
            ;;
        egress)
            for m in $_BREAK_EGRESS_MODES; do
                if [ "$m" = "$mode" ]; then
                    printf 'egress:%s\nnone\nnone\nnone\nnone\nnone\nnone\nnone\n%s\nnone\nnone\n' "$mode" "$mode"
                    return 0
                fi
            done
            echo "run-real-docker: unknown egress break mode '$mode' (must be one of: $_BREAK_EGRESS_MODES)" >&2
            return 2
            ;;
        cicdprofile)
            for m in $_BREAK_CICDPROFILE_MODES; do
                if [ "$m" = "$mode" ]; then
                    printf 'cicdprofile:%s\nnone\nnone\nnone\nnone\nnone\nnone\nnone\nnone\n%s\nnone\n' "$mode" "$mode"
                    return 0
                fi
            done
            echo "run-real-docker: unknown cicdprofile break mode '$mode' (must be one of: $_BREAK_CICDPROFILE_MODES)" >&2
            return 2
            ;;
        cicdverify)
            for m in $_BREAK_CICDVERIFY_MODES; do
                if [ "$m" = "$mode" ]; then
                    printf 'cicdverify:%s\nnone\nnone\nnone\nnone\nnone\nnone\nnone\nnone\nnone\n%s\n' "$mode" "$mode"
                    return 0
                fi
            done
            echo "run-real-docker: unknown cicdverify break mode '$mode' (must be one of: $_BREAK_CICDVERIFY_MODES)" >&2
            return 2
            ;;
        *)
            echo "run-real-docker: unknown break family '$family' (must be 'channel', 'witness', 'gateshim', 'coldinstall', 'trialimage', 'closure', 'cwd', 'egress', 'cicdprofile' or 'cicdverify'), from spec '$spec'" >&2
            return 2
            ;;
    esac
}

# A break run - ANYTHING but the exact normalized string "none" - must
# NEVER resolve to the certifying context (skillc/real-docker); only
# skillc/real-docker-control, labelled expected-red by the caller. Pure
# function of resolve_break_spec's own normalized output, so this
# decision is made in exactly one place rather than independently at each
# of run-real-docker's two posting sites.
context_for_break_mode() {
    if [ "${1:-}" = "none" ]; then
        echo "skillc/real-docker"
    else
        echo "skillc/real-docker-control"
    fi
}
