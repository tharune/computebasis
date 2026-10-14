/* The landing view: the Brief. A one-page argument, drawn from the live simulated book. */
(() => {
  "use strict";
  const D = window.ComputeDemo; if (!D) return;
  const { charts, state, h, int, usd, pct, compact, gradeClass, replace, empty, live, legendGrades, lowestPrice, FIELD_NAMES, CATEGORIES, byId } = D;
  const showView = D.host.showView;

  /* ---- Brief ---- */
  /* The landing view. Its charts come from one small local primitive, briefBars, so the page owns its own
     type and spacing; colour still arrives only through CSS classes (--gc), keeping both themes and the CSP intact. */
  const SVG_NS = "http://www.w3.org/2000/svg";
  const r2 = (value) => Math.round(value * 100) / 100;
  let briefDrawn = false;
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
      replace("brief-fact-cost", statLine(pct(allin / price - 1, 0, true), ["Quote " + quote.ref + ", the lowest " + example.entry.model + " offer, asks " + usd(price) + " ", h("span", "bf-nowrap", "per GPU-hour"), ". All-in it costs " + usd(allin) + "."]));
      const part = (name, value, className) => h("div", "", h("dt", "", h("span", "swatch " + className), name), h("dd", "", usd(value, value < 1 ? 3 : 2)));
      replace("brief-anatomy",
        briefBars({ rows: [{ label: "Quoted", parts: [{ value: price, className: "part-price", title: "Quoted price " + usd(price) }], text: usd(price) },
          { label: "All-in", parts: [{ value: price, className: "part-price", title: "Quoted price " + usd(price) }, { value: financing, className: "part-financing", title: "Financing on the down payment " + usd(financing, 3) }, { value: exposure, className: "part-exposure", title: "Expected loss if the seller fails " + usd(exposure, 3) }], text: usd(allin) }],
        max: allin, width: briefWidth(520), labelWidth: 64, valueWidth: 64, rowHeight: 48, bar: 18, grow, description: "Quote " + quote.ref + " per GPU-hour: quoted " + usd(price) + ", plus financing " + usd(financing, 3) + ", plus expected loss " + usd(exposure, 3) + ", is " + usd(allin) + " all-in." }),
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
  D.host.onView((name) => { if (name !== "brief") byId("brief-view").classList.add("bf-entered"); });
  ["lp-open", "brief-open-desk", "brief-open-desk-end"].forEach((id) => byId(id).addEventListener("click", () => showView("desk"))); byId("brief-open-quotes").addEventListener("click", () => showView("quotes"));
  function goTo(sectionId, titleId) {
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches === true;
    byId(sectionId).scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "start" }); byId(titleId).focus({ preventScroll: true });
  }
  [["brief-see-problem", "brief-problem", "brief-problem-title"], ["lp-go-problem", "brief-problem", "brief-problem-title"], ["lp-go-how", "brief-how", "brief-how-title"]]
    .forEach(([button, section, title]) => byId(button).addEventListener("click", () => goTo(section, title)));
  armReveal();
  D.register("brief", { render: renderBrief, resize: true });
})();
