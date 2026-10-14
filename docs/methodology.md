# Pricing compute that is not standardized

A compute price describes hardware, memory, interconnect, location, availability, guarantees and payment terms. Identical accelerator names can conceal different economic value. Advertised rates say little about attainable inventory, overhead or workload performance.

ComputeBasis makes those differences explicit before calculating a benchmark or bid. Call `compute_pricing.evaluate(payload)` with observations and policy inputs. This offline prototype explains its arithmetic; it does not discover inventory or independently verify evidence.

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

Costs are explicit named components. The selling floor assumes purchase at the recommended bid ceiling; recompute it against the actual supplier acquisition price before making a firm sale. The reported profit and margin include the supplied policy capital charge, so they are economic results rather than a cash-ledger balance. A nonpositive denominator has no feasible floor. Revenue-dependent fees, gross-billed margins, tick rounding and a full daily funding test require extensions beyond this release. Its funding cap covers supplier advances and upfront costs only.

Unknown terms remain unknown. A calculated margin is conditional on its inputs; it does not prove creditworthiness, enforceability, availability or execution readiness.
