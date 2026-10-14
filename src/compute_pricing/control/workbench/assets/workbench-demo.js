/* Brief, Overview and Quotes: three views over one locally simulated market book.
   The server owns every number (/v1/book); this file only draws it and sends scenario controls. */
(() => {
  "use strict";
  const host = window.ComputeHost; const charts = window.ComputeCharts;
  if (!host || !charts) return;
  const { api, byId, notify, showView } = host;
  const GRADES = ["A", "B", "C", "D"];
  const POLL_MS = 2000;
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const FIELD_NAMES = { location: "Location", country: "Country", moq: "Minimum order", interconnect: "Interconnect", cooling: "Cooling", lead_weeks: "Lead time", months: "Term", down_payment: "Down payment", payment_days: "Payment terms", expires: "Expiry" };
  const CATEGORIES = { certification: "Certification", dc_tier: "Facility tier", sla: "SLA and uptime", delivery: "Delivery record", credit: "Counterparty credit", responsiveness: "Responsiveness" };
  const SCENARIOS = [["price_war", "Price war"], ["supply_shock", "Supply shock"], ["downgrade", "Provider downgrade"]];
  const SCENARIO_DETAIL = { price_war: "Weaker sellers undercut B300", supply_shock: "Large H200 offers withdrawn", downgrade: "The largest grade A seller loses its standing" };

  const state = { data: null, tag: "", model: "B300", view: "brief", sort: "allin", selected: "", showAll: false, inflight: false, lastAlert: null, flash: new Set(), fresh: new Set(), epoch: null, kpi: new Map(), error: "", busy: false, timer: null };

  /* ---- small helpers ---- */
  function h(tag, className, ...children) {
    const node = document.createElement(tag); if (className) node.className = className;
    children.flat(Infinity).forEach((child) => { if (child !== null && child !== undefined && child !== false) node.append(typeof child === "object" ? child : document.createTextNode(String(child))); });
    return node;
  }
  const num = (value) => (value === null || value === undefined ? null : Number(value));
  const int = (value) => String(Math.round(value)).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const usd = (value, places = 2) => "$" + Number(value).toFixed(places);
  const pct = (value, places = 1, sign = false) => (sign && value > 0 ? "+" : value < 0 ? "−" : "") + Math.abs(value * 100).toFixed(places) + "%";
  const compact = (value) => value >= 1e9 ? (value / 1e9).toFixed(2) + "B" : value >= 1e6 ? (value / 1e6).toFixed(1) + "M" : value >= 1e4 ? (value / 1e3).toFixed(1) + "k" : int(value);
  function clock(iso, short = false) {
    const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso || ""); if (!match) return "";
    return short ? match[4] + ":" + match[5] : MONTHS[Number(match[2]) - 1] + " " + Number(match[3]) + " " + match[4] + ":" + match[5];
  }
  const gradeClass = (grade) => "g-" + String(grade).toLowerCase();
  const chip = (grade, title) => { const node = h("span", "grade " + gradeClass(grade), grade); node.setAttribute("title", title || "Grade " + grade); return node; };
  const model = (name) => state.data.models.find((entry) => entry.model === name);
  const live = () => state.data !== null;
  function replace(id, ...children) { byId(id).replaceChildren(...children.flat().filter(Boolean)); }
  function empty(message) { return h("p", "empty-state", message); }
  function legendGrades() { return charts.legend(GRADES.map((g) => ({ label: "Grade " + g, className: gradeClass(g) }))); }
  const lowestPrice = (entry) => (entry.cheapest ? Number(entry.cheapest.price) : null);

  /* ---- polling and control ---- */
  async function poll(force = false) {
    if (state.inflight || !host.isSession() || (document.hidden && !force)) return;
    state.inflight = true; const meta = { ifNoneMatch: force ? "" : state.tag };
    try {
      const data = await api("/v1/book", {}, meta);
      state.error = "";
      if (data) {
        const first = state.data === null; const previous = state.data;
        state.data = data; state.tag = meta.etag || "";
        trackChanges(previous, first); render();
        if (first || previous.meta.paused !== data.meta.paused) paintControls();  // the buttons depend on whether the book is live and paused
      }
      paintStatus();  // also clears "Reconnecting" when the book is unchanged (304)
    } catch (error) {
      state.error = error.message; paintStatus(); if (state.data === null) render();
    } finally { state.inflight = false; }
  }
  function trackChanges(previous, firstLoad) {
    let first = firstLoad;
    if (state.epoch !== state.data.meta.epoch) { state.epoch = state.data.meta.epoch; state.lastAlert = null; state.kpi.clear(); first = true; }  // a reset restarts alert numbering
    const latest = state.data.alerts.length ? state.data.alerts[0].n : 0;
    state.flash = new Set(first || state.lastAlert === null ? [] : state.data.alerts.filter((a) => a.n > state.lastAlert).map((a) => a.n));
    state.fresh = new Set(first || !previous ? [] : state.data.quotes.filter((q) => q.changed_tick > previous.meta.tick).map((q) => q.id));
    state.lastAlert = latest; rememberScenarios();
  }
  async function control(action, scenario) {
    if (state.busy) return; state.busy = true; paintControls();
    try { await api("/v1/book/control", { method: "POST", body: JSON.stringify(scenario ? { action, scenario } : { action }) }); state.tag = ""; await poll(true); }
    catch (error) { notify(error.message, true); }
    finally { state.busy = false; paintControls(); }
  }
  function controlBar() {
    const paused = Boolean(state.data?.meta.paused); const group = h("div", "sim-controls");
    const button = (label, title, handler, className = "quiet-button") => { const node = h("button", className, label); node.type = "button"; node.setAttribute("title", title); node.disabled = state.busy || !live(); node.addEventListener("click", handler); return node; };
    group.append(h("span", "sim-label", "Simulate"));
    SCENARIOS.forEach(([key, name]) => group.append(button(name, SCENARIO_DETAIL[key], () => control("scenario", key), "secondary-button")));
    group.append(h("span", "sim-rule"), button(paused ? "Resume" : "Pause", paused ? "Resume the market clock" : "Freeze the market clock", () => control(paused ? "resume" : "pause")), button("Reset", "Return to the workbook's starting book", () => control("reset")));
    return group;
  }
  function paintControls() { ["desk-controls", "quotes-controls"].forEach((id) => replace(id, controlBar())); }
  function paintStatus() {
    const dot = byId("session-dot"); const label = byId("session-state");
    if (!host.isSession()) return;
    const paused = Boolean(state.data?.meta.paused);
    label.textContent = state.error ? "Reconnecting" : !state.data ? "Connecting" : paused ? "Paused" : "Live";
    dot.classList.toggle("live", Boolean(state.data) && !paused && !state.error); dot.classList.toggle("paused", paused);
  }

  /* ---- shared visuals ---- */
  function headline() {
    const entry = state.data.models.filter((m) => m.cheapest && m.best).sort((a, b) => b.gpus - a.gpus)[0];
    return entry || null;
  }

  /* ---- Brief ---- */
  /* The landing view. Its charts come from one small local primitive, briefBars, so the page owns its own
     type and spacing; colour still arrives only through CSS classes (--gc), keeping both themes and the CSP intact. */
  const SVG_NS = "http://www.w3.org/2000/svg";
  const r2 = (value) => Math.round(value * 100) / 100;
  let briefDrawn = false; let briefResize = null;
  function svgNode(tag, attributes = {}, ...children) {
    const element = document.createElementNS(SVG_NS, tag);
    Object.entries(attributes).forEach(([name, value]) => { if (value !== null && value !== undefined) element.setAttribute(name, String(value)); });
    children.flat().forEach((child) => { if (child) element.append(child); });
    return element;
  }
  function svgText(content, x, y, className, anchor = "start") {
    const element = svgNode("text", { x: r2(x), y: r2(y), class: className, "text-anchor": anchor, dy: "0.34em" }); element.textContent = content; return element;
  }
  function svgTip(element, content) { if (content) { const title = svgNode("title"); title.textContent = content; element.append(title); } return element; }
  const briefWidth = (limit) => Math.max(300, Math.min(limit, (Number(window.innerWidth) || 1440) - 48));
  /* Horizontal bars on one scale from zero. A row carries either `value` or stacked `parts`; `text` prints at the end of
     its bar (or in place of it when there is none) and `sub` sits under the label. */
  function briefBars({ rows, max, width, labelWidth = 88, valueWidth = 72, rowHeight = 48, bar = 12, axis = [], grow = false, description }) {
    const top = axis.length ? 26 : 0; const height = top + rows.length * rowHeight; const scale = max > 0 ? max : 1;
    const chart = svgNode("svg", { viewBox: "0 0 " + width + " " + height, class: "bf-chart" + (grow ? " bf-grow" : ""), role: "img", "aria-label": description, focusable: "false" });
    const x = (value) => labelWidth + (Math.max(0, value) / scale) * (width - labelWidth - valueWidth);
    axis.forEach((tick) => chart.append(svgNode("line", { x1: r2(x(tick.value)), x2: r2(x(tick.value)), y1: top - 10, y2: height, class: "bf-grid" }), svgText(tick.text, x(tick.value), 4, "bf-tick", "middle")));
    rows.forEach((row, index) => {
      const cy = top + index * rowHeight + rowHeight / 2;
      const rank = " bf-r" + index;  // the row's place in the entrance stagger; see .bf-grow in workbench.css
      if (row.label) chart.append(svgText(row.label, 0, row.sub ? cy - 8 : cy, "bf-row-label" + rank));
      if (row.sub) chart.append(svgText(row.sub, 0, cy + 10, "bf-row-sub" + rank));
      const parts = row.parts || [{ value: row.value, className: row.className, title: row.title }];
      const total = parts.reduce((sum, part) => sum + (part.value > 0 ? part.value : 0), 0);
      if (total > 0) {
        const group = svgNode("g", { class: "bf-bar-group" + rank }); let cursor = 0;
        parts.forEach((part) => {
          if (!(part.value > 0)) return;
          const from = x(cursor); cursor += part.value;
          group.append(svgTip(svgNode("rect", { x: r2(from), y: r2(cy - bar / 2), width: Math.max(2, r2(x(cursor) - from - (cursor < total ? 1 : 0))), height: bar, rx: 2, class: "bf-bar " + (part.className || "") }), part.title));
        });
        chart.append(group); if (row.text) chart.append(svgText(row.text, x(total) + 10, cy, "bf-value" + rank));
      } else if (row.text) chart.append(svgText(row.text, labelWidth, cy, "bf-note" + rank));
    });
    return chart;
  }
  const statLine = (value, caption) => [h("strong", "bf-stat-value", value), h("span", "bf-stat-text", caption)];

  function renderBrief() {
    const slots = ["brief-facts", "brief-fact-gaps", "brief-gaps", "brief-fact-cost", "brief-anatomy", "brief-fact-grades", "brief-grades", "brief-weights", "brief-eligible", "brief-basis-live"];
    if (!live()) { replace("brief-live", empty(state.error || "Opening the simulated book…")); slots.forEach((id) => replace(id)); return; }
    const grow = !briefDrawn; briefDrawn = true;
    briefHero(state.data, grow); briefNumbers(state.data, grow); briefProblems(state.data, grow); briefMethod(state.data, grow);
  }
  function briefHero(data, grow) {
    const kpis = data.kpis;
    const rows = data.models.map((entry) => {
      const low = lowestPrice(entry); const best = entry.best; const ranked = Boolean(best) && entry.basis !== null;
      return {
        label: entry.model, sub: ranked && low !== null ? usd(low) + " → " + usd(best.risk_adjusted) : low !== null ? usd(low) : "No quotes",
        value: ranked ? entry.basis * 100 : 0, text: ranked ? pct(entry.basis, 1, true) : "No eligible seller", className: "",
        title: ranked ? entry.model + ": lowest quote " + entry.cheapest.id + " (" + entry.cheapest.provider + ", grade " + entry.cheapest.grade + ") at " + usd(low) + "; best eligible " + best.id + " (" + best.provider + ", grade " + best.grade + ") at " + usd(best.risk_adjusted, 3) + " all-in" : "",
      };
    });
    const reach = Math.max(30, Math.ceil(Math.max(0, ...rows.map((row) => row.value)) / 10) * 10);
    const axis = Array.from({ length: reach / 10 + 1 }, (_, step) => ({ value: step * 10, text: step ? "+" + step * 10 + "%" : "0%" }));
    const widest = rows.filter((row) => row.value > 0).sort((a, b) => b.value - a.value)[0];
    const description = "Basis by GPU model: how much more the best eligible quote costs all-in than the lowest quote. " + rows.map((row) => row.label + " " + row.text).join(", ") + "." + (widest ? " " + widest.label + " has the widest gap." : "");
    replace("brief-live", briefBars({ rows, max: reach, width: briefWidth(600), labelWidth: 100, valueWidth: 76, rowHeight: 56, bar: 14, axis, grow, description }),
      h("p", "bf-caption", "Under each model: the lowest quote → the best eligible all-in cost, per GPU-hour. " + int(kpis.live_quotes) + " live quotes from " + kpis.providers_quoting + " providers; simulated, refreshed every few seconds."));
  }
  function briefNumbers(data, grow) {
    const k = data.kpis; const s = data.series;
    const items = [
      { label: "Live quotes", value: int(k.live_quotes), sub: "from " + k.providers_quoting + " providers", spark: s.live },
      { label: "GPUs on offer", value: compact(k.gpus), sub: "across " + k.models + " models", spark: s.gpus },
      { label: "Eligible quotes", value: k.eligible_share === null ? "—" : pct(k.eligible_share, 0), sub: int(k.eligible_quotes) + " clear the bar", spark: s.eligible_share },
      { label: "Market basis", value: k.basis === null ? "—" : pct(k.basis, 1, true), sub: "best eligible over lowest quote", spark: s.basis },
    ];
    replace("brief-facts", items.map((item) => h("div", grow ? "bf-number bf-in" : "bf-number", h("span", "bf-number-label", item.label), h("strong", "bf-number-value", item.value), h("span", "bf-number-sub", item.sub), item.spark ? charts.sparkline(item.spark, { width: 120, height: 32 }) : null)));
  }
  /* One model's lowest quote whose hidden costs are worth showing. The pick sticks while it stays the lowest quote of its
     model, so the figure does not jump between quotes as the book ticks. */
  let briefPick = "";
  const briefUplift = (quote) => (quote.risk_adjusted === null ? 0 : quote.risk_adjusted / Number(quote.price) - 1);
  function briefExample(data) {
    const picks = data.models.filter((entry) => entry.cheapest).map((entry) => ({ entry, quote: data.quotes.find((q) => q.id === entry.cheapest.id) })).filter((pick) => pick.quote && pick.quote.risk_adjusted !== null);
    const kept = picks.find((pick) => pick.quote.id === briefPick && briefUplift(pick.quote) >= 0.05);
    const chosen = kept || picks.slice().sort((a, b) => briefUplift(b.quote) - briefUplift(a.quote) || b.entry.gpus - a.entry.gpus)[0] || null;
    briefPick = chosen ? chosen.quote.id : ""; return chosen;
  }
  function briefProblems(data, grow) {
    const kpis = data.kpis;
    // 1. Terms left blank
    const heavy = data.completeness.filter((c) => c.missing >= 4).reduce((sum, c) => sum + c.quotes, 0);
    const gaps = Object.entries(data.field_gaps).sort((a, b) => b[1] - a[1]).slice(0, 5); const total = Math.max(1, kpis.live_quotes);
    replace("brief-fact-gaps", statLine(pct(heavy / total, 0), "of live quotes leave four or more of ten key terms blank."));
    replace("brief-gaps", briefBars({ rows: gaps.map(([field, count]) => ({ label: FIELD_NAMES[field] || field, value: count / total, text: pct(count / total, 0), className: "part-price", title: count + " of " + total + " live quotes omit " + (FIELD_NAMES[field] || field).toLowerCase() })), max: Math.max(0.1, ...gaps.map(([, count]) => count / total)), width: briefWidth(520), labelWidth: 112, valueWidth: 56, rowHeight: 40, bar: 12, grow,
      description: "The terms live quotes most often leave blank: " + gaps.map(([field, count]) => (FIELD_NAMES[field] || field).toLowerCase() + " " + pct(count / total, 0)).join(", ") + "." }));
    // 2. What the headline price leaves out
    const example = briefExample(data);
    if (example) {
      const quote = example.quote; const price = Number(quote.price); const financing = quote.financing || 0; const exposure = quote.exposure || 0; const allin = price + financing + exposure;
      replace("brief-fact-cost", statLine(pct(allin / price - 1, 0, true), ["Quote " + quote.id + ", the lowest " + example.entry.model + " offer, asks " + usd(price) + " ", h("span", "bf-nowrap", "per GPU-hour"), ". All-in it costs " + usd(allin) + "."]));
      const part = (name, value, className) => h("div", "", h("dt", "", h("span", "swatch " + className), name), h("dd", "", usd(value, value < 1 ? 3 : 2)));
      replace("brief-anatomy",
        briefBars({ rows: [{ label: "Quoted", parts: [{ value: price, className: "part-price", title: "Quoted price " + usd(price) }], text: usd(price) },
          { label: "All-in", parts: [{ value: price, className: "part-price", title: "Quoted price " + usd(price) }, { value: financing, className: "part-financing", title: "Financing on the down payment " + usd(financing, 3) }, { value: exposure, className: "part-exposure", title: "Expected loss if the seller fails " + usd(exposure, 3) }], text: usd(allin) }],
        max: allin, width: briefWidth(520), labelWidth: 64, valueWidth: 64, rowHeight: 48, bar: 18, grow, description: "Quote " + quote.id + " per GPU-hour: quoted " + usd(price) + ", plus financing " + usd(financing, 3) + ", plus expected loss " + usd(exposure, 3) + ", is " + usd(allin) + " all-in." }),
        h("dl", "bf-split", part("Quoted price", price, "part-price"), part("Financing", financing, "part-financing"), part("Expected loss", exposure, "part-exposure")),
        h("p", "bf-caption", quote.id + " · " + quote.provider + " · grade " + quote.grade));
    } else { replace("brief-fact-cost", statLine("—", "No quote with a stated term to price yet.")); replace("brief-anatomy", empty("No comparison available yet.")); }
    // 3. The lowest quotes come from the weakest sellers
    const weak = data.models.filter((m) => m.cheapest && ["C", "D"].includes(m.cheapest.grade)).length;
    const below = data.models.filter((m) => m.cheapest && m.median).map((m) => ({ entry: m, gap: 1 - lowestPrice(m) / m.median }));
    replace("brief-fact-grades", statLine(weak + " of " + data.models.length, "GPU models have a grade C or D seller as the lowest quote."));
    replace("brief-grades", briefBars({ rows: below.map(({ entry, gap }) => ({ label: entry.model, sub: "Grade " + entry.cheapest.grade, value: Math.max(0, gap), text: pct(Math.max(0, gap), 0) + " below", className: gradeClass(entry.cheapest.grade), title: entry.cheapest.id + " · " + entry.cheapest.provider + " · grade " + entry.cheapest.grade + " · " + usd(lowestPrice(entry)) + " against a median of " + usd(entry.median) })),
      max: Math.max(0.25, ...below.map((row) => row.gap)), width: briefWidth(520), labelWidth: 84, valueWidth: 88, rowHeight: 48, bar: 12, grow,
      description: "How far the lowest quote for each GPU model sits below that model's median, coloured by the seller's grade: " + below.map(({ entry, gap }) => entry.model + " " + pct(Math.max(0, gap), 0) + " below, grade " + entry.cheapest.grade).join("; ") + "." }), legendGrades());
  }
  function briefMethod(data, grow) {
    const kpis = data.kpis; const weights = Object.entries(data.assumptions.weights).sort((a, b) => b[1] - a[1]);
    replace("brief-weights",
      briefBars({ rows: [{ label: "", parts: weights.map(([key, value], index) => ({ value, className: "w" + index, title: CATEGORIES[key] + " " + pct(value, 0) })), text: "" }], max: 1, width: briefWidth(360), labelWidth: 0, valueWidth: 0, rowHeight: 28, bar: 16, grow,
        description: "Scorecard weights: " + weights.map(([key, value]) => CATEGORIES[key] + " " + pct(value, 0)).join(", ") + "." }),
      charts.legend(weights.map(([key, value], index) => ({ label: CATEGORIES[key] + " " + pct(value, 0), className: "w" + index }))));
    replace("brief-eligible", statLine(int(kpis.eligible_quotes) + " of " + int(kpis.live_quotes), "live quotes clear the bar right now."));
    replace("brief-basis-live", kpis.basis === null ? null : h("span", "", h("strong", "", pct(kpis.basis, 1, true)), " across today's book, weighted by GPUs."));
  }

  /* ---- Overview ---- */
  function delta(series, kind, windowSize = 48) {
    const values = series.filter((v) => v !== null && v !== undefined); if (values.length < 2) return null;
    const last = values[values.length - 1]; const prior = values[Math.max(0, values.length - 1 - windowSize)]; const diff = last - prior;
    if (kind === "pp") return { text: (diff >= 0 ? "+" : "−") + Math.abs(diff * 100).toFixed(1) + " pt", up: diff >= 0 };
    if (kind === "pct") return { text: (diff >= 0 ? "+" : "−") + Math.abs((diff / prior) * 100).toFixed(1) + "%", up: diff >= 0 };
    return { text: (diff >= 0 ? "+" : "−") + int(Math.abs(diff)), up: diff >= 0 };
  }
  function renderKpis() {
    const data = state.data; const k = data.kpis; const s = data.series;
    const items = [
      { key: "quotes", label: "Live quotes", value: int(k.live_quotes), sub: "from " + k.providers_quoting + " of " + k.providers_total + " providers", change: delta(s.live, "n"), spark: s.live },
      { key: "gpus", label: "GPUs on offer", value: compact(k.gpus), sub: "across " + k.models + " models", change: delta(s.gpus, "pct"), spark: s.gpus },
      { key: "value", label: "Contract value", value: "$" + compact(k.contract_value), sub: "notional, all live quotes" },
      { key: "eligible", label: "Eligible", value: k.eligible_share === null ? "—" : pct(k.eligible_share, 0), sub: int(k.eligible_quotes) + " clear the bar", change: delta(s.eligible_share, "pp"), spark: s.eligible_share },
      { key: "basis", label: "Market basis", value: k.basis === null ? "—" : pct(k.basis, 1, true), sub: "all-in vs lowest quote", change: delta(s.basis, "pp"), spark: s.basis },
      { key: "weak", label: "Lowest quote ineligible", value: k.cheapest_is_ineligible + " of " + k.models, sub: "models, the cheapest seller fails the bar" },
    ];
    replace("desk-kpis", items.map((item) => {
      const changed = state.kpi.has(item.key) && state.kpi.get(item.key) !== item.value; state.kpi.set(item.key, item.value);
      return h("div", "kpi", h("span", "kpi-label", item.label), h("strong", "kpi-value" + (changed ? " flash" : ""), item.value),
        h("span", "kpi-sub", item.sub), item.change ? h("span", "kpi-delta " + (item.change.up ? "up" : "down"), item.change.text + " · 24h") : null, item.spark ? charts.sparkline(item.spark) : null);
    }));
  }
  /* Charts are drawn at the width they are shown at, so their type keeps its set size on any screen. */
  function fit(id, fallback) { const width = Math.floor(Number(byId(id).clientWidth) || 0); return width >= 240 ? width : fallback; }
  function median(values) {
    const sorted = values.filter((v) => Number.isFinite(v)).sort((a, b) => a - b); const mid = sorted.length >> 1;
    return sorted.length ? (sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2) : null;
  }
  function modelTabs(containerId, withCounts = true) {
    const box = byId(containerId); const names = state.data.models.map((entry) => entry.model); const current = Array.from(box.children);
    if (!withCounts && current.length === names.length && current.every((button, i) => button.dataset.model === names[i])) {  // same tabs: keep the nodes so focus survives the poll
      current.forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.model === state.model))); return;
    }
    replace(containerId, state.data.models.map((entry) => {
      const button = h("button", "tab", entry.model, withCounts ? h("small", "", String(entry.quotes)) : null); button.type = "button"; button.dataset.model = entry.model; button.setAttribute("aria-pressed", String(entry.model === state.model));
      button.addEventListener("click", () => { state.model = entry.model; state.selected = ""; render(); }); return button;
    }));
  }
  const text = (id, value) => { byId(id).textContent = value; };

  /* Basis by GPU model: lowest quote and best eligible all-in cost as paired bars on one zero-based $/GPU-hour axis. */
  function renderBasis() {
    const data = state.data; const width = fit("desk-basis", 680); const narrow = width < 480;
    const rows = data.models.map((entry) => {
      const low = lowestPrice(entry); const cheap = entry.cheapest; const best = entry.best;
      return {
        label: entry.model, sub: entry.eligible + (narrow ? "/" : " of ") + entry.quotes + " eligible",
        bars: [
          { value: low, text: low === null ? "" : usd(low), className: "part-price", grade: cheap ? cheap.grade : null, title: cheap ? "Lowest quote " + cheap.id + " · " + cheap.provider + " · grade " + cheap.grade + " · " + usd(low) + " quoted · " + cheap.missing + " of 10 key terms missing" : "" },
          best ? { value: best.risk_adjusted, text: usd(best.risk_adjusted, 3), className: "part-best", grade: best.grade, title: "Best eligible " + best.id + " · " + best.provider + " · grade " + best.grade + " · " + usd(best.risk_adjusted, 3) + " all-in · " + usd(best.price) + " quoted" } : { value: null, absent: "No eligible seller" },
        ],
        trail: best && entry.basis !== null ? pct(entry.basis, 1, true) : "—", trailClass: best ? "" : "none",
      };
    });
    const widest = data.models.filter((m) => m.basis !== null && m.cheapest).sort((a, b) => b.basis - a.basis)[0]; const none = data.models.filter((m) => !m.best).map((m) => m.model);
    const description = "Lowest quote against best eligible all-in cost, dollars per GPU-hour, for each GPU model. " + data.models.map((m) => m.model + " " + (m.cheapest ? usd(lowestPrice(m)) : "no quote") + (m.best ? " against " + usd(m.best.risk_adjusted, 3) + ", basis " + pct(m.basis, 1, true) : ", no eligible seller")).join("; ") + ".";
    replace("desk-basis",
      charts.groupedBars({ rows, width, format: (v) => "$" + (Number.isInteger(v) ? v : v.toFixed(2)), labelWidth: narrow ? 84 : 108, trailWidth: narrow ? 52 : 62, valueRoom: narrow ? 76 : 86, tickCount: narrow ? 5 : 7, trailTitle: "Basis", description }),
      charts.legend([{ label: "Lowest quote, as quoted", className: "part-price" }, { label: "Best eligible, all-in", className: "part-best" }]),
      h("p", "figure-caption", "The letter beside each bar is the seller's grade. " + (widest ? widest.model + " has the widest basis at " + pct(widest.basis, 1, true) + ", and its lowest quote comes from a grade " + widest.cheapest.grade + " seller. " : "") + (none.length ? none.join(", ") + (none.length > 1 ? " have" : " has") + " no eligible seller." : "")));
  }

  /* Scenario flags for the price chart. A flag for another model's market is drawn faint and names that model. */
  const SCENARIO_NAMES = [[/^Price war/, "Price war"], [/^Supply shock/, "Supply shock"], [/downgraded/, "Provider downgrade"]];
  /* The feed keeps only the latest alerts, so a scenario is remembered here until its tick leaves the chart window. */
  const scenarioSeen = new Map(); let scenarioEpoch = null;
  function rememberScenarios() {
    const data = state.data; if (!data) return;
    if (scenarioEpoch !== data.meta.epoch) { scenarioEpoch = data.meta.epoch; scenarioSeen.clear(); }
    data.alerts.forEach((a) => { if (a.kind === "scenario") scenarioSeen.set(a.n, a); });
    [...scenarioSeen].forEach(([n, a]) => { if (!data.series.ticks.includes(a.tick)) scenarioSeen.delete(n); });
  }
  function scenarioMarkers(forModel) {
    const data = state.data; rememberScenarios();
    return [...scenarioSeen.values()].map((a) => {
      const named = SCENARIO_NAMES.find(([pattern]) => pattern.test(a.text)); const target = /^(?:Price war|Supply shock) in ([^:]+):/.exec(a.text); const dim = Boolean(target) && target[1] !== forModel;
      return { index: data.series.ticks.indexOf(a.tick), label: (named ? named[1] : "Scenario") + (dim ? " · " + target[1] : ""), dim, title: a.text };
    }).filter((marker) => marker.index >= 0);
  }
  /* Price history for one model: lowest quote against best eligible all-in cost, with the basis as the shaded gap. */
  function renderTrend() {
    const data = state.data; const m = data.models.find((entry) => entry.model === state.model) || data.models[0]; const s = data.series.models[m.model];
    const times = data.series.times; const hasBest = s.best.some((v) => v !== null); const width = fit("desk-trend", 540); const narrow = width < 460; const low = lowestPrice(m);
    const lines = [{ key: "cheapest", name: "Lowest quote", values: s.cheapest, className: "ln-cheap" }, hasBest ? { key: "best", name: "Best eligible", values: s.best, className: "ln-best" } : { key: "median", name: "Median quote", values: s.median, className: "ln-median" }];
    const at = (values, i) => (values[i] === null || values[i] === undefined ? "none" : usd(values[i], 2));
    const prior = s.basis[Math.max(0, s.basis.length - 1 - 48)];
    text("desk-trend-title", m.model + " price history");
    const readout = h("dl", "readout",
      h("div", "", h("dt", "", "Lowest quote"), h("dd", "", usd(low), m.cheapest ? chip(m.cheapest.grade, "The lowest quote, " + m.cheapest.id + ", is from a grade " + m.cheapest.grade + " seller") : null)),
      m.best ? h("div", "is-best", h("dt", "", narrow ? "Best all-in" : "Best eligible, all-in"), h("dd", "", usd(m.best.risk_adjusted, 3), chip(m.best.grade, "The best eligible quote, " + m.best.id + ", is from a grade " + m.best.grade + " seller"))) : h("div", "", h("dt", "", "Best eligible"), h("dd", "muted", "None")),
      m.best ? h("div", "", h("dt", "", "Basis"), h("dd", "", pct(m.basis, 1, true))) : null);
    replace("desk-trend", readout,
      charts.lineChart({ points: times.length, series: lines, gap: hasBest ? ["best", "cheapest"] : null, format: (v) => "$" + v.toFixed(2), markers: scenarioMarkers(m.model), xLabel: (i) => clock(times[i]), width, height: narrow ? 220 : 270, marginRight: narrow ? 52 : 134, endLabels: narrow ? "value" : "full", yTickCount: 5, xTickCount: narrow ? 2 : 3,
        hover: (i) => clock(times[i]) + " · " + lines.map((l) => l.name + " " + at(l.values, i)).join(" · "),
        description: m.model + " price history. " + (m.best ? "The best eligible all-in cost is " + usd(m.best.risk_adjusted, 3) + " against a lowest quote of " + usd(low) + "." : "No eligible seller for this model.") }),
      narrow ? charts.legend(lines.map((l) => ({ label: l.name, className: "ln-swatch " + l.className }))) : null,
      h("p", "figure-caption", m.best ? "The shaded band is the basis: " + pct(m.basis, 1, true) + " now" + (Number.isFinite(prior) ? ", " + pct(prior, 1, true) + " a day ago." : ".") : "No seller for this model clears the eligibility bar, so there is no all-in price to compare."));
  }

  /* Supply by seller grade: each model's GPUs as a share bar split by grade; totals sit on the right. */
  function renderSupply() {
    const data = state.data; const width = fit("desk-supply", 420); const narrow = width < 400; const mix = data.grade_mix; const all = GRADES.reduce((sum, g) => sum + mix[g].gpus, 0) || 1;
    const share = (grades) => grades.reduce((sum, g) => sum + mix[g].gpus, 0) / all;
    replace("desk-supply",
      charts.stackedBars({ rows: data.models.map((m) => ({ label: m.model, parts: GRADES.map((g) => ({ value: data.supply[m.model][g], className: gradeClass(g), title: m.model + " · grade " + g + " · " + int(data.supply[m.model][g]) + " GPUs" })) })), normalize: true, width, labelWidth: narrow ? 68 : 74, valueWidth: 46, rowHeight: 38, barHeight: 22, inside: (part, fraction) => (fraction >= 0.1 ? Math.round(fraction * 100) + "%" : ""), valueText: (row, total) => compact(total),
        description: "Share of GPUs on offer by seller grade for each model. Grade A and B sellers hold " + pct(share(["A", "B"]), 0) + " of all GPUs; " + data.models.filter((m) => !data.supply[m.model].A && !data.supply[m.model].B).map((m) => m.model).join(", ") + " have none from grade A or B." }),
      legendGrades(),
      h("p", "figure-caption", "Grade A and B sellers hold " + pct(share(["A", "B"]), 0) + " of the GPUs on offer; grade D sellers hold " + pct(share(["D"]), 0) + "."));
  }
  /* Quote completeness: live quotes by count of missing key terms, stacked by grade; more than three missing is ineligible. */
  function renderCompleteness() {
    const data = state.data; const width = fit("desk-completeness", 420); const blocked = data.completeness.filter((c) => c.missing >= 4).reduce((sum, c) => sum + c.quotes, 0); const total = data.kpis.live_quotes || 1;
    replace("desk-completeness",
      charts.columns({ cols: data.completeness.map((c) => ({ label: c.label.replace("6 or more", "6+"), parts: GRADES.map((g) => ({ value: c.by_grade[g], className: gradeClass(g), title: c.by_grade[g] + " grade " + g + " quotes missing " + c.label + " terms" })) })), width, height: 236, totals: true, divider: 3, dividerLabel: "Ineligible beyond three",
        description: "Live quotes by number of key terms missing, split by seller grade. " + int(blocked) + " of " + int(total) + " quotes miss more than three terms and are ineligible." }),
      legendGrades(),
      h("p", "figure-caption", int(blocked) + " of " + int(total) + " live quotes (" + pct(blocked / total, 0) + ") leave four or more key terms blank and cannot be ranked."));
  }
  /* Median premium over each model's lowest quote, by seller grade: what the quote says against what it costs all-in. */
  function gradeCosts() {
    const data = state.data; const low = new Map(data.models.map((m) => [m.model, lowestPrice(m)]));
    return GRADES.map((grade) => {
      const quotes = data.quotes.filter((q) => q.grade === grade && q.risk_adjusted !== null && low.get(q.gpu));
      return { grade, count: quotes.length, quoted: median(quotes.map((q) => Number(q.price) / low.get(q.gpu) - 1)), allin: median(quotes.map((q) => q.risk_adjusted / low.get(q.gpu) - 1)) };
    });
  }
  function renderGrades() {
    const rows = gradeCosts(); const width = fit("desk-grades", 420); const by = (g) => rows.find((r) => r.grade === g); const a = by("A"); const d = by("D");
    const gap = a.quoted !== null && d.quoted !== null && a.allin !== null && d.allin !== null ? [Math.round((a.quoted - d.quoted) * 100), Math.round((a.allin - d.allin) * 100)] : null;
    replace("desk-grades",
      charts.groupedColumns({ cols: rows.map((r) => ({ label: r.grade, sub: r.count + " quotes", bars: [
        { value: r.quoted, text: r.quoted === null ? "" : pct(r.quoted, 0, true), className: gradeClass(r.grade) + " tint", title: "Grade " + r.grade + " · median quoted price " + (r.quoted === null ? "none" : pct(r.quoted, 1, true)) + " over the lowest quote, " + r.count + " quotes" },
        { value: r.allin, text: r.allin === null ? "" : pct(r.allin, 0, true), className: gradeClass(r.grade), title: "Grade " + r.grade + " · median all-in cost " + (r.allin === null ? "none" : pct(r.allin, 1, true)) + " over the lowest quote, " + r.count + " quotes" }] })), width, height: 236, format: (v) => pct(v, 0, true),
        description: "Median premium over each model's lowest quote by seller grade, quoted price against all-in cost. " + rows.filter((r) => r.quoted !== null).map((r) => "Grade " + r.grade + " " + pct(r.quoted, 0, true) + " quoted, " + pct(r.allin, 0, true) + " all-in").join("; ") + "." }),
      charts.legend([{ label: "Quoted price", className: "part-price tint" }, { label: "All-in cost", className: "part-price" }]),
      h("p", "figure-caption", gap ? "Grade D looks " + gap[0] + " points cheaper than grade A on quoted price. All-in, the gap is " + gap[1] + (gap[1] === 1 ? " point." : " points.") : "Colour shows the seller's grade; the lighter bar is the quoted price."));
  }
  function renderExpiry() {
    const data = state.data; const total = data.expiry.reduce((sum, e) => sum + e.quotes, 0) || 1;
    replace("desk-expiry", charts.bars({ rows: data.expiry.map((e, i) => ({ label: e.label, value: e.quotes, text: e.quotes + " · " + pct(e.quotes / total, 0), className: i < 2 ? "part-warn" : "part-price", title: e.quotes + " quotes" })), width: fit("desk-expiry", 420), labelWidth: 100, valueWidth: 64, description: "Live quotes by time to expiry. " + data.expiry[0].quotes + " expire within seven days." }));
  }
  function renderDesk() {
    if (!live()) { replace("desk-kpis", empty(state.error || "Opening the simulated book…")); return; }
    const data = state.data;
    text("desk-lede", int(data.kpis.live_quotes) + " live quotes from " + data.kpis.providers_quoting + " providers, scored and priced all-in. Market time " + clock(data.meta.time) + " UTC, simulated.");
    renderKpis(); renderBasis(); modelTabs("desk-model-tabs", false); renderTrend();
    renderSupply(); renderCompleteness(); renderGrades(); renderProviders(); renderActivity(); renderExpiry();
  }
  function renderProviders() {
    const data = state.data; const rows = data.providers.slice().sort((a, b) => b.gpus - a.gpus); const shown = state.showAll ? rows : rows.slice(0, 10);
    const body = h("tbody");
    shown.forEach((p) => {
      const recent = p.changed_tick !== null && data.meta.tick - p.changed_tick <= 6;
      const link = h("button", "row-link", p.name); link.type = "button";
      link.addEventListener("click", () => { const first = data.quotes.find((q) => q.provider_id === p.id); if (first) { state.model = first.gpu; state.selected = first.id; showView("quotes"); } });
      body.append(h("tr", recent ? "recent" : "", h("th", "", link), h("td", "", chip(p.grade), h("span", "kind", p.kind === "Reseller" ? "Broker" : "Owner")), h("td", "num", p.score.toFixed(0)), h("td", "num", String(p.quotes)), h("td", "num", int(p.gpus)), h("td", "num", p.missing_average === null ? "—" : p.missing_average.toFixed(1)), h("td", "num", p.eligible_share === null ? "—" : pct(p.eligible_share, 0))));
    });
    const table = h("table", "data-table", h("caption", "sr-only", "Providers by GPUs on offer"), h("thead", "", h("tr", "", ["Provider", "Grade", "Score", "Quotes", "GPUs", "Missing terms", "Eligible"].map((label, i) => { const th = h("th", i > 1 ? "num" : "", label); th.scope = "col"; return th; }))), body);
    const toggle = h("button", "link-button", state.showAll ? "Show top 10" : "Show all " + rows.length); toggle.type = "button"; toggle.addEventListener("click", () => { state.showAll = !state.showAll; renderProviders(); });
    replace("desk-providers", h("div", "table-wrap", table), toggle);
  }
  function renderActivity() {
    const list = h("ol", "activity"); state.data.alerts.slice(0, 9).forEach((a) => list.append(h("li", "event " + a.level + (state.flash.has(a.n) ? " flash" : ""), h("time", "", clock(a.time, true)), h("span", "", a.text))));
    replace("desk-activity", list);
  }

  /* Cost per GPU-hour as stacked bars on one shared zero-based scale: quoted price, financing on the down payment,
     expected loss if the seller fails. Each bar carries its all-in total, and every component prints its own value. */
  function costBreakdown(entries, named = true) {
    const parts = (quote) => [{ name: "Quoted price", value: Number(quote.price), className: "part-price", places: 2 }, { name: "Financing", value: quote.financing || 0, className: "part-financing", places: 3 }, { name: "Expected loss", value: quote.exposure || 0, className: "part-exposure", places: 3 }];
    const totals = entries.map(({ quote }) => (quote.risk_adjusted === null || quote.risk_adjusted === undefined ? parts(quote).reduce((sum, p) => sum + p.value, 0) : quote.risk_adjusted)); const max = Math.max(...totals);
    return h("div", "cost-compare", entries.map(({ label, tag, quote }, i) => {
      const segments = parts(quote);
      const bar = charts.stackedBars({ rows: [{ label: "", parts: segments.map((p) => ({ value: p.value, className: p.className, title: p.name + " " + usd(p.value, p.places) })) }], max, labelWidth: 0, valueWidth: 0, width: 440, rowHeight: 22, barHeight: 16, valueText: () => "",
        description: (label || "Quote") + " costs " + usd(totals[i], 3) + " per GPU-hour all-in: " + segments.map((p) => p.name.toLowerCase() + " " + usd(p.value, p.places)).join(", ") });
      return h("div", "cost-row", h("div", "cost-head", named ? h("span", "cost-name", chip(quote.grade), label, tag ? h("small", "", tag) : null) : null, h("strong", "cost-total", usd(totals[i], 3), h("small", "", "all-in"))), bar,
        h("ul", "cost-parts", segments.map((p) => h("li", "", h("span", "swatch " + p.className, ""), p.name, h("strong", "", usd(p.value, p.places))))));
    }));
  }

  /* ---- Quotes ---- */
  function renderQuotes() {
    if (!live()) { replace("quotes-callout", empty(state.error || "Opening the simulated book…")); return; }
    const data = state.data; modelTabs("quotes-models");
    const m = data.models.find((entry) => entry.model === state.model) || data.models[0]; state.model = m.model;
    const quotes = data.quotes.filter((q) => q.gpu === m.model);
    const cheapest = m.cheapest && quotes.find((q) => q.id === m.cheapest.id); const best = m.best && quotes.find((q) => q.id === m.best.id);
    text("quotes-lede", m.model + ": " + m.quotes + " quotes, " + m.eligible + " eligible. Ranked by what each costs all-in, not by headline price.");
    replace("quotes-callout", best && cheapest ? [
      h("div", "callout-text", h("p", "", h("strong", "", cheapest.id + " is the lowest quote at " + usd(cheapest.price) + ".")), h("p", "muted", cheapest.eligible ? "Grade " + cheapest.grade + ", " + cheapest.missing.length + " of 10 key terms missing." : "Grade " + cheapest.grade + " seller, not eligible: " + cheapest.reasons.join("; ") + "."), h("p", "", h("strong", "", best.id + " is the best eligible buy at " + usd(best.risk_adjusted, 3) + " all-in.")), h("p", "muted", "Grade " + best.grade + ", " + best.provider + ", " + pct(m.basis, 1, true) + " over the lowest quote.")),
      h("div", "callout-chart", h("h3", "cost-title", "All-in cost per GPU-hour"), costBreakdown([{ label: cheapest.id, tag: "Lowest quote", quote: cheapest }, { label: best.id, tag: "Best eligible", quote: best }]))]
      : [h("div", "callout-text", h("p", "", h("strong", "", m.cheapest ? "Lowest quote " + m.cheapest.id + " at " + usd(m.cheapest.price) + "." : "No quotes.")), h("p", "muted", "No seller for " + m.model + " clears the eligibility bar, so there is no all-in price to rank."))]);
    const sorted = quotes.slice().sort((a, b) => state.sort === "price" ? Number(a.price) - Number(b.price) || a.id.localeCompare(b.id) : (a.risk_rank ?? 1e9) - (b.risk_rank ?? 1e9) || Number(a.price) - Number(b.price));
    const low = cheapest ? Number(cheapest.price) : null; const body = h("tbody");
    sorted.forEach((q) => {
      const fresh = state.fresh.has(q.id); const selected = q.id === state.selected;
      const link = h("button", "row-link", q.id); link.type = "button"; link.addEventListener("click", () => { state.selected = q.id; renderQuotes(); });
      const standing = q.eligible ? h("span", "standing ok", "Eligible") : h("span", "standing no", q.reasons[0] || "Ineligible");
      const row = h("tr", [selected ? "selected" : "", fresh ? "flash" : "", q.id === (cheapest && cheapest.id) ? "is-lowest" : "", q.id === (best && best.id) ? "is-best" : ""].filter(Boolean).join(" "),
        h("td", "num", q.risk_rank === null ? "—" : String(q.risk_rank)), h("th", "", link, q.workbook ? h("span", "tag", "workbook") : null), h("td", "", chip(q.grade), h("span", "kind", q.provider)),
        h("td", "num", usd(q.price)), h("td", "num strong", q.risk_adjusted === null ? "—" : usd(q.risk_adjusted, 3)), h("td", "num", low && q.risk_adjusted !== null ? pct(q.risk_adjusted / low - 1, 1, true) : "—"),
        h("td", "num", q.months === null ? "—" : q.months + " mo"), h("td", "num", q.down_payment === null ? "—" : pct(q.down_payment, 0)), h("td", "num", q.missing.length + "/10"), h("td", "", standing));
      body.append(row);
    });
    const head = ["Rank", "Quote", "Seller", "Quoted", "All-in", "vs lowest", "Term", "Down", "Missing", "Standing"];
    replace("quotes-table", h("caption", "sr-only", "Live " + m.model + " quotes ranked by all-in cost per GPU-hour"), h("thead", "", h("tr", "", head.map((label, i) => { const th = h("th", i === 1 || i === 2 || i === 9 ? "" : "num", label); th.scope = "col"; return th; }))), body);
    ["allin", "price"].forEach((key) => byId("sort-" + key).setAttribute("aria-pressed", String(state.sort === key)));
    renderDetail(quotes.find((q) => q.id === state.selected) || best || cheapest || null);
  }
  function renderDetail(q) {
    if (!q) return replace("quotes-detail", empty("Select a quote to see its scorecard and cost."));
    const data = state.data; const provider = data.providers.find((p) => p.id === q.provider_id);
    const card = h("table", "scorecard", h("caption", "sr-only", "Scorecard for " + provider.name), h("tbody", "", Object.entries(data.assumptions.weights).map(([key, weight]) => {
      const tier = provider.tiers[key]; const pips = h("span", "pips", [1, 2, 3].map((n) => h("i", n >= tier ? "pip on" : "pip"))); pips.setAttribute("role", "img"); pips.setAttribute("aria-label", "Tier " + tier + " of 3");
      return h("tr", "", h("th", "", CATEGORIES[key]), h("td", "num muted", pct(weight, 0)), h("td", "", pips), h("td", "num", "Tier " + tier));
    })));
    const facts = [["Contract value", q.contract_value === null ? "—" : "$" + compact(q.contract_value)], ["GPUs", int(q.gpus)], ["Term", q.months === null ? "—" : q.months + " months"], ["Down payment", q.down_payment === null ? "—" : pct(q.down_payment, 0)], ["Payment terms", q.payment_days === null ? "—" : "net " + q.payment_days], ["Location", q.location ? q.location + (q.country ? ", " + q.country : "") : "—"], ["Expires", q.days_to_expiry === null ? "No expiry" : q.days_to_expiry + " days"], ["Discount to reference", q.discount_to_reference === null ? "No index" : pct(q.discount_to_reference, 1)]];
    const grid = h("dl", "facts", facts.map(([k, v]) => [h("dt", "", k), h("dd", "", v)]));
    const prefill = h("button", "primary-button", "Price this quote"); prefill.type = "button"; prefill.addEventListener("click", () => host.priceQuote ? host.priceQuote(q) : showView("pricing"));
    replace("quotes-detail", h("div", "detail-head", h("div", "", h("h2", "", q.id), h("p", "muted", q.provider)), h("div", "detail-grade", chip(q.grade), h("strong", "", provider.score.toFixed(0)), h("small", "", "quality score"))),
      h("h3", "", "All-in cost per GPU-hour"), q.risk_adjusted === null ? empty("Term not stated, so no all-in cost can be computed.") : costBreakdown([{ label: q.id, quote: q }], false),
      q.eligible ? h("p", "standing ok", "Eligible: grade " + q.grade + ", " + q.missing.length + " of 10 key terms missing.") : h("p", "standing no", "Not eligible: " + q.reasons.join("; ") + "."),
      h("h3", "", "Seller scorecard"), card, h("h3", "", "Terms"), grid,
      q.missing.length ? h("p", "muted", "Missing: " + q.missing.map((f) => FIELD_NAMES[f] || f).join(", ") + ".") : null, q.flags.length ? h("p", "muted", q.flags.join(" ")) : null, prefill);
  }

  /* ---- orchestration ---- */
  function render() {
    if (state.view === "brief") renderBrief(); else if (state.view === "desk") renderDesk(); else if (state.view === "quotes") renderQuotes();
    state.flash = new Set(); state.fresh = new Set();  // a change is highlighted once, then left alone
  }
  /* Motion. The Brief plays its entrance once, on first load; after the person has left it, coming back is a plain fade.
     Sections below the fold fade in as they scroll into view. Without IntersectionObserver, or when motion is reduced,
     nothing is hidden and the page simply shows. */
  const REVEAL = ["brief-problem-head", "brief-problem-1", "brief-problem-2", "brief-problem-3", "brief-how-head", "brief-steps", "brief-basis", "brief-close"];
  function armReveal() {
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches === true;
    if (reduced || typeof window.IntersectionObserver !== "function") return;
    const watcher = new window.IntersectionObserver((entries) => entries.forEach((entry) => {
      if (entry.isIntersecting) { entry.target.classList.add("rv-in"); watcher.unobserve(entry.target); }
    }), { threshold: 0.12, rootMargin: "0px 0px -6% 0px" });
    byId("brief-view").classList.add("rv-on"); REVEAL.forEach((id) => watcher.observe(byId(id)));
  }
  host.onView((name) => { if (name !== "brief") byId("brief-view").classList.add("bf-entered"); });
  host.onView((name) => { state.view = name; if (["brief", "desk", "quotes"].includes(name)) { paintControls(); render(); poll(true); } });
  host.onSession((connected) => {
    if (!connected) { state.data = null; state.tag = ""; state.lastAlert = null; state.kpi.clear(); state.error = ""; render(); return; }
    paintControls(); poll(true);
  });
  ["allin", "price"].forEach((key) => byId("sort-" + key).addEventListener("click", () => { state.sort = key; renderQuotes(); }));
  ["lp-open", "brief-open-desk", "brief-open-desk-end"].forEach((id) => byId(id).addEventListener("click", () => showView("desk"))); byId("brief-open-quotes").addEventListener("click", () => showView("quotes"));
  function goTo(sectionId, titleId) {
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches === true;
    byId(sectionId).scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "start" }); byId(titleId).focus({ preventScroll: true });
  }
  [["brief-see-problem", "brief-problem", "brief-problem-title"], ["lp-go-problem", "brief-problem", "brief-problem-title"], ["lp-go-how", "brief-how", "brief-how-title"]]
    .forEach(([button, section, title]) => byId(button).addEventListener("click", () => goTo(section, title)));
  window.addEventListener?.("resize", () => { if (state.view !== "brief" || !live()) return; clearTimeout(briefResize); briefResize = setTimeout(renderBrief, 150); });
  let deskResize = null;
  window.addEventListener?.("resize", () => { if (!["desk", "quotes"].includes(state.view) || !live()) return; clearTimeout(deskResize); deskResize = setTimeout(render, 150); });
  setInterval(() => poll(false), POLL_MS);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(true); });
  armReveal(); paintControls(); render();
})();
