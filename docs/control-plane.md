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

Evaluation, inventory, policy and source routes authenticate before reading JSON. The local browser bootstraps a short-lived HttpOnly SameSite Strict session; writes require the exact Host/Origin, same-origin Fetch Metadata and a page-memory CSRF token. Optional API clients keep strong Bearer authentication. `/health` exposes metadata only. JSON rejects duplicate keys, NaN/infinity and oversized bodies. Library creation defaults to no feed reads. The local launcher enables explicitly configured, approved public startup/periodic reads inside its running backend; `--no-auto-refresh` opts out. Metadata GETs perform no collection. See [session and refresh contract](local-session-refresh.md).

| Route | Function |
| --- | --- |
| `GET /v1/contracts/schema` | Shared generated contract |
| `GET /v1/sources` | Explicit admission/implementation blockers |
| `POST /v1/session/bootstrap` | Exact-origin local browser session/CSRF bootstrap |
| `POST /v1/session/logout` | CSRF-protected shared-session revocation |
| `POST /v1/sources/{source_id}/collect` | Manual rights-admitted read |
| `GET /v1/market/refresh/status` | Application-owned public refresh status |
| `GET /v1/demo/market` | Latest explicitly configured public display scopes, native commitment points and current permissions/freshness; no whole-market completeness claim |
| `GET /v1/demo/contract` | Typed empty inputs, explicit assumptions and a deliberately selected invented example |
| `POST /v1/demo/scenario` | Compact declared economics, held provenance and actual supplier-rate dated cash, saved with the complete expanded input for replay |
| `POST /v1/pricing/evaluate` | Current benchmark, bid/ask and cash path |
| `POST /v1/pricing/scenarios` | Complete independent repricing alternatives |
| `POST /v1/cash/evaluate` | Dated accounting and funding simulation |
| `POST /v1/inference/evaluate` | Qualified local/routed economics |
| `POST /v1/calibration/evaluate` | Research fit and holdout diagnostics |
| `POST /v1/financing/evaluate` | Borrowing base or waterfall simulation |
| `GET /v1/portfolio/template` | Blank contract with no inferred funds or holdings |
| `POST /v1/portfolio/evaluate` | Pure shared-cash/capacity candidate assessment |
| `GET /v1/decisions/{sha256}` | Immutable authenticated snapshot replay |

SQLite development snapshots use canonical hashes, transactions, append-only triggers, exact replay checks and restricted file permissions outside Git. They are not a production double-entry journal, authorization database or recovery guarantee. Paper intents retain their process-local state machine and can use the optional [durable local paper repository](durable-paper-controls.md) for transactionally committed command history, exact historical retries and nonexecuting outbox records. Production identity, authoritative cash/capacity transactions, external reconciliation and certified recovery remain required.

The compact demo fixes its stated scope to USD, actual UTC calendar GPU-hours,
one exclusive supplier allocation and one buyer, and margin on gross billings.
Every commercial amount, collection share, utilization, fee, date and cash floor
is explicit. It recognizes the full service billing and records uncollected
receivables as writeoffs; these losses do not reduce the gross revenue denominator.
Outflows precede receipts on the same calendar date. A hypothetical reference is
display-only and cannot supply a benchmark or market cap. The API preserves the
held decision and null bid while returning scenario economics and funding limits.

## Source boundaries

The [local workbench](workbench.md) adds an authenticated retained-market index and bounded configured refresh. Azure is admitted for documented internal regional/SKU retail comparison in native VM-hour units; GPU model/count remain unknown. AWS regional files retain their native cloud meter units. OpenRouter supplies advertised model token rates with invalid-model quarantine and conditional prices unapplied. ECB provides informational EUR-base reference FX. Hugging Face supplies bounded model and recipe discovery without prices, weights or technical qualification. These roles stay separate from comparable physical GPU-hour support.


GetDeploying has a read-only weekly advertised-price CSV adapter. Its published [dataset](https://getdeploying.com/dataset/gpu-prices) specifies [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) attribution; the admission example records that scope. API selection excludes an incomplete current week. Values remain claimed global aggregates, not confirmed rentable inventory. No live prices or raw vendor payloads are committed here.

Vast parsers and Runpod query candidates retain explicit authentication, unit and rights gates. OpenRouter's reviewed anonymous catalog scope is restricted to local comparison and excludes inference calls, routing resale and raw public redistribution. Licensed index providers, financial venues and direct-model vendors remain candidates where commercial access/schema/rights or relevant instruments are unverified. The [admission example](../examples/source-admission.json) makes unavailable states visible. No source is enabled merely because its name is popular, a URL exists or an API key has been supplied.

The transport pins admitted public DNS to verified TLS connections, restricts endpoints/methods/redirects, bounds response sizes/timeouts/retries, respects cooldowns and rejects concurrent collection of the same source. It does not install a scheduler or send orders. Source attribution and allowed use remain part of every observation.

## Validation and next acceptance

The offline suite uses independently invented observations, scenarios and workload evidence. It covers changing prices/population, source/provider caps, unit/currency/term mismatches, duplicate lots, restricted cash, facility limits, settlement tails, inverse floors/ticks, full-node allocations, inference qualification, holdout leakage, exposure/loss ownership, financing/waterfall and paper ambiguity. It makes no live request.

Next acceptance requires certified physical/buyer evidence and meters; independently calibrated factors and loss models; durable identity/capacity/cash/journal/outbox; security/privacy isolation and permissions; restores and incident/load/stale-data drills; then separately authorized and reconciled execution rails. See [the scoped roadmap](roadmap.md).
