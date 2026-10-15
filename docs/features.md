# ComputeBasis capabilities

ComputeBasis turns nonstandard compute offers into comparable prices and
transparent contract economics. It combines market evidence, configurable
risk factors, inventory, power costs and cash-flow modeling to assess bids,
selling floors, margins and funding needs.

The browser app has four views: the Brief, Overview, Quotes and Pricing (see the [workbench guide](workbench.md)).
Overview and Quotes draw a simulated quote book; Pricing evaluates an editable contract with the full dated cash model.
The inventory, underwriting, policy, inference, cash, portfolio, power and hedge capabilities below are backend APIs; the
browser no longer has a page for them.

| Area | Working functionality |
| --- | --- |
| Pricing assessment demo | Three full editable provider/hardware/power/settlement/funding examples; simulated purchase ceiling, cost-recovery/minimum-margin/target asks, contribution and funding; modal with 70 declared surface points, native-unit retained cloud/reference context, cash and vesting charts; saved assessment JSON and unsigned receipt-bound compute-services PDF |
| Hourly treasury simulation | Explicit bank or stable-asset units/marks, restricted prefunding, service release, provider payments and arrears, customer refund, independent hypothetical yield accrual and provider/platform/buyer shares; liquidity/depeg/permission holds; no custody or money movement |
| Brief, Overview and Quotes | The landing Brief, an Overview of the simulated book (basis by GPU model and over time, supply and cost by seller grade, provider health, expiry, scenario controls) and a ranked Quotes table with per-quote cost breakdown and a handoff to Pricing; top navigation, light/dark themes and automatic local sessions |
| Market ingestion | Ten admitted anonymous source roles: GetDeploying datasets, Azure retail prices, AWS published regional prices, ECB FX, Hugging Face metadata and endpoint catalogs, OpenRouter model catalogs, Energinet power references, GPUHunt publisher-derived AWS/Azure/GCP GPU/VM catalogs and national GB grid-carbon context; explicit scopes, native units, pagination/archive budgets and source cooldowns |
| Comparable quote studies | Exact best-bid/best-ask midpoint and spread under matching configuration, region, delivery, payment, cost, unit, currency and whole-node size; one-sided/crossed/expired/unknown books held; physical forward, spot, financial future and advertised term roles remain separate; caller declarations are not firm quote evidence |
| Backend change delivery | Bounded configured-scope current view with authenticated ETag/304, immutable cache invalidated by new inputs and known expiry deadlines, and bounded SSE change notifications; source collection is separate from frontend subscriptions and monetary evaluations |
| Automatic updates | Backend refresh at configured source cadence, per-source backoff and retained immutable snapshots; freshness and publication lag stay visible through the API |
| Compute normalization | Hardware/configuration/region/term/unit comparability, exact currencies and evidence lineage; distinct physical listings, advertised aggregates, token meters and reference catalogs |
| Benchmarks | Explicit source-quality/freshness policies, source/provider concentration limits, support checks and weighted estimators; no arbitrary fusion of energy, token and GPU-hour prices |
| Curves | Observed commitment-duration nodes by source/cohort/week; declared nested contract totals and actual calendar GPU-hours; separate implied interval arithmetic, missing tenors and comparability holds; no default interpolation, extrapolation or future-price forecast |
| Power | Allocated idle/load/shared IT watts, utilization, PUE, actual interval energy, dated demand peaks, fixed/network/tax items and per-capacity/per-sold-hour costs; included/unknown power protections; source-bound wholesale reference scenarios |
| Inventory (API) | Physical units, lots and timed commitments with site coordinates; available/reserved/sold/maintenance/unavailable counts; overselling checks, unknown locations, immutable revisions, audit records and concurrent-write protection |
| Underwriting (API) | 112-entry typed factor catalog and editable requirements; subject/date-scoped evidence, missing-value and readiness checks for hardware, topology, uptime, counterparties, terms, privacy and compliance; no automatically calibrated credit probabilities |
| Pricing engine | Economic/market/liquidity bid caps, exact price ticks, minimum/target selling diagnostics, collections and fee conventions, explicit cost ownership, margin breakdown and full dated supplier cash inversion; held results do not emit a usable bid |
| Inference (API) | Whole-deployment measured goodput/SLO qualification, model/runtime/quantization/parallelism inputs, memory constraints, native token/request pricing, full-replica operating costs, sale-floor and supplier-ceiling diagnostics |
| Cash (API) | Daily and ordered cash paths, reserves, facilities, invoices, receipts, restricted deposits, usable advances, supplier prepayments, application/refund, credit notes, noncash write-offs and separate forfeiture income; explicit invoice calendar rules |
| Portfolio (API) | Shared capacity and cash across inference, resale and physical-forward routes; route ownership, full supply-cost reconciliation, margin/funding diagnostics and conservative entity/group/site/currency exposure bounds |
| Policies (API) | Immutable policies, predecessor/conflict checks, registered feature ownership, evidence-source admission and decision-version binding |
| Risk and hedges | Declared scenario loss tails, cash funding stress and capacity constraints; scalar signed futures hedge study, weighted covariance, zero/floor/ceiling candidates, fees, exact loss VaR/ES and separate collateral/variation-margin funding tails |
| Financing | Paper borrowing-base eligibility, receivable exclusions, pledge conflict checks, concentration/haircuts, facilities and collection waterfalls; securitization remains a feasibility track |
| Intake and audit | Workbook/table parsing, retained extra fields and unknowns, exact decimal inputs, generated domain contracts, reproducible decision hashes and append-only local SQLite records |
| Local controls | Same-origin authenticated sessions and CSRF, bounded HTTPS read transports, input/resource limits, source revocation/stale-evidence holds, restart/drain controls and offline verification |

These functions support research and paper decisions. Verified capacity, signed
contracts, bank/custody balances, calibrated predictive coefficients, licensed
financial quotes, clearing accounts, live execution and institutional operating
approval remain separate requirements. More fields do not create reliable
coefficients without evidence and validation.

Source cadence is not an exchange tick stream. Energinet's default rolling scope
contains completed Danish calendar days, with 15-minute UTC delivery intervals;
it is historical wholesale context, not a retail tariff or complete power curve.
Its [CC-BY4.0 terms](https://www.energidataservice.dk/terms-and-conditions) and
[API guide](https://www.energidataservice.dk/guides/api-guides) require attribution
and efficient cached use. No live vendor payload is committed in this repository.

Ornn and licensed financial data remain off until specific access and purpose
are verified. Documented compute futures are research leads, not proof of live
availability, liquidity or a qualified hedge for any physical offer. Financial
contract multipliers and basis must stay separate from actual calendar capacity.

API discovery is available at `/v1/demo/contract`, `/v1/cash/contract`, `/v1/curves/contract`,
`/v1/power/contract` and `/v1/hedges/contract`. Evaluation routes store their
registered model versions and never enable execution.

The [independently generated quote book](quote-book.md) supplies a populated,
reproducible demonstration with exact monetary strings, explicit missing terms,
calendar-based contract costing and bounded simulation controls. Its ranking
eligibility is a simulation rule; firm pricing and execution stay disabled.
