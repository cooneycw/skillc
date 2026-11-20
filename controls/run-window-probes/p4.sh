#!/bin/sh
# P4 (#797 precondition 1.2.3): persistence controls. Read-only and
# unprivileged. No Docker.
#
# The `live` arm reads the runner VM itself, and its verdict IS the finding:
# CONFIRMED_NEGATIVE means swap off, no piped core handler and hibernation not
# enterable, so a window may open. Any survivor there blocks a window; it is
# not a probe error. The other arms run the same readers over planted copies
# in the scratch directory, so the readers are shown to discriminate.
#
# Arms and expected verdicts:
#   live       the VM's own state                     CONFIRMED_NEGATIVE (finding)
#   swap       a planted /proc/swaps with one device  SURVIVOR_OBSERVED
#   pipe       a planted piped core_pattern           SURVIVOR_OBSERVED
#   fault      readers pointed at dangling links      OBSERVATION_FAILED
set -eu
PROBE_NAME=p4
# shellcheck source=SCRIPTDIR/lib.sh
. "${PROBE_LIB:-$(dirname -- "$0")/lib.sh}"
parse_common "$@"

# read_state ARM SWAPS CORE_PATTERN RESUME: record the three facts or ERR.
read_state() {
    if s=$(awk 'NR > 1 && NF > 0 { c++ } END { print c + 0 }' "$2" 2>/dev/null) && [ -r "$2" ]; then
        record "$1" swap_devices "$s"
    else
        record "$1" swap_devices ERR
    fi
    if c=$(head -c 1 -- "$3" 2>/dev/null) && [ -r "$3" ]; then
        if [ "$c" = '|' ]; then record "$1" core_piped 1; else record "$1" core_piped 0; fi
    else
        record "$1" core_piped ERR
    fi
    # Hibernation needs a resume device: 0:0 means none. A kernel built
    # without hibernation has no such file at all, which also means none; a
    # path that exists (or dangles) but cannot be read is a failed observation.
    if [ ! -e "$4" ] && [ ! -L "$4" ]; then
        record "$1" resume_set 0
    elif r=$(cat -- "$4" 2>/dev/null) && [ -n "$r" ]; then
        if [ "$r" = 0:0 ]; then record "$1" resume_set 0; else record "$1" resume_set 1; fi
    else
        record "$1" resume_set ERR
    fi
}

observe() {
    scratch_make "${PROBE_TMPFS:-/dev/shm}"
    trap scratch_remove EXIT
    read_state live /proc/swaps /proc/sys/kernel/core_pattern /sys/power/resume
    d=$PROBE_SCRATCH
    printf 'Filename Type Size Used Priority\n' >"$d/swaps-none"
    printf 'Filename Type Size Used Priority\n/swapfile file 1024 0 -2\n' >"$d/swaps-one"
    printf 'core\n' >"$d/core-file"
    printf '|/usr/lib/handler %%p\n' >"$d/core-pipe"
    printf '0:0\n' >"$d/resume-none"
    read_state swap "$d/swaps-one" "$d/core-file" "$d/resume-none"
    read_state pipe "$d/swaps-none" "$d/core-pipe" "$d/resume-none"
    for f in swaps core resume; do ln -s "$d/absent-$f-target" "$d/dangling-$f"; done
    read_state fault "$d/dangling-swaps" "$d/dangling-core" "$d/dangling-resume"
}

verdict() {
    s=$(rd_uint "$1" swap_devices) || { printf '%s\n' "$PROBE_FAIL"; return; }
    c=$(rd_uint "$1" core_piped) || { printf '%s\n' "$PROBE_FAIL"; return; }
    r=$(rd_uint "$1" resume_set) || { printf '%s\n' "$PROBE_FAIL"; return; }
    if [ "$s" -eq 0 ] && [ "$c" -eq 0 ] && [ "$r" -eq 0 ]; then
        printf '%s\n' "$PROBE_NEG"
    else
        printf '%s\n' "$PROBE_SURV"
    fi
}

classify() {
    arm live "$PROBE_NEG" "$(verdict live)"
    arm swap "$PROBE_SURV" "$(verdict swap)"
    arm pipe "$PROBE_SURV" "$(verdict pipe)"
    arm fault "$PROBE_FAIL" "$(verdict fault)"
    finish
}

if [ "$PROBE_MODE" = live ]; then observe; fi
classify
