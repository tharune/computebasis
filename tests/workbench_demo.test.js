"use strict";
// Draw the shipped chart and Brief/Overview/Quotes modules against snapshots produced by the real
// simulator, in a browserless DOM. The fake DOM throws on innerHTML and inline styles, as the CSP would.
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const assets = process.env.COMPUTEBASIS_WORKBENCH_ASSETS;
const snapshotFile = process.env.COMPUTEBASIS_BOOK_SNAPSHOTS;
assert.ok(assets, "COMPUTEBASIS_WORKBENCH_ASSETS must point to the checked-out workbench assets");
assert.ok(snapshotFile, "COMPUTEBASIS_BOOK_SNAPSHOTS must point to simulator snapshots (see tests/test_workbench_demo_js_v10.py)");
const snapshots = JSON.parse(fs.readFileSync(snapshotFile, "utf8"));
const html = fs.readFileSync(path.join(assets, "index.html"), "utf8");
const chartsSource = fs.readFileSync(path.join(assets, "workbench-charts.js"), "utf8");
const demoSource = fs.readFileSync(path.join(assets, "workbench-demo.js"), "utf8");

class El {
  constructor(tag) {
    this.tagName = tag; this.children = []; this.attributes = {}; this.listeners = new Map(); this.className = "";
    this.disabled = false; this.hidden = false; this.dataset = {}; this._text = "";
    this.classList = { add: (name) => this.setClass(name, true), remove: (name) => this.setClass(name, false), contains: (name) => this.has(name), toggle: (name, flag) => this.setClass(name, flag === undefined ? !this.has(name) : flag) };
  }
  has(name) { return this.className.split(/\s+/).includes(name); }
  setClass(name, on) { const set = new Set(this.className.split(/\s+/).filter(Boolean)); if (on) set.add(name); else set.delete(name); this.className = [...set].join(" "); }
  get style() { throw new Error("Inline styles are blocked by the content security policy"); }
  get innerHTML() { throw new Error("innerHTML is not allowed"); }
  set innerHTML(_) { throw new Error("innerHTML is not allowed"); }
  get textContent() { return this._text + this.children.map((child) => child.textContent).join(""); }
  set textContent(value) { this._text = String(value); this.children = []; }
  append(...nodes) { nodes.forEach((node) => { assert.ok(node instanceof El, "append expects DOM nodes"); this.children.push(node); }); }
  replaceChildren(...nodes) { this.children = []; this._text = ""; this.append(...nodes); }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  getAttribute(key) { return this.attributes[key] ?? null; }
  removeAttribute(key) { delete this.attributes[key]; }
  addEventListener(name, action) { this.listeners.set(name, [...(this.listeners.get(name) || []), action]); }
  async click() { if (this.disabled) return; await Promise.all((this.listeners.get("click") || []).map((action) => action({ preventDefault() {}, target: this }))); }
  focus() { this.focused = true; }
  scrollIntoView(options) { this.scrolled = options; }
}
const walk = (node, visit) => { visit(node); node.children.forEach((child) => walk(child, visit)); };
const findAll = (node, test) => { const out = []; walk(node, (item) => { if (test(item)) out.push(item); }); return out; };
const classes = (node) => `${node.className} ${node.attributes.class || ""}`.split(/\s+/);
const byClass = (node, name) => findAll(node, (item) => classes(item).includes(name));
const byTag = (node, tag) => findAll(node, (item) => item.tagName === tag);
const settle = async () => { for (let i = 0; i < 6; i++) await new Promise((resolve) => setImmediate(resolve)); };
const BROKEN = /\b(NaN|undefined|Infinity)\b|\[object/;
function assertClean(node, label = "chart") {
  walk(node, (item) => {
    for (const [key, value] of Object.entries(item.attributes)) assert.doesNotMatch(value, BROKEN, `${label}: attribute ${key} on <${item.tagName}> is "${value}"`);
    if (item._text) assert.doesNotMatch(item._text, BROKEN, `${label}: text "${item._text}"`);
  });
}

function makePage(initial, { priceQuote } = {}) {
  const ids = new Map();
  for (const tag of html.matchAll(/<([a-z][a-z0-9]*)\b([^>]*)>/g)) {
    const id = /\bid="([^"]+)"/.exec(tag[2]); if (id) ids.set(id[1], new El(tag[1]));
  }
  const server = { snapshot: initial, tag: 'W/"one"', session: true, failure: "", gate: null, posts: [] };
  const calls = []; const notices = []; const shown = []; const priced = [];
  const viewListeners = []; const sessionListeners = []; const intervals = []; const documentListeners = [];
  const doc = {
    hidden: false,
    createElement: (tag) => new El(tag), createElementNS: (_, tag) => new El(tag),
    createTextNode: (text) => { const node = new El("#text"); node._text = String(text); return node; },
    addEventListener: (name, action) => documentListeners.push({ name, action }),
  };
  const host = {
    api: async (url, options = {}, meta) => {
      calls.push({ url, method: options.method || "GET", ifNoneMatch: meta?.ifNoneMatch || "" });
      if (url === "/v1/book/control") { server.posts.push(JSON.parse(options.body)); if (server.gate) await server.gate; return { simulated: true }; }
      assert.equal(url, "/v1/book", "unexpected request " + url);
      if (server.failure) throw new Error(server.failure);
      if (meta?.ifNoneMatch && meta.ifNoneMatch === server.tag) { meta.status = 304; return null; }
      meta.status = 200; meta.etag = server.tag; return structuredClone(server.snapshot);
    },
    byId: (id) => { assert.ok(ids.has(id), "Missing DOM element " + id); return ids.get(id); },
    notify: (message, error = false) => notices.push({ message, error }),
    showView: (name) => { shown.push(name); viewListeners.forEach((listener) => listener(name)); },
    isSession: () => server.session,
    onView: (listener) => viewListeners.push(listener), onSession: (listener) => sessionListeners.push(listener),
    ...(priceQuote ? { priceQuote: (quote) => { priced.push(quote); } } : {}),
  };
  const window = { ComputeHost: host };
  const context = vm.createContext({ window, document: doc, setInterval: (fn, ms) => intervals.push({ fn, ms }), console });
  vm.runInContext(chartsSource, context, { filename: "workbench-charts.js" });
  vm.runInContext(demoSource, context, { filename: "workbench-demo.js" });
  const el = (id) => host.byId(id);
  const button = (id, label) => findAll(el(id), (item) => item.tagName === "button" && item.textContent === label)[0];
  return {
    server, calls, notices, shown, priced, host, el, button, doc, charts: window.ComputeCharts,
    connect: () => sessionListeners.forEach((listener) => listener(true)),
    disconnect: () => sessionListeners.forEach((listener) => listener(false)),
    poll: () => intervals.find((item) => item.ms === 2000).fn(),
    visibility: () => documentListeners.filter((item) => item.name === "visibilitychange").forEach((item) => item.action({})),
  };
}
const { base, war, reset } = snapshots;
const assertLive = (page) => { assert.equal(page.el("session-state").textContent, "Live"); assert.ok(page.el("session-dot").has("live")); };

test("snapshots come from the simulator and the scenario and reset change them", () => {
  assert.equal(base.simulated, true);
  assert.notEqual(base.kpis.basis, war.kpis.basis);
  assert.ok(war.alerts.some((alert) => alert.kind === "scenario"));
  assert.notEqual(war.meta.epoch, reset.meta.epoch);
});

test("ticks cover the range with round values", () => {
  const ticks = (...args) => [...makePage(base).charts.ticks(...args)];
  assert.deepEqual(ticks(0, 25, 4), [0, 10, 20]);
  assert.deepEqual(ticks(5, 5), [5]);
  const fine = ticks(4.1, 5.6, 4);
  assert.ok(fine.length >= 2 && fine.every((value, index) => index === 0 || value > fine[index - 1]) && fine[0] >= 4.1 && fine.at(-1) <= 5.6);
});

test("zero axes reach the first round tick above the longest bar without overshooting", () => {
  const { charts } = makePage(base);
  assert.deepEqual({ ...charts.zeroAxis(6.2, 7), ticks: [...charts.zeroAxis(6.2, 7).ticks] }, { top: 7, ticks: [0, 1, 2, 3, 4, 5, 6, 7] });
  assert.equal(charts.zeroAxis(5.55, 5).top, 6);
  assert.equal(charts.zeroAxis(0.294, 5).top, 0.3);
  assert.equal(charts.zeroAxis(53, 6).top, 60);
  assert.ok(charts.zeroAxis(0, 5).top > 0, "an empty axis still has a scale");
  [4.63, 5.55, 12, 0.07, 340].forEach((high) => { const axis = charts.zeroAxis(high, 6); assert.ok(axis.top >= high && axis.top < high * 2, "axis top " + axis.top + " for " + high); });
});

test("charts survive empty, single-point and missing data without NaN or undefined", () => {
  const { charts } = makePage(base);
  const plain = { className: "part" };
  const drawn = [
    charts.sparkline([]), charts.sparkline([3]), charts.sparkline([null, 2, null, 3, 4]), charts.sparkline([2, 2, 2]),
    charts.lineChart({ points: 0, series: [], description: "empty" }),
    charts.lineChart({ points: 3, series: [{ key: "a", name: "A", values: [null, null, null] }], description: "all missing" }),
    charts.lineChart({ points: 4, series: [{ key: "best", name: "Best", values: [5, null, 5.2, 5.1] }, { key: "low", name: "Low", values: [4, 4, 4, 4] }], gap: ["best", "low"], xLabel: (i) => "t" + i, markers: [{ index: 2, label: "Event" }, { index: 99, label: "off chart" }], description: "gappy" }),
    charts.lineChart({ points: 3, series: [{ key: "flat", name: "Flat", values: [2, 2, 2] }], description: "flat" }),
    charts.stackedBars({ rows: [{ label: "A", parts: [{ value: 0, ...plain }] }], description: "zero" }),
    charts.columns({ cols: [{ label: "0", parts: [{ value: 0, ...plain }] }], description: "zero columns" }),
    charts.bars({ rows: [{ label: "A", value: 0 }], description: "zero" }),
    charts.groupedBars({ rows: [{ label: "X", sub: "none", bars: [{ value: null, absent: "No eligible seller" }, { value: null }], trail: "—" }], description: "no values" }),
    charts.groupedBars({ rows: [{ label: "X", bars: [{ value: 4.6, grade: "D" }, { value: 5.5, grade: "A", text: "$5.500" }], trail: "+19%" }], format: (v) => "$" + v, description: "pair" }),
    charts.groupedColumns({ cols: [{ label: "A", sub: "0 quotes", bars: [{ value: null }, { value: null }] }], description: "no values" }),
    charts.groupedColumns({ cols: [{ label: "D", bars: [{ value: 0.1 }, { value: 0.22, text: "+22%" }] }], format: (v) => v + "%", description: "pair" }),
    charts.columns({ cols: [{ label: "0", parts: [{ value: 3, ...plain }] }], totals: true, description: "totals" }),
    charts.lineChart({ points: 6, series: [{ key: "a", name: "A", values: [1, 2, 3, 2, 3, 4] }], markers: [{ index: 1, label: "One" }, { index: 2, label: "Two overlapping" }, { index: 3, label: "Three overlapping", dim: true }, { index: 4, label: "Four overlapping" }, { index: 5, label: "Five at the edge" }], hover: (i) => "step " + i, marginRight: 52, endLabels: "value", description: "flags" }),
  ];
  drawn.forEach((chart, index) => { assert.equal(chart.tagName, "svg"); assertClean(chart, "chart " + index); });
  assert.match(drawn[4].textContent, /Waiting for history/);
  assert.equal(byTag(drawn[0], "path").length, 0);
  assert.equal(drawn[0].getAttribute("role"), null);
  assert.equal(drawn[8].getAttribute("role"), "img");
  assert.match(drawn[8].getAttribute("aria-label"), /zero/);
});


test("the first poll draws the Brief from the simulated book and marks the workspace live", async () => {
  const page = makePage(base);
  assert.equal(page.calls.length, 0);
  page.connect(); await settle();
  assert.deepEqual(page.calls, [{ url: "/v1/book", method: "GET", ifNoneMatch: "" }]);
  assertLive(page);
  const live = page.el("brief-live");
  assert.equal(byTag(live, "svg").length >= 1, true);
  base.models.forEach((entry) => assert.match(live.textContent, new RegExp(entry.model)));
  BRIEF_SLOTS.forEach((id) => { assertClean(page.el(id), id); assert.ok(page.el(id).children.length > 0, id + " is empty"); });
  assert.ok(page.el("brief-facts").textContent.length > 0);
});

const BRIEF_SLOTS = ["brief-live", "brief-facts", "brief-fact-gaps", "brief-gaps", "brief-fact-cost", "brief-anatomy", "brief-fact-grades", "brief-grades", "brief-weights", "brief-eligible", "brief-basis-live"];

test("the Brief states the problem with figures from the book and draws clean bars, not dumbbells", async () => {
  const page = makePage(base); page.connect(); await settle();
  const hero = page.el("brief-live");
  assert.equal(byClass(hero, "bf-bar").length, base.models.filter((entry) => entry.best).length, "one bar per model with an eligible seller");
  assert.match(hero.textContent, /No eligible seller/, "a model without an eligible seller says so instead of drawing a bar");
  assert.equal(byClass(page.el("brief-facts"), "bf-number").length, 4);
  assert.match(page.el("brief-facts").textContent, new RegExp(String(base.kpis.live_quotes)));
  assert.match(page.el("brief-fact-grades").textContent, new RegExp("of " + base.models.length));
  assert.equal(byClass(page.el("brief-gaps"), "bf-bar").length, 5, "the five most often omitted terms");
  const anatomy = page.el("brief-anatomy"); const stack = byClass(anatomy, "bf-bar-group")[1];
  assert.equal(byClass(stack, "bf-bar").length, 3, "the all-in bar stacks price, financing and expected loss");
  assert.match(anatomy.textContent, /Quoted/); assert.match(anatomy.textContent, /All-in/);
  assert.match(page.el("brief-fact-cost").textContent, /^\+\d+%Quote Q\d+/);
  assert.equal(byClass(page.el("brief-weights"), "bf-bar").length, 6, "six scorecard weights");
});

test("the Brief copes with a book that has no eligible seller and no priced quote", async () => {
  const bare = structuredClone(base);
  bare.models.forEach((entry) => { entry.best = null; entry.basis = null; });
  Object.assign(bare.kpis, { basis: null, eligible_quotes: 0, eligible_share: 0 });
  bare.quotes.forEach((quote) => { quote.risk_adjusted = null; quote.financing = null; quote.exposure = null; quote.eligible = false; });
  const page = makePage(bare); page.connect(); await settle();
  BRIEF_SLOTS.forEach((id) => assertClean(page.el(id), id));
  assert.equal(byClass(page.el("brief-live"), "bf-bar").length, 0);
  assert.match(page.el("brief-live").textContent, /No eligible seller/);
  assert.match(page.el("brief-anatomy").textContent, /No comparison available/);
  assert.equal(page.el("brief-basis-live").children.length, 0);
});

test("Brief buttons open the Overview and Quotes, and See the problem scrolls to the problem section", async () => {
  const page = makePage(base); page.connect(); await settle();
  await page.el("brief-open-desk").click(); await page.el("brief-open-desk-end").click(); await page.el("brief-open-quotes").click();
  assert.deepEqual(page.shown, ["desk", "desk", "quotes"]);
  await page.el("brief-see-problem").click();
  assert.equal(page.el("brief-problem").scrolled.block, "start");
  assert.equal(page.el("brief-problem").scrolled.behavior, "smooth");
  assert.ok(page.el("brief-problem-title").focused, "focus follows the scroll for keyboard users");
});

test("controls stay locked until the book arrives, then unlock", async () => {
  const page = makePage(base); page.host.showView("desk");
  const buttons = () => findAll(page.el("desk-controls"), (node) => node.tagName === "button");
  assert.ok(buttons().length >= 5 && buttons().every((node) => node.disabled));
  page.connect(); await settle();
  assert.ok(buttons().every((node) => !node.disabled));
});

test("an unchanged book is answered 304 and the drawn page is left alone", async () => {
  const page = makePage(base); page.connect(); await settle();
  const drawn = page.el("brief-live").children[0];
  page.poll(); await settle();
  assert.deepEqual(page.calls.at(-1), { url: "/v1/book", method: "GET", ifNoneMatch: 'W/"one"' });
  assert.equal(page.el("brief-live").children[0], drawn);
  assertLive(page);
});

test("a changed book redraws the Overview and highlights only what moved", async () => {
  const page = makePage(base); page.connect(); await settle();
  page.host.showView("desk"); await settle();
  const kpis = page.el("desk-kpis");
  assert.equal(byClass(kpis, "kpi").length, 6);
  assert.equal(byClass(kpis, "flash").length, 0, "nothing flashes on first paint");
  assert.match(kpis.textContent, new RegExp((base.kpis.basis * 100).toFixed(1) + "%"));
  assert.equal(byClass(page.el("desk-basis"), "ch-part").length, base.models.reduce((count, entry) => count + 1 + (entry.best ? 1 : 0), 0), "a bar for each model's lowest quote and one for its best eligible quote");
  ["desk-kpis", "desk-basis", "desk-trend", "desk-supply", "desk-completeness", "desk-grades", "desk-providers", "desk-activity", "desk-expiry"].forEach((id) => { assertClean(page.el(id), id); assert.ok(page.el(id).children.length > 0, id + " is empty"); });
  page.server.snapshot = war; page.server.tag = 'W/"two"';
  page.poll(); await settle();
  assert.match(kpis.textContent, new RegExp((war.kpis.basis * 100).toFixed(1) + "%"));
  assert.ok(byClass(kpis, "flash").length > 0, "changed figures are highlighted");
  assert.ok(byClass(page.el("desk-trend"), "ch-marker-label").some((node) => /price war/i.test(node.textContent)), "the scenario is annotated on the chart");
  assert.ok(byClass(page.el("desk-activity"), "flash").length > 0, "new events are highlighted");
});

test("the Overview basis bars carry the book's own numbers, and a model with no eligible seller says so", async () => {
  const page = makePage(base); page.connect(); await settle(); page.host.showView("desk"); await settle();
  const basis = page.el("desk-basis");
  const labels = byClass(basis, "ch-value").map((node) => node.textContent); const trails = byClass(basis, "ch-trail").map((node) => node.textContent);
  assert.equal(trails.length, base.models.length);
  base.models.forEach((entry, index) => {
    assert.ok(labels.includes("$" + Number(entry.cheapest.price).toFixed(2)), entry.model + " lowest quote is labelled");
    if (entry.best) { assert.ok(labels.includes("$" + entry.best.risk_adjusted.toFixed(3)), entry.model + " best eligible all-in is labelled"); assert.equal(trails[index], "+" + (entry.basis * 100).toFixed(1) + "%"); }
    else assert.equal(trails[index], "—");
  });
  assert.ok(base.models.some((entry) => !entry.best), "the starting book has a model with no eligible seller");
  assert.match(basis.textContent, /No eligible seller/);
  const bars = byClass(basis, "ch-part"); assert.ok(bars.every((bar) => Number(bar.attributes.width) > 0 && Number(bar.attributes.x) >= 0), "bars start at the zero line");
  assert.equal(page.el("desk-grades").textContent.includes("Grade D looks"), true, "the grade chart explains the gap in words");
});

test("the Overview price chart flags each scenario and names the market a flag belongs to", async () => {
  const page = makePage(war); page.connect(); await settle(); page.host.showView("desk"); await settle();
  const flags = byClass(page.el("desk-trend"), "ch-marker-label"); assert.ok(flags.some((node) => /^Price war/.test(node.textContent)));
  page.server.snapshot = { ...war, alerts: war.alerts.filter((alert) => alert.kind !== "scenario") }; page.server.tag = 'W/"quiet"'; page.poll(); await settle();
  assert.ok(byClass(page.el("desk-trend"), "ch-marker-label").some((node) => /^Price war/.test(node.textContent)), "a flag stays on the chart after the feed has moved past its alert");
  const other = page.el("desk-model-tabs").children.find((button) => button.dataset.model !== "B300"); await other.click(); await settle();
  const faint = byClass(page.el("desk-trend"), "ch-marker-label").filter((node) => classes(node).includes("dim"));
  assert.ok(faint.some((node) => /Price war · B300/.test(node.textContent)), "a flag for another model is faint and names that model");
  assert.equal(page.el("desk-model-tabs").children.length, base.models.length);
});

test("a reset removes the scenario flags it leaves behind on the Overview price chart", async () => {
  const page = makePage(war); page.connect(); await settle(); page.host.showView("desk"); await settle();
  const flags = () => byClass(page.el("desk-trend"), "ch-marker-label").filter((node) => /^Price war/.test(node.textContent));
  assert.ok(flags().length > 0, "the price war is flagged before the reset");
  // The reset book keeps the earlier clock ticks on its axis, so only the epoch change can clear the flag.
  const sameAxis = { ...reset, series: { ...reset.series, ticks: war.series.ticks }, meta: { ...reset.meta } };
  page.server.snapshot = sameAxis; page.server.tag = 'W/"reset"'; page.poll(); await settle();
  assert.equal(flags().length, 0, "a flag from before the reset must not outlive it");
});

test("the Quotes cost bars print every component and the all-in total straight from the quote", async () => {
  const page = makePage(base); page.connect(); await settle(); page.host.showView("quotes"); await settle();
  const b300 = base.models.find((entry) => entry.model === "B300"); const best = base.quotes.find((quote) => quote.id === b300.best.id);
  const callout = page.el("quotes-callout"); assert.equal(byClass(callout, "cost-row").length, 2);
  assert.ok(byClass(callout, "cost-total").some((node) => node.textContent.startsWith("$" + best.risk_adjusted.toFixed(3))));
  ["$" + Number(best.price).toFixed(2), "$" + best.financing.toFixed(3), "$" + best.exposure.toFixed(3)].forEach((value) => assert.ok(callout.textContent.includes(value), value + " is printed"));
  assert.equal(byClass(page.el("quotes-detail"), "cost-row").length, 1);
  assert.equal(byClass(callout, "ch-part").length >= 3, true);
});

test("a scenario button sends one control request, locks the controls until it returns, then refetches", async () => {
  const page = makePage(base); page.connect(); await settle(); page.host.showView("desk"); await settle();
  let release; page.server.gate = new Promise((resolve) => { release = resolve; });
  const pending = page.button("desk-controls", "Price war").click(); await settle();
  assert.deepEqual(page.server.posts, [{ action: "scenario", scenario: "price_war" }]);
  assert.ok(findAll(page.el("desk-controls"), (node) => node.tagName === "button").every((node) => node.disabled), "controls are locked while a request is pending");
  await page.button("desk-controls", "Supply shock").click(); await settle();
  assert.equal(page.server.posts.length, 1, "a second scenario cannot start while one is pending");
  page.server.snapshot = war; page.server.tag = 'W/"two"'; release(); await pending; await settle();
  assert.deepEqual(page.calls.at(-1), { url: "/v1/book", method: "GET", ifNoneMatch: "" }, "the new book is fetched unconditionally");
  assert.ok(findAll(page.el("desk-controls"), (node) => node.tagName === "button").every((node) => !node.disabled));
  assert.deepEqual(page.notices, []);
});

test("pause, resume and reset send their own actions", async () => {
  const page = makePage(base); page.connect(); await settle(); page.host.showView("desk"); await settle();
  await page.button("desk-controls", "Pause").click(); await settle();
  await page.button("desk-controls", "Reset").click(); await settle();
  assert.deepEqual(page.server.posts, [{ action: "pause" }, { action: "reset" }]);
  const paused = structuredClone(base); paused.meta.paused = true; page.server.snapshot = paused; page.server.tag = 'W/"paused"';
  page.poll(); await settle();
  assert.equal(page.el("session-state").textContent, "Paused");
  assert.ok(page.el("session-dot").has("paused") && !page.el("session-dot").has("live"));
  assert.ok(page.button("desk-controls", "Resume"));
});

test("a failed poll keeps the last book on screen and reports reconnecting, then recovers", async () => {
  const page = makePage(base); page.connect(); await settle();
  const drawn = page.el("brief-live").children[0];
  page.server.failure = "offline"; page.poll(); await settle();
  assert.equal(page.el("session-state").textContent, "Reconnecting");
  assert.equal(page.el("brief-live").children[0], drawn, "the last good book stays visible");
  page.server.failure = ""; page.poll(); await settle();
  assertLive(page);
});

test("a hidden tab stops polling and refreshes as soon as it is visible", async () => {
  const page = makePage(base); page.connect(); await settle();
  const before = page.calls.length;
  page.doc.hidden = true; page.poll(); await settle();
  assert.equal(page.calls.length, before);
  page.doc.hidden = false; page.visibility(); await settle();
  assert.equal(page.calls.length, before + 1);
});

test("ending the session clears the book and does not poll until a session returns", async () => {
  const page = makePage(base); page.connect(); await settle();
  page.server.session = false; page.disconnect(); await settle();
  assert.match(page.el("brief-live").textContent, /Opening the simulated book/);
  const before = page.calls.length; page.poll(); await settle();
  assert.equal(page.calls.length, before);
});

test("a reset restarts alert numbering, so the next event is highlighted", async () => {
  const page = makePage(war); page.connect(); await settle(); page.host.showView("desk"); await settle();
  page.server.snapshot = reset; page.server.tag = 'W/"reset"'; page.poll(); await settle();
  assert.equal(byClass(page.el("desk-activity"), "flash").length, 0, "a reset replays nothing");
  const next = structuredClone(reset); next.meta.tick += 1;
  const latest = reset.alerts.length ? reset.alerts[0].n : 0;
  next.alerts.unshift({ n: latest + 1, tick: next.meta.tick, time: reset.meta.time, level: "watch", kind: "market", text: "Follow-up after reset" });
  page.server.snapshot = next; page.server.tag = 'W/"after"'; page.poll(); await settle();
  const flashed = byClass(page.el("desk-activity"), "flash");
  assert.equal(flashed.length, 1);
  assert.match(flashed[0].textContent, /Follow-up after reset/);
});

test("Quotes ranks every quote for the selected model and Price this quote hands off the selected one", async () => {
  const page = makePage(base, { priceQuote: true }); page.connect(); await settle(); page.host.showView("quotes"); await settle();
  const rows = byTag(page.el("quotes-table"), "tbody")[0].children;
  const b300 = base.quotes.filter((quote) => quote.gpu === "B300");
  assert.equal(rows.length, b300.length);
  ["quotes-lede", "quotes-callout", "quotes-table", "quotes-detail", "quotes-models"].forEach((id) => assertClean(page.el(id), id));
  const first = findAll(rows[0], (node) => node.tagName === "button")[0];
  const chosen = b300.slice().sort((a, b) => (a.risk_rank ?? 1e9) - (b.risk_rank ?? 1e9) || Number(a.price) - Number(b.price))[0];
  assert.equal(first.textContent, chosen.id, "the top row is the best all-in quote");
  await first.click(); await settle();
  assert.match(page.el("quotes-detail").textContent, new RegExp(chosen.id));
  await page.button("quotes-detail", "Price this quote").click();
  assert.equal(page.priced.length, 1);
  assert.equal(page.priced[0].id, chosen.id);
  assert.equal(page.priced[0].price, chosen.price);
  assert.equal(typeof page.priced[0].price, "string", "prices stay decimal strings");
});

test("without a pricing handler the button simply opens Pricing", async () => {
  const page = makePage(base); page.connect(); await settle(); page.host.showView("quotes"); await settle();
  await page.button("quotes-detail", "Price this quote").click();
  assert.equal(page.shown.at(-1), "pricing");
});

test("the sources keep to the content security policy", () => {
  for (const [name, source] of [["workbench-charts.js", chartsSource], ["workbench-demo.js", demoSource]]) {
    for (const forbidden of ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", "localStorage", "sessionStorage", ".style.", 'setAttribute("style"', "setAttribute('style'"]) {
      assert.equal(source.includes(forbidden), false, name + " must not use " + forbidden);
    }
  }
});
