# ComputeBasis

**Compare compute offers on a common economic basis.**

Compute is hard to price consistently. An hourly GPU listing, an exclusive multi-GPU node reservation and an inference token bill describe different products. Hardware, topology, region, availability, contract duration and payment terms change what a dollar buys. A deal can show a positive margin while its cash commitments exceed available funding.

ComputeBasis is a Python toolkit and local API for evidence-aware compute normalization, procurement economics and dated cash simulation. Changing source observations, workload qualifications and contract terms are inputs; policy and model versions explain how they become a reference mark, bid ceiling, selling floor and held decision.

Maintained by **Tharun Ekambaram**.

## Implemented

- Immutable shared contracts, exact Decimal strings, generated JSON Schema/TypeScript, typed units and preserved extensions.
- Read-only source admission and bounded HTTPS transport, with explicit rights, authentication, freshness and schema states.
- Separate physical offers, advertised aggregate references, token tariffs and financial/event instruments.
- Comparable cohort matching, complete-node normalization, duplicate/conflicting lot handling, configurable source/provider weights and support diagnostics.
- Inverse bid/ask economics with explicit collection/fee/margin denominators and nonoverlapping owned costs.
- Full dated cash ledgers, segregated advances, supplier prepayments, reserves, facility roll-forwards and conservative cash-limited price ticks.
- Exact-workload inference qualification, full idle allocation cost, explicit routed operating costs, mix-specific price floors and qualified-capacity break-even diagnostics.
- Persistent declared inventory with physical-unit interval checks, sold/reserved/maintenance/available states, local geographic map and contract timelines.
- Immutable benchmark and typed feature policies with exact source weights, freshness/support controls, registry ownership and optimistic concurrency.
- Portfolio exposure, explicit scenario/tail research, forward readiness and receivable financing simulations.
- Durable local paper commands, exact idempotent receipts, version-bound approvals, restart-safe uncertain-effect holds and a nonexecuting paper outbox.
- One shared portfolio candidate assessment for exclusive capacity, complete supply cost, dated funding and baseline exposure limits.
- Research-only regional/configuration regression with temporal and group/lot-separated holdouts.
- Exact comparable bid/ask studies for spot, physical forwards and financial futures, with separate advertised commitment references, whole-node size checks and explicit source-evidence holds.
- Anonymous publisher-derived AWS/Azure/GCP GPU/VM references, plus conditional retained-market reads and bounded server-sent change notifications.
- Server-bound retained cohort comparisons, versioned simulation-policy previews, and selected-quote cash scenarios using exact supplier capacity, calendars, deposits and net terms.

This is a local read-only and paper development release. Source and qualification assertions are not independently verified assets or bank evidence. Calibration uses research diagnostics; no live regional premium, credit probability or confidence interval is asserted. Local durable paper commands and snapshots still require production identity, authoritative transactional cash/capacity coordination, accounting and witnessed operating evidence before real execution.

The [backend pricing flow](docs/backend-pricing-flow.md) documents the retained
reference and quote-to-cash routes for a separately developed frontend. Source
observations, simulation policy and saved paper decisions retain distinct roles.

## Run the local workbench

The [workbench guide](docs/workbench.md) starts the local application. It opens a short-lived same-origin workspace session automatically. Ten configured anonymous source roles provide advertised GPU references, regional retail meters, native cloud tariffs, inference token rates, informational FX, model/recipe discovery, wholesale energy references, publisher-derived GPU/VM catalogs and [Great Britain grid-carbon context](docs/grid-carbon-context.md). The backend refreshes explicitly configured scopes with permission checks, cooldowns, coalescing and backoff; the browser synchronizes retained evidence without overwriting drafts. Native economic units stay separate. Configured access is distinct from runtime availability and public redistribution permission.

Start `.venv/bin/python scripts/local.py start --runtime ABSOLUTE_EXTERNAL_RUNTIME --source-config examples/source-admission.json --collection-plan examples/collection-plan.json` after installation, then open `http://127.0.0.1:8000`. No credential paste is needed. Source reads run only while the local app runs; no system jobs are installed. `--no-auto-refresh` selects manual operation. Review [source scope](docs/source-adapters.md), [session and refresh](docs/local-session-refresh.md) and [workspace workflows](docs/workspace-workflows.md).

For the focused **Market → Deal economics → Inventory** demonstration, use the
[demo runbook](docs/demo-sprint.md) and its four-scope collection plan:

```sh
DEMO_RUNTIME="${TMPDIR:-/tmp}/computebasis-public-demo"
.venv/bin/python scripts/local.py start --runtime "$DEMO_RUNTIME" \
  --source-config examples/source-admission.json \
  --collection-plan examples/demo-collection-plan.json \
  --auto-refresh-config examples/auto-refresh.json --port 8000
```

This schedules GetDeploying, ECB and Energinet DK1/DK2 only. Choose the invented
deal deliberately; its costs, margin and cash diagnostics remain a **synthetic
scenario**, with no admitted physical bid or trade. Live references never become
owned inventory or verified counterparty evidence. Keep this dedicated runtime
outside Git and separate from any runtime containing sensitive records.

## Try the current control plane

Use Python 3.12 and a virtual environment:

```sh
git clone https://github.com/tharune/computebasis.git
cd computebasis
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install -e . --no-deps
.venv/bin/python -m compute_pricing.control.cli pricing examples/control-pricing.json
.venv/bin/python scripts/validate.py
```

The example is independently invented synthetic data. It demonstrates a cash-limited bid, defined selling floors and a funding shortfall at the separately supplied supplier ask. Change observations, dates, costs, margins or funding and rerun the same engine. It is not market inventory.

```python
from compute_pricing.control.pricing import evaluate_pricing

result = evaluate_pricing(request)
```

The earlier compact research interface remains available as `compute_pricing.evaluate` and `scripts/evaluate.py examples/request.json`; its packet and signing-cash model are described in [methodology](docs/methodology.md). Use the control-plane packet for its supported dated settlement and qualification methods.

For explicit machine API clients, optionally set a fresh `COMPUTE_PRICING_API_KEY` secret of 32–256 printable characters and run `.venv/bin/python scripts/serve.py --store ABSOLUTE_EXTERNAL_SQLITE_PATH`. The database must be outside every Git checkout. The server binds only `127.0.0.1` and suppresses access logging. The launcher uses the reviewed public admission and collection configurations by default, with bounded startup and periodic reads. The app-library factory defaults to offline/manual behavior, and `--no-auto-refresh` disables runtime automatic reads. Cookie access is scoped to local reads, pure evaluations and paper inventory/policy changes; execution stays disabled.

Read [the implementation guide](docs/control-plane.md) for endpoints, request contracts, formulas, source boundaries and remaining work.

## Dynamic inputs and explicit policy

Prices, quantities, dates and terms belong in requests. Source enablement, freshness, cohort support, concentration limits, estimator choice and loss ownership belong in versioned policy. Missing is not zero. Extra fields are retained and visibly unpriced until a registered, validated method can use them. A policy-critical feature holds pricing when its owning model is unavailable.

The tool does not presume a universal US premium or turn every additional factor into an arbitrary percentage adjustment. Regional and configuration effects need comparable data and validated fitting; credit, availability and privacy have distinct eligibility, cash-loss, capacity and price paths. A token tariff or event-contract value never becomes a GPU-hour rate by averaging it into an index.

## Read more

- [Backend/frontend integration contract](docs/backend-frontend-handoff.md), [quote readiness](docs/quote-readiness.md) and [provider coverage](docs/provider-source-coverage.md)
- [Design](docs/architecture.md)
- [Three-screen demo runbook and sprint scope](docs/demo-sprint.md)
- [Control-plane methods and operating boundaries](docs/control-plane.md)
- [Compact research methodology](docs/methodology.md)
- [Conditional threshold-ladder diagnostics](docs/market-diagnostics.md)
- [Shared portfolio and inference price floors](docs/portfolio-and-inference-diagnostics.md)
- [Scoped roadmap](docs/roadmap.md)
- [Contribution and publication policy](CONTRIBUTING.md)
- [Domain JSON Schema](docs/contracts/domain-v1.schema.json) and [generated TypeScript source](docs/contracts/domain-v1.types.txt)

MIT licensed. Public samples are invented; credentials, customer records, evidence documents and raw or licensed vendor payloads belong outside Git. Only the maintainer publishes to the default branch.

## Analyst workspace and flexible intake

The [quality and intake guide](docs/quality-and-intake.md) covers the responsive analyst layout, exact native-unit sorting, bounded collection and schema-neutral local table evidence. Unknown columns and source meanings remain visible; arbitrary input never becomes approved pricing evidence automatically. Offline validation requires Node 24 for the dependency-free frontend behavior tests; serving the app requires no JavaScript build.

The [inventory and policy guide](docs/inventory-and-policy.md) covers versioned local holdings, source controls and factor registration. Public demos are independently invented; listings never automatically become inventory. Map outlines are packaged [public-domain Natural Earth geometry](docs/third-party-notices.md), with no external tile or location request.

The [interface design guide](docs/interface-design.md) records typography, action hierarchy, accessible controls and visual review criteria.

The [underwriting coverage guide](docs/underwriting-assessment.md) describes the 112 neutral requirements, dynamic scopes and caller-qualified evidence checks. Missing evidence remains explicit; checklist coverage does not calibrate price factors or approve a transaction. The workspace now uses top navigation and light/dark themes.

Current functionality and backend curve, power and hedge boundaries are listed in [capabilities](docs/features.md).

A separate [simulated quote book](docs/quote-book.md) provides independently generated
providers, offer terms and scenario changes through authenticated `/v1/book` routes.
These invented records remain separate from live reference collection, retained
market evidence and declared inventory.
