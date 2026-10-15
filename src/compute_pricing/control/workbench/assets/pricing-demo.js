/* Pricing demonstration, part 1 of 5: shared helpers.
   The page is split over pricing-demo.js (this file), -fields.js (term labels and the form), -charts.js (SVG charts),
   -view.js (the assessment dialog) and -app.js (state, requests, wiring). Each file is an IIFE that attaches to
   window.PricingDemo and runs in the order index.html lists them, so later files may rely on earlier ones.
   Rules that hold throughout: DOM built with createElement and textContent, no inline style, colour only through classes
   and SVG attributes, and no financial arithmetic here. The page prints what the backend computed, rounded for display. */
(() => {
  "use strict";
  const ns = window.PricingDemo = window.PricingDemo || {};
  const SVG_NS = "http://www.w3.org/2000/svg";
  const NOT_SUPPLIED = "Not supplied";
  const NOT_AVAILABLE = "Not available";

  /* A figure counts only if it is a real number or a decimal string; "", null, booleans and NaN never print as values. */
  const isNumeric = (value) => value !== null && value !== undefined && value !== "" && typeof value !== "boolean" && Number.isFinite(Number(value));
  const num = (value) => (isNumeric(value) ? Number(value) : null);
  const clone = (value) => (value === undefined ? undefined : JSON.parse(JSON.stringify(value)));

  function h(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }
  function svg(tag, attributes = {}, ...children) {
    const node = document.createElementNS(SVG_NS, tag);
    Object.entries(attributes).forEach(([name, value]) => { if (value !== null && value !== undefined) node.setAttribute(name, String(value)); });
    children.flat().forEach((child) => { if (child) node.append(child); });
    return node;
  }
  const svgText = (content, attributes) => { const node = svg("text", attributes); node.textContent = content; return node; };

  /* Display formats. Money keeps cents unless told otherwise; rates keep three places; a missing value prints a reason, never a blank. */
  const group = (value, min, max) => Number(value).toLocaleString("en-US", { minimumFractionDigits: min, maximumFractionDigits: max });
  const MINUS = "−";
  function money(value, digits = 2, fallback = NOT_AVAILABLE) {
    if (!isNumeric(value)) return fallback;
    const amount = Number(value);
    const body = group(Math.abs(amount), digits, digits);
    return (amount < 0 && Number(body.replaceAll(",", "")) !== 0 ? MINUS : "") + "$" + body;
  }
  const rate = (value, fallback = NOT_AVAILABLE) => money(value, 3, fallback);
  function percent(value, maxDigits = 2, fallback = NOT_AVAILABLE) {
    if (!isNumeric(value)) return fallback;
    return group(Number(value) * 100, 0, maxDigits) + "%";
  }
  function count(value, fallback = NOT_AVAILABLE) { return isNumeric(value) ? group(value, 0, 4) : fallback; }
  /* Axis labels: whole dollars, then K and M from 1,000 up. */
  function compactMoney(value) {
    const amount = Math.abs(value); const sign = value < 0 ? MINUS : "";
    if (amount >= 1e6) return sign + "$" + group(amount / 1e6, 0, 2) + "M";
    if (amount >= 1e3) return sign + "$" + group(amount / 1e3, 0, 2) + "K";
    return sign + "$" + group(amount, 0, 2);
  }

  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})/;
  function shortDate(value) {
    const match = typeof value === "string" ? ISO_DATE.exec(value) : null;
    return match ? MONTHS[Number(match[2]) - 1] + " " + Number(match[3]) : NOT_SUPPLIED;
  }
  function longDate(value) {
    const match = typeof value === "string" ? ISO_DATE.exec(value) : null;
    return match ? MONTHS[Number(match[2]) - 1] + " " + Number(match[3]) + ", " + match[1] : NOT_SUPPLIED;
  }
  function utcStamp(value) {
    const match = typeof value === "string" ? /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(value) : null;
    return match ? longDate(match[1]) + " " + match[2] + " UTC" : NOT_SUPPLIED;
  }
  function spanDays(start, end) {
    const from = Date.parse(start); const to = Date.parse(end);
    return Number.isFinite(from) && Number.isFinite(to) && to > from ? Math.round((to - from) / 86400000) : null;
  }
  const plural = (n, one, many) => n + " " + (n === 1 ? one : many);

  const humanize = (key) => String(key).replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());

  /* Backend hold codes in plain words. A code that is not listed falls back to its own name, spaced out. */
  const HOLDS = {
    required_declared_input_unknown: "A required term is not supplied",
    ownership_or_credit_class_unknown: "Ownership or credit band is unknown",
    power_cash_payer_unknown_or_not_supported_by_broker_cost_model: "The power payer is unknown, or is not the broker (the only payer the model supports)",
    illustrative_weak_grade_requires_hourly_restricted_escrow: "A weak-grade provider requires hourly restricted escrow",
    full_escrow_prefunding_not_declared: "Escrow prefunding is not fully declared",
    pricing_cash_inversion_requires_full_declared_service_and_collection_in_hourly_mode: "Hourly mode needs full declared service and full collection",
    remaining_customer_principal_refund_not_confirmed: "Refund of the remaining customer principal is not confirmed",
    no_positive_economic_and_cash_purchase_ceiling: "No positive purchase ceiling meets both the economic and the cash limits",
    supplied_rate_breaches_declared_cash_floor: "The supplier price breaches the declared cash floor",
    asset_price_unknown: "The asset price is not supplied",
    asset_illiquid: "The asset is illiquid",
    asset_unknown: "Asset liquidity is unknown",
    depeg_unknown: "Depeg status is unknown",
    depeg_depegged: "The asset is depegged",
    principal_release_unconfirmed: "Release of principal is not confirmed",
    principal_release_denied: "Release of principal is not authorized",
    yield_accrued_only: "Yield accrues but cannot be withdrawn hourly",
    yield_unknown: "Yield access is unknown",
    yield_entitlement_unknown: "Yield entitlement is not declared",
  };
  const holdText = (code) => HOLDS[code] || humanize(code);

  /* The host throws "HTTP 422 · invalid_pricing_demo_input" style messages. Keep the code, say what to do about it. */
  function explainError(error) {
    const message = error && error.message ? String(error.message) : "The request failed";
    if (/invalid_pricing_demo_input/.test(message)) return "The server rejected these terms (" + message + "). Check that dates are real, fractions lie between 0 and 1 and the supplier price sits inside any variable range.";
    if (/demo_evidence_store_unavailable|assessment_store_unavailable|market_reference_store_unavailable/.test(message)) return "The local evidence store is unavailable (" + message + "). Nothing was saved; try again.";
    if (/agreement_terms_not_complete/.test(message)) return "This assessment has no complete agreement terms to render (" + message + ").";
    return message;
  }

  /* The public entry for the Quotes page: window.ComputePricingDemo.loadQuote(quote) -> Promise<boolean>.
     Quotes may call it before the rest of this page has loaded or the pricing contract has arrived, so a quote that cannot be applied yet
     is held here and applied by pricing-demo-app.js the moment it can be. Resolves true when the form was filled now, false when queued. */
  let queued = null;
  ns.takeQueuedQuote = () => { const quote = queued; queued = null; return quote; };
  window.ComputePricingDemo = Object.freeze({ loadQuote(quote) {
    if (typeof ns.loadQuote === "function") return ns.loadQuote(quote);
    queued = quote; return Promise.resolve(false);
  } });

  Object.assign(ns, { SVG_NS, NOT_SUPPLIED, NOT_AVAILABLE, MINUS, isNumeric, num, clone, h, svg, svgText, group, money, rate, percent, count, compactMoney, shortDate, longDate, utcStamp, spanDays, plural, humanize, holdText, explainError });
})();
