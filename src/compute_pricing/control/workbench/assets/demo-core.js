/* The shared core of the Brief, Overview and Quotes views: one polled, normalised book, the helpers every page draws with, the
   scenario controls and the page registry. The server owns every number (/v1/book); the pages only draw it.
   A page file calls ComputeDemo.register(name, { render, resize }) and reads what it needs from window.ComputeDemo. */
(() => {
  "use strict";
  const host = window.ComputeHost; const charts = window.ComputeCharts;
  if (!host || !charts) return;
  const { api, byId, notify } = host;
  const GRADES = ["A", "B", "C", "D"];
  const POLL_MS = 2000;
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const FIELD_NAMES = { location: "Location", country: "Country", moq: "Minimum order", interconnect: "Interconnect", cooling: "Cooling", lead_weeks: "Lead time", months: "Term", down_payment: "Down payment", payment_days: "Payment terms", expires: "Expiry" };
  const CATEGORIES = { certification: "Certification", dc_tier: "Facility tier", sla: "SLA and uptime", delivery: "Delivery record", credit: "Counterparty credit", responsiveness: "Responsiveness" };
  const SCENARIOS = [["price_war", "Price war"], ["supply_shock", "Supply shock"], ["downgrade", "Provider downgrade"]];
  const SCENARIO_DETAIL = { price_war: "Weaker sellers undercut B300", supply_shock: "Large H200 offers withdrawn", downgrade: "The largest grade A seller loses its standing" };

  const state = { data: null, tag: "", model: "B300", view: "brief", sort: "allin", selected: "", showAll: false, inflight: false, lastAlert: null, flash: new Set(), fresh: new Set(), epoch: null, kpi: new Map(), error: "", busy: false, timer: null, desk: null, deskTag: "", deskError: "", deskInflight: false };

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
      const raw = await api("/v1/book", {}, meta);
      state.error = "";
      const data = raw ? window.BookAdapter.normalizeBook(raw) : null;
      if (raw && !data) throw new Error("The server sent something other than a quote book.");
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
    if (state.view === "desk") pollDesk(force);
  }
  /* The desk ledger (positions, brokered bids, sites) is only read while the Overview is open. If it cannot be read the market still draws. */
  async function pollDesk(force = false) {
    if (state.deskInflight || !host.isSession()) return;
    state.deskInflight = true; const meta = { ifNoneMatch: force ? "" : state.deskTag };
    try {
      const raw = await api("/v1/book/desk", {}, meta); state.deskError = "";
      if (raw) {
        const desk = window.BookAdapter.normalizeDesk(raw);
        if (!desk) throw new Error("The server sent something other than a desk ledger.");
        state.desk = desk; state.deskTag = meta.etag || ""; render();
      }
    } catch (error) { state.deskError = error.message; if (!state.desk) render(); }
    finally { state.deskInflight = false; }
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
  /* The feed keeps only the latest alerts, so a scenario is remembered here until its tick leaves the chart window. */
  const scenarioSeen = new Map(); let scenarioEpoch = null;
  function rememberScenarios() {
    const data = state.data; if (!data) return;
    if (scenarioEpoch !== data.meta.epoch) { scenarioEpoch = data.meta.epoch; scenarioSeen.clear(); }
    data.alerts.forEach((a) => { if (a.kind === "scenario") scenarioSeen.set(a.n, a); });
    [...scenarioSeen].forEach(([n, a]) => { if (!data.series.ticks.includes(a.tick)) scenarioSeen.delete(n); });
  }

  /* ---- pages and orchestration ---- */
  const pages = new Map();
  function render() {
    pages.get(state.view)?.render();
    state.flash = new Set(); state.fresh = new Set();  // a change is highlighted once, then left alone
  }
  function register(name, page) { pages.set(name, page); if (state.view === name) page.render(); }
  host.onView((name) => { state.view = name; if (pages.has(name)) { paintControls(); render(); poll(true); } });
  host.onSession((connected) => {
    if (!connected) { state.data = null; state.tag = ""; state.desk = null; state.deskTag = ""; state.deskError = ""; state.lastAlert = null; state.kpi.clear(); state.error = ""; render(); return; }
    paintControls(); poll(true);
  });
  let resizeTimer = null;
  window.addEventListener?.("resize", () => { if (!live() || !pages.get(state.view)?.resize) return; clearTimeout(resizeTimer); resizeTimer = setTimeout(render, 150); });
  setInterval(() => poll(false), POLL_MS);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(true); });
  paintControls();

  window.ComputeDemo = Object.freeze({ host, charts, state, h, num, int, usd, pct, compact, clock, gradeClass, chip, replace, empty, live, fit, median, modelTabs, text, legendGrades, lowestPrice, headline, paintControls, poll, GRADES, FIELD_NAMES, CATEGORIES, notify, byId, SCENARIOS, MONTHS, scenarioSeen, scenarioReady: () => rememberScenarios(), pollDesk, register, render });
})();
