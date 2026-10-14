# ComputeBasis: three-hour demo sprint

Build one convincing flow: **Market → Deal economics → Inventory**. The demo
should show why compute prices need context, why profitable contracts can still
need cash, and how declared capacity changes through time. Use three primary
navigation items, one restrained visual system, and a two-to-four-minute story.

This sprint builds on the public 0.8 curve, power, cash and inventory APIs.
The implementation checklist below states acceptance goals; a plan entry does
not mean its UI work or performance target has already passed. The public repository should remain reproducible from its documented
local startup; a hosted service requires a separately configured deployment.

## Short local runbook

Use Python 3.12 and the repository's pinned environment. From a clean checkout,
install once:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install -e . --no-deps
```

Start the frontend and backend together; no JavaScript build or credential-entry
form is required:

```sh
DEMO_RUNTIME="${TMPDIR:-/tmp}/computebasis-public-demo"
.venv/bin/python scripts/local.py start --runtime "$DEMO_RUNTIME" \
  --source-config examples/source-admission.json \
  --collection-plan examples/demo-collection-plan.json \
  --auto-refresh-config examples/auto-refresh.json --port 8000
.venv/bin/python scripts/local.py status --runtime "$DEMO_RUNTIME"
```

Open `http://127.0.0.1:8000`. Use a new dedicated external runtime for a shared
demo; do not reuse a database holding confidential records. The temporary path
above is suitable for a demo, not permanent storage. Keep the runtime value for
the matching status/stop commands. If port 8000 belongs to another service,
choose `--port 8001` and open that URL; do not replace an unknown listener.
A running instance keeps its original launch settings: stop the instance owned
by this runtime before restarting with a different collection plan.

The [demo collection plan](../examples/demo-collection-plan.json) contains four
scopes across three source roles: GetDeploying and ECB with no filters, plus
Energinet DK1 and DK2 with `rolling_days: 1` and `limit: 1000`. This narrows the
scheduled demo reads; it does not change [source admission](../examples/source-admission.json).
The existing refresh configuration supplies source-specific cadence/backoff.
Energinet refreshes daily and selects the preceding completed Danish calendar
day; its 15-minute delivery intervals are historical wholesale context. The
GetDeploying record represents a completed observation week, and ECB FX is
informational. There are no simulated replacements for failed vendor reads.

For offline preparation add `--no-auto-refresh`; the app can still evaluate
explicit scenarios and synthetic inventory. Do not click source refresh in an
offline rehearsal. To exercise the numerical example without a server, run:

```sh
.venv/bin/python -m compute_pricing.control.cli pricing examples/control-pricing.json
```

Follow the three screens below. Load **Try an invented deal** deliberately,
retain its Synthetic scenario label and inspect the assumptions. An advertised
reference provides context, not admitted physical supply. Unbound synthetic
pricing retains its evidence hold, null submitted bid and disabled execution.
Changing usable cash should change funding feasibility rather than operating
profit. Synthetic inventory is preview-only and cannot become persisted holdings.

End the service owned by this runtime:

```sh
.venv/bin/python scripts/local.py stop --runtime "$DEMO_RUNTIME"
```

Keep attribution, native units and original source timestamps in the recording.
For source use and transformation boundaries see [source adapters](source-adapters.md)
and [electricity costs](electricity-and-compute-costs.md). This runbook contains
no captured vendor payload, credentials, private deal or implied trading mandate.

## What the demo can honestly show

| Screen | Actual data or calculation | Meaning displayed |
| --- | --- | --- |
| Market | Current server-retained GetDeploying weekly advertised commitment marks | Exact model, billing term, reservation tenor, USD conversion basis and completed observation week; global aggregate with unknown physical location/capacity. |
| Market context | ECB informational FX and Energinet day-ahead power references | Separately attributed native units and timestamps. Electricity references remain wholesale MWh prices, not a site tariff or GPU price. |
| Deal economics | Explicit caller inputs evaluated by the existing pricing/cash engines | Scenario costs, margin, selling floor, funding constraint and cash path. Unbound evidence stays held and `bid` stays null. |
| Inventory | Existing server inventory evaluator and offline geographic geometry | Declared or clearly marked synthetic units, sold/reserved/available states and contract intervals. Market listings never become holdings automatically. |

The shared MVP displays the three sources above with their attribution and
source references. Other approved anonymous feeds can keep their existing
backend catalog roles; leave them off shared demo screens until their particular
redisplay purpose is explicit. This changes presentation, not source admission.
Do not add licensed index prints or imply that event-contract values are GPU
prices. Source counts and timestamps must come from the API, never fixed cards.

## The three screens

**Market.** Start here instead of a separate Overview. Put hardware and native
billing filters above a compact commitment dot plot. Show observed tenor nodes;
do not smooth missing tenors into prices. A small table below gives the exact
rates, units, completed week and source. Put capture time and source freshness
in a narrow evidence strip. Selecting a node opens its source/term details and
offers **Compare a deal**. A selected advertised reference stays a comparison
reference; it does not populate verified supplier capacity, region or rights.

Keep FX and power in a compact context drawer. Power can show retained delivery
intervals and signed native prices with their area. Do not combine the currencies
or blend wholesale prices into compute rates. Keep most source administration,
policy, inference, underwriting and research controls in an advanced drawer,
outside the main demo navigation.

**Deal economics.** Use a short commercial form on the left and results on the
right. Visible inputs: GPU count, delivery dates, supplier rate, buyer rate,
billed GPU-hours, collection assumption, opening usable cash, payment dates and
required margin. Expand fees, operating costs, capital, advance/refund terms,
scenario reference and ownership evidence under **Assumptions and terms**.
Empty is unknown. Explicit zero and false remain distinct from empty.

Offer **Try an invented deal** as a deliberate action. Keep a persistent
**Synthetic scenario** label beside the form and results, with all assumptions
inspectable. Do not silently insert an example into an empty live state.
Changing buyer inputs must regenerate a consistent full invoice, revenue
recognition, receipt and any noncash writeoff. Usable advances remain liabilities;
their receipt and later application cannot be counted as two collections.

Show four primary results: **Scenario funding ceiling**, **Scenario selling
floor**, **Profit at supplied supplier rate**, and **Additional cash required**.
Use backend `caps`, `cash_constraint.tested_purchase_tick`, `ask`, `economics`
and the selected cash schedule. If the funding result is absent or infeasible,
show that state instead of inventing a number. Keep the API evidence hold visible;
never relabel a hypothetical ceiling as a submitted or live buy bid. A daily cash
chart and compact cost breakdown explain the result. Updating opening cash should
change funding feasibility while leaving operating profit unchanged.

**Inventory.** Put the map beside a short lot list and a selected-lot timeline.
Use existing server counts, separated by physical unit kind. Show available,
reserved, sold and maintenance states with text as well as color. “Unsold” means
available plus reserved plus maintenance within active availability; it does not
mean immediately rentable. Unknown locations belong in an unmapped list.

An explicitly selected synthetic inventory can be explored and re-evaluated at
another UTC instant. If time permits, allow **Preview reservation** to update a
synthetic draft and call the evaluator. It must stay a preview with no persisted
holdings or purchase. Saving declared paper inventory remains a separate explicit
action. Do not build an automatic deal-to-inventory transaction in this sprint.

## Exact API wiring

| Purpose | Endpoint and response used |
| --- | --- |
| Workspace | `POST /v1/session/bootstrap`; existing same-origin cookie/CSRF client. No bearer-key form. |
| Read demo sources | `GET /v1/demo/market`; bounded configured GetDeploying/ECB/Energinet display, source/snapshot/observation/coverage metadata and `commitment_curves`. The full index remains an advanced read. |
| Commitment marks | `GET /v1/demo/market` → `commitment_curves` for the focused display; separated native groups/nodes/references/exclusions. `GET /v1/market/curves` remains available for the full configured scope. |
| Feed status | `GET /v1/market/refresh/status`; active scope status, attempt/success and retry state. A running scheduler alone is not “reading feeds.” |
| Scenario pricing | `GET /v1/demo/contract` supplies empty inputs and an opt-in invented example. `POST /v1/demo/scenario` expands the explicit compact terms into the existing pricing and treasury models, preserves the provenance hold and immutable result envelope, and includes `scenario_supplier_cash_schedule` at the caller's supplier rate. The advanced packet endpoint remains available. |
| Cash details | `GET /v1/cash/contract`, `POST /v1/cash/evaluate`, `POST /v1/cash/calendar`; native accounting and explicit calendar rules. |
| Optional power comparison | `GET /v1/power/contract`, `POST /v1/power/from-reference`; selected retained delivery intervals and declared load profile. Reference output remains held for unverified site tariff. |
| Optional declared term study | `GET /v1/curves/contract`, `POST /v1/curves/evaluate`; matching dated cohorts and distinct interval arithmetic, not a forward forecast. |
| Inventory | `GET /v1/inventory`; `POST /v1/inventory/evaluate` with `{state, as_of}` for synthetic previews. |

Frontend synchronization reads retained data. It does not call vendor APIs from
the browser or trigger a new collection on every input edit. Retain the previous
good display during background reads and display failures/expiry explicitly.
Keep observation week, source capture, index as-of and browser synchronization
time distinct. Preserve drafts while background data arrives; re-evaluate only
on the user's action. Repeated refresh clicks must use the existing coalescing
and source cooldowns.

The demo read selects the latest immutable record for each configured display
scope through an indexed query. It verifies the selected records and applies
current permissions and age limits. Its coverage describes this explicit display
population; it does not certify unrelated history, complete market coverage or
benchmark weights. Curves preserve the server's fractional capture timestamps.

## Priority blockers and file targets

1. **Market-read latency is the first backend task.** A full retained-history
   scan is too slow for an interactive first frame. Add a bounded current-scope
   projection/read path or reuse a validated display projection, with current
   permission/freshness checks, exact snapshot references and explicit omitted
   scope/truncation metadata. Profile before and after. Do not change
   `PricingProvenance`, estimator weighting or benchmark admission to gain speed.
   Targets: `src/compute_pricing/control/api/market.py`,
   `src/compute_pricing/control/reporting/store.py`,
   `src/compute_pricing/control/api/app.py`.
2. **Replace nine primary tabs with three workflows.** Preserve advanced
   functionality behind a drawer and keep DOM bindings coherent; simply deleting
   elements referenced by `byId()` can break startup. Carry forward the existing
   centered container, typography, theme tokens, precise numeric presentation,
   loading placeholders and truthful refresh-state treatment. Synchronize the
   frontend work with the current backend before integration.
   Targets: `src/compute_pricing/control/workbench/assets/index.html`,
   `workbench.css`, `workbench.js`, `workbench-drafts.js` in that same directory.
3. **Connect a compact commercial form to a consistent cash packet.** The older
   shorthand of invoicing only expected collections is incompatible with native
   net-billing reconciliation. Keep full service billing/recognition, explicit
   receipts and noncash loss. Use a small typed adapter only if needed; do not
   rewrite financial kernels or fabricate hidden risk/source inputs.
   Targets: the workbench draft builder and, if justified,
   `src/compute_pricing/control/api/demo.py`; existing
   `pricing/engine.py`, `pricing/liquidity.py`, `treasury/payload.py` are the
   authoritative calculations.
4. **Render scenario diagnostics without weakening the evidence boundary.**
   Synthetic and unbound requests correctly receive an evidence hold and no
   submitted bid. That is expected behavior, not an error to disable for filming.
   Targets: result rendering in `workbench.js`; preserve
   `src/compute_pricing/control/api/provenance.py`.
5. **Keep map interaction small and server-backed.** Reuse packaged geography,
   the existing inventory validator and returned timeline/counts.
   Targets: workbench map rendering, `examples/synthetic-inventory.json`,
   `src/compute_pricing/control/inventory/model.py` and `inventory/routes.py`.

## Three-hour execution schedule

| Time | Frontend owner | Backend owner | Integration owner |
| --- | --- | --- | --- |
| 0–15 min | Agree on three views, stable DOM/API contracts and one visual system. | Profile index/curve reads; confirm current source scopes and DTOs. | Freeze the demo script and choose the current tested baseline. |
| 15–60 min | Build Market and compact Deal layouts; reuse session client and theme tokens. | Implement the bounded display read and typed deal-packet assembly; focused correctness checks. | Prepare independently invented sample inputs and source attribution. |
| 60–105 min | Wire market points, scenario result cards, cash chart and inventory selection. | Verify source timestamps/expiry, dynamic gross/receipt/writeoff identity, funding and result DTOs. | Integrate stable changes; confirm no draft overwrite or automatic fake live fallback. |
| 105–140 min | Polish all three views, keyboard controls, mobile layout and loading/error states. | Resolve actual functional failures; keep optional power/term insets behind the timebox. | Run appropriate offline/backend/frontend checks and rehearse the complete flow. |
| 140–165 min | Fix the most visible or blocking issue; stop adding screens. | Freeze financial/API changes after passing checks. | Review the exact public tree for credentials, private content and raw payloads; publish the clean generalized release. |
| 165–180 min | Final visual check and short recording. | Confirm clean startup, retained-feed status and repeatable scenario results. | Record the two-to-four-minute demo and share the public repository/run instructions. |

One owner handles each file group; avoid concurrent edits to API or workbench
entry points. No additional audit-only workers, framework migration or new vendor
account is needed. Existing tests plus focused regressions for changed behavior
are the acceptance gate. Keep credentials and runtime data outside Git.

## A three-minute recording

| Time | Action | Narration and proof |
| --- | --- | --- |
| 0:00–0:40 | Open Market; select a hardware/billing cohort and inspect two tenor points. | “Compute is not a standardized commodity. These are retained advertised references with their original terms and observation week.” Show exact source/unit/time and missing tenors. |
| 0:40–1:15 | Choose **Compare a deal**, then explicitly load the invented deal. | “The reference is context. Contract terms and cash are separate inputs.” Show the synthetic label, supplier/buyer terms and collection/payment assumptions. |
| 1:15–2:00 | Evaluate; point to profit and the supplier-rate funding shortfall. Change usable opening cash and evaluate again. | “A positive margin does not fund the signing payment.” Show the cash trough moving while operating profit stays unchanged. Explain the scenario ceiling and visible evidence hold; no live bid is submitted. |
| 2:00–2:40 | Open Inventory; explicitly load the synthetic map, select a lot and change the UTC instant. | “Capacity is tracked by physical units and contract windows.” Show available/reserved/sold counts and the corresponding timeline. Unknown locations stay unmapped. |
| 2:40–3:00 | Return to the selected market node and evidence strip. | “Every result retains its inputs, source timestamps and model version.” Close on the public repository and a repeatable local start. |

For a two-minute cut, omit the optional context drawers. For four minutes, add
one wholesale-power comparison and explain its tariff hold; do not add a hedge
claim or trade. Keep research derivatives, model qualification, policy editing,
financing and securitization outside this first recording.

## Done means

- A clean checkout starts the backend and frontend with the documented command;
  the workspace opens automatically without pasting credentials.
- All three workflows work end to end with clear loading, empty, stale and
  rejected states. Current market data never silently becomes a synthetic case.
- A quick warmed market read is targeted below one second; initial loading is
  explicit if startup projection work remains. Coverage bounds remain visible.
- Editing buyer terms maintains complete native accounting; editing cash changes
  funding rather than inventing operating profit. Exact money stays on the backend.
- Synthetic inventory stays a preview and cannot be saved as actual holdings.
- Dark/light themes, 390px mobile layout, keyboard focus, long numeric values and
  the absence of horizontal page overflow are checked across all three views.
- Appropriate changed-code checks pass; the exact public release contains no
  credentials, private identities/data/history or raw vendor records.

Stop at that result. It is a useful, demonstrable MVP; broader calibration,
verified counterparty credit, executable bids, authoritative reservations and
financial execution remain future work.
