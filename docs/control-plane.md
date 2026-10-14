# Control-plane implementation guide

The control plane accepts declared evidence and scenarios. Every output is indicative or held and execution remains disabled. Validation proves arithmetic and input/state invariants on supplied data; independent data, legal, security and operating certification remain necessary.

## Request and decision flow

1. Preserve source status, source and ingestion times, rights, unit, currency, hardware, identity and actual terms in a domain observation.
2. Match a physical cohort or explicitly separate advertised aggregate cohort. Exclude incompatible sources or missing critical evidence and expose the reasons.
3. Normalize complete-node comparison rates and known quantity units. Deduplicate the same underlying lot; conflicting provider identities are quarantined.
4. Apply declared age/quality weights and source/provider caps. Report contributors, actual weights, support and dispersion. Dispersion is not a calibrated confidence interval.
5. Combine buyer economics, owned costs and full dated shared-account cash. Invert the constraints into a purchase limit and selling floors on an explicit tick grid.
6. Bind input, schema, policy, registry and model versions in an immutable decision snapshot. Technical qualification, capacity, privacy, credit, liquidity and execution approval remain distinct.

`market` is the generated `PricingRequest`. `target` identifies scope, currency, hardware, country, exact configuration, GPU count and actual UTC delivery dates/duration. `commercial` provides buyer billings/rate, supplier ask, collection fraction, fee bases, required margin/denominator, market discount, price tick, complete-node GPU count, cost owners and cost lines. See [the invented packet](../examples/control-pricing.json).

Aggregate reference requests require explicit `aggregate_terms` with billing type and reserved-month tenor, with exact source matches. They cannot claim a local configuration, physical lot, delivery quantity or regional premium. Repeated observations of the same source/model/term/week add no independent support.

Unregistered fields survive in evidence or the hashed input and appear as unused; they do not silently alter a formula. Critical features without an approved owning model hold pricing. Float money, missing required terms, mismatched currency, duplicate loss channels and ambiguous units fail validation.

## Financial definitions

Let `S` be allocated GPU-hours, `B` gross billed GPU-hours, `a` buyer rate, `q` expected collection share, `fc` fee fraction on collected revenue, `fg` fee fraction on gross billing, `m` required margin, `C` expected fixed cost, `K` policy capital and `x` purchase-linked cost fraction.

The net revenue factor is `q(1-fc)-fg`. Required margin subtracts `m` for a gross-billing denominator or `mq` for a collected-revenue denominator. The economic purchase ceiling is:

```text
(a * B * required_margin_factor - C - K) / (S * (1 + x))
```

The reservation price is constrained by economic, market, explicit stress and full cash-path limits. Buy ticks round down; sell ticks round up. Nonpositive factors/caps or sub-tick feasibility hold the decision. Expected contribution deducts expected costs; economic profit deducts policy capital once. Both selling floors and margins use the supplied supplier ask, which can exceed our affordable bid.

Actual UTC duration supplies `S`; no universal 730-hour month is used. Allocated integer GPUs must form complete exclusive nodes. A normalized whole-node per-GPU mark is a full-bundle allocation measure; it does not grant fractional procurement rights. Buyer physical billings cannot exceed exclusive supply capacity.

## Complete cash path

`cash_template` contains `schedule`, `purchase_coefficients`, `deal_event_ids` and `minimum_cash`. The schedule covers the common entity/account/currency baseline, as-of, service and every known final settlement. Restricted deposits remain separate from unrestricted bank cash. They can release only against evidenced earned invoices; supplier prepayments credit invoices once. Unused facility commitments are not bank cash.

The scoped deal's variable supplier outflows reconcile to `S(1+x)`, buyer collections to `aBq` and fixed outflows to expected costs plus collection/gross fees. Accounting counterparts must balance. All final advance/invoice balances must settle. Increasing purchase rate may increase outflows, never incoming buyer/deposit/facility legs. Facility-dependent or nonlinear funding needs a separate complete reevaluation.

The cash-limited solver replays every calendar day and ordered same-day trough, then searches integer price ticks conservatively. It reports the selected ledger, affordable tick and separate cash shortfall at the supplied supplier ask. Arbitrary caller-supplied liquidity-cap points are rejected. A caller can still omit an unknown obligation, so this is declared-scenario analysis until contracts and statements are independently reconciled.

Separate cash simulations support explicitly dated committed facilities, revolving/nonrevolving commitment, actual-day interest, reserve intervals, maturity checks and unresolved balances. Complete alternative scenarios are independent paths; overlapping shared cash cannot be added together.

## Inference and factor research

Inference comparisons require exact model/runtime/hardware/precision/quantization, tensor/pipeline/data parallelism, context, batch and request token mix. A current supplied benchmark must match this setup, cover the service interval and evidence measured whole-deployment SLO goodput, TTFT/p95, memory including KV/runtime overhead and parallel bandwidth.

Measured whole-deployment requests per second are not multiplied again by replicas or batch. GPU costs include every allocated GPU through the actual calendar, including idle time. Input, output and cached-input token quantities and per-request charges have separate denominators; cache does not become free by default. Routed comparisons require compatible model/precision/quantization and rates that cover the interval. Benchmark evidence does not establish privacy, quality, buyer demand or supplier credit.

Hedonic research fits log normalized physical prices with explicit feature/reference coding, training-only scaling, rank/support gates and temporal/group/lot-separated holdouts. Numeric fitting uses research floating-point diagnostics. Coefficients are not automatically published into monetary evaluation or treated as causal regional premiums. Real representative data, uncertainty, independent holdouts, ablation and bounded coefficient approval are remaining work.

Tail research accepts a complete explicitly normalized scenario distribution and common portfolio baseline with exclusive loss ownership. Weighted VaR and expected shortfall are conditional on those supplied probabilities. Financing simulations distinguish eligible accepted receivables, disjoint haircuts, unique pledges, concentration denominators, commitment/borrowing-base bounds and forecast-versus-cleared collections. No funded lender offer or security issuance is implied.

## API and persistence

All evaluation/read routes require a bearer key. `/health` exposes metadata only. JSON rejects duplicate keys, NaN/infinity and oversized bodies. No network request occurs at startup or on metadata GETs.

| Route | Function |
| --- | --- |
| `GET /v1/contracts/schema` | Shared generated contract |
| `GET /v1/sources` | Explicit admission/implementation blockers |
| `POST /v1/sources/{source_id}/collect` | Manual rights-admitted read |
| `POST /v1/pricing/evaluate` | Current benchmark, bid/ask and cash path |
| `POST /v1/pricing/scenarios` | Complete independent repricing alternatives |
| `POST /v1/cash/evaluate` | Dated accounting and funding simulation |
| `POST /v1/inference/evaluate` | Qualified local/routed economics |
| `POST /v1/calibration/evaluate` | Research fit and holdout diagnostics |
| `POST /v1/financing/evaluate` | Borrowing base or waterfall simulation |
| `GET /v1/decisions/{sha256}` | Immutable authenticated snapshot replay |

SQLite development snapshots use canonical hashes, transactions, append-only triggers, exact replay checks and restricted file permissions outside Git. They are not a production double-entry journal, authorization database or recovery guarantee. Paper intents use in-memory locks, economic idempotency, distinct proposer/risk/treasury identities and independently reconciled uncertain legs. Production identity and durable atomic holds/outbox/reconciliation remain required.

## Source boundaries

The [local workbench](workbench.md) adds an authenticated retained-market index and explicit scoped refresh. Azure is admitted for documented internal regional/SKU retail comparison in native VM-hour units; GPU model/count remain unknown. ECB provides informational EUR-base reference FX. Hugging Face provides bounded [model discovery](model-discovery.md) without prices, weights or technical qualification. These roles stay separate from comparable GPU-hour support.


GetDeploying has a read-only weekly advertised-price CSV adapter. Its published [dataset](https://getdeploying.com/dataset/gpu-prices) specifies [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) attribution; the admission example records that scope. API selection excludes an incomplete current week. Values remain claimed global aggregates, not confirmed rentable inventory. No live prices or raw vendor payloads are committed here.

Vast/OpenRouter parsers and Runpod query candidates have explicit authentication, unit and rights gates. Licensed index providers, financial venues and direct-model vendors remain candidates where commercial access/schema/rights or relevant instruments are unverified. The [admission example](../examples/source-admission.json) makes unavailable states visible. No source is enabled merely because its name is popular, a URL exists or an API key has been supplied.

The transport pins admitted public DNS to verified TLS connections, restricts endpoints/methods/redirects, bounds response sizes/timeouts/retries, respects cooldowns and rejects concurrent collection of the same source. It does not install a scheduler or send orders. Source attribution and allowed use remain part of every observation.

## Validation and next acceptance

The offline suite uses independently invented observations, scenarios and workload evidence. It covers changing prices/population, source/provider caps, unit/currency/term mismatches, duplicate lots, restricted cash, facility limits, settlement tails, inverse floors/ticks, full-node allocations, inference qualification, holdout leakage, exposure/loss ownership, financing/waterfall and paper ambiguity. It makes no live request.

Next acceptance requires certified physical/buyer evidence and meters; independently calibrated factors and loss models; durable identity/capacity/cash/journal/outbox; security/privacy isolation and permissions; restores and incident/load/stale-data drills; then separately authorized and reconciled execution rails. See [the scoped roadmap](roadmap.md).
