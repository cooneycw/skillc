#!/bin/sh
# P4 (#797 precondition 1.2.3): persistence controls. Read-only and
# unprivileged. No Docker. The conclusion is limited to the observed swap,
# core-handler and resume configuration.
#
# The `live` arm reads the runner VM itself, and its verdict IS the finding:
# CONFIRMED_NEGATIVE means no swap device, a non-piped core_pattern and no
# resume device, so a window may open. A survivor there blocks a window; it
# is not a probe error. The other arms run the same readers over planted
# copies in the scratch directory, so the readers are shown to discriminate.
#
# Arms and expected verdicts:
#   live    the VM's own state                    CONFIRMED_NEGATIVE (finding)
#   swap    a planted swaps table with one device SURVIVOR_OBSERVED
#   pipe    a planted piped core_pattern          SURVIVOR_OBSERVED
#   fault   readers pointed at empty or dangling
#           inputs                                OBSERVATION_FAILED
set -eu
PROBE_NAME=p4
# shellcheck source=SCRIPTDIR/lib.sh
. "${PROBE_LIB:-$(dirname -- "$0")/lib.sh}"
parse_common "$@"

# swap_devices FILE: count device rows of a /proc/swaps-shaped table. The
# header must start with the kernel's fixed column name and every row must
# have five fields; anything else fails.
swap_devices() {
    awk '
        NR == 1 {
            if (NF != 5 || $1 != "Filename" || $2 != "Type" || $3 != "Size" ||
                $4 != "Used" || $5 != "Priority") bad = 1
            next
        }
        NF == 0 { next }
        NF != 5 { bad = 1 }
        { c++ }
        END { if (NR < 1 || bad) exit 1; print c + 0 }
    ' "$1"
}

# read_state ARM SWAPS CORE_PATTERN POWER_DIR: record swap_devices,
# core_piped and resume_set, each a number or ERR.
read_state() {
    if [ -r "$2" ] && s=$(swap_devices "$2" 2>/dev/null); then
        record "$1" swap_devices "$s"
    else
        record "$1" swap_devices ERR
    fi
    # core_pattern must be exactly one nonempty line.
    nl='
'
    if [ -r "$3" ] && n=$(wc -l <"$3" 2>/dev/null) && [ "$n" -eq 1 ] \
        && v=$(cat -- "$3" 2>/dev/null) && [ -n "$v" ]; then
        case $v in
            *"$nl"*) record "$1" core_piped ERR ;;
            '|'*) record "$1" core_piped 1 ;;
            *) record "$1" core_piped 0 ;;
        esac
    else
        record "$1" core_piped ERR
    fi
    # Hibernation needs a resume device. The power interface directory must be
    # visible; inside it, a missing `resume` means the kernel cannot resume
    # (none), and a present one must read exactly major:minor.
    if [ ! -d "$4" ] || [ ! -r "$4/state" ]; then
        record "$1" resume_set ERR
    elif [ ! -e "$4/resume" ] && [ ! -L "$4/resume" ]; then
        record "$1" resume_set 0
    elif n=$(wc -l <"$4/resume" 2>/dev/null) && [ "$n" -eq 1 ] \
        && r=$(cat -- "$4/resume" 2>/dev/null) && printf '%s\n' "$r" | grep -Eq '^[0-9]+:[0-9]+$'; then
        if [ "$r" = 0:0 ]; then record "$1" resume_set 0; else record "$1" resume_set 1; fi
    else
        record "$1" resume_set ERR
    fi
}

observe() {
    scratch_make "${PROBE_TMPFS:-/dev/shm}"
    read_state live /proc/swaps /proc/sys/kernel/core_pattern /sys/power
    d=$PROBE_SCRATCH
    header='Filename                                Type            Size            Used            Priority'
    printf '%s\n' "$header" >"$d/swaps-none"
    printf '%s\n/swapfile file 1048572 0 -2\n' "$header" >"$d/swaps-one"
    printf 'core\n' >"$d/core-file"
    printf '|/usr/lib/handler %%p\n' >"$d/core-pipe"
    mkdir -p "$d/power"
    printf 'freeze mem\n' >"$d/power/state"
    printf '0:0\n' >"$d/power/resume"
    read_state swap "$d/swaps-one" "$d/core-file" "$d/power"
    read_state pipe "$d/swaps-none" "$d/core-pipe" "$d/power"
    : >"$d/empty"
    ln -s "$d/absent-target" "$d/dangling"
    read_state fault "$d/empty" "$d/dangling" "$d/absent-power"
}

verdict() {
    s=$(rd_uint "$1" swap_devices) || { printf '%s\n' "$PROBE_FAIL"; return; }
    c=$(rd_bool "$1" core_piped) || { printf '%s\n' "$PROBE_FAIL"; return; }
    r=$(rd_bool "$1" resume_set) || { printf '%s\n' "$PROBE_FAIL"; return; }
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
