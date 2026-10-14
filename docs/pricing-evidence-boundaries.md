# Pricing evidence and cash-risk boundaries

Compute Pricing separates hypothetical arithmetic from qualified source evidence. The pure inverse-pricing kernel can analyze explicit invented or manually supplied assumptions. An authenticated API request additionally binds retained source observations to the current saved policy. Neither inline rights nor benchmark weights grant source permissions. Firm pricing and execution remain disabled.

## Required caps and monetary ticks

A usable purchase bid requires economic-margin and market caps, a complete fundable cash path and no other pricing hold. Held calculations keep economic/cost/cap diagnostics but return `bid: null`.

Cash inversion searches only up to the other caps on the supplied tick grid. A feasible search ceiling is a censored test, not an independently identified liquidity maximum. It returns `maximum_purchase_tick: null`, `limit_censored_by_search_ceiling: true` and the actual `tested_purchase_tick`. A slack test does not add `daily_liquidity` or claim liquidity binds. The raw reservation retains the fractional minimum of required and explicit optional caps; only the final buy submission rounds downward. Cash feasibility above the tested grid remains unknown.

If the ceiling fails, the monotone complete-ledger search finds the highest feasible purchase tick and reports that discrete liquidity cap. Sell floors remain based on the supplied supplier ask. Optional stress caps are caller decisions. The compatible method is `inverse-linear/1.0.0`, with separately recorded implementation `purchase-cap-censoring/1.0.1` and cash search `full-ledger-monotone-tick/1.0.1`.

## Retained-market request contract

`pricing_provenance` is a top-level object with exactly `mode` and `policy_revision`.

- A declared scenario uses `{"mode":"declared_scenario","policy_revision":null}`. An omitted object is also unbound. API output is visibly held, its bid and ordinary benchmark price are null, and hypothetical numeric/cohort evidence appears only under `scenario_diagnostics.benchmark`. Economic and cap calculations remain available; no hypothetical bid recommendation is returned.
- Retained market analysis uses `{"mode":"retained_market","policy_revision":"<saved revision>"}`. Each observation carries the index's `snapshot_id`. That immutable collection must contain the same normalized observation. The saved revision must be the current head for its policy identity, and the normalized inline policy must match exactly.

The boundary checks current server observe/retain/benchmark permissions, saved source activation, supported model, policy dates, capture/observation freshness and expiry independently. Only the index's top-level `snapshot_id`, `index_stale` and `execution_enabled` fields are ignored in record equality. All monetary, source, hardware, rights, time and extension content stays bound. Historical `as_of` cannot revive stale observations. A valid unrelated memo reference is held; actual storage failures receive generic unavailable diagnostics.

Results include a versioned `pricing_provenance` block with actionable `blockers`, `status`, `source_evidence_eligible` and the policy revision. Evidence binding does not prove calibration, physical capacity or credit quality. Ordinary downstream holds still apply. Each complete scenario alternative is checked separately. Final decision snapshots preserve held status and hash the evaluated output.

## Economic loss and liquidity are different quantities

Loss VaR and expected shortfall aggregate only explicit, nonoverlapping loss components under supplied normalized scenario weights. Full cash stress measures dated funding shortfall against the common opening cash and financing baseline. An unannotated outflow must not silently become economic loss, and an omitted loss must not be described as verified zero.

Reports label both bases, retain `loss_attribution_completeness_verified: false`, and list scenarios without declared loss components plus cash-effect IDs without annotations. Those lists expose completeness gaps without declaring every payment a loss. Calibration stays unverified. A separate liquidity-tail distribution or limit needs explicit policy and evidence; loss expected shortfall does not supply it automatically.

See the [pricing kernel](../src/compute_pricing/control/pricing/engine.py), [cash search](../src/compute_pricing/control/pricing/liquidity.py), [API evidence boundary](../src/compute_pricing/control/api/provenance.py), and [loss-tail report](../src/compute_pricing/control/risk/tail.py). [Independent invented regressions](../tests/test_pricing_provenance_regressions.py) cover cap attribution, immutable joins, revoked rights, current policy heads, alternative scenarios and separate loss/funding quantities. All checks are offline.
