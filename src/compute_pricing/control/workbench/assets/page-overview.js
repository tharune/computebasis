/* The Overview: the state of the simulated market at a glance. */
(() => {
  "use strict";
  const D = window.ComputeDemo; if (!D) return;
  const { charts, state, h, int, usd, pct, compact, clock, gradeClass, chip, replace, empty, live, fit, median, modelTabs, text, legendGrades, lowestPrice, GRADES, scenarioSeen, scenarioReady } = D;
  const showView = D.host.showView; const rememberScenarios = scenarioReady;

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

  function scenarioMarkers() {
    const data = state.data; rememberScenarios();
    return [...scenarioSeen.values()].map((a) => ({ index: data.series.ticks.indexOf(a.tick), label: a.scenario_label || "Scenario", dim: false, title: a.text })).filter((marker) => marker.index >= 0);
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
      charts.lineChart({ points: times.length, series: lines, gap: hasBest ? ["best", "cheapest"] : null, format: (v) => "$" + v.toFixed(2), markers: scenarioMarkers(), xLabel: (i) => clock(times[i]), width, height: narrow ? 220 : 270, marginRight: narrow ? 52 : 134, endLabels: narrow ? "value" : "full", yTickCount: 5, xTickCount: narrow ? 2 : 3,
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

  D.register("desk", { render: renderDesk, resize: true });
})();
