"use strict";
// The Overview drawn from real simulator snapshots and the desk-ledger contract fixture, in the browserless DOM (see demo_harness.js).
// Expected figures are worked out here from the snapshots and the fixture, never copied from the page and never tied to a site id or value.
const { test } = require("node:test");
const { assert, fs, path, assets, findAll, classes, byClass, byTag, settle, assertClean, makePage, base, war, reset, book, normalize, deskFixture } = require("./demo_harness.js");

const read = (name) => fs.readFileSync(path.join(assets, name), "utf8");
const SLOTS = ["desk-kpis", "desk-positions", "desk-bid-fill", "desk-bid-status", "desk-bids", "desk-basis", "desk-trend", "desk-supply", "desk-reasons", "desk-providers", "desk-activity"];
const TEXTS = ["desk-lede", "desk-clock", "desk-positions-lede", "desk-bids-lede", "desk-market-lede", "desk-capacity-lede", "desk-trend-title", "desk-map-note"];
const grouped = (digits) => digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
/* The expected printing of a server decimal: its own digits, separators, a real minus sign. */
const money = (exact, sign = false) => { const negative = exact.startsWith("-"); const [whole, fraction] = exact.replace("-", "").split("."); return (negative ? "−" : sign ? "+" : "") + "$" + grouped(whole) + (fraction ? "." + fraction : ""); };
const rows = (node) => byTag(node, "tbody").flatMap((body) => body.children.filter((child) => child.tagName === "tr"));
const cellText = (row) => row.children.map((cell) => cell.textContent);
const open = async (snapshot, options = {}) => { const page = makePage(snapshot, options); page.connect(); await settle(); page.host.showView("desk"); await settle(); return page; };
const stubMap = () => { const log = { created: [], updates: [], options: [] }; const component = { create: (container, options) => { log.created.push(container); log.options.push(options); return { update: (input) => log.updates.push(input), destroy() {} }; } }; return { log, component }; };
const clone = (value) => structuredClone(value);

test("every section draws from a real book and the ledger, with nothing broken", async () => {
  const page = await open(base);
  SLOTS.forEach((id) => { assertClean(page.el(id), id); assert.ok(page.el(id).children.length > 0, id + " is empty"); });
  TEXTS.forEach((id) => assert.doesNotMatch(page.el(id).textContent, /\b(NaN|undefined|Infinity)\b|\[object/, id));
  assert.equal(byClass(page.el("desk-kpis"), "ov-kpi").length, 6);
  const lede = /<p id="desk-lede">([^<]*)<\/p>/.exec(read("index.html"))[1];  // static, so it is there before the book is
  assert.match(lede, /Simulated data/); assert.match(lede, /executes a trade/); assert.ok(lede.length < 120, "the statement is one line");
  assert.match(page.el("desk-clock").textContent, new RegExp("Market time " + book.base.meta.as_of));
  assert.equal(page.deskCalls().length, 1, "the ledger is read once on opening");
  assert.equal(page.notices.length, 0);
});

test("positions print the server's exact money and say where each is held", async () => {
  const page = await open(base); const table = page.el("desk-positions"); const lines = rows(table);
  assert.equal(lines.length, deskFixture.positions.length);
  const sites = new Map(deskFixture.sites.map((site) => [site.id, site]));
  deskFixture.positions.forEach((position, index) => {
    const text = lines[index].textContent; const site = sites.get(position.site_id);
    assert.ok(text.includes(position.model) && text.includes(position.id), position.id + " is named");
    assert.ok(text.includes(site.placement.label), position.id + " says where it is held");
    assert.ok(text.includes(site.provider), position.id + " names the seller");
    assert.ok(text.includes(money(position.price)), position.id + " contract price, exact: " + money(position.price));
    assert.ok(text.includes(money(position.mark)), position.id + " mark, exact");
    assert.ok(text.includes(money(position.unrealized_usd, true)), position.id + " unrealized difference, exact");
    assert.ok(text.includes(String(position.gpus)), position.id + " GPUs");
    assert.ok(text.includes(position.status === "active" ? "Active" : "Upcoming"));
  });
  const total = byTag(table, "tfoot")[0].textContent;
  assert.ok(total.includes(money(deskFixture.summary.unrealized_usd, true)), "the total is the server's, not a sum made here");
  assert.ok(total.includes(String(deskFixture.summary.position_gpus)));
  assert.ok(table.textContent.includes(money(deskFixture.summary.position_notional_usd)), "notional is printed from the server's string");
  assert.equal(byClass(table, "ov-signed").length, deskFixture.positions.length, "one signed bar per position");
  const kinds = new Set(byClass(table, "ov-bar").map((bar) => classes(bar).find((name) => name === "ov-gain" || name === "ov-loss")));
  const wantGain = deskFixture.positions.some((p) => Number(p.unrealized_usd) > 0); const wantLoss = deskFixture.positions.some((p) => Number(p.unrealized_usd) < 0);
  assert.equal(kinds.has("ov-gain"), wantGain); assert.equal(kinds.has("ov-loss"), wantLoss);
  assert.ok(lines.every((row) => row.children[0].tagName === "th"), "every row leads with a row header");
});

test("a position without a mark says so and leaves the total blank instead of printing zero", async () => {
  const desk = clone(deskFixture); desk.positions[0].mark = null; desk.positions[0].unrealized_usd = null; desk.summary.unrealized_usd = null;
  const page = await open(base, { desk }); const table = page.el("desk-positions");
  assert.match(rows(byTag(table, "table")[0])[0].textContent, /No mark/);
  assert.match(byTag(table, "tfoot")[0].textContent, /—/);
  assert.match(table.textContent, /blank while any model has no mark/);
  assert.match(page.el("desk-kpis").textContent, /a model has no mark/);
  SLOTS.forEach((id) => assertClean(page.el(id), id));
});

test("bids show ask against bid, the outcome, and which bid became a position", async () => {
  const page = await open(base); const table = byTag(page.el("desk-bids"), "table")[0]; const lines = rows(table);
  assert.equal(lines.length, deskFixture.bids.length);
  const placed = deskFixture.bids.slice().sort((a, b) => String(b.placed).localeCompare(String(a.placed)) || a.id.localeCompare(b.id));
  placed.forEach((bid, index) => {
    const text = lines[index].textContent;
    assert.ok(text.includes(bid.id) && text.includes(bid.model), bid.id);
    assert.ok(text.includes(money(bid.ask)) && text.includes(money(bid.bid)), bid.id + " ask and bid, exact");
    assert.ok(text.includes(bid.status[0].toUpperCase() + bid.status.slice(1)), bid.id + " outcome");
    if (bid.position_id) assert.ok(text.includes(bid.position_id), bid.id + " names the position it became"); else assert.ok(!/pos-\d/.test(text), bid.id + " became nothing");
    assert.doesNotMatch(text, /Not in book/, bid.id + " joins to its quote");
  });
  const count = (status) => deskFixture.bids.filter((bid) => bid.status === status).length; const decided = count("filled") + count("declined") + count("expired");
  const fill = page.el("desk-bid-fill").textContent;
  assert.ok(fill.includes(Math.round((count("filled") / decided) * 100) + "%"), "fill rate");
  assert.ok(fill.includes(count("filled") + " of " + decided + " decided bids"), "the fill rate names its denominator");
  const status = byClass(page.el("desk-bid-status"), "ov-val").map((node) => node.textContent);
  ["open", "filled", "declined", "expired"].forEach((name, index) => assert.match(status[index], new RegExp("^" + count(name) + " bids?, ")));
  assert.equal(byClass(page.el("desk-bid-status"), "ov-bar").length, ["open", "filled", "declined", "expired"].filter((name) => count(name) > 0).length);
});

test("a bid whose quote has left the book, and a decided rate of nothing, draw without a join", async () => {
  const desk = clone(deskFixture); desk.bids[0].quote_id = "quote-gone"; desk.bids.forEach((bid) => { if (bid.status !== "open") bid.status = "open"; bid.decided = null; bid.position_id = null; });
  desk.summary.fill_rate = null; desk.summary.bids_open = desk.bids.length; desk.summary.bids_filled = 0; desk.summary.bids_declined = 0; desk.summary.bids_expired = 0;
  const page = await open(base, { desk });
  assert.ok(rows(page.el("desk-bids")).some((row) => /Not in book/.test(row.textContent)), "a bid whose quote is gone says so");
  assert.match(page.el("desk-bid-fill").textContent, /No bid has been decided yet/);
  assert.match(page.el("desk-kpis").textContent, new RegExp(deskFixture.bids.length + " open"));
  SLOTS.forEach((id) => assertClean(page.el(id), id));
});

test("a ledger with no positions and no bids says so", async () => {
  const desk = clone(deskFixture); desk.positions = []; desk.bids = []; Object.assign(desk.summary, { positions: 0, position_gpus: 0, unrealized_usd: "0.00", bids: 0, bids_open: 0, bids_filled: 0, bids_declined: 0, bids_expired: 0, bid_gpus: 0, filled_gpus: 0, open_gpus: 0, fill_rate: null });
  const page = await open(base, { desk });
  assert.match(page.el("desk-positions").textContent, /holds no positions/);
  assert.match(page.el("desk-bids").textContent, /No bids brokered yet/); assert.equal(page.el("desk-bid-top").hidden, true);
  SLOTS.forEach((id) => assertClean(page.el(id), id));
  assert.ok(page.el("desk-basis").children.length > 0, "the market still draws");
});

test("when the ledger cannot be read the market still draws and the desk sections explain", async () => {
  for (const make of [
    async () => { const page = makePage(base); page.server.deskFailure = "Not found"; page.connect(); await settle(); page.host.showView("desk"); await settle(); return page; },
    async () => open(base, { desk: { schema_version: "something-else/1.0" } }),
  ]) {
    const page = await make();
    assert.match(page.el("desk-positions").textContent, /desk ledger is unavailable/);
    assert.match(page.el("desk-bids").textContent, /desk ledger is unavailable/); assert.equal(page.el("desk-bid-top").hidden, true, "no empty fill-rate panel without a ledger");
    assert.match(page.el("desk-kpis").textContent, /Ledger unavailable/);
    assert.equal(byClass(page.el("desk-kpis"), "ov-kpi").length, 6);
    ["desk-basis", "desk-trend", "desk-supply", "desk-reasons", "desk-providers", "desk-activity"].forEach((id) => assert.ok(page.el(id).children.length > 0, id + " draws without the ledger"));
    SLOTS.forEach((id) => assertClean(page.el(id), id));
    assert.equal(page.el("desk-map").hidden, true); assert.equal(page.el("desk-map-note").hidden, false);
    assert.match(page.el("desk-map-note").textContent, /unaffected/);
  }
});

test("the capacity map is created once, given the normalised ledger on every render, and never overlaps a missing component", async () => {
  const { log, component } = stubMap(); const page = await open(base, { browser: { ComputeMap: component } });
  assert.equal(log.created.length, 1); assert.strictEqual(log.created[0], page.el("desk-map"));
  assert.equal(page.el("desk-map").hidden, false); assert.equal(page.el("desk-map-note").hidden, true);
  const first = log.updates.at(-1); assert.equal(first.sites.length, deskFixture.sites.length); assert.equal(first.positions.length, deskFixture.positions.length); assert.equal(first.bids.length, deskFixture.bids.length);
  assert.ok(Number.isFinite(first.sites[0].lat) && first.sites[0].grade, "the inputs are the normalised desk objects");
  const renders = log.updates.length; page.server.snapshot = war; page.server.tag = 'W/"two"'; page.poll(); await settle();
  assert.ok(log.updates.length > renders, "every render updates the map");
  assert.equal(log.created.length, 1, "the map is never rebuilt");
  page.host.showView("quotes"); await settle(); page.host.showView("desk"); await settle();
  assert.equal(log.created.length, 1, "leaving and returning keeps the same map");
  assert.match(page.el("desk-capacity-lede").textContent, /illustrative metros/);
  assert.match(page.el("desk-capacity-lede").textContent, new RegExp(grouped(String(deskFixture.summary.us_supply_gpus))));
});

test("without the map component, or when it throws, the page says so quietly and keeps drawing", async () => {
  const none = await open(base);
  assert.equal(none.el("desk-map").hidden, true); assert.match(none.el("desk-map-note").textContent, /not available in this build/);
  assert.ok(none.el("desk-bids").children.length > 0);
  const broken = await open(base, { browser: { ComputeMap: { create: () => { throw new Error("boom"); } } } });
  assert.match(broken.el("desk-map-note").textContent, /could not be drawn/); assert.equal(broken.el("desk-map").hidden, true);
  assert.ok(broken.el("desk-positions").children.length > 0, "a map failure does not stop the page");
  const flaky = stubMap(); flaky.component.create = () => ({ update: () => { throw new Error("update failed"); }, destroy() {} });
  const page = await open(base, { browser: { ComputeMap: flaky.component } }); assert.ok(page.el("desk-basis").children.length > 0);
});

test("the map is not touched while the ledger is missing, and appears when it arrives", async () => {
  const { log, component } = stubMap(); const page = makePage(base, { browser: { ComputeMap: component } }); page.server.deskFailure = "down";
  page.connect(); await settle(); page.host.showView("desk"); await settle();
  assert.equal(log.created.length, 0); assert.equal(page.el("desk-map").hidden, true);
  page.server.deskFailure = ""; page.host.showView("desk"); await settle();
  assert.equal(log.created.length, 1); assert.equal(page.el("desk-map").hidden, false);
});

test("the basis bars carry the book's own numbers, and a model with no eligible seller says so", async () => {
  const drawn = structuredClone(base); const lone = drawn.models[drawn.models.length - 1];
  lone.best = null; lone.basis = null; lone.eligible = 0; lone.eligible_count = 0;
  const expected = normalize(drawn); const page = await open(drawn); const basis = page.el("desk-basis");
  const labels = byClass(basis, "ov-val").map((node) => node.textContent); const trails = byClass(basis, "ov-trail").map((node) => node.textContent);
  assert.equal(trails.length, expected.models.length);
  expected.models.forEach((entry, index) => {
    assert.ok(labels.includes("$" + Number(entry.cheapest.price).toFixed(2)), entry.model + " lowest quote is labelled");
    if (entry.best) { assert.ok(labels.includes("$" + entry.best.risk_adjusted.toFixed(3)), entry.model + " best eligible all-in is labelled"); assert.equal(trails[index], "+" + (entry.basis * 100).toFixed(1) + "%"); }
    else assert.equal(trails[index], "—");
  });
  assert.match(basis.textContent, /No eligible seller/);
  assert.equal(byClass(basis, "ov-bar").length, expected.models.reduce((count, entry) => count + 1 + (entry.best ? 1 : 0), 0));
  const paths = byClass(basis, "ov-bar"); assert.ok(paths.every((bar) => /^M[\d.]+ [\d.]+H/.test(bar.attributes.d)), "bars are drawn from the zero line");
  assert.match(basis.textContent, /ineligible for \d+ of \d+ models/, "the caption states the book's own count");
  assert.equal(byClass(basis, "ov-twin").length, 1, "each chart has its data table");
});

test("price history: a book with one reading says it is collecting, and shows where the quotes sit instead of an empty frame", async () => {
  assert.equal(base.series.times.length, 1);
  const page = await open(base); const trend = page.el("desk-trend");
  assert.match(trend.textContent, /Collecting history/);
  assert.equal(byClass(trend, "ov-history").length, 0); assert.equal(byClass(trend, "ov-range").length, 1);
  assert.doesNotMatch(trend.textContent, /Waiting for history|NaN/);
  assert.match(page.el("desk-trend-title").textContent, new RegExp(book.base.models[0].model));
  assertClean(trend, "trend");
  assert.match(trend.textContent, /1 reading/);
  const paused = clone(base); paused.meta.paused = true; const stopped = await open(paused); assert.match(stopped.el("desk-trend").textContent, /paused/);
});

test("price history with readings draws two lines, flags each scenario, and the hover readout follows the pointer", async () => {
  const page = await open(war); const trend = page.el("desk-trend");
  assert.equal(byClass(trend, "ov-history").length, 1);
  const flags = byClass(trend, "ov-flag-label"); assert.ok(flags.some((node) => /^Price war/.test(node.textContent)), "the scenario is annotated on the chart");
  assert.ok(byClass(trend, "ov-line").length >= 1);
  assert.match(trend.textContent, /minutes? ago/);
  assert.doesNotMatch(trend.textContent, /a day ago|24h/);
  const hits = byClass(trend, "ov-hit"); assert.equal(hits.length, book.war.series.times.length);
  const chartWidth = Number(byClass(trend, "ov-history")[0].attributes.viewBox.split(" ")[2]);
  assert.ok(hits.every((hit) => Number(hit.attributes.x) >= 0 && Number(hit.attributes.x) + Number(hit.attributes.width) <= chartWidth), "no hover target reaches past the chart, even with few readings");
  const readout = byClass(trend, "ov-readout")[0]; const before = readout.textContent;
  assert.match(before, /Latest/);
  hits[1].fire("pointerenter"); const during = byClass(page.el("desk-trend"), "ov-readout")[0].textContent;
  assert.notEqual(during, before); assert.match(during, /00:\d\d UTC/);
  assert.ok(byClass(page.el("desk-trend"), "ov-cross").some((node) => classes(node).includes("on")), "the crosshair snaps to the reading");
  byClass(page.el("desk-trend"), "ov-history")[0].fire("pointerleave");
  assert.match(byClass(page.el("desk-trend"), "ov-readout")[0].textContent, /Latest/);
  assertClean(trend, "trend");
});

test("a scenario flag names the whole market, stays after its alert leaves the feed, and a reset removes it", async () => {
  const page = await open(war);
  page.server.snapshot = { ...war, alerts: war.alerts.filter((alert) => !alert.scenario) }; page.server.tag = 'W/"quiet"'; page.poll(); await settle();
  assert.ok(byClass(page.el("desk-trend"), "ov-flag-label").some((node) => /^Price war/.test(node.textContent)), "a flag stays on the chart after the feed has moved past its alert");
  const other = page.el("desk-model-tabs").children.find((button) => button.dataset.model !== "B300"); await other.click(); await settle();
  assert.ok(byClass(page.el("desk-trend"), "ov-flag-label").some((node) => /^Price war$/.test(node.textContent)), "the same flag is on every model");
  assert.equal(page.el("desk-model-tabs").children.length, book.war.models.length);
  const sameAxis = { ...reset, series: { ...reset.series, ticks: war.series.ticks }, meta: { ...reset.meta } };
  page.server.snapshot = sameAxis; page.server.tag = 'W/"reset"'; page.poll(); await settle();
  assert.equal(byClass(page.el("desk-trend"), "ov-flag-label").filter((node) => /^Price war/.test(node.textContent)).length, 0, "a flag from before the reset must not outlive it");
});

test("eligible supply is worked out from the quotes, split by grade, and never counts an unrated seller as a grade", async () => {
  const page = await open(base); const supply = page.el("desk-supply"); const data = book.base;
  const total = data.quotes.filter((q) => q.eligible).reduce((sum, q) => sum + q.gpus, 0);
  assert.match(supply.textContent, new RegExp(grouped(String(total)) + " of " + grouped(String(data.kpis.gpus))));
  data.models.forEach((entry) => { const eligible = data.quotes.filter((q) => q.gpu === entry.model && q.eligible).reduce((sum, q) => sum + q.gpus, 0); assert.match(supply.textContent, new RegExp(grouped(String(eligible)) + " of ")); });
  const legend = byClass(supply, "ov-legend")[0].textContent; ["Grade A", "Grade B", "Grade C", "Grade D"].forEach((name) => assert.ok(legend.includes(name)));
  assert.doesNotMatch(legend, /Grade U/);
  const ramp = new Set(byClass(supply, "ov-bar").flatMap((bar) => classes(bar).filter((name) => /^og-[a-d]$/.test(name)))); assert.ok(ramp.size >= 2, "grades are the ordinal ramp");
  const withUnrated = clone(base); const eligibleQuote = withUnrated.quotes.find((q) => q.eligible !== false && (q.ineligible_reasons || []).length === 0); eligibleQuote.grade = null;
  const mixed = await open(withUnrated); assert.match(byClass(mixed.el("desk-supply"), "ov-legend")[0].textContent, /Sellers not rated/); assertClean(mixed.el("desk-supply"), "supply");
});

test("quotes held back are counted by reason, and the dominant reason is named for what it is", async () => {
  const page = await open(base); const reasons = page.el("desk-reasons"); const data = book.base;
  const held = data.quotes.filter((q) => !q.eligible); const counts = new Map(); held.forEach((q) => q.reasons.forEach((reason) => counts.set(reason, (counts.get(reason) || 0) + 1)));
  const labels = byClass(reasons, "ov-lab").map((node) => node.textContent); const values = byClass(reasons, "ov-val").map((node) => node.textContent);
  assert.equal(labels.length, counts.size);
  [...counts].forEach(([reason, n]) => { const at = labels.indexOf(reason); assert.ok(at >= 0, reason); assert.equal(values[at], n + " of " + held.length); });
  const top = [...counts].sort((a, b) => b[1] - a[1])[0];
  assert.equal(labels[0], top[0]); assert.match(reasons.textContent, new RegExp(top[0] + " is on " + top[1] + " of the " + held.length + " held quotes"));
  assert.match(reasons.textContent, /more than one reason/);
  const all = clone(base); all.quotes.forEach((q) => { q.eligible = true; q.ineligible_reasons = []; });
  assert.match((await open(all)).el("desk-reasons").textContent, /Every quote in the book is eligible/);
});

test("seller health counts eligible quotes per seller, drops the zero columns, and opens a seller's quotes", async () => {
  const page = await open(base); const table = byTag(page.el("desk-providers"), "table")[0]; const data = book.base;
  assert.equal(rows(table).length, 10); const head = byTag(table, "thead")[0].textContent;
  assert.doesNotMatch(head, /Missing terms/); assert.match(head, /Eligible quotes/);
  const lines = rows(table); const top = data.providers.slice().sort((a, b) => b.gpus - a.gpus || a.name.localeCompare(b.name))[0];
  const eligible = data.quotes.filter((q) => q.provider_id === top.id && q.eligible).length;
  assert.ok(lines[0].textContent.includes(top.name) && lines[0].textContent.includes(eligible + " of " + top.quotes));
  assert.equal(byClass(lines[0], "row-link").length, 1);
  assert.ok(lines.every((row) => !classes(row).includes("recent")), "no seller is marked as just changed at the start of the book");
  const toggle = findAll(page.el("desk-providers"), (node) => node.tagName === "button" && /Show all/.test(node.textContent))[0]; await toggle.click();
  assert.equal(rows(byTag(page.el("desk-providers"), "table")[0]).length, data.providers.length);
  await byClass(rows(byTag(page.el("desk-providers"), "table")[0])[0], "row-link")[0].click();
  assert.ok(page.shown.includes("quotes"), "a seller opens the Quotes page");
  const unrated = clone(base); unrated.providers[0].grade = null; unrated.providers[0].quotes = 0; assertClean((await open(unrated)).el("desk-providers"), "providers");
});

test("key figures leave out a change when the book has no history, and name its window when it has", async () => {
  const start = await open(base); const text = start.el("desk-kpis").textContent;
  assert.equal(byClass(start.el("desk-kpis"), "ov-kpi-change").filter((node) => !node.hidden).length, 0);
  assert.doesNotMatch(text, /24h|\+0|NaN|undefined/);
  assert.match(text, new RegExp(String(book.base.kpis.live_quotes))); assert.match(text, new RegExp((book.base.kpis.basis * 100).toFixed(1) + "%"));
  const moved = await open(war); const changes = byClass(moved.el("desk-kpis"), "ov-kpi-change").filter((node) => !node.hidden).map((node) => node.textContent);
  changes.forEach((change) => assert.match(change, /^[+−][\d,.]+( pt)? in \d+ min$/));
  assert.doesNotMatch(moved.el("desk-kpis").textContent, /24h|\+0\.0|−0\.0/);
  const labels = byClass(start.el("desk-kpis"), "ov-kpi-label").map((node) => node.textContent);
  assert.deepEqual(labels, ["GPUs held", "Unrealized difference", "Bids brokered", "Live quotes", "Eligible quotes", "Market basis"]);
  assert.match(text, new RegExp(String(deskFixture.summary.position_gpus)));
});

test("a changed book redraws the Overview and highlights only what moved", async () => {
  const page = await open(base); const kpis = page.el("desk-kpis");
  assert.equal(byClass(kpis, "flash").length, 0, "nothing flashes on first paint");
  page.server.snapshot = war; page.server.tag = 'W/"two"'; page.poll(); await settle();
  assert.match(page.el("desk-kpis").textContent, new RegExp((war.kpis.basis * 100).toFixed(1) + "%"));
  assert.ok(byClass(page.el("desk-kpis"), "flash").length > 0, "changed figures are highlighted");
  assert.ok(byClass(page.el("desk-activity"), "flash").length > 0, "new events are highlighted");
  SLOTS.forEach((id) => assertClean(page.el(id), id));
});

test("when only the ledger changes, the market panels are left as they are and the desk sections redraw", async () => {
  const page = await open(war); const basis = page.el("desk-basis").children[0]; const trend = page.el("desk-trend").children.slice(); const positions = page.el("desk-positions").children[0];
  byClass(page.el("desk-trend"), "ov-hit")[1].fire("pointerenter");
  const desk = clone(deskFixture); desk.positions[0].unrealized_usd = "1.00"; desk.summary.unrealized_usd = "1.00"; page.server.desk = desk; page.server.deskTag = 'W/"desk-two"';
  page.poll(); await settle();
  assert.strictEqual(page.el("desk-basis").children[0], basis, "the basis chart is not redrawn for a ledger change");
  page.el("desk-trend").children.forEach((node, i) => assert.strictEqual(node, trend[i], "the price panel keeps its nodes, and with them the crosshair"));
  assert.notStrictEqual(page.el("desk-positions").children[0], positions, "the positions are redrawn");
  assert.match(page.el("desk-positions").textContent, /\+\$1\.00/);
});

test("the event feed says what it is waiting for, and a reset restarts its numbering", async () => {
  const page = await open(base); assert.equal(base.alerts.length, 0);
  assert.match(page.el("desk-activity").textContent, /No market events yet/);
  page.server.snapshot = war; page.server.tag = 'W/"two"'; page.poll(); await settle();
  assert.equal(byClass(page.el("desk-activity"), "ov-event").length, Math.min(9, war.alerts.length));
  page.server.snapshot = reset; page.server.tag = 'W/"reset"'; page.poll(); await settle();
  assert.equal(byClass(page.el("desk-activity"), "flash").length, 0, "a reset replays nothing");
  const next = structuredClone(reset); next.meta.tick += 1; const latest = reset.alerts.length ? reset.alerts[0].n : 0;
  next.alerts.unshift({ n: latest + 1, tick: next.meta.tick, time: reset.meta.time, level: "watch", kind: "market", text: "Follow-up after reset" });
  page.server.snapshot = next; page.server.tag = 'W/"after"'; page.poll(); await settle();
  const flashed = byClass(page.el("desk-activity"), "flash"); assert.equal(flashed.length, 1); assert.match(flashed[0].textContent, /Follow-up after reset/);
});

test("an empty book draws without a single broken figure", async () => {
  const empty = clone(base);
  empty.models = []; empty.quotes = []; empty.providers = []; empty.supply = {}; empty.completeness = []; empty.expiry = []; empty.field_gaps = {};
  Object.assign(empty.kpis, { live_quotes: 0, eligible_quotes: 0, quotes: 0, held_quotes: 0, gpus: 0, quoted_gpus: 0, providers_quoting: 0, eligible_share: null, basis: null, models: 0, models_with_basis: 0, cheapest_is_ineligible: 0 });
  empty.series = { ...empty.series, models: {} }; empty.grade_mix = { A: { providers: 0, quotes: 0, gpus: 0 }, B: { providers: 0, quotes: 0, gpus: 0 }, C: { providers: 0, quotes: 0, gpus: 0 }, D: { providers: 0, quotes: 0, gpus: 0 }, unknown: { providers: 0, quotes: 0, gpus: 0 } };
  const page = await open(empty, { desk: { ...clone(deskFixture), sites: [], positions: [], bids: [] } });
  assert.equal(byClass(page.el("desk-kpis"), "ov-kpi").length, 6);
  ["desk-kpis", "desk-basis", "desk-trend", "desk-supply", "desk-reasons", "desk-providers", "desk-activity", "desk-positions", "desk-bid-fill"].forEach((id) => { assertClean(page.el(id), id); });
  assert.match(page.el("desk-trend").textContent, /No GPU models in the book/);
  assert.match(page.el("desk-reasons").textContent, /Every quote in the book is eligible/);
});

test("before the book arrives, and after the session ends, the Overview waits quietly", async () => {
  const page = makePage(base); page.server.session = false; page.host.showView("desk"); await settle();
  assert.match(page.el("desk-kpis").textContent, /Opening the simulated book/);
  page.server.session = true; page.connect(); await settle(); assert.equal(byClass(page.el("desk-kpis"), "ov-kpi").length, 6);
  page.disconnect(); await settle(); assert.match(page.el("desk-kpis").textContent, /Opening the simulated book/);
  assert.equal(byClass(page.el("desk-kpis"), "ov-kpi").length, 0);
});

test("motion belongs to a section's first second: it enters once, then polls redraw without it", async () => {
  const page = await open(base);
  assert.ok(classes(page.el("desk-kpis")).includes("ov-in"), "the key figures enter");
  assert.ok(byClass(page.el("desk-basis"), "ov-in").length === 1 && byClass(page.el("desk-positions"), "ov-in").length === 1, "charts and tables enter on first draw");
  await new Promise((resolve) => setTimeout(resolve, 1100));
  page.server.snapshot = war; page.server.tag = 'W/"two"'; page.poll(); await settle();
  assert.ok(!classes(page.el("desk-kpis")).includes("ov-in"), "a poll after the first second does not re-enter the figures");
  ["desk-basis", "desk-supply", "desk-reasons", "desk-bid-status"].forEach((id) => assert.equal(byClass(page.el(id), "ov-in").length, 0, id + " does not re-animate"));
  assert.equal(byClass(page.el("desk-positions"), "ov-in").length + byClass(page.el("desk-bids"), "ov-in").length, 0, "tables do not re-animate");
  assert.equal(byClass(page.el("desk-trend"), "ov-history").length, 1, "the line chart replaces the strip once there is history; that is its own first draw");
});

test("a moving book never prints a malformed price", async () => {
  const page = await open(war);
  SLOTS.forEach((id) => { assertClean(page.el(id), id); assert.doesNotMatch(page.el(id).textContent, /\$-|\$NaN|--\d/, id); });
});

/* ---- what the files themselves must obey ---- */
const OVERVIEW_JS = fs.readdirSync(assets).filter((name) => /^page-overview(-[a-z]+)?\.js$/.test(name));
const withoutComments = (source) => source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");

test("the Overview scripts load in order after page-overview.js, one per line, and obey the content security policy", () => {
  const html = read("index.html"); const lines = [...html.matchAll(/<script src="\/workbench\/assets\/([^"]+)" defer><\/script>/g)].map((m) => m[1]);
  const at = lines.indexOf("page-overview.js"); assert.ok(at >= 0);
  const followers = OVERVIEW_JS.filter((name) => name !== "page-overview.js").sort();
  assert.deepEqual(lines.slice(at + 1, at + 1 + followers.length).slice().sort(), followers, "each page-overview-*.js sits directly after page-overview.js");
  assert.ok(lines.indexOf("page-overview-charts.js") < lines.indexOf("page-overview-desk.js") && lines.indexOf("page-overview-charts.js") < lines.indexOf("page-overview-market.js"), "primitives load before the modules that draw with them");
  OVERVIEW_JS.forEach((name) => {
    const source = withoutComments(read(name));
    ["innerHTML", "outerHTML", "insertAdjacentHTML", "eval(", "new Function", "localStorage", "sessionStorage", "document.write"].forEach((word) => assert.ok(!source.includes(word), name + " must not use " + word));
    assert.doesNotMatch(source, /\.style\b|setAttribute\(\s*["']style["']/, name + " must not touch inline style");
    assert.doesNotMatch(source, /\bstyle\s*:/, name + " must not pass a style attribute");
  });
  assert.doesNotMatch(html.slice(html.indexOf('id="desk-view"'), html.indexOf('id="quotes-view"')), /\sstyle=|\son[a-z]+=/, "the desk view has no inline style or handler");
});

test("every element id the Overview scripts read exists in index.html", () => {
  const html = read("index.html"); const ids = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]));
  OVERVIEW_JS.forEach((name) => {
    const source = read(name);
    [...source.matchAll(/(?:byId|replace|text|fit|modelTabs)\(\s*"(desk-[a-z0-9-]+)"/g)].forEach((m) => assert.ok(ids.has(m[1]), name + " reads #" + m[1]));
    [...source.matchAll(/const (?:slot|chart) = "(desk-[a-z-]+)"/g)].forEach((m) => assert.ok(ids.has(m[1]), name + " draws into #" + m[1]));
  });
  ["desk-controls", "desk-map", "desk-map-note", "desk-kpis"].forEach((id) => assert.ok(ids.has(id), id));
  assert.match(html, /<div id="desk-map" class="ov-map"><\/div>/, "the map component gets an empty container of its own");
});

test("overview.css keeps light, dark and system-dark values in step and moves nothing but opacity and transform", () => {
  const css = withoutComments(read("overview.css"));
  const block = (marker) => { const start = css.indexOf(marker); assert.ok(start >= 0, marker); const open = css.indexOf("{", start); let depth = 0; for (let i = open; i < css.length; i++) { if (css[i] === "{") depth++; if (css[i] === "}" && --depth === 0) return css.slice(open + 1, i); } return ""; };
  const names = (text) => [...text.matchAll(/(--[a-z0-9-]+)\s*:/g)].map((m) => m[1]).sort();
  const light = names(block(":root {")); const dark = names(block(':root[data-theme="dark"] {')); const system = names(block(":root:not([data-theme]) {"));
  assert.ok(light.length > 0); assert.deepEqual(dark, light); assert.deepEqual(system, light);
  const motion = block("@media (prefers-reduced-motion: no-preference)");
  const keyframes = [...css.matchAll(/@keyframes\s+(ov-[a-z]+)/g)].map((m) => m[1]); assert.ok(keyframes.length >= 3);
  keyframes.forEach((name) => assert.ok(motion.includes("@keyframes " + name), name + " sits inside no-preference"));
  const properties = (name) => [...new Set([...block("@keyframes " + name).matchAll(/([a-z-]+)\s*:/g)].map((m) => m[1]))];
  keyframes.forEach((name) => properties(name).forEach((property) => assert.ok(["opacity", "transform"].includes(property), name + " animates " + property)));
  assert.doesNotMatch(css.replace(motion, ""), /animation\s*:/, "no animation outside no-preference");
  assert.doesNotMatch(css, /gradient|text-transform:\s*uppercase|letter-spacing:\s*\.0[5-9]/, "no decorative gradients and no tracked capitals");
});

test("the page contains no tracked-caps labels, numbered markers or hype", () => {
  const html = read("index.html"); const desk = html.slice(html.indexOf('id="desk-view"'), html.indexOf('id="quotes-view"'));
  assert.doesNotMatch(desk, /eyebrow|class="step"|>\s*0\d\s*</, "no eyebrows and no 01/02/03 markers");
  OVERVIEW_JS.map(read).concat(desk).forEach((source) => assert.doesNotMatch(source, /seamless|revolution|cutting-edge|unlock|supercharge|powerful|🚀|✨/i));
});
