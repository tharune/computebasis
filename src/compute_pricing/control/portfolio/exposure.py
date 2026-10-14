"""Conservative date-only gross asset bounds, without credit or netting calibration."""
from collections import Counter
from decimal import Decimal

from compute_pricing.control._numbers import text_number

ZERO = Decimal(0)
BALANCE_KINDS = {
    "supplier_prepayment": ("supplier_prepaid", "advance_account", 1),
    "prepaid_apply": ("supplier_prepaid", "advance_account", -1),
    "buyer_invoice": ("buyer_receivable", "invoice_id", 1),
    "buyer_receipt": ("buyer_receivable", "invoice_id", -1),
    "receivable_writeoff": ("buyer_receivable", "invoice_id", -1),
    "buyer_credit_note": ("buyer_receivable", "invoice_id", -1),
    "buyer_deposit": ("restricted_deposit_liability", "advance_account", 1),
    "deposit_refund": ("restricted_deposit_liability", "advance_account", -1),
    "deposit_forfeit": ("restricted_deposit_liability", "advance_account", -1),
    "buyer_advance": ("customer_advance_liability", "advance_account", 1),
    "advance_refund": ("customer_advance_liability", "advance_account", -1),
}
OPENING = {"opening_prepaids": "supplier_prepaid", "opening_receivables": "buyer_receivable",
           "opening_deposits": "restricted_deposit_liability",
           "opening_advances": "customer_advance_liability"}
LIABILITIES = {"restricted_deposit_liability": "restricted_deposit_liabilities",
               "customer_advance_liability": "customer_advance_liabilities"}
INCREASE_KINDS = frozenset(kind for kind, (_, _, sign) in BALANCE_KINDS.items() if sign > 0)


def ledger_exposure_floor(cash_payload, events, exposures, limits, supplies, routes,
                          metadata, reservations, *, cash_valid):
    """Date-only admission uses opening balances plus every same-day increase.

    Supplier prepaids and gross buyer receivables form asset floors. Restricted
    deposits remain separately reported refund liabilities; they never offset
    receivables. Group memberships remain caller declarations. Missing baseline
    balance attribution holds rather than borrowing a candidate's identity.
    Caller-ordered peaks remain diagnostics. The daily bound makes no claim
    about actual intraday settlement order or economic/default loss.
    """
    currency = cash_payload.get("currency")
    report = {"basis": "conservative_daily_gross_asset_upper_bounds_no_netting",
              "currency": currency, "complete_attribution": False, "admitted": False,
              "components": [], "scope_comparisons": [], "restricted_deposit_liabilities": [],
              "customer_advance_liabilities": [], "ordered_schedule_diagnostics": None,
              "unattributed_balances": [], "blockers": [], "warnings": [
                  "counterparty_group_membership_is_declared_not_verified",
                  "supplied_schedule_is_not_actual_intraday_settlement_evidence",
                  "same_day_increases_precede_decreases_for_conservative_admission_not_settlement_replay",
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
    for field, category in OPENING.items():
        for identity, amount in cash_payload.get(field, {}).items():
            value = Decimal(amount)
            if value:
                report["unattributed_balances"].append({"kind": category, "balance_id": identity,
                    "amount": text_number(value), "currency": currency, "opening": True})
                hold("ledger_exposure_baseline_attribution_missing")

    def replay(*, conservative):
        balances, identities, peaks, scope_peaks = {}, {}, {}, {}
        current, changed = Counter(), set()

        def witness(event):
            value = {"event_id": event["event_id"], "on": event["on"]}
            if conservative:
                value["order_basis"] = "same_day_increases_before_decreases_not_actual_settlement"
            return value

        def update(category, balance_id, delta, event):
            keys = event_owners.get(event["event_id"], [])
            mapping = owners.get(keys[0]) if len(keys) == 1 else None
            expected = "supplier" if category == "supplier_prepaid" else "buyer"
            if mapping is None or mapping["category"] != expected:
                if not conservative:
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
            if balances[key] > peaks.get(key, {}).get("amount", ZERO):
                peaks[key] = {"amount": balances[key], "witness": witness(event)}
            if category not in LIABILITIES:
                for scope, member in (("entity", mapping["entity_id"]), ("group", mapping["group_id"]),
                                      ("site", mapping["site_id"]), ("currency", mapping["currency"])):
                    scope_key = (scope, member, currency)
                    current[scope_key] += delta
                    changed.add(scope_key)

        # Chronology always remains intact. Only date-only admission places
        # increases first within each day; event IDs give deterministic witnesses.
        ordered = sorted(events, key=(lambda row: (row["on"], row["kind"] not in INCREASE_KINDS, row["event_id"]))
                         if conservative else lambda row: row["on"])
        for event in ordered:
            changed.clear()
            kind = event["kind"]
            value = Decimal(event["amount"])
            if kind in {"deposit_apply", "advance_apply"}:
                update("buyer_receivable", event["invoice_id"], -value, event)
                category = "restricted_deposit_liability" if kind == "deposit_apply" else "customer_advance_liability"
                update(category, event["advance_account"], -value, event)
            elif kind in BALANCE_KINDS:
                category, field, sign = BALANCE_KINDS[kind]
                update(category, event[field], value * sign, event)
            # Scope balances add at each prefix before the maximum is taken.
            for key in changed:
                amount = current[key]
                if amount > scope_peaks.get(key, {}).get("amount", ZERO):
                    scope_peaks[key] = {"amount": amount, "witness": witness(event)}
        packet = {"components": [], "restricted_deposit_liabilities": [], "customer_advance_liabilities": []}
        for key in sorted(peaks):
            mapping, peak = identities[key], peaks[key]
            packet[LIABILITIES.get(key[0], "components")].append({"kind": key[0], "balance_id": key[1],
                **{field: mapping[field] for field in ("owner_id", "entity_id", "group_id", "site_id", "lot_id", "currency")},
                "peak_amount": text_number(peak["amount"]), "witness": peak["witness"]})
        return packet, scope_peaks

    diagnostic, ordered_peaks = replay(conservative=False)
    report["ordered_schedule_diagnostics"] = {"basis": "declared_same_day_order_not_settlement_evidence",
        **diagnostic, "scope_peaks": [{"scope": key[0], "member_id": key[1], "currency": key[2],
            "peak_amount": text_number(peak["amount"]), "witness": peak["witness"]}
            for key, peak in sorted(ordered_peaks.items())]}
    conservative, scope_peaks = replay(conservative=True)
    report.update(conservative)
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
