/* Figures the landing page derives from one book snapshot. Pure functions, no DOM, so they can be checked against the server's own numbers.
   Every function answers null (or an empty list) when the book cannot support the figure, and the page then says nothing instead of a wrong thing. */
(function () {
  "use strict";
  const finite = (value) => typeof value === "number" && Number.isFinite(value);
  const number = (value) => (finite(value) ? value : typeof value === "string" && value.trim() !== "" && Number.isFinite(Number(value)) ? Number(value) : null);
  const list = (value) => (Array.isArray(value) ? value : []);

  /* ---- names ---- */
  /* Every key field a quote can leave out, in the words a buyer would use. `grade` is not a field the seller fills in: it is the
     seller's rating, and the book counts a quote as missing it when the seller has none. */
  const TERMS = {
    gpu: "GPU model", gpus_per_node: "GPUs per node", nodes: "Nodes", price: "Price", currency: "Currency", price_unit: "Price unit",
    months: "Contract length", down_payment: "Down payment", available: "Start date", expires: "Expiry", payment_days: "Payment terms",
    moq: "Minimum order", lead_weeks: "Lead time", location: "Location", country: "Country", interconnect: "Interconnect", cooling: "Cooling",
    grade: "Seller grade", reference: "Reference price",
  };
  const words = (code) => String(code).replace(/_/g, " ").trim();
  const sentence = (text) => text.charAt(0).toUpperCase() + text.slice(1);
  const lowerFirst = (text) => (/^[A-Z][a-z]/.test(text) ? text.charAt(0).toLowerCase() + text.slice(1) : text);
  const termName = (field) => TERMS[field] || sentence(words(field));

  /* Why a quote fails the eligibility checks (scoring.py), lower case so a reason can sit inside a sentence. */
  const REASONS = {
    contract_start_precedes_as_of: "contract start has passed", contract_term_expired: "contract term has ended", simulated_quote_expired: "quote has expired",
    inactive_simulated_quote: "quote withdrawn", no_available_capacity: "no capacity left", available_nodes_below_minimum_order: "capacity below the minimum order",
    missing_grade: "seller has no grade", unsupported_currency_no_implicit_fx: "price not in dollars", unsupported_price_unit_no_implicit_conversion: "price not per GPU-hour",
  };
  function reasonName(code) {
    if (REASONS[code]) return REASONS[code];
    const missing = /^missing_(.+)$/.exec(String(code));
    return missing ? "no " + lowerFirst(termName(missing[1])) + " stated" : words(code);
  }

  /* ---- shares ---- */
  /* A share of a whole, as the value a bar is drawn at and the text printed beside it. A share is never printed as 0% or 100% unless it is. */
  function share(count, total) {
    if (!finite(count) || !finite(total) || !(total > 0)) return null;
    const fraction = Math.min(1, Math.max(0, count / total)); const percent = fraction * 100;
    const text = count <= 0 ? "0%" : count >= total ? "100%" : percent < 0.5 ? "<1%" : percent >= 99.5 ? ">99%" : Math.round(percent) + "%";
    return { fraction, value: percent, text };
  }
  /* Parts of a total, rounded to `places` decimals so that the rounded parts add up to the rounded total (largest remainder). */
  function apportion(values, places = 1) {
    const unit = 10 ** places; const scaled = values.map((value) => (finite(value) ? value * unit : 0));
    const total = Math.round(scaled.reduce((a, b) => a + b, 0)); const floors = scaled.map((value) => Math.floor(value));
    let left = total - floors.reduce((a, b) => a + b, 0);
    scaled.map((value, index) => ({ index, rest: value - floors[index] })).sort((a, b) => b.rest - a.rest || a.index - b.index).forEach(({ index }) => { if (left > 0) { floors[index] += 1; left -= 1; } });
    return floors.map((value) => value / unit);
  }

  /* ---- the quotes that count ---- */
  /* The quotes kpis.live_quotes counts: active, with capacity and a future expiry. null when the book's quotes do not add up to the
     server's own count, so a figure drawn from them is left out rather than guessed. */
  function liveQuotes(data) {
    const quotes = list(data?.quotes); const count = number(data?.kpis?.live_quotes);
    if (count === null) return null;
    const live = quotes.filter((quote) => quote && quote.active !== false && quote.nodes > 0 && finite(quote.days_to_expiry) && quote.days_to_expiry > 0);
    return live.length === count ? live : null;
  }

  /* How many live quotes pass every eligibility check and why the others do not. `reasons` counts a quote once under each reason it
     fails, so a quote with two reasons appears twice; `overlap` says so. */
  function eligibility(data) {
    const live = liveQuotes(data); const kpis = data?.kpis || {};
    const total = number(kpis.live_quotes); const passing = number(kpis.eligible_quotes);
    if (total === null || passing === null) return null;
    const out = { live: total, eligible: passing, failing: total - passing, reasons: [], overlap: false, dominant: null, dominantMost: false, known: false };
    if (!live || live.filter((quote) => quote.eligible).length !== passing) return out;
    const counts = new Map();
    live.filter((quote) => !quote.eligible).forEach((quote) => new Set(quote.reason_codes).forEach((code) => counts.set(code, (counts.get(code) || 0) + 1)));
    out.reasons = [...counts].map(([code, count]) => ({ code, name: reasonName(code), count })).sort((a, b) => b.count - a.count || a.code.localeCompare(b.code));
    out.known = true; out.overlap = out.reasons.reduce((sum, row) => sum + row.count, 0) > out.failing;
    out.dominant = out.reasons[0] || null; out.dominantMost = Boolean(out.dominant) && out.dominant.count * 2 > out.failing;
    return out;
  }

  /* Key terms the quotes leave blank, over every quote in the book (field_gaps counts all of them, live or not). `grade` is reported
     apart, because a missing grade is the seller's, not a term the quote left out. */
  function termGaps(data) {
    const quotes = list(data?.quotes); const total = quotes.length; if (!total) return null;
    const gaps = data?.field_gaps && typeof data.field_gaps === "object" ? data.field_gaps : {};
    const terms = Object.entries(gaps).map(([field, count]) => ({ field, name: termName(field), count: number(count) })).filter((row) => row.count !== null && row.count > 0 && row.field !== "grade" && row.field !== "reference")
      .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
    const blank = quotes.filter((quote) => list(quote.missing).some((field) => field !== "grade" && field !== "reference")).length;
    return { total, terms, quotesWithBlank: blank, unrated: number(gaps.grade) || 0 };
  }

  /* The lowest quote of each model: how many are ineligible, and how many come from a grade C or D seller. */
  function lowestQuotes(data) {
    const priced = list(data?.models).filter((entry) => entry && entry.cheapest);
    return { priced: priced.length, ineligible: priced.filter((entry) => entry.cheapest.eligible !== true).length, weak: priced.filter((entry) => entry.cheapest.grade === "C" || entry.cheapest.grade === "D").length,
      unrated: priced.filter((entry) => entry.cheapest.grade === "U").length };
  }

  /* ---- the basis ---- */
  /* Where the market basis comes from. The basis is how much more the best eligible all-in cost is than the lowest quoted price,
     weighted by the GPUs on offer in each model. It has two sources, and the page should say which is which:
       screen   what leaving out the ineligible quotes does: the cheapest ELIGIBLE quoted price against the lowest quoted price;
       costing  what financing and expected loss add: the best eligible all-in cost against that cheapest eligible price.
     screen + costing equals the basis exactly. Costing splits again into the best quote's own financing and expected loss and,
     where the best all-in quote is not the cheapest eligible one, `price`: how much dearer its quoted price is. Those three also add
     up to costing exactly. Models with no eligible, fully priced quote are left out, as the server's basis does. */
  function basisBreakdown(data) {
    const quotes = list(data?.quotes); const models = list(data?.models); const byId = new Map(quotes.map((quote) => [quote.id, quote]));
    let weight = 0, total = 0, screen = 0, price = 0, financing = 0, loss = 0, counted = 0, detailed = 0;
    models.forEach((entry) => {
      if (!entry || !entry.best || !finite(entry.best.risk_adjusted) || !(entry.gpus > 0)) return;
      const mine = quotes.filter((quote) => quote.gpu === entry.model);
      const eligible = mine.filter((quote) => quote.eligible).map((quote) => number(quote.price)).filter((value) => value !== null);
      const prices = mine.map((quote) => number(quote.price)).filter((value) => value !== null);
      const lowest = number(entry.cheapest?.price) ?? (prices.length ? Math.min(...prices) : null);
      if (!eligible.length || lowest === null || !(lowest > 0)) return;
      const cheapestEligible = Math.min(...eligible);
      weight += entry.gpus; counted++;
      total += entry.gpus * (entry.best.risk_adjusted / lowest - 1);
      screen += entry.gpus * (cheapestEligible / lowest - 1);
      const own = byId.get(entry.best.id); const bestPrice = own ? number(own.price) : null; const fin = own ? number(own.financing) : null; const exp = own ? number(own.exposure) : null;
      if (bestPrice !== null && fin !== null && exp !== null) {
        detailed++; price += entry.gpus * ((bestPrice - cheapestEligible) / lowest); financing += entry.gpus * (fin / lowest); loss += entry.gpus * (exp / lowest);
      }
    });
    if (!(weight > 0)) return null;
    const all = detailed === counted;
    return { basis: total / weight, screen: screen / weight, costing: (total - screen) / weight, price: all ? price / weight : null, financing: all ? financing / weight : null, loss: all ? loss / weight : null,
      models: counted, modelsTotal: models.length, gpus: weight };
  }

  window.LandingData = Object.freeze({ basisBreakdown, eligibility, termGaps, lowestQuotes, liveQuotes, share, apportion, termName, reasonName, TERMS });
})();
