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
- Exact-workload inference qualification and complete allocated GPU costs, including idle capacity, versus explicit routed token/request tariffs.
- Capacity interval checks, portfolio exposure, explicit scenario/tail research, forward readiness and receivable financing simulations.
- Version-bound paper approvals, idempotent paper intents, uncertain-effect holds and authenticated immutable decision snapshots.
- Research-only regional/configuration regression with temporal and group/lot-separated holdouts.

This is a local read-only and paper development release. Source and qualification assertions are not independently verified assets or bank evidence. Calibration uses research diagnostics; no live regional premium, credit probability or confidence interval is asserted. The in-memory paper journal and SQLite snapshots need production identity, transactional durability, accounting, reconciliation and operating evidence before real execution.

## Run the local workbench

The [workbench guide](docs/workbench.md) runs a local browser UI with current source admission, native prices, freshness and immutable provenance. It includes manual scoped refresh and actual retained-reference evaluation; pricing/cash/inference editors keep synthetic examples separate. Four source roles are available: weekly GPU references, regional cloud VM retail meters, informational FX and bounded model discovery. They are not four interchangeable GPU-price feeds.

After installation, start `.venv/bin/python scripts/local.py start --runtime ABSOLUTE_EXTERNAL_RUNTIME --source-config examples/source-admission.json --collection-plan examples/collection-plan.json`, then open `http://127.0.0.1:8000`. Retrieve your locally generated development key with the explicit `scripts/local.py key` command and paste it into the page. Startup makes no live request; choose **Read admitted feeds** to index the configured scopes.

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

The earlier compact research interface remains available as `compute_pricing.evaluate` and `scripts/evaluate.py examples/request.json`; its packet and signing-cash model are described in [methodology](docs/methodology.md). Use the control-plane packet for full daily settlement and qualification work.

For the local API, set a fresh `COMPUTE_PRICING_API_KEY` secret of 32–256 printable characters and run `.venv/bin/python scripts/serve.py --store ABSOLUTE_EXTERNAL_SQLITE_PATH`. The database must be outside every Git checkout. The server binds only `127.0.0.1`, suppresses access logging and makes no feed request on startup. Source collection requires a separately reviewed `--source-config`; omission blocks all feeds.

Read [the implementation guide](docs/control-plane.md) for endpoints, request contracts, formulas, source boundaries and remaining work.

## Dynamic inputs and explicit policy

Prices, quantities, dates and terms belong in requests. Source enablement, freshness, cohort support, concentration limits, estimator choice and loss ownership belong in versioned policy. Missing is not zero. Extra fields are retained and visibly unpriced until a registered, validated method can use them. A policy-critical feature holds pricing when its owning model is unavailable.

The tool does not presume a universal US premium or turn every additional factor into an arbitrary percentage adjustment. Regional and configuration effects need comparable data and validated fitting; credit, availability and privacy have distinct eligibility, cash-loss, capacity and price paths. A token tariff or event-contract value never becomes a GPU-hour rate by averaging it into an index.

## Read more

- [Design](docs/architecture.md)
- [Control-plane methods and operating boundaries](docs/control-plane.md)
- [Compact research methodology](docs/methodology.md)
- [Scoped roadmap](docs/roadmap.md)
- [Contribution and publication policy](CONTRIBUTING.md)
- [Domain JSON Schema](docs/contracts/domain-v1.schema.json) and [generated TypeScript source](docs/contracts/domain-v1.types.txt)

MIT licensed. Public samples are invented; credentials, customer records, evidence documents and raw or licensed vendor payloads belong outside Git. Only the maintainer publishes to the default branch.

## Analyst workspace and flexible intake

The [quality and intake guide](docs/quality-and-intake.md) covers the responsive analyst layout, exact native-unit sorting, bounded collection and schema-neutral local table evidence. Unknown columns and source meanings remain visible; arbitrary input never becomes approved pricing evidence automatically. Offline validation requires Node 24 for the dependency-free frontend behavior tests; serving the app requires no JavaScript build.
