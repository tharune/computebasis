"""A bounded in-memory simulation book with an explicitly separate clock."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, localcontext
import hashlib
import json
import math
import random
import threading
import time

from compute_pricing.control._numbers import calculation_precision


SIMULATION_DATE = "2032-06-01"
HISTORY_LIMIT = 128
CATCHUP_LIMIT = 8
SCENARIOS = frozenset({"price_war", "supply_shock", "downgrade"})


def _serial(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {key: _serial(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serial(item) for item in value]
    return value


def _total(values):
    values = list(values)
    with localcontext() as context:
        context.prec = calculation_precision([format(value, "f") for value in values]) + 8
        return sum(values, Decimal(0))


def _mean(values):
    values = list(values)
    if not values:
        return None
    with localcontext() as context:
        context.prec = calculation_precision([format(value, "f") for value in values]) + 8
        return _total(values) / len(values)


def _weighted_mean(pairs):
    pairs = [(value, weight) for value, weight in pairs if weight > 0]
    if not pairs:
        return None
    inputs = [[format(value, "f"), str(weight)] for value, weight in pairs]
    with localcontext() as context:
        context.prec = calculation_precision(inputs) + 12
        return _total(value * weight for value, weight in pairs) / sum(weight for _, weight in pairs)


def _ratio(numerator, denominator):
    if not denominator:
        return None
    with localcontext() as context:
        context.prec = calculation_precision([str(numerator), str(denominator)]) + 8
        return Decimal(numerator) / Decimal(denominator)


def _basis(lowest_price, cost):
    if not lowest_price:
        return None
    with localcontext() as context:
        context.prec = calculation_precision([format(lowest_price, "f"), format(cost, "f")]) + 8
        return cost / lowest_price - 1


def _median(values):
    values = sorted(values)
    if not values:
        return None
    middle = len(values) // 2
    return values[middle] if len(values) % 2 else _mean(values[middle - 1:middle + 1])


def _clock_value(clock):
    value = clock()
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("simulation clock must return a finite numeric value")
    return value


class QuoteBook:
    """Deterministic synthetic ticks; no disk, network, holdings or execution.

    Wall-clock time determines when bounded simulation ticks are due. All dated
    quote arithmetic uses the independently declared simulation date instead.
    """

    def __init__(self, seed_value=4271, clock=time.monotonic, tick_seconds=3, policy=None):
        if isinstance(seed_value, bool) or not isinstance(seed_value, int) or not 0 <= seed_value < 2**32:
            raise ValueError("bounded integer simulation seed required")
        if (isinstance(tick_seconds, bool) or not isinstance(tick_seconds, (int, float))
                or not math.isfinite(tick_seconds) or not .25 <= tick_seconds <= 3600):
            raise ValueError("finite tick duration between .25 and 3600 seconds required")
        if not callable(clock):
            raise ValueError("simulation clock must be callable")
        self._lock = threading.RLock()
        self._clock, self._period = clock, tick_seconds
        from .scoring import validate_policy
        self._seed, self._policy = seed_value, validate_policy(deepcopy(policy))
        self._date = date.fromisoformat(SIMULATION_DATE)
        self._last_clock = _clock_value(clock)
        self._epoch, self._alert_number = 0, 0
        from compute_pricing.control.api.book_policy import default_document
        self._policy_document = default_document(self._policy)
        self._economics = deepcopy(self._policy_document["economics"])
        self._policy_revision, self._policy_history = 0, {}
        self._reset_state()
        self._policy_history[0] = self._policy_record(None)

    def _reset_state(self):
        from .population import build_population
        providers, quotes = build_population(self._seed, as_of=self._date.isoformat())
        self._providers, self._quotes = deepcopy(providers), deepcopy(quotes)
        self._random = random.Random(self._seed ^ 0x5A713C)
        self._tick, self._paused, self._scenario = 0, False, None
        self._history, self._alerts = [], []
        self._catchup_clamped = False
        self._record()

    def _simulation_time(self):
        return datetime.combine(self._date, datetime.min.time(), timezone.utc) + timedelta(minutes=self._tick)

    def _as_of(self):
        return self._simulation_time().date()

    def _time_text(self):
        return self._simulation_time().isoformat().replace("+00:00", "Z")

    def _move_prices(self):
        with localcontext() as context:
            context.prec = 64
            for quote in self._quotes:
                if quote.get("price") is None:
                    continue
                delta = Decimal(self._random.randrange(-5, 6) * 3) / 10000
                old = Decimal(quote["price"])
                new = max(Decimal("0.000001"), old * (1 + delta)).quantize(Decimal("0.000001"))
                if new != old:
                    quote["price"] = format(new, "f")
                    quote["changed_tick"] = self._tick
                    quote["updated"] = self._time_text()

    def _apply_scenario(self, scenario):
        with localcontext() as context:
            context.prec = 64
            if scenario == "price_war":
                for quote in self._quotes:
                    if quote.get("price") is not None:
                        quote["price"] = format(Decimal(quote["price"]) * Decimal("0.96"), "f")
                        quote["changed_tick"] = self._tick
                        quote["updated"] = self._time_text()
                detail = "Declared simulated asks reduced by four percent."
            elif scenario == "supply_shock":
                for quote in self._quotes:
                    if quote.get("nodes") is not None:
                        quote["nodes"] = quote["nodes"] * 3 // 4
                        if not quote["nodes"]:
                            quote["active"] = False
                        quote["changed_tick"] = self._tick
                        quote["updated"] = self._time_text()
                detail = "One quarter of each quoted node capacity removed, rounding remaining nodes down."
            else:
                for provider in self._providers:
                    # A missing rating remains missing rather than becoming a
                    # known low rating through a stress-control click.
                    provider["tiers"] = {key: None if value is None else 0
                                         for key, value in provider["tiers"].items()}
                detail = "Known ratings changed to the weakest invented strength level; unknowns preserved."
        self._alert_number += 1
        self._alerts.append({"n": self._alert_number, "time": self._time_text(),
                             "level": "info" if scenario == "price_war" else "warn", "text": detail,
                             "tick": self._tick, "scenario": scenario,
                             "message": detail, "simulated": True})
        self._alerts = self._alerts[-32:]

    def _build_frame(self, *, scorecard=None, economics=None):
        from .population import BASE_PRICE, MODELS
        from .scoring import CATEGORIES, GRADES, grade_for, quality_score, quote_economics

        when = self._as_of()
        selected_policy = self._policy if scorecard is None else scorecard
        selected_economics = self._economics if economics is None else economics
        provider_rows, provider_map = [], {}
        for raw in self._providers:
            tiers = raw.get("tiers", {})
            unknown = set(CATEGORIES) - set(tiers) or any(tiers.get(key) is None for key in CATEGORIES)
            score = None if unknown else quality_score(tiers, selected_policy)
            graded = None if score is None else grade_for(score, selected_policy)
            row = {**deepcopy(raw), "score": None if score is None else float(score),
                   "score_exact": None if score is None else format(score, "f"),
                   "grade": None if graded is None else graded[0],
                   "grade_premium": None if graded is None else format(graded[1], "f"),
                   "synthetic": True, "simulated": True, "source_evidence_eligible": False,
                   "firm_price_eligible": False, "execution_enabled": False}
            provider_rows.append(row)
            provider_map[raw["id"]] = (row, graded)
        quotes, gaps = [], {}
        for raw in self._quotes:
            provider, graded = provider_map[raw["provider_id"]]
            computed = _serial(quote_economics(raw, grade=graded,
                reference=BASE_PRICE[raw["gpu"]], as_of=when.isoformat(), assumptions=selected_economics))
            missing = computed["missing"]
            row = {**deepcopy(raw), **computed, "provider": provider["name"],
                   "provider_name": provider["name"], "quality_score": provider["score"],
                   "quality_score_exact": provider["score_exact"],
                   "missing_fields": missing, "missing": missing, "missing_count": len(missing),
                   "reasons": deepcopy(computed["ineligible_reasons"]),
                   "financing": computed["financing_cost_per_gpu_hour"],
                   "exposure": computed["exposure_charge"],
                   "days_to_expiry": None if raw.get("expires") is None else (date.fromisoformat(raw["expires"]) - when).days,
                   "price_rank": None, "risk_rank": None,
                   "synthetic": True, "simulated": True, "source_evidence_eligible": False,
                   "firm_price_eligible": False, "execution_enabled": False}
            quotes.append(row)
            row["units"].update(financing="USD_per_gpu_hour", exposure="USD_per_gpu_hour")
            for name in missing:
                gaps[name] = gaps.get(name, 0) + 1

        def live(row):
            # Active here is a synthetic quote-validity state, not live vendor evidence.
            expires = row.get("expires")
            return row.get("active", True) and row["nodes"] > 0 and expires is not None and date.fromisoformat(expires) > when

        live_rows = [row for row in quotes if live(row)]
        models, supply = [], {}
        for model in MODELS:
            native = [row for row in quotes if row["gpu"] == model]
            current = [row for row in native if live(row)]
            eligible = [row for row in current if row.get("eligible") is True and row.get("risk_adjusted") is not None]
            priced = [row for row in current if row.get("price") is not None]
            cheapest = min(priced, key=lambda row: (Decimal(row["price"]), row["id"]), default=None)
            best = min(eligible, key=lambda row: (Decimal(row["risk_adjusted"]), row["id"]), default=None)
            for rank, row in enumerate(sorted(priced, key=lambda row: (Decimal(row["price"]), row["id"])), 1):
                row["price_rank"] = rank
            for rank, row in enumerate(sorted(eligible, key=lambda row: (Decimal(row["risk_adjusted"]), row["id"])), 1):
                row["risk_rank"] = rank

            def leg(row):
                if row is None:
                    return None
                values = {key: row.get(key) for key in
                        ("id", "provider", "provider_id", "grade", "price", "risk_adjusted",
                         "missing", "missing_fields", "ineligible_reasons", "eligible", "currency",
                         "price_unit", "simulated", "source_evidence_eligible", "firm_price_eligible",
                         "execution_enabled")}
                values["missing"] = row["missing_count"]
                return values

            basis = None if best is None or cheapest is None else _basis(Decimal(cheapest["price"]), Decimal(best["risk_adjusted"]))
            prices = [Decimal(row["price"]) for row in priced]
            gpus = sum(row["gpus"] for row in current)
            models.append({"gpu": model, "model": model, "reference": BASE_PRICE[model],
                "reference_basis": "independently_invented_simulation_anchor_not_market_midpoint",
                "currency": "USD", "price_unit": "gpu_hour", "best": leg(best),
                "cheapest": leg(cheapest), "quote_count": len(native), "quotes": len(current),
                "eligible_count": len(eligible), "eligible": len(eligible), "gpus": gpus,
                "basis": _serial(basis), "basis_unit": "fraction_above_lowest_displayed_native_offer",
                "basis_definition": "best_eligible_exposure_cost_divided_by_lowest_displayed_native_offer_minus_one",
                "basis_weight": gpus, "basis_weight_unit": "current_synthetic_quoted_gpus",
                "low": _serial(min(prices)) if prices else None, "median": _serial(_median(prices)),
                "high": _serial(max(prices)) if prices else None, "simulated": True})
            supply[model] = {grade: sum(row["gpus"] for row in current if (row["grade"] or "unknown") == grade)
                             for grade in (*GRADES, "unknown")}
        grade_mix = {grade: {"providers": sum((row["grade"] or "unknown") == grade for row in provider_rows),
                            "quotes": sum((row["grade"] or "unknown") == grade for row in live_rows),
                            "gpus": sum(row["gpus"] for row in live_rows if (row["grade"] or "unknown") == grade)}
                     for grade in (*GRADES, "unknown")}
        eligible_count = sum(row.get("eligible") is True for row in live_rows)
        expiry_counts = {"Expired": 0, "Within 7 days": 0, "Within 30 days": 0,
                         "Later": 0, "Unknown": 0}
        for quote in quotes:
            if quote.get("expires") is None:
                expiry_counts["Unknown"] += 1
                continue
            days = (date.fromisoformat(quote["expires"]) - when).days
            label = "Expired" if days <= 0 else "Within 7 days" if days <= 7 else "Within 30 days" if days <= 30 else "Later"
            expiry_counts[label] += 1
        completeness = []
        for count in sorted({row["missing_count"] for row in quotes}):
            selected = [row for row in quotes if row["missing_count"] == count]
            completeness.append({"missing": count, "label": "Complete declared inputs" if not count else str(count) + " missing fields",
                "by_grade": {grade: sum((row["grade"] or "unknown") == grade for row in selected) for grade in (*GRADES, "unknown")},
                "quotes": len(selected)})
        for provider in provider_rows:
            selected = [row for row in quotes if row["provider_id"] == provider["id"]]
            current = [row for row in selected if live(row)]
            indices = [_ratio(Decimal(row["price"]), Decimal(BASE_PRICE[row["gpu"]]))
                       for row in current if row["price"] is not None]
            provider.update(quotes=len(current), gpus=sum(row["gpus"] for row in current),
                missing_average=_serial(_mean(Decimal(row["missing_count"]) for row in selected)),
                eligible_share=_serial(_ratio(sum(row["eligible"] for row in current), len(current))),
                price_index=_serial(_mean(indices)))
        nodes = sum(row["nodes"] for row in live_rows)
        gpus = sum(row["gpus"] for row in live_rows)
        supported_models = [row for row in models if row["basis"] is not None and row["gpus"] > 0]
        basis_gpus = sum(row["gpus"] for row in supported_models)
        aggregate_basis = _weighted_mean((Decimal(row["basis"]), row["gpus"]) for row in supported_models)
        known_contracts = [row for row in live_rows if row["contract_value"] is not None]
        contract_value = _total(Decimal(row["contract_value"]) for row in known_contracts)
        kpis = {"providers": len(provider_rows), "providers_total": len(provider_rows),
            "providers_quoting": len({row["provider_id"] for row in live_rows}), "quotes": len(quotes),
            "live_quotes": len(live_rows), "eligible_quotes": eligible_count,
            "held_quotes": len(quotes) - eligible_count, "quoted_nodes": nodes, "quoted_gpus": gpus,
            "gpus": gpus, "contract_value": _serial(contract_value),
            "contract_value_basis": "known_components_only_active_synthetic_quotes_not_owned_positions",
            "contract_value_known_components": len(known_contracts),
            "contract_value_unknown_components": len(live_rows) - len(known_contracts),
            "contract_value_complete": len(known_contracts) == len(live_rows),
            "eligible_share": _serial(_ratio(eligible_count, len(live_rows))),
            "basis": _serial(aggregate_basis), "models_with_basis": len(supported_models),
            "basis_weighting": "current_synthetic_quoted_gpu_count_supported_models_only",
            "basis_supported_gpus": basis_gpus, "basis_total_quoted_gpus": gpus,
            "basis_unsupported_gpus": gpus - basis_gpus,
            "basis_weight_coverage": _serial(_ratio(basis_gpus, gpus)),
            "models": len(models), "cheapest_is_ineligible": sum(row["cheapest"] is not None and not row["cheapest"]["eligible"] for row in models)}
        return {"kpis": kpis, "models": models, "grade_mix": grade_mix, "supply": supply,
                "expiry": [{"label": label, "quotes": count} for label, count in expiry_counts.items()],
                "completeness": completeness, "field_gaps": dict(sorted(gaps.items())),
                "providers": provider_rows, "quotes": quotes,
                "assumptions": {"classification": "independently_invented_simulation",
                    "reference_prices": dict(BASE_PRICE), "reference_currency": "USD",
                    "reference_unit": "gpu_hour", "scorecard_policy": deepcopy(selected_policy),
                    "weights": deepcopy(selected_policy["weights"]),
                    "quote_model_assumptions": deepcopy(quotes[0]["assumptions"]) if quotes else None,
                    "basis_definition": "current_synthetic_gpu_weighted_mean_supported_model_best_eligible_exposure_cost_over_lowest_native_offer_minus_one",
                    "basis_is_market_benchmark": False,
                    "rank_basis": "current_synthetic_quotes_per_model_ordinal_ties_by_quote_id",
                    "supply_basis": "synthetic_quoted_capacity_not_owned_inventory",
                    "calibration_verified": False}}

    def _record(self, *, replace_current=False, frame=None):
        self._frame = self._build_frame() if frame is None else frame
        point = {"tick": self._tick, "time": self._time_text(), "as_of": self._as_of().isoformat(),
                 "policy_revision": self._policy_revision,
                 "live": self._frame["kpis"]["live_quotes"], "gpus": self._frame["kpis"]["gpus"],
                 "eligible_share": self._frame["kpis"]["eligible_share"], "basis": self._frame["kpis"]["basis"],
                 "models": {row["gpu"]: {"cheapest": row["cheapest"]["price"] if row["cheapest"] else None,
                     "best": row["best"]["risk_adjusted"] if row["best"] else None,
                     "basis": row["basis"], "median": row["median"], "reference": row["reference"]}
                     for row in self._frame["models"]}}
        if replace_current and self._history and self._history[-1]["tick"] == self._tick:
            self._history[-1] = point
        else:
            self._history.append(point)
        self._history = self._history[-HISTORY_LIMIT:]

    def _assemble(self):
        series = {name: [point[name] for point in self._history] for name in
                  ("live", "gpus", "eligible_share", "basis")}
        series.update(ticks=[point["tick"] for point in self._history],
                      times=[point["time"] for point in self._history],
                      policy_revisions=[point["policy_revision"] for point in self._history])
        series["models"] = {row["gpu"]: {name: [point["models"][row["gpu"]][name] for point in self._history]
                              for name in ("cheapest", "best", "basis", "median", "reference")}
                            for row in self._frame["models"]}
        return {**self._frame, "meta": {"schema_version": "synthetic-quote-book/1.0",
            "as_of": self._as_of().isoformat(), "time": self._time_text(),
            "as_of_basis": "simulation_assessment_date_not_vendor_observation",
            "time_basis": "one_simulation_minute_per_processed_tick",
            "tick": self._tick, "paused": self._paused, "scenario": self._scenario,
            "epoch": self._epoch, "source": "Independent simulation fixture", "step_minutes": 1,
            "policy_revision": self._policy_revision, "policy_version": self._policy_document["version"],
            "tick_seconds": self._period, "seed": self._seed,
            "catchup_limit": CATCHUP_LIMIT, "catchup_clamped": self._catchup_clamped,
            "history_limit": HISTORY_LIMIT, "simulation_provenance": "independently_invented_population_and_policy",
            "simulated": True, "synthetic": True, "source_evidence_eligible": False,
            "firm_price_eligible": False, "execution_enabled": False},
            "series": series, "alerts": self._alerts, "simulated": True,
            "policy": {"revision": self._policy_revision, "document": deepcopy(self._policy_document)},
            "synthetic": True, "source_evidence_eligible": False, "inventory_verified": False,
            "firm_price_eligible": False, "execution_enabled": False}

    def _advance(self, now):
        if self._paused or now < self._last_clock:
            self._last_clock = now
            return 0
        elapsed = now - self._last_clock
        # Compare before division: an extreme finite clock jump cannot create
        # an unbounded integer conversion or a large catch-up loop.
        clamped = elapsed >= self._period * (CATCHUP_LIMIT + 1)
        ticks = CATCHUP_LIMIT if clamped else int(elapsed // self._period)
        if not ticks:
            return 0
        self._catchup_clamped = clamped
        self._last_clock = now if clamped else self._last_clock + ticks * self._period
        for _ in range(ticks):
            self._tick += 1
            self._move_prices()
            self._record()
        return ticks

    def snapshot(self):
        with self._lock:
            self._advance(_clock_value(self._clock))
            return deepcopy(self._assemble())

    def encoded(self):
        body = json.dumps(self.snapshot(), sort_keys=True, separators=(",", ":"), allow_nan=False)
        etag = 'W/"' + hashlib.sha256(body.encode("utf-8")).hexdigest() + '"'
        return etag, body

    def etag(self):
        return self.encoded()[0]

    def _policy_record(self, predecessor):
        return {"revision": self._policy_revision, "predecessor_revision": predecessor,
                "document": deepcopy(self._policy_document), "tick": self._tick,
                "epoch": self._epoch, "applied_at_simulation_time": self._time_text(),
                "simulated": True, "source_evidence_eligible": False, "execution_enabled": False}

    def read_policy(self, revision=None):
        from compute_pricing.control.api.book_policy import BookPolicyNotFound, MAX_REVISIONS
        with self._lock:
            selected = self._policy_revision if revision is None else revision
            if type(selected) is not int or selected not in self._policy_history:
                raise BookPolicyNotFound("book policy revision not found in this process")
            history = [{key: record[key] for key in ("revision", "predecessor_revision", "tick", "epoch", "applied_at_simulation_time")}
                       | {"version": record["document"]["version"]} for record in self._policy_history.values()]
            return deepcopy({"schema_version": "book-policy-state/1.0", "current_revision": self._policy_revision,
                "record": self._policy_history[selected], "history": history, "maximum_revisions": MAX_REVISIONS,
                "storage": "process_memory_only", "simulated": True, "source_evidence_eligible": False,
                "firm_price_eligible": False, "execution_enabled": False})

    def _policy_candidate(self, expected_revision, document):
        from compute_pricing.control.api.book_policy import BookPolicyConflict, validate_document
        if type(expected_revision) is not int or expected_revision != self._policy_revision:
            raise BookPolicyConflict("book policy revision changed")
        candidate = validate_document(document)
        if candidate["policy_id"] != self._policy_document["policy_id"]:
            raise ValueError("book policy identity cannot change")
        return candidate

    def evaluate_policy(self, expected_revision, document):
        from compute_pricing.control.api.book_policy import comparison
        with self._lock:
            candidate = self._policy_candidate(expected_revision, document)
            after = self._build_frame(scorecard=candidate["scorecard"], economics=candidate["economics"])
            return {"schema_version": "book-policy-comparison/1.0", "base_revision": self._policy_revision,
                "candidate_document": deepcopy(candidate), "context": {"tick": self._tick, "epoch": self._epoch,
                    "as_of": self._as_of().isoformat(), "time": self._time_text()},
                **comparison(self._frame, after), "book_changed": False, "simulated": True,
                "source_evidence_eligible": False, "firm_price_eligible": False, "execution_enabled": False}

    def update_policy(self, expected_revision, document):
        from compute_pricing.control.api.book_policy import (
            BookPolicyCapacity, MAX_REVISIONS, comparison, policy_version, validate_document,
        )
        with self._lock:
            candidate = validate_document(document)
            current = self._policy_history[self._policy_revision]
            if (type(expected_revision) is int and candidate == self._policy_document
                    and expected_revision in (self._policy_revision, current["predecessor_revision"])):
                return {**self.read_policy(), "changed": False, "comparison": None}
            candidate = self._policy_candidate(expected_revision, candidate)
            if policy_version(candidate["version"]) <= policy_version(self._policy_document["version"]):
                raise ValueError("book policy successor version required")
            if len(self._policy_history) >= MAX_REVISIONS:
                raise BookPolicyCapacity("book policy history is full; no revision was removed")
            after = self._build_frame(scorecard=candidate["scorecard"], economics=candidate["economics"])
            change = comparison(self._frame, after)
            predecessor = self._policy_revision
            self._policy_revision += 1
            self._policy_document = deepcopy(candidate)
            self._policy = deepcopy(candidate["scorecard"])
            self._economics = deepcopy(candidate["economics"])
            self._policy_history[self._policy_revision] = self._policy_record(predecessor)
            # Preserve previous tick/policy points. Policy changes have the same
            # synthetic timestamp and never fabricate a price tick or RNG step.
            self._record(frame=after)
            return {**self.read_policy(), "changed": True, "comparison": change}

    def control(self, action, scenario=None):
        if not isinstance(action, str) or action not in {"pause", "resume", "reset", "scenario"}:
            raise ValueError("unsupported simulation control")
        if action == "scenario" and (not isinstance(scenario, str) or scenario not in SCENARIOS):
            raise ValueError("unsupported simulation scenario")
        if action != "scenario" and scenario is not None:
            raise ValueError("scenario is allowed only with the scenario action")
        with self._lock:
            now = _clock_value(self._clock)
            self._advance(now)
            if action == "reset":
                self._epoch += 1
                self._reset_state()
                self._last_clock = now
                changed = True
            elif action == "pause":
                changed, self._paused = not self._paused, True
                self._last_clock = now
            elif action == "resume":
                changed, self._paused = self._paused, False
                if changed:
                    self._last_clock = now
            else:
                changed = scenario != self._scenario
                if changed:
                    self._apply_scenario(scenario)
                    self._scenario = scenario
                    self._record(replace_current=True)
            return {"posted": True, "changed": changed, "tick": self._tick,
                    "epoch": self._epoch,
                    "paused": self._paused, "scenario": self._scenario,
                    "simulated": True, "execution_enabled": False}
