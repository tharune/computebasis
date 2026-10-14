# Local workbench and live coverage

The October 14 release adds the ComputeBasis browser workbench to the existing
read-only/paper kernels. It starts a loopback application, indexes explicit
admitted public scopes and lets actual retained observations drive an indicative
reference evaluation. It does not enable trades or turn unknown quantities,
GPU counts, performance, counterparty credit or demand into defaults.

## Start, connect and manage

Use the pinned virtual environment from the implementation runbook. Choose an
absolute runtime directory outside every Git checkout for the 0600 local API key,
SQLite snapshots, service metadata and logs. Copy the [collection plan](../examples/collection-plan.json)
there and edit its region, author and retrieval budgets explicitly. These are
starting coverage settings, not hardcoded market prices or universal model policy.

```sh
.venv/bin/python scripts/local.py start --runtime ABSOLUTE_EXTERNAL_RUNTIME \
  --source-config examples/source-admission.json \
  --collection-plan ABSOLUTE_EXTERNAL_PLAN
.venv/bin/python scripts/local.py status --runtime ABSOLUTE_EXTERNAL_RUNTIME
.venv/bin/python scripts/local.py key --runtime ABSOLUTE_EXTERNAL_RUNTIME
.venv/bin/python scripts/local.py stop --runtime ABSOLUTE_EXTERNAL_RUNTIME
```

The local URL is `http://127.0.0.1:8000` unless an explicit port is supplied.
Paste the development key into the password field and select **Connect**. The
page keeps the key in memory; no cookie, local storage, query-string credential,
external asset or third-party request is used. Ending the session clears received
data and drafts, and responses still in flight cannot restore a logged-out view.
Normal startup/status output never prints the key; only the explicit `key`
command does. A launch does not collect feeds automatically or install a job.

The launcher refuses an occupied port and refuses to stop an unrelated process.
It reuses its own ready instance and preserves external snapshots/key on stop.
The API remains loopback-only with Bearer authentication for every `/v1` route;
the unauthenticated shell and health endpoint contain no financial data or key.

## Live source roles

| Source | Current role and verification | Important limit |
| --- | --- | --- |
| GetDeploying | Published weekly advertised GPU-hour reference; current complete week selected, attribution retained | Global publisher aggregate; no independent lot, delivery right, local premium or confirmed inventory |
| Azure Retail Prices | Documented unauthenticated internal comparison API; explicit N-family region/SKU consumption-hour scope, exact retail USD/native node-hour amounts | Price API does not supply GPU model/count or rentable quantity; no automatic GPU-hour normalization or tax/storage/transfer inclusion |
| ECB | Attributed published daily reference FX, exact EUR-base quote rates | Informational reference, not an executable settlement/hedge quote; observation date stays separate from capture |
| Hugging Face | Bounded public author/task model metadata, licensing/gating/revision claims retained | No prices, weight downloads, model-use permission or measured technical qualification; limited response is not a complete model universe |

Index counts come from the live API and change with each source response. Model discovery is bounded and explicitly incomplete. Native retail/listing prices are not verified capacity. Other API candidates remain visible with rights, authentication, instrument or
schema blockers; popularity and a readable URL do not admit a new source.

The [source status](control-plane.md) and [model metadata scope](model-discovery.md)
record primary documentation and rights boundaries. No public repository contains
the live snapshots or client source data. The required metadata/byte limits,
verified TLS with the pinned CA bundle, public DNS pinning, exact endpoint/query
redirect constraints, cooldowns and explicit bounded pagination remain enforced.

## What the browser does

The market page displays source admission, retained scopes, current-policy
freshness, native units, exclusions/coverage, and snapshot provenance. Filters
and pagination operate on received rows. FX and model discovery remain separate
from compute price support. Synthetic examples never fill an empty live index.

**Evaluate live reference** builds an editable request from the chosen admitted
current aggregate GPU model and exact billing/reservation term. Its single-source
exploration weights are explicitly unvalidated; the result is a global reference
with no commercial bid, ask or regional premium. The separate pricing editor can
load a clearly labelled invented scenario and calculate the declared bid/ask and
full cash waterfall. Inference and cash editors use their existing pure kernels.

All result panels show the immutable snapshot, versions, holds and full JSON.
Vendor text is rendered as text, not executable HTML. The shell uses restrictive
same-origin CSP, no external assets, and no form credential field name/value.
Browser automation environments may block loopback navigation; HTTP, assets,
auth, live collection and pricing can still be verified through the local API.

## Index and refresh contracts

`GET /v1/market/index` makes no live request. It returns the latest integrity-checked
collection per explicit source/filter population, current admission and staleness,
native observations, separate catalog records and coverage/display limits.
Changing a retrieval page budget does not create an independent population.

`POST /v1/market/refresh` accepts either `source_ids` using the configured plan or
an explicit `requests` array of `{source_id, filters}`. It requires auth, checks
observe/retain/benchmark scopes before and after collection, paces shared hosts
within the wait budget, and records updated/held/failed scopes individually.
Successful previous evidence remains available after another scope fails, with
current expiry checked rather than refreshed by the failure. Every attempt has a
distinct refresh event and timestamps, so a repeated failure cannot appear older
than an intervening success. No infinite retries or scheduled requests are added.

Current lookup/display budgets are explicit in the index, not claims of complete
worldwide market coverage. Firm procurement still needs admitted verified physical
offers, complete contracts/buyer demand, independently validated risk inputs and
durable capacity/treasury/execution acceptance described in the broader plan.
