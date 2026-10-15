/* Pricing demonstration, part 4 of 5: the assessment dialog's contents and the reference table.
   Everything printed here comes from the saved receipt (rounded for display) or from the terms that were evaluated.
   A figure the backend left unknown prints "Not available" with its reason; a term nobody supplied prints "Not supplied". */
(() => {
  "use strict";
  const P = window.PricingDemo;
  const { h, num, isNumeric, money, rate, percent, group, shortDate, longDate, utcStamp, spanDays, holdText, humanize, plural, NOT_SUPPLIED, NOT_AVAILABLE } = P;
  const C = P.charts; const F = P.fields;
  const byId = (id) => window.ComputeHost.byId(id);

  /* What is on screen now, so a resize or a tab change can redraw without asking the server again. */
  const current = { receipt: null, input: null, references: [], drawn: new Set() };
  const seen = (value, fallback = NOT_SUPPLIED) => (value === null || value === undefined || value === "" ? fallback : String(value));
  const perHour = "per GPU-hour";

  /* ----- small builders ---------------------------------------------------------------------------------------------------------- */
  function facts(rows) {
    const list = h("dl", "pd-facts");
    rows.forEach(([name, value, note]) => {
      const row = h("div"); const dd = h("dd", "", value);
      if (note) dd.append(h("small", "", note));
      row.append(h("dt", "", name), dd); list.append(row);
    });
    return list;
  }
  function kpis(target, items) {
    target.replaceChildren();
    items.forEach((item) => {
      const empty = item.empty === undefined ? !isNumeric(item.raw) : item.empty;
      const cell = h("div", "pd-kpi"); const value = h("strong", "pd-kpi-value" + (empty ? " is-empty" : ""), item.value);
      if (item.unit && !empty) value.append(h("span", "pd-kpi-unit", item.unit));
      cell.append(h("span", "pd-kpi-label", item.label), value, h("span", "pd-kpi-note", item.note)); target.append(cell);
    });
  }
  function nativeRate(row) {
    if (!isNumeric(row.amount)) return NOT_AVAILABLE;
    return (!row.currency || row.currency === "USD" ? "$" : row.currency + " ") + group(row.amount, 3, 3);
  }
  const unitWords = (unit) => (unit === "gpu_hour" ? perHour : unit ? String(unit).replaceAll("_", " ") : "unit not stated");

  /* Retained references for the same hardware. They stay context: the page never mixes them into a price. */
  function referenceTable(rows, compact = false) {
    if (!rows.length) return h("p", "pd-empty-note", "No permitted current reference matches this hardware. The scenario remains separately priced.");
    const wrap = h("div", "pd-table-wrap"); const table = h("table", "pd-table pd-refs");
    table.append(h("caption", "sr-only", "Retained provider references for this hardware"));
    const head = h("thead"); const tr = h("tr");
    (compact ? ["Provider", "Rate"] : ["Provider", "Hardware and terms", "Rate", "Observed"]).forEach((text, index) => { const th = h("th", index === (compact ? 1 : 2) ? "is-num" : "", text); th.setAttribute("scope", "col"); tr.append(th); });
    head.append(tr); table.append(head);
    const body = h("tbody");
    rows.slice(0, compact ? 5 : 14).forEach((row) => {
      const line = h("tr"); const name = h("th", "", seen(row.provider || row.source_id, "Unnamed source")); name.setAttribute("scope", "row");
      name.append(h("small", "", seen(row.status, "published reference"))); line.append(name);
      if (!compact) line.append(h("td", "", seen(row.hardware_model, "") + (row.terms ? " · " + String(row.terms).replaceAll("_", " ") : "")));
      const price = h("td", "is-num", nativeRate(row)); price.append(h("small", "", (row.currency || "USD") + " " + unitWords(row.unit))); line.append(price);
      if (!compact) line.append(h("td", "", utcStamp(row.observed_at)));
      body.append(line);
    });
    table.append(body); wrap.append(table); return wrap;
  }

  /* ----- header, status and the headline answer ---------------------------------------------------------------------------------- */
  function terms(receipt, input) { return (receipt.result && receipt.result.agreement_terms) || input; }
  function renderHead(receipt, input) {
    const r = receipt.result; const t = terms(receipt, input); const c = t.capacity || {}; const p = t.provider || {};
    byId("pd-dialog-title").textContent = seen(p.label, "Provider") + " · " + seen(c.model, "GPU");
    const days = spanDays(c.starts_at, c.ends_at);
    byId("pd-dialog-subtitle").textContent = [seen(c.location, "Location not supplied"), isNumeric(c.node_count) && isNumeric(c.gpus_per_node) ? plural(Number(c.node_count), "node", "nodes") + " × " + c.gpus_per_node + " GPUs" : null, days ? plural(days, "day", "days") : null, "USD per GPU-hour"].filter(Boolean).join(" · ");
    const held = r.status === "held"; const s = r.summary || {};
    const status = byId("pd-modal-status"); status.replaceChildren();
    const feasible = s.cash_feasible === true ? "Funded under the declared terms." : s.cash_feasible === false ? "Additional funding is required under the declared terms." : "Funding feasibility is not established.";
    status.append(h("span", "pill " + (held ? "warn" : s.cash_feasible === false ? "warn" : "good"), held ? "Held" : "Scenario estimate"));
    status.append(h("span", "pd-status-text", held ? "No assessment is made until this is resolved: " + (r.hold_reasons || []).map(holdText).join("; ") + "." : feasible + " Market references and projected yields remain separate."));
  }
  function renderHeadline(receipt, input) {
    const r = receipt.result; const s = r.summary || {}; const held = r.status === "held"; const q = (terms(receipt, input).pricing) || {};
    const whyHeld = held ? "Held: " + (r.hold_reasons || []).map(holdText).join("; ") : "";
    const pick = (value, note) => (isNumeric(value) ? note : whyHeld || "The backend did not return this figure.");
    kpis(byId("pd-kpis"), [
      { label: "Purchase ceiling", value: rate(s.purchase_ceiling), raw: s.purchase_ceiling, unit: perHour, note: pick(s.purchase_ceiling, "Scenario economic limit, not a market bid") },
      { label: "Minimum selling rate", value: rate(s.sell_floor), raw: s.sell_floor, unit: perHour, note: pick(s.sell_floor, "Recovers all costs at the supplier price") },
      { label: "Target selling rate", value: rate(s.target_ask), raw: s.target_ask, unit: perHour, note: pick(s.target_ask, "Meets the declared target margin" + (isNumeric(q.target_margin) ? " of " + percent(q.target_margin) : "")) },
      { label: "Economic profit", value: money(s.expected_profit, 2), raw: s.expected_profit, note: pick(s.expected_profit, (isNumeric(s.expected_margin) ? percent(s.expected_margin, 1) + " of billings. " : "") + "Scenario figure after the capital budget, before treasury yield") },
    ]);
  }

  /* ----- pricing tab ------------------------------------------------------------------------------------------------------------- */
  function rateRows(receipt, input) {
    const s = receipt.result.summary || {}; const q = (terms(receipt, input).pricing) || {};
    const margin = (value) => (isNumeric(value) ? " of " + percent(value) : "");
    const row = (id, label, note, raw, className) => {
      const value = num(raw);
      return { id, label, note, raw, value, className, text: value === null ? NOT_AVAILABLE : rate(value),
        tip: { head: value === null ? NOT_AVAILABLE : "$" + group(value, 4, 4) + " " + perHour, rows: [], notes: [note] } };
    };
    return [
      row("supplier", "Supplier price", "Declared in the contract", s.supplier_rate, "c-ref"),
      row("power", "Power cost", "Declared power, per GPU-hour", s.power_rate, "c-ref"),
      row("ceiling", "Purchase ceiling", "Economic limit, not a market bid", s.purchase_ceiling, "c-main"),
      row("floor", "Minimum selling rate", "Recovers all costs at the supplier price", s.sell_floor, "c-main"),
      row("minimum", "Minimum-margin ask", "Meets the required margin" + margin(q.required_margin), s.minimum_margin_ask, "c-main"),
      row("target", "Target selling rate", "Meets the target margin" + margin(q.target_margin), s.target_ask, "c-main"),
    ];
  }
  function drawRates(animate) {
    const slot = byId("pd-rate-chart"); const { receipt, input } = current;
    const rows = rateRows(receipt, input);
    if (!rows.some((row) => row.value !== null)) { slot.replaceChildren(h("p", "pd-empty-note", "No rates were produced for this assessment." + (receipt.result.status === "held" ? " It is held: " + (receipt.result.hold_reasons || []).map(holdText).join("; ") + "." : ""))); return; }
    const chart = C.barChart({ rows, width: C.widthOf(slot, 560), axisTitle: "USD per GPU-hour", description: "Rates in USD per GPU-hour: " + rows.map((row) => row.label + " " + row.text).join(", "), animate });
    const key = C.legend([{ label: "Declared cost", className: "c-ref" }, { label: "Assessed rate", className: "c-main" }]);
    const twin = C.table({ summary: "View as a table", caption: "Rates in USD per GPU-hour", columns: [{ label: "Measure" }, { label: "Kind" }, { label: "USD per GPU-hour", numeric: true }],
      rows: rows.map((row) => [row.label, row.className === "c-ref" ? "Declared cost" : "Assessed rate", row.value === null ? NOT_AVAILABLE : group(row.value, 4, 4)]) });
    slot.replaceChildren(chart, key, twin);
  }
  function renderLedger(receipt) {
    const r = receipt.result; const s = r.summary || {}; const e = (r.pricing && r.pricing.economics) || {};
    const channel = (id) => { const found = (e.cost_breakdown || []).find((item) => item.id === id); return found ? found.amount : null; };
    const total = byId("pd-ledger"); total.replaceChildren();
    if (!isNumeric(s.gross_billings) && !isNumeric(s.expected_profit)) { total.append(h("p", "pd-empty-note", "Scenario totals are not available for a held assessment.")); return; }
    total.append(facts([
      ["Gross billings", money(s.gross_billings), "Billed GPU-hours at the buyer price"],
      ["Expected collections", money(s.expected_collections)],
      ["Fees", money(e.fees)],
      ["Fixed operating cost", money(channel("operations"))],
      ["Power", money(channel("power"))],
      ["Capital budget", money(s.capital_budget), "Reduces profit and reserves cash; not paid out"],
      ["Economic profit", money(s.expected_profit)],
    ]));
  }

  /* The sensitivity grid: tenor across, shock down, rate in each cell. */
  function surfaceModel(surface) {
    const points = (surface && Array.isArray(surface.points) ? surface.points : []).map((p) => ({ tenor: num(p.tenor_days), shock: num(p.shock), rate: num(p.rate), cap: num(p.economic_cap), within: p.rate_below_economic_cap })).filter((p) => p.tenor !== null && p.shock !== null && p.rate !== null);
    const tenors = [...new Set(points.map((p) => p.tenor))].sort((a, b) => a - b); const shocks = [...new Set(points.map((p) => p.shock))].sort((a, b) => b - a);
    const at = new Map(points.map((p) => [p.tenor + "|" + p.shock, p]));
    return { points, tenors, shocks, at };
  }
  const shockText = (z) => (z > 0 ? "+" + z : z < 0 ? P.MINUS + Math.abs(z) : "0");
  const cellText = (value) => (value >= 100 ? group(value, 0, 0) : value >= 10 ? group(value, 1, 1) : group(value, 2, 2));
  function drawSurface(animate) {
    const slot = byId("pd-surface-chart"); const surface = current.receipt.result.surface; const model = surfaceModel(surface);
    const caption = byId("pd-surface-caption");
    if (!model.points.length) { caption.textContent = "No sensitivity grid is available for this assessment."; slot.replaceChildren(); return; }
    const flagged = model.points.filter((p) => p.within === false).length;
    caption.textContent = "Illustrative. A declared lognormal sensitivity with " + percent(surface.annual_volatility, 1, "unstated") + " annual volatility and zero drift; not a fitted volatility, market forward curve or forecast. Cells show the supplier price in USD per GPU-hour. The price stays within the economic cap in " + (model.points.length - flagged) + " of " + model.points.length + " cases.";
    const bins = C.quantileBins(model.points.map((p) => p.rate), 6);
    const cols = model.tenors.map((t) => ({ value: t, label: String(t) })); const rows = model.shocks.map((z) => ({ value: z, label: shockText(z) }));
    const cell = (col, row) => {
      const p = model.at.get(col.value + "|" + row.value); if (!p) return null;
      const flag = p.within === false;
      return { value: p.rate, text: cellText(p.rate), flag, aria: "Tenor " + plural(col.value, "day", "days") + ", shock " + shockText(row.value) + ": " + rate(p.rate) + " " + perHour + (flag ? ", above the economic cap" : ", within the economic cap"),
        tip: { title: plural(col.value, "day", "days") + " · shock " + shockText(row.value), head: "$" + group(p.rate, 3, 3) + " " + perHour, rows: [{ name: "Economic cap", value: p.cap === null ? NOT_AVAILABLE : "$" + group(p.cap, 3, 3) }], notes: [flag ? "Above the economic cap" : "Within the economic cap"] } };
    };
    const chart = C.heatmap({ cols, rows, cell, width: C.widthOf(slot, 720), bins, colTitle: "Tenor (days)", rowTitle: "Shock (standard deviations)", description: "Supplier price in USD per GPU-hour by tenor in days and rate shock", animate });
    const items = []; for (let i = 0; i < bins.count; i++) items.push({ label: "$" + group(bins.edges[i], 2, 2) + " to $" + group(bins.edges[i + 1], 2, 2), className: C.rampClass(i, bins.count) });
    items.push({ label: "Above the economic cap", className: "pd-hm-flag-key", kind: "flag" });
    const twin = C.table({ summary: "View as a table", caption: "Supplier price in USD per GPU-hour by tenor and shock", columns: [{ label: "Shock" }, ...model.tenors.map((t) => ({ label: t + " d", numeric: true }))],
      rows: model.shocks.map((z) => [shockText(z), ...model.tenors.map((t) => { const p = model.at.get(t + "|" + z); return p ? group(p.rate, 3, 3) + (p.within === false ? " (above cap)" : "") : NOT_AVAILABLE; })]) });
    slot.replaceChildren(chart, C.legend(items), twin);
  }
  const axisMoney = (value) => (Math.abs(value) >= 1000 ? P.compactMoney(value) : "$" + group(value, 0, 2));
  function drawCollections(animate) {
    const slot = byId("pd-collect-chart"); const caption = byId("pd-collect-caption"); const surface = current.receipt.result.surface;
    const rows = surface && Array.isArray(surface.collection_sensitivity_points) ? surface.collection_sensitivity_points : [];
    const tenors = [...new Set(rows.map((p) => num(p.tenor_days)).filter((v) => v !== null))].sort((a, b) => a - b);
    const cuts = [...new Set(rows.map((p) => p.collection_share_reduction))].sort((a, b) => Number(a) - Number(b));
    if (!tenors.length || !cuts.length) { caption.textContent = "No collection sensitivity is available for this assessment."; slot.replaceChildren(); return; }
    caption.textContent = "The purchase ceiling at each tenor if buyers collect less than declared. Each line cuts the declared collection share; the dated cash path is not recomputed.";
    const classes = ["c-s1", "c-s2", "c-s3"];
    const series = cuts.slice(0, 3).map((cut, index) => {
      const sample = rows.find((p) => p.collection_share_reduction === cut); const share = percent(sample && sample.collection_share, 1);
      return { name: "Collection share " + share, short: share + " collected", className: classes[index], values: tenors.map((t) => { const p = rows.find((q) => num(q.tenor_days) === t && q.collection_share_reduction === cut); return p ? num(p.economic_cap) : null; }) };
    });
    const xs = tenors.map((_, i) => i);
    const chart = C.lineChart({ xs, xTicks: tenors.map((t, i) => ({ value: i, label: String(t) })), series, width: C.widthOf(slot, 720), height: 240, format: axisMoney, exact: (v) => "$" + group(v, 3, 3), title: (i) => "Tenor " + plural(tenors[i], "day", "days"), axisTitle: "Tenor (days)", description: "Purchase ceiling in USD per GPU-hour by tenor under three collection shares", animate });
    const twin = C.table({ summary: "View as a table", caption: "Purchase ceiling in USD per GPU-hour by tenor and collection share", columns: [{ label: "Tenor (days)" }, ...series.map((s) => ({ label: s.name, numeric: true }))], rows: tenors.map((t, i) => [String(t), ...series.map((s) => (s.values[i] === null ? NOT_AVAILABLE : group(s.values[i], 3, 3)))]) });
    slot.replaceChildren(chart, C.legend(series.map((s) => ({ label: s.name, className: s.className, kind: "line" }))), twin);
  }

  /* ----- cash and escrow tab ----------------------------------------------------------------------------------------------------- */
  function renderCashFigures(receipt, input) {
    const r = receipt.result; const s = r.summary || {}; const e = r.escrow; const cash = r.cash;
    const yieldUnits = e && e.yield && isNumeric(e.yield.total_accrued_asset_units) ? group(e.yield.total_accrued_asset_units, 0, 4) + " " + seen(e.asset && e.asset.unit, "units") : null;
    if (e) {
      kpis(byId("pd-cash-kpis"), [
        { label: "Prefunded principal", value: money(e.prefunding && e.prefunding.declared_value_usd), raw: e.prefunding && e.prefunding.declared_value_usd, note: "Restricted customer funds, kept separate from revenue" },
        { label: "Paid to provider", value: money(e.settlement && e.settlement.provider_service_paid_usd), raw: e.settlement && e.settlement.provider_service_paid_usd, note: "Hourly, against qualified service" },
        { label: "Hypothetical yield", value: yieldUnits || NOT_AVAILABLE, empty: yieldUnits === null, note: "Declared " + percent(e.yield && e.yield.annual_nominal_apr, 2, "unstated") + " APR, not guaranteed" },
        { label: "Broker yield entitlement", value: money(e.yield && e.yield.broker_economic_entitlement_usd, 4), raw: e.yield && e.yield.broker_economic_entitlement_usd, note: "Accrued entitlement; cash is separate" },
      ]);
    } else {
      kpis(byId("pd-cash-kpis"), [
        { label: "Cash required", value: money(s.cash_required), raw: s.cash_required, note: "Purchase, costs and reserve" },
        { label: "Minimum free cash", value: money(cash && cash.minimum_free_cash), raw: cash && cash.minimum_free_cash, note: "Lowest point of the dated ledger" },
        { label: "Additional funding", value: money(s.cash_shortfall), raw: s.cash_shortfall, note: "Needed to meet the declared cash floor" },
        { label: "Net operating cash", value: money(s.net_cash_flow), raw: s.net_cash_flow, note: "Before hypothetical treasury yield" },
      ]);
    }
    const funding = [
      ["Funding result", s.cash_feasible === true ? "Scenario funded" : s.cash_feasible === false ? "Scenario funding shortfall" : "Unknown liquidity or mark"],
      ["Minimum free cash", money(cash && cash.minimum_free_cash), cash && cash.minimum_free_cash_date ? "On " + longDate(cash.minimum_free_cash_date) : null],
      ["Minimum cash floor", money(cash && cash.minimum_cash_floor)],
      ["Additional funding", money(s.cash_shortfall)],
      ["Capital reserve", money(s.capital_budget), "Owned budget, held back from free cash"],
      ["Deposit financing carry", percent(s.financing_carry_fraction, 3), "Of supplier purchase cost"],
      ["Net present value", money(s.npv), "Dated net operating cash, ACT/365, at the declared discount rate"],
      ["Internal rate of return", NOT_AVAILABLE, s.irr_basis ? humanize(s.irr_basis) : "Equity financing timeline not declared"],
    ];
    const host = byId("pd-cash-detail"); host.replaceChildren();
    const block = (title, rows) => { const section = h("section", "pd-fact-block"); section.append(h("h3", "", title), facts(rows)); host.append(section); };
    block("Funding", funding);
    if (e) {
      const st = e.settlement || {}; const y = e.yield || {}; const rk = e.risk_proposal || {}; const unit = seen(e.asset && e.asset.unit, "units");
      block("Hourly escrow", [
        ["Escrow asset", F.choiceLabel("settlement.asset_kind", e.asset && e.asset.kind) + " (" + unit + ")", e.asset && e.asset.stable_parity_verified === false ? "Parity and insurance not verified" : null],
        ["Provider earned / paid", money(st.provider_service_earned_usd) + " / " + money(st.provider_service_paid_usd), "Owed: " + money(st.provider_service_owed_usd)],
        ["Buyer service earned", money(st.buyer_service_earned_usd)],
        ["Broker service margin", money(st.broker_service_economic_margin_usd)],
        ["Refund to buyer", money(st.terminal_buyer_refund_usd), "Remaining principal, after the last hour"],
        ["Yield access", F.choiceLabel("settlement.yield_access", y.access), y.cash_access_held ? "Cash access held: " + (y.hold_reasons || []).map(holdText).join("; ") : null],
        ["Buffer and collateral", money(rk.buffer_usd) + " and " + money(rk.collateral_usd), "Uncalibrated proposals; neither is posted or added to cash"],
      ]);
    } else {
      const st = (terms(receipt, input).settlement) || {};
      const open = cash && cash.unresolved_balances && typeof cash.unresolved_balances === "object" ? Object.values(cash.unresolved_balances).some((group) => group && Object.keys(group).length) : null;
      block("Settlement", [["Mode", F.choiceLabel("settlement.mode", st.mode)], ["Supplier deposit", percent(st.down_payment_fraction, 2, NOT_SUPPLIED)], ["Balances left open at the end", open === null ? NOT_AVAILABLE : open ? "Some remain; see the JSON" : "None"]]);
    }
  }
  const hourTicks = (xs) => C.niceTicks(xs[0], xs[xs.length - 1], 5).filter((t) => t >= xs[0] && t <= xs[xs.length - 1]).map((t) => ({ value: t, label: String(t) }));
  function dayTicks(xs) {
    const span = xs[xs.length - 1] - xs[0]; const step = [1, 2, 7, 14, 30, 60, 90, 180].find((n) => span / n <= 6) || 365; const out = [];
    for (let day = xs[0]; day <= xs[xs.length - 1]; day += step) out.push({ value: day, label: shortDate(new Date(day * 86400000).toISOString().slice(0, 10)) });
    return out;
  }
  function drawEscrow(animate) {
    const block = byId("pd-escrow-block"); const slot = byId("pd-escrow-chart"); const e = current.receipt.result.escrow;
    block.hidden = !e;
    if (!e) return;
    const rows = (e.chart && e.chart.rows) || []; const price = num(e.asset && e.asset.declared_price_usd);
    const xs = rows.map((row) => num(row.hour)).filter((v) => v !== null);
    const note = byId("pd-escrow-note");
    note.textContent = (e.chart && e.chart.sampled ? "Showing " + e.chart.rows_returned + " of " + e.chart.total_hours_evaluated + " hours, evenly spaced and including the first and last; totals use every hour. " : "") +
      "Principal is restricted customer funds, not revenue" + (price === null ? ". It is not valued here because no asset price was supplied." : ", valued at the declared asset price of $" + group(price, 0, 4) + ".");
    if (xs.length < 2) { slot.replaceChildren(h("p", "pd-empty-note", "No hourly path for this settlement mode.")); return; }
    const series = [];
    if (price !== null) series.push({ name: "Customer principal held", short: "Principal held", className: "c-s1", values: rows.map((row) => { const units = num(row.closing_restricted_principal_asset_units); return units === null ? null : units * price; }) });
    series.push({ name: "Buyer service earned", short: "Earned from buyer", className: price === null ? "c-s1" : "c-s2", values: rows.map((row) => num(row.cumulative_buyer_service_earned_usd)) });
    series.push({ name: "Paid to provider", short: "Paid to provider", className: price === null ? "c-s2" : "c-s3", values: rows.map((row) => num(row.cumulative_provider_service_paid_usd)) });
    const chart = C.lineChart({ xs, xTicks: hourTicks(xs), series, width: C.widthOf(slot, 720), height: 260, format: axisMoney, exact: (v) => money(v, 2), title: (i) => "Hour " + xs[i], axisTitle: "Hours of service", description: "Hourly vesting in USD: " + series.map((s) => s.name).join(", "), animate });
    const twin = C.table({ summary: "View as a table", caption: "Hourly vesting in USD", columns: [{ label: "Hour" }, ...series.map((s) => ({ label: s.name, numeric: true }))], rows: xs.map((x, i) => [String(x), ...series.map((s) => money(s.values[i], 2))]) });
    slot.replaceChildren(chart, C.legend(series.map((s) => ({ label: s.name, className: s.className, kind: "line" }))), twin);
  }
  function drawCash(animate) {
    const slot = byId("pd-cash-chart"); const note = byId("pd-cash-note"); const cash = current.receipt.result.cash;
    const days = cash && Array.isArray(cash.days) ? cash.days : [];
    const xs = days.map((d) => (typeof d.on === "string" ? Date.parse(d.on + "T00:00:00Z") / 86400000 : null)).filter((v) => v !== null && Number.isFinite(v));
    if (!cash || xs.length < 2 || xs.length !== days.length) { note.textContent = "No dated cash path is available for this assessment."; slot.replaceChildren(); return; }
    const floor = num(cash.minimum_cash_floor);
    note.textContent = "Free cash is what remains after reserves and restricted deposits. Its lowest point is " + money(cash.minimum_free_cash) + (cash.minimum_free_cash_date ? " on " + longDate(cash.minimum_free_cash_date) : "") + (floor === null ? "." : ", against a declared floor of " + money(floor, 0) + (cash.cash_floor_feasible === true ? ", so the floor holds under these terms." : cash.cash_floor_feasible === false ? ", so the floor is breached." : "."));
    const series = [{ name: "Cash balance", short: "Cash balance", className: "c-s1", values: days.map((d) => num(d.cash)) }, { name: "Free cash after reserves", short: "Free cash", className: "c-s2", values: days.map((d) => num(d.free_cash)) }];
    const chart = C.lineChart({ xs, xTicks: dayTicks(xs), series, width: C.widthOf(slot, 720), height: 260, format: axisMoney, exact: (v) => money(v, 2), title: (i) => longDate(days[i].on), reference: floor === null ? null : { value: floor, label: "Minimum cash floor " + money(floor, 0) }, axisTitle: "Date (UTC)", description: "Dated cash path in USD: cash balance and free cash after reserves", animate });
    const twin = C.table({ summary: "View as a table", caption: "Dated cash path in USD", columns: [{ label: "Date" }, { label: "Cash balance", numeric: true }, { label: "Free cash after reserves", numeric: true }], rows: days.map((d) => [longDate(d.on), money(d.cash, 2), money(d.free_cash, 2)]) });
    slot.replaceChildren(chart, C.legend([...series.map((s) => ({ label: s.name, className: s.className, kind: "line" })), ...(floor === null ? [] : [{ label: "Minimum cash floor", className: "c-floor", kind: "line" }])]), twin);
  }

  /* ----- agreement terms tab ----------------------------------------------------------------------------------------------------- */
  const midnight = (value) => typeof value === "string" && /T00:00(:00)?Z?$/.test(value);
  const instant = (value) => (midnight(value) ? longDate(value) : utcStamp(value));
  const windowText = (start, end) => instant(start) + " to " + instant(end);
  function renderTerms(receipt, input) {
    const t = terms(receipt, input); const p = t.provider || {}; const c = t.capacity || {}; const q = t.pricing || {}; const st = t.settlement || {}; const pw = q.power || {};
    const gpus = isNumeric(c.total_gpu_count) ? Number(c.total_gpu_count) : isNumeric(c.node_count) && isNumeric(c.gpus_per_node) ? Number(c.node_count) * Number(c.gpus_per_node) : null;
    const days = spanDays(c.starts_at, c.ends_at);
    const share = (value) => percent(value, 2, NOT_SUPPLIED);
    const sections = [
      ["Parties", [["Supplier", seen(p.label)], ["Buyer", seen(st.buyer_label)], ["Hardware", seen(c.model) + (isNumeric(c.memory_gib) ? " · " + c.memory_gib + " GiB per GPU" : "")], ["Allocation", gpus === null ? NOT_SUPPLIED : plural(Number(c.node_count), "node", "nodes") + " × " + c.gpus_per_node + " GPUs = " + plural(gpus, "GPU", "GPUs")]]],
      ["Site and service window", [["Site", seen(c.location) + (c.country_code ? ", " + c.country_code : "")], ["Facility", seen(c.colocation), c.ownership ? F.choiceLabel("capacity.ownership", c.ownership) : null], ["Service window", windowText(c.starts_at, c.ends_at), (days ? plural(days, "day", "days") + ", " : "") + "UTC"]]],
      ["Price and power", [
        ["Rate structure", q.rate_type === "variable" ? "Variable, " + rate(q.variable_low) + " to " + rate(q.variable_high) : F.choiceLabel("pricing.rate_type", q.rate_type || ""), perHour],
        ["Supplier and buyer price", rate(q.supplier_rate, NOT_SUPPLIED) + " and " + rate(q.buyer_rate, NOT_SUPPLIED), perHour],
        ["Billed utilization and collection", share(q.billed_utilization) + " and " + share(q.collection_share)],
        ["Required and target margin", share(q.required_margin) + " and " + share(q.target_margin)],
        ["Fees", share(q.fee_on_collected) + " of collections and " + share(q.fee_on_gross) + " of billings"],
        ["Power", pw.inclusion ? F.choiceLabel("pricing.power.inclusion", pw.inclusion) : NOT_SUPPLIED, pw.payer ? "Payer: " + F.choiceLabel("pricing.power.payer", pw.payer) : null]]],
      ["Provider claims, declared and unverified", [["SLA and response", share(p.sla_fraction) + " and " + (isNumeric(p.response_hours) ? plural(Number(p.response_hours), "hour", "hours") : NOT_SUPPLIED)], ["Uptime", share(p.uptime_fraction)], ["Compliance", seen(p.compliance)], ["Privacy", seen(p.privacy)], ["Evidence basis", seen(p.evidence_basis)]]],
      ["Settlement and protection", [
        ["Mode", st.mode ? F.choiceLabel("settlement.mode", st.mode) : NOT_SUPPLIED], ["Supplier deposit", share(st.down_payment_fraction), "Financed at " + share(st.financing_apr) + " APR"],
        ["Provider security", isNumeric(st.provider_collateral_usd) ? money(st.provider_collateral_usd, 0) + " proposed" : NOT_SUPPLIED, "Posting is not verified"],
        ["Vesting basis", seen(st.vesting_basis)], ["Escrow asset", st.asset_kind ? F.choiceLabel("settlement.asset_kind", st.asset_kind) + " (" + seen(st.asset_unit) + ")" : NOT_SUPPLIED],
        ["Yield shares", "Provider " + share(st.yield_share_provider) + ", broker " + share(st.yield_share_broker) + ", buyer " + share(st.yield_share_buyer), st.yield_access ? F.choiceLabel("settlement.yield_access", st.yield_access) : null]]],
      ["Unresolved", [["Governing law and courts", "Unresolved in this demonstration"], ["Signature authority", "Unresolved"], ["Legal entitlements", "Not verified"], ["Execution", "None. No signing, custody or money movement occurs."]]],
    ];
    const target = byId("pd-terms"); target.replaceChildren();
    sections.forEach(([title, rows]) => { const section = h("section", "pd-fact-block"); section.append(h("h3", "", title), facts(rows)); target.append(section); });
    byId("pd-terms-note").textContent = receipt.result.agreement_terms ? "The download is an unsigned, nonbinding compute-services agreement and quote schedule built from this saved assessment. No signing, custody or money movement occurs." : "A held assessment has no agreement terms, so there is no agreement to download. The declared terms are shown as entered.";
  }

  /* ----- public ------------------------------------------------------------------------------------------------------------------ */
  function render(receipt, input, references) {
    current.receipt = receipt; current.input = input; current.references = references || []; current.drawn = new Set();
    renderHead(receipt, input); renderHeadline(receipt, input); renderLedger(receipt); renderCashFigures(receipt, input); renderTerms(receipt, input);
    const refs = (receipt.result.live_references && Array.isArray(receipt.result.live_references.references) ? receipt.result.live_references.references : current.references);
    byId("pd-modal-rates").replaceChildren(referenceTable(refs));
    byId("pd-receipt").textContent = "Saved assessment " + String(receipt.snapshot_id).slice(0, 12) + " · " + utcStamp(receipt.created_at);
  }
  /* Draw the charts of one tab at the width they are shown at. The first draw of each chart per assessment may animate; redraws never do. */
  function draw(tab) {
    if (!current.receipt) return;
    const once = (key) => { const first = !current.drawn.has(key); current.drawn.add(key); return first; };
    if (tab === "quote") { drawRates(once("rates")); drawSurface(once("surface")); drawCollections(once("collections")); }
    if (tab === "cash") { drawEscrow(once("escrow")); drawCash(once("cash")); }
  }
  function reset() { current.receipt = null; current.input = null; current.drawn = new Set(); }

  P.view = Object.freeze({ render, draw, reset, referenceTable, facts, current, surfaceModel, rateRows });
})();
