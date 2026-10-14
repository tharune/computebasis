# Conditional finite threshold-ladder diagnostics

The [pure module](../src/compute_pricing/control/market_diagnostics/ladder.py) checks a finite set of caller-supplied, normalized binary-claim quote bounds. It has no feed adapter, API route, data extractor, venue integration or execution path. Its output cannot enter compute-price benchmarking. The [independent invented tests](../tests/test_market_diagnostics.py) exercise feasible and impossible envelopes, missing sides, unknown tails, equality, mismatched terms, stale/future evidence, exact arithmetic and bounded output.

A quote on a contingent payout is a different object from a compute rental rate. Even an option-implied risk-neutral distribution differs from a real-world outcome forecast when risk preferences affect prices; transforming one into the other requires additional evidence and modeling. This distinction is discussed in [Bank of England Working Paper 455](https://www.bankofengland.co.uk/-/media/boe/files/working-paper/2012/estimating-probability-distributions-of-future-asset-prices-emperical-transformations.pdf). This module implements no such transformation and makes no empirical claim about a market or provider.

## Explicit input contract

Call `evaluate_threshold_ladder(payload)` with these fields:

- `schema_version`: `conditional-threshold-ladder/1.0`.
- `as_of`: explicit UTC instant ending in `Z`.
- `survival_level`: exact decimal string strictly between zero and one; there is no default median level.
- `common_terms`: `terms_id`, `underlying_id`, `settlement_id`, `issuer_id`, `threshold_unit`, `comparison`, `bound_basis`, `alignment_evidence_id`.
- `quotes`: at most 256 records, each containing `quote_id`, the same six alignment fields through `comparison`, `normalization_evidence_id`, `threshold`, `bid_bound`, `ask_bound`, `observed_at`, `expires_at`.

`comparison` must be `strict_gt`. `bound_basis` must explicitly declare `conditional_common_pricing_measure`. Thresholds are signed exact decimal strings in the declared underlying unit. The bounds are dimensionless exact decimal strings in `[0,1]`, already normalized by an independently specified method to a common unit payout and pricing measure. The module does not divide a raw contract price by a payout, choose a discount factor, remove fees, infer credit equivalence or establish that these normalized values are valid probability bounds.

Missing bid/ask sides must be `null`; explicit zero is retained. Missing alignment or normalization evidence, mismatched underlying/settlement/issuer/unit/comparison, future observations or expiry at/before the assessment instant hold all arithmetic. Caller-provided evidence IDs and expiry dates remain claims, not independent verification. Unknown fields, float/Boolean monetary-like numbers, nonfinite/scientific notation, duplicate quote IDs or numerically duplicate thresholds fail validation with safe codes. Empty or wholly unquoted ladders are held.

## Feasibility under the declared hypothesis

Let `S(K) = Q(X > K)` under the assumed common pricing measure. This survival function cannot increase as the threshold increases. For ordered observed thresholds `K_1 < ... < K_n`, interpret each provided normalized bid/ask as a hypothesized lower/upper bound. The exact propagated bounds are:

```text
L_i = max(0, all supplied bid bounds at thresholds K_j >= K_i)
U_i = min(1, all supplied ask bounds at thresholds K_j <= K_i)
```

Zero and one here are universal probability-domain constraints. They are not invented quotes. Outputs preserve each missing side as `null`, identify the quote witnessing a propagated bound, and distinguish a universal-only bound from a supplied quote.

The finite envelope is feasible only if `L_i <= U_i` at every observed node. Any impossible intersection holds level identification; the module does not repair it through midpoint interpolation or isotonic fitting. All lower/higher threshold pairs are checked, including nonadjacent pairs and same-threshold bid/ask crossings. If a higher-threshold bid exceeds a lower-threshold ask, the output records their exact normalized gross gap and quote IDs. At most 32 violation records are returned, with the full count and explicit truncation flag.

These inequalities diagnose inconsistency under aligned-payoff and common-measure assumptions. They are not executable arbitrage evidence: current depth, synchronized execution, shorting rights, fees, funding, collateral, settlement and issuer risk remain unevaluated. `no_arbitrage_certificate` and `execution_eligible` are always false, including for a feasible ladder.

## Observed-threshold level identification

The requested cut has a precise definition:

```text
q = inf{x : S(x) <= survival_level}
```

For any observed `K_i`, `L_i > level` establishes `q > K_i`; `U_i <= level` establishes `q <= K_i`. Therefore the output uses the largest established lower threshold and the smallest established upper threshold. A finite lower endpoint is open and a finite upper endpoint is closed. Equality does not establish a lower bound.

Only observed thresholds determine this conservative bracket. Missing endpoints remain `null` with explicit lower/upper unbounded-tail flags. Width is returned only when both endpoints are finite. The module provides no point estimate between thresholds, no midpoint/median forecast, no unobserved-tail completion and no expected underlying value. A finite bracket describes the assumed pricing measure, not a real-world quantile or calibrated confidence interval.

## Output and validation

Outputs include schema/model versions, assessment instant, declared unit/basis/evidence, quote count, conditional feasibility, envelopes, gross dominance diagnostics, blockers and level identification. All derived numbers are exact decimal strings and calculations use local precision sufficient for the bounded inputs, independent of the caller's Decimal context. The result is detached from input objects.

`conditional_feasible` means only that the declared finite inequalities can coexist. `compute_price_eligible`, `execution_eligible` and `no_arbitrage_certificate` remain false; `expected_underlying_value` remains null. No rights, normalization qualification, calibration or instrument activation follows from this result.

Run the focused offline tests with:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest discover -s tests -p test_market_diagnostics.py -v
```
