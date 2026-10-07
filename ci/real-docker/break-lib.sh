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

# Resolves a --break argument to FOUR lines on stdout: the NORMALIZED spec
# ("none", or "<family>:<mode>" - a bare legacy channel mode is normalized
# to its "channel:<mode>" form here, so every caller downstream has exactly
# one spelling to compare against "none"), the value to export as
# SKILLC_LIVE_TEST_BREAK, the value to export as SKILLC_GATE_WITNESS_
# LIVE_BREAK, and the value to export as SKILLC_GATE_SHIM_LIVE_BREAK -
# ALWAYS ALL PRESENT, exactly one equal to the resolved mode and the other
# two the literal string "none" (never empty, never left for the caller to
# infer from an empty field).
#
# codex:code_review finding (HIGH, this file's own follow-up review): an
# earlier draft returned only the SELECTED family's env var name and
# value, so run-real-docker's invocation set just that one variable and
# left the OTHER family's variable exactly as inherited from the runner's
# own process environment - a `--break none` run with a stale
# SKILLC_LIVE_TEST_BREAK=omit-mount already in the environment (left over
# from a prior by-hand invocation, say) would silently run that break
# while posting to the CERTIFYING context, the exact failure this whole
# mechanism exists to prevent. Emitting an explicit value for BOTH
# families, every time, makes "the non-selected family is always clean"
# true by construction rather than by a caller remembering to unset it.
#
# Prints a reason to STDERR and returns 2 for anything the closed table
# below does not name - an unknown family, an unknown mode inside a known
# family, or a bare spelling outside the three legacy channel modes
# (including every witness mode, which has no bare form) - nothing is
# printed to stdout on refusal.
resolve_break_spec() {
    local spec="${1:-}" family mode m
    if [ "$spec" = "none" ]; then
        printf 'none\nnone\nnone\nnone\n'
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
                    printf 'channel:%s\n%s\nnone\nnone\n' "$mode" "$mode"
                    return 0
                fi
            done
            echo "run-real-docker: unknown channel break mode '$mode' (must be one of: $_BREAK_CHANNEL_MODES)" >&2
            return 2
            ;;
        witness)
            for m in $_BREAK_WITNESS_MODES; do
                if [ "$m" = "$mode" ]; then
                    printf 'witness:%s\nnone\n%s\nnone\n' "$mode" "$mode"
                    return 0
                fi
            done
            echo "run-real-docker: unknown witness break mode '$mode' (must be one of: $_BREAK_WITNESS_MODES)" >&2
            return 2
            ;;
        gateshim)
            for m in $_BREAK_GATESHIM_MODES; do
                if [ "$m" = "$mode" ]; then
                    printf 'gateshim:%s\nnone\nnone\n%s\n' "$mode" "$mode"
                    return 0
                fi
            done
            echo "run-real-docker: unknown gateshim break mode '$mode' (must be one of: $_BREAK_GATESHIM_MODES)" >&2
            return 2
            ;;
        *)
            echo "run-real-docker: unknown break family '$family' (must be 'channel', 'witness' or 'gateshim'), from spec '$spec'" >&2
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
