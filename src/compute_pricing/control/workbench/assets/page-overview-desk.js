/* Overview: the desk's own book. What it holds (positions) and the bids it brokered, joined to the sites and to the quote book.
   Money is printed from the server's exact strings (`.exact`); the numbers beside them only size the marks. Nothing here prices anything. */
(() => {
  "use strict";
  const D = window.ComputeDemo; const C = window.OverviewCharts; if (!D || !C) return;
  const { h, int, pct, replace, empty, chip, MONTHS } = D;

  /* ---- printing ---- */
  const DECIMAL = /^-?\d+(?:\.\d+)?$/;
  const grouped = (digits) => digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  /* "-31840.12" -> "−$31,840.12": the server's digits, with separators and a real minus sign. Nothing is rounded. */
  function money(exact, { sign = false } = {}) {
    if (typeof exact !== "string" || !DECIMAL.test(exact)) return "—";
    const negative = exact.startsWith("-"); const [whole, fraction] = exact.replace("-", "").split("."); const zero = /^0*$/.test(whole) && /^0*$/.test(fraction || "");
    return (negative && !zero ? "−" : sign && !zero ? "+" : "") + "$" + grouped(whole) + (fraction ? "." + fraction : "");
  }
  /* A figure of a row: its exact string when the adapter kept one, else the number at the given places. */
  const printed = (row, name, places, options) => (row.exact && typeof row.exact[name] === "string" ? money(row.exact[name], options) : C.finite(row[name]) ? money(row[name].toFixed(places), options) : "—");
  const day = (iso) => { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || ""); return m ? MONTHS[Number(m[2]) - 1] + " " + Number(m[3]) : ""; };
  const place = (site) => (site ? site.place + (site.country && site.country !== "US" ? ", " + site.country : "") : "");
  const th = (label, className = "", unit = "") => { const cell = h("th", className, label, unit ? h("span", "ov-unit", unit) : null); cell.scope = "col"; return cell; };
  const scroller = (label, table) => { const box = h("div", "ov-scroll", table); box.tabIndex = 0; box.setAttribute("role", "region"); box.setAttribute("aria-label", label); return box; };
  /* Below the table breakpoint a row becomes a small card; each cell then names itself through data-label (see overview.css). */
  const labelled = (row, names) => { Array.from(row.children).forEach((cell, i) => { if (names[i]) cell.setAttribute("data-label", names[i]); }); return row; };
  const seller = (name, grade) => h("span", "ov-seller", grade && grade !== "U" ? chip(grade) : h("span", "ov-unrated", "Not rated"), h("span", "ov-seller-name", name || "Unknown seller"));

  /* Why there is nothing to show: still reading, or the server could not give the ledger. The market is unaffected either way. */
  function absent(state, what) {
    return state.deskError
      ? h("div", "ov-absent", h("strong", "", "The desk ledger is unavailable"), h("p", "", what + " come from the desk ledger, which the server did not provide. The market below is unaffected."), h("p", "ov-absent-why", state.deskError))
      : h("div", "ov-absent", h("p", "", "Reading the desk ledger…"));
  }

  const POSITION_LABELS = ["", "Held at", "Term", "GPUs", "Contract", "Mark", "Unrealized difference"];
  const BID_LABELS = ["", "Seller", "GPUs", "Ask", "Bid", "Quote now", "Outcome", "Position"];

  /* ---- Positions ---- */
  function renderPositions(ctx) {
    const { state } = D; const desk = state.desk;
    if (!desk) { replace("desk-positions", absent(state, "Positions")); D.text("desk-positions-lede", "Capacity the desk holds under contract, set against the market."); return; }
    D.text("desk-positions-lede", "Capacity the desk holds under contract, with each contract price against the book's current mark. Prices are dollars per GPU-hour.");
    if (!desk.positions.length) { replace("desk-positions", h("div", "ov-absent", h("p", "", "The desk holds no positions in this ledger."))); return; }
    const sites = new Map(desk.sites.map((site) => [site.id, site]));
    const values = desk.positions.map((p) => p.unrealized_usd).filter(C.finite); const low = Math.min(0, ...values); const high = Math.max(0, ...values);
    const body = h("tbody");
    desk.positions.forEach((p, index) => {
      const site = sites.get(p.site_id); const unrealized = printed(p, "unrealized_usd", 2, { sign: true });
      const gap = C.finite(p.unrealized_usd) ? C.signedBar({ value: p.unrealized_usd, low, high, width: 112, title: unrealized + " unrealized, " + p.id }) : null;
      body.append(labelled(h("tr", "ov-r" + Math.min(index + 1, 8),
        h("th", "ov-first", h("span", "ov-model", p.model), h("span", "ov-id", p.id)),
        h("td", "", site ? h("div", "ov-two", h("span", "ov-place", place(site)), seller(site.provider, site.grade)) : h("span", "ov-unrated", "Site not in the ledger")),
        h("td", "", h("div", "ov-two", h("span", "ov-state " + (p.status === "active" ? "is-active" : "is-upcoming"), h("i", "ov-pip"), p.status === "active" ? "Active" : "Upcoming"), h("span", "ov-dates", p.start + " to " + p.end))),
        h("td", "ov-n", int(p.gpus)), h("td", "ov-n", printed(p, "price", 4)), h("td", "ov-n", p.mark === null ? h("span", "ov-unrated", "No mark") : printed(p, "mark", 4)),
        h("td", "ov-n ov-diff", gap, h("span", "ov-diff-value", unrealized))), POSITION_LABELS));
    });
    const s = desk.summary; const total = s.unrealized_usd === null ? "—" : money(s.exact.unrealized_usd, { sign: true });
    const foot = h("tfoot", "", labelled(h("tr", "", h("th", "ov-first", "All positions", h("span", "ov-id", String(desk.positions.length))), h("td", ""), h("td", ""), h("td", "ov-n", int(s.position_gpus)), h("td", ""), h("td", ""), h("td", "ov-n ov-diff", h("span", "ov-diff-value", total))), POSITION_LABELS));
    const table = h("table", "ov-table ov-card ov-positions" + (ctx.enter("positions") ? " ov-in" : ""), h("caption", "sr-only", "Positions the desk holds, with contract price, mark and unrealized difference"),
      h("thead", "", h("tr", "", th("Position", "ov-first"), th("Held at"), th("Term"), th("GPUs", "ov-n"), th("Contract", "ov-n", "$ per GPU-hour"), th("Mark", "ov-n", "$ per GPU-hour"), th("Unrealized difference", "ov-n ov-diff", "$"))), body, foot);
    replace("desk-positions", scroller("Positions; scroll to see every column", table),
      h("p", "ov-footnote", "Notional " + money(s.exact.position_notional_usd) + " is contract price × GPUs × contract hours. The mark is the book's current best eligible all-in cost for the model. Unrealized difference is the server's figure, (mark − contract price) × GPUs × remaining contract hours" + (s.unrealized_usd === null ? "; it is blank while any model has no mark." : ".")));
  }

  /* ---- Bids ---- */
  const STATUS = [["open", "Open", "ov-fill-a", true], ["filled", "Filled", "ov-fill-a", false], ["declined", "Declined", "ov-fill-n", false], ["expired", "Expired", "ov-fill-n", true]];
  const sumGpus = (rows) => rows.reduce((total, row) => total + (Number.isFinite(row.gpus) ? row.gpus : 0), 0);

  function renderBidSummary(desk, ctx) {
    const slot = "desk-bid-fill"; const chart = "desk-bid-status";
    D.byId("desk-bid-top").hidden = !desk || !desk.bids.length;  // without a ledger, or without bids, one message stands in for the summary and the table
    if (!desk || !desk.bids.length) { replace(slot); replace(chart); return; }
    const by = (status) => desk.bids.filter((bid) => bid.status === status); const decided = by("filled").length + by("declined").length + by("expired").length;
    const rate = desk.summary.fill_rate;
    replace(slot, h("p", "ov-figure", rate === null ? "—" : pct(rate, 0)), h("p", "ov-figure-note", rate === null ? "No bid has been decided yet." : by("filled").length + " of " + decided + " decided bids were filled."),
      h("p", "ov-figure-note", by("open").length ? by("open").length + " open " + (by("open").length === 1 ? "bid is" : "bids are") + " not counted until " + (by("open").length === 1 ? "it is" : "they are") + " decided." : "No bids are open."));
    const rows = STATUS.map(([key, name, className, hollow]) => { const list = by(key); return { label: name, value: list.length, className, hollow, text: list.length + (list.length === 1 ? " bid, " : " bids, ") + int(sumGpus(list)) + " GPUs", title: name + ": " + list.length + " bids, " + int(sumGpus(list)) + " GPUs" }; });
    const width = D.fit(chart, 520);
    replace(chart, C.hbars({ rows, width, enter: ctx.enter("bid-status"), labelWidth: 88, valueWidth: 150, rowHeight: 34, description: "Bids by outcome: " + rows.map((r) => r.label + " " + r.text).join("; ") + "." }),
      C.twin("Bids by outcome", ["Outcome", "Bids", "GPUs"], STATUS.map(([key, name]) => [name, by(key).length, sumGpus(by(key))])));
  }

  function renderBids(ctx) {
    const { state } = D; const desk = state.desk; renderBidSummary(desk, ctx);
    if (!desk) { replace("desk-bids", absent(state, "Bids")); D.text("desk-bids-lede", "Bids the desk placed with sellers on behalf of buyers."); return; }
    D.text("desk-bids-lede", "Bids the desk placed with sellers on behalf of buyers, each against a quote in the book. Fill rate counts filled bids over decided bids; open bids are left out.");
    if (!desk.bids.length) { replace("desk-bids", h("div", "ov-absent", h("p", "", "No bids brokered yet."))); return; }
    const sites = new Map(desk.sites.map((site) => [site.id, site])); const quotes = new Map(state.data.quotes.map((quote) => [quote.id, quote]));
    const ordered = desk.bids.slice().sort((a, b) => String(b.placed).localeCompare(String(a.placed)) || String(a.id).localeCompare(String(b.id)));
    const body = h("tbody");
    ordered.forEach((bid, index) => {
      const site = sites.get(bid.site_id); const quote = quotes.get(bid.quote_id); const known = STATUS.find(([key]) => key === bid.status);
      const name = (site && site.provider) || (quote && quote.provider) || ""; const grade = site ? site.grade : quote ? quote.grade : "U";
      const row = labelled(h("tr", "ov-r" + Math.min(index + 1, 8), h("th", "ov-first", h("span", "ov-model", bid.model), h("span", "ov-id", bid.id)),
        h("td", "", seller(name, grade)), h("td", "ov-n", int(bid.gpus)), h("td", "ov-n", printed(bid, "ask", 4)), h("td", "ov-n ov-strong", printed(bid, "bid", 4)),
        h("td", "ov-n", quote ? (C.finite(quote.price) ? C.money(quote.price, 4) : "—") : h("span", "ov-unrated", "Not in book")),
        h("td", "", h("span", "ov-state is-" + bid.status, h("i", "ov-pip"), known ? known[1] : String(bid.status)), h("span", "ov-dates", bid.decided ? day(bid.decided) : "since " + day(bid.placed))),
        h("td", "", bid.position_id ? h("span", "ov-link-id", bid.position_id) : h("span", "ov-unrated", "—"))), BID_LABELS);
      row.setAttribute("title", bid.id + (site ? " at " + place(site) : "") + (quote ? ", quote " + quote.ref : ", quote no longer in the book"));
      body.append(row);
    });
    const table = h("table", "ov-table ov-card ov-bids" + (ctx.enter("bids") ? " ov-in" : ""), h("caption", "sr-only", "Bids the desk brokered, newest first, with ask, bid, the quote's price now, outcome and the position a filled bid became"),
      h("thead", "", h("tr", "", th("Bid", "ov-first"), th("Seller"), th("GPUs", "ov-n"), th("Ask", "ov-n", "$ per GPU-hour"), th("Bid", "ov-n", "$ per GPU-hour"), th("Quote now", "ov-n", "$ per GPU-hour"), th("Outcome"), th("Position"))), body);
    replace("desk-bids", scroller("Bids, newest first; scroll to see every column", table));
  }

  window.OverviewDesk = Object.freeze({ renderPositions, renderBids, money, printed, day });
})();
