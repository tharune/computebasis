"""A seeded market simulation that advances with the wall clock and feeds quote-book views.

Nothing here observes a real market. Provider and quote rows start from the fictional mock workbook,
are extended in its shape, and then evolve one step per `tick_seconds` of wall time. Each step draws
from an RNG derived from (seed, step number), so a run is reproducible. Every number shown is
recomputed from the current state with the workbook's formulas (see scoring.py), so a change in a
quote, a grade or a reference price shows up in every view that depends on it.
"""
from __future__ import annotations

import collections
import dataclasses
import datetime as dt
import json
import random
import statistics
import threading
import time
from typing import Any, Callable

from . import population, scoring, seed
from .population import BASE_PRICE, GRADE_PRICE_OFFSET, MODELS, grade_of

STEP = dt.timedelta(minutes=30)       # simulated market time per step
WARMUP_STEPS = 90                     # steps of history already on the charts when the book opens
HISTORY_STEPS = 150
TARGET_LIVE = 150
REVISE_PROBABILITY = 0.012            # per quote per step
SOLD_PROBABILITY = 0.004
MAX_CATCH_UP = 12                     # steps taken at once after a long gap; the clock is re-anchored beyond that
ALERT_LIMIT = 120
SCENARIOS = ("price_war", "supply_shock", "downgrade")
ACTIONS = ("pause", "resume", "reset", "scenario")
EXPIRY_BUCKETS = (("Under 7 days", 0, 7), ("7 to 14 days", 7, 14), ("15 to 30 days", 14, 30),
                  ("31 to 60 days", 30, 60), ("Over 60 days", 60, 10 ** 6))
CATEGORY_NOTE = {"certification": "certification lapsed", "responsiveness": "response times slipped",
                 "sla": "SLA terms weakened", "delivery": "a delivery slipped", "credit": "credit standing weakened",
                 "dc_tier": "facility rating dropped"}


@dataclasses.dataclass
class Pressure:
    model: str
    drift: float   # per-step multiplicative push on the model's market level
    left: int


class QuoteBook:
    def __init__(self, *, seed_value: int = 2026, clock: Callable[[], float] = time.monotonic, tick_seconds: float = 3.0):
        if tick_seconds <= 0:
            raise ValueError("tick_seconds must be positive")
        self._seed, self._clock, self._tick_seconds = seed_value, clock, tick_seconds
        self._lock = threading.RLock()
        self._epoch = 0
        self._build()

    # ----------------------------------------------------------------- state

    def _build(self) -> None:
        rng = random.Random(f"{self._seed}:init")
        start = dt.datetime.fromisoformat(seed.AS_OF + "T09:00:00")
        self.now = start - WARMUP_STEPS * STEP
        self.tick = -WARMUP_STEPS
        self._version = 0
        self.providers = population.build_providers(rng)
        # Market level by model. The warm-up path is drawn backward from exactly 1.0 at tick 0, so the
        # workbook's reference prices (and every figure that depends on them) hold at the book's start.
        back = random.Random(f"{self._seed}:warmup")
        self._warm = {model: [1.0] for model in MODELS}
        for _ in range(WARMUP_STEPS):
            for model in MODELS:
                level = self._warm[model][-1]
                self._warm[model].append(min(1.3, max(0.75, level + 0.05 * (1 - level) + back.gauss(0, 0.004))))
        self.factor = {model: self._warm[model][WARMUP_STEPS] for model in MODELS}
        self.reference_base = dict(scoring.ASSUMPTIONS["reference"])
        self._pressure: list[Pressure] = []
        self.quotes = population.seed_quotes(self.providers, self.now.date())
        for quote in self.quotes.values():  # anchor each workbook quote to where it sits against its own grade
            grade = grade_of(self.providers[quote["provider_id"]])
            quote["skew"] = quote["price"] / (BASE_PRICE[quote["gpu"]] * (1 + GRADE_PRICE_OFFSET[grade]))
        self._next_quote = len(seed.QUOTES) + 1
        for _ in range(TARGET_LIVE - len(self.quotes)):
            self._post(rng, backdate=True)
        self.alerts: collections.deque[dict[str, Any]] = collections.deque(maxlen=ALERT_LIMIT)
        self._alert_seq = 0
        self.series: collections.deque[dict[str, Any]] = collections.deque(maxlen=HISTORY_STEPS)
        self._analysis_key: tuple[int, int, int] | None = None
        self._analysis: dict[str, Any] = {}
        self._body_key: tuple[int, int, int] | None = None
        self._body: tuple[str, bytes] = ("", b"")
        self._last_basis_alert: dict[str, float | None] = {}
        self._paused_at: float | None = None
        self._origin = self._clock()
        self._steps_taken = 0
        self._record()
        for _ in range(WARMUP_STEPS):
            self._step()
        self._last_basis_alert = {model: summary["basis"] for model, summary in self._analyze()["models"].items()}
        self.alerts.clear()
        self._alert("info", "start", "Simulation started from the workbook's 38 quotes, extended to a full book.")

    def _alert(self, level: str, kind: str, text: str, **refs: Any) -> None:
        self._alert_seq += 1
        self.alerts.append({"n": self._alert_seq, "tick": self.tick, "time": self.now.isoformat(timespec="minutes"),
                            "level": level, "kind": kind, "text": text, **refs})

    def _grade(self, provider_id: str) -> str:
        return grade_of(self.providers[provider_id])

    def _reference(self, model: str) -> float | None:
        base = self.reference_base.get(model)
        return None if base is None else round(base * self.factor[model], 3)

    def _pin(self, quote: dict[str, Any]) -> None:
        """Hold a quote at its current price: later revisions drift toward this level, not back to the grade's usual one."""
        grade = self._grade(quote["provider_id"])
        quote["skew"] = quote["price"] / (BASE_PRICE[quote["gpu"]] * self.factor[quote["gpu"]] * (1 + GRADE_PRICE_OFFSET[grade]))

    def _target_price(self, quote: dict[str, Any]) -> float:
        grade = self._grade(quote["provider_id"])
        return BASE_PRICE[quote["gpu"]] * self.factor[quote["gpu"]] * (1 + GRADE_PRICE_OFFSET[grade]) * quote["skew"]

    def _name(self, provider_id: str) -> str:
        return self.providers[provider_id]["name"]

    # ------------------------------------------------------------- dynamics

    def _post(self, rng: random.Random, *, backdate: bool = False, **fixed: Any) -> dict[str, Any]:
        quote = population.new_quote(rng, self._next_quote, self.providers, self.now, self.tick, backdate=backdate,
                                     factors=self.factor, **fixed)
        self._next_quote += 1
        self.quotes[quote["id"]] = quote
        return quote

    def _revise(self, quote: dict[str, Any], rng: random.Random, price: float | None = None) -> tuple[float, float]:
        old = quote["price"]
        if price is None:
            price = old + 0.45 * (self._target_price(quote) - old) + rng.gauss(0, 0.005) * old
        price = round(price, 2)
        if price == old:
            price = round(old + rng.choice((-0.01, 0.01)), 2)
        quote["price"], quote["updated"], quote["changed_tick"] = price, self.now.date().isoformat(), self.tick
        return old, price

    def _step(self) -> None:
        self.tick += 1
        self.now += STEP
        rng = random.Random(f"{self._seed}:{self.tick}")
        running = self.tick > 0  # the workbook's own rows stay as published until the book's clock starts
        for model in MODELS:
            level = self.factor[model]
            if not running:
                self.factor[model] = self._warm[model][-self.tick]
            else:
                self.factor[model] = min(1.3, max(0.75, level + 0.05 * (1 - level) + rng.gauss(0, 0.004)))
        for pressure in list(self._pressure):
            self.factor[pressure.model] *= 1 + pressure.drift
            pressure.left -= 1
            if pressure.left <= 0:
                self._pressure.remove(pressure)

        lows = {}
        for model in MODELS:
            prices = [q["price"] for q in self.quotes.values() if q["gpu"] == model]
            lows[model] = min(prices) if prices else None
        today = self.now.date().isoformat()
        for quote in list(self.quotes.values()):
            if quote["seed"] and not running:
                continue
            if quote["expires"] is not None and quote["expires"] < today:
                del self.quotes[quote["id"]]
                self._alert("info", "expired", f'{quote["id"]} {quote["gpu"]} from {self._name(quote["provider_id"])} expired.',
                            quote=quote["id"], provider=quote["provider_id"])
            elif rng.random() < SOLD_PROBABILITY:
                del self.quotes[quote["id"]]
                self._alert("info", "sold_out", f'{quote["id"]} {quote["gpu"]} from {self._name(quote["provider_id"])} is no longer available.',
                            quote=quote["id"], provider=quote["provider_id"])
            elif rng.random() < REVISE_PROBABILITY:
                old, new = self._revise(quote, rng)
                move = new / old - 1
                if abs(move) >= 0.025:
                    word = "cut" if move < 0 else "raised"
                    self._alert("watch", "price_cut" if move < 0 else "price_up",
                                f'{self._name(quote["provider_id"])} {word} {quote["gpu"]} to ${new:.2f}, {abs(move) * 100:.1f}% {"lower" if move < 0 else "higher"}.',
                                quote=quote["id"], provider=quote["provider_id"], model=quote["gpu"])

        births = max(0, round(rng.gauss(0.55 + (TARGET_LIVE - len(self.quotes)) * 0.06, 0.7)))
        for _ in range(births):
            quote = self._post(rng)
            low = lows.get(quote["gpu"])
            if running and low is not None and quote["price"] < low:
                grade = self._grade(quote["provider_id"])
                self._alert("watch", "new_low", f'New {quote["gpu"]} low: {self._name(quote["provider_id"])} at ${quote["price"]:.2f}, a grade {grade} seller.',
                            quote=quote["id"], provider=quote["provider_id"], model=quote["gpu"])
                lows[quote["gpu"]] = quote["price"]
            elif running:
                self._alert("info", "posted", f'{self._name(quote["provider_id"])} posted {quote["gpus_per_node"] * quote["nodes"]} {quote["gpu"]} at ${quote["price"]:.2f}.',
                            quote=quote["id"], provider=quote["provider_id"], model=quote["gpu"])

        if running and rng.random() < 0.025:
            provider = rng.choice(list(self.providers.values()))
            category = rng.choice([name for name, _ in scoring.CATEGORIES])
            before = grade_of(provider)
            step = rng.choice((-1, 1)) if 1 < provider["tiers"][category] < 3 else (1 if provider["tiers"][category] == 1 else -1)
            provider["tiers"][category] += step
            after = grade_of(provider)
            provider["changed_tick"] = self.tick
            if after != before:
                self._alert("alert", "grade_change", f'{provider["name"]} moved from grade {before} to {after}: {CATEGORY_NOTE[category] if step > 0 else "improved " + category.replace("_", " ")}.',
                            provider=provider["id"])
        self._record()
        if running:
            self._basis_alerts()

    def _basis_alerts(self) -> None:
        for model, summary in self._analyze()["models"].items():
            basis, last = summary["basis"], self._last_basis_alert.get(model)
            if basis is None or last is None or abs(basis - last) < 0.03:
                self._last_basis_alert[model] = basis if last is None else last
                continue
            self._alert("watch", "basis", f'{model} basis {"widened" if basis > last else "narrowed"} to {basis * 100:+.1f}% (was {last * 100:+.1f}%).', model=model)
            self._last_basis_alert[model] = basis

    # ------------------------------------------------------------ analysis

    def _analyze(self) -> dict[str, Any]:
        key = (self._epoch, self.tick, self._version)
        if self._analysis_key == key:
            return self._analysis
        as_of = self.now.date()
        grades = {pid: grade_of(provider) for pid, provider in self.providers.items()}
        scores = {pid: scoring.quality_score(provider["tiers"]) for pid, provider in self.providers.items()}
        references = {model: self._reference(model) for model in MODELS}
        rows = []
        for quote in self.quotes.values():
            grade = grades[quote["provider_id"]]
            rows.append({"q": quote, "grade": grade,
                         "e": scoring.quote_economics(quote, grade=grade, reference=references[quote["gpu"]], as_of=as_of)})
        models: dict[str, dict[str, Any]] = {}
        for model in MODELS:
            group = sorted((r for r in rows if r["q"]["gpu"] == model), key=lambda r: (r["q"]["price"], r["q"]["id"]))
            for rank, row in enumerate(group, start=1):
                row["price_rank"] = rank
            eligible = sorted((r for r in group if r["e"]["eligible"]), key=lambda r: (r["e"]["risk_adjusted"], r["q"]["id"]))
            for rank, row in enumerate(eligible, start=1):
                row["risk_rank"] = rank
            cheapest, best = (group[0] if group else None), (eligible[0] if eligible else None)
            prices = [r["q"]["price"] for r in group]
            models[model] = {
                "count": len(group), "gpus": sum(r["e"]["gpus"] for r in group), "eligible": len(eligible),
                "cheapest": cheapest, "best": best, "reference": references[model],
                "median": statistics.median(prices) if prices else None,
                "low": min(prices) if prices else None, "high": max(prices) if prices else None,
                "basis": None if not (cheapest and best) else best["e"]["risk_adjusted"] / cheapest["q"]["price"] - 1,
            }
        self._analysis_key, self._analysis = key, {"rows": rows, "models": models, "grades": grades, "scores": scores}
        return self._analysis

    def _record(self, replace: bool = False) -> None:
        if replace and self.series and self.series[-1]["tick"] == self.tick:
            self.series.pop()
        analysis = self._analyze()
        rows, models = analysis["rows"], analysis["models"]
        weighted = [(m["gpus"], m["basis"]) for m in models.values() if m["basis"] is not None]
        total = sum(weight for weight, _ in weighted)
        self.series.append({
            "tick": self.tick, "time": self.now.isoformat(timespec="minutes"), "live": len(rows),
            "gpus": sum(r["e"]["gpus"] for r in rows),
            "eligible_share": sum(1 for r in rows if r["e"]["eligible"]) / len(rows) if rows else None,
            "basis": sum(w * b for w, b in weighted) / total if total else None,
            "models": {name: {"cheapest": m["low"], "best": None if not m["best"] else m["best"]["e"]["risk_adjusted"],
                              "basis": m["basis"], "median": m["median"], "reference": m["reference"]} for name, m in models.items()},
        })

    # ------------------------------------------------------------- the clock

    def _advance(self) -> None:
        if self._paused_at is not None:
            return
        due = int((self._clock() - self._origin) / self._tick_seconds)
        behind = due - self._steps_taken
        if behind > MAX_CATCH_UP:  # the process was suspended; do not replay hours of market in one request
            self._origin += (behind - MAX_CATCH_UP) * self._tick_seconds
            behind = MAX_CATCH_UP
        for _ in range(max(0, behind)):
            self._step()
            self._steps_taken += 1

    # ---------------------------------------------------------- scenarios

    def _scenario(self, name: str) -> str:
        rng = random.Random(f"{self._seed}:{self.tick}:{name}:{self._version}")
        if name == "price_war":
            model = "B300"
            ranked = sorted((q for q in self.quotes.values() if q["gpu"] == model), key=lambda q: q["price"])
            weak = [q for q in ranked if self._grade(q["provider_id"]) in ("C", "D")][:4] or ranked[:3]
            for quote in weak:
                old, new = self._revise(quote, rng, price=quote["price"] * (1 - rng.uniform(0.06, 0.10)))
                self._pin(quote)
                self._alert("watch", "price_cut", f'{self._name(quote["provider_id"])} cut {model} to ${new:.2f}, {abs(new / old - 1) * 100:.1f}% lower.',
                            quote=quote["id"], provider=quote["provider_id"], model=model)
            broker = max((p for p in self.providers.values() if p["kind"] == "Reseller"), key=lambda p: p["weight"])
            posted = self._post(rng, provider_id=broker["id"], gpu=model)
            low = min(q["price"] for q in self.quotes.values() if q["gpu"] == model and q["id"] != posted["id"])
            posted["price"] = round(low * 0.97, 2)
            self._pin(posted)
            self._pressure.append(Pressure(model, -0.005, 8))
            text = f'Price war in {model}: {len(weak)} sellers cut and {broker["name"]} posted ${posted["price"]:.2f}.'
        elif name == "supply_shock":
            model = "H200"
            ranked = sorted((q for q in self.quotes.values() if q["gpu"] == model), key=lambda q: -q["nodes"])
            total = sum(q["nodes"] for q in ranked)
            removed = 0
            for quote in ranked:
                if removed >= 0.45 * total:
                    break
                removed += quote["nodes"]
                del self.quotes[quote["id"]]
                self._alert("watch", "sold_out", f'{self._name(quote["provider_id"])} withdrew {quote["nodes"] * quote["gpus_per_node"]} {model}.',
                            quote=quote["id"], provider=quote["provider_id"], model=model)
            self._pressure.append(Pressure(model, 0.007, 10))
            text = f'Supply shock in {model}: {removed * 8} GPUs withdrawn ({removed / total * 100:.0f}% of the book).'
        else:
            gpus = collections.Counter()
            for quote in self.quotes.values():
                gpus[quote["provider_id"]] += quote["gpus_per_node"] * quote["nodes"]
            strong = [pid for pid in gpus if self._grade(pid) == "A"] or list(gpus)
            provider = self.providers[max(strong, key=lambda pid: gpus[pid])]
            before, causes = grade_of(provider), []
            for category, worst in (("certification", 3), ("responsiveness", 3), ("sla", 2), ("delivery", 3), ("credit", 3)):
                if scoring.GRADES.index(grade_of(provider)) >= min(scoring.GRADES.index(before) + 2, 3):
                    break
                provider["tiers"][category] = max(provider["tiers"][category], worst)
                causes.append(CATEGORY_NOTE[category])
            provider["changed_tick"] = self.tick
            text = (f'{provider["name"]} downgraded from {before} to {grade_of(provider)}: {", ".join(causes)}.' if causes
                    else f'{provider["name"]} is already grade {before}; nothing further to downgrade.')
        self._alert("alert", "scenario", text)
        return text

    # ---------------------------------------------------------- public API

    def control(self, action: str, scenario: str | None = None) -> dict[str, Any]:
        if action not in ACTIONS:
            raise ValueError("unknown action")
        if (action == "scenario") != (scenario is not None) or (scenario is not None and scenario not in SCENARIOS):
            raise ValueError("scenario actions need exactly one known scenario")
        with self._lock:
            self._advance()
            if action == "pause" and self._paused_at is None:
                self._paused_at = self._clock()
            elif action == "resume" and self._paused_at is not None:
                self._origin += self._clock() - self._paused_at
                self._paused_at = None
            elif action == "reset":
                epoch = self._epoch + 1
                self._build()
                self._epoch = epoch
            elif action == "scenario":
                self._scenario(scenario)
            if action != "reset":
                self._version += 1
                self._record(replace=True)
            return {"tick": self.tick, "paused": self._paused_at is not None, "epoch": self._epoch}

    def etag(self) -> str:
        with self._lock:
            self._advance()
            return f'W/"book-{self._epoch}-{self.tick}-{self._version}"'

    def encoded(self) -> tuple[str, bytes]:
        """The current snapshot as (etag, JSON bytes); rebuilt only when the market has moved."""
        with self._lock:
            self._advance()
            key = (self._epoch, self.tick, self._version)
            if self._body_key != key:
                body = json.dumps(self._snapshot(), separators=(",", ":"), allow_nan=False).encode()
                self._body_key, self._body = key, (f'W/"book-{self._epoch}-{self.tick}-{self._version}"', body)
            return self._body

    def snapshot(self) -> dict[str, Any]:
        return json.loads(self.encoded()[1])

    # ------------------------------------------------------------ snapshot

    def _snapshot(self) -> dict[str, Any]:
        analysis = self._analyze()
        rows, models, grades, scores = analysis["rows"], analysis["models"], analysis["grades"], analysis["scores"]
        today = self.now.date()

        def r(value: float | None, places: int) -> float | None:
            return None if value is None else round(value, places)

        def quote_view(row: dict[str, Any]) -> dict[str, Any]:
            q, e = row["q"], row["e"]
            expires = None if q["expires"] is None else dt.date.fromisoformat(q["expires"])
            return {
                "id": q["id"], "provider_id": q["provider_id"], "provider": self._name(q["provider_id"]), "grade": row["grade"],
                "gpu": q["gpu"], "gpus": e["gpus"], "nodes": q["nodes"], "price": f'{q["price"]:.2f}', "months": q["months"],
                "down_payment": q["down_payment"], "payment_days": q["payment_days"], "location": q["location"], "country": q["country"],
                "interconnect": q["interconnect"], "cooling": q["cooling"], "moq": q["moq"], "lead_weeks": q["lead_weeks"],
                "available": q["available"], "expires": q["expires"], "days_to_expiry": None if expires is None else (expires - today).days,
                "missing": e["missing"], "flags": e["flags"], "eligible": e["eligible"], "reasons": e["ineligible_reasons"],
                "risk_adjusted": r(e["risk_adjusted"], 4), "financing": r(e["financing_cost"], 4), "exposure": r(e["exposure_charge"], 4),
                "discount_to_reference": r(e["discount_to_reference"], 4), "contract_value": r(e["contract_value"], 0),
                "price_rank": row["price_rank"], "risk_rank": row.get("risk_rank"),
                "posted_tick": q["posted_tick"], "changed_tick": q["changed_tick"], "workbook": q["seed"],
            }

        def leg(row: dict[str, Any] | None) -> dict[str, Any] | None:
            if row is None:
                return None
            return {"id": row["q"]["id"], "provider": self._name(row["q"]["provider_id"]), "grade": row["grade"],
                    "price": f'{row["q"]["price"]:.2f}', "risk_adjusted": r(row["e"]["risk_adjusted"], 4), "missing": len(row["e"]["missing"])}

        by_provider: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
        for row in rows:
            by_provider[row["q"]["provider_id"]].append(row)
        medians = {name: m["median"] for name, m in models.items()}
        provider_views = []
        for pid, provider in self.providers.items():
            own = by_provider.get(pid, [])
            provider_views.append({
                "id": pid, "name": provider["name"], "kind": provider["kind"], "region": provider["region"], "sites": provider["sites"],
                "grade": grades[pid], "score": r(scores[pid], 1), "tiers": provider["tiers"], "quotes": len(own),
                "gpus": sum(x["e"]["gpus"] for x in own), "missing_average": r(sum(len(x["e"]["missing"]) for x in own) / len(own), 2) if own else None,
                "eligible_share": r(sum(1 for x in own if x["e"]["eligible"]) / len(own), 3) if own else None,
                "price_index": r(statistics.median(x["q"]["price"] / medians[x["q"]["gpu"]] for x in own), 4) if own else None,
                "changed_tick": provider.get("changed_tick"), "workbook": provider["seed"],
            })
        grade_mix = {g: {"providers": 0, "quotes": 0, "gpus": 0} for g in scoring.GRADES}
        for view in provider_views:
            grade_mix[view["grade"]]["providers"] += 1
        for row in rows:
            grade_mix[row["grade"]]["quotes"] += 1
            grade_mix[row["grade"]]["gpus"] += row["e"]["gpus"]
        supply = {model: {g: sum(x["e"]["gpus"] for x in rows if x["q"]["gpu"] == model and x["grade"] == g) for g in scoring.GRADES} for model in MODELS}
        expiry = []
        for label, low, high in EXPIRY_BUCKETS:
            days = [(dt.date.fromisoformat(x["q"]["expires"]) - today).days for x in rows if x["q"]["expires"]]
            expiry.append({"label": label, "quotes": sum(1 for d in days if low <= d < high or (low == 0 and d < 0))})
        expiry.append({"label": "No expiry", "quotes": sum(1 for x in rows if not x["q"]["expires"])})
        missing_counts = collections.Counter(min(len(x["e"]["missing"]), 6) for x in rows)
        completeness = [{"missing": n, "label": ("6 or more" if n == 6 else str(n)),
                         "by_grade": {g: sum(1 for x in rows if min(len(x["e"]["missing"]), 6) == n and x["grade"] == g) for g in scoring.GRADES},
                         "quotes": missing_counts.get(n, 0)} for n in range(7)]
        field_gaps = {name: sum(1 for x in rows if name in x["e"]["missing"]) for name in scoring.KEY_FIELDS}
        weighted = [(m["gpus"], m["basis"]) for m in models.values() if m["basis"] is not None]
        total_gpus = sum(w for w, _ in weighted)
        series = list(self.series)
        eligible = [x for x in rows if x["e"]["eligible"]]
        return {
            "simulated": True,
            "meta": {"tick": self.tick, "time": self.now.isoformat(timespec="minutes"), "paused": self._paused_at is not None,
                     "tick_seconds": self._tick_seconds, "epoch": self._epoch, "seed": self._seed, "source": seed.SOURCE,
                     "step_minutes": int(STEP.total_seconds() // 60), "as_of": today.isoformat()},
            "kpis": {
                "live_quotes": len(rows), "providers_quoting": len(by_provider), "providers_total": len(self.providers),
                "gpus": sum(x["e"]["gpus"] for x in rows), "contract_value": r(sum(x["e"]["contract_value"] or 0 for x in rows), 0),
                "eligible_quotes": len(eligible), "eligible_share": r(len(eligible) / len(rows), 4) if rows else None,
                "basis": r(sum(w * b for w, b in weighted) / total_gpus, 4) if total_gpus else None,
                "cheapest_is_ineligible": sum(1 for m in models.values() if m["cheapest"] and not m["cheapest"]["e"]["eligible"]),
                "models_with_basis": len(weighted), "models": len(MODELS),
            },
            "models": [{
                "model": name, "quotes": m["count"], "gpus": m["gpus"], "eligible": m["eligible"], "basis": r(m["basis"], 4),
                "cheapest": leg(m["cheapest"]), "best": leg(m["best"]), "reference": m["reference"],
                "low": m["low"], "median": r(m["median"], 3), "high": m["high"],
                "discount_to_reference": None if not (m["reference"] and m["low"]) else r(1 - m["low"] / m["reference"], 4),
            } for name, m in models.items()],
            "grade_mix": grade_mix, "supply": supply, "expiry": expiry, "completeness": completeness, "field_gaps": field_gaps,
            "providers": sorted(provider_views, key=lambda v: (-v["score"], v["id"])),
            "quotes": [quote_view(row) for row in sorted(rows, key=lambda x: (MODELS.index(x["q"]["gpu"]), x["price_rank"]))],
            "alerts": list(reversed(list(self.alerts)[-40:])),
            "series": {
                "ticks": [p["tick"] for p in series], "times": [p["time"] for p in series], "live": [p["live"] for p in series],
                "gpus": [p["gpus"] for p in series], "eligible_share": [r(p["eligible_share"], 4) for p in series],
                "basis": [r(p["basis"], 4) for p in series],
                "models": {name: {key: [r(p["models"][name][key], 4) for p in series] for key in ("cheapest", "best", "basis", "median", "reference")} for name in MODELS},
            },
            "assumptions": {
                "weights": {name: weight for name, weight in scoring.CATEGORIES},
                "grades": [{"grade": g, "minimum": lo, "premium": pm, "annual_failure": scoring.ASSUMPTIONS["failure_probability"][g]} for g, lo, pm in scoring.GRADE_BANDS],
                "cost_of_capital": scoring.ASSUMPTIONS["cost_of_capital"], "failure_share_remaining": scoring.ASSUMPTIONS["failure_share_remaining"],
                "eligibility": {"min_grade": scoring.ASSUMPTIONS["min_eligible_grade"], "max_missing": scoring.ASSUMPTIONS["max_missing_fields"], "key_fields": len(scoring.KEY_FIELDS)},
                "references": "On-demand rental indexes, so discounts to them overstate term-resale margin. No index exists for GB300 or Pro 6000.",
            },
        }
