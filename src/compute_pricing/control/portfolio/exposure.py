"""Conservative ordered gross ledger floors, without credit or netting calibration."""
from collections import Counter
from decimal import Decimal

from compute_pricing.control._numbers import text_number

ZERO = Decimal(0)
BALANCE_KINDS = {
    "supplier_prepayment": ("supplier_prepaid", "advance_account", 1),
    "prepaid_apply": ("supplier_prepaid", "advance_account", -1),
    "buyer_invoice": ("buyer_receivable", "invoice_id", 1),
    "buyer_receipt": ("buyer_receivable", "invoice_id", -1),
    "buyer_deposit": ("restricted_deposit_liability", "advance_account", 1),
    "deposit_refund": ("restricted_deposit_liability", "advance_account", -1),
}
OPENING = {"opening_prepaids": "supplier_prepaid", "opening_receivables": "buyer_receivable",
           "opening_deposits": "restricted_deposit_liability"}


def ledger_exposure_floor(cash_payload, events, exposures, limits, supplies, routes,
                          metadata, reservations, *, cash_valid):
    """Evaluate only supplied valid events, preserving explicit same-day ordering.

    Supplier prepaids and gross buyer receivables form asset floors. Restricted
    deposits remain separately reported refund liabilities; they never offset
    receivables. Group memberships remain caller declarations. Missing baseline
    balance attribution holds rather than borrowing a candidate's identity.
    """
    currency = cash_payload.get("currency")
    report = {"basis": "ordered_gross_prepaid_and_receivable_peaks_no_netting",
              "currency": currency, "complete_attribution": False, "admitted": False,
              "components": [], "scope_comparisons": [], "restricted_deposit_liabilities": [],
              "unattributed_balances": [], "blockers": [], "warnings": [
                  "counterparty_group_membership_is_declared_not_verified",
                  "supplied_schedule_is_not_actual_intraday_settlement_evidence",
                  "gross_ledger_floors_are_not_calibrated_risk_ead_or_default_probabilities",
                  "no_collateral_deposit_offset_cross_counterparty_or_currency_netting",
                  "future_contingent_delivery_replacement_and_stochastic_exposures_remain_unknown"]}
    blockers = report["blockers"]

    def hold(code):
        if code not in blockers:
            blockers.append(code)

    if not cash_valid:
        hold("ledger_exposure_floor_unavailable_invalid_cash")
        return report
    groups, entity_groups = {}, {}
    declared = Counter()
    for row in exposures:
        groups.setdefault((row.entity_id, row.site_id, row.currency), set()).add(row.group_id)
        entity_groups.setdefault(row.entity_id, set()).add(row.group_id)
        for scope, member in (("entity", row.entity_id), ("group", row.group_id),
                              ("site", row.site_id), ("currency", row.currency)):
            declared[(scope, member, row.currency)] += Decimal(row.amount)
    owners, event_owners = {}, {}

    def add_owner(identity, entity, lot_id, event_ids, category):
        lot = metadata.get(lot_id)
        if lot is None:
            hold("ledger_exposure_attribution_missing_lot")
            return
        key = (entity, lot["site_id"], currency)
        matches = groups.get(key, set())
        if len(matches) != 1 or len(entity_groups.get(entity, set())) != 1:
            hold("ledger_exposure_group_missing_or_ambiguous")
        else:
            owners[identity] = {"owner_id": identity, "entity_id": entity,
                                "group_id": next(iter(matches)), "site_id": lot["site_id"],
                                "lot_id": lot_id, "currency": currency, "category": category}
        for event_id in event_ids:
            event_owners.setdefault(event_id, []).append(identity)

    for supply in supplies:
        lot = metadata.get(supply["lot_id"])
        if lot:
            add_owner("supply:" + supply["supply_id"], lot["supplier_entity_id"],
                      supply["lot_id"], supply["cash_event_ids"], "supplier")
        else:
            hold("ledger_exposure_attribution_missing_lot")
    for route in routes:
        reservation = reservations.get(route["reservation_id"])
        if reservation:
            add_owner("route:" + route["route_id"], route["buyer_entity_id"],
                      reservation.lot_id, route["cash_event_ids"], "buyer")
        else:
            hold("ledger_exposure_attribution_missing_reservation")
    balances, identities, peaks, scope_peaks = {}, {}, {}, {}
    current, changed = Counter(), set()
    for field, category in OPENING.items():
        for identity, amount in cash_payload.get(field, {}).items():
            value = Decimal(amount)
            if value:
                report["unattributed_balances"].append({"kind": category, "balance_id": identity,
                    "amount": text_number(value), "currency": currency, "opening": True})
                hold("ledger_exposure_baseline_attribution_missing")

    def update(category, balance_id, delta, event):
        keys = event_owners.get(event["event_id"], [])
        mapping = owners.get(keys[0]) if len(keys) == 1 else None
        expected = "supplier" if category == "supplier_prepaid" else "buyer"
        if mapping is None or mapping["category"] != expected:
            report["unattributed_balances"].append({"kind": category, "balance_id": balance_id,
                "event_id": event["event_id"], "on": event["on"], "amount": text_number(abs(delta)),
                "currency": currency, "opening": False})
            hold("ledger_exposure_event_attribution_missing_or_ambiguous")
            return
        key = (category, balance_id)
        if key in identities and identities[key] != mapping:
            hold("ledger_exposure_balance_crosses_attribution")
            return
        identities[key] = mapping
        balances[key] = balances.get(key, ZERO) + delta
        if balances[key] < ZERO:
            hold("ledger_exposure_balance_replay_not_reconciled")
        witness = {"event_id": event["event_id"], "on": event["on"]}
        if balances[key] > peaks.get(key, {}).get("amount", ZERO):
            peaks[key] = {"amount": balances[key], "witness": witness}
        if category != "restricted_deposit_liability":
            for scope, member in (("entity", mapping["entity_id"]), ("group", mapping["group_id"]),
                                  ("site", mapping["site_id"]), ("currency", mapping["currency"])):
                scope_key = (scope, member, currency)
                current[scope_key] += delta
                changed.add(scope_key)

    # Sorting dates is the cash kernel's ordering rule; ties retain caller order.
    for event in sorted(events, key=lambda row: row["on"]):
        changed.clear()
        kind = event["kind"]
        value = Decimal(event["amount"])
        if kind == "deposit_apply":
            update("buyer_receivable", event["invoice_id"], -value, event)
            update("restricted_deposit_liability", event["advance_account"], -value, event)
        elif kind in BALANCE_KINDS:
            category, field, sign = BALANCE_KINDS[kind]
            update(category, event[field], value * sign, event)
        # A peak of each simultaneous aggregate, not a sum of separate peaks.
        for key in changed:
            amount = current[key]
            if amount > scope_peaks.get(key, {}).get("amount", ZERO):
                scope_peaks[key] = {"amount": amount, "witness": {"event_id": event["event_id"], "on": event["on"]}}
    for key in sorted(peaks):
        mapping, peak = identities[key], peaks[key]
        row = {"kind": key[0], "balance_id": key[1],
               **{field: mapping[field] for field in ("owner_id", "entity_id", "group_id", "site_id", "lot_id", "currency")},
               "peak_amount": text_number(peak["amount"]), "witness": peak["witness"]}
        report["restricted_deposit_liabilities" if key[0] == "restricted_deposit_liability" else "components"].append(row)
    maxima = {(item.scope, item.member_id, item.currency): Decimal(item.maximum_amount) for item in limits}
    for key, peak in sorted(scope_peaks.items()):
        amount, maximum, declaration = peak["amount"], maxima.get(key), declared.get(key, ZERO)
        enough = declaration >= amount
        limit_pass = maximum is not None and amount <= maximum
        report["scope_comparisons"].append({"scope": key[0], "member_id": key[1], "currency": key[2],
            "floor_amount": text_number(amount), "declared_amount": text_number(declaration),
            "maximum_amount": None if maximum is None else text_number(maximum),
            "declaration_covers_floor": enough, "floor_within_limit": limit_pass, "witness": peak["witness"]})
        if not enough:
            hold("declared_exposure_below_ledger_floor")
        if maximum is None:
            hold("ledger_exposure_floor_limit_missing")
        elif not limit_pass:
            hold("ledger_exposure_floor_above_limit")
    report["complete_attribution"] = not any(code.startswith("ledger_exposure_") and code not in {
        "ledger_exposure_floor_limit_missing", "ledger_exposure_floor_above_limit"} for code in blockers)
    report["admitted"] = not blockers
    return report
