"use strict";
// The Quotes page drawn from real simulator snapshots in the browserless DOM (see demo_harness.js): what it prints, that every quote is
// reachable, that a poll leaves the selection alone, that quotes the book cannot price or grade are handled, and that the handoff is exact.
const { test } = require("node:test");
const { assert, vm, fs, path, assets, El, findAll, classes, byClass, byTag, walk, settle, assertClean, makePage, base, war, reset, book, normalize, assertLive, html, chartsSource } = require("./demo_harness.js");

const VIEW_IDS = ["quotes-lede", "quotes-callout", "quotes-ladder", "quotes-reasons", "quotes-reasons-note", "quotes-table", "quotes-foot", "quotes-detail"];
const open = async (snapshot = base, options) => { const page = makePage(snapshot, options); page.connect(); await settle(); page.host.showView("quotes"); await settle(); return page; };
const chooseModel = async (page, model) => { await findAll(page.el("quotes-models"), (n) => n.tagName === "button" && n.dataset.model === model)[0].click(); await settle(); };
const rowButtons = (page) => findAll(page.el("quotes-table"), (n) => n.tagName === "button" && classes(n).includes("row-link"));
const rowRefs = (page) => rowButtons(page).map((b) => b.textContent);
const buttonFor = (page, ref) => rowButtons(page).find((b) => b.textContent === ref);
const modelQuotes = (snapshot, model) => snapshot.quotes.filter((q) => q.gpu === model);
const allText = (page) => VIEW_IDS.map((id) => page.el(id).textContent).join("\n");
/* Any text a person reads, and any label a screen reader reads: no machine codes, no full ids, nothing broken. */
const SNAKE = /\b[a-z]+(?:_[a-z]+)+\b/;
function assertReadable(page, label) {
  VIEW_IDS.forEach((id) => {
    assertClean(page.el(id), label + " " + id);
    walk(page.el(id), (node) => {
      if (node._text) { assert.doesNotMatch(node._text, SNAKE, label + " " + id + ": raw code in text \"" + node._text + "\""); assert.doesNotMatch(node._text, /quote-demo-\d+/, label + " " + id + ": full id in text \"" + node._text + "\""); }
      for (const [key, value] of Object.entries(node.attributes)) {
        if (["class", "data-id", "data-fk", "d", "viewBox", "transform", "id", "role", "tabindex", "scope", "colspan", "type", "aria-current", "text-anchor", "dy"].includes(key)) continue;
        assert.doesNotMatch(value, SNAKE, label + " " + id + ": raw code in " + key + " \"" + value + "\""); assert.doesNotMatch(value, /quote-demo-\d+/, label + " " + id + ": full id in " + key);
      }
    });
  });
}
const tickLabels = (page) => byClass(page.el("quotes-ladder"), "ch-tick").map((node) => node.textContent);

test("every model draws a readable headline, ladder, breakdown, table and detail in every snapshot", async () => {
  for (const [name, snapshot] of [["base", base], ["price war", war], ["reset", reset]]) {
    const page = await open(snapshot); assertLive(page);
    for (const entry of book.base.models) {
      await chooseModel(page, entry.model);
      assertReadable(page, name + " " + entry.model);
      VIEW_IDS.forEach((id) => assert.ok(page.el(id).children.length > 0 || page.el(id).textContent, id + " is empty for " + entry.model));
    }
  }
});

test("the page says the data is simulated, and names prices in dollars per GPU-hour", async () => {
  const page = await open();
  assert.match(page.el("quotes-lede").textContent, /simulated/i); assert.match(page.el("quotes-lede").textContent, /GPU-hour/);
  assert.match(page.el("quotes-lede").textContent, new RegExp(String(base.quotes.length)));
});

test("the headline names the lowest quote and the best eligible buy by short ref, with the server's figures", async () => {
  const page = await open(); const b300 = book.base.models.find((m) => m.model === "B300");
  const lowest = book.base.quotes.find((q) => q.id === b300.cheapest.id); const best = book.base.quotes.find((q) => q.id === b300.best.id);
  const callout = page.el("quotes-callout").textContent;
  assert.match(callout, new RegExp(lowest.ref)); assert.match(callout, new RegExp(best.ref));
  assert.ok(callout.includes("$" + lowest.price.toFixed(4)), "the lowest quote's price"); assert.ok(callout.includes("$" + best.risk_adjusted.toFixed(4)), "the best eligible all-in cost");
  assert.ok(callout.includes((b300.basis * 100).toFixed(1) + "%"), "the server's basis");
  assert.match(callout, /not eligible/i, "B300's lowest quote is not eligible, and the page says why");
  assert.match(callout, /contract start/i);
  const figures = byClass(page.el("quotes-callout"), "qx-figure"); assert.equal(figures.length, 2);
});

test("when the lowest quote is also the best eligible buy, the headline says so once", async () => {
  const page = await open(); await chooseModel(page, "Pro 6000");
  const entry = book.base.models.find((m) => m.model === "Pro 6000"); assert.equal(entry.cheapest.id, entry.best.id, "the simulator's Pro 6000 lowest quote is eligible");
  const ref = book.base.quotes.find((q) => q.id === entry.best.id).ref;
  assert.match(page.el("quotes-callout").textContent, new RegExp(ref + " is both the lowest Pro 6000 quote and the best eligible buy"));
  assertReadable(page, "Pro 6000");
});

test("when the lowest quote is eligible but another quote is cheaper all-in, the headline says which", async () => {
  const drawn = structuredClone(base); const model = drawn.models.find((m) => m.model === "B300");
  const target = drawn.quotes.find((q) => q.id === model.best.id);  // make the best eligible buy the lowest-priced quote and give the old lowest quote a higher all-in cost
  const old = drawn.quotes.find((q) => q.id === model.cheapest.id); old.eligible = true; old.ineligible_reasons = []; old.reasons = []; old.risk_adjusted = String(Number(target.risk_adjusted) + 1); old.risk_rank = 9;
  model.cheapest = { ...model.cheapest, eligible: true, ineligible_reasons: [] };
  const page = await open(drawn); const lowest = normalize(drawn).quotes.find((q) => q.id === old.id); const best = normalize(drawn).quotes.find((q) => q.id === target.id);
  const text = page.el("quotes-callout").textContent;
  assert.match(text, new RegExp("lowest B300 quote is eligible, but " + best.ref + " is cheaper all-in"));
  assert.ok(text.includes(lowest.ref) && text.includes("$" + lowest.risk_adjusted.toFixed(4)));
  assertReadable(page, "lowest eligible");
});

test("a model with no eligible quote says so and still lists every quote", async () => {
  const drawn = structuredClone(base); const model = drawn.models.find((m) => m.model === "B300"); model.best = null; model.basis = null; model.eligible = 0; model.eligible_count = 0;
  drawn.quotes.filter((q) => q.gpu === "B300").forEach((q) => { q.eligible = false; q.risk_rank = null; if (!q.ineligible_reasons.length) q.ineligible_reasons = ["simulated_quote_expired"]; q.reasons = q.ineligible_reasons; });
  const page = await open(drawn);
  assert.match(page.el("quotes-callout").textContent, /No B300 quote is eligible/); assert.match(page.el("quotes-callout").textContent, /no best buy/i);
  assert.equal(rowButtons(page).length, modelQuotes(drawn, "B300").length);
  assert.equal(byClass(page.el("quotes-ladder"), "qx-q").filter((m) => classes(m).includes("elig")).length, 0, "no solid dot"); assertReadable(page, "no eligible");
});

test("the quote ladder draws every quote once, solid when eligible and a ring when not, and calls out the lowest and the best", async () => {
  for (const entry of book.base.models) {
    const page = await open(); await chooseModel(page, entry.model);
    const quotes = book.base.quotes.filter((q) => q.gpu === entry.model); const marks = byClass(page.el("quotes-ladder"), "qx-q");
    assert.equal(marks.length, quotes.length, entry.model + ": one mark per quote");
    assert.deepEqual(marks.map((m) => m.attributes["data-id"]).sort(), quotes.map((q) => q.id).sort(), "every quote is on the ladder");
    assert.equal(marks.filter((m) => classes(m).includes("elig")).length, quotes.filter((q) => q.eligible).length);
    assert.equal(marks.filter((m) => classes(m).includes("inel")).length, quotes.filter((q) => !q.eligible).length);
    const priced = quotes.filter((q) => q.risk_adjusted !== null).length; assert.equal(byClass(page.el("quotes-ladder"), "qx-span").length, priced, "a line only where the book can price the quote all-in");
    assert.ok(byClass(page.el("quotes-ladder"), "qx-ref-low").length === 1); assert.ok(byClass(page.el("quotes-ladder"), "qx-ref-best").length <= 1);
    const names = byClass(page.el("quotes-ladder"), "qx-ref-name").map((n) => n.textContent); assert.ok(names.some((n) => /Lowest quote/.test(n)), entry.model + ": the lowest quote is named");
    marks.forEach((m) => assert.ok(m.attributes["aria-label"].includes(quotes.find((q) => q.id === m.attributes["data-id"]).ref), "marks are named by short ref"));
    assert.equal(marks.filter((m) => m.attributes.tabindex === "0").length, 1, "one tab stop on the ladder");
  }
});

test("the ladder band for each grade holds that grade's quotes, with unrated sellers in their own band", async () => {
  const page = await open(); const chips = byClass(page.el("quotes-ladder"), "ch-chip"); const letters = chips.map((c) => c.textContent.trim());
  assert.deepEqual(letters, ["A", "B", "C", "D", "U"]);
  assert.ok(classes(chips[4]).includes("g-u"), "unrated is never given a grade class from A to D");
  const counts = byClass(page.el("quotes-ladder"), "qx-band-count").map((n) => n.textContent);
  const quotes = book.base.quotes.filter((q) => q.gpu === "B300");
  ["A", "B", "C", "D", "U"].forEach((grade, i) => assert.equal(Number.parseInt(counts[i], 10), quotes.filter((q) => q.grade === grade).length, "band " + grade));
  assert.equal(quotes.filter((q) => q.grade === "U").length > 0 && base.quotes.filter((q) => q.gpu === "B300" && q.grade === null).length, quotes.filter((q) => q.grade === "U").length, "the book's null grade is the U band");
});

test("the ladder axis has round ticks, and its names never overlap", async () => {
  for (const entry of book.base.models) {
    const page = await open(); await chooseModel(page, entry.model);
    const ticks = tickLabels(page).map(Number); assert.ok(ticks.length >= 3, "at least three ticks"); assert.ok(ticks.every(Number.isFinite));
    const steps = ticks.slice(1).map((value, i) => Math.round((value - ticks[i]) * 1e6) / 1e6); assert.ok(steps.every((step) => step === steps[0]), entry.model + ": ticks are evenly spaced " + steps);
    assert.ok([1, 2, 2.5, 5].includes(Math.round(steps[0] / 10 ** Math.floor(Math.log10(steps[0])) * 100) / 100), entry.model + ": a round step " + steps[0]);
    const quotes = book.base.quotes.filter((q) => q.gpu === entry.model); const values = quotes.flatMap((q) => [q.price, q.risk_adjusted]).filter((v) => v !== null);
    assert.ok(ticks[0] <= Math.min(...values) && ticks[ticks.length - 1] >= Math.max(...values), "the axis covers every mark");
  }
});

/* The ladder module on its own, with the lowest quote and the best eligible buy pushed against each other and against the edges of the chart. */
function loadLadder() {
  const doc = { createElement: (tag) => new El(tag), createElementNS: (_, tag) => new El(tag), createTextNode: (text) => { const node = new El("#text"); node._text = String(text); return node; } };
  const window = {}; const context = vm.createContext({ window, document: doc, console });
  vm.runInContext(chartsSource, context, { filename: "workbench-charts.js" });
  vm.runInContext(fs.readFileSync(path.join(assets, "page-quotes-ladder.js"), "utf8"), context, { filename: "page-quotes-ladder.js" });
  return window.QuotesCharts;
}
const synth = (id, price, allin, grade, eligible) => ({ id, ref: "Q" + id.slice(-4), provider: "Seller " + id.slice(-1), grade, price, risk_adjusted: allin, eligible, reasons: eligible ? [] : ["Contract start has passed"], reason_codes: eligible ? [] : ["contract_start_precedes_as_of"] });
test("the ladder keeps its names apart and inside the chart when the lowest quote and the best buy sit close together or at the edges", () => {
  const { ladder } = loadLadder();
  const cases = [
    [synth("q-0001", 5.0, 5.02, "A", false), synth("q-0002", 5.01, 5.03, "A", true), synth("q-0003", 9, 9.2, "B", true)],   // lowest at the left edge, best a hair away
    [synth("q-0001", 5.0, 5.4, "A", true), synth("q-0002", 9, 9.3, "B", false), synth("q-0003", 4.9, 9.4, "D", false)],     // best at the right edge
    [synth("q-0001", 7.0, 7.001, "A", true)],                                                                                // one quote that is both
  ];
  [300, 360, 520, 760, 1000].forEach((width) => cases.forEach((quotes, n) => {
    const lowest = quotes.slice().sort((a, b) => a.price - b.price)[0]; const best = quotes.filter((q) => q.eligible).sort((a, b) => a.risk_adjusted - b.risk_adjusted)[0];
    const chart = ladder({ quotes, model: "X", width, lowestId: lowest.id, bestId: best.id, basisText: "+2.0%" });
    const svg = chart.node.children[0]; const names = byClass(svg, "qx-ref-name");
    const boxes = names.map((node) => { const x = Number(node.attributes.x); const w = node.textContent.length * 11.5 * 0.54; const end = node.attributes["text-anchor"] === "end"; return { from: end ? x - w : x, to: end ? x : x + w, y: Number(node.attributes.y) }; });
    boxes.forEach((box) => { assert.ok(box.from >= -1 && box.to <= width + 1, "case " + n + " at " + width + ": a name stays inside the chart " + JSON.stringify(box)); });
    boxes.forEach((a, i) => boxes.slice(i + 1).forEach((b) => assert.ok(a.y !== b.y ? Math.abs(a.y - b.y) >= 14 : a.to + 6 <= b.from || b.to + 6 <= a.from, "case " + n + " at " + width + ": names overlap " + JSON.stringify([a, b]))));
    assertClean(svg, "ladder case " + n + " at " + width);
  }));
});

test("hovering or focusing a mark shows its details in the chart, and clicking it selects that quote", async () => {
  const page = await open(); const chosen = book.base.quotes.find((q) => q.gpu === "B300" && q.risk_adjusted !== null && !q.eligible);
  const mark = byClass(page.el("quotes-ladder"), "qx-q").find((m) => m.attributes["data-id"] === chosen.id);
  const tip = byClass(page.el("quotes-ladder"), "qx-tip")[0]; assert.ok(!classes(tip).includes("is-on"));
  mark.listeners.get("pointerenter")[0](); assert.ok(classes(tip).includes("is-on"));
  const lines = byTag(tip, "text").map((n) => n.textContent).join("|");
  assert.ok(lines.includes(chosen.ref) && lines.includes(chosen.provider) && lines.includes(chosen.price.toFixed(4)) && lines.includes(chosen.risk_adjusted.toFixed(4)) && /not eligible/.test(lines), lines);
  assert.match(lines, /Contract start has passed/);
  mark.listeners.get("pointerleave")[0](); assert.ok(!classes(tip).includes("is-on"));
  mark.listeners.get("focus")[0](); assert.ok(classes(tip).includes("is-on")); mark.listeners.get("blur")[0]();
  await mark.listeners.get("click")[0](); await settle();
  assert.match(page.el("quotes-detail").textContent, new RegExp(chosen.ref));
  const row = byClass(page.el("quotes-table"), "selected"); assert.equal(row.length, 1); assert.match(row[0].textContent, new RegExp(chosen.ref));
});

test("arrow keys move between marks on the ladder, with one tab stop", async () => {
  const page = await open(); const marks = byClass(page.el("quotes-ladder"), "qx-q"); const sorted = marks.slice().sort((a, b) => Number(a.children.find((c) => classes(c).includes("qx-dot")).attributes.cx) - Number(b.children.find((c) => classes(c).includes("qx-dot")).attributes.cx));
  const first = sorted[0]; let prevented = 0; first.listeners.get("keydown")[0]({ key: "ArrowRight", preventDefault: () => { prevented += 1; } });
  assert.equal(prevented, 1); assert.ok(sorted[1].focused, "the next mark is focused"); assert.equal(sorted[1].attributes.tabindex, "0"); assert.equal(marks.filter((m) => m.attributes.tabindex === "0").length, 1);
});

test("the eligibility breakdown counts each reason code and names them in plain words", async () => {
  for (const entry of book.base.models) {
    const page = await open(); await chooseModel(page, entry.model);
    const quotes = book.base.quotes.filter((q) => q.gpu === entry.model); const counts = {}; quotes.forEach((q) => q.reason_codes.forEach((code) => { counts[code] = (counts[code] || 0) + 1; }));
    const chart = page.el("quotes-reasons"); const names = byClass(chart, "qx-reason-name").map((n) => n.textContent); const values = byClass(chart, "qx-reason-count").map((n) => Number(n.textContent));
    assert.equal(names[0], "Eligible"); assert.equal(values[0], quotes.filter((q) => q.eligible).length);
    assert.equal(names.length, 1 + Object.keys(counts).length);
    Object.entries(counts).forEach(([code, count]) => { const label = quotes.find((q) => q.reason_codes.includes(code)).reasons[quotes.find((q) => q.reason_codes.includes(code)).reason_codes.indexOf(code)]; const at = names.indexOf(label); assert.ok(at > 0, code + " is named \"" + label + "\""); assert.equal(values[at], count, label); });
    assert.deepEqual(values.slice(1), values.slice(1).slice().sort((a, b) => b - a), "most common reason first");
    assert.equal(byClass(chart, "qx-bar").length, names.length, "a bar for every row that has a count");
    assert.match(page.el("quotes-reasons-note").textContent, /more than one check/);
  }
});

test("the breakdown marks the reasons the lowest quote fails, which answers why it is not the buy", async () => {
  const page = await open(); const lowest = book.base.quotes.find((q) => q.id === book.base.models.find((m) => m.model === "B300").cheapest.id);
  const tagged = byClass(page.el("quotes-reasons"), "qx-reason-tag"); assert.equal(tagged.length, lowest.reason_codes.length);
  assert.ok(tagged.every((n) => n.textContent === "Lowest quote"));
});

test("the breakdown has a hidden data table, and so does the ladder", async () => {
  const page = await open(); const quotes = book.base.quotes.filter((q) => q.gpu === "B300");
  const ladderTable = byTag(page.el("quotes-ladder"), "table")[0]; assert.equal(byTag(ladderTable, "tr").length, 1 + quotes.length);
  assert.ok(byTag(ladderTable, "th").every((th) => th.attributes.scope === "col")); assert.match(byTag(ladderTable, "caption")[0].textContent, /B300/);
  assert.ok(ladderTable.textContent.includes("Not available"), "an unpriced quote's all-in cost is stated as not available");
  const reasonTable = byTag(page.el("quotes-reasons"), "table")[0]; assert.ok(byTag(reasonTable, "tr").length >= 3);
});

test("the table lists every quote for each model, in both orders, and nothing is cut off", async () => {
  for (const entry of book.base.models) {
    const page = await open(); await chooseModel(page, entry.model);
    const quotes = book.base.quotes.filter((q) => q.gpu === entry.model);
    assert.equal(rowButtons(page).length, quotes.length, entry.model + ": all rows");
    assert.deepEqual(rowRefs(page).slice().sort(), quotes.map((q) => q.ref).sort(), "every quote is a row");
    assert.match(page.el("quotes-foot").textContent, new RegExp("All " + quotes.length + " quotes are listed"));
    await page.el("sort-price").click(); await settle();
    assert.equal(rowButtons(page).length, quotes.length); const prices = rowRefs(page).map((ref) => quotes.find((q) => q.ref === ref).price);
    assert.deepEqual(prices, prices.slice().sort((a, b) => a - b), "by quoted price, lowest first");
    assert.equal(page.el("sort-price").attributes["aria-pressed"], "true"); assert.equal(page.el("sort-allin").attributes["aria-pressed"], "false");
    await page.el("sort-allin").click(); await settle();
    const refs = rowRefs(page); const eligible = quotes.filter((q) => q.eligible).sort((a, b) => a.risk_rank - b.risk_rank);
    assert.deepEqual(refs.slice(0, eligible.length), eligible.map((q) => q.ref), "eligible quotes come first in rank order");
    const rest = refs.slice(eligible.length).map((ref) => quotes.find((q) => q.ref === ref)); const priced = rest.filter((q) => q.risk_adjusted !== null);
    assert.deepEqual(priced.map((q) => q.risk_adjusted), priced.map((q) => q.risk_adjusted).slice().sort((a, b) => a - b), "then the rest by all-in cost");
    assert.ok(rest.slice(priced.length).every((q) => q.risk_adjusted === null), "quotes that cannot be priced come last");
  }
});

test("the table's group rows say how many quotes are eligible and how many are not", async () => {
  const page = await open(); const groups = findAll(page.el("quotes-table"), (n) => n.tagName === "th" && n.attributes.scope === "rowgroup");
  const quotes = book.base.quotes.filter((q) => q.gpu === "B300"); assert.equal(groups.length, 2);
  assert.match(groups[0].textContent, new RegExp("Eligible.*" + quotes.filter((q) => q.eligible).length)); assert.match(groups[1].textContent, new RegExp("Not eligible.*" + quotes.filter((q) => !q.eligible).length));
  const columns = byTag(page.el("quotes-table"), "col").length; assert.equal(groups[0].attributes.colspan, String(columns), "a group row spans the table");
  await page.el("sort-price").click(); await settle(); assert.equal(findAll(page.el("quotes-table"), (n) => n.attributes.scope === "rowgroup").length, 0, "one flat list when ordered by price");
});

test("the table prints rank, short ref, grade, both prices, premium over the lowest quote, term, down payment and standing", async () => {
  const page = await open(); const quotes = book.base.quotes.filter((q) => q.gpu === "B300"); const lowest = book.base.quotes.find((q) => q.id === book.base.models.find((m) => m.model === "B300").cheapest.id);
  const best = quotes.filter((q) => q.eligible).sort((a, b) => a.risk_rank - b.risk_rank)[0];
  const row = byTag(page.el("quotes-table"), "tr").find((tr) => tr.attributes["data-id"] === best.id); const cells = row.children.map((cell) => cell.textContent);
  assert.equal(cells[0], "1"); assert.ok(cells[1].startsWith(best.ref)); assert.ok(cells[2].includes(best.grade) && cells[2].includes(best.provider));
  assert.equal(cells[3], best.price.toFixed(4)); assert.equal(cells[4], best.risk_adjusted.toFixed(4));
  assert.equal(cells[5], "+" + ((best.risk_adjusted / lowest.price - 1) * 100).toFixed(1) + "%"); assert.equal(cells[6], best.months + " mo"); assert.equal(cells[7], Math.round(best.down_payment * 100) + "%"); assert.ok(cells[8].endsWith("Eligible"));
  const heads = byTag(page.el("quotes-table"), "th").filter((th) => th.attributes.scope === "col").map((th) => th.textContent); assert.deepEqual(heads, ["Rank", "Quote", "Seller", "Quoted", "All-in", "vs lowest", "Term", "Down", "Standing"]);
  const tags = byClass(page.el("quotes-table"), "qx-tag").map((n) => n.textContent); assert.ok(tags.includes("Best") || tags.includes("Lowest, best")); assert.ok(tags.includes("Lowest"));
});

test("an ineligible quote shows its first reason and how many more, and an unpriced quote shows a dash, never a number it does not have", async () => {
  const page = await open(); const quotes = book.base.quotes.filter((q) => q.gpu === "B300");
  const many = quotes.find((q) => q.reason_codes.length > 2); const row = byTag(page.el("quotes-table"), "tr").find((tr) => tr.attributes["data-id"] === many.id);
  assert.match(row.children[row.children.length - 1].textContent, new RegExp("\\+" + (many.reason_codes.length - 1)));
  assert.ok(row.attributes.title.includes(many.reasons[1]), "the full reasons are in the row's title");
  const unpriced = quotes.filter((q) => q.risk_adjusted === null); assert.ok(unpriced.length > 0);
  unpriced.forEach((q) => { const tr = byTag(page.el("quotes-table"), "tr").find((r) => r.attributes["data-id"] === q.id); assert.equal(tr.children[4].textContent, "—"); assert.equal(tr.children[5].textContent, "—"); });
});

test("rows are keyboard-selectable: one tab stop, the arrow keys move the selection, and Enter on a row opens it", async () => {
  const page = await open(); const buttons = rowButtons(page); const stops = buttons.filter((b) => b.attributes.tabindex === "0"); assert.equal(stops.length, 1, "one tab stop in the table");
  assert.equal(stops[0].attributes["aria-current"], "true");
  const order = rowRefs(page); const selected = stops[0].textContent; const at = order.indexOf(selected);
  let prevented = 0; await stops[0].listeners.get("keydown")[0]({ key: "ArrowDown", preventDefault: () => { prevented += 1; } }); await settle();
  assert.equal(prevented, 1); assert.match(page.el("quotes-detail").textContent, new RegExp(order[at + 1]));
  assert.equal(rowButtons(page).filter((b) => b.attributes["aria-current"] === "true")[0].textContent, order[at + 1]);
  assert.ok(buttonFor(page, order[at + 1]).focused, "focus follows the selection");
  await buttonFor(page, order[0]).listeners.get("keydown")[0]({ key: "End", preventDefault() {} }); await settle(); assert.match(page.el("quotes-detail").textContent, new RegExp(order[order.length - 1]));
  await buttonFor(page, order[3]).click(); await settle(); assert.match(page.el("quotes-detail").textContent, new RegExp(order[3]));
});

test("the table region keeps its scroll position, and the selection, across polls and a changed book", async () => {
  const page = await open(); const region = page.el("quotes-scroll"); region.scrollTop = 240;
  const refs = rowRefs(page); const picked = refs[11]; await buttonFor(page, picked).click(); await settle();
  assert.equal(region.scrollTop, 240, "choosing a row does not move the table");
  page.server.snapshot = war; page.server.tag = 'W/"two"'; page.poll(); await settle();
  assert.equal(region.scrollTop, 240, "a new book does not move the table");
  assert.deepEqual(rowRefs(page).slice().sort(), refs.slice().sort(), "the same quotes");
  const selected = byClass(page.el("quotes-table"), "selected"); assert.equal(selected.length, 1); assert.match(selected[0].textContent, new RegExp(picked));
  assert.match(page.el("quotes-detail").textContent, new RegExp(picked));
  assert.ok(classes(byClass(page.el("quotes-ladder"), "qx-q").find((m) => m.attributes["data-id"] === book.base.quotes.find((q) => q.ref === picked).id)).includes("is-selected"), "the ladder marks the same quote");
  page.poll(); await settle(); page.poll(); await settle(); assert.match(page.el("quotes-detail").textContent, new RegExp(picked));
});

test("a refresh puts keyboard focus back on the row that had it", async () => {
  const page = await open(); const target = rowRefs(page)[4]; const before = buttonFor(page, target); before.focused = true; page.doc.activeElement = before;
  page.server.snapshot = war; page.server.tag = 'W/"two"'; page.poll(); await settle();
  const after = buttonFor(page, target); assert.notEqual(after, before, "the row was redrawn"); assert.ok(after.focused, "and the new row has focus");
  assert.equal(after.attributes["data-fk"], "row:" + book.base.quotes.find((q) => q.ref === target).id);
});

test("changing model starts from that model's best eligible quote, and the selection stays on the model's own quotes", async () => {
  const page = await open(); await buttonFor(page, rowRefs(page)[9]).click(); await settle();
  await chooseModel(page, "H100"); const entry = book.base.models.find((m) => m.model === "H100"); const best = book.base.quotes.find((q) => q.id === entry.best.id);
  assert.match(page.el("quotes-detail").textContent, new RegExp(best.ref)); assert.equal(byClass(page.el("quotes-table"), "selected").length, 1);
  assert.ok(rowButtons(page).every((b) => book.base.quotes.find((q) => q.ref === b.textContent && q.gpu === "H100")), "only H100 quotes");
});

test("if the selected quote leaves the book, the page falls back to the best quote instead of showing nothing", async () => {
  const page = await open(); const gone = rowRefs(page)[12]; await buttonFor(page, gone).click(); await settle();
  const smaller = structuredClone(base); const id = book.base.quotes.find((q) => q.ref === gone).id; smaller.quotes = smaller.quotes.filter((q) => q.id !== id);
  page.server.snapshot = smaller; page.server.tag = 'W/"two"'; page.poll(); await settle();
  assert.ok(!rowRefs(page).includes(gone)); assert.equal(byClass(page.el("quotes-table"), "selected").length, 1); assertReadable(page, "after withdrawal");
});

test("the detail panel shows standing, the cost parts, the seller scorecard and terms, and reads like text", async () => {
  const page = await open(); const best = book.base.quotes.find((q) => q.id === book.base.models.find((m) => m.model === "B300").best.id);
  const provider = book.base.providers.find((p) => p.id === best.provider_id); const detail = page.el("quotes-detail"); const text = detail.textContent;
  assert.match(text, new RegExp(best.ref)); assert.ok(text.includes(best.provider)); assert.match(text, /Eligible/); assert.match(text, /Ranked 1 of 7 eligible quotes/);
  ["$" + best.price.toFixed(4), "$" + best.financing.toFixed(4), "$" + best.exposure.toFixed(4), "$" + best.risk_adjusted.toFixed(4)].forEach((value) => assert.ok(text.includes(value), value + " is printed"));
  assert.ok(byClass(detail, "ch-part").length >= 2, "the cost bar has its parts");
  assert.match(text, /Scorecard method: \$/); assert.match(text, /alternatives and are not added/);
  const scorecard = byClass(detail, "qx-scorecard")[0]; assert.equal(byTag(scorecard, "tr").length, Object.keys(book.base.assumptions.weights).length, "six categories");
  Object.entries(provider.tiers).forEach(([key, tier]) => assert.ok(scorecard.textContent.includes(tier + " of 4")));
  assert.equal(byClass(scorecard, "pips").length, 6); assert.equal(byClass(scorecard, "pip").length, 24, "four pips per category, on the 0 to 4 scale the server uses");
  ["Contract value", "Down payment", "Payment terms", "Contract start", "Expires", "Location", "Interconnect", "Cooling"].forEach((label) => assert.ok(text.includes(label), label));
  assert.ok(text.includes(best.exact.price + " per GPU-hour"), "the exact quoted price from the server");
  assertReadable(page, "detail");
});

test("the terms say whether a quote is above or below the simulation's reference price, in the direction the server's discount means", async () => {
  const page = await open(); const quotes = book.base.quotes.filter((q) => q.gpu === "B300"); const reference = book.base.models.find((m) => m.model === "B300").reference;
  const cheap = quotes.find((q) => q.price < reference); const dear = quotes.find((q) => q.price > reference);
  for (const [q, word] of [[cheap, "below"], [dear, "above"]]) {
    await buttonFor(page, q.ref).click(); await settle(); const fact = byTag(page.el("quotes-detail"), "div").find((d) => d.children.length === 2 && d.children[0].textContent === "Against simulation reference");
    assert.equal(fact.children[1].textContent, (Math.abs(q.discount_to_reference) * 100).toFixed(1) + "% " + word + " $" + reference.toFixed(2), q.ref + " at " + q.price + " against " + reference);
  }
});

test("the notes under a quote are plain sentences, and a note the page does not know is humanised, never shown as a code", async () => {
  const page = await open(); const notes = byClass(page.el("quotes-detail"), "qx-notes")[0]; const items = byTag(notes, "li").map((n) => n.textContent);
  const flags = base.quotes[0].flags; assert.equal(items.length, flags.length);
  assert.ok(items.every((line) => /^[A-Z].*[.]$/.test(line) && !line.includes("_")), items.join(" | "));
  assert.ok(items.some((line) => /Financing assumes the down payment is held for the whole contract term/.test(line)));
  assert.ok(items.some((line) => /never added together/i.test(line)));
  const odd = structuredClone(base); odd.quotes.forEach((q) => { q.flags = [...q.flags, "payment_terms_were_estimated_from_peers", "x"]; });
  const other = await open(odd); const lines = byTag(byClass(other.el("quotes-detail"), "qx-notes")[0], "li").map((n) => n.textContent);
  assert.ok(lines.includes("Payment terms were estimated from peers.")); assert.ok(lines.includes("X.")); assertReadable(other, "unknown notes");
});

test("a quote the book cannot price says why and prints no all-in cost", async () => {
  const page = await open(); const quotes = book.base.quotes.filter((q) => q.gpu === "B300");
  const noDeposit = quotes.find((q) => q.risk_adjusted === null && q.down_payment === null);
  await buttonFor(page, noDeposit.ref).click(); await settle(); const text = page.el("quotes-detail").textContent;
  assert.match(text, /All-in cost not available/); assert.match(text, /No down payment is stated, so financing and expected loss cannot be costed/);
  assert.ok(text.includes("$" + noDeposit.price.toFixed(4))); assert.equal((text.match(/Not available/g) || []).length, 2, "financing and expected loss are each stated as not available");
  assert.equal(byClass(page.el("quotes-detail"), "qx-costbar").length, 0, "no bar for a cost that does not exist");
  assert.ok(!/Scorecard method/.test(text), "no scorecard alternative either"); assertReadable(page, "unpriced");
  assert.equal(byClass(page.el("quotes-detail"), "qx-reasons-list").length, 0);
});

test("an unrated seller is shown as unrated, never as a grade, and its missing score does not break the panel", async () => {
  const page = await open(); const unrated = book.base.quotes.find((q) => q.gpu === "B300" && q.grade === "U" && q.financing !== null);
  assert.ok(unrated, "the book has an unrated seller with a financing figure");
  await buttonFor(page, unrated.ref).click(); await settle(); const detail = page.el("quotes-detail"); const text = detail.textContent;
  const chip = byClass(detail, "grade")[0]; assert.equal(chip.textContent, "U"); assert.ok(classes(chip).includes("g-u")); assert.equal(chip.attributes.title, "Unrated seller");
  assert.match(text, /Not scored/); assert.match(text, /no grade/i); assert.match(text, /not a zero rating/);
  assert.ok(text.includes("$" + unrated.financing.toFixed(4)), "the financing it does have is printed"); assert.match(text, /Expected loss.*Not available/);
  const row = byTag(page.el("quotes-table"), "tr").find((tr) => tr.attributes["data-id"] === unrated.id); assert.equal(byClass(row, "grade")[0].textContent, "U"); assertReadable(page, "unrated");
  assert.ok(!classes(chip).some((c) => /^g-[a-d]$/.test(c)));
});

test("an ineligible quote lists each reason as a sentence with its dates", async () => {
  const page = await open(); const q = book.base.quotes.find((x) => x.gpu === "B300" && x.reason_codes.includes("simulated_quote_expired"));
  await buttonFor(page, q.ref).click(); await settle(); const reasons = byTag(byClass(page.el("quotes-detail"), "qx-why")[0], "li").map((n) => n.textContent);
  assert.equal(reasons.length, q.reason_codes.length);
  assert.ok(reasons.some((line) => /The contract starts \d+ [A-Z][a-z]{2} \d{4}, before the book date of 1 Jun 2032\./.test(line)), reasons.join("|"));
  assert.ok(reasons.some((line) => /The quote expired on \d+ [A-Z][a-z]{2} \d{4}\./.test(line)));
  assert.match(page.el("quotes-detail").textContent, /Not eligible/);
});

test("Price this quote hands off the selected quote's key and the exact decimal the server sent", async () => {
  const page = await open(base, { priceQuote: true });
  const chosen = book.base.quotes.filter((q) => q.gpu === "B300").sort((a, b) => (a.risk_rank ?? 1e9) - (b.risk_rank ?? 1e9) || a.price - b.price)[0];
  assert.equal(rowRefs(page)[0], chosen.ref, "the top row is the best all-in quote");
  await buttonFor(page, chosen.ref).click(); await settle();
  await page.button("quotes-detail", "Price this quote").click();
  assert.equal(page.priced.length, 1); assert.equal(page.priced[0].id, chosen.id, "the full id is the key");
  assert.equal(page.priced[0].price, chosen.exact.price, "the exact decimal, not a rounded number"); assert.equal(typeof page.priced[0].price, "string");
  const war_quote = war.quotes.find((q) => q.price !== base.quotes.find((b) => b.id === q.id).price); assert.ok(war_quote);
  page.server.snapshot = war; page.server.tag = 'W/"two"'; page.poll(); await settle(); await buttonFor(page, war_quote.id.replace(/^.*-(\d+)$/, "Q$1")).click(); await settle();
  await page.button("quotes-detail", "Price this quote").click(); assert.equal(page.priced.at(-1).price, war_quote.price, "prices with more than four decimals stay whole");
});

test("without a pricing handler the button simply opens Pricing", async () => {
  const page = await open(); await page.button("quotes-detail", "Price this quote").click(); assert.equal(page.shown.at(-1), "pricing");
});

test("figures in the headline open that quote", async () => {
  const page = await open(); const lowest = book.base.quotes.find((q) => q.id === book.base.models.find((m) => m.model === "B300").cheapest.id);
  await findAll(page.el("quotes-callout"), (n) => n.tagName === "button" && n.textContent === lowest.ref)[0].click(); await settle();
  assert.match(page.el("quotes-detail").textContent, new RegExp(lowest.ref)); assert.match(byClass(page.el("quotes-table"), "selected")[0].textContent, new RegExp(lowest.ref));
});

test("the first draw of a model animates, a refresh of the same book does not, and a new model does", async () => {
  const page = await open(); const entering = () => ({ ladder: classes(byTag(page.el("quotes-ladder"), "svg")[0]).includes("qx-enter"), reasons: classes(byTag(page.el("quotes-reasons"), "svg")[0]).includes("qx-enter") });
  assert.deepEqual(entering(), { ladder: true, reasons: true }, "first draw");
  page.server.snapshot = war; page.server.tag = 'W/"two"'; page.poll(); await settle(); assert.deepEqual(entering(), { ladder: false, reasons: false }, "a refresh redraws without the entrance");
  await buttonFor(page, rowRefs(page)[2]).click(); await settle(); assert.deepEqual(entering(), { ladder: false, reasons: false }, "choosing a quote does not re-animate");
  await page.el("sort-price").click(); await settle(); assert.deepEqual(entering(), { ladder: false, reasons: false }, "sorting does not either");
  await chooseModel(page, "H200"); assert.deepEqual(entering(), { ladder: true, reasons: true }, "a model that has not been drawn yet");
  page.host.showView("desk"); await settle(); page.host.showView("quotes"); await settle(); assert.deepEqual(entering(), { ladder: true, reasons: true }, "coming back to the page");
});

test("the table adapts to a narrow region by leaving out columns, and keeps the seller and both prices", async () => {
  const page = makePage(base); page.connect(); await settle();
  const region = page.el("quotes-scroll"); region.clientWidth = 600; page.host.showView("quotes"); await settle();
  let heads = byTag(page.el("quotes-table"), "th").filter((th) => th.attributes.scope === "col").map((th) => th.textContent);
  assert.deepEqual(heads, ["Rank", "Quote", "Seller", "Quoted", "All-in", "vs lowest", "Standing"].filter((name) => name !== "Rank" && name !== "vs lowest" && name !== "Standing"), "compact");
  assert.ok(classes(page.el("quotes-table")).includes("qx-compact")); assert.match(page.el("quotes-table").textContent, /Start has passed/, "the reason moves under the seller");
  region.clientWidth = 760; page.server.tag = 'W/"two"'; page.poll(); await settle();
  heads = byTag(page.el("quotes-table"), "th").filter((th) => th.attributes.scope === "col").map((th) => th.textContent); assert.deepEqual(heads, ["Rank", "Quote", "Seller", "Quoted", "All-in", "vs lowest", "Standing"]);
  const group = findAll(page.el("quotes-table"), (n) => n.attributes.scope === "rowgroup")[0]; assert.equal(group.attributes.colspan, "7");
});

test("an empty book, a book with no quotes for the model, and a failed read are each said plainly", async () => {
  const empty = structuredClone(base); empty.quotes = []; empty.models = [];
  const page = await open(empty); assert.match(page.el("quotes-callout").textContent, /no quotes/i); assert.equal(rowButtons(page).length, 0); assertClean(page.el("quotes-callout"));
  const none = structuredClone(base); none.quotes = none.quotes.filter((q) => q.gpu !== "B300"); none.models.find((m) => m.model === "B300").cheapest = null; none.models.find((m) => m.model === "B300").best = null;
  const second = await open(none); assert.match(second.el("quotes-callout").textContent, /No B300 quotes in the book/); assert.equal(rowButtons(second).length, 0);
  assert.match(second.el("quotes-ladder").textContent, /No B300 quotes/); assert.match(second.el("quotes-detail").textContent, /Select a quote/); [ "quotes-ladder", "quotes-reasons", "quotes-table", "quotes-detail"].forEach((id) => assertClean(second.el(id), id));
  const failed = makePage(base); failed.server.failure = "The simulated book is unreachable."; failed.connect(); await settle(); failed.host.showView("quotes"); await settle();
  assert.match(failed.el("quotes-callout").textContent, /unreachable/); assert.equal(failed.el("quotes-table").children.length, 0); assertClean(failed.el("quotes-callout"));
  failed.server.failure = ""; failed.poll(); await settle(); assert.ok(rowButtons(failed).length > 0, "the page recovers when the book comes back");
});

test("a quote with missing prices or terms never prints NaN, undefined or a raw code anywhere on the page", async () => {
  const odd = structuredClone(base);
  odd.quotes.forEach((q, i) => { if (i % 5 === 0) { q.price = "8"; } if (i % 7 === 0) { q.months = null; q.down_payment = null; q.financing = null; q.exposure = null; q.risk_adjusted = null; q.risk_adjusted_scorecard = null; q.contract_value = null; q.payment_days = null; q.expires = null; q.days_to_expiry = null; q.location = null; q.interconnect = null; q.cooling = null; q.lead_weeks = null; q.discount_to_reference = null; q.failure_probability = null; q.reasons = ["strange_new_reason"]; q.ineligible_reasons = ["strange_new_reason"]; q.eligible = false; } });
  odd.providers.forEach((p, i) => { if (i % 4 === 0) { p.score = null; p.tiers = {}; } if (i % 5 === 0) p.grade = null; });
  odd.models.forEach((m) => { m.reference = null; m.basis = null; });
  const page = await open(odd);
  for (const entry of book.base.models) {
    await chooseModel(page, entry.model); assertReadable(page, "odd " + entry.model);
    for (const ref of rowRefs(page).slice(0, 32)) { await buttonFor(page, ref).click(); await settle(); assertClean(page.el("quotes-detail"), "detail " + ref); assert.doesNotMatch(page.el("quotes-detail").textContent, SNAKE, ref); }
  }
  assert.match(allText(page), /Strange new reason/, "an unknown reason is humanised");
});

test("the Quotes view still lists its controls and handlers, and the chart files load directly after the page file", () => {
  ["quotes-controls", "quotes-models", "sort-allin", "sort-price", "quotes-callout", "quotes-ladder", "quotes-reasons", "quotes-reasons-note", "quotes-scroll", "quotes-table", "quotes-foot", "quotes-detail"].forEach((id) => assert.ok(new RegExp('id="' + id + '"').test(html), id + " is in index.html"));
  const scripts = [...html.matchAll(/<script src="\/workbench\/assets\/([^"]+)" defer><\/script>/g)].map((m) => m[1]); const at = scripts.indexOf("page-quotes.js");
  assert.ok(at >= 0 && scripts.slice(at + 1, at + 3).every((name) => /^page-quotes-[a-z-]+\.js$/.test(name)), "page-quotes-*.js follow page-quotes.js: " + scripts.slice(at, at + 4));
  ["page-quotes-ladder.js", "page-quotes-reasons.js"].forEach((name) => assert.ok(scripts.includes(name), name));
  const css = fs.readFileSync(path.join(assets, "quotes.css"), "utf8"); assert.doesNotMatch(css, /\bstyle\s*=|!important/);
});

test("every colour the Quotes stylesheet reads is a token the shared stylesheet defines in both themes", () => {
  const css = fs.readFileSync(path.join(assets, "quotes.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, ""); const shared = fs.readFileSync(path.join(assets, "workbench.css"), "utf8");
  const used = new Set([...css.matchAll(/var\((--[a-z0-9-]+)\)/g)].map((m) => m[1])); const own = new Set([...css.matchAll(/(--[a-z0-9-]+)\s*:/g)].map((m) => m[1]));
  const root = shared.slice(shared.indexOf(":root {"), shared.indexOf(':root[data-theme="dark"]')); const dark = shared.slice(shared.indexOf(':root[data-theme="dark"]'), shared.indexOf("@media (prefers-color-scheme: dark)"));
  [...used].filter((name) => !own.has(name) && !["--ease", "--fast", "--r", "--r-sm", "--r-lg", "--font", "--mono", "--shadow-pop"].includes(name)).forEach((name) => { assert.ok(root.includes(name + ":"), name + " exists in the light tokens"); });
  ["--accent", "--faint", "--canvas", "--surface", "--ink", "--ink-soft", "--muted", "--border", "--accent-soft", "--control-border", "--focus"].forEach((name) => { assert.ok(dark.includes(name + ":"), name + " has a dark value"); });
});
