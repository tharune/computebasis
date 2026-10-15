# Local workbench

The workbench is the browser app that ships with the local ComputeBasis API. It has four views: the **Brief** (the
landing page), **Overview**, **Quotes** and **Pricing**. Overview and Quotes run on a locally simulated quote book;
Pricing evaluates one editable contract on the pricing engine. Everything is read-only or paper: nothing here executes
a trade, and no unknown quantity, GPU count, performance figure, counterparty credit or demand is turned into a default.

## Start, connect and manage

Use the pinned virtual environment from the implementation runbook. Choose an
absolute runtime directory outside every Git checkout for SQLite snapshots,
optional API-client credentials, service metadata and logs. Copy the [collection plan](../examples/collection-plan.json)
there and edit its region, author and retrieval budgets explicitly. These are
starting coverage settings, not hardcoded market prices or universal model policy.

```sh
.venv/bin/python scripts/local.py start --runtime ABSOLUTE_EXTERNAL_RUNTIME \
  --source-config examples/source-admission.json \
  --collection-plan ABSOLUTE_EXTERNAL_PLAN
.venv/bin/python scripts/local.py status --runtime ABSOLUTE_EXTERNAL_RUNTIME
.venv/bin/python scripts/local.py stop --runtime ABSOLUTE_EXTERNAL_RUNTIME
```

The local URL is `http://127.0.0.1:8000` unless an explicit port is supplied.
The page bootstraps its local browser session automatically. A short-lived,
host-only HttpOnly SameSite Strict cookie authenticates the browser; CSRF stays
only in page memory and accompanies each write. Exact Host/Origin and same-origin
Fetch Metadata protect the local boundary. No API key belongs in the page, URL
or browser storage. Optional API-client keys remain separate from this workflow.

The running backend starts and periodically updates its explicitly configured
approved public scopes. Use `--auto-refresh-config ABSOLUTE_EXTERNAL_SETTINGS`
for reviewed cadence/backoff settings or `--no-auto-refresh` for manual-only
reads. The app installs no system job. See [session and refresh contract](local-session-refresh.md).

The launcher refuses an occupied port and refuses to stop an unrelated process.
It reuses its own ready instance and preserves external snapshots/key on stop.
Stop verifies the owned PID and health instance, requests graceful termination,
and waits at most sixty seconds for actual process exit. A closed listener alone
does not prove exit. If a read still drains, status reports it and replacement
startup stays blocked; no forced termination is sent.
Lifecycle commands share an outside-Git advisory process lock. A competing
command fails safely before process checks or signals, preventing duplicate
starts or termination requests from this helper.
The API remains loopback-only with scoped cookie/CSRF authentication for the
browser and optional Bearer authentication for API clients;
the unauthenticated shell and health endpoint contain no financial data or key.

## Live source roles

| Source | Current role and verification | Important limit |
| --- | --- | --- |
| GetDeploying | Published weekly advertised GPU-hour reference; current complete week selected, attribution retained | Global publisher aggregate; no independent lot, delivery right, local premium or confirmed inventory |
| Azure Retail Prices | Documented unauthenticated internal comparison API; explicit region/SKU/prefix consumption-hour scope, exact retail USD/native node-hour amounts | Price API does not supply GPU model/count or rentable quantity; no automatic GPU-hour normalization or tax/storage/transfer inclusion |
| AWS published prices | Bounded regional Lightsail/ECS/Bedrock/Lambda/S3 native meter tariffs | Tiers, reserved terms, monthly caps and included resources need their own cost model; no GPU mapping or owned inventory |
| OpenRouter Models API | Anonymous scoped current-default model catalog and exact token rates | Conditional workload/time pricing stays unapplied; no provider-pinned quote, inference call or broader archival/resale permission |
| ECB | Attributed published daily reference FX, exact EUR-base quote rates | Informational reference, not an executable settlement/hedge quote; observation date stays separate from capture |
| Hugging Face | Bounded public author/task model metadata, licensing/gating/revision claims retained | No prices, weight downloads, model-use permission or measured technical qualification; limited response is not a complete model universe |
| Hugging Face catalog | Scoped public model/recipe metadata and engine/accelerator labels | No prices, physical GPU count, model-use right or serving qualification |

Index counts come from the live API and change with each source response. Model discovery is bounded and explicitly incomplete. Native retail/listing prices are not verified capacity. Other API candidates remain visible with rights, authentication, instrument or
schema blockers; popularity and a readable URL do not admit a new source.

The [source status](control-plane.md) and [model metadata scope](model-discovery.md)
record primary documentation and rights boundaries. No public repository contains
the live snapshots or client source data. The required metadata/byte limits,
verified TLS with the pinned CA bundle, public DNS pinning, exact endpoint/query
redirect constraints, cooldowns and explicit bounded pagination remain enforced.

## What the browser shows

The top navigation switches between three app views; the logo returns to the Brief. Each view has its own address
(`/#desk`, `/#quotes`, `/#pricing`), so a refresh or the back button lands where you were. The page opens its own
short-lived local session; there is no credential to paste.

- **Brief** (`/`) explains the problem with figures measured on the live simulated book: a quote's price is only part of
  what it costs, because sellers ask for down payments, can fail, and leave terms blank. It then walks through the four
  steps that turn a quoted price into an all-in cost (grade the seller, set the odds of failure, price the risk, rank
  what is eligible) and links to Overview and Quotes.
- **Overview** shows the whole book at a glance: live quotes, GPUs on offer, contract value, the share of quotes that
  are eligible, the market basis (the gap between the lowest quote and the best eligible all-in cost) by GPU model and
  over time, supply and cost by seller grade, quote completeness, provider health, time to expiry and a feed of recent
  moves. The Simulate buttons (price war, supply shock, provider downgrade, pause, reset) change the simulated book so
  you can watch the basis move.
- **Quotes** lists every live quote for one GPU model, ranked by all-in cost or by quoted price. Select a quote to see
  its all-in cost breakdown (price, financing, expected loss), the seller's scorecard, its terms and missing terms,
  and whether it is eligible and why not. **Price this quote** sends that quote to Pricing.
- **Pricing** opens three populated example contracts (strong H100 capacity, balanced L40S terms, weak A4000 capacity
  with hourly restricted escrow) or a blank one. Edit any term, press **Simulate**, and read the assessment: purchase
  ceiling, cost-recovery and margin asks, provider reference rates, the sensitivity surface and the dated cash path.
  The assessment downloads as JSON and as an unsigned, nonbinding compute-services agreement. See
  [pricing demonstrations](pricing-demonstrations.md), [hourly vesting](hourly-vesting.md) and
  [agreement generation](demo-compute-agreement.md).

Overview and Quotes read `GET /v1/book` and `GET /v1/book/desk` every two seconds (conditional requests, paused while the
tab is hidden); the numbers come from the server, the pages only draw them. See [quote book](quote-book.md) and
[desk ledger contract](desk-ledger-contract.md). Pricing reads `/v1/pricing/demo/*`. Vendor text is rendered as text, not
HTML. The shell uses a same-origin content security policy, loads no external asset, and stores nothing in browser
storage. Browser automation environments may block loopback navigation; HTTP, assets, auth, live collection and pricing
can still be verified through the local API.

Earlier builds also had pages for live feeds, market evidence, inventory, underwriting, model policy, inference, dated cash
and portfolio under a More menu. They were removed from the browser. Their API routes are unchanged and documented in
[inventory and policy](inventory-and-policy.md), [underwriting assessment](underwriting-assessment.md),
[portfolio and inference diagnostics](portfolio-and-inference-diagnostics.md) and the contracts below.

## Run the demo

For the demo flow (Brief, Overview, press **Price war** then **Supply shock**, Quotes, **Price this quote**, Pricing),
start the app with the four-scope demo collection plan on a dedicated runtime outside Git:

```sh
DEMO_RUNTIME="${TMPDIR:-/tmp}/computebasis-public-demo"
.venv/bin/python scripts/local.py start --runtime "$DEMO_RUNTIME" \
  --source-config examples/source-admission.json \
  --collection-plan examples/demo-collection-plan.json \
  --auto-refresh-config examples/auto-refresh.json --port 8000
.venv/bin/python scripts/local.py stop --runtime "$DEMO_RUNTIME"
```

The [demo collection plan](../examples/demo-collection-plan.json) schedules GetDeploying, ECB and Energinet DK1/DK2 only.
Pass `--no-auto-refresh` for an offline rehearsal; the simulated book and Pricing still work. If port 8000 belongs to
another service, choose another port; do not replace an unknown listener.

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
distinct manual refresh event and timestamps, so a repeated failure cannot appear
older than an intervening success. Automatic reads reuse the same permission,
transport and persistence checks, coalesce identical active scopes, and report
due/attempt/success/failure state at `/v1/market/refresh/status`. The read-only
index displays updates without changing source dates or granting execution.

Current lookup/display budgets are explicit in the index, not claims of complete
worldwide market coverage. Firm procurement still needs admitted verified physical
offers, complete contracts/buyer demand, independently validated risk inputs and
durable capacity/treasury/execution acceptance described in the broader plan.
