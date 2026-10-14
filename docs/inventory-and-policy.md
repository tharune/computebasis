# Inventory, policy and source workspace

This release adds persistent local paper inventory, a geographic and timeline
view, versioned benchmark/feature policies and expanded documented public price
discovery. An external tariff remains market evidence; it never creates an owned
unit, sale, reservation, contract or verified asset.

## Track physical units and positions

The authenticated `/v1/inventory` API stores the caller's complete declared plan.
Sites have explicit optional geographic coordinates; lots have named physical
unit IDs, unit kind and UTC availability; positions reserve, sell or maintain
particular units over half-open intervals. Unknown location stays unlocated.
GPU, node, CPU and other accelerator counts are reported independently.

At the selected UTC instant, active units are classified as available, reserved,
sold or under maintenance. Units with no active availability are unavailable.
Unsold means available plus reserved plus maintenance within active availability;
it is broader than immediately available capacity. The interval end belongs to
the next state, so adjacent reservations do not double sell a unit.

Each replacement requires the current integer `expected_revision`. SQLite
`BEGIN IMMEDIATE` serializes the compare-and-swap; competing replacements return
a conflict, while identical retries replay exactly one revision. Reload and
merge before retrying. Removed holds and lots remain in immutable historical
revisions. Audit metadata and adjacent links are checked over the explicitly
bounded history; a selected revision's state is verified on replay.

`as_of` evaluates the selected declared plan revision. It does not reconstruct
what an operator knew at a past instant. A historical plan must be selected
explicitly to replay that state. Declared purchase and sale values retain their
full-record basis and separate currencies; they are not net exposure, earned
revenue, dated cash or market marks. Financial execution remains disabled.

| Route | Contract |
| --- | --- |
| `GET /v1/inventory?as_of=UTC_SECOND_Z` | Latest plan with map, unit/status, timeline and bounded audit data |
| `PUT /v1/inventory` | Exact `{expected_revision,state}`; durable local paper replacement |
| `GET /v1/inventory/revisions/{revision}` | Explicit immutable plan replay |
| `POST /v1/inventory/evaluate` | Exact `{state,as_of}`; pure draft/demo evaluation with no persistence |

The browser keeps an explicitly loaded invented demo separate from saved
inventory. Saving a declared plan is a separate action. Local plan reloads
do not read external feeds. The site map uses packaged Natural Earth land
geometry, with no third-party tiles, location lookup or marker transmission.

An optional state `provenance` is `declared` or `synthetic`. Pure preview accepts
the synthetic marker; persistent writes refuse it before a revision is created.
Absent legacy markers are preserved in normalized state so historical hashes
continue to verify, and are reported as `unspecified`. Provenance is a caller
claim, never proof of ownership. Sold positions without `contract_id` remain
editable paper declarations and appear in
`position_evidence.sold_position_ids_without_contract`; even supplied contract
references remain unverified and grant no execution permission.

## Customize controls without silent model changes

`/v1/policies` stores immutable policy versions outside Git. Each document has a
shared `PolicySnapshot`, typed `feature_definitions` and bounded notes. The
benchmark controls expose estimator, source quality, freshness/half-life,
source/provider caps and support thresholds. Feature definitions declare type,
unit, bounds/categories, requiredness, owning path and model ownership.

Policy saves require the predecessor revision hash and an increasing semantic
version. Feature-definition changes also require a successor registry version.
Weights-only changes may retain the registry version. Duplicate keys, invalid
Unicode, floats in weight controls, unknown benchmark parameters and
unregistered critical feature IDs refuse before storage. Identical saves are
idempotent; existing versions cannot be overwritten.

Saving/validating a policy does not grant source access or activate a new price,
loss or regional coefficient. Weights remain caller-supplied, uncalibrated
controls. Applying a saved policy explicitly edits a pricing draft and requires
a new evaluation. Critical features still hold when their owning monetary model
has not been independently qualified.

| Route | Contract |
| --- | --- |
| `GET /v1/policies` | Bounded immutable versions, dynamic source catalog and feature types/paths |
| `GET /v1/policies/{revision}` | Exact saved configuration replay |
| `POST /v1/policies/validate` | Exact `{document}`; pure configuration validation |
| `POST /v1/policies` | Exact `{expected_revision,document}`; immutable save or conflict |
| `POST /v1/requests/parse` | Strict JSON-only editor boundary; no semantic pricing approval, evaluation or persistence |

## Broader source discovery

Collection scopes are explicit editable JSON. Azure supports region, exact SKU
or an explicit compute SKU prefix. AWS public regional service catalogs retain
native meters and contract ranges. CPU-hours, memory-hours, monthly bundles and
tokens remain distinct from GPU-hour evidence and physical inventory.
Current adapters and admission boundaries are recorded in the
[source status](source-adapters.md). Rights-pending candidates
remain visible with concrete blockers; source-rule enablement cannot bypass
those gates. No automatic collector or external execution job is installed.

See [third-party notices](third-party-notices.md) for local map data.
Offline tests use independently invented plans, exact decimal policies and
source-shaped synthetic responses. Browser checks exercise the actual handlers
and HTTP APIs using a separate invented-data service with external transport
disabled. Release candidates require the complete offline suite and independent privacy/numerical review.
