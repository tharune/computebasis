"""One candidate portfolio, one cash/facility ledger and one capacity ledger.

The request contains the complete baseline plus candidate route claims. Checks
are deterministic and do not authenticate bank documents, create holds, choose
an optimal bid/allocation, calibrate demand/credit or grant execution authority.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import asdict, fields
from decimal import Decimal, localcontext
import re
from typing import Any

from compute_pricing.control._numbers import calculation_precision, canonical_json, digest, text_number
from compute_pricing.control.capacity import CapacityLot, Maintenance, Reservation, validate_capacity
from compute_pricing.control.domain import ValidationError, utc_instant
from compute_pricing.control.domain.spec import ID_PATTERN
from compute_pricing.control.inference import evaluate_inference_payload
from compute_pricing.control.risk import Exposure, ExposureLimit, assess_exposures
from compute_pricing.control.treasury import evaluate_cash_payload
from compute_pricing.control.treasury._validation import decimal_value
from compute_pricing.control.underwriting import assess_underwriting, underwriting_template
from .exposure import ledger_exposure_floor

SCHEMA = "portfolio-assessment/1.0"
MODEL = "shared-portfolio-candidate/1.1.0"
ROUTES = {"inference", "resale", "forward"}
MAX_ROWS, MAX_ROUTES, MAX_BYTES = 10000, 16, 1048576
ROUTE_FIELDS = {"route_id", "kind", "buyer_entity_id", "reservation_id", "cash_event_ids", "exposure_ids", "economics", "supply_cost_allocations", "inference_request", "underwriting_request_id"}
ECONOMIC_FIELDS = {"currency", "gross_billings", "expected_collections", "distribution_fees", "nonpurchase_cost", "policy_capital"}
ROUTE_CASH_KINDS = {"buyer_invoice", "revenue", "buyer_receipt", "buyer_deposit", "deposit_apply", "deposit_refund", "expense", "other_outflow"}
SUPPLY_CASH_KINDS = {"supplier_invoice", "supplier_prepayment", "prepaid_apply", "supplier_payment", "expense", "other_outflow"}
SUPPLY_OUTFLOWS = {"supplier_prepayment", "supplier_payment", "other_outflow"}
ZERO = Decimal(0)


def _fail(code):
    raise ValidationError("portfolio:" + code)


def _id(value):
    if not isinstance(value, str) or len(value) > 128 or not re.fullmatch(ID_PATTERN, value):
        _fail("canonical_identity_required")
    return value


def _tree(value, depth=0, budget=None):
    if budget is None:
        budget = [0]
    budget[0] += 1
    if budget[0] > 60000 or depth > 30:
        _fail("bounded_input_tree_required")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or not key or len(key) > 2048:
                _fail("bounded_keys_required")
            _tree(item, depth + 1, budget)
    elif isinstance(value, list):
        for item in value:
            _tree(item, depth + 1, budget)
    elif isinstance(value, str):
        if len(value) > 16384:
            _fail("bounded_text_required")
    elif value is not None and type(value) not in {bool, int}:
        _fail("exact_json_values_required")
    elif type(value) is int and abs(value) > 2147483647:
        _fail("bounded_integer_required")


def _object(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= set(value) or set(value) - set(required) - set(optional):
        _fail("explicit_registered_record_fields_required")
    return value


def _rows(value, *, maximum=MAX_ROWS):
    if not isinstance(value, list) or len(value) > maximum:
        _fail("bounded_array_required")
    return value


def _ids(value):
    return [_id(item) for item in _rows(value)]


def _money(value):
    try:
        return decimal_value(value, "portfolio money")
    except ValueError:
        _fail("exact_nonnegative_decimal_string_required")


def _typed(raw, cls):
    _object(raw, {field.name for field in fields(cls)})
    for key, value in raw.items():
        if key == "member_id" and cls is ExposureLimit and raw.get("scope") == "currency":
            if value != raw.get("currency"):
                _fail("currency_limit_member_must_match_currency")
        elif key.endswith("_id"):
            _id(value)
        elif key == "unit_ids":
            _ids(value)
    try:
        return cls(**{key: tuple(value) if key == "unit_ids" and isinstance(value, list) else value for key, value in raw.items()})
    except (ValueError, TypeError):
        _fail("invalid_" + cls.__name__.lower())


def _encode(value):
    if isinstance(value, Decimal):
        return text_number(value)
    if isinstance(value, dict):
        return {key: _encode(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_encode(item) for item in value]
    return value


def portfolio_template():
    """A blank input contract with no prices, holdings, funds or evidence."""
    return {"schema_version": SCHEMA, "model_version": MODEL, "route_kinds": sorted(ROUTES),
            "request": {"schema_version": SCHEMA, "request_id": None, "as_of": None, "policy_version": None,
                        "cash": {"legal_entity_id": None, "cash_account_id": None, "currency": None,
                                 "opening_cash": None, "start_date": None, "end_date": None,
                                 "events": [], "reserves": [], "facility": None},
                        "capacity": {"lots": [], "reservations": [], "maintenance": [], "baseline_allocation_ids": []},
                        "routes": [], "supplies": [], "baseline_cash_event_ids": [], "baseline_exposure_ids": [],
                        "exposures": [], "limits": [], "underwriting_requests": [], "minimum_free_cash": None},
            "warnings": ["blank_contract_requires_explicit_baseline_candidate_and_evidence", "one_entity_account_currency_and_one_facility_no_implicit_transfers"],
            "execution_enabled": False, "firm_price_eligible": False}


def evaluate_portfolio_payload(payload: dict[str, Any]) -> dict[str, Any]:
    _tree(payload)
    if len(canonical_json(payload).encode("utf-8")) > MAX_BYTES:
        _fail("input_size_limit")
    with localcontext() as context:
        context.prec = calculation_precision(payload)
        return _evaluate(payload)


def _evaluate(payload):
    required = set(portfolio_template()["request"])
    if not isinstance(payload, dict):
        _fail("object_required")
    if payload.get("extensions") is not None and not isinstance(payload["extensions"], dict):
        _fail("extensions_object_required")
    unused = sorted(set(payload) - required - {"extensions"})
    result = {"schema_version": SCHEMA, "status": "held", "execution_enabled": False, "firm_price_eligible": False,
              "request_id": payload.get("request_id"), "as_of": payload.get("as_of"),
              "versions": {"model": MODEL, "schema": SCHEMA, "policy": payload.get("policy_version")},
              "blockers": [], "warnings": ["caller_supplied_complete_baseline_and_candidate_not_independent_verification",
                  "shared_scenario_feasibility_not_optimal_bid_or_firm_quote", "no_currency_entity_or_account_netting",
                  "evidence_completeness_does_not_verify_substantive_legal_credit_privacy_eligibility"],
              "checks": {"cash": False, "capacity": False, "exposure": False, "evidence": False, "economic_reconciliation": False},
              "cash": None, "capacity": None, "exposures": None, "routes": [], "economics": None,
              "ledger_exposure_floor": None,
              "underwriting": [], "unused_fields": unused, "input_hash": digest(payload)}
    blockers = result["blockers"]

    def hold(code, *, route_id=None):
        entry = {"code": code}
        if route_id is not None:
            entry["route_id"] = route_id
        if entry not in blockers:
            blockers.append(entry)

    def finish():
        if unused or payload.get("extensions"):
            result["warnings"].append("unregistered_extensions_and_fields_hashed_but_not_used")
        result["status"] = "held" if blockers else "indicative"
        result["decision_hash"] = digest(result)
        return deepcopy(result)

    missing = [key for key in required if payload.get(key) is None]
    if missing:
        for key in sorted(missing):
            hold("missing:" + key)
        return finish()
    if payload["schema_version"] != SCHEMA:
        _fail("unsupported_schema")
    _id(payload["request_id"])
    if not isinstance(payload["policy_version"], str) or not payload["policy_version"].strip() or len(payload["policy_version"]) > 128:
        _fail("explicit_bounded_policy_version_required")
    as_of = utc_instant(payload["as_of"])
    floor = _money(payload["minimum_free_cash"])
    routes = _rows(payload["routes"], maximum=MAX_ROUTES)
    if not routes:
        hold("nonempty_candidate_routes_required")
    route_ids, route_map = [], {}
    for route in routes:
        _object(route, ROUTE_FIELDS)
        identity = _id(route["route_id"])
        if not isinstance(route["kind"], str) or route["kind"] not in ROUTES:
            _fail("supported_route_kind_required")
        for key in ("buyer_entity_id", "reservation_id"):
            _id(route[key])
        if route["underwriting_request_id"] is not None:
            _id(route["underwriting_request_id"])
        _object(route["economics"], ECONOMIC_FIELDS)
        for field in ECONOMIC_FIELDS - {"currency"}:
            _money(route["economics"][field])
        if _money(route["economics"]["expected_collections"]) > _money(route["economics"]["gross_billings"]):
            hold("collections_exceed_gross_billings", route_id=identity)
        _ids(route["cash_event_ids"]); _ids(route["exposure_ids"])
        route_ids.append(identity)
        route_map[identity] = route
    if len(set(route_ids)) != len(route_ids):
        _fail("duplicate_route_identity")
    capacity = _object(payload["capacity"], {"lots", "reservations", "maintenance", "baseline_allocation_ids"})
    baseline_allocations = _ids(capacity["baseline_allocation_ids"])
    if set(baseline_allocations) & set(route_ids) or len(set(baseline_allocations)) != len(baseline_allocations):
        _fail("baseline_and_candidate_allocation_identity_conflict")
    lots, metadata = [], {}
    for raw in _rows(capacity["lots"]):
        base_fields = {field.name for field in fields(CapacityLot)}
        _object(raw, base_fields | {"supplier_entity_id", "hardware_model", "accelerators_per_unit"})
        _id(raw["supplier_entity_id"])
        if raw["hardware_model"] is not None and (not isinstance(raw["hardware_model"], str) or not raw["hardware_model"].strip()):
            _fail("explicit_hardware_label_required")
        if raw["accelerators_per_unit"] is not None:
            count = _money(raw["accelerators_per_unit"])
            if count <= 0 or count != count.to_integral_value():
                _fail("positive_whole_accelerators_per_unit_required")
            if raw["unit_kind"] == "gpu" and count != 1:
                _fail("gpu_unit_must_be_one_accelerator")
        lot = _typed({key: raw[key] for key in base_fields}, CapacityLot)
        lots.append(lot); metadata[lot.lot_id] = raw
    reservations = tuple(_typed(raw, Reservation) for raw in _rows(capacity["reservations"]))
    maintenance = tuple(_typed(raw, Maintenance) for raw in _rows(capacity["maintenance"]))
    by_reservation = {item.reservation_id: item for item in reservations}
    try:
        capacity_report = validate_capacity(tuple(lots), reservations, maintenance)
        result["capacity"] = _encode(asdict(capacity_report))
        result["checks"]["capacity"] = True
    except ValueError:
        hold("shared_capacity_overlap_or_invalid_ledger")
    for reservation in reservations:
        if reservation.allocation_id not in set(route_ids) | set(baseline_allocations):
            hold("unowned_capacity_allocation")
    linked_reservations = [route["reservation_id"] for route in routes]
    if len(set(linked_reservations)) != len(linked_reservations):
        hold("reservation_claimed_by_multiple_routes")
    for reservation in reservations:
        if reservation.allocation_id in route_map and reservation.reservation_id not in linked_reservations:
            hold("candidate_reservation_missing_route_join")
    for route in routes:
        reservation = by_reservation.get(route["reservation_id"])
        if not reservation or reservation.allocation_id != route["route_id"]:
            hold("route_reservation_identity_mismatch", route_id=route["route_id"])
    cash_payload = payload["cash"]
    if not isinstance(cash_payload, dict):
        _fail("shared_cash_object_required")
    try:
        cash = evaluate_cash_payload(cash_payload)
        result["cash"] = cash.to_dict()
        if cash.minimum_free_cash < floor:
            hold("shared_cash_below_required_floor")
        if cash.maturity_breach:
            hold("shared_facility_maturity_breach")
        if any(cash.unresolved_balances.values()):
            hold("shared_cash_unreconciled_final_balances")
        if cash_payload["start_date"] > payload["as_of"][:10] or cash_payload["end_date"] < payload["as_of"][:10]:
            hold("cash_horizon_omits_as_of")
        if any(cash_payload["end_date"] < lot.end_at[:10] for lot in lots):
            hold("cash_horizon_omits_supply_tail")
        if any(cash_payload["start_date"] > lot.start_at[:10] for lot in lots):
            hold("cash_horizon_omits_supply_start")
        result["checks"]["cash"] = not any(item["code"].startswith(("shared_cash_", "shared_facility_", "cash_horizon_")) for item in blockers)
    except (ValueError, TypeError, KeyError, ArithmeticError):
        hold("invalid_shared_cash_schedule")
        cash = None
    events = _rows(cash_payload.get("events", []))
    if any(not isinstance(event, dict) or "event_id" not in event or "kind" not in event for event in events):
        _fail("explicit_cash_events_required")
    for event in events:
        _id(event["event_id"])
        if event.get("obligation_id") is not None:
            _id(event["obligation_id"])
    event_map = {event["event_id"]: event for event in events}
    currency = cash_payload.get("currency")
    cash_owners = Counter(_ids(payload["baseline_cash_event_ids"]))
    supplies, supply_map = _rows(payload["supplies"]), {}
    total_supply = ZERO
    for supply in supplies:
        _object(supply, {"supply_id", "lot_id", "purchase_cost", "currency", "cash_event_ids"})
        identity = _id(supply["supply_id"]); _id(supply["lot_id"])
        if identity in supply_map:
            _fail("duplicate_supply_identity")
        supply_map[identity] = supply
        value = _money(supply["purchase_cost"])
        total_supply += value
        if supply["currency"] != currency or supply["lot_id"] not in metadata:
            hold("supply_currency_or_lot_mismatch")
        owned_ids = _ids(supply["cash_event_ids"])
        cash_owners.update(owned_ids)
        owned = [event_map[identity] for identity in owned_ids if identity in event_map]
        if any(event["kind"] not in SUPPLY_CASH_KINDS for event in owned):
            hold("supply_cannot_own_revenue_or_financing_cash")
        outflows = sum((_money(event["amount"]) for event in owned if event["kind"] in SUPPLY_OUTFLOWS), ZERO)
        expense = sum((_money(event["amount"]) for event in owned if event["kind"] == "expense"), ZERO)
        if outflows != value or expense != value:
            hold("supplier_cash_and_expense_do_not_reconcile")
    lot_supply_ids = [supply["lot_id"] for supply in supplies]
    if len(set(lot_supply_ids)) != len(lot_supply_ids):
        hold("supply_lot_cost_declared_multiple_times")
    if set(lot_supply_ids) != set(metadata):
        hold("every_supply_lot_requires_one_cost_record")
    exposures = tuple(_typed(raw, Exposure) for raw in _rows(payload["exposures"]))
    limits = tuple(_typed(raw, ExposureLimit) for raw in _rows(payload["limits"]))
    exposure_map = {item.exposure_id: item for item in exposures}
    exposure_owners = Counter(_ids(payload["baseline_exposure_ids"]))
    try:
        report = assess_exposures(exposures, limits)
        if any(item.currency != currency for item in exposures) or any(item.currency != currency for item in limits):
            hold("exposure_currency_mismatch_no_implicit_fx")
        result["exposures"] = {"totals": [{"scope": key[0], "member_id": key[1], "currency": key[2], "amount": text_number(amount)} for key, amount in sorted(report.totals.items())],
                               "limits": _encode([asdict(item) for item in report.limits]),
                               "uncovered": [list(key) for key in report.uncovered], "admitted": report.admitted}
        result["checks"]["exposure"] = report.admitted and not any(item["code"] == "exposure_currency_mismatch_no_implicit_fx" for item in blockers)
        if not report.admitted:
            hold("missing_or_breached_shared_portfolio_limits")
    except ValueError:
        hold("invalid_shared_exposure_ledger")
    underwriting = _rows(payload["underwriting_requests"], maximum=MAX_ROUTES)
    assessments, underwriting_inputs = {}, {}
    for raw in underwriting:
        assessment = assess_underwriting(raw)
        identity = assessment["request_id"]
        if identity in assessments:
            _fail("duplicate_underwriting_request_identity")
        assessments[identity], underwriting_inputs[identity] = assessment, raw
        result["underwriting"].append(assessment)
    baseline_requirements = underwriting_template()["requirements"]
    catalog_fields = {"required", "value_type", "unit", "subject_kind", "owning_path", "owner_model", "evidence_scope", "allow_not_applicable", "minimum", "maximum"}
    economic_totals = {field: ZERO for field in ECONOMIC_FIELDS - {"currency"}}
    allocated_costs = Counter()
    for route in routes:
        identity, economics = route["route_id"], route["economics"]
        route_start = len(blockers)
        if economics["currency"] != currency:
            hold("route_currency_mismatch", route_id=identity)
        for key in economic_totals:
            economic_totals[key] += _money(economics[key])
        owned_ids = _ids(route["cash_event_ids"])
        cash_owners.update(owned_ids)
        owned = [event_map[key] for key in owned_ids if key in event_map]
        if any(event["kind"] not in ROUTE_CASH_KINDS for event in owned):
            hold("route_cannot_own_supply_or_financing_cash", route_id=identity)
        collections = sum((_money(event["amount"]) for event in owned if event["kind"] in {"buyer_receipt", "deposit_apply"}), ZERO)
        gross_invoices = sum((_money(event["amount"]) for event in owned if event["kind"] == "buyer_invoice"), ZERO)
        earned_revenue = sum((_money(event["amount"]) for event in owned if event["kind"] == "revenue"), ZERO)
        outflows = sum((_money(event["amount"]) for event in owned if event["kind"] == "other_outflow"), ZERO)
        expense = sum((_money(event["amount"]) for event in owned if event["kind"] == "expense"), ZERO)
        fees_and_cost = _money(economics["distribution_fees"]) + _money(economics["nonpurchase_cost"])
        if collections != _money(economics["expected_collections"]) or outflows != fees_and_cost or expense != fees_and_cost:
            hold("route_cash_and_economics_do_not_reconcile", route_id=identity)
        if gross_invoices != _money(economics["gross_billings"]) or earned_revenue != _money(economics["gross_billings"]):
            hold("gross_invoices_earned_revenue_do_not_reconcile", route_id=identity)
        # Uncollected gross face value is a declared loss assumption, not a cash
        # flow. The dated ledger still must settle every supplied invoice/advance.
        reservation = by_reservation.get(route["reservation_id"])
        lot = metadata.get(reservation.lot_id) if reservation else None
        allocated = ZERO
        route_supply_ids = set()
        for allocation in _rows(route["supply_cost_allocations"]):
            _object(allocation, {"supply_id", "amount"})
            supply_id = _id(allocation["supply_id"])
            if supply_id in route_supply_ids:
                _fail("duplicate_route_supply_cost_allocation")
            route_supply_ids.add(supply_id)
            amount = _money(allocation["amount"])
            allocated_costs[supply_id] += amount
            allocated += amount
            supply = supply_map.get(supply_id)
            if not supply or not reservation or supply["lot_id"] != reservation.lot_id:
                hold("supply_cost_allocation_has_wrong_lot", route_id=identity)
        if not route_supply_ids:
            hold("explicit_route_supply_cost_allocation_required", route_id=identity)
        owned_exposure_ids = _ids(route["exposure_ids"])
        exposure_owners.update(owned_exposure_ids)
        owned_exposures = [exposure_map[key] for key in owned_exposure_ids if key in exposure_map]
        if not owned_exposures:
            hold("route_exposure_evidence_required", route_id=identity)
        if lot and ({route["buyer_entity_id"], lot["supplier_entity_id"]} - {item.entity_id for item in owned_exposures}
                    or any(item.site_id != lot["site_id"] for item in owned_exposures)):
            hold("route_buyer_supplier_site_exposure_mapping_missing", route_id=identity)
        inference = None
        if route["kind"] == "inference":
            if not isinstance(route["inference_request"], dict):
                hold("missing_qualified_inference_request", route_id=identity)
            else:
                inference = evaluate_inference_payload(route["inference_request"]).to_dict()
                workload = route["inference_request"].get("workload", {})
                local = inference.get("local")
                if inference["status"] != "indicative" or local is None:
                    hold("inference_economics_or_qualification_held", route_id=identity)
                elif not lot or not reservation or lot["unit_kind"] not in {"gpu", "node", "accelerator"} or lot["accelerators_per_unit"] is None:
                    hold("inference_physical_accelerator_mapping_unknown", route_id=identity)
                else:
                    expected_gpu_count = _money(lot["accelerators_per_unit"]) * len(reservation.unit_ids)
                    if (_money(local["allocated_gpu_count"]) != expected_gpu_count or workload.get("hardware_model") != lot["hardware_model"]
                            or workload.get("starts_at") != reservation.start_at or workload.get("ends_at") != reservation.end_at
                            or utc_instant(route["inference_request"]["as_of"]) != as_of or local["currency"] != currency
                            or route["inference_request"]["policy_version"] != payload["policy_version"]):
                        hold("inference_setup_does_not_match_reserved_capacity", route_id=identity)
                    if (Decimal(local["billed_revenue"]) != _money(economics["gross_billings"])
                            or Decimal(local["expected_collected_revenue"]) != _money(economics["expected_collections"])
                            or Decimal(local["distribution_fees"]) != _money(economics["distribution_fees"])
                            or Decimal(local["gpu_cost_including_idle"]) != allocated
                            or Decimal(local["total_cost"]) - allocated != _money(economics["nonpurchase_cost"])):
                        hold("inference_economics_do_not_reconcile_to_shared_portfolio", route_id=identity)
        elif route["inference_request"] is not None:
            _fail("inference_request_only_on_inference_route")
        assessment = assessments.get(route["underwriting_request_id"])
        review = underwriting_inputs.get(route["underwriting_request_id"])
        if not assessment or not review or assessment["status"] != "complete_for_declared_requirements":
            hold("route_underwriting_evidence_missing_or_held", route_id=identity)
        else:
            required_rows = [row for row in baseline_requirements if route["kind"] in row["scopes"] and row["required"]]
            supplied_rows = {row["requirement_id"]: row for row in review["requirements"]}
            weak = any(row["requirement_id"] not in supplied_rows or any(supplied_rows[row["requirement_id"]].get(key) != row.get(key) for key in catalog_fields) or route["kind"] not in supplied_rows[row["requirement_id"]].get("scopes", []) for row in required_rows)
            subjects = review["subjects"]
            if (route["kind"] not in review["scopes"] or utc_instant(review["as_of"]) != as_of or weak
                    or review["requirements_version"] != underwriting_template()["requirements_version"]
                    or not lot or subjects.get("lot") != reservation.lot_id or subjects.get("site") != lot["site_id"]
                    or subjects.get("buyer") != route["buyer_entity_id"] or subjects.get("supplier") != lot["supplier_entity_id"]
                    or subjects.get("transaction") != identity or subjects.get("portfolio") != payload["request_id"]):
                hold("route_underwriting_scope_subject_or_required_core_mismatch", route_id=identity)
            if route["kind"] == "inference" and isinstance(route["inference_request"], dict):
                qualification = route["inference_request"].get("qualification", {})
                benchmark = next((row for row in review["evidence"] if row["requirement_id"] == "inference:benchmark"), {})
                if (subjects.get("workload") != identity
                        or not any(ref.get("artifact_sha256") == qualification.get("evidence_sha256") for ref in benchmark.get("evidence", []))):
                    hold("inference_benchmark_not_bound_to_underwriting_evidence", route_id=identity)
        contribution = _money(economics["expected_collections"]) - fees_and_cost - allocated
        result["routes"].append({"route_id": identity, "kind": route["kind"], "reservation_id": route["reservation_id"],
                                  "economics": {**deepcopy(economics), "allocated_supply_cost": text_number(allocated),
                                                "expected_contribution": text_number(contribution), "economic_profit": text_number(contribution - _money(economics["policy_capital"]))},
                                  "inference": inference, "underwriting_request_id": route["underwriting_request_id"],
                                  "blockers": [item["code"] for item in blockers[route_start:] if item.get("route_id") == identity]})
    if any(allocated_costs[identity] > _money(supply["purchase_cost"]) for identity, supply in supply_map.items()):
        hold("supplier_cost_allocated_more_than_once")
    if set(cash_owners) != set(event_map) or any(count != 1 for count in cash_owners.values()):
        hold("cash_events_must_have_one_global_owner")
    # Event IDs alone are insufficient: an invoice/deposit application for one
    # buyer must not be attributed to another route with a different credit map.
    event_owner = {key: "baseline" for key in payload["baseline_cash_event_ids"]}
    for supply in supplies:
        event_owner.update({key: "supply:" + supply["supply_id"] for key in supply["cash_event_ids"]})
    for route in routes:
        event_owner.update({key: "route:" + route["route_id"] for key in route["cash_event_ids"]})
    invoice_owners, advance_owners = {}, {}
    for field, category, registry in (("opening_receivables", "buyer", invoice_owners), ("opening_payables", "supplier", invoice_owners),
                                      ("opening_deposits", "buyer", advance_owners), ("opening_prepaids", "supplier", advance_owners)):
        for identity in cash_payload.get(field, {}):
            registry[(category, identity)] = {"baseline"}
    for event in events:
        owner = event_owner.get(event["event_id"])
        if owner is None:
            continue
        category = "supplier" if event["kind"] in SUPPLY_CASH_KINDS - {"expense", "other_outflow"} else "buyer"
        if event.get("invoice_id"):
            invoice_owners.setdefault((category, event["invoice_id"]), set()).add(owner)
        if event.get("advance_account"):
            advance_owners.setdefault((category, event["advance_account"]), set()).add(owner)
    if any(len(owners) != 1 for owners in invoice_owners.values()):
        hold("invoice_crosses_economic_owners")
    if any(len(owners) != 1 for owners in advance_owners.values()):
        hold("advance_crosses_economic_owners")
    if set(exposure_owners) != set(exposure_map) or any(count != 1 for count in exposure_owners.values()):
        hold("exposures_must_have_one_global_owner")
    floor_report = ledger_exposure_floor(cash_payload, events, exposures, limits, supplies, routes,
                                         metadata, by_reservation, cash_valid=cash is not None)
    result["ledger_exposure_floor"] = floor_report
    for code in floor_report["blockers"]:
        hold(code)
    result["checks"]["exposure"] &= floor_report["admitted"]
    allocated_total = sum(allocated_costs.values(), ZERO)
    contribution = economic_totals["expected_collections"] - economic_totals["distribution_fees"] - economic_totals["nonpurchase_cost"] - total_supply
    result["economics"] = {"currency": currency, **{key: text_number(value) for key, value in economic_totals.items()},
                           "total_supply_cost": text_number(total_supply), "unallocated_supply_cost": text_number(total_supply - allocated_total),
                           "expected_contribution": text_number(contribution), "economic_profit": text_number(contribution - economic_totals["policy_capital"]),
                           "basis": "candidate_expected_collections_less_owned_operating_and_entire_supply_cost_financing_excluded"}
    if contribution <= 0:
        hold("candidate_expected_contribution_not_positive")
    if contribution - economic_totals["policy_capital"] < 0:
        hold("candidate_economic_profit_negative")
    result["checks"]["capacity"] &= not any(item["code"] in {"unowned_capacity_allocation", "reservation_claimed_by_multiple_routes", "candidate_reservation_missing_route_join", "route_reservation_identity_mismatch", "inference_physical_accelerator_mapping_unknown", "inference_setup_does_not_match_reserved_capacity"} for item in blockers)
    result["checks"]["exposure"] &= not any(item["code"] in {"exposures_must_have_one_global_owner", "route_exposure_evidence_required", "route_buyer_supplier_site_exposure_mapping_missing"} for item in blockers)
    if result["exposures"] is not None:
        result["exposures"]["declared_measures_admitted"] = result["exposures"]["admitted"]
        result["exposures"]["admitted"] = result["checks"]["exposure"]
    result["checks"]["evidence"] = bool(routes) and not any(item["code"].startswith("route_underwriting_") or item["code"] == "inference_benchmark_not_bound_to_underwriting_evidence" for item in blockers)
    result["checks"]["economic_reconciliation"] = cash is not None and not any(item["code"] in {"collections_exceed_gross_billings", "supply_currency_or_lot_mismatch", "supply_cannot_own_revenue_or_financing_cash", "supplier_cash_and_expense_do_not_reconcile", "supply_lot_cost_declared_multiple_times", "every_supply_lot_requires_one_cost_record", "route_currency_mismatch", "route_cannot_own_supply_or_financing_cash", "route_cash_and_economics_do_not_reconcile", "gross_invoices_earned_revenue_do_not_reconcile", "supply_cost_allocation_has_wrong_lot", "explicit_route_supply_cost_allocation_required", "inference_economics_do_not_reconcile_to_shared_portfolio", "supplier_cost_allocated_more_than_once", "cash_events_must_have_one_global_owner", "invoice_crosses_economic_owners", "advance_crosses_economic_owners"} for item in blockers)
    result["warnings"].append("gross_uncollected_difference_is_declared_credit_assumption_not_a_verified_default_forecast")
    result["warnings"].extend(["native_unrestricted_customer_advance_liability_and_receivable_writeoff_models_not_implemented",
                              "candidate_supply_cost_reconciliation_excludes_previously_paid_baseline_assets"])
    return finish()
