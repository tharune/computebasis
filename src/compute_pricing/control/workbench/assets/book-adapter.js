/* The one place the frontend learns the shape of /v1/book.
   The backend sends money, rates and ratios as exact decimal strings (some are hundreds of digits long) and describes ranking
   with machine reason codes. Pages read the working model returned here: plain numbers for drawing and arithmetic on display,
   the exact strings kept beside the money fields for tooltips and details, and one vocabulary for every reason. Numbers that
   are already numbers pass through, so an older snapshot still works. Nothing here invents a value: a missing field stays null. */
(function () {
  "use strict";
  const DECIMAL = /^-?\d+(?:\.\d+)?$/;
  /* Text keys that may look numeric but are not quantities. */
  const KEEP_AS_TEXT = new Set(["id", "quote_id", "provider_id", "label", "name", "model", "gpu", "text", "message", "location", "country", "provider", "provider_name", "currency", "unit", "price_unit"]);
  /* Money fields whose exact backend string is kept on `quote.exact` for tooltips and details. */
  const EXACT_QUOTE_FIELDS = ["price", "risk_adjusted", "financing", "exposure", "down_payment", "contract_value", "scorecard_charge"];

  const REASONS = {
    contract_start_precedes_as_of: "Contract start has passed",
    simulated_quote_expired: "Quote has expired",
    missing_down_payment: "No down payment stated",
    missing_expires: "No expiry stated",
    missing_interconnect: "No interconnect stated",
    missing_cooling: "No cooling stated",
    missing_grade: "Seller not rated",
    missing_months: "No contract length stated",
    no_stated_duration: "No contract length stated",
  };
  const humanize = (code) => { const text = String(code).replace(/_/g, " ").trim(); return text.charAt(0).toUpperCase() + text.slice(1); };
  const reasonText = (code) => REASONS[code] || humanize(code);

  const isObject = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
  function toNumbers(value, key) {
    if (typeof value === "string") return !KEEP_AS_TEXT.has(key) && DECIMAL.test(value) ? Number(value) : value;
    if (Array.isArray(value)) return value.map((item) => toNumbers(item, key));
    if (isObject(value)) { const out = {}; Object.keys(value).forEach((name) => { out[name] = toNumbers(value[name], name); }); return out; }
    return value;
  }
  const finite = (value) => (typeof value === "number" && Number.isFinite(value) ? value : null);
  const grade = (value) => (typeof value === "string" && /^[A-D]$/.test(value) ? value : "U");  // U: not rated; never counted as a grade

  /* Short label for reading: quote-demo-0149 shows as Q0149. The full id stays on `id` for keys and for the handoff to Pricing. */
  const quoteRef = (id) => { const text = String(id ?? ""); const match = /(\d+)$/.exec(text); return match ? "Q" + match[1] : text; };
  function normalizeQuote(raw) {
    const quote = toNumbers(raw, "");
    const exact = {}; EXACT_QUOTE_FIELDS.forEach((name) => { if (typeof raw[name] === "string") exact[name] = raw[name]; });
    const codes = Array.isArray(raw.ineligible_reasons) ? raw.ineligible_reasons : Array.isArray(raw.reasons) ? raw.reasons : [];
    const missingFields = Array.isArray(raw.missing_fields) ? raw.missing_fields : Array.isArray(raw.missing) ? raw.missing : [];
    return {
      ...quote, exact, ref: quoteRef(raw.id), grade: grade(raw.grade),
      price: finite(quote.price), risk_adjusted: finite(quote.risk_adjusted), financing: finite(quote.financing), exposure: finite(quote.exposure),
      down_payment: finite(quote.down_payment), contract_value: finite(quote.contract_value),
      missing: missingFields, missing_fields: missingFields, missing_count: missingFields.length,
      eligible: raw.eligible === true, reason_codes: codes, reasons: codes.map(reasonText),
      location: typeof raw.location === "string" && raw.location ? raw.location : null, country: typeof raw.country === "string" && raw.country ? raw.country : null,
    };
  }
  function normalizeModelQuote(raw) {
    if (!isObject(raw)) return null;
    const quote = toNumbers(raw, ""); return { ...quote, ref: quoteRef(raw.id), grade: grade(raw.grade), price: finite(quote.price), risk_adjusted: finite(quote.risk_adjusted), missing: Number.isFinite(raw.missing) ? raw.missing : Array.isArray(raw.missing_fields) ? raw.missing_fields.length : 0 };
  }
  function normalizeModel(raw) {
    const model = toNumbers(raw, "");
    return { ...model, cheapest: normalizeModelQuote(raw.cheapest), best: normalizeModelQuote(raw.best), basis: finite(model.basis), low: finite(model.low), median: finite(model.median), high: finite(model.high), reference: finite(model.reference), eligible: Number.isFinite(model.eligible_count) ? model.eligible_count : model.eligible, quotes: Number.isFinite(model.quote_count) ? model.quote_count : model.quotes };
  }
  function normalizeProvider(raw) {
    const provider = toNumbers(raw, "");
    const sites = Array.isArray(raw.sites) ? raw.sites.slice() : typeof raw.sites === "string" && raw.sites ? raw.sites.split(/\s*,\s*/) : [];
    return { ...provider, grade: grade(raw.grade), sites, score: finite(provider.score), missing_average: finite(provider.missing_average), eligible_share: finite(provider.eligible_share), price_index: finite(provider.price_index) };
  }
  /* A scenario acts on the whole market, so its flag names the scenario and no single model. */
  const SCENARIOS = { price_war: "Price war", supply_shock: "Supply shock", downgrade: "Provider downgrade" };
  /* An older alert carried its kind; the current one carries the scenario that caused it. */
  function normalizeAlert(raw, index) {
    const alert = toNumbers(raw, "");
    return { ...alert, n: Number.isFinite(alert.n) ? alert.n : index + 1, kind: typeof raw.kind === "string" ? raw.kind : raw.scenario ? "scenario" : "market", scenario_label: SCENARIOS[raw.scenario] || (raw.scenario ? humanize(raw.scenario) : ""), level: raw.level || "info", text: String(raw.text ?? raw.message ?? ""), tick: Number.isFinite(alert.tick) ? alert.tick : 0, time: raw.time || "" };
  }
  /* Grade bands, premiums and failure odds, whichever way the backend lays them out. */
  function normalizeAssumptions(raw) {
    const base = toNumbers(raw || {}, "");
    const policy = isObject(base.scorecard_policy) ? base.scorecard_policy : {}; const model = isObject(base.quote_model_assumptions) ? base.quote_model_assumptions : {};
    const weights = isObject(base.weights) ? base.weights : isObject(policy.weights) ? policy.weights : {};
    let grades = Array.isArray(base.grades) ? base.grades : [];
    if (!grades.length && isObject(policy.grade_bands)) {
      grades = ["A", "B", "C", "D"].filter((name) => name in policy.grade_bands).map((name) => ({ grade: name, minimum: finite(policy.grade_bands[name]), premium: finite(policy.grade_premiums?.[name]), annual_failure: finite(model.annual_failure_probability?.[name]) }));
    }
    return { ...base, weights, grades, deposit_apr: finite(model.deposit_apr) ?? finite(base.cost_of_capital), recovery_fraction: finite(model.recovery_fraction), categories: policy.categories || null };
  }
  const renameUnknown = (map) => { if (!isObject(map)) return map; const out = { ...map }; if ("unknown" in out) { out.U = out.unknown; delete out.unknown; } return out; };

  /* null when the response is not a book at all, so the caller can say so instead of drawing nothing. */
  function normalizeBook(raw) {
    if (!isObject(raw) || !Array.isArray(raw.quotes) || !Array.isArray(raw.models) || !Array.isArray(raw.providers) || !isObject(raw.kpis) || !isObject(raw.meta)) return null;
    const series = toNumbers(raw.series || {}, "series");
    const supply = {}; Object.keys(raw.supply || {}).forEach((name) => { supply[name] = renameUnknown(toNumbers(raw.supply[name], "")); });
    const gradeMix = renameUnknown(toNumbers(raw.grade_mix || {}, ""));
    return {
      ...toNumbers(raw, ""),
      meta: toNumbers(raw.meta, "meta"), kpis: toNumbers(raw.kpis, "kpis"),
      quotes: raw.quotes.map(normalizeQuote), models: raw.models.map(normalizeModel), providers: raw.providers.map(normalizeProvider),
      alerts: (Array.isArray(raw.alerts) ? raw.alerts : []).map(normalizeAlert),
      completeness: (Array.isArray(raw.completeness) ? raw.completeness : []).map((row) => ({ ...toNumbers(row, ""), label: String(row.label ?? ""), by_grade: renameUnknown(toNumbers(row.by_grade || {}, "")) })),
      field_gaps: toNumbers(raw.field_gaps || {}, ""), expiry: Array.isArray(raw.expiry) ? raw.expiry : [],
      grade_mix: gradeMix, supply, series, assumptions: normalizeAssumptions(raw.assumptions),
      raw,
    };
  }

  window.BookAdapter = Object.freeze({ normalizeBook, reasonText, REASONS, SCENARIOS });
})();
