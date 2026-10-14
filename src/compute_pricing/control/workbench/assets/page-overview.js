/* The Overview: what the desk holds, the bids it brokered, the state of the simulated market and where capacity can be had.
   This file draws the header, the key figures and the capacity map, and hands each section to its module:
   page-overview-desk.js (positions, bids), page-overview-market.js (market panels), page-overview-charts.js (chart primitives).
   Those load after this file, so they are looked up when a render runs, never at load. */
(() => {
  "use strict";
  const D = window.ComputeDemo; if (!D) return;
  const { state, h, int, pct, compact, replace, empty, live, text, byId } = D;

  /* A section animates only for its first second on screen. A redraw inside that second restarts the entrance rather than cutting it
     short (the book and the ledger arrive a moment apart); after it, polls and resizes redraw without motion. */
  const born = new Map(); const ENTRANCE_MS = 1000;
  function enter(key) { const now = Date.now(); if (!born.has(key)) born.set(key, now); return now - born.get(key) < ENTRANCE_MS; }
  const ctx = Object.freeze({ enter });

  const stamp = (iso) => { const m = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(iso || ""); return m ? m[1] + " " + m[2] + " UTC" : ""; };

  /* ---- Key figures ---- */
  /* Change in a market series over the readings the book holds (at most 48), named in minutes of simulated time. Nothing is shown without history. */
  function change(values, kind) {
    const ticks = state.data.series.ticks || []; const series = values.map((v) => (Number.isFinite(v) ? v : null)); const last = series.length - 1;
    if (last < 1 || series[last] === null) return null;
    let from = Math.max(0, last - 48); while (from < last && series[from] === null) from += 1; if (from >= last) return null;
    const minutes = Math.round(((ticks[last] ?? last) - (ticks[from] ?? from)) * (state.data.meta.step_minutes || 1)); if (minutes < 1) return null;
    const diff = series[last] - series[from]; const shown = kind === "pp" ? Math.abs(diff * 100).toFixed(1) : int(Math.abs(diff)); if (Number(shown) === 0) return null;
    return (diff > 0 ? "+" : "−") + shown + (kind === "pp" ? " pt" : "") + " in " + minutes + " min";
  }
  function money(value) {
    const size = Math.abs(value); const body = size >= 1e6 ? (size / 1e6).toFixed(2) + "M" : size >= 1e3 ? (size / 1e3).toFixed(1) + "k" : int(size);
    return (value < 0 ? "−" : value > 0 ? "+" : "") + "$" + body;
  }
  function renderKpis() {
    const data = state.data; const k = data.kpis; const s = data.series; const desk = state.desk; const sum = desk ? desk.summary : null; const none = state.deskError ? "Ledger unavailable" : "Reading the ledger";
    const money_ = (name) => window.OverviewDesk && sum ? window.OverviewDesk.money(sum.exact[name], { sign: true }) : "";
    const items = [
      { key: "held", label: "GPUs held", value: sum ? int(sum.position_gpus) : "—", sub: sum ? (sum.positions === 1 ? "in 1 position" : "in " + int(sum.positions) + " positions") : none },
      { key: "unrealized", label: "Unrealized difference", value: sum && sum.unrealized_usd !== null ? money(sum.unrealized_usd) : "—", title: sum && sum.unrealized_usd !== null ? money_("unrealized_usd") : "", sub: sum ? (sum.unrealized_usd === null ? "a model has no mark" : "against the book's current mark") : none },
      { key: "bids", label: "Bids brokered", value: sum ? int(sum.bids) : "—", sub: sum ? int(sum.bids_open) + " open" + (sum.fill_rate === null ? "" : ", " + pct(sum.fill_rate, 0) + " of decided filled") : none },
      { key: "quotes", label: "Live quotes", value: int(k.live_quotes), sub: "from " + k.providers_quoting + " of " + k.providers_total + " sellers", change: change(s.live || [], "n") },
      { key: "eligible", label: "Eligible quotes", value: int(k.eligible_quotes), sub: k.eligible_share === null ? "of the live quotes" : pct(k.eligible_share, 0) + " of live quotes", change: change(s.eligible_share || [], "pp") },
      { key: "basis", label: "Market basis", value: k.basis === null ? "—" : pct(k.basis, 1, true), sub: "best eligible all-in over lowest quote", change: change(s.basis || [], "pp") },
    ];
    const tiles = items.map((item) => {
      const before = state.kpi.get(item.key); const changed = before !== undefined && before !== "—" && before !== item.value; state.kpi.set(item.key, item.value);  // a figure that was only a placeholder is not a change
      const value = h("strong", "ov-kpi-value" + (changed ? " flash" : ""), item.value); if (item.title) value.setAttribute("title", item.title);
      return h("div", "ov-kpi", h("span", "ov-kpi-label", item.label), value, h("span", "ov-kpi-sub", item.sub), item.change ? h("span", "ov-kpi-change", item.change) : null);
    });
    const box = byId("desk-kpis"); box.classList.toggle("ov-in", enter("kpis")); replace("desk-kpis", tiles);
  }

  /* ---- Capacity map: the component owns everything inside #desk-map ---- */
  let map = null; let mapFailed = false;
  function renderCapacity() {
    const desk = state.desk; const host = byId("desk-map"); const note = byId("desk-map-note");
    if (!desk) {
      host.hidden = true; note.hidden = false; note.textContent = state.deskError ? "Site capacity comes from the desk ledger, which the server did not provide. The market above is unaffected." : "Reading the desk ledger…";
      text("desk-capacity-lede", "Where the book's GPUs sit, and where the desk is exposed."); return;
    }
    const s = desk.summary;
    text("desk-capacity-lede", (Number.isFinite(s.us_supply_gpus) && Number.isFinite(s.supply_gpus) && s.supply_gpus > 0 ? int(s.us_supply_gpus) + " of " + int(s.supply_gpus) + " quoted GPUs (" + pct(s.us_supply_share === undefined || s.us_supply_share === null ? s.us_supply_gpus / s.supply_gpus : Number(s.us_supply_share), 0) + ") are at sites in the US. " : "") + "Positions and open bids mark where the desk is already exposed. Sites sit on illustrative metros, not on real vendor locations.");
    if (!window.ComputeMap) { host.hidden = true; note.hidden = false; note.textContent = "The capacity map is not available in this build."; return; }
    host.hidden = false; note.hidden = true;
    try {
      if (!map && !mapFailed) map = window.ComputeMap.create(host);
      if (map) map.update({ sites: desk.sites, positions: desk.positions, bids: desk.bids });
    } catch (error) { mapFailed = true; map = null; host.hidden = true; note.hidden = false; note.textContent = "The capacity map could not be drawn."; }
  }

  /* ---- Page ---- */
  function renderDesk() {
    if (!live()) { replace("desk-kpis", empty(state.error || "Opening the simulated book…")); byId("desk-kpis").classList.remove("ov-in"); return; }
    const data = state.data; const D_ = window.OverviewDesk; const M = window.OverviewMarket; if (!D_ || !M) return;
    text("desk-clock", "Market time " + stamp(data.meta.time) + (data.meta.paused ? ", paused." : ", one simulated minute every " + (data.meta.tick_seconds || 3) + " seconds."));
    text("desk-market-lede", int(data.kpis.live_quotes) + " live quotes from " + data.kpis.providers_quoting + " of " + data.kpis.providers_total + " sellers, " + int(data.kpis.eligible_quotes) + " of them eligible to rank. Prices are dollars per GPU-hour.");
    renderKpis(); D_.renderPositions(ctx); D_.renderBids(ctx);
    M.renderBasis(ctx); M.renderTrend(ctx); M.renderSupply(ctx); M.renderReasons(ctx); M.renderProviders(); M.renderActivity();
    renderCapacity();
  }

  D.register("desk", { render: renderDesk, resize: true });
})();
