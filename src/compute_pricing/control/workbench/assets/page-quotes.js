/* Quotes: every simulated quote for one model, ranked by what it costs all-in. */
(() => {
  "use strict";
  const D = window.ComputeDemo; if (!D) return;
  const { host, charts, state, h, int, usd, pct, compact, chip, replace, empty, live, modelTabs, text, FIELD_NAMES, CATEGORIES, byId } = D;
  const showView = D.host.showView;

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
    const prefill = h("button", "primary-button", "Price this quote"); prefill.type = "button"; prefill.addEventListener("click", () => host.priceQuote ? host.priceQuote({ ...q, price: q.exact?.price ?? String(q.price) }) : showView("pricing"));
    replace("quotes-detail", h("div", "detail-head", h("div", "", h("h2", "", q.id), h("p", "muted", q.provider)), h("div", "detail-grade", chip(q.grade), h("strong", "", provider.score.toFixed(0)), h("small", "", "quality score"))),
      h("h3", "", "All-in cost per GPU-hour"), q.risk_adjusted === null ? empty("Term not stated, so no all-in cost can be computed.") : costBreakdown([{ label: q.id, quote: q }], false),
      q.eligible ? h("p", "standing ok", "Eligible: grade " + q.grade + ", " + q.missing.length + " of 10 key terms missing.") : h("p", "standing no", "Not eligible: " + q.reasons.join("; ") + "."),
      h("h3", "", "Seller scorecard"), card, h("h3", "", "Terms"), grid,
      q.missing.length ? h("p", "muted", "Missing: " + q.missing.map((f) => FIELD_NAMES[f] || f).join(", ") + ".") : null, q.flags.length ? h("p", "muted", q.flags.join(" ")) : null, prefill);
  }
  ["allin", "price"].forEach((key) => byId("sort-" + key).addEventListener("click", () => { state.sort = key; renderQuotes(); }));
  D.register("quotes", { render: renderQuotes, resize: true });
})();
