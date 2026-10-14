# ComputeBasis

**Compare compute offers on a common economic basis.**

Compute has a price-comparison problem. An hourly GPU quote, a multi-GPU node reservation and a hosted inference bill describe different products. Hardware, topology, geography, availability, contract duration and payment terms change what a quoted dollar buys. A cheap listing can be expensive to deliver—and profitable on paper while requiring more cash than is available.

ComputeBasis is a Python toolkit for transparent compute-price normalization and procurement economics. It accepts changing observations and deal terms, builds an explicitly qualified comparable index, and explains the constraints behind a bid ceiling and a selling floor.

Maintained by **Tharun Ekambaram**.

## What works today

- JSON-driven inputs with variable observation counts, named cost components and preserved extensions.
- GPU-hour and node-hour normalization with explicit GPU counts, matching currency, hardware, region and tenor.
- Source admission, freshness, duplicate-lot handling, configurable quality weights and provider-concentration controls.
- Weighted-median or winsorized-mean comparison, with contributors, exclusions and support diagnostics.
- Deal economics using actual start/end timestamps, supplied utilization/availability/collection assumptions, and explicit costs, margins and signing-funding constraints.
- Decimal-string results and reproducible snapshots. Missing or inadequate evidence produces a held result.

The current release is an offline research prototype. Live vendor adapters, calibrated risk models, a daily cash ledger, inference performance qualification and execution are roadmap work. Observation status and source quality are supplied evidence assertions; this library does not independently verify them. It does not place orders or move funds.

## Try it

Python 3.11 or later; runtime uses the standard library.

```sh
git clone https://github.com/tharune/computebasis.git
cd computebasis
python3 scripts/evaluate.py examples/request.json
python3 -m unittest discover -s tests -v
```

The example is independently invented synthetic data. Its numbers demonstrate the mechanics and are not market observations. Change its prices, source rules, costs or contract dates and rerun the same engine.

```python
from compute_pricing import evaluate

result = evaluate(request)
```

Install the package with `python3 -m pip install -e .` for library imports, or use the script directly from a checkout. Feed a JSON request through standard input with `python3 scripts/evaluate.py -`.

## Dynamic inputs, explicit policy

Prices and contract terms belong in inputs. Source enablement, freshness limits, concentration limits and estimator choice belong in versioned policy. A new optional field can be retained as an extension, but only a registered, validated method may use it to change a price. Missing values are not zero. Configurable assumptions are not calibrated estimates.

The engine compares a declared cohort. Regional and hardware differences require comparable evidence or an independently validated adjustment model; a universal country premium would conceal a different product. Rental rates, token-service rates and financial-instrument prices need separate unit-aware models.

## Read more

- [The problem and design](docs/architecture.md)
- [Methods and boundaries](docs/methodology.md)
- [Implementation roadmap](docs/roadmap.md)
- [Publication and contribution policy](CONTRIBUTING.md)

## Development

Keep numerical methods deterministic, preserve units and provenance, and test changing inputs and missing evidence. Public samples must be independently synthetic or explicitly redistributable. Credentials, private customer data and licensed raw feeds belong outside Git.

MIT licensed. This repository is maintained as an owner-published project; outside contributions can be proposed for review, but only the maintainer publishes to its default branch.
