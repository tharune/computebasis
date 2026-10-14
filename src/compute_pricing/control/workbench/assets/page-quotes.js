/* Quotes: the simulated market for one GPU model. A headline (lowest quote against best eligible all-in), the quote ladder, why quotes are
   not eligible, every quote ranked in a table, and the selected quote's cost, standing, seller scorecard and terms.
   The server owns every number; this file prints them. The ladder is page-quotes-ladder.js and the eligibility chart is page-quotes-reasons.js
   (both load after this file, so they are looked up when a render needs them). Selection lives in ComputeDemo.state.selected, so a poll
   redraws without moving the selected row, the scroll position or the keyboard focus. */
(() => {
  "use strict";
  const D = window.ComputeDemo; if (!D) return;
  const { host, charts, state, h, int, usd, pct, compact, replace, empty, live, modelTabs, text, FIELD_NAMES, CATEGORIES, MONTHS, byId } = D;
  const showView = host.showView;

  /* ---- words ---- */
  /* What each note on a quote means, in plain sentences. A note this map does not know is shown humanised, never as a raw code. */
  const FLAGS = {
    illustrative_uncalibrated_simulation: "Illustrative simulation: these costs use invented assumptions that are not calibrated to any real market.",
    financing_assumes_deposit_held_for_full_contract_term: "Financing assumes the down payment is held for the whole contract term.",
    loss_assumes_unrecovered_deposit_plus_full_term_replacement_premium: "Expected loss assumes that if the seller fails only part of the deposit comes back, and the buyer pays a premium to replace the full term.",
    scorecard_and_exposure_models_are_alternatives_not_cumulative: "The seller scorecard charge and the expected-loss charge are two ways to price seller risk. The all-in cost uses expected loss; the two are never added together.",
    payment_days_and_operating_features_are_preserved_not_additional_cost_models: "Payment days, interconnect and cooling are shown as quoted and do not change the all-in cost.",
  };
  const MISSING = { ...FIELD_NAMES, grade: "Seller grade", down_payment: "Down payment", expires: "Expiry date" };
  const lowerFirst = (value) => value.charAt(0).toLowerCase() + value.slice(1);
  const humanise = (code) => { const words = String(code).replace(/_/g, " ").trim(); return words ? words.charAt(0).toUpperCase() + words.slice(1) : ""; };
  const flagText = (code) => FLAGS[code] || humanise(code) + ".";
  const joinList = (parts) => (parts.length < 2 ? parts[0] || "" : parts.slice(0, -1).join(", ") + " and " + parts[parts.length - 1]);
  const date = (iso) => { const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || ""); return match ? Number(match[3]) + " " + MONTHS[Number(match[2]) - 1] + " " + match[1] : ""; };
  const m4 = (value) => (value === null || value === undefined || !Number.isFinite(value) ? "—" : value.toFixed(4));
  const usd4 = (value) => (value === null || value === undefined || !Number.isFinite(value) ? "—" : "$" + value.toFixed(4));
  const ordinalOf = (n, of) => n + " of " + of;

  /* Why a quote is not eligible: a clause for running text, and a full sentence for the detail panel. */
  const REASON = {
    contract_start_precedes_as_of: { clause: (q) => "its contract start" + (date(q.contract_start) ? " (" + date(q.contract_start) + ")" : "") + " has passed", detail: (q, asOf) => "The contract starts " + (date(q.contract_start) || "on a date before the book date") + ", before the book date of " + (date(asOf) || "the simulation") + "." },
    simulated_quote_expired: { clause: (q) => "it expired" + (date(q.expires) ? " on " + date(q.expires) : ""), detail: (q) => "The quote expired" + (date(q.expires) ? " on " + date(q.expires) : "") + "." },
    missing_down_payment: { clause: () => "it states no down payment", detail: () => "No down payment is stated, so financing and expected loss cannot be costed." },
    missing_expires: { clause: () => "it states no expiry date", detail: () => "No expiry date is stated." },
    missing_interconnect: { clause: () => "it states no interconnect", detail: () => "No interconnect is stated." },
    missing_cooling: { clause: () => "it states no cooling", detail: () => "No cooling is stated." },
    missing_grade: { clause: () => "its seller is unrated", detail: () => "The seller has no grade, so expected loss cannot be costed." },
    missing_months: { clause: () => "it states no contract length", detail: () => "No contract length is stated." },
    no_stated_duration: { clause: () => "it states no contract length", detail: () => "No contract length is stated." },
  };
  const reasonName = (quote, index) => quote.reasons[index] || humanise(quote.reason_codes[index]);
  const reasonClause = (quote, index) => (REASON[quote.reason_codes[index]]?.clause(quote)) || lowerFirst(reasonName(quote, index));
  const reasonDetail = (quote, index, asOf) => (REASON[quote.reason_codes[index]]?.detail(quote, asOf)) || reasonName(quote, index) + ".";
  const clauses = (quote) => joinList(quote.reason_codes.map((code, i) => reasonClause(quote, i)));
  /* Why a quote has no all-in cost. The reasons list already says so when the cause is also an eligibility reason, so this only speaks when it adds something. */
  function unpricedWhy(quote) {
    const said = (code) => quote.reason_codes.includes(code);
    if (quote.missing.includes("down_payment") || quote.down_payment === null) return said("missing_down_payment") ? "" : "No down payment is stated, so financing and expected loss cannot be costed.";
    if (quote.grade === "U") return said("missing_grade") ? "" : "The seller has no grade, so expected loss cannot be costed.";
    if (quote.months === null) return "No contract length is stated, so the cost cannot be worked out over the term.";
    return "The book does not price this quote all-in.";
  }
  const sellerWord = (quote) => (quote.grade === "U" ? "an unrated seller" : "a grade " + quote.grade + " seller");
  const gradeChip = (grade) => { const node = D.chip(grade, grade === "U" ? "Unrated seller" : "Grade " + grade); return node; };

  /* ---- keyboard focus survives a redraw: focusable things are keyed, and the keyed one that had focus gets it back ---- */
  let focusables = new Map(); let rowNodes = new Map(); let hoverId = ""; let revealNext = false; let drawn = null; let notesOpen = false; let detailScroll = null; let detailFor = "";
  const keyed = (node, key) => { node.setAttribute("data-fk", key); focusables.set(key, node); return node; };
  const focusedKey = () => { const active = typeof document !== "undefined" ? document.activeElement : null; return active && active.getAttribute ? active.getAttribute("data-fk") : null; };
  const refocus = (key) => { const node = key ? focusables.get(key) : null; if (node) node.focus({ preventScroll: true }); };
  const memo = { ladderKey: "", reasonsKey: "", marks: new Map() };  // what the two charts last drew
  host.onView?.((name) => { if (name !== "quotes") { drawn = null; hoverId = ""; memo.ladderKey = ""; memo.reasonsKey = ""; } });

  /* ---- ordering ---- */
  const compareNumbers = (a, b) => (a === null && b === null ? 0 : a === null ? 1 : b === null ? -1 : a - b);
  const byRank = (a, b) => compareNumbers(a.risk_rank ?? null, b.risk_rank ?? null) || compareNumbers(a.price, b.price) || a.id.localeCompare(b.id);
  const byAllIn = (a, b) => compareNumbers(a.risk_adjusted, b.risk_adjusted) || compareNumbers(a.price, b.price) || a.id.localeCompare(b.id);
  const byPrice = (a, b) => compareNumbers(a.price, b.price) || a.id.localeCompare(b.id);
  /* By all-in cost, eligible quotes come first in their rank order, then the rest by all-in cost, unpriced ones last. By price is one flat list. */
  function arrange(quotes, sort) {
    if (sort === "price") return [{ title: "", rows: quotes.slice().sort(byPrice) }];
    const eligible = quotes.filter((q) => q.eligible).sort(byRank); const others = quotes.filter((q) => !q.eligible).sort(byAllIn);
    return [{ title: "Eligible, ranked by all-in cost", rows: eligible }, { title: "Not eligible", rows: others }].filter((group) => group.rows.length);
  }

  /* ---- the headline ---- */
  function figure(kind, title, value, unit, quote, note, focusKey) {
    const open = h("button", "qx-ref-link", quote.ref); open.type = "button"; keyed(open, focusKey); open.setAttribute("aria-label", "Open " + quote.ref + " in the table and detail panel"); open.addEventListener("click", () => select(quote.id, { reveal: true }));
    return h("div", "qx-figure " + kind, h("p", "qx-figure-label", title), h("p", "qx-figure-value", value, h("small", "", unit)), h("p", "qx-figure-who", open, gradeChip(quote.grade), h("span", "", quote.provider)), h("p", "qx-figure-note", note));
  }
  function headline(m, quotes, lowest, best, basis) {
    if (!lowest) return h("div", "qx-say", h("h2", "", "No " + m.model + " quotes in the book."), h("p", "qx-lede", "Reset the simulation to restore the starting book."));
    const same = best && best.id === lowest.id;
    let title; let body;
    if (same) { title = lowest.ref + " is both the lowest " + m.model + " quote and the best eligible buy."; body = lowest.ref + " is from " + lowest.provider + ", " + sellerWord(lowest) + ". It quotes " + usd4(lowest.price) + " and costs " + usd4(best.risk_adjusted) + " per GPU-hour all-in, including financing and expected loss."; }
    else if (best && !lowest.eligible) { title = "The lowest " + m.model + " quote is not eligible. " + (basis === null ? "The best eligible buy costs more, all-in." : "The best eligible buy, all-in, is " + pct(basis, 1) + " above it."); body = lowest.ref + " quotes " + usd4(lowest.price) + " per GPU-hour but is not eligible: " + clauses(lowest) + ". " + best.ref + ", from " + best.provider + ", " + sellerWord(best) + ", is the best eligible buy at " + usd4(best.risk_adjusted) + " all-in, including financing and expected loss."; }
    else if (best) { title = "The lowest " + m.model + " quote is eligible, but " + best.ref + " is cheaper all-in."; body = lowest.ref + " quotes " + usd4(lowest.price) + " and costs " + usd4(lowest.risk_adjusted) + " all-in. " + best.ref + " quotes " + usd4(best.price) + " and costs " + usd4(best.risk_adjusted) + " all-in, from " + best.provider + ", " + sellerWord(best) + "."; }
    else { title = "No " + m.model + " quote is eligible."; body = "The lowest quote is " + lowest.ref + " at " + usd4(lowest.price) + " per GPU-hour" + (clauses(lowest) ? ", and " + clauses(lowest) : "") + ". Until a quote passes the eligibility checks there is no best buy to show."; }
    const lowNote = lowest.eligible ? "Eligible" : "Not eligible: " + (lowest.reasons[0] || "see the detail panel") + (lowest.reasons.length > 1 ? " and " + (lowest.reasons.length - 1) + " more" : "");
    const figures = [figure("low", "Lowest quote", usd4(lowest.price), " per GPU-hour", lowest, lowNote, "fig:low")];
    if (best) figures.push(figure("best", "Best eligible, all-in", usd4(best.risk_adjusted), " per GPU-hour", best, same ? "The lowest quote is also the best buy" : (basis === null ? "Eligible" : "Eligible, " + pct(basis, 1) + " above the lowest quote"), "fig:best"));
    else figures.push(h("div", "qx-figure best none", h("p", "qx-figure-label", "Best eligible, all-in"), h("p", "qx-figure-value", "None"), h("p", "qx-figure-note", "No " + m.model + " quote is eligible")));
    return [h("div", "qx-say", h("h2", "", title), h("p", "qx-lede", body)), h("div", "qx-figures", figures)];
  }

  /* ---- the cost of one quote ---- */
  /* One bar for the all-in cost per GPU-hour: the quoted price, then financing, then expected loss, with a 2px gap between parts and a 4px
     rounded end on the last. It is zero-based, so the add-ons are as small as they really are; the list under it prints every value. */
  function costBar(parts, total, width = 360) {
    const gap = 2; const bar = 14; const shown = parts.filter((p) => p.value > 0); const room = width - gap * Math.max(0, shown.length - 1);
    const chart = charts.svg("svg", { viewBox: "0 0 " + width + " " + bar, class: "chart qx-costbar", role: "img", "aria-label": "All-in cost " + usd4(total) + " per GPU-hour: " + parts.map((p) => p.name.toLowerCase() + " " + usd4(p.value)).join(", ") });
    let cursor = 0; const sizes = shown.map((p) => Math.max(2, (p.value / total) * room)); const spare = sizes.reduce((s, v) => s + v, 0) - room; if (spare > 0) { const widest = sizes.indexOf(Math.max(...sizes)); sizes[widest] -= spare; }
    shown.forEach((part, i) => {
      const length = sizes[i]; const last = i === shown.length - 1; const r = Math.min(4, length / 2);
      const d = last ? "M" + cursor + " 0H" + (cursor + length - r) + "A" + r + " " + r + " 0 0 1 " + (cursor + length) + " " + r + "V" + (bar - r) + "A" + r + " " + r + " 0 0 1 " + (cursor + length - r) + " " + bar + "H" + cursor + "Z" : "M" + cursor + " 0H" + (cursor + length) + "V" + bar + "H" + cursor + "Z";
      chart.append(charts.svg("path", { d, class: "ch-part " + part.className })); cursor += length + gap;
    });
    return chart;
  }
  function costBreakdown(entries, named = true, width = 360) {
    return h("div", "qx-cost", entries.map(({ label, tag, quote }) => {
      const priced = quote.risk_adjusted !== null; const total = priced ? quote.risk_adjusted : null;
      const parts = [{ name: "Quoted price", value: quote.price, className: "part-price" }, { name: "Financing", value: quote.financing, className: "part-financing", needs: "a down payment" }, { name: "Expected loss", value: quote.exposure, className: "part-exposure", needs: "a graded seller" }];
      const share = (value) => (priced && total > 0 && value !== null ? (value / total * 100).toFixed(1) + "%" : "");
      return h("div", "qx-cost-row", named && label ? h("p", "qx-cost-name", label, tag ? h("small", "", " " + tag) : null) : null,
        priced ? [h("p", "qx-cost-total", usd4(total), h("small", "", " per GPU-hour all-in"), quote.price > 0 ? h("span", "qx-cost-over", pct(total / quote.price - 1, 1, true) + " on the quoted price") : null), costBar(parts.map((p) => ({ ...p, value: p.value || 0 })), total, width)] : h("p", "qx-cost-total none", "All-in cost not available"),
        h("ul", "qx-cost-parts", parts.map((p) => h("li", "", h("span", "swatch " + p.className), h("span", "qx-cost-part-name", p.name), h("strong", "", p.value === null || p.value === undefined ? "Not available" : usd4(p.value)), h("span", "qx-cost-part-share", share(p.value))))));
    }));
  }

  /* ---- the table ---- */
  /* Columns, in order. `from` is the narrowest table (px) that still shows the column: the table keeps the seller's name and the two prices at any
     width, drops Term and Down first, then Rank, vs lowest and Standing (the reason moves under the seller's name). */
  const COLUMNS = [{ key: "rank", label: "Rank", cls: "c-rank qx-num", from: 701, title: "Position among eligible quotes, ranked by all-in cost" }, { key: "quote", label: "Quote", cls: "c-quote", from: 0, title: "" }, { key: "seller", label: "Seller", cls: "c-seller", from: 0, title: "Seller grade and name" },
    { key: "quoted", label: "Quoted", cls: "c-quoted qx-num", from: 0, title: "Quoted price, dollars per GPU-hour" }, { key: "allin", label: "All-in", cls: "c-allin qx-num", from: 0, title: "Quoted price plus financing and expected loss, dollars per GPU-hour" },
    { key: "vs", label: "vs lowest", cls: "c-vs qx-num", from: 701, title: "All-in cost compared with the lowest quoted price" }, { key: "term", label: "Term", cls: "c-term qx-num", from: 801, title: "Contract term" },
    { key: "down", label: "Down", cls: "c-down qx-num", from: 801, title: "Down payment, share of contract value" }, { key: "standing", label: "Standing", cls: "c-standing", from: 701, title: "Eligible, or the first reason it is not" }];
  /* Short names for the table; the detail panel and the breakdown chart use the full ones. */
  const SHORT = { contract_start_precedes_as_of: "Start has passed", simulated_quote_expired: "Expired", missing_down_payment: "No down payment", missing_expires: "No expiry", missing_interconnect: "No interconnect", missing_cooling: "No cooling", missing_grade: "Unrated seller", missing_months: "No term", no_stated_duration: "No term" };
  function standingOf(q) { return q.eligible ? "Eligible" : (SHORT[q.reason_codes[0]] || q.reasons[0] || "Not eligible") + (q.reasons.length > 1 ? " +" + (q.reasons.length - 1) : ""); }
  function renderTable(model, quotes, selected, lowest, best) {
    const groups = arrange(quotes, state.sort); const order = groups.flatMap((g) => g.rows); const lowPrice = lowest ? lowest.price : null;
    const room = Math.floor(Number(byId("quotes-scroll").clientWidth) || 0); const columns = COLUMNS.filter((column) => !room || room >= column.from); const compactTable = Boolean(room) && room <= 700;
    byId("quotes-table").classList.toggle("qx-compact", compactTable);
    rowNodes = new Map();
    const bodies = groups.map((group) => {
      const body = h("tbody");
      if (group.title) { const th = h("th", "", group.title, h("span", "", String(group.rows.length))); th.setAttribute("colspan", String(columns.length)); th.setAttribute("scope", "rowgroup"); body.append(h("tr", "qx-group", th)); }
      group.rows.forEach((q) => {
        const isSelected = q.id === selected.id;
        const link = h("button", "row-link", q.ref); link.type = "button"; keyed(link, "row:" + q.id); link.setAttribute("tabindex", isSelected ? "0" : "-1"); if (isSelected) link.setAttribute("aria-current", "true");
        link.addEventListener("click", () => select(q.id));
        link.addEventListener("keydown", (event) => {
          const at = order.findIndex((row) => row.id === q.id); let next = null;
          if (event.key === "ArrowDown") next = order[Math.min(order.length - 1, at + 1)]; else if (event.key === "ArrowUp") next = order[Math.max(0, at - 1)]; else if (event.key === "Home") next = order[0]; else if (event.key === "End") next = order[order.length - 1];
          if (next) { event.preventDefault?.(); select(next.id, { reveal: true, focus: "row:" + next.id }); }
        });
        const isLow = Boolean(lowest) && q.id === lowest.id; const isBest = Boolean(best) && q.id === best.id; const status = standingOf(q);
        const tags = [isLow || isBest ? h("span", "qx-tag" + (isBest ? " best" : ""), isLow && isBest ? "Lowest, best" : isLow ? "Lowest" : "Best") : null, q.workbook ? h("span", "qx-tag", "Workbook") : null];
        const cells = {
          rank: h("td", "qx-num c-rank", q.risk_rank === null || q.risk_rank === undefined ? "—" : String(q.risk_rank)), quote: h("th", "c-quote", link, tags),
          seller: h("td", "c-seller", h("span", "qx-seller", gradeChip(q.grade), h("span", "qx-seller-text", h("span", "qx-name", q.provider || "Unknown seller"), h("span", "qx-sub", status)))),
          quoted: h("td", "qx-num c-quoted", m4(q.price)), allin: h("td", "qx-num c-allin strong", q.risk_adjusted === null ? "—" : m4(q.risk_adjusted)),
          vs: h("td", "qx-num c-vs", lowPrice && q.risk_adjusted !== null ? pct(q.risk_adjusted / lowPrice - 1, 1, true) : "—"), term: h("td", "qx-num c-term", q.months === null || q.months === undefined ? "—" : q.months + " mo"),
          down: h("td", "qx-num c-down", q.down_payment === null ? "—" : pct(q.down_payment, 0)), standing: h("td", "c-standing", h("span", q.eligible ? "qx-ok" : "qx-no", status)),
        };
        const row = h("tr", ["qx-row", isSelected ? "selected" : "", q.eligible ? "" : "ineligible"].filter(Boolean).join(" "), columns.map((column) => cells[column.key]));
        row.setAttribute("data-id", q.id); if (!q.eligible) row.setAttribute("title", q.reasons.join("; ") + (q.risk_adjusted === null ? ". Cannot be priced all-in." : ""));
        row.addEventListener("click", (event) => { if (event.target !== link) select(q.id); });
        rowNodes.set(q.id, row); body.append(row);
      });
      return body;
    });
    const head = h("tr", "", columns.map((column) => { const th = h("th", column.cls, column.label); th.setAttribute("scope", "col"); if (column.title) th.setAttribute("title", column.title); return th; }));
    const cols = h("colgroup", "", columns.map((column) => h("col", column.cls.split(" ")[0])));
    replace("quotes-table", h("caption", "sr-only", model + " quotes " + (state.sort === "price" ? "by quoted price" : "by all-in cost, eligible quotes first") + ", dollars per GPU-hour"), cols, h("thead", "", head), bodies);
    ["allin", "price"].forEach((key) => byId("sort-" + key).setAttribute("aria-pressed", String(state.sort === key)));
    text("quotes-foot", "All " + quotes.length + " quotes are listed; scroll the table to see them. Rank counts eligible quotes only. Costs are US dollars per GPU-hour.");
  }
  function revealRow(id) {
    const region = byId("quotes-scroll"); const rowNode = rowNodes.get(id);
    if (!rowNode || typeof rowNode.offsetTop !== "number" || !region.clientHeight) return;
    const headHeight = 34; const top = rowNode.offsetTop; const bottom = top + rowNode.offsetHeight;
    if (top - headHeight < region.scrollTop) region.scrollTop = Math.max(0, top - headHeight - 6); else if (bottom > region.scrollTop + region.clientHeight) region.scrollTop = bottom - region.clientHeight + 6;
  }

  /* ---- the detail panel ---- */
  /* The cost bar is drawn at the width it is shown at; that depends on which of the page's layouts is active (see quotes.css). */
  function costWidth() {
    const box = byId("quotes-detail"); const full = Math.floor(Number(box.clientWidth) || 0); if (full < 200) return 360;
    const match = (query) => typeof window.matchMedia === "function" && window.matchMedia(query).matches;
    return Math.max(200, match("(min-width: 1180px)") ? full - 12 : match("(min-width: 761px)") ? Math.floor((full - 40) / 2) : full);
  }
  function scorecardRows(data, provider) {
    const max = data.assumptions.scorecard_policy?.rating_scale?.maximum ?? 4;
    return h("table", "qx-scorecard", h("caption", "sr-only", "Seller scorecard for " + provider.name + ": each category's weight and tier out of " + max), h("tbody", "", Object.entries(data.assumptions.weights).map(([key, weight]) => {
      const tier = provider.tiers ? provider.tiers[key] : null; const known = Number.isFinite(tier);
      const pips = h("span", "pips", Array.from({ length: max }, (_, n) => h("i", known && n < tier ? "pip on" : "pip"))); pips.setAttribute("role", "img"); pips.setAttribute("aria-label", known ? "Tier " + tier + " of " + max : "No tier");
      return h("tr", "", h("th", "", CATEGORIES[key] || humanise(key)), h("td", "qx-num weight", pct(weight, 0)), h("td", "", pips), h("td", "qx-num tier", known ? tier + " of " + max : "—"));
    })));
  }
  function gradeBand(data, grade) {
    const bands = (data.assumptions.grades || []).slice().sort((a, b) => b.minimum - a.minimum); const index = bands.findIndex((band) => band.grade === grade); if (index < 0 || !Number.isFinite(bands[index].minimum)) return "";
    return index === 0 ? "Grade " + grade + " is a score of " + bands[index].minimum + " or more." : bands[index].minimum > 0 ? "Grade " + grade + " is a score of " + bands[index].minimum + " or more and below " + bands[index - 1].minimum + "." : "Grade " + grade + " is a score below " + bands[index - 1].minimum + ".";
  }
  function facts(q, m) {
    const unstated = h("span", "unstated", "Not stated"); const place = q.location ? q.location + (q.country && !q.location.includes("(" + q.country + ")") ? ", " + q.country : "") : null;
    const rows = [["Quoted price", "$" + (q.exact?.price ?? String(q.price)) + " per GPU-hour"], ["GPUs", int(q.gpus)], ["Term", q.months === null ? unstated : q.months + (q.months === 1 ? " month" : " months")], ["Contract value", q.contract_value === null ? unstated : "$" + compact(q.contract_value)],
      ["Down payment", q.down_payment === null ? unstated : pct(q.down_payment, 0)], ["Payment terms", q.payment_days === null ? unstated : "Net " + q.payment_days], ["Contract start", date(q.contract_start) || unstated], ["Expires", q.expires ? date(q.expires) + (!Number.isFinite(q.days_to_expiry) ? "" : q.days_to_expiry < 0 ? ", expired" : ", in " + q.days_to_expiry + " days") : unstated],
      ["Lead time", q.lead_weeks === null || q.lead_weeks === undefined ? unstated : q.lead_weeks + " weeks"], ["Location", place || unstated], ["Interconnect", q.interconnect || unstated], ["Cooling", q.cooling || unstated],
      ["Against simulation reference", !Number.isFinite(q.discount_to_reference) || !Number.isFinite(m.reference) ? unstated : pct(Math.abs(q.discount_to_reference), 1) + (q.discount_to_reference >= 0 ? " below " : " above ") + usd(m.reference, 2)],  // the server's discount is positive when the price is under the reference
      ["Chance the seller fails in the term", !Number.isFinite(q.failure_probability) ? unstated : pct(q.failure_probability, 2)]];
    return h("dl", "qx-facts", rows.map(([name, value]) => h("div", "", h("dt", "", name), h("dd", "", value))));
  }
  function section(title, ...children) { return h("section", "qx-sec", h("h3", "", title), children); }
  function renderDetail(q, data, m, lowest, best, eligibleCount) {
    const provider = data.providers.find((p) => p.id === q.provider_id) || null; const asOf = data.meta.as_of;
    const previous = detailScroll; const sameQuote = detailFor === q.id; const keepAt = previous && sameQuote ? previous.scrollTop : 0;
    const kind = provider && provider.kind ? String(provider.kind) + (provider.region ? ", " + provider.region : "") : provider && provider.region ? String(provider.region) : "";
    const score = provider && Number.isFinite(provider.score) ? provider.score : null;
    const head = h("div", "qx-detail-head", h("div", "qx-detail-id", h("h2", "", q.ref), h("p", "qx-detail-seller", q.provider || "Unknown seller", kind ? h("span", "", kind) : null)),
      h("div", "qx-detail-grade", gradeChip(q.grade), h("small", "", score === null ? "Not scored" : "Score " + score.toFixed(0))));
    const tags = [q.id === (lowest && lowest.id) ? "lowest quote" : "", q.id === (best && best.id) ? "best eligible buy" : ""].filter(Boolean);
    const standing = q.eligible ? [h("p", "qx-standing ok", "Eligible"), h("p", "qx-standing-note", (q.risk_rank ? "Ranked " + ordinalOf(q.risk_rank, eligibleCount) + " eligible quotes by all-in cost." : "Eligible.") + (tags.length ? " This is the " + joinList(tags) + "." : ""))]
      : [h("p", "qx-standing no", "Not eligible" + (tags.length ? "; this is the " + joinList(tags) : "")), h("ul", "qx-why", q.reason_codes.map((code, i) => h("li", "", reasonDetail(q, i, asOf))))];
    const cost = [costBreakdown([{ quote: q }], false, costWidth()), q.risk_adjusted === null && unpricedWhy(q) ? h("p", "qx-standing-note", unpricedWhy(q)) : null,
      q.risk_adjusted_scorecard !== null && q.risk_adjusted_scorecard !== undefined && Number.isFinite(q.risk_adjusted_scorecard) ? h("p", "qx-alt", "Scorecard method: " + usd4(q.risk_adjusted_scorecard) + " all-in. It prices seller risk with the grade charge instead of expected loss, so the two are alternatives and are not added.") : null];
    const card = provider ? [scorecardRows(data, provider), gradeBand(data, q.grade) ? h("p", "qx-standing-note", gradeBand(data, q.grade)) : q.grade === "U" ? h("p", "qx-standing-note", "This seller has no grade. An unknown rating is not a zero rating.") : null] : empty("Seller scorecard not available.");
    const missing = q.missing.length ? h("p", "qx-standing-note", "Not stated: " + joinList(q.missing.map((field) => (MISSING[field] || humanise(field)).toLowerCase())) + ".") : null;
    const notes = h("details", "qx-notes", h("summary", "", "How this cost is built"), h("ul", "", q.flags.map((flag) => h("li", "", flagText(flag)))));
    if (notesOpen) notes.setAttribute("open", ""); notes.addEventListener("toggle", () => { notesOpen = Boolean(notes.open); });
    const body = h("div", "qx-detail-body", section("Standing", standing), section("Cost per GPU-hour", cost), section("Seller scorecard", card), section("Terms", facts(q, m), missing), q.flags.length ? notes : null);
    body.setAttribute("tabindex", "0"); body.setAttribute("role", "region"); body.setAttribute("aria-label", "Details of " + q.ref + "; scroll for more");
    const price = h("button", "primary-button", "Price this quote"); price.type = "button"; keyed(price, "price");
    price.addEventListener("click", () => (host.priceQuote ? host.priceQuote({ ...q, price: q.exact?.price ?? String(q.price) }) : showView("pricing")));
    const foot = h("div", "qx-detail-foot", price, h("p", "", "Opens Pricing with this quote's price as the ask. Nothing is evaluated or saved until you press Evaluate."));
    replace("quotes-detail", head, body, foot);
    detailScroll = body; detailFor = q.id; if (keepAt) body.scrollTop = keepAt;
  }

  /* ---- the page ---- */
  function select(id, { reveal = false, focus = "" } = {}) { state.selected = id; revealNext = reveal; renderQuotes(focus); }
  function renderQuotes(focusKey = "") {
    if (!live()) {
      focusables = new Map(); memo.ladderKey = ""; memo.reasonsKey = ""; text("quotes-lede", state.error ? "The simulated book could not be read." : "Opening the simulated book…");
      replace("quotes-callout", empty(state.error || "Opening the simulated book…")); ["quotes-ladder", "quotes-reasons", "quotes-table", "quotes-detail"].forEach((id) => replace(id)); text("quotes-foot", ""); return;
    }
    const data = state.data; const wanted = focusKey || focusedKey(); focusables = new Map();
    text("quotes-lede", data.quotes.length + " simulated quotes. Costs are US dollars per GPU-hour; all-in adds financing and expected loss to the quoted price.");
    modelTabs("quotes-models", false);
    const m = data.models.find((entry) => entry.model === state.model) || data.models[0];
    if (!m) { memo.ladderKey = ""; memo.reasonsKey = ""; replace("quotes-callout", empty("The simulated book holds no quotes.")); ["quotes-ladder", "quotes-reasons", "quotes-table", "quotes-detail"].forEach((id) => replace(id)); text("quotes-foot", ""); return; }
    state.model = m.model;
    const quotes = data.quotes.filter((q) => q.gpu === m.model);
    const pick = (summary) => (summary ? quotes.find((q) => q.id === summary.id) || null : null);
    const lowest = pick(m.cheapest) || quotes.slice().sort(byPrice)[0] || null; const best = pick(m.best);
    const basis = Number.isFinite(m.basis) ? m.basis : null; const eligibleCount = quotes.filter((q) => q.eligible).length;
    if (!quotes.some((q) => q.id === state.selected)) state.selected = (best || lowest || { id: "" }).id;
    const selected = quotes.find((q) => q.id === state.selected) || null;
    const animate = drawn !== m.model; drawn = m.model;

    replace("quotes-callout", headline(m, quotes, lowest, best, basis));
    const Q = window.QuotesCharts || {};
    const premium = (q) => (lowest && q.risk_adjusted !== null && lowest.price ? pct(q.risk_adjusted / lowest.price - 1, 1, true) : null);
    /* A chart is only redrawn when what it shows has changed: the same book arriving again (a refresh, or the read that follows opening the page)
       leaves it alone, so its entrance, its tooltip and its focus are not cut short. */
    const stamp = (rows) => rows.map((q) => [q.id, q.price, q.risk_adjusted, q.eligible ? 1 : 0, q.grade, q.reason_codes.join(",")].join(":")).join("|");
    if (Q.ladder) {
      const width = D.fit("quotes-ladder", 760); const key = [m.model, width, state.selected, lowest ? lowest.id : "", best ? best.id : "", basis, stamp(quotes)].join("#");
      if (memo.ladderKey !== key) {
        const result = Q.ladder({ quotes, model: m.model, lowestId: lowest ? lowest.id : "", bestId: best ? best.id : "", selectedId: state.selected, width, animate, basisText: basis === null ? "" : pct(basis, 1, true), premium, onSelect: (id) => select(id, { reveal: true }), onHover: (id) => { hoverId = id; } });
        replace("quotes-ladder", result.node); memo.ladderKey = key; memo.marks = result.marks; if (hoverId) result.reveal(hoverId);
      }
      memo.marks.forEach((node, id) => focusables.set("mark:" + id, node));
    }
    if (Q.reasons) {
      const width = D.fit("quotes-reasons", 380); const key = [m.model, width, lowest ? lowest.id : "", stamp(quotes)].join("#");
      if (memo.reasonsKey !== key) {
        const names = new Map(); quotes.forEach((q) => q.reason_codes.forEach((code, i) => names.set(code, q.reasons[i] || humanise(code))));
        replace("quotes-reasons", Q.reasons({ quotes, model: m.model, width, lowest, animate, name: (code) => names.get(code) || humanise(code) }).node); memo.reasonsKey = key;
      }
      const ineligible = quotes.length - eligibleCount; const alone = quotes.filter((q) => !q.eligible && q.reason_codes.length === 1 && q.reason_codes[0] === "contract_start_precedes_as_of").length;
      text("quotes-reasons-note", ineligible ? "Of " + quotes.length + " quotes, " + eligibleCount + " are eligible. A quote can fail more than one check, so the reasons add up to more than " + ineligible + "." + (alone ? " " + alone + " fail only because the contract start has passed." : "") : "All " + quotes.length + " quotes are eligible.");
    }
    if (selected) { renderTable(m.model, quotes, selected, lowest, best); renderDetail(selected, data, m, lowest, best, eligibleCount); } else { replace("quotes-table"); replace("quotes-detail", empty("Select a quote to see its cost, seller scorecard and terms.")); }
    if (revealNext && selected) revealRow(selected.id); revealNext = false;
    refocus(wanted);
  }
  ["allin", "price"].forEach((key) => byId("sort-" + key).addEventListener("click", () => { state.sort = key; renderQuotes(); }));
  D.register("quotes", { render: () => renderQuotes(), resize: true });
})();
