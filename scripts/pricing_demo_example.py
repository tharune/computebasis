"""Run the three independently invented pricing demonstrations offline."""
import json

from compute_pricing.control.demo_pricing import demo_scenarios, evaluate_demo_pricing


def main():
    for case in demo_scenarios():
        result = evaluate_demo_pricing(case["inputs"])
        print(json.dumps({"scenario": case["id"], "status": result["status"],
            "purchase_ceiling": result["summary"]["purchase_ceiling"],
            "cost_recovery_sell_floor": result["summary"]["sell_floor"],
            "target_ask": result["summary"]["target_ask"],
            "cash_feasible": result["summary"]["cash_feasible"],
            "execution_enabled": result["execution_enabled"]}))


if __name__ == "__main__":
    main()
