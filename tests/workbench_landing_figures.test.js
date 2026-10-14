"use strict";
// Every figure and sentence the Brief prints, checked against the real simulator's snapshots (raw, as the server sends them), under each
// scenario, and against books that cannot support a figure. The expected values here are worked out from the raw wire shape, not from
// the page's own helpers, so the page cannot agree with itself by accident. Fake DOM from demo_harness.js.
const { test } = require("node:test");
const { assert, fs, path, vm, assets, snapshots, walk, byClass, settle, assertClean, makePage, base, war, dataSource } = require("./demo_harness.js");

const SLOTS = ["brief-live", "brief-facts", "brief-fact-gaps", "brief-gaps", "brief-fact-cost", "brief-anatomy", "brief-fact-grades", "brief-grades", "brief-weights", "brief-odds", "brief-eligible", "brief-basis-live"];
const BOOKS = Object.entries({ "the starting book": base, "the price war": war, "the supply shock": snapshots.shock, "the provider downgrade": snapshots.downgrade, "the reset book": snapshots.reset }).filter(([, raw]) => raw);
const text = (page, id) => { const out = []; walk(page.el(id), (item) => { if (item._text) out.push(item._text); }); return out.join(" "); };  // spaces between nodes, so cells do not run together
const flat = (page, id) => page.el(id).textContent;
const rowsOf = (page, id) => byClass(page.el(id), "bf-row");
const valuesOf = (page, id) => byClass(page.el(id), "bf-value").map((node) => node.textContent);
const labelsOf = (page, id) => byClass(page.el(id), "bf-row-label").map((node) => node.textContent);
const BROKEN = /\b(NaN|undefined|Infinity|null)\b|\[object|quote-demo|provider-demo|\$NaN/;
function assertNoBroken(page, label) { SLOTS.forEach((id) => { assertClean(page.el(id), label + " " + id); assert.doesNotMatch(text(page, id), BROKEN, label + " " + id + " prints a broken value or a raw id"); }); }
let serial = 0;
async function show(page, raw) { page.server.snapshot = raw; page.server.tag = 'W/"figures-' + (++serial) + '"'; await page.poll(); await settle(); }
async function draw(raw, options = {}) { const page = makePage(raw, { width: 520, ...options }); page.connect(); await settle(); return page; }
const quiet = async (action) => { const original = console.error; console.error = () => {}; try { return await action(); } finally { console.error = original; } };

/* ---- what the book says, worked out from the raw snapshot ---- */
const printed = (value) => Number((Number(value) < 10 ? Number(value).toFixed(3) : Number(value).toFixed(2)));
const money = (value) => "$" + (Number(value) < 10 ? Number(value).toFixed(3) : Number(value).toFixed(2));
const percent = (fraction, places = 0) => (fraction * 100).toFixed(places) + "%";
const kilo = (value) => (value >= 1e4 ? (value / 1e3).toFixed(1) + "k" : String(value));
const TERM = { down_payment: "Down payment", expires: "Expiry", cooling: "Cooling", interconnect: "Interconnect", moq: "Minimum order", months: "Contract length", lead_weeks: "Lead time", location: "Location", country: "Country", payment_days: "Payment terms" };
function facts(raw) {
  const asOf = raw.meta.as_of;
  const live = raw.quotes.filter((q) => q.active !== false && q.nodes > 0 && q.expires && q.expires > asOf);
  const failing = live.filter((q) => !q.eligible); const reasons = {};
  failing.forEach((q) => new Set(q.reasons).forEach((code) => { reasons[code] = (reasons[code] || 0) + 1; }));
  const blank = raw.quotes.filter((q) => q.missing_fields.some((field) => field !== "grade")).length;
  return { live, failing, reasons, blank, total: raw.quotes.length, cheapestIneligible: raw.models.filter((m) => m.cheapest && !m.cheapest.eligible).length, pricedModels: raw.models.filter((m) => m.cheapest).length,
    weak: raw.models.filter((m) => m.cheapest && ["C", "D"].includes(m.cheapest.grade)).length };
}
const exampleOf = (page) => { const ref = /Quote (Q\d+)/.exec(flat(page, "brief-fact-cost"))[1]; return "quote-demo-" + ref.slice(1); };

test("the starting book is the book these figures are meant for: live, partly eligible, with a blank-term and an unrated minority", () => {
  const f = facts(base);
  assert.equal(f.live.length, base.kpis.live_quotes, "the live quotes counted here are the server's");
  assert.equal(f.live.filter((q) => q.eligible).length, base.kpis.eligible_quotes);
  assert.ok(f.blank > 0 && f.blank < f.total && f.failing.length > 0);
});

/* ---- LandingData against the server's own numbers ---- */
function landingData() { const w = {}; vm.runInContext(dataSource, vm.createContext({ window: w })); return w.LandingData; }
const { normalize } = require("./demo_harness.js");
test("LandingData counts what the server counts: live quotes, eligible quotes, blank terms, the lowest quote's eligibility", () => {
  const D = landingData();
  BOOKS.forEach(([name, raw]) => {
    const f = facts(raw); const data = normalize(raw);
    const e = D.eligibility(data);
    assert.equal(e.live, raw.kpis.live_quotes, name); assert.equal(e.eligible, raw.kpis.eligible_quotes, name); assert.equal(e.failing, f.failing.length, name); assert.equal(e.known, true, name);
    assert.deepEqual(Object.fromEntries(e.reasons.map((row) => [row.code, row.count])), f.reasons, name + ": every reason is counted once per quote that fails it");
    assert.equal(e.overlap, Object.values(f.reasons).reduce((a, b) => a + b, 0) > f.failing.length, name);
    const gaps = D.termGaps(data);
    assert.equal(gaps.total, raw.kpis.quotes, name + ": the blanks are counted over every quote in the book"); assert.equal(gaps.quotesWithBlank, f.blank, name);
    assert.deepEqual(Object.fromEntries(gaps.terms.map((row) => [row.field, row.count])), Object.fromEntries(Object.entries(raw.field_gaps).filter(([field]) => field !== "grade")), name);
    assert.equal(gaps.unrated, raw.field_gaps.grade || 0, name + ": a seller's missing grade is reported apart from the terms");
    const low = D.lowestQuotes(data);
    assert.equal(low.ineligible, raw.kpis.cheapest_is_ineligible, name); assert.equal(low.priced, raw.kpis.models, name); assert.equal(low.weak, f.weak, name);
    const parts = D.basisBreakdown(data); const sum = parts.screen + parts.price + parts.financing + parts.loss;
    assert.ok(Math.abs(sum - parts.basis) < 1e-12 && Math.abs(parts.basis - Number(raw.kpis.basis)) < 1e-9, name + ": the four sources add up to the server's basis");
  });
});
test("LandingData refuses a figure its book cannot support, instead of guessing", () => {
  const D = landingData(); const data = normalize(base);
  const off = structuredClone(data); off.kpis.live_quotes += 1;
  const e = D.eligibility(off); assert.equal(e.known, false, "quotes that do not add up to the live count give no reasons"); assert.equal(e.reasons.length, 0);
  assert.equal(D.eligibility({ kpis: {} }), null); assert.equal(D.eligibility(null), null); assert.equal(D.termGaps({ quotes: [] }), null); assert.equal(D.termGaps(null), null);
  assert.equal(JSON.stringify(D.lowestQuotes({})), JSON.stringify({ priced: 0, ineligible: 0, weak: 0, unrated: 0 }));
  assert.equal(D.basisBreakdown({ quotes: [], models: [] }), null);
});
test("shares are never printed as 0% or 100% unless they are, and parts keep adding up to their rounded whole", () => {
  const { share, apportion } = landingData();
  assert.equal(share(0, 144).text, "0%"); assert.equal(share(1, 1000).text, "<1%"); assert.equal(share(24, 192).text, "13%"); assert.equal(share(998, 1000).text, ">99%"); assert.equal(share(5, 5).text, "100%");
  assert.equal(share(1, 0), null); assert.equal(share(NaN, 4), null); assert.equal(share(-3, 10).text, "0%");
  [[1.449, 0.249, 3.449, 0.149], [0.05, 0.05, 0.05, 0.05], [2.25, 2.25, 0, 0], [0, 0, 0, 0]].forEach((values) => {
    const shown = apportion(values, 1); const total = Math.round(values.reduce((a, b) => a + b, 0) * 10) / 10;
    assert.ok(Math.abs(shown.reduce((a, b) => a + b, 0) - total) < 1e-9, JSON.stringify(values) + " -> " + shown);
    shown.forEach((value, index) => assert.ok(Math.abs(value - values[index]) <= 0.1 + 1e-9));
  });
});

/* ---- the page ---- */
for (const [name, raw] of BOOKS) {
  test("every figure the Brief prints matches the book under " + name, async () => {
    const page = await draw(raw); const f = facts(raw); const k = raw.kpis; assertNoBroken(page, name);
    // the four numbers
    const band = text(page, "brief-facts");
    assert.match(band, new RegExp("Live quotes " + k.live_quotes + " from " + k.providers_quoting + " sellers"));
    assert.match(band, new RegExp("GPUs quoted " + kilo(k.gpus).replace(".", "\\.") + " across " + k.models + " models"));
    assert.match(band, new RegExp("Eligible quotes " + Math.round((100 * k.eligible_quotes) / k.live_quotes) + "% " + k.eligible_quotes + " of " + k.live_quotes + " pass every check"));
    assert.match(band, new RegExp("Lowest quote ineligible " + f.cheapestIneligible + " of " + f.pricedModels + " GPU models"));
    assert.doesNotMatch(band, /basis/i, "the basis is shown in the chart and the basis band, not repeated in a tile");
    // terms left blank
    const blank = flat(page, "brief-fact-gaps");
    assert.ok(blank.startsWith(percent(f.blank / f.total) + "of the " + f.total + " quotes in the book (" + f.blank + ") leave at least one key term blank."), blank);
    const unrated = raw.field_gaps.grade || 0; if (unrated) assert.ok(blank.endsWith(unrated + " more come from a seller with no grade."), blank);
    const terms = Object.entries(raw.field_gaps).filter(([field]) => field !== "grade").sort((a, b) => b[1] - a[1] || TERM[a[0]].localeCompare(TERM[b[0]]));
    assert.deepEqual(labelsOf(page, "brief-gaps"), terms.slice(0, 5).map(([field]) => TERM[field]), "named terms, correctly capitalised, most often left blank first, never `grade`");
    assert.deepEqual(valuesOf(page, "brief-gaps"), terms.slice(0, 5).map(([, count]) => percent(count / f.total)));
    // what the price leaves out
    const quote = raw.quotes.find((q) => q.id === exampleOf(page)); const entry = raw.models.find((m) => m.model === quote.gpu);
    assert.equal(entry.cheapest.id, quote.id, "the example is a model's lowest quote");
    const price = printed(quote.price), financing = printed(quote.financing), exposure = printed(quote.exposure); const allin = Math.round((price + financing + exposure) * 1000) / 1000; const uplift = allin / price - 1;
    const stat = flat(page, "brief-fact-cost");
    assert.ok(stat.startsWith("+" + (uplift < 0.095 ? (uplift * 100).toFixed(1) : (uplift * 100).toFixed(0)) + "%Quote " + exampleOf(page).replace("quote-demo-", "Q")), stat);
    assert.ok(stat.includes("asks " + money(price) + " per GPU-hour. All-in it costs " + money(allin) + "."), stat);
    const note = flat(page, "brief-anatomy"); const apr = raw.assumptions.quote_model_assumptions.deposit_apr;
    assert.ok(note.includes(exampleOf(page).replace("quote-demo-", "Q") + " · " + quote.provider_name + " · " + (quote.grade ? "Grade " + quote.grade : "Unrated")), "the label is Q0149 · seller · Grade D");
    assert.ok(note.includes("Financing: " + (Number(apr) * 100).toFixed(1) + "% a year on the " + (Number(quote.down_payment) * 100).toFixed(0) + "% down payment, for " + quote.months + " months."), "the financing sentence is the quote's own terms");
    assert.ok(note.includes("the " + (Number(quote.failure_probability) * 100).toFixed(1) + "% chance that the seller fails during the term"));
    assert.ok(note.includes(quote.eligible ? "· eligible." : "· not eligible: "), "the example says whether it is eligible");
    // the lowest quote and the seller
    assert.ok(flat(page, "brief-fact-grades").startsWith(f.weak + " of " + f.pricedModels + "GPU models " + (f.pricedModels === 1 ? "has" : "have") + " a grade C or D seller as the lowest quote."), flat(page, "brief-fact-grades"));
    // the failure odds come from the policy, never typed
    const odds = raw.assumptions.quote_model_assumptions.annual_failure_probability;
    assert.deepEqual(labelsOf(page, "brief-odds"), ["Grade A", "Grade B", "Grade C", "Grade D"]);
    assert.deepEqual(valuesOf(page, "brief-odds"), ["A", "B", "C", "D"].map((grade) => (Number(odds[grade]) * 100).toFixed(1) + "%"));
    assert.ok(flat(page, "brief-odds").includes("recovers " + (Number(raw.assumptions.quote_model_assumptions.recovery_fraction) * 100).toFixed(0) + "% of the down payment"));
    assert.deepEqual(labelsOf(page, "brief-weights"), ["SLA and uptime", "Certification", "Counterparty credit", "Delivery record", "Facility tier", "Responsiveness"]);
    assert.deepEqual(valuesOf(page, "brief-weights"), ["25%", "20%", "20%", "15%", "10%", "10%"]);
    // the eligibility bar and why quotes fail it
    const bar = flat(page, "brief-eligible"); const top = Object.entries(f.reasons).sort((a, b) => b[1] - a[1])[0];
    assert.ok(bar.startsWith(k.eligible_quotes + " of " + k.live_quotes + "live quotes pass every check."), bar);
    assert.ok(bar.includes("The other " + f.failing.length + " fail at least one: "), bar);
    Object.entries(f.reasons).forEach(([code, count]) => assert.ok(bar.includes("(" + count + ")"), code + " is counted: " + bar));
    assert.equal(bar.includes("Most fail on the start date"), top[0] === "contract_start_precedes_as_of" && top[1] * 2 > f.failing.length, "the start-date caveat appears exactly when that reason dominates");
  });
  test("the market basis band under " + name + " explains the server's basis, and its rows add up to it", async () => {
    const page = await draw(raw); const rows = valuesOf(page, "brief-basis-live").map((value) => Number(value.replace("+", "").replace("%", "")));
    assert.equal(labelsOf(page, "brief-basis-live").length, 5, "four sources and the total"); const total = rows.pop();
    assert.ok(Math.abs(rows.reduce((a, b) => a + b, 0) - total) < 1e-9, "the printed parts add to the printed total: " + rows + " = " + total);
    assert.ok(Math.abs(total - Number(raw.kpis.basis) * 100) <= 0.05 + 1e-9, "the total is the server's basis, " + (Number(raw.kpis.basis) * 100).toFixed(2));
    assert.ok(flat(page, "brief-basis-live").includes("The best eligible all-in cost is " + total.toFixed(1) + "% above the lowest quote."));
    assert.equal(labelsOf(page, "brief-live").at(-1), "All models"); assert.equal(valuesOf(page, "brief-live").at(-1), "+" + (Number(raw.kpis.basis) * 100).toFixed(1) + "%");
  });
}

test("no sentence keeps a number from before the scenario: the example, the basis and the hero follow the book in place", async () => {
  const page = await draw(base); const before = { svg: page.el("brief-live").children[0].children[0], bar: byClass(page.el("brief-live"), "bf-bar")[0], cost: flat(page, "brief-fact-cost"), basis: text(page, "brief-basis-live"), hero: valuesOf(page, "brief-live") };
  await show(page, war);
  assert.equal(page.el("brief-live").children[0].children[0], before.svg, "the hero keeps its svg"); assert.equal(byClass(page.el("brief-live"), "bf-bar")[0], before.bar, "and its bars");
  assert.notEqual(flat(page, "brief-fact-cost"), before.cost); assert.notEqual(text(page, "brief-basis-live"), before.basis); assert.notDeepEqual(valuesOf(page, "brief-live"), before.hero);
  const quote = war.quotes.find((q) => q.id === exampleOf(page)); const allin = Math.round((printed(quote.price) + printed(quote.financing) + printed(quote.exposure)) * 1000) / 1000;
  assert.ok(flat(page, "brief-fact-cost").includes("costs " + money(allin) + "."), "the all-in cost is the price war's");
  assert.doesNotMatch(text(page, "brief-fact-cost") + text(page, "brief-anatomy"), new RegExp(money(printed(base.quotes.find((q) => q.id === quote.id).price)).replace("$", "\\$") + "(?!\\d)"), "the old ask is gone");
  assert.equal(valuesOf(page, "brief-live").at(-1), "+" + (Number(war.kpis.basis) * 100).toFixed(1) + "%");
  assertNoBroken(page, "after the price war");
  // a downgrade moves the expected-loss bar and the weak-seller count, and says nothing else changed
  if (snapshots.downgrade) { await show(page, snapshots.downgrade); assert.ok(flat(page, "brief-fact-grades").startsWith(facts(snapshots.downgrade).weak + " of "), flat(page, "brief-fact-grades")); assertNoBroken(page, "after the downgrade"); }
  await show(page, snapshots.reset); assert.equal(valuesOf(page, "brief-live").at(-1), "+" + (Number(snapshots.reset.kpis.basis) * 100).toFixed(1) + "%"); assert.equal(flat(page, "brief-fact-cost"), before.cost, "a reset returns the example's words");
});

test("a poll that changes nothing printed replaces no figure and no sentence", async () => {
  const page = await draw(base); const before = SLOTS.map((id) => [...page.el(id).children]); const texts = SLOTS.map((id) => text(page, id));
  const same = structuredClone(base); same.meta.tick += 1; await show(page, same);
  SLOTS.forEach((id, index) => { page.el(id).children.forEach((child, i) => assert.equal(child, before[index][i], id + " keeps its node " + i)); assert.equal(text(page, id), texts[index], id); });
});

/* ---- books that cannot support a figure ---- */
const clone = (raw = base) => structuredClone(raw);
function withoutEligible(raw) {
  const data = clone(raw);
  data.quotes.forEach((q) => { q.eligible = false; q.reasons = ["missing_grade"]; q.ineligible_reasons = ["missing_grade"]; q.risk_adjusted = null; q.financing = null; q.exposure = null; });
  data.models.forEach((m) => { m.best = null; m.basis = null; m.eligible = 0; m.eligible_count = 0; if (m.cheapest) m.cheapest.eligible = false; });
  Object.assign(data.kpis, { eligible_quotes: 0, eligible_share: "0", basis: null, models_with_basis: 0, cheapest_is_ineligible: data.models.filter((m) => m.cheapest).length });
  return data;
}
test("a book with no eligible quote says so in every figure and prints no zero it cannot stand behind", async () => {
  const page = await draw(withoutEligible(base)); assertNoBroken(page, "no eligible quote");
  assert.match(text(page, "brief-facts"), /Eligible quotes 0% 0 of 144 pass every check/); assert.match(text(page, "brief-facts"), /Lowest quote ineligible 6 of 6 GPU models/);
  assert.match(flat(page, "brief-eligible"), /^0 of 144live quotes pass every check\. The other 144 fail at least one: seller has no grade \(144\)\.$/);
  assert.equal(byClass(page.el("brief-live"), "bf-bar").length, 0); assert.match(text(page, "brief-live"), /No eligible seller/);
  assert.match(flat(page, "brief-basis-live"), /^No model has an eligible quote yet/); assert.match(flat(page, "brief-fact-cost"), /^—No live quote has a price and a stated term/);
  assert.equal(byClass(page.el("brief-odds"), "bf-bar").length, 4, "the odds are policy, not book, so they still draw");
});
test("a book whose sellers are all unrated shows Unrated, never a grade, and nothing about a grade it cannot know", async () => {
  const data = withoutEligible(base);
  data.providers.forEach((p) => { p.grade = null; }); data.quotes.forEach((q) => { q.grade = null; });
  data.models.forEach((m) => { if (m.cheapest) m.cheapest.grade = null; });
  const page = await draw(data); assertNoBroken(page, "all unrated");
  assert.match(flat(page, "brief-fact-grades"), /^0 of 6GPU models have a grade C or D seller/);
  assert.doesNotMatch(text(page, "brief-grades"), /Grade [A-D]\b/, "no grade is shown for a seller that has none");
});
test("a model with one quote, no model at all, and a book with a missing series all draw clean", async () => {
  const lone = clone(); const model = lone.models.find((m) => m.model === "Pro 6000"); const only = lone.quotes.find((q) => q.id === model.best.id);
  lone.models = [model]; lone.quotes = [only];
  Object.assign(model, { quote_count: 1, quotes: 1, eligible_count: 1, eligible: 1, gpus: only.gpus, median: only.price, low: only.price, high: only.price });
  Object.assign(lone.kpis, { live_quotes: 1, quotes: 1, eligible_quotes: 1, eligible_share: "1", models: 1, cheapest_is_ineligible: 0, providers_quoting: 1, basis: model.basis, gpus: only.gpus });
  lone.field_gaps = {};
  let page = await draw(lone); assertNoBroken(page, "one quote");
  assert.match(flat(page, "brief-eligible"), /^1 of 1live quote passes every check\.$/); assert.match(flat(page, "brief-fact-grades"), /^[01] of 1GPU model has a grade C or D seller/);
  assert.equal(valuesOf(page, "brief-grades")[0], "0%", "one quote is the median, so it sits 0% below it, which is true");
  assert.match(flat(page, "brief-fact-gaps"), /^0%of the 1 quote in the book leave a key term blank\./); assert.match(text(page, "brief-gaps"), /No quote in the book leaves a key term blank/);
  assert.match(text(page, "brief-facts"), /Live quotes 1 from 1 seller\b/);

  const none = clone(); none.models = []; Object.assign(none.kpis, { models: 0, basis: null, cheapest_is_ineligible: 0 });
  page = await draw(none); assertNoBroken(page, "no models"); assert.match(flat(page, "brief-fact-grades"), /^—No GPU model has a priced live quote/); assert.match(flat(page, "brief-basis-live"), /^No model has an eligible quote/);

  const bare = clone(); bare.series = {}; page = await draw(bare); assertNoBroken(page, "empty series");
  assert.equal(byClass(page.el("brief-facts"), "bf-spark").length, 0, "no trend is drawn from no history"); assert.equal(byClass(page.el("brief-facts"), "bf-number").length, 4);
  const short = clone(); short.series = { live: [144], gpus: [48890], eligible_share: [0.29], basis: [0.05], ticks: [0], times: [], policy_revisions: [], models: {} }; page = await draw(short); assertNoBroken(page, "one point of history");
});
test("a book with no live quote at all (every offer expired) says so and leaves the live figures out", async () => {
  const data = clone(); data.quotes.forEach((q) => { q.days_to_expiry = -1; q.eligible = false; q.reasons = ["simulated_quote_expired"]; q.risk_adjusted = null; q.financing = null; q.exposure = null; });
  data.models.forEach((m) => { Object.assign(m, { cheapest: null, best: null, basis: null, quotes: 0, quote_count: 32, eligible: 0, eligible_count: 0, gpus: 0, low: null, median: null, high: null }); });
  Object.assign(data.kpis, { live_quotes: 0, eligible_quotes: 0, eligible_share: null, basis: null, providers_quoting: 0, gpus: 0, cheapest_is_ineligible: 0 });
  const page = await draw(data); assertNoBroken(page, "no live quote");
  assert.match(text(page, "brief-facts"), /Live quotes 0 from 0 sellers GPUs quoted 0 across 6 models Eligible quotes — No live quotes Lowest quote ineligible —/);
  assert.match(flat(page, "brief-eligible"), /^—There are no live quotes to check\.$/); assert.match(flat(page, "brief-fact-grades"), /^—No GPU model has a priced live quote/);
  assert.equal(byClass(page.el("brief-live"), "bf-bar").length, 0);
});
test("a book whose headline counts are missing prints a dash or leaves the sentence out, never NaN", async () => {
  const data = clone(); Object.assign(data.kpis, { live_quotes: null, eligible_quotes: null, eligible_share: null, providers_quoting: null, gpus: null, models: null, quotes: null, cheapest_is_ineligible: null, basis: null });
  data.assumptions = { quote_model_assumptions: null, scorecard_policy: null, weights: {} }; data.field_gaps = null;
  const page = await draw(data); assertNoBroken(page, "missing counts");
  assert.match(text(page, "brief-facts"), /Live quotes — GPUs quoted — Eligible quotes — Lowest quote ineligible/); assert.equal(byClass(page.el("brief-odds"), "bf-bar").length, 0); assert.equal(byClass(page.el("brief-weights"), "bf-bar").length, 0);
  assert.match(flat(page, "brief-eligible"), /does not say how many quotes are live/);
});

/* ---- the render path ---- */
test("before the book arrives, when the server cannot be reached and when it sends something else, the Brief says so and prints no figure", async () => {
  const page = makePage(base, { width: 520 });
  assert.equal(flat(page, "brief-live"), "Opening the simulated book…"); SLOTS.slice(1).forEach((id) => assert.equal(page.el(id).children.length, 0, id + " is empty before the book arrives"));
  page.server.failure = "The local API could not be reached. Check the local service, then retry."; page.connect(); await settle();
  assert.match(flat(page, "brief-live"), /^The simulated book is not loading\. The local API could not be reached/); assertNoBroken(page, "unreachable");
  const other = makePage({ simulated: true, quotes: "none" }, { width: 520 }); other.connect(); await settle();
  assert.match(flat(other, "brief-live"), /^The simulated book is not loading\. The server sent something other than a quote book\./); SLOTS.slice(1).forEach((id) => assert.equal(other.el(id).children.length, 0, id));
  const recovered = makePage(base, { width: 520 }); recovered.server.failure = "down"; recovered.connect(); await settle(); recovered.server.failure = ""; recovered.server.tag = 'W/"up"'; await recovered.poll(); await settle();
  assert.ok(byClass(recovered.el("brief-live"), "bf-bar").length > 0, "the Brief draws once the book arrives"); assertNoBroken(recovered, "recovered");
});
test("a failed poll leaves the last book on screen untouched", async () => {
  const page = await draw(base); const texts = SLOTS.map((id) => text(page, id));
  page.server.failure = "The local API could not be reached."; page.server.tag = 'W/"gone"'; await page.poll(); await settle();
  SLOTS.forEach((id, index) => assert.equal(text(page, id), texts[index], id + " still shows the last book"));
});
test("when the session ends the figures are cleared, and they come back as the same words without replaying the entrance", async () => {
  const page = await draw(base); const texts = SLOTS.map((id) => text(page, id));
  page.disconnect(); await settle(); SLOTS.slice(1).forEach((id) => assert.equal(page.el(id).children.length, 0, id)); page.connect(); await settle();
  SLOTS.forEach((id, index) => assert.equal(text(page, id), texts[index], id + " reads the same"));
  assert.equal(byClass(page.el("brief-facts"), "bf-in").length, 0, "coming back is not an entrance");
});

/* ---- what the sources may say ---- */
test("no figure is typed into the Brief's words: every number in a sentence is read from the book", () => {
  for (const name of ["page-brief.js", "landing-data.js"]) {
    const source = fs.readFileSync(path.join(assets, name), "utf8").split("/* Motion.")[0].replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
    const strings = [...source.matchAll(/"((?:[^"\\\n]|\\.)*)"/g)].map((match) => match[1]);
    strings.forEach((value) => {
      if (name === "page-brief.js") assert.doesNotMatch(value, /\d\s*%|\d+(\.\d+)?\s*(percent|points)\b/i, name + ": a typed percentage in \"" + value + "\"");
      assert.doesNotMatch(value, /\b(four|ten|twelve|eighteen|thirty-five)\b|\bmock\b|workbook|\bon-demand\b|cost of capital/i, name + ": a stale claim in \"" + value + "\"");
    });
  }
});
