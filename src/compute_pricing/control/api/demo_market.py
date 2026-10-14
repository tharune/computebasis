"""Small, source-bound demo display; no market-completeness or price authority."""
from .market import market_index
from compute_pricing.control.curves import observed_commitment_curves

DISPLAY_SOURCES = frozenset({"getdeploying", "ecb", "energinet_day_ahead"})


def demo_market(store, policies, plan):
    selected = [row for row in plan if row["source_id"] in DISPLAY_SOURCES]
    admitted = {name: policy for name, policy in policies.items() if name in DISPLAY_SOURCES}

    class SelectedDisplay:
        def latest_collection_scan(self):
            return store.requested_collection_scan(selected)

        def latest_refresh(self):
            return None

    packet = market_index(SelectedDisplay(), admitted, selected, row_limit=800)
    packet["sources"] = [row for row in packet["sources"] if row["source_id"] in DISPLAY_SOURCES]
    packet["commitment_curves"] = observed_commitment_curves(packet, group_limit=512, node_limit=1024)
    packet["coverage"].update({"population": "configured_public_demo_display_scopes",
        "selection_method": "latest_per_explicit_source_and_filter",
        "requested_scope_count": len(selected), "full_history_integrity_scan": False,
        "all_market_sources": False, "selection_is_benchmark_weighting": False})
    packet["warnings"].append("demo_display_population_is_not_a_complete_market_or_pricing_admission")
    return packet
