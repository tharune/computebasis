"use strict";
// Draw the shipped chart and Brief/Overview/Quotes modules against snapshots produced by the real simulator, in a browserless DOM.
const { test } = require("node:test");
const { assert, fs, path, vm, assets, snapshots, html, El, walk, findAll, classes, byClass, byTag, settle, assertClean, makePage, base, war, reset, book, normalize, assertLive, DEMO_FILES, chartsSource, dataSource, adapterSource } = require("./demo_harness.js");

test("snapshots come from the simulator and the scenario and reset change them", () => {
  assert.equal(base.simulated, true);
  assert.notEqual(base.kpis.basis, war.kpis.basis);
  assert.ok(war.alerts.some((alert) => alert.scenario === "price_war"));
  assert.ok(book.war.alerts.some((alert) => alert.kind === "scenario" && alert.scenario_label === "Price war"), "the adapter names the scenario");
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
  book.base.models.forEach((entry) => assert.match(live.textContent, new RegExp(entry.model)));
  BRIEF_SLOTS.forEach((id) => { assertClean(page.el(id), id); assert.ok(page.el(id).children.length > 0, id + " is empty"); });
  assert.ok(page.el("brief-facts").textContent.length > 0);
});

const BRIEF_SLOTS = ["brief-live", "brief-facts", "brief-fact-gaps", "brief-gaps", "brief-fact-cost", "brief-anatomy", "brief-fact-grades", "brief-grades", "brief-weights", "brief-eligible", "brief-basis-live"];

test("the Brief states the problem with figures from the book and draws clean bars, not dumbbells", async () => {
  const page = makePage(base); page.connect(); await settle();
  const hero = page.el("brief-live");
  assert.equal(byClass(hero, "bf-bar").length, book.base.models.filter((entry) => entry.best).length, "one bar per model with an eligible seller");
  assert.equal(byClass(page.el("brief-facts"), "bf-number").length, 4);
  assert.match(page.el("brief-facts").textContent, new RegExp(String(base.kpis.live_quotes)));
  assert.match(page.el("brief-fact-grades").textContent, new RegExp("of " + book.base.models.length));
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

test("a scenario button sends one control request, locks the controls until it returns, then refetches", async () => {
  const page = makePage(base); page.connect(); await settle(); page.host.showView("desk"); await settle();
  let release; page.server.gate = new Promise((resolve) => { release = resolve; });
  const pending = page.button("desk-controls", "Price war").click(); await settle();
  assert.deepEqual(page.server.posts, [{ action: "scenario", scenario: "price_war" }]);
  assert.ok(findAll(page.el("desk-controls"), (node) => node.tagName === "button").every((node) => node.disabled), "controls are locked while a request is pending");
  await page.button("desk-controls", "Supply shock").click(); await settle();
  assert.equal(page.server.posts.length, 1, "a second scenario cannot start while one is pending");
  page.server.snapshot = war; page.server.tag = 'W/"two"'; release(); await pending; await settle();
  assert.deepEqual(page.bookCalls().at(-1), { url: "/v1/book", method: "GET", ifNoneMatch: "" }, "the new book is fetched unconditionally");
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

/* Motion: what the script decides, since the CSS cannot be drawn in a browserless DOM. */
const REVEAL_IDS = ["brief-problem-head", "brief-problem-1", "brief-problem-2", "brief-problem-3", "brief-how-head", "brief-steps", "brief-basis", "brief-close"];
function fakeObserver() {
  const watchers = [];
  class Watcher {
    constructor(callback, options) { this.callback = callback; this.options = options; this.observed = []; this.unobserved = []; watchers.push(this); }
    observe(node) { this.observed.push(node); }
    unobserve(node) { this.unobserved.push(node); }
  }
  return { watchers, IntersectionObserver: Watcher };
}

test("sections below the fold are hidden only when the script can also reveal them, and each is revealed once", async () => {
  const seen = fakeObserver(); const page = makePage(base, { browser: { IntersectionObserver: seen.IntersectionObserver } });
  assert.ok(page.el("brief-view").has("rv-on"), "the hidden state is armed");
  assert.equal(seen.watchers.length, 1);
  const [watcher] = seen.watchers;
  assert.deepEqual(watcher.observed.map((node) => node), REVEAL_IDS.map((id) => page.el(id)));
  const [above, visible] = [page.el("brief-problem-1"), page.el("brief-problem-2")];
  watcher.callback([{ isIntersecting: false, target: above }, { isIntersecting: true, target: visible }]);
  assert.equal(above.has("rv-in"), false, "a block that has not scrolled in stays hidden");
  assert.equal(visible.has("rv-in"), true);
  assert.deepEqual(watcher.unobserved, [visible], "a revealed block is not watched again, so it never replays");
});

test("nothing is hidden without IntersectionObserver or when motion is reduced", () => {
  const none = makePage(base);
  assert.equal(none.el("brief-view").has("rv-on"), false);
  REVEAL_IDS.forEach((id) => assert.equal(none.el(id).has("rv-in"), false));
  const seen = fakeObserver(); const reduced = makePage(base, { browser: { IntersectionObserver: seen.IntersectionObserver, matchMedia: () => ({ matches: true }) } });
  assert.equal(reduced.el("brief-view").has("rv-on"), false);
  assert.equal(seen.watchers.length, 0, "no observer is even created");
});

test("every block the page marks for reveal is one the script reveals", () => {
  const marked = [...html.matchAll(/<[a-z0-9]+\b[^>]*\bid="([^"]+)"[^>]*\bclass="([^"]*)"|<[a-z0-9]+\b[^>]*\bclass="([^"]*)"[^>]*\bid="([^"]+)"/g)]
    .map((tag) => ({ id: tag[1] || tag[4], cls: (tag[2] || tag[3]).split(/\s+/) })).filter((tag) => tag.cls.includes("rv") || tag.cls.includes("rv-group")).map((tag) => tag.id);
  assert.deepEqual([...marked].sort(), [...REVEAL_IDS].sort(), "a block with rv but no entry in REVEAL would stay invisible");
  const withClass = [...html.matchAll(/class="([^"]*)"/g)].filter((tag) => tag[1].split(/\s+/).some((name) => name === "rv" || name === "rv-group")).length;
  assert.equal(withClass, REVEAL_IDS.length, "every block marked for reveal has an id the script can find");
});

test("the Brief's entrance is for the first visit; once the person has left, coming back is a plain fade", () => {
  const page = makePage(base);
  assert.equal(page.el("brief-view").has("bf-entered"), false);
  page.host.showView("desk"); assert.ok(page.el("brief-view").has("bf-entered"));
  page.host.showView("brief"); assert.ok(page.el("brief-view").has("bf-entered"), "returning does not restart the sequence");
});

test("the figures and chart rows stagger in on the first draw only, never again on a poll", async () => {
  const page = makePage(base); page.connect(); await settle();
  assert.equal(byClass(page.el("brief-facts"), "bf-in").length, 4, "the four figures enter in turn");
  assert.ok(byClass(page.el("brief-live"), "bf-grow").length > 0, "the hero chart draws in");
  const groups = byClass(page.el("brief-live"), "bf-bar-group");
  groups.forEach((group, index) => assert.ok(classes(group).some((name) => /^bf-r\d+$/.test(name)), "bar " + index + " carries its row rank"));
  assert.equal(byClass(page.el("brief-live"), "bf-value").every((node) => classes(node).some((name) => /^bf-r\d+$/.test(name))), true);
  page.server.snapshot = structuredClone(base); page.server.snapshot.meta.tick += 1; page.server.tag = 'W/"two"'; page.poll(); await settle();
  assert.equal(byClass(page.el("brief-facts"), "bf-in").length, 0, "a later poll redraws without the entrance, so nothing flickers");
  assert.equal(byClass(page.el("brief-live"), "bf-grow").length, 0);
});

test("the basis breakdown adds up to the basis and to the server's own figure", () => {
  const { window } = (() => { const w = {}; vm.runInContext(dataSource, vm.createContext({ window: w })); return { window: w }; })();
  const { basisBreakdown } = window.LandingData;
  [["start", book.base], ["price war", book.war], ["reset", book.reset]].forEach(([name, snapshot]) => {
    const parts = basisBreakdown(snapshot);
    assert.ok(parts, name + " has a breakdown");
    assert.ok(Math.abs(parts.screen + parts.costing - parts.basis) < 1e-12, name + ": screen and costing add up to the basis");
    assert.ok(Math.abs(parts.basis - snapshot.kpis.basis) < 6e-4, name + ": " + parts.basis + " matches the server's " + snapshot.kpis.basis);
    assert.ok(parts.screen >= 0 && parts.costing >= 0, name + ": both sources are non-negative");
    assert.ok(parts.models >= 1 && parts.models <= parts.modelsTotal);
    [parts.basis, parts.screen, parts.costing, parts.gpus].forEach((value) => assert.ok(Number.isFinite(value)));
  });
});

test("the basis breakdown says nothing when no model has an eligible, priced quote", () => {
  const w = {}; vm.runInContext(dataSource, vm.createContext({ window: w })); const { basisBreakdown } = w.LandingData;
  assert.equal(basisBreakdown(null), null);
  assert.equal(basisBreakdown({}), null);
  assert.equal(basisBreakdown({ quotes: [], models: [{ model: "X", gpus: 8, best: null }] }), null);
  const lone = { models: [{ model: "X", gpus: 8, best: { risk_adjusted: 6 } }], quotes: [{ gpu: "X", price: "5", eligible: false }] };
  assert.equal(basisBreakdown(lone), null, "a model whose only quote is ineligible is left out");
  const one = { models: [{ model: "X", gpus: 8, best: { risk_adjusted: 6 } }], quotes: [{ gpu: "X", price: "4", eligible: false }, { gpu: "X", price: "5", eligible: true }] };
  const parts = basisBreakdown(one);
  assert.ok(Math.abs(parts.basis - 0.5) < 1e-12 && Math.abs(parts.screen - 0.25) < 1e-12 && Math.abs(parts.costing - 0.25) < 1e-12);
});

test("the sources keep to the content security policy", () => {
  for (const [name, source] of [["workbench-charts.js", chartsSource], ...DEMO_FILES.map((name) => [name, fs.readFileSync(path.join(assets, name), "utf8")]), ["landing-data.js", dataSource], ["book-adapter.js", adapterSource]]) {
    for (const forbidden of ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", "localStorage", "sessionStorage", ".style.", 'setAttribute("style"', "setAttribute('style'"]) {
      assert.equal(source.includes(forbidden), false, name + " must not use " + forbidden);
    }
  }
});

test("the adapter turns the server's decimal strings into numbers and keeps the exact text beside the money", () => {
  const quote = book.base.quotes[0]; const sent = base.quotes[0];
  assert.equal(typeof quote.price, "number");
  assert.equal(quote.exact.price, sent.price, "the exact decimal stays available for labels and the handoff");
  assert.equal(quote.exact.contract_value, sent.contract_value);
  assert.equal(quote.ref, "Q" + sent.id.match(/(\d+)$/)[1]);
  assert.equal(book.base.models[0].best.exact === undefined, true, "only quotes carry exact strings");
  assert.equal(typeof book.base.kpis.basis, "number");
  assert.ok(Math.abs(book.base.kpis.basis - Number(base.kpis.basis)) < 1e-15);
  assert.equal(base.quotes[0].id, quote.id, "ids are never turned into numbers");
});

test("the adapter gives every unrated seller grade U and never counts it as a grade", () => {
  const unrated = book.base.quotes.filter((quote) => base.quotes.find((raw) => raw.id === quote.id).grade === null);
  assert.ok(unrated.length > 0, "the starting book includes unrated sellers");
  unrated.forEach((quote) => assert.equal(quote.grade, "U"));
  assert.ok("U" in book.base.grade_mix && !("unknown" in book.base.grade_mix));
  Object.values(book.base.supply).forEach((row) => assert.ok("U" in row && !("unknown" in row)));
  book.base.completeness.forEach((row) => assert.ok("U" in row.by_grade && !("unknown" in row.by_grade)));
  book.base.providers.forEach((provider) => assert.match(provider.grade, /^[ABCDU]$/));
});

test("the adapter keeps a quote's missing terms as a list and gives every ineligible quote readable reasons", () => {
  const gaps = book.base.quotes.filter((quote) => quote.missing.length);
  assert.ok(gaps.length > 0);
  gaps.forEach((quote) => { assert.ok(Array.isArray(quote.missing)); assert.equal(quote.missing_count, quote.missing.length); });
  book.base.quotes.filter((quote) => !quote.eligible).forEach((quote) => {
    assert.ok(quote.reason_codes.length > 0, quote.id + " says why it is not eligible");
    assert.equal(quote.reasons.length, quote.reason_codes.length);
    quote.reasons.forEach((reason) => assert.doesNotMatch(reason, /_/, "no machine codes in readable reasons: " + reason));
  });
  book.base.quotes.filter((quote) => quote.eligible).forEach((quote) => assert.deepEqual([...quote.reasons], []));
});

test("the adapter leaves a price it cannot know as null instead of making one up", () => {
  const unpriced = book.base.quotes.filter((quote) => quote.risk_adjusted === null);
  assert.ok(unpriced.length > 0, "the book has quotes that cannot be priced all-in");
  unpriced.forEach((quote) => { assert.equal(quote.eligible, false); assert.equal(Number.isNaN(quote.financing), false); });
  const walk2 = (value, where) => {
    if (typeof value === "number") assert.ok(Number.isFinite(value), where + " is not finite");
    else if (Array.isArray(value)) value.forEach((item, index) => walk2(item, where + "[" + index + "]"));
    else if (value && typeof value === "object") Object.entries(value).forEach(([key, item]) => { if (key !== "raw") walk2(item, where + "." + key); });
  };
  ["base", "war", "reset"].forEach((name) => walk2(book[name], name));
});

test("the adapter names each scenario and refuses a response that is not a book", () => {
  assert.equal(book.war.alerts[0].scenario_label, "Price war");
  assert.equal(book.base.alerts.length, 0);
  [null, undefined, 0, "book", [], {}, { quotes: [] }, { ...base, kpis: null }, { ...base, quotes: "none" }].forEach((bad) => assert.equal(normalize(bad), null, JSON.stringify(bad)?.slice(0, 40)));
  const older = structuredClone(book.base); older.raw = undefined;
  assert.ok(normalize(JSON.parse(JSON.stringify(base))), "a book is accepted whole");
});

test("the page says so when the server sends something that is not a book", async () => {
  const page = makePage({ simulated: true, quotes: "none" }); page.connect(); await settle();
  assert.match(page.el("session-state").textContent, /Reconnecting|Connecting/);
  assert.equal(page.el("brief-live").children.length >= 0, true);
});

const { deskFixture } = require("./demo_harness.js");
const normalizeDesk = (raw) => adapterContext_.window.BookAdapter.normalizeDesk(raw);
const adapterContext_ = vm.createContext({ window: {} }); vm.runInContext(adapterSource, adapterContext_, { filename: "book-adapter.js" });

test("the desk ledger is read only while the Overview is open, and its exact money survives", async () => {
  const page = makePage(base); page.connect(); await settle();
  assert.equal(page.deskCalls().length, 0, "the Brief does not read the ledger");
  page.host.showView("desk"); await settle();
  assert.equal(page.deskCalls().length, 1);
  assert.deepEqual(page.deskCalls()[0], { url: "/v1/book/desk", method: "GET", ifNoneMatch: "" });
  page.poll(); await settle();
  assert.equal(page.deskCalls().at(-1).ifNoneMatch, 'W/"desk-one"', "a later read is conditional");
  page.host.showView("quotes"); await settle(); const reads = page.deskCalls().length; page.poll(); await settle();
  assert.equal(page.deskCalls().length, reads, "leaving the Overview stops the reads");
});

test("the Overview still draws the market when the desk ledger cannot be read or is not a ledger", async () => {
  const failing = makePage(base); failing.server.deskFailure = "The desk ledger is unavailable."; failing.connect(); await settle(); failing.host.showView("desk"); await settle();
  assertLive(failing); assertClean(failing.el("desk-kpis"), "desk-kpis"); assert.ok(failing.el("desk-basis").children.length > 0);
  const wrong = makePage(base, { desk: { schema_version: "something-else/1.0" } }); wrong.connect(); await settle(); wrong.host.showView("desk"); await settle();
  assertLive(wrong); assert.ok(wrong.el("desk-basis").children.length > 0);
});

test("the adapter reads the desk ledger: numbers to draw, exact money to print, places on the map", () => {
  const desk = normalizeDesk(deskFixture);
  assert.ok(desk, "the contract fixture is accepted");
  assert.equal(desk.simulated, true); assert.equal(desk.execution_enabled, false); assert.equal(desk.inventory_verified, false);
  assert.equal(desk.sites.length, deskFixture.sites.length);
  desk.sites.filter((site) => site.country === "US").forEach((site) => { assert.match(site.state, /^[A-Z]{2}$/); assert.ok(Number.isFinite(site.lat) && Number.isFinite(site.lon)); });
  desk.sites.filter((site) => site.country !== "US").forEach((site) => assert.equal(site.state, null));
  const position = desk.positions[0]; const sent = deskFixture.positions[0];
  assert.equal(typeof position.price, "number"); assert.equal(position.exact.price, sent.price); assert.equal(position.exact.unrealized_usd, sent.unrealized_usd);
  assert.equal(desk.bids.find((bid) => bid.status === "open").decided, null);
  assert.equal(typeof desk.summary.fill_rate, "number"); assert.equal(desk.summary.exact.unrealized_usd, deskFixture.summary.unrealized_usd);
  const unmarked = structuredClone(deskFixture); unmarked.positions[0].mark = null; unmarked.positions[0].unrealized_usd = null; unmarked.summary.fill_rate = null;
  const gap = normalizeDesk(unmarked); assert.equal(gap.positions[0].mark, null); assert.equal(gap.positions[0].unrealized_usd, null); assert.equal(gap.summary.fill_rate, null);
  [null, {}, { schema_version: "synthetic-desk-ledger/1.0" }, { ...deskFixture, sites: "none" }, { ...deskFixture, schema_version: "other" }].forEach((bad) => assert.equal(normalizeDesk(bad), null));
});

test("the desk fixture keeps the contract's joins and honesty flags", () => {
  const ids = (list) => new Set(list.map((row) => row.id));
  const sites = ids(deskFixture.sites); const positions = ids(deskFixture.positions); const quotes = ids(base.quotes); const providers = ids(base.providers);
  deskFixture.positions.forEach((position) => assert.ok(sites.has(position.site_id)));
  deskFixture.bids.forEach((bid) => { assert.ok(sites.has(bid.site_id)); assert.ok(quotes.has(bid.quote_id)); if (bid.position_id) assert.ok(positions.has(bid.position_id)); });
  deskFixture.sites.forEach((site) => assert.ok(providers.has(site.provider_id)));
  assert.equal(deskFixture.summary.supply_gpus, base.kpis.gpus);
  assert.equal(deskFixture.summary.supply_gpus, deskFixture.sites.reduce((sum, site) => sum + site.capacity.gpus, 0));
  assert.deepEqual([deskFixture.simulated, deskFixture.synthetic, deskFixture.source_evidence_eligible, deskFixture.inventory_verified, deskFixture.firm_price_eligible, deskFixture.execution_enabled], [true, true, false, false, false, false]);
});
