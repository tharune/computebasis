"""Independent opt-in public pricing scenarios; none describe a real provider."""
from copy import deepcopy

SCHEMA = "pricing-demo/1.0.0"


def _case(model, memory, nodes, gpus, start, end, *, level, rate, buyer, util, collection, cash,
          fixed, risk, idle, load, shared, pue, tariff, power_util, mode, deposit, low, high,
          supplier_date, balance_date, invoice_date, receipt_date, cost_date, fee_date, writeoff_date):
    stronger = level == "strong"
    weak = level == "weak"
    return {
        "schema_version": SCHEMA, "classification": "synthetic",
        "provider": {"id": "illustrative-provider:" + level, "label": "Invented " + level + " provider",
            "credit_score": "94" if stronger else "68" if not weak else "32",
            "credit_band": level, "uptime_fraction": "0.9995" if stronger else "0.978" if not weak else "0.91",
            "sla_fraction": "0.999" if stronger else "0.97" if not weak else "0.9",
            "response_hours": "1" if stronger else "8" if not weak else "24",
            "compliance": "Illustrative SOC 2 Type II claim" if stronger else "Illustrative controls review" if not weak else "No independently verified attestation",
            "privacy": "Dedicated tenant; asserted isolation", "evidence_basis": "Independently invented demonstration claims",
            "ratings": {"certification": 4 if stronger else 3 if not weak else 0,
                "dc_tier": 4 if stronger else 3 if not weak else 1, "sla": 4 if stronger else 3 if not weak else 1,
                "delivery": 4 if stronger else 2 if not weak else 0, "credit": 4 if stronger else 3 if not weak else 0,
                "responsiveness": 4 if stronger else 3 if not weak else 0}},
        "capacity": {"model": model, "memory_gib": memory, "gpus_per_node": gpus, "node_count": nodes,
            "country_code": "US" if stronger else "DE" if not weak else "CA",
            "location": "Example North region" if stronger else "Example Central region" if not weak else "Example West region",
            "colocation": "Invented Harbor facility" if stronger else "Invented Cedar facility" if not weak else "Invented Ridge facility",
            "ownership": "owned" if stronger else "leased", "starts_at": start, "ends_at": end,
            "cpu_cores": "64", "ram_gib": "512", "network_gbps": "25", "interconnect": "Explicitly declared fabric"},
        "pricing": {"supplier_rate": rate, "rate_type": "fixed" if stronger or weak else "variable",
            "variable_low": low, "variable_high": high, "buyer_rate": buyer, "billed_utilization": util,
            "collection_share": collection, "fee_on_collected": "0.012" if stronger else "0.02" if not weak else "0.025",
            "fee_on_gross": "0.004" if stronger else "0.007" if not weak else "0.005",
            "required_margin": "0.14" if stronger else "0.16", "target_margin": "0.22" if stronger else "0.25" if not weak else "0.28",
            "tick_size": "0.01", "fixed_operating_cost": fixed, "risk_allowance_per_gpu_hour": risk,
            "risk_cost_owner": "demo:declared-capital-budget", "discount_apr": "0.08",
            "power": {"idle_watts_per_gpu": idle, "load_watts_per_gpu": load, "shared_it_watts": shared,
                "pue": pue, "utilization": power_util, "tariff_per_kwh": tariff,
                "inclusion": "excluded", "cost_owner": "allocated-power-cost/1.0.0", "payer": "broker"}},
        "settlement": {"mode": mode, "buyer_label": "Invented demonstration buyer", "down_payment_fraction": deposit,
            "financing_apr": "0.08" if stronger else "0.10" if not weak else "0.12",
            "provider_collateral_usd": "0" if stronger else "250" if not weak else "150",
            "collateral_owner": "provider_restricted_performance_security",
            "vesting_basis": "After explicit verification of delivered service; proposal only",
            "prefunded_principal": "450" if weak else "0", "asset_kind": "bank_deposit", "asset_unit": "USD",
            "asset_price_usd": "1", "liquidity": "liquid", "depeg_status": "not_applicable",
            "yield_apr": "0.03", "yield_share_provider": "0.2", "yield_share_broker": "0.3", "yield_share_buyer": "0.5",
            "yield_access": "accrued_only", "release_authorized": True, "refund_at_end": True,
            "buffer_hours": 24 if weak else 0, "collateral_fraction": "0.25" if weak else "0",
            "service_fraction": "1", "service_basis": "delivered"},
        "treasury": {"opening_cash": cash, "minimum_cash": "1000" if stronger else "250" if not weak else "30",
            "supplier_payment_on": supplier_date, "supplier_balance_on": balance_date,
            "buyer_invoice_on": invoice_date, "buyer_receipt_on": receipt_date, "operating_cost_on": cost_date,
            "fees_on": fee_date, "writeoff_on": writeoff_date},
        "surface": {"tenor_days": ["1", "3", "7", "14", "30", "45", "60", "90", "180", "365"], "collection_shocks": ["0", "0.05", "0.15"],
                    "annual_volatility": "0.35" if stronger else "0.55" if not weak else "0.8",
                    "shocks": ["-3", "-2", "-1", "0", "1", "2", "3"]},
    }


def demo_scenarios():
    cases = [
        {"id": "invented-h100-strong", "label": "H100 · strong provider",
         "summary": "High declared uptime and credit; partial supplier prepayment with service milestones.",
         "inputs": _case("H100", "80", 2, 8, "2027-02-01T00:00:00Z", "2027-03-03T00:00:00Z", level="strong",
             rate="2.45", buyer="4.4", util="0.88", collection="0.995", cash="40000", fixed="480", risk="0.03",
             idle="90", load="430", shared="400", pue="1.19", tariff="0.105", power_util="0.72",
             mode="milestone", deposit="0.3", low="2.45", high="2.45", supplier_date="2027-01-30",
             balance_date="2027-03-03", invoice_date="2027-03-03", receipt_date="2027-03-05", cost_date="2027-02-01",
             fee_date="2027-03-05", writeoff_date="2027-03-05")},
        {"id": "invented-l40s-balanced", "label": "L40S · balanced provider",
         "summary": "Moderate declared service/credit; variable supply range and a bounded deposit.",
         "inputs": _case("L40S", "48", 1, 8, "2027-02-08T00:00:00Z", "2027-02-22T00:00:00Z", level="balanced",
             rate="0.83", buyer="1.55", util="0.82", collection="0.97", cash="3500", fixed="90", risk="0.07",
             idle="60", load="300", shared="160", pue="1.33", tariff="0.13", power_util="0.6",
             mode="milestone", deposit="0.15", low="0.72", high="1.05", supplier_date="2027-02-07",
             balance_date="2027-02-22", invoice_date="2027-02-22", receipt_date="2027-02-24", cost_date="2027-02-08",
             fee_date="2027-02-24", writeoff_date="2027-02-24")},
        {"id": "invented-a4000-restricted", "label": "A4000 · hourly restricted escrow",
         "summary": "Weak declared quality requires hourly verified vesting, customer-owned principal and a security proposal.",
         "inputs": _case("A4000", "16", 2, 4, "2027-02-15T00:00:00Z", "2027-02-18T00:00:00Z", level="weak",
             rate="0.23", buyer="0.64", util="0.9", collection="1", cash="130", fixed="20", risk="0.09",
             idle="35", load="150", shared="80", pue="1.48", tariff="0.16", power_util="0.65",
             mode="hourly_escrow", deposit="0", low="0.23", high="0.23", supplier_date="2027-02-15",
             balance_date="2027-02-18", invoice_date="2027-02-15", receipt_date="2027-02-18", cost_date="2027-02-15",
             fee_date="2027-02-18", writeoff_date="2027-02-18")},
    ]
    return deepcopy(cases)
