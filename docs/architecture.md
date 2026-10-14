# Architecture and boundaries

The Python boundary is `compute_pricing.evaluate(payload)`. Callers supply the cohort, observations, contract interval and policy assumptions. Decimal arithmetic supports reproducibility; changing inputs changes outputs without editing code.

Connectors, persistent evidence, calibrated models and a complete cash ledger are future components.

## Planned data flow

```text
Evidence → typed observations → normalization and cohort admission
         → benchmark snapshot → deal economics and constraints
         → reproducible decision record
```

Evidence preserves source values and timestamps. Admission checks comparability, freshness, offer identity and permitted use. Benchmarking records contributors, exclusions, weights and support. Pricing combines that snapshot with contract, cost and policy inputs.

Optional features belong in a versioned registry with a type, unit, evidence requirement and declared effect. An unknown extra field can be preserved without silently changing a formula. A missing required field prevents the affected calculation; a missing optional field must not become zero. Sensitive evidence stays outside public examples and source control.

## Reproducibility and updates

A decision record should retain inputs, evaluation time, schema/model/policy versions, results and reasons. Material changes create new evaluations; historical records remain reproducible. Stale or partial feeds produce explicit limitations and appropriate holds.

Future adapters acquire observations separately. Quotas, retries and permissions belong at the connector boundary. Price refreshes have no transaction side effects. Eventual execution requires separate authorization, idempotency and reconciliation.

The development sequence is in [the roadmap](roadmap.md); the economic conventions are in [the methodology](methodology.md).
