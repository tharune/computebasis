"""Neutral diligence catalog, without provider facts or calibrated coefficients.

This is a versioned starting checklist. Callers explicitly choose scopes and
may add, remove or change requirements in a separately versioned request.
"""
from copy import deepcopy

from .engine import SCHEMA_VERSION, SCOPE_OPTIONS

REQUIREMENTS_VERSION = "1.0.0"
CORE = ("inference", "resale", "forward")
ALL = SCOPE_OPTIONS


def _group(group, subject, scopes, fields, *, path="constraint", allow_na=True):
    rows = []
    for field in fields:
        key, title, description, *numeric = field
        identity = group + ":" + key
        row = {"requirement_id": identity, "ownership_id": identity, "group": group,
               "title": title, "description": description, "scopes": list(scopes),
               "required": True, "value_type": "decimal" if numeric else "string",
               "unit": numeric[0] if numeric else None, "subject_kind": subject,
               "owning_path": path, "owner_model": "underwriting:" + group,
               "evidence_scope": [identity], "allow_not_applicable": allow_na}
        if numeric:
            row["minimum"] = "0"
            if numeric[0] == "fraction":
                row["maximum"] = "1"
            if numeric[0] == "accelerators_per_node":
                row.update(value_type="integer", minimum="1")
        rows.append(row)
    return rows


_REQUIREMENTS = []
_REQUIREMENTS += _group("attribution", "transaction", ALL, (
    ("legal_roles", "Contracting roles", "Identify supplier, buyer, broker, guarantor, issuer, servicer and operating legal entities separately."),
    ("rights", "Evidence use rights", "Observe, retain and disclose permissions, retention/minimization policy and access owner for each evidence artifact."),
    ("provenance", "Input attribution", "Distinguish observed, measured, contracted, forecast and synthetic inputs; retain source/version/hash/locator."),
    ("review", "Independent review and mandate", "Record reviewer, exceptions, intended entity/account/product and mandate; coverage itself grants no mandate."),
), allow_na=False)
_REQUIREMENTS += _group("supplier", "supplier", CORE, (
    ("identity", "Supplier legal identity", "Registration, jurisdiction, signatory authority and beneficial ownership; resolve immutable identities."),
    ("group", "Supplier related-party group", "Related entities, parent/broker/operator relationships and concentrated economic exposure."),
    ("ownership_chain", "Owner/operator/reseller chain", "Underlying supply/site agreements, subleasing/resale consent, asset title and enforceable capacity entitlement."),
    ("asset_identity", "Physical inventory identity", "Canonical lot/node/accelerator identifiers and duplicate/reseller lineage, not advertised quantity alone."),
    ("financials", "Supplier financial condition", "Dated statements, liquidity, debt, leverage, disputes, references and financial evidence freshness."),
    ("prepayment_exposure", "Supplier advance exposure", "Dated at-risk prepayments, recoverability, default timing and net replacement/delivery exposure."),
    ("guarantee", "Supplier credit protection", "Guarantee, collateral, insurance, enforceability, exclusions, recoveries and time to cash; no invented PD/LGD."),
    ("delivery_history", "Supplier delivery track record", "Observed promised/actual starts, shortfalls, causes, failure durations, claim outcomes and measurement windows."),
))
_REQUIREMENTS += _group("facility", "site", CORE, (
    ("identity", "Facility identity and jurisdiction", "Actual site, country/subdivision/locality, site rights and immutable facility identity."),
    ("tier", "Facility tier evidence", "Certification/assessment scope, validity and limitations rather than a claimed tier badge."),
    ("power", "Power and grid dependencies", "Contracted power, redundancy, tariff/pass-through, shared grid and usable power envelope."),
    ("cooling", "Cooling and thermal envelope", "Cooling specification, thermal limits, throttling and actual acceptance evidence."),
    ("maintenance", "Maintenance and spares", "Planned/unplanned maintenance, spare inventory, repair resources and supply availability intervals."),
    ("carrier", "Carrier and disaster dependencies", "ISP/carrier/site hazards, shared failure groups, diverse paths and tested continuity."),
    ("energy_requirements", "Buyer environmental requirements", "Any required energy/emissions/disposal attributes and independently supported costs; no automatic premium."),
))
_REQUIREMENTS += _group("hardware", "lot", CORE, (
    ("sku", "Exact accelerator SKU", "Manufacturer, full model revision, generation, PCIe/SXM/rack shape and serial or attested asset identity."),
    ("memory", "Usable accelerator memory", "Per-device VRAM, allocation/MIG/vGPU constraints and usable measured capacity.", "GiB"),
    ("count", "Accelerators per node", "Positive whole usable accelerator count and complete-node allocation boundary.", "accelerators_per_node"),
    ("health", "Hardware health and burn-in", "Age, sustained burn-in, ECC/Xid/failure history, power caps, firmware and thermal condition."),
    ("interconnect", "GPU interconnect and topology", "NVLink/NVSwitch/peer-to-peer, fabric, topology, RDMA/NCCL and measured usable bandwidth."),
    ("cpu", "CPU and NUMA shape", "CPU architecture/model/core count and NUMA placement accepted for the workload."),
    ("ram", "Host memory", "Usable host RAM, bandwidth, isolation and model loading requirements.", "GiB"),
    ("storage", "Storage specification", "NVMe capacity, IOPS, throughput, persistence, encryption, snapshot and transfer/loading constraints."),
    ("network", "Network specification", "Usable ingress/egress/east-west bandwidth, NIC count, latency, IP and transfer billing boundaries."),
    ("software", "Software and image restrictions", "Pinned drivers, firmware, runtime/container, privilege/image restrictions and license rights."),
    ("acceptance", "Hardware acceptance", "Independent workload replay, health/network/storage tests, burn-in, sign-off and payment-release conditions."),
))
_REQUIREMENTS += _group("operations", "supplier", CORE, (
    ("access", "OOB and administrator control", "IPMI/OOB access, key custody, permitted privileges, power-cycle/reimage and recovery rights."),
    ("support", "Support and escalation", "Written response/repair times, named accountable escalation role, coverage hours and parts runbook."),
    ("promised_uptime", "Contracted availability", "Promised SLA as a declared fractional quantity with contractual exclusions and measurement rule.", "fraction"),
    ("measured_uptime", "Measured availability", "Observed availability and incidents over a known period, independently of promised SLA.", "fraction"),
    ("remedies", "Realizable outage remedies", "Credits/cash damages, claim deadlines, liability caps, cure rights and recovery lag."),
    ("recovery", "Tested recovery and step-in", "Authorized access, replacement pool, model/data transfer, failover, acceptance and funded restoration time."),
))
_REQUIREMENTS += _group("geography", "site", CORE, (
    ("residency", "Buyer residency and location compatibility", "Required processing/storage/logging/routing/backup countries and actual eligible site paths."),
    ("latency", "Buyer-to-site latency", "Measured client-region latency and workload SLO, not distance or country alone."),
    ("basis", "Supported regional price basis", "Matched configuration/service/tenor common support; unsupported local premium remains unpriced."),
    ("tax", "Jurisdiction and tax treatment", "Applicable tax/VAT/withholding/import/export/activity determinations and accountable qualified review."),
))
_REQUIREMENTS += _group("security", "site", CORE, (
    ("soc2", "SOC 2 report scope", "Type I/II, system/site/service, auditor opinion, period, exceptions, gaps and complementary user controls."),
    ("iso", "ISO assurance scope", "Actual applicable certificate/report, validity, boundary and exclusions."),
    ("tenancy", "Tenant and host isolation", "Shared/dedicated scope, privileged-host threat model, network/storage/cache isolation and administrator access."),
    ("patching", "Patch and incident controls", "Vulnerability/patch posture, access logs, incident duties, buyer notification and tested response."),
    ("keys", "Key custody and attestation", "Encryption boundaries, authorized administrators, key custody and configuration-specific confidential-compute attestation if claimed."),
))
_REQUIREMENTS += _group("privacy", "workload", ("inference", "resale", "forward"), (
    ("classification", "Workload data classification", "Buyer-specific privacy/regulated-data class and permissible processing/access scope."),
    ("dpa", "DPA and model-use rights", "Executed buyer/provider terms, authorized purpose, model licenses and downstream customer rights."),
    ("retention", "Retention, training and deletion", "Prompt/output/cache/metadata/log retention, training use, deletion, debug consent and evidence."),
    ("subprocessors", "Approved subprocessors and routes", "Full trust chain, permitted providers/tools/observability, regional routing and authorized fallback."),
    ("telemetry", "Content-minimized telemetry", "Pseudonymous meter metadata, scoped access, redaction and exclusion of customer content/secrets from Git and public outputs."),
))
_REQUIREMENTS += _group("buyer", "buyer", CORE, (
    ("identity", "Buyer legal identity and authority", "Exact debtor/group, beneficial ownership, jurisdiction, authority and geographic/activity eligibility."),
    ("credit", "Buyer credit and collections", "Financial capacity, actual invoice aging/payment history, limits, concentration and dated amounts owed to us."),
    ("security", "Buyer payment security", "Deposits, LC/guarantee/collateral accessibility, legal applicability, draw timing and cure; refund liabilities remain separate."),
    ("demand", "Signed versus forecast demand", "Booked/minimum volume, merchant forecast, churn, elasticity, sales lead and enforceable receipts distinguished."),
    ("acceptance", "Buyer product and acceptance", "Hardware/workload/model, quality/privacy/region requirements, acceptance tests and permitted substitution."),
    ("remedies", "Buyer termination and remedies", "Cancellation, credit/refund, substitution, close-out, cure and liability terms with timing."),
))
_REQUIREMENTS += _group("commercial", "transaction", CORE, (
    ("currency_unit", "Settlement currency and price unit", "Explicit ISO currency/native unit; no dollar-sign inference or silent FX/token/GPU conversion."),
    ("quantity", "Quantity, MOQ and ramp", "Exclusive physical units, minimum/maximum lot, indivisible nodes, ramp and current confirmed capacity."),
    ("dates", "Actual service and delivery calendar", "Signature, delivery/acceptance/start/end, lead-time anchor, time zone, billable hours and full residual tail."),
    ("scope", "Service and commitment form", "Bare/managed, dedicated/shared, interruptible, minimum-spend/take-or-pay/reservation and wholesale/prepaid/on-demand form."),
    ("inclusions", "Price inclusions and extras", "Power/CPU/RAM/storage/egress/software/tax/maintenance/orchestration included versus separately payable."),
    ("supplier_payments", "Supplier advances and invoices", "Deposit base/due/application/refund/recoverability; invoice trigger, settlement lag and billing minimum/downtime rules."),
    ("buyer_payments", "Buyer advances and collections", "Deposit segregation/permitted use/refund/application, invoice anchor, cleared bank receipts and collection timing."),
    ("fees", "Distribution and operating charges", "Fixed/variable and gross/collected fees, processors, router/broker, retries, support, refunds and owned costs charged once."),
    ("legal_options", "Resale, assignment and optionality", "Enforceable resale/workload/assignment/reclaim/resize/exit/substitution rights and exercise conditions."),
    ("expiry", "Quote and contract validity", "Offer expiry/cutoff time zone, signature deadline, amendment version and current acceptance evidence."),
))
_REQUIREMENTS += _group("market", "market", CORE + ("hedging",), (
    ("sources", "Source permission and product admission", "Exact instrument/API/product, read-only scope, source version, observe/retain/benchmark rights and redistribution limits."),
    ("cohort", "Comparable cohort", "Hardware/memory/configuration, native currency/unit, geography, service terms, quantity and actual delivery interval."),
    ("lineage", "Offer independence and depth", "Source/offer/lot/provider groups, aggregate/constituent overlap, executable size and reseller duplicates."),
    ("freshness", "Observation time and expiry", "Source/ingestion/publication cadence, current expiry, stale/unavailable/partial scope and source schema status."),
    ("weights", "Versioned benchmark controls", "Explicit source quality/age/half-life, caps/minimum support, method, final weights/ESS/dispersion; no calibrated confidence claim."),
    ("basis", "Configuration, tenor and payment basis", "Supported comparable differences, forward/index/physical basis and unsupported extrapolation visibly held."),
))
_REQUIREMENTS += _group("inference", "workload", ("inference",), (
    ("model", "Model and tokenizer identity", "Exact model revision/hash, architecture, tokenizer/adapters/license and buyer-accepted task quality."),
    ("runtime", "Runtime and container identity", "Pinned runtime/version/container/driver/hardware and reproducible authorized benchmark configuration."),
    ("precision", "Precision and quantization", "Exact dtype/quantizer/method/hardware support and measured quality/latency/cost versus baseline."),
    ("parallelism", "Parallelism and whole-replica allocation", "Tensor/pipeline/data/expert topology and entire deployment GPU allocation; measured aggregate throughput counted once."),
    ("memory", "Memory and communication fit", "Per-GPU weights/KV/runtime/activation budgets, context, bandwidth and loading/startup requirements."),
    ("workload", "Input/output/context workload", "Token distributions, batch/concurrency/arrival rates, cache hit/creation/eviction, tools and retry/cancellation cases."),
    ("benchmark", "Qualified measured serving frontier", "Current setup-matching measured whole-deployment acceptable goodput, sample window, failures and service-horizon validity."),
    ("slo", "Task quality and latency objectives", "Buyer quality acceptance, TTFT/TPOT/p95/p99, structured/tool validity, overload and failover behavior."),
    ("demand", "Realizable inference demand", "Signed/forecast served request volumes, merchant utilization, interruption/holdback and zero-demand fixed cost."),
    ("local_cost", "All-in local serving costs", "Calendar/idle/standby GPU cost, license/startup/orchestration/network/storage/operations and inclusion boundaries."),
    ("managed_cost", "Exact routed service economics", "Same accepted model/precision/product, input/output/cache/request/media/tool fees, conditional rates and routing charges once."),
    ("meter", "Meter and invoice reconciliation", "Generated/acceptable/billable/credited/collected quantities, provider tokenizer/meter, retries, streams, corrections and disputes."),
    ("price_vector", "Workload price-vector floor", "Permitted input/output/cache/request/reservation mix, attainable ask, cost recovery and adverse-mix testing."),
    ("route_privacy", "Approved serving route", "Endpoint/model/provider/region privacy, retention, SLO and authorized failover; public rates are not route qualification."),
))
_REQUIREMENTS += _group("forward", "transaction", ("forward",), (
    ("contract", "Forward signature and enforceability", "Separate actual signing, six-to-twelve-month or declared lead, delivery start and subsequent service end."),
    ("deposit", "Cleared forward deposit", "Unique unreversed cleared receipts, entity/account/currency, legal permitted use, refund/security and deposit milestones."),
    ("capacity", "Forward capacity cutover", "Full-unit availability through service, preparation/warmup cutoff, current/future exclusive reservations and maintenance."),
    ("readiness", "Readiness and final obligations", "Funding/capacity/legal/operational acceptance, default/cure and completion reconciliation including refunds/full tail."),
))
_REQUIREMENTS += _group("risk", "portfolio", ALL, (
    ("cash", "Full-horizon dated cash", "One shared settled account/facility, restricted funds, reserves, advances, invoices, same-day order and daily/intraday funding trough."),
    ("loss_ownership", "Nonoverlapping loss ownership", "Buyer/supplier credit, refund, performance, replacement, market and operating paths; loss/recovery cash timing once."),
    ("limits", "Baseline portfolio limits", "Entity/group/site/currency plus shared grid/carrier/operator/demand dependencies and funding accessibility."),
    ("bid_ask", "Bid and ask definitions", "Economic/market/daily-liquidity/stress/portfolio caps, active constraint, downward buy/upward sell ticks, expected/economic floors."),
    ("margin", "Margin and hurdle definitions", "Gross versus collected revenue denominator, capital/funding/expense/reserve separation, dated hurdle and attainable commercial ask."),
    ("uncertainty", "Uncertainty and error evidence", "Spread versus estimate/prediction/stress, segment support, actual held-out errors and uncalibrated scenario ranges."),
    ("stress", "Joint deterministic stress", "Demand, price, delay, site failure, buyer default, refunds, replacement, conversion/margin and facility withdrawal over full cash tail."),
    ("surveillance", "Actuals and change governance", "Immutable input/policy/model versions, freshness, approvals invalidation, actual fills/goodput/collections and drift/reconciliation."),
))
_REQUIREMENTS += _group("hedging", "instrument", ("hedging",), (
    ("instrument", "Admitted hedge instrument", "Positive listed product/event identity, specification/multiplier/currency/expiry/settlement and actual authorized account."),
    ("access", "Legal and broker access", "Eligible entity/account/product, jurisdiction, custody/clearing/broker counterparties, quote/market-data rights and mandate."),
    ("basis", "Physical-to-financial basis", "Matched exposure/history, out-of-sample hedge relation, event/volatility interpretation and unsupported hedge benefit held."),
    ("liquidity", "Depth, costs and unwind", "Observed bids/asks/size, fees/slippage, unwind/roll/cancel/fill risks and available tenor."),
    ("margin", "Funded hedge margin", "Initial/variation/intraday collateral, conversion, stress path, close-out and accessible pledged liquidity."),
))
_REQUIREMENTS += _group("financing", "financing_facility", ("securitization",), (
    ("receivables", "Eligible receivable pool", "Accepted service, unique invoices/ownership, assignability, expiry and disjoint dispute/dilution/tax/offset/chargeback exclusions."),
    ("pledges", "Unique pledge and lien evidence", "Canonical economic asset across all facilities, perfected priority, legal/security opinions and accessible collections account."),
    ("terms", "Actual facility and borrowing-base terms", "Commitment, currently drawable undrawn funds, advance/haircut/reserves/concentration/covenants, fees/draw lag/maturity."),
    ("waterfall", "Collection and debt waterfall", "Cleared versus forecast collections, exact day-count interest, sweep/reserve/principal priority, maturity and forced paydown."),
))
_REQUIREMENTS += _group("securitization", "issuer", ("securitization",), (
    ("structure", "Issuer, asset and transaction structure", "Separate issuer/SPV/obligor/originator/guarantor, true-sale/bankruptcy/assignment/security/priority and actual investor mandate."),
    ("history", "Asset performance and investor evidence", "Actual receivable collection/default/dilution/concentration history, investor/lender terms and independently reviewed economics."),
    ("tranches", "Tranches and enhancement", "Actual note/subordination/overcollateralization/reserve/trigger/fee terms, loss allocation and stress waterfall."),
    ("continuity", "Servicing and operating continuity", "Backup servicer, ongoing compute delivery rights, replacement capacity, data/contract continuity and tested enforcement."),
    ("legal", "Capital-market and legal approval", "Qualified transaction/jurisdiction-specific legal/accounting/tax review and independently approved go/no-go; no automatic issuance."),
))


def underwriting_template():
    requirements = deepcopy(_REQUIREMENTS)
    return {"schema_version": SCHEMA_VERSION, "requirements_version": REQUIREMENTS_VERSION,
            "scope_options": list(SCOPE_OPTIONS), "requirements": requirements,
            "request": {"schema_version": SCHEMA_VERSION, "request_id": None, "as_of": None,
                        "requirements_version": REQUIREMENTS_VERSION, "scopes": [],
                        "subjects": {}, "requirements": deepcopy(requirements), "evidence": []},
            "warnings": ["neutral_starting_catalog_not_a_complete_legal_or_financial_policy",
                         "explicit_scopes_subjects_as_of_and_evidence_required",
                         "covered_inputs_do_not_activate_monetary_weights_or_execution"],
            "execution_enabled": False, "monetary_effects_enabled": False}
