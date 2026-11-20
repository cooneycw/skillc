# shellcheck shell=sh
# shellcheck disable=SC2034  # verdict tokens are used by the sourcing probes
# Shared helpers for the run-window probes (#797 section 7). Sourced, never run.
#
# Every probe has two phases with one classifier between them:
#   observe  - LIVE mode only: touches the host, writes "ARM KEY VALUE" lines
#              to a readings file, and records ERR for any failed observation.
#   classify - pure: reads the readings file and prints one verdict per arm.
# `--classify FILE` runs only the classifier over committed fixture readings,
# so CI can qualify every verdict rule without root, Docker or a VM.
#
# Verdicts (exactly one per arm):
#   CONFIRMED_NEGATIVE  the observation succeeded and found nothing
#   SURVIVOR_OBSERVED   the observation succeeded and found a survivor
#   OBSERVATION_FAILED  the observation could not be made completely
# A missing, duplicated, empty or malformed reading is OBSERVATION_FAILED,
# never a zero. No error text is ever matched; only exit statuses and parsed
# numbers or fixed tokens decide.

PROBE_NEG=CONFIRMED_NEGATIVE
PROBE_SURV=SURVIVOR_OBSERVED
PROBE_FAIL=OBSERVATION_FAILED
PROBE_MISMATCH=0

probe_die() {
    printf 'PROBE %s REFUSED %s\n' "${PROBE_NAME:-unknown}" "$1"
    exit 2
}

# is_uint VALUE: true only for a nonempty string of ASCII digits.
is_uint() {
    case $1 in
        '' | *[!0-9]*) return 1 ;;
        *) return 0 ;;
    esac
}

# rd ARM KEY: print the single recorded value, or fail. Fails on a missing or
# duplicated key, and on the ERR marker an observe step writes for a failure.
rd() {
    awk -v a="$1" -v k="$2" '
        $1 == a && $2 == k { v = $3; n++ }
        END { if (n != 1 || v == "" || v == "ERR") exit 1; print v }
    ' "$PROBE_READINGS"
}

# rd_uint ARM KEY: rd, and also refuse anything that is not an unsigned integer.
rd_uint() {
    _v=$(rd "$1" "$2") || return 1
    is_uint "$_v" || return 1
    printf '%s\n' "$_v"
}

# record ARM KEY VALUE: append one reading (live mode only).
record() {
    printf '%s %s %s\n' "$1" "$2" "${3:-ERR}" >>"$PROBE_READINGS"
}

# arm NAME EXPECTED VERDICT: print the verdict and note a mismatch.
arm() {
    printf 'ARM %s %s\n' "$1" "$3"
    if [ "$3" != "$2" ]; then
        PROBE_MISMATCH=1
    fi
}

info() {
    printf 'INFO %s\n' "$*"
}

# finish: exit 0 when every arm gave its expected verdict, 1 otherwise.
finish() {
    if [ "$PROBE_MISMATCH" = 0 ]; then
        printf 'PROBE %s QUALIFIED\n' "$PROBE_NAME"
        exit 0
    fi
    printf 'PROBE %s MISMATCH\n' "$PROBE_NAME"
    exit 1
}

# parse_common "$@": sets PROBE_MODE (live|classify), PROBE_READINGS,
# PROBE_IMAGE_ID and PROBE_RUNNER_UNIT. Unknown flags refuse.
parse_common() {
    PROBE_MODE=live
    PROBE_READINGS=
    PROBE_IMAGE_ID=
    PROBE_RUNNER_UNIT=
    while [ "$#" -gt 0 ]; do
        case $1 in
            --classify)
                [ "$#" -ge 2 ] || probe_die 'usage'
                PROBE_MODE=classify
                PROBE_READINGS=$2
                shift 2
                ;;
            --image-id)
                [ "$#" -ge 2 ] || probe_die 'usage'
                PROBE_IMAGE_ID=$2
                shift 2
                ;;
            --runner-unit)
                [ "$#" -ge 2 ] || probe_die 'usage'
                PROBE_RUNNER_UNIT=$2
                shift 2
                ;;
            *) probe_die 'usage' ;;
        esac
    done
    if [ "$PROBE_MODE" = classify ]; then
        if [ ! -f "$PROBE_READINGS" ] || [ ! -r "$PROBE_READINGS" ]; then
            probe_die 'readings-unreadable'
        fi
    fi
}

# scratch_make PARENT: create a fresh private scratch directory, refusing reuse.
scratch_make() {
    [ -d "$1" ] || probe_die 'scratch-parent-missing'
    PROBE_SCRATCH="$1/skillc-dev-probe-$PROBE_NAME-$$"
    mkdir -m 0700 "$PROBE_SCRATCH" || probe_die 'scratch-exists'
    PROBE_READINGS="$PROBE_SCRATCH/readings"
    : >"$PROBE_READINGS"
}

# scratch_remove: remove the scratch directory and verify it is gone. A
# failed or unverified cleanup is reported and makes the run exit 2.
scratch_remove() {
    if [ -n "${PROBE_SCRATCH:-}" ] && [ -e "$PROBE_SCRATCH" ]; then
        rm -rf -- "$PROBE_SCRATCH" || true
        if [ -e "$PROBE_SCRATCH" ]; then
            printf 'PROBE %s CLEANUP-FAILED\n' "$PROBE_NAME"
            exit 2
        fi
    fi
}

# require_root: the probe's arms need root; refuse rather than run blind.
require_root() {
    [ "$(id -u)" = 0 ] || probe_die 'root-required'
}

# require_image: validate --image-id and confirm the daemon holds exactly it.
require_image() {
    printf '%s\n' "$PROBE_IMAGE_ID" | grep -Eq '^sha256:[0-9a-f]{64}$' || probe_die 'image-id-invalid'
    _id=$(docker image inspect --format '{{.Id}}' "$PROBE_IMAGE_ID") || probe_die 'image-absent'
    [ "$_id" = "$PROBE_IMAGE_ID" ] || probe_die 'image-id-mismatch'
}

# require_runner_idle: Docker probes never overlap a runner job. The unit name
# is supplied by the operator; its ActiveState must be exactly inactive or failed.
require_runner_idle() {
    [ -n "$PROBE_RUNNER_UNIT" ] || probe_die 'runner-unit-required'
    _state=$(systemctl show -p ActiveState --value -- "$PROBE_RUNNER_UNIT") || probe_die 'runner-state-unreadable'
    case $_state in
        inactive | failed) ;;
        *) probe_die 'runner-active' ;;
    esac
}

# require_overlay2: P5 and P6 read the overlay upper directory.
require_overlay2() {
    _driver=$(docker info --format '{{.Driver}}') || probe_die 'driver-unreadable'
    [ "$_driver" = overlay2 ] || probe_die 'driver-not-overlay2'
}
