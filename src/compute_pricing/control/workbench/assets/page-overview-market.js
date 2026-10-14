/* Overview: the state of the simulated market. Basis by model, price history for one model, eligible supply by grade, why quotes are
   held back, seller health and the event feed. Every sentence is built from the book's own numbers; a figure the book does not have
   is left out or shown as "—", never as zero. */
(() => {
  "use strict";
  const D = window.ComputeDemo; const C = window.OverviewCharts; if (!D || !C) return;
  const { state, h, int, usd, pct, clock, chip, replace, empty, fit, modelTabs, text, lowestPrice, GRADES, scenarioSeen, scenarioReady } = D;
  const reasonText = (code) => (window.BookAdapter && window.BookAdapter.reasonText ? window.BookAdapter.reasonText(code) : String(code));
  const plural = (n, one, many) => n + " " + (n === 1 ? one : many);
  const join = (items) => (items.length < 3 ? items.join(" and ") : items.slice(0, -1).join(", ") + " and " + items[items.length - 1]);
  const labelled = (row, names) => { Array.from(row.children).forEach((cell, i) => { if (names[i]) cell.setAttribute("data-label", names[i]); }); return row; };
  const th = (label, className = "") => { const cell = h("th", className, label); cell.scope = "col"; return cell; };
  const GRADE_CLASS = { A: "og-a", B: "og-b", C: "og-c", D: "og-d", U: "og-u" };

  /* ---- Basis by GPU model ---- */
  function renderBasis(ctx) {
    const data = state.data; const width = fit("desk-basis", 640); const narrow = width < 520;
    const rows = data.models.map((entry) => {
      const low = lowestPrice(entry); const cheap = entry.cheapest; const best = entry.best;
      const why = cheap && !cheap.eligible && cheap.ineligible_reasons && cheap.ineligible_reasons.length ? "; not eligible: " + cheap.ineligible_reasons.map(reasonText).join(", ").toLowerCase() : "";
      return {
        label: entry.model, sub: entry.eligible + (narrow ? "/" : " of ") + entry.quotes + " eligible",
        bars: [
          low === null ? { value: null, absent: "No quote" } : { value: low, text: usd(low), className: "ov-s-low", grade: cheap ? cheap.grade : null, title: "Lowest quote" + (cheap ? " " + cheap.ref + ", " + cheap.provider + ", grade " + cheap.grade : "") + ", " + usd(low) + " as quoted" + why },
          best ? { value: best.risk_adjusted, text: usd(best.risk_adjusted, 3), className: "ov-s-best", grade: best.grade, title: "Best eligible " + best.ref + ", " + best.provider + ", grade " + best.grade + ", " + usd(best.risk_adjusted, 3) + " all-in, " + usd(best.price) + " quoted" } : { value: null, absent: "No eligible seller" },
        ],
        trail: best && entry.basis !== null ? pct(entry.basis, 1, true) : "—",
      };
    });
    const widest = data.models.filter((m) => m.basis !== null && m.cheapest && m.best).sort((a, b) => b.basis - a.basis)[0]; const none = data.models.filter((m) => !m.best).map((m) => m.model);
    const blocked = data.kpis.cheapest_is_ineligible; const total = data.models.length;
    const caption = (widest ? widest.model + " has the widest basis, " + pct(widest.basis, 1, true) + ". " : "") + (Number.isFinite(blocked) && blocked > 0 ? "The lowest quote is itself ineligible for " + blocked + " of " + total + " models. " : "") + (none.length ? join(none) + (none.length > 1 ? " have" : " has") + " no eligible seller." : "");
    const description = "Lowest quote against best eligible all-in cost, dollars per GPU-hour, by GPU model. " + data.models.map((m) => m.model + " " + (m.cheapest ? usd(lowestPrice(m)) : "no quote") + (m.best ? " against " + usd(m.best.risk_adjusted, 3) + ", basis " + pct(m.basis, 1, true) : ", no eligible seller")).join("; ") + ".";
    replace("desk-basis",
      C.pairedBars({ rows, width, enter: ctx.enter("basis"), format: (v) => "$" + (Number.isInteger(v) ? v : v.toFixed(2)), labelWidth: narrow ? 78 : 96, trailWidth: narrow ? 50 : 58, valueRoom: narrow ? 78 : 88, tickCount: narrow ? 4 : 6, description }),
      C.legend([{ label: "Lowest quote, as quoted", className: "ov-s-low" }, { label: "Best eligible, all-in", className: "ov-s-best" }]),
      h("p", "ov-caption", caption.trim()),
      C.twin("Basis by GPU model, dollars per GPU-hour", ["Model", "Lowest quote", "Best eligible all-in", "Basis", "Eligible quotes", "Quotes"], data.models.map((m) => [m.model, m.cheapest ? usd(lowestPrice(m)) : "none", m.best ? usd(m.best.risk_adjusted, 3) : "none", m.best && m.basis !== null ? pct(m.basis, 1, true) : "none", m.eligible, m.quotes])));
  }

  /* ---- Price history for one model ---- */
  function scenarioMarkers() {
    const data = state.data; scenarioReady();
    return [...scenarioSeen.values()].map((a) => ({ index: data.series.ticks.indexOf(a.tick), label: a.scenario_label || "Scenario", title: a.text })).filter((marker) => marker.index >= 0);
  }
  const node = (value) => (typeof value === "object" ? value : document.createTextNode(String(value)));
  function renderTrend(ctx) {
    const data = state.data; const m = data.models.find((entry) => entry.model === state.model) || data.models[0]; if (!m) { replace("desk-trend", empty("No GPU models in the book.")); return; }
    modelTabs("desk-model-tabs", false); text("desk-trend-title", m.model + " price history");
    const s = data.series.models[m.model] || { cheapest: [], best: [], median: [], basis: [] }; const times = data.series.times || []; const hasBest = s.best.some((v) => v !== null && v !== undefined);
    const width = fit("desk-trend", 560); const narrow = width < 460; const low = lowestPrice(m);
    const lines = [{ key: "cheapest", name: "Lowest quote", values: s.cheapest, className: "ov-s-low" }, hasBest ? { key: "best", name: "Best eligible, all-in", values: s.best, className: "ov-s-best" } : { key: "median", name: "Median quote", values: s.median, className: "ov-s-med" }];
    const at = (values, i) => (values[i] === null || values[i] === undefined ? "none" : usd(values[i], 2));
    const history = times.length >= 2;
    /* The readout above the chart shows the latest reading, or the reading under the pointer. */
    const stamp = h("span", "ov-readout-time"); const cells = {};
    const item = (key, name, className) => { const value = h("dd", ""); cells[key] = value; return h("div", className || "", h("dt", "", name), value); };
    const readout = h("dl", "ov-readout", item("low", "Lowest quote"), item("best", narrow ? "Best all-in" : "Best eligible, all-in", "is-best"), item("basis", "Basis"), stamp);
    const fill = (index) => {
      const hovering = Number.isInteger(index); readout.className = "ov-readout" + (hovering ? " is-hover" : "");
      const lowValue = hovering ? s.cheapest[index] : low; const bestValue = hovering ? s.best[index] : m.best ? m.best.risk_adjusted : null; const basisValue = hovering ? s.basis[index] : m.best ? m.basis : null;
      const grade = (quote, label) => (!hovering && quote ? chip(quote.grade, label + " " + quote.ref + " is from a grade " + quote.grade + " seller") : null);
      cells.low.replaceChildren(...[lowValue === null || lowValue === undefined ? "—" : usd(lowValue), grade(m.cheapest, "The lowest quote,")].filter(Boolean).map(node));
      cells.best.replaceChildren(...[bestValue === null || bestValue === undefined ? "None" : usd(bestValue, 3), grade(m.best, "The best eligible quote,")].filter(Boolean).map(node));
      cells.basis.replaceChildren(node(basisValue === null || basisValue === undefined ? "—" : pct(basisValue, 1, true)));
      stamp.textContent = hovering ? clock(times[index], true) + " UTC" : history ? "Latest, " + clock(times[times.length - 1], true) + " UTC" : "";
    };
    fill(null);
    const chartDescription = m.model + " price history, dollars per GPU-hour. " + (m.best ? "The best eligible all-in cost is " + usd(m.best.risk_adjusted, 3) + " against a lowest quote of " + usd(low) + "." : "No eligible seller for this model.");
    let body; let caption;
    if (history) {
      const markers = scenarioMarkers();
      const chart = C.historyChart({ times, series: lines, gap: hasBest ? ["best", "cheapest"] : null, markers, width, height: narrow ? 220 : 250, enter: ctx.enter("history"), xLabel: (i) => clock(times[i], true), yTicks: 4, xTicks: narrow ? 2 : 3, description: chartDescription,
        hoverText: (i) => clock(times[i], true) + " UTC, " + lines.map((l) => l.name + " " + at(l.values, i)).join(", "), onHover: fill });
      body = [chart, C.legend([...lines.map((l) => ({ label: l.name, className: "ov-key " + l.className })), ...(hasBest ? [{ label: "Basis", className: "ov-band" }] : [])])];
      const back = Math.min(48, times.length - 1); const minutes = Math.round((data.series.ticks[times.length - 1] - data.series.ticks[times.length - 1 - back]) * (data.meta.step_minutes || 1)); const prior = s.basis[times.length - 1 - back];
      caption = m.best && Number.isFinite(prior) && minutes >= 1 ? "The shaded band is the basis: " + pct(m.basis, 1, true) + " now, " + pct(prior, 1, true) + " " + minutes + (minutes === 1 ? " minute" : " minutes") + " ago." + (markers.length ? " Dashed flags mark scenarios." : "") : m.best ? "The shaded band is the basis." : "No seller for this model clears the eligibility bar, so there is no all-in line.";
    } else {
      const marks = [m.cheapest && low !== null ? { value: low, text: "Lowest quote " + usd(low), className: "ov-s-low", title: "Lowest quote " + usd(low) } : null, m.best ? { value: m.best.risk_adjusted, text: "Best eligible, all-in " + usd(m.best.risk_adjusted, 3), className: "ov-s-best", title: "Best eligible all-in " + usd(m.best.risk_adjusted, 3) } : null].filter(Boolean);
      body = [Number.isFinite(m.low) && Number.isFinite(m.high) && marks.length ? C.rangeStrip({ low: m.low, median: m.median, high: m.high, marks, width, description: m.model + " quotes now, dollars per GPU-hour: lowest " + usd(m.low) + ", median " + (Number.isFinite(m.median) ? usd(m.median) : "none") + ", highest " + usd(m.high) + "." }) : empty("No quotes for this model yet.")];
      caption = "Collecting history: the book has " + plural(times.length, "reading", "readings") + ". " + (data.meta.paused ? "The market clock is paused, so no history is being added. Resume it to start the line." : "The line starts after the second reading, one per simulated minute (every " + (data.meta.tick_seconds || 3) + " seconds). Run a scenario to see it move.") + " Until then, the strip shows where this model's quotes sit now.";
    }
    replace("desk-trend", readout, body, h("p", "ov-caption", caption),
      C.twin(m.model + " price history, dollars per GPU-hour", ["Time (UTC)", "Lowest quote", "Best eligible all-in", "Basis"], times.map((t, i) => [clock(t, true), at(s.cheapest, i), s.best[i] === null || s.best[i] === undefined ? "none" : usd(s.best[i], 3), s.basis[i] === null || s.basis[i] === undefined ? "none" : pct(s.basis[i], 1, true)])));
  }

  /* ---- Eligible supply by grade: each model's eligible GPUs, split by seller grade ---- */
  function renderSupply(ctx) {
    const data = state.data; const width = fit("desk-supply", 560);
    const eligible = new Map(data.models.map((m) => [m.model, { A: 0, B: 0, C: 0, D: 0, U: 0 }]));
    data.quotes.forEach((q) => { const row = eligible.get(q.gpu); if (row && q.eligible && Number.isFinite(q.gpus)) row[GRADES.includes(q.grade) ? q.grade : "U"] += q.gpus; });
    const offered = (model) => Object.values(data.supply[model] || {}).reduce((sum, v) => sum + (Number.isFinite(v) ? v : 0), 0);
    const sum = (row) => row.A + row.B + row.C + row.D + row.U; const totalEligible = [...eligible.values()].reduce((n, row) => n + sum(row), 0); const totalOffered = data.models.reduce((n, m) => n + offered(m.model), 0);
    const withU = [...eligible.values()].some((row) => row.U > 0); const letters = withU ? [...GRADES, "U"] : GRADES;
    const rows = data.models.map((m) => { const row = eligible.get(m.model); return { label: m.model, none: "None eligible", parts: letters.map((g) => ({ value: row[g], className: GRADE_CLASS[g], title: m.model + ", " + (g === "U" ? "sellers not rated" : "grade " + g) + ": " + int(row[g]) + " eligible GPUs" })), trail: sum(row) > 0 ? int(sum(row)) + " of " + int(offered(m.model)) : "0 of " + int(offered(m.model)) }; });
    const gradeShare = (set) => (totalEligible ? set.reduce((n, g) => n + [...eligible.values()].reduce((k, row) => k + row[g], 0), 0) / totalEligible : null);
    const ab = gradeShare(["A", "B"]); const leader = data.models.slice().sort((a, b) => sum(eligible.get(b.model)) - sum(eligible.get(a.model)))[0];
    const caption = totalOffered ? int(totalEligible) + " of " + int(totalOffered) + " GPUs on offer (" + pct(totalEligible / totalOffered, 0) + ") are in eligible quotes." + (ab !== null && leader ? " Grade A and B sellers hold " + pct(ab, 0) + " of them. " + leader.model + " has the most eligible GPUs, " + int(sum(eligible.get(leader.model))) + "." : "") : "No GPUs are on offer.";
    const parts = (g) => (g === "U" ? "Sellers not rated" : "Grade " + g);
    replace("desk-supply",
      C.gradeStack({ rows, width, enter: ctx.enter("supply"), description: "Eligible GPUs by seller grade for each model, as a share of that model's eligible GPUs. " + rows.map((r) => r.label + " " + r.trail).join("; ") + "." }),
      C.legend(letters.map((g) => ({ label: parts(g), className: GRADE_CLASS[g] }))), h("p", "ov-caption", caption),
      C.twin("Eligible GPUs by model and seller grade", ["Model", ...letters.map(parts), "Eligible GPUs", "GPUs on offer"], data.models.map((m) => [m.model, ...letters.map((g) => int(eligible.get(m.model)[g])), int(sum(eligible.get(m.model))), int(offered(m.model))])));
  }

  /* ---- Why quotes are held back ---- */
  const START = "contract_start_precedes_as_of";
  function renderReasons(ctx) {
    const data = state.data; const held = data.quotes.filter((q) => !q.eligible); const width = fit("desk-reasons", 560);
    if (!held.length) { replace("desk-reasons", empty("Every quote in the book is eligible.")); return; }
    const counts = new Map(); held.forEach((q) => q.reason_codes.forEach((code) => counts.set(code, (counts.get(code) || 0) + 1)));
    const ordered = [...counts].sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0])));
    const unexplained = held.filter((q) => !q.reason_codes.length).length; const top = ordered[0];
    const rows = ordered.map(([code, n]) => ({ label: reasonText(code), value: n, text: int(n) + " of " + int(held.length), title: reasonText(code) + ": " + n + " of " + held.length + " held quotes" }));
    if (unexplained) rows.push({ label: "No reason given", value: unexplained, text: int(unexplained) + " of " + int(held.length), title: unexplained + " held quotes carry no reason" });
    const only = top && top[0] === START ? held.filter((q) => q.reason_codes.length === 1 && q.reason_codes[0] === START).length : null;
    const caption = (top ? reasonText(top[0]) + " is on " + int(top[1]) + " of the " + int(held.length) + " held quotes" + (only !== null ? " and is the only reason for " + int(only) + " of them" : "") + ". " : "") + "A quote can fail for more than one reason, so the bars add up to more than " + int(held.length) + ". " + int(data.quotes.length - held.length) + " of " + int(data.quotes.length) + " quotes in the book are eligible.";
    replace("desk-reasons",
      C.hbars({ rows, width, enter: ctx.enter("reasons"), labelWidth: 188, valueWidth: 84, stack: width < 520, className: "ov-one", description: "Why " + held.length + " quotes are held back from ranking: " + rows.map((r) => r.label + " " + r.value).join("; ") + "." }),
      h("p", "ov-caption", caption),
      C.twin("Reasons quotes are held back", ["Reason", "Quotes"], rows.map((r) => [r.label, r.value])));
  }

  /* ---- Seller health ---- */
  function renderProviders() {
    const data = state.data; const byProvider = new Map();
    data.quotes.forEach((q) => { const row = byProvider.get(q.provider_id) || { eligible: 0, reasons: new Map() }; if (q.eligible) row.eligible += 1; else q.reasons.forEach((reason) => row.reasons.set(reason, (row.reasons.get(reason) || 0) + 1)); byProvider.set(q.provider_id, row); });
    const rows = data.providers.slice().sort((a, b) => b.gpus - a.gpus || String(a.name).localeCompare(String(b.name))); const shown = state.showAll ? rows : rows.slice(0, 10); const body = h("tbody");
    shown.forEach((p) => {
      const stat = byProvider.get(p.id) || { eligible: 0, reasons: new Map() }; const top = [...stat.reasons].sort((a, b) => b[1] - a[1])[0]; const recent = Number.isFinite(p.changed_tick) && p.changed_tick >= 0 && data.meta.tick - p.changed_tick <= 6;
      const link = h("button", "row-link", p.name); link.type = "button";
      link.addEventListener("click", () => { const first = data.quotes.find((q) => q.provider_id === p.id); if (first) { state.model = first.gpu; state.selected = first.id; D.host.showView("quotes"); } });
      const live = p.quotes > 0;
      body.append(labelled(h("tr", recent ? "recent" : "", h("th", "ov-first", link), h("td", "", p.grade !== "U" ? [chip(p.grade), h("span", "ov-kind", p.kind === "Reseller" ? "Broker" : "Owner")] : [h("span", "ov-unrated", "Not rated"), h("span", "ov-kind", p.kind === "Reseller" ? "Broker" : "Owner")]),
        h("td", "ov-n", p.score === null ? "—" : p.score.toFixed(0)), h("td", "ov-n", int(p.quotes)), h("td", "ov-n", int(p.gpus)),
        h("td", "ov-n", live ? stat.eligible + " of " + p.quotes : h("span", "ov-unrated", "No live quotes")), h("td", "ov-why", !live ? "" : top ? top[0] : stat.eligible ? "None held" : "")), ["", "Grade", "Score", "Live quotes", "GPUs on offer", "Eligible quotes", "Most common hold"]));
    });
    const table = h("table", "ov-table ov-card ov-sellers", h("caption", "sr-only", "Sellers by GPUs on offer, with grade, score, live quotes, eligible quotes and the reason most of their other quotes are held"),
      h("thead", "", h("tr", "", th("Seller", "ov-first"), th("Grade"), th("Score", "ov-n"), th("Live quotes", "ov-n"), th("GPUs on offer", "ov-n"), th("Eligible quotes", "ov-n"), th("Most common hold"))), body);
    const toggle = h("button", "link-button ov-toggle", state.showAll ? "Show top 10" : "Show all " + rows.length); toggle.type = "button"; toggle.addEventListener("click", () => { state.showAll = !state.showAll; renderProviders(); });
    const box = h("div", "ov-scroll", table); box.tabIndex = 0; box.setAttribute("role", "region"); box.setAttribute("aria-label", "Sellers; scroll to see every column");
    replace("desk-providers", box, rows.length > 10 ? toggle : null);
  }

  /* ---- Event feed ---- */
  function renderActivity() {
    const alerts = state.data.alerts.slice(0, 9);
    if (!alerts.length) { replace("desk-activity", h("p", "ov-note", "No market events yet. A scenario, a price move or a withdrawal appears here as it happens.")); return; }
    const list = h("ol", "ov-feed"); alerts.forEach((a) => list.append(h("li", "ov-event is-" + a.level + (state.flash.has(a.n) ? " flash" : ""), h("time", "", clock(a.time, true)), h("span", "", a.text))));
    replace("desk-activity", list);
  }

  window.OverviewMarket = Object.freeze({ renderBasis, renderTrend, renderSupply, renderReasons, renderProviders, renderActivity });
})();
