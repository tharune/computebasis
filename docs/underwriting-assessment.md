# Underwriting evidence coverage

ComputeBasis provides a separate checklist for the inputs needed to assess
compute supply, buyers, offtake, inference, cash, hedging and securitization.
The checklist answers **which declared requirements have current qualifying
evidence pointers**. It does not determine a supplier's creditworthiness,
approve a privacy claim, authenticate an artifact or change a price.

The neutral starting catalog has 112 entries across 17 groups. Each entry
contains a description of its related variables and explicit scope, subject,
type, unit, ownership and evidence requirements. It contains no provider facts,
personal identities, market prices, calibrated coefficients or default holdings.
The catalog is a starting point rather than an exhaustive legal/financial policy.

## Use the local interface

1. Open the local workspace and its Underwriting view. The browser establishes
   a scoped local session; explicit API clients can use their configured bearer key.
2. Load the neutral template explicitly. Select the relevant scopes and supply
   real reviewed subject IDs outside Git: transaction, supplier, buyer, site,
   lot, workload, market, portfolio and any relevant instrument/facility/issuer.
3. Edit the request's requirements and evidence. Retain unfamiliar material
   questions as gaps. Record explicit reviewed reasons for allowed N/A decisions.
4. Assess the declared coverage and inspect every blocker/reference finding.
   Resolve evidence gaps separately from whether a known value is acceptable.

The available initial scopes are `inference`, `resale`, `forward`, `hedging` and
`securitization`. Additional scopes and requirements can be supplied explicitly;
a selected scope with no required requirements returns a hold. Change the
declared requirements version when changing the reviewed checklist. The exact
normalized requirement hash and input hash identify its actual contents.

Covered is an input-completeness concept. A current report of an adverse fact
may be covered while the transaction still fails a substantive policy. A known
false boolean and an explicit zero are real inputs; neither means a favorable
condition. Missing, claimed, invalid, expired, conflicted or wrong-subject data
does not silently qualify a required entry.

## API contract

All routes authenticate before parsing an assessment body. Explicit API clients
use `Authorization: Bearer <configured-api-key>`. The same-origin local browser
uses its HttpOnly session cookie and CSRF header on writes. Credentials are not
parameters or fields in the assessment.

| Route | Behavior |
| --- | --- |
| `GET /v1/underwriting/template` | Returns a detached neutral catalog, scope options and an unfilled `request` skeleton. It performs no collection or persistence. |
| `POST /v1/underwriting/assess` | Accepts a bounded raw JSON request; returns a direct assessment object, without the financial endpoint's snapshot envelope. It performs no collection, document persistence or monetary calculation. |

The template's `request_id` and `as_of` are null, and its scopes, subjects and
evidence are empty. Fill them explicitly; the unfilled skeleton is deliberately
not a valid completed assessment. JSON duplicate keys, nonfinite numbers and
oversized/deep input are rejected. Decimal/integer feature values and bounds
are exact decimal strings; floats, booleans-as-numbers and exponents cannot
stand in for financial or numeric feature values.

A minimal independently invented custom request illustrates a held result:

```json
{
  "schema_version": "underwriting-assessment/1.0",
  "request_id": "request:invented-review",
  "as_of": "2035-02-01T00:00:00Z",
  "requirements_version": "1.0.0",
  "scopes": ["resale"],
  "subjects": {"lot": "lot:invented-example"},
  "requirements": [
    {
      "requirement_id": "hardware:count",
      "ownership_id": "hardware:count",
      "group": "hardware",
      "title": "Accelerators per node",
      "description": "Positive whole usable count supported by reviewed inventory evidence.",
      "scopes": ["resale"],
      "required": true,
      "value_type": "integer",
      "unit": "accelerators_per_node",
      "minimum": "1",
      "subject_kind": "lot",
      "owning_path": "constraint",
      "owner_model": "underwriting:hardware",
      "evidence_scope": ["hardware:count"],
      "allow_not_applicable": false
    }
  ],
  "evidence": []
}
```

This is a single-requirement contract example, not a full supplier checklist or
real inventory. It returns `held`, `required_total: 1`, `required_blocked: 1`
and `missing_requirement_evidence`. Use the full catalog for an actual review
rather than treating this abbreviated example as sufficient diligence.

## Requirement and evidence fields

| Requirement field | Meaning |
| --- | --- |
| `requirement_id`, `group`, `title`, `description` | Canonical identity and human-readable question; descriptions enumerate closely related variables. |
| `ownership_id` | Optional canonical input ownership ID, defaulting to `requirement_id`. Duplicate ownership/requirement IDs are rejected. |
| `scopes`, `required` | Which declared activities require this input. Optional gaps remain visible but do not count as required blockers. |
| `value_type`, `unit`, `minimum`, `maximum`, `allowed_values` | Explicit typed/bounded/category contract. Supported types are decimal, integer, string and boolean. No unit or currency conversion occurs. |
| `subject_kind` | Key into the request's subject mapping. Evidence must name that exact subject ID. |
| `owning_path`, `owner_model` | Declared price/cost/loss/constraint/diagnostic ownership. Registration does not activate a monetary effect. |
| `evidence_scope`, `allow_not_applicable` | Required artifact scope and whether a reviewed N/A rationale is allowed. |

Each evidence entry has `requirement_id`, `subject_id`, `status`, `value`, `unit`,
`valid_from`, `valid_until`, `reviewed_by`, `evidence` and optionally
`not_applicable_reason`. Supported declared statuses are `declared`, `verified`,
`missing`, `stale`, `conflicted`, `invalid` and `not_applicable`. A claimed
`verified` entry failing qualification is reported as `unverified`, or `stale`
when its validity/artifact rights have expired. Unselected entries are
`out_of_scope`; unused supplied evidence IDs are listed separately.

To count as current caller-verified coverage, an entry needs a valid typed
value/unit, current half-open UTC validity interval, exact subject and reviewer.
At least one domain `EvidenceRef` must provide:

- A canonical artifact/source identity, artifact SHA-256 and verifier.
- Nonfuture access/event dates and explicit future expiry at the selected as-of.
- All registered evidence scopes plus `subject:<subject_id>` in artifact scope.
- Caller-qualified allowed observe/retain rights and a rights reviewer, with
  no expired permission. Financial benchmark/execution rights are not granted.

The artifact hash and review IDs are **pointers and caller assertions**, not
cryptographic identity validation, a legal opinion or proof of report contents.
Conflicting content under the same evidence ID is rejected; a consistent
multi-scope artifact can support more than one reviewed input. A report badge
with the wrong site/service/subject does not satisfy the required scope.

N/A also requires the requirement to permit it, a null value, a nonempty stated
reason, review owner and the same current scoped evidence. The software cannot
judge whether that reason is substantively justified; accountable independent
review remains necessary. Removing a question is not the same as demonstrating
that it is inapplicable.

Unknown record fields are retained in the request hash and warned as unused
extensions. They do not secretly become requirements, weights, formulas or
permissions. Add a typed requirement explicitly to have a new factor assessed.

## Result interpretation

The direct response includes `status`, `rows`, `blockers`, `unused_evidence_ids`,
warnings, model/schema/requirements versions and deterministic
`requirements_hash`, `input_hash` and `assessment_hash`.

`summary` reports `required_total`, `required_covered`,
`required_not_applicable`, `required_blocked`, `optional_total` and `by_status`.
All row values retain native units. Each row includes its subject/ownership,
status/blockers, qualifying evidence IDs, and per-reference evidence findings.
Counts are not percentages of institutional readiness or calibrated confidence.

`complete_for_declared_requirements` means no required gap remains for the exact
declared checklist at its as-of. It is not a firm quote, legal/security approval,
credit rating or assertion that every possible risk was considered. The response
always sets `execution_enabled: false`, `monetary_effects_enabled: false` and
`persisted: false`. Financial kernels continue to apply their own explicit
inputs and holds; this diagnostic does not replace them.

The request can contain sensitive diligence. Use evidence pointers and minimized
review summaries, avoid copying source documents/customer content into editors
or Git, and use the separately approved evidence storage/access/retention process.
The pure endpoint stores no submitted documents; it is not that evidence store.

Offline `test_underwriting_v6.py` covers current/stale/unknown/subject/type/unit/
rights/N/A behavior, custom catalogs and extensions, duplicate identities,
exact decimal strings, authentication and strict JSON. These tests verify the
diagnostic boundary, not real documents or production eligibility.
