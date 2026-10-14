"""Bind API pricing to retained source evidence and the current saved policy.

The offline pricing kernel permits explicit hypothetical inputs. An API request
cannot turn those inputs, inline rights, or old policy versions into admitted
market evidence merely by naming a source.
"""
from copy import deepcopy
import datetime as dt

from compute_pricing.control._numbers import digest
from compute_pricing.control.domain import parse_market_observation, parse_policy_snapshot, utc_instant
from .market import _collection_packet


DISPLAY_FIELDS = frozenset({"snapshot_id", "index_stale", "execution_enabled"})
VERSION = "retained-evidence-boundary/1.0.0"


def _observation(row):
    return parse_market_observation({key: value for key, value in row.items() if key not in DISPLAY_FIELDS}).to_dict()


class PricingProvenance:
    def __init__(self, store, policies, repository, *, clock=None):
        self.store, self.policies, self.repository = store, policies, repository
        self.clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))

    def blockers(self, payload):
        claim = payload.get("pricing_provenance")
        if claim is None:
            return "declared_scenario", None, ["api_pricing_provenance_not_bound"]
        if (not isinstance(claim, dict) or set(claim) != {"mode", "policy_revision"}
                or claim["mode"] not in {"declared_scenario", "retained_market"}):
            raise ValueError("invalid_pricing_provenance")
        mode, revision = claim["mode"], claim["policy_revision"]
        if mode == "declared_scenario":
            if revision is not None:
                raise ValueError("scenario_policy_revision_must_be_null")
            return mode, None, ["api_declared_scenario_not_admitted_source_evidence"]
        if not isinstance(revision, str) or len(revision) != 64 or any(c not in "0123456789abcdef" for c in revision):
            raise ValueError("saved_policy_revision_required")
        market = payload.get("market")
        if not isinstance(market, dict) or not isinstance(market.get("observations"), list):
            raise ValueError("pricing_market_required")
        reasons, now = set(), self.clock()
        policy = parse_policy_snapshot(market.get("policy")).to_dict()
        saved = self.repository.get(revision)
        if saved is None:
            reasons.add("saved_policy_revision_not_found")
        else:
            if saved["document"]["policy"] != policy:
                reasons.add("inline_policy_does_not_match_saved_revision")
            head = self.repository.head(saved["policy_id"])
            if head is None or head["revision"] != revision:
                reasons.add("saved_policy_revision_is_not_current_head")
        if policy["model_version"] != "inverse-linear/1.0.0":
            reasons.add("saved_policy_model_not_supported")
        if utc_instant(policy["effective_at"]) > now:
            reasons.add("saved_policy_not_yet_effective")
        if policy["expires_at"] is not None and utc_instant(policy["expires_at"]) <= now:
            reasons.add("saved_policy_expired")
        if utc_instant(market["as_of"]) > now:
            reasons.add("pricing_as_of_is_in_future")
        rules = policy["parameters"].get("benchmark", {}).get("source_rules", {})
        if not market["observations"]:
            reasons.add("retained_market_observations_required")
        cache = {}
        for row in market["observations"]:
            if not isinstance(row, dict):
                raise ValueError("invalid_market_observation")
            source = row.get("source_id")
            admitted = self.policies.get(source)
            if admitted is None:
                reasons.add("external_source_not_admitted_by_server")
            else:
                if any(admitted.blockers(scope, now) for scope in ("observe", "retain", "benchmark")):
                    reasons.add("server_source_permission_blocked")
            rule = rules.get(source, {})
            if not isinstance(rule, dict) or rule.get("enabled") is not True:
                reasons.add("source_not_enabled_by_saved_policy")
            ref = row.get("snapshot_id")
            if not isinstance(ref, str) or len(ref) != 64 or any(c not in "0123456789abcdef" for c in ref):
                reasons.add("observation_retained_snapshot_required")
                continue
            if ref not in cache:
                snapshot = self.store.get(ref)
                if snapshot is None:
                    cache[ref] = (None, {})
                elif snapshot.to_dict()["document"].get("kind") != "market_collection":
                    cache[ref] = (snapshot.to_dict()["document"], {})
                else:
                    packet, output, _, _ = _collection_packet(snapshot)
                    indexed = {}
                    for item in output.get("observations", []):
                        indexed.setdefault(item.get("id"), []).append(item)
                    cache[ref] = (packet["document"], indexed)
            document, indexed = cache[ref]
            if (document is None or document.get("kind") != "market_collection"
                    or document.get("input", {}).get("source_id") != source
                    or document.get("output", {}).get("source_id") != source):
                reasons.add("observation_retained_snapshot_mismatch")
                continue
            output = document["output"]
            if output.get("execution_enabled") is not False:
                reasons.add("observation_retained_snapshot_mismatch")
                continue
            candidates = indexed.get(row.get("id"), [])
            if len(candidates) != 1 or _observation(candidates[0]) != _observation(row):
                reasons.add("observation_differs_from_retained_evidence")
            captured = output.get("raw_metadata", {}).get("captured_at")
            try:
                observed, expires, capture = utc_instant(row["observed_at"]), utc_instant(row["expires_at"]), utc_instant(captured)
                if admitted is not None and (not 0 <= (now - observed).total_seconds() < admitted.max_age_s
                        or not 0 <= (now - capture).total_seconds() < admitted.max_age_s or expires <= now):
                    reasons.add("retained_observation_not_currently_fresh")
            except (ValueError, TypeError, KeyError):
                reasons.add("retained_observation_freshness_unverified")
        return mode, revision, sorted(reasons)

    def apply(self, payload, output):
        mode, revision, blockers = self.blockers(payload)
        result = deepcopy(output)
        result["pricing_provenance"] = {"mode": mode, "policy_revision": revision,
            "boundary_version": VERSION, "status": "held" if blockers else "retained_evidence_bound",
            "source_evidence_eligible": not blockers, "calibration_verified": False,
            "blockers": blockers}
        if blockers:
            result["scenario_diagnostics"] = {"benchmark": deepcopy(result.get("benchmark")),
                "basis": "hypothetical_caller_inputs_not_qualified_market_evidence"}
            benchmark = deepcopy(result.get("benchmark") or {})
            benchmark.update(status="held", price=None, reason="api_source_evidence_not_bound")
            result["benchmark"] = benchmark
            result["bid"] = None
            result["status"] = "held"
            result["hold_reasons"] = sorted(set(result.get("hold_reasons", [])) | set(blockers))
        result["firm_price_eligible"] = result["executable"] = False
        result.setdefault("versions", {})["api_provenance"] = VERSION
        result["decision_hash"] = digest({key: value for key, value in result.items() if key != "decision_hash"})
        return result
