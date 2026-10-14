# Pricing compute that is not standardized

A compute price describes hardware, memory, interconnect, location, availability, guarantees and payment terms. Identical accelerator names can conceal different economic value. Advertised rates say little about attainable inventory, overhead or workload performance.

ComputeBasis makes those differences explicit before calculating a benchmark or bid. This page describes the compact `compute_pricing.evaluate(payload)` reference interface. The [control plane](control-plane.md) adds admitted source discovery, dated cash, inference and [shared portfolio assessment](portfolio-and-inference-diagnostics.md). Neither interface independently verifies evidence or acquires inventory.

## Compare the same product

Define the target cohort first. Keep node bundles, accelerator hours and inference services separate. A node price can become an accelerator-hour price only with a known accelerator count and comparable resources. A token service needs a workload and performance model before comparison with capacity.

Use one declared currency and unit within a calculation. Retain the original offer, normalization steps and observation time. Repeated advertisements of the same underlying capacity do not constitute independent supply. Listings, firm quotes and completed rentals have different evidentiary strength.

## Keep the inputs dynamic

Prices, weights, costs, collection assumptions, caps and contract timestamps are supplied inputs. Example files are synthetic cases, not market defaults. Contract hours come from the supplied interval; this is not a complete invoicing or cash-settlement calendar.

The prototype matches hardware, region, currency and tenor. Source policy controls admission, quality and freshness. Latest observations of an underlying lot supersede relistings. Provider-group weight caps and minimum support prevent a concentrated sample from silently becoming an index. Duration compatibility does not verify a future delivery window or firm capacity commitment; this release does not construct a forward curve.

Choose a weighted median or a mean clipped around that median:

```text
clipped price_i = clamp(price_i, median * (1 - band), median * (1 + band))
clipped mean = sum(final weight_i * clipped price_i)
```

Weights combine source quality and age decay before concentration caps. Support and dispersion describe the sample, not forecast confidence. Cross-region or configuration adjustment requires future calibration; there is no universal country premium.

## Separate value, affordability and margin

A purchase limit is constrained by economics, the market mark, an optional supplier policy cap and advance funding. The binding cap is visible. Capital charges affect economics without automatically being cash payments. Buyer prepayment contributes to procurement funding only when the caller explicitly permits that use.

A simplified selling floor uses expected collected hours and margin on collected revenue:

```text
minimum ask = all-in cost / [expected collected hours * (1 - required margin)]
```

Costs are explicit named components. The selling floor assumes purchase at the recommended bid ceiling; recompute it against the actual supplier acquisition price before making a firm sale. The reported profit and margin include the supplied policy capital charge, so they are economic results rather than a cash-ledger balance. A nonpositive denominator has no feasible floor. This compact interface has no revenue-dependent fee, gross-billed margin, tick or full daily funding solve; its funding cap covers supplier advances and upfront costs only. Use the control-plane pricing and cash interfaces for their explicit supported terms, and the shared portfolio kernel to reconcile routes against one cash and capacity baseline.

Unknown terms remain unknown. A calculated margin is conditional on its inputs; it does not prove creditworthiness, enforceability, availability or execution readiness.

## Model the joint distribution before labeling percentiles

Expectations are linear; percentiles generally are not. A weighted sum of component percentiles is a sensitivity calculation, not the percentile of their aggregate. A regime mixture also needs its complete mixture distribution before a percentile can be reported. Dependence, weights, support and distribution evidence must be explicit; invented stress ranges do not become forecast confidence intervals.

For an independently invented illustration, consider two equally likely loss paths, `(0, 12)` and `(12, 0)`, in the same currency. Each component's 75th percentile is 12, but the portfolio always loses 12. Adding the component percentiles would report 24. If the paths instead are `(0, 0)` and `(12, 12)`, the component marginal distributions are unchanged while the portfolio's 75th percentile becomes 24.

The control-plane tail-risk calculation therefore takes complete joint scenarios and explicit probabilities; it calculates discrete VaR and fractional-boundary expected shortfall after aggregating each path. It still reports `calibration_verified = false`: normalized supplied weights are not empirical validation. The [independent dependence regression](../tests/test_joint_distribution_semantics.py) checks this counterexample against the shipped kernel. Scenario loss attribution and cash effects retain separate ownership so reporting a loss does not debit cash twice.
