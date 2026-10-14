# Architecture and boundaries

ComputeBasis separates source evidence, comparable prices, contract economics, dated cash, technical qualification and financial authority. Changing observations and terms change the result without changing code. Exact monetary calculations retain declared units, currencies and versions.

The current local control-plane entry is `compute_pricing.control.pricing.evaluate_pricing`; authenticated API routes wrap the same kernels and store hashed development snapshots. `compute_pricing.evaluate` remains the compact research interface. The [control-plane guide](control-plane.md) defines their scope and request boundaries.

## Current development flow

```text
Admitted read → typed observations → exact cohort and normalization
              → deduplicated weighted benchmark → inverse economics
              → full dated shared-account cash constraints
              → immutable indicative/held decision
```

Read-only connectors enforce rights, admitted endpoints, authentication, TLS/DNS, quotas and bounded retries. Physical offers and aggregate references retain different evidence. Token tariffs, financial marks and event values have separate unit-aware roles. Benchmark snapshots expose excluded inputs, actual contributors and weights, support and uncalibrated dispersion.

Pricing reconciles explicit buyer collections and owned costs with the scoped deal's dated cash legs. Full-node allocation, complete settlement horizons, reserves and ordered cash troughs constrain a purchase price. Inference costing uses measured matching workload setups and the entire allocated GPU deployment, including idle capacity. Research regression never silently becomes a live regional premium.

Features belong in a versioned registry with type, unit, evidence and owning model. Unknown fields survive as evidence and remain visibly unpriced. Missing critical inputs or unavailable validated owning methods hold the result. Source assertions do not independently establish commercial rights, privacy, bank balances or creditworthiness.

## Persistence and control

The local API saves immutable canonical input/output/version snapshots in SQLite outside Git and verifies hashes on replay. The paper journal binds approvals to versions/expiry, checks claimed actor limits and preserves holds for unknown effects until independent reconciliation. These are tested development slices.

Production identity and authorization, transactional capacity/cash holds, balanced journal, durable outbox/saga, recovery and external reconciliation remain implementation and operating-certification work. Calibrated models require representative evidence and independent validation. Real execution needs a separately admitted, funded and authorized rail.

Price refreshes have no transaction side effects. No startup feed collection, signing, trading, paid inference or funds movement occurs. The [roadmap](roadmap.md) records the remaining acceptance for each module.
