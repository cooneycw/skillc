"""#287 acceptance item 1: computed (not quoted/approximated) one-sided
Fisher's exact power limits, and the worst-case attempt count and measured-mean token totals for
the two separate 2-arm pilot declarations (discrimination: intact vs degraded;
improvement: cpp vs baseline), at n per arm in {10, 15, 20, 30}.

THE QUESTION THIS ANSWERS. For a fixed n per arm, if the better arm (intact,
or CPP) passes every attempt (n/n - the most favorable observable outcome),
what is the largest number of passes the worse arm (degraded, or baseline)
can show and STILL let a one-sided Fisher's exact test reach p < 0.05? Worse-
arm counts AT OR BELOW that cutoff reach significance (fewer passes only
strengthen it); counts ABOVE it cannot, even with the better arm at ceiling.
At n=10 the cutoff is 6: 10/10 vs 6/10 gives p = 0.043, 10/10 vs 7/10 gives
p = 0.105. This is the number #287's acceptance item 1 ("size repeats from
measured costs and the declared uncertainty target, not an invented large
matrix") needs before any n is chosen, and it has to be computed, not read
off a table, because this specific 2x2 shape (one margin pinned at its
ceiling) is not what most Fisher's-exact tables are built for.

THE DERIVATION. Fix n attempts per arm. Build the 2x2 table with the better
arm's pass count pinned at its maximum, n (its fail count is then 0):

              pass    fail    row total
    better     n       0          n
    worse      k      n-k         n
    -------------------------------
    total     n+k    n-k         2n

With both margins fixed (row totals n and n; column totals n+k and n-k), the
better arm's pass count A follows Hypergeometric(population=2n,
successes=n+k, draws=n). The one-sided p-value for "better did at least this
well relative to worse" is P(A >= n). Because a row total of n is also A's
hard ceiling, P(A >= n) = P(A = n) exactly - there is only one term, not a
sum, which is what makes this closed-form rather than a tail sum:

    p(k) = C(n+k, n) * C(n-k, 0) / C(2n, n) = C(n+k, n) / C(2n, n)

(`C(n-k, 0) = 1` whenever `0 <= k <= n`, which always holds here.) p(k) is
non-decreasing in k by construction - a worse arm closer to the better arm's
score makes the table less extreme - so the search below is a plain forward
scan from k=0, stopping at the first k where p(k) >= 0.05; the reported
`max_lower_pass_for_p_lt_0.05` is the entry just before that.

Stdlib only (AGENTS.md): `math.comb` is exact (arbitrary-precision integer
arithmetic), so this is a computed figure, not a floating-point
approximation, let alone a quoted one.
"""

from __future__ import annotations

import json
import math
import re
import statistics
from pathlib import Path

ALPHA = 0.05
N_PER_ARM = (10, 15, 20, 30)

#: MEASURED per-attempt token input (orchestrator ruling 2026-10-17: cite
#: measured inputs; mark UNKNOWN rather than estimate). Source: #237's
#: uptake-study run, `evals/uptake-study/report.md` results table (codex-cli
#: 0.157.1, gpt-6-astra, effort high; 60 confirmed attempts). Only per-cell
#: means are committed (each rounded, "~NNNk"), so the per-attempt mean is
#: the attempt-weighted mean of those cells, computed below. The LARGEST CELL
#: MEAN is carried as a scenario, NOT an upper bound: a cell averaging 175k can
#: contain larger attempts. A true per-attempt upper bound is UNKNOWN (no
#: measured maxima are committed and no token limit is enforced). CAVEAT: #237 ran the level-1 slug-small-fix task, not
#: gate-stops-early; it is the nearest measured figure for this client,
#: model and effort, cited as exactly that.
MEASURED_TOKEN_CELLS: tuple[tuple[str, int, int], ...] = (
    # (case/arm, attempts, mean tokens per attempt)
    ("intended-use/published", 20, 175_000),
    ("intended-use/rewritten", 20, 137_000),
    ("near-miss/published", 10, 103_000),
    ("near-miss/rewritten", 10, 116_000),
)
MEASURED_TOKEN_SOURCE = "evals/uptake-study/report.md results table (#237, run 2026-10-04, 60 attempts)"
MEASURED_MEAN_TOKENS_PER_ATTEMPT = round(
    sum(n * mean for _c, n, mean in MEASURED_TOKEN_CELLS) / sum(n for _c, n, _m in MEASURED_TOKEN_CELLS))
LARGEST_CELL_MEAN_TOKENS_PER_ATTEMPT = max(mean for _c, _n, mean in MEASURED_TOKEN_CELLS)

#: Per-attempt wall time, MEASURED but SCRIPTED: #375's pre-registered final
#: run (42 rows, scripted actors, no model; issuecomment-6240849747), extracted
#: to `evidence/l375-final-scripted-timings.txt`. It measures the container,
#: gate and grading path on these exact Level-3 tasks, not a live agent's
#: thinking time, so a LIVE per-attempt wall time stays UNKNOWN.
SCRIPTED_TIMINGS_FILE = Path(__file__).with_name("evidence") / "l375-final-scripted-timings.txt"


def scripted_timings(path: Path = SCRIPTED_TIMINGS_FILE) -> list[float]:
    """Seconds per row, from the committed extract ('... NN.Ns)' per line)."""
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.search(r", ([0-9]+(?:\.[0-9]+)?)s\)$", line)
        if m and not line.startswith("#"):
            out.append(float(m.group(1)))
    return out


_T = scripted_timings()
SCRIPTED_SECONDS = {"rows": len(_T), "min": min(_T), "median": round(statistics.median(_T), 2),
                    "mean": round(statistics.mean(_T), 1), "max": max(_T)}
WALL_SECONDS_PER_ATTEMPT: float | None = None  # LIVE: UNKNOWN
WALL_SECONDS_SOURCE = ("LIVE: UNKNOWN; SCRIPTED (#375 final run, evidence/l375-final-scripted-timings.txt): "
                       f"{SCRIPTED_SECONDS['rows']} rows, min {SCRIPTED_SECONDS['min']}s, median "
                       f"{SCRIPTED_SECONDS['median']}s, max {SCRIPTED_SECONDS['max']}s")

#: No dollar figure: the cost cap is superseded (owner, #287 comment
#: 6021089903: size for power, report tokens for transparency), and no
#: measured price exists for the pinned model.

#: Two SEPARATE 2-arm pilot declarations (decision P2, comment 6025311708):
#: discrimination (intact vs degraded) and improvement (cpp vs baseline).
#: Never pooled (P1), so each declaration runs its own arms in full.
DECLARATIONS = 2
ARMS_PER_DECLARATION = 2


def max_lower_pass_for_alpha(n: int, alpha: float = ALPHA) -> tuple[int, float]:
    """The largest k in [0, n] with p(k) < alpha, and that p(k). p is
    non-decreasing in k (more lower-arm passes = a less extreme table), so a
    forward scan from k=0 finds the breakpoint in O(n) exact-integer steps."""
    denom = math.comb(2 * n, n)
    best_k, best_p = -1, 1.0
    for k in range(n + 1):
        p = math.comb(n + k, n) / denom
        if p < alpha:
            best_k, best_p = k, p
        else:
            break
    if best_k < 0:
        raise AssertionError(f"n={n}: even k=0 fails to reach p<{alpha} - the table is unusable at this n")
    return best_k, best_p


def total_tokens(total_attempts: int, per_attempt: int) -> int:
    """Tokens for `total_attempts` at a measured per-attempt figure; a
    plain product, so a reader can re-check it by hand."""
    return total_attempts * per_attempt


def build_table() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for n in N_PER_ARM:
        k, p = max_lower_pass_for_alpha(n)
        # Worst case: EVERY arm of BOTH declarations runs its full n attempts
        # (no early stop pays off in the estimate - #287 acceptance item 2
        # forbids "do not rerun until the desired result appears", so the
        # estimate must not assume a favorable early stop either).
        total_attempts = DECLARATIONS * ARMS_PER_DECLARATION * n
        # k < n always (k=n means both arms perfect, p=1): k+1 <= n is safe.
        p_next = math.comb(n + k + 1, n) / math.comb(2 * n, n)
        rows.append(
            {
                "n_per_arm": n,
                "better_arm_passes": n,
                "max_worse_arm_passes_below_p05": k,
                "p_at_max_worse_arm_passes": p,
                "p_at_next_worse_arm_pass": p_next,
                "total_attempts_both_declarations": total_attempts,
                "tokens_at_measured_mean": total_tokens(total_attempts, MEASURED_MEAN_TOKENS_PER_ATTEMPT),
                "tokens_at_largest_cell_mean": total_tokens(total_attempts, LARGEST_CELL_MEAN_TOKENS_PER_ATTEMPT),
                "wall_seconds": "UNKNOWN" if WALL_SECONDS_PER_ATTEMPT is None
                else total_attempts * WALL_SECONDS_PER_ATTEMPT,
                "scripted_floor_seconds_at_median": round(total_attempts * SCRIPTED_SECONDS["median"]),
            }
        )
    return rows


def main() -> None:
    rows = build_table()
    print(f"measured tokens/attempt: mean {MEASURED_MEAN_TOKENS_PER_ATTEMPT}, largest-cell-mean scenario {LARGEST_CELL_MEAN_TOKENS_PER_ATTEMPT}, true upper bound UNKNOWN "
          f"({MEASURED_TOKEN_SOURCE}); wall time: {WALL_SECONDS_SOURCE}")
    print(f"{'n/arm':>6} {'best-case gap (n vs k)':>24} {'p(k)':>12} {'p(k+1)':>12} {'attempts':>9} "
          f"{'tokens@mean':>13} {'tokens@largest-cell-mean':>25}")
    for row in rows:
        gap = f"{row['better_arm_passes']}/{row['n_per_arm']} vs {row['max_worse_arm_passes_below_p05']}/{row['n_per_arm']}"
        print(
            f"{row['n_per_arm']:>6} {gap:>24} {row['p_at_max_worse_arm_passes']:>12.6f} "
            f"{row['p_at_next_worse_arm_pass']:>12.6f} {row['total_attempts_both_declarations']:>9} "
            f"{row['tokens_at_measured_mean']:>13} {row['tokens_at_largest_cell_mean']:>25}"
        )

    out = {
        "_comment": (
            "Computed by evals/calibration-287/power_cost_table.py (run it to reproduce - "
            "math.comb is exact integer arithmetic, no approximation). alpha=0.05, one-sided "
            "Fisher's exact, better arm pinned at n/n (the most favorable observable outcome). "
            "Token inputs are MEASURED and cited. Live wall time is UNKNOWN; #375's final run gives "
            "SCRIPTED per-attempt seconds on these tasks, a floor that excludes model time. No "
            "dollar figure (cost cap superseded, #287 comment 6021089903)."
        ),
        "alpha": ALPHA,
        "measured_token_cells": [list(c) for c in MEASURED_TOKEN_CELLS],
        "measured_token_source": MEASURED_TOKEN_SOURCE,
        "measured_mean_tokens_per_attempt": MEASURED_MEAN_TOKENS_PER_ATTEMPT,
        "largest_cell_mean_tokens_per_attempt": LARGEST_CELL_MEAN_TOKENS_PER_ATTEMPT,
        "upper_bound_tokens_per_attempt": "UNKNOWN",
        "wall_seconds_per_attempt": "UNKNOWN" if WALL_SECONDS_PER_ATTEMPT is None else WALL_SECONDS_PER_ATTEMPT,
        "wall_seconds_source": WALL_SECONDS_SOURCE,
        "scripted_seconds_per_attempt": SCRIPTED_SECONDS,
        "declarations": DECLARATIONS,
        "arms_per_declaration": ARMS_PER_DECLARATION,
        "rows": rows,
    }
    out_path = Path(__file__).with_name("power_cost_table.json")
    out_path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
