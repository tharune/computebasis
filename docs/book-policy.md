# Simulation book policy

The independent quote book supports configurable quality factors and financing
assumptions. Preview a complete replacement against the current synthetic book,
then commit it with an explicit predecessor revision. These operations never
collect market data, admit source evidence, verify inventory or enable execution.
The illustrative defaults are uncalibrated assumptions, not estimated failure
probabilities or validated underwriting thresholds.

The [book model](../src/compute_pricing/control/quote_book/market.py) owns its
configuration and revision history. The
[policy helper](../src/compute_pricing/control/api/book_policy.py) validates the
document and exposes authenticated routes.

| Route | Result |
| --- | --- |
| `GET /v1/book/policy/contract` | Complete field contract and resolved defaults |
| `GET /v1/book/policy` | Current document, revision and history summaries |
| `GET /v1/book/policy/revisions/{revision}` | Detached historical configuration record |
| `POST /v1/book/policy/evaluate` | Pinned before/after comparison; no state mutation |
| `PUT /v1/book/policy` | Compare-and-set commit or an exact retry |

Browser writes require an authorized `book` session scope, the configured exact
origin and host, Fetch Metadata checks, and `X-Compute-CSRF`. The preview is a
POST and requires the same protection. Bearer authentication remains available
for configured local clients. Follow the existing
[backend/frontend handshake](backend-frontend-handoff.md) for deployment.

## Complete document

Read the current `record.document`, copy it, edit the intended fields, and send
the entire document. Updates and previews accept exactly:

```json
{
  "expected_revision": 0,
  "document": {
    "schema_version": "book-policy/1.0",
    "policy_id": "independent-simulation",
    "version": "1.1.0",
    "scorecard": {
      "label": "Illustrative quality comparison",
      "weights": {
        "certification": "0.20", "dc_tier": "0.10", "sla": "0.25",
        "delivery": "0.15", "credit": "0.20", "responsiveness": "0.10"
      },
      "grade_bands": {"A":"90", "B":"75", "C":"60", "D":"0"},
      "grade_premiums": {"A":"0.005", "B":"0.017", "C":"0.041", "D":"0.083"},
      "rating_scale": {"minimum":0, "maximum":4, "higher_is_stronger":true}
    },
    "economics": {
      "label": "Illustrative financing sensitivity, not calibrated risk",
      "deposit_apr": "0.12",
      "annual_failure_probability": {"A":"0.008", "B":"0.024", "C":"0.061", "D":"0.173"},
      "recovery_fraction": "0.35"
    }
  }
}
```

The example contains invented assumptions and commits only against revision zero.
Use the current document and revision for subsequent changes. Financial values
are finite plain decimal **strings**, including fractions and thresholds.
Floats, null required values, extra keys and partial replacements are rejected.

| Object | Required fields and constraints |
| --- | --- |
| `scorecard` | `label`, `weights`, `grade_bands`, `grade_premiums`, `rating_scale` |
| `weights` | Exactly `certification`, `dc_tier`, `sla`, `delivery`, `credit`, `responsiveness`; each in `[0,1]`; exact sum `1` |
| `grade_bands` | Exactly `A`, `B`, `C`, `D`; `100 >= A > B > C > D = 0` |
| `grade_premiums` | Exactly `A`, `B`, `C`, `D`; each in `[0,1]` |
| `rating_scale` | Exactly `{"minimum":0,"maximum":4,"higher_is_stronger":true}` |
| `economics` | `label`, `deposit_apr`, `annual_failure_probability`, `recovery_fraction` |
| `deposit_apr`, `recovery_fraction` | Each in `[0,1]` |
| `annual_failure_probability` | Exactly `A`, `B`, `C`, `D`; each in `[0,1]` |

Labels must be explicit bounded text. Documents are limited to 16 KiB. A policy
identity stays fixed for the book instance. Versions use bounded
`major.minor.patch`; a committed successor must increase numerically. Changing a
factor weight does not fill a missing provider rating, even when that factor has
zero weight. Unknown ratings retain an unknown grade and held economics.

## Preview and commit

The preview compares the current cached quote population under the current and
candidate policies at the same simulation tick, epoch and assessment date. It
does not read the wall clock, advance time, move prices, consume random numbers
or change the ETag. Its context is explicit; it is not a reservation of the book
state. Ordinary book reads and controls may subsequently advance the simulation.

Comparisons contain before/after KPIs and model summaries, provider changes and
bounded quote changes with exact decimal deltas. Unknown cost inputs produce
null deltas. The two cost models remain alternatives: exposure cost uses the
declared failure/recovery assumptions, while scorecard cost uses the declared
grade premium. Both include deposit financing; their risk charges are never
added together. Actual calendar terms and the model's existing unit labels apply.

Commit requires `expected_revision` to match the current revision. Validation and
comparison finish before the model changes. A successful commit increments the
revision, recomputes current economics without changing native quote prices, and
appends a history point at the same synthetic time. `meta.policy_revision`,
`meta.policy_version`, `policy.document` and `series.policy_revisions` identify
the effective configuration; the book ETag changes. Deal clients must refresh
their book selection after an ETag change.

An exact retry of the latest normalized document with its current revision or
immediate predecessor returns `changed:false`. It does not create a revision or
history point. Another stale write returns HTTP 409
`book_policy_revision_conflict`. Invalid documents return HTTP 422
`invalid_book_policy`; absent historical revisions return HTTP 404.

## History and lifetime

Revision zero is the resolved initial document. Records contain their predecessor,
tick, epoch and synthetic application time, and returned values are detached.
Book reset restores the synthetic population and series while preserving the
current policy and its earlier configuration records. Old series points and
already saved paper calculation receipts are not rewritten by a policy update.

The process retains at most 64 configuration records, including revision zero;
the next commit returns HTTP 409 `book_policy_history_capacity` without deleting
history. This configuration history is process memory only and is lost on server
restart. A historical policy record is not a historical quote snapshot or a
durable replay facility. Every result remains explicitly simulated, with source
evidence, firm eligibility and execution disabled.
