"""#287 acceptance item 1: computed (not quoted/approximated) one-sided
Fisher's exact power limits, and the worst-case quota-equivalent cost for
the 3 shared arms (baseline, intact/CPP, degraded), at n per arm in
{10, 15, 20, 30}.

THE QUESTION THIS ANSWERS. For a fixed n per arm, if the better arm (intact,
or CPP) passes every attempt (n/n - the most favorable observable outcome),
what is the largest number of passes the worse arm (degraded, or baseline)
can show and STILL let a one-sided Fisher's exact test reach p < 0.05? Below
that count, the design cannot show significance even in the best case the
data could hand it; above it, n is wasted margin. This is the number #287's
acceptance item 1 ("size repeats from measured costs and the declared
uncertainty target, not an invented large matrix") needs before any n is
chosen, and it has to be computed, not read off a table, because this
specific 2x2 shape (one margin pinned at its ceiling) is not what most
Fisher's-exact tables are built for.

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
from pathlib import Path

ALPHA = 0.05
N_PER_ARM = (10, 15, 20, 30)

#: Reused verbatim from evals/selection-probe/run-manifest.json and
#: evals/matched-pilot/run-manifest.json's `cost_estimate.price` (both #26
#: and the matched pilot cite the SAME source) - not independently
#: re-verified here, kept identical so a reader comparing the three
#: documents sees one price, not three unexplained near-duplicates.
PRICE: dict[str, str | float] = {
    "name": "gpt-5.1-codex",
    "input_usd_per_million": 1.25,
    "output_usd_per_million": 10.00,
    "source": "pricepertoken.com, 2026-09-26 (third-party aggregator, not independently confirmed against OpenAI's own page) - the same price #26 and the matched pilot use",
}
PRICE_INPUT_USD_PER_MILLION: float = float(PRICE["input_usd_per_million"])
PRICE_OUTPUT_USD_PER_MILLION: float = float(PRICE["output_usd_per_million"])

#: The orchestrator's assigned token assumption for this table (~140k/attempt),
#: NOT the #26/matched-pilot figure (50k in + 5k out = 55k) - #287's task is
#: unknown pending #270/#271, so this is a stated planning assumption, split
#: input-heavy on the same reasoning #26 already gave for why input dominates
#: in a multi-turn agentic session (system prompt + skill surface + goal
#: re-sent every turn): 125k input + 15k output = 140k total.
ASSUMED_INPUT_TOKENS_PER_ATTEMPT = 125_000
ASSUMED_OUTPUT_TOKENS_PER_ATTEMPT = 15_000
ASSUMED_TOTAL_TOKENS_PER_ATTEMPT = ASSUMED_INPUT_TOKENS_PER_ATTEMPT + ASSUMED_OUTPUT_TOKENS_PER_ATTEMPT

#: baseline, intact/CPP, degraded (#287's acceptance scope: discrimination
#: test is intact-vs-degraded, improvement test is intact/CPP-vs-baseline;
#: all three arms share attempts rather than needing a fourth).
SHARED_ARMS = 3


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


def quota_equivalent_usd(total_attempts: int) -> float:
    """Same formula as `skillc.cost_estimate.estimate` (not imported, to
    keep this script a standalone, re-checkable artifact alongside the
    manifest): tokens priced at `PRICE`, reported as a QUOTA-equivalent
    figure per ADR 0005 rule 6, never a dollar charge - agent attempts run
    under the operator's subscription login; see the README for the gate
    this figure is NOT compared against."""
    input_cost = total_attempts * ASSUMED_INPUT_TOKENS_PER_ATTEMPT / 1_000_000 * PRICE_INPUT_USD_PER_MILLION
    output_cost = total_attempts * ASSUMED_OUTPUT_TOKENS_PER_ATTEMPT / 1_000_000 * PRICE_OUTPUT_USD_PER_MILLION
    return input_cost + output_cost


def build_table() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for n in N_PER_ARM:
        k, p = max_lower_pass_for_alpha(n)
        # Worst case: EVERY shared arm runs its full n attempts (no early
        # stop pays off in the estimate - #287 acceptance item 2 forbids
        # "do not rerun until the desired result appears", so the estimate
        # must not assume a favorable early stop either).
        total_attempts = SHARED_ARMS * n
        # k < n always (k=n means both arms perfect, p=1): k+1 <= n is safe.
        p_next = math.comb(n + k + 1, n) / math.comb(2 * n, n)
        rows.append(
            {
                "n_per_arm": n,
                "better_arm_passes": n,
                "max_worse_arm_passes_below_p05": k,
                "p_at_max_worse_arm_passes": p,
                "p_at_next_worse_arm_pass": p_next,
                "total_attempts_3_shared_arms": total_attempts,
                "worst_case_quota_equivalent_usd": round(quota_equivalent_usd(total_attempts), 4),
            }
        )
    return rows


def main() -> None:
    rows = build_table()
    print(f"{'n/arm':>6} {'best-case gap (n vs k)':>24} {'p(k)':>12} {'p(k+1)':>12} {'attempts (3 arms)':>18} {'quota-equiv $':>14}")
    for row in rows:
        gap = f"{row['better_arm_passes']}/{row['n_per_arm']} vs {row['max_worse_arm_passes_below_p05']}/{row['n_per_arm']}"
        print(
            f"{row['n_per_arm']:>6} {gap:>24} {row['p_at_max_worse_arm_passes']:>12.6f} "
            f"{row['p_at_next_worse_arm_pass']:>12.6f} {row['total_attempts_3_shared_arms']:>18} "
            f"{row['worst_case_quota_equivalent_usd']:>14.2f}"
        )

    out = {
        "_comment": (
            "Computed by evals/calibration-287/power_cost_table.py (run it to reproduce - "
            "math.comb is exact integer arithmetic, no approximation). alpha=0.05, one-sided "
            "Fisher's exact, better arm pinned at n/n (the most favorable observable outcome). "
            "quota-equivalent costs are NOT dollar charges (ADR 0005 rule 6) - see README.md."
        ),
        "alpha": ALPHA,
        "price": PRICE,
        "assumed_input_tokens_per_attempt": ASSUMED_INPUT_TOKENS_PER_ATTEMPT,
        "assumed_output_tokens_per_attempt": ASSUMED_OUTPUT_TOKENS_PER_ATTEMPT,
        "assumed_total_tokens_per_attempt": ASSUMED_TOTAL_TOKENS_PER_ATTEMPT,
        "shared_arms": SHARED_ARMS,
        "rows": rows,
    }
    out_path = Path(__file__).with_name("power_cost_table.json")
    out_path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
