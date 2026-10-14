"use strict";
// The landing page's chart engine (landing-charts.js) and the Brief's use of it, drawn from the real simulator's snapshots in the
// browserless DOM (demo_harness.js): 1:1 width, one svg kept across polls, in-place patches, a tooltip drawn in the chart, a hidden
// table per chart, one precision rule, and graceful degradation. The fake DOM throws on inline styles, as the CSP would.
const { test } = require("node:test");
const { assert, El, walk, classes, byClass, byTag, settle, assertClean, makePage, base, book, layout, assertLive } = require("./demo_harness.js");
const BRIEF_SLOTS = ["brief-live", "brief-facts", "brief-fact-gaps", "brief-gaps", "brief-fact-cost", "brief-anatomy", "brief-fact-grades", "brief-grades", "brief-weights", "brief-eligible", "brief-basis-live"];

/* ---- The landing charts (landing-charts.js): drawn at their own width, patched in place, never rebuilt under the pointer ---- */
const CHARTS = ["brief-live", "brief-gaps", "brief-anatomy", "brief-grades", "brief-weights"];
const chartParts = (page, id) => { const host = page.el(id).children[0]; const [svg, hits, twin] = host.children; return { host, svg, hits, twin, table: twin.children[0] }; };
const textsOf = (node, name) => byClass(node, name).map((item) => item.textContent);
const heroTicks = (page) => textsOf(chartParts(page, "brief-live").svg, "bf-tick");
const withBook = (mutate, from = base) => { const data = structuredClone(from); mutate(data); return data; };
let serial = 0;
async function show(page, data) { page.server.snapshot = data; page.server.tag = 'W/"landing-' + (++serial) + '"'; await page.poll(); await settle(); }
function setBasis(data, model, basis) {  // the best eligible all-in price that gives this model that basis over its lowest quote
  const entry = data.models.find((item) => item.model === model); entry.best.risk_adjusted = Number((Number(entry.cheapest.price) * (1 + basis)).toFixed(4)); entry.basis = basis;
}
function fakeResize() {
  const observers = [];
  class Watcher { constructor(callback) { this.callback = callback; this.nodes = []; observers.push(this); } observe(node) { this.nodes.push(node); } disconnect() { this.nodes = []; } }
  return { observers, ResizeObserver: Watcher, trigger: (width) => observers.forEach((watcher) => watcher.nodes.forEach((node) => watcher.callback([{ target: node, contentRect: { width } }]))) };
}
const spacedText = (node) => { const out = []; walk(node, (item) => { if (item._text) out.push(item._text); }); return out.join(" "); };  // textContent runs table cells together
const quiet = async (action) => { const original = console.error; console.error = () => {}; try { return await action(); } finally { console.error = original; } };

test("a poll that changes nothing printed leaves every chart, its table and its slot untouched", async () => {
  const page = makePage(base, { width: 520 }); page.connect(); await settle();
  const before = CHARTS.map((id) => chartParts(page, id)); const slots = CHARTS.map((id) => [...page.el(id).children]);
  let replaced = 0; before.forEach(({ host }) => { const original = host.replaceChildren.bind(host); host.replaceChildren = (...nodes) => { replaced += 1; return original(...nodes); }; });
  await show(page, withBook((data) => { data.meta.tick += 1; }));
  CHARTS.forEach((id, index) => {
    const now = chartParts(page, id);
    assert.equal(now.svg, before[index].svg, id + " keeps its svg"); assert.equal(now.hits, before[index].hits, id + " keeps its row targets"); assert.equal(now.table, before[index].table, id + " keeps its table");
    page.el(id).children.forEach((child, i) => assert.equal(child, slots[index][i], id + " keeps its slot's children"));
  });
  assert.equal(replaced, 0, "nothing inside a chart host was replaced");
});

test("a changed number moves its bar in place: the same svg, the same bar node, new geometry and a new table cell", async () => {
  const page = makePage(base, { width: 520 }); page.connect(); await settle();
  const { svg, hits, table } = chartParts(page, "brief-live"); const bar = byClass(svg, "bf-bar")[0]; const was = { d: bar.attributes.d, value: textsOf(svg, "bf-value")[0], cell: table.textContent };
  await show(page, withBook((data) => setBasis(data, "B300", 0.12)));
  const now = chartParts(page, "brief-live");
  assert.equal(now.svg, svg); assert.equal(now.hits, hits); assert.equal(byClass(now.svg, "bf-bar")[0], bar, "the bar element itself is reused");
  assert.notEqual(bar.attributes.d, was.d, "its path moved"); assert.notEqual(textsOf(now.svg, "bf-value")[0], was.value); assert.match(textsOf(now.svg, "bf-value")[0], /^\+1[12]\.\d%$/);
  assert.notEqual(now.table.textContent, was.cell, "the table twin follows the chart");
  assert.match(byClass(hits, "bf-hit")[0].attributes["aria-label"], /basis \+1[12]\.\d%/, "so does the row's spoken label");
});

test("the hero axis only grows, so a bar crossing a round number never rescales the others, and an epoch change starts it again", async () => {
  const page = makePage(base, { width: 560 }); page.connect(); await settle();
  const widest = Math.max(...book.base.models.map((entry) => (entry.basis === null ? 0 : entry.basis * 100)));
  const reach = Math.max(20, Math.ceil((widest * 1.1) / 10) * 10); const start = Array.from({ length: reach / 10 + 1 }, (_, i) => String(i * 10)); start[start.length - 1] += "%";
  assert.deepEqual(heroTicks(page), start, "the axis stops at the first multiple of 10 that holds the widest basis with 10% to spare");
  const probe = () => byClass(chartParts(page, "brief-live").svg, "bf-bar")[1].attributes.d;  // the second bar
  const before = probe();
  await show(page, withBook((data) => setBasis(data, "B300", 0.31)));
  assert.deepEqual(heroTicks(page), ["0", "10", "20", "30", "40%"], "one basis passing 27% adds a step");
  const grown = probe(); assert.notEqual(grown, before, "the others shrink once, when the axis grows");
  await show(page, withBook((data) => { data.meta.tick += 1; }));
  assert.deepEqual(heroTicks(page), ["0", "10", "20", "30", "40%"], "and the axis does not shrink back when it falls");
  assert.equal(probe(), grown, "so the same number draws the same bar");
  await show(page, withBook((data) => { data.meta.epoch += 1; }));
  assert.deepEqual(heroTicks(page), start, "a new epoch (a reset book) starts the axis again");
  assert.equal(probe(), before);
});

test("every gridline and the zero baseline sit on a half pixel so they are one crisp pixel wide", async () => {
  const page = makePage(base, { width: 520 }); page.connect(); await settle();
  CHARTS.forEach((id) => {
    const { svg } = chartParts(page, id); const grid = byClass(svg, "bf-grid")[0]; const zero = byClass(svg, "bf-base")[0];
    assert.ok(grid && zero, id + " draws gridlines and a baseline");
    [grid.attributes.d, zero.attributes.d].forEach((d) => [...d.matchAll(/M([\d.]+) /g)].forEach((match) => assert.equal(Number(match[1]) % 1, 0.5, id + " line at " + match[1] + " is not on a half pixel")));
  });
});

test("tick labels thin out before they crowd, the unit stays on the last one shown, and the gridlines never thin", () => {
  const { landing } = makePage(base);
  const draw = (width) => {
    layout.width = width; const host = new El("div"); host.className = "bf-chart-host";
    landing.bars(host, { rows: [{ key: "a", value: 12, text: "12%" }, { key: "b", value: 30, text: "30%" }], axis: { step: 10, floor: 40, format: (value, last) => value + (last ? "%" : "") } });
    const svg = host.children[0]; return { labels: textsOf(svg, "bf-tick"), lines: byClass(svg, "bf-grid")[0].attributes.d.match(/M/g).length };
  };
  const wide = draw(400); const narrow = draw(170);
  assert.deepEqual(wide.labels, ["0", "10", "20", "30", "40%"]); assert.deepEqual(narrow.labels, ["0", "20", "40%"], "every other label, the unit on the last one");
  assert.equal(narrow.lines, wide.lines, "the same gridlines at any width");
});

test("charts draw 1:1 at the width of their slot, capped, and redraw when the slot's width changes", async () => {
  const seen = fakeResize(); const page = makePage(base, { width: 480, browser: { ResizeObserver: seen.ResizeObserver } }); page.connect(); await settle();
  const view = (id) => chartParts(page, id).svg.attributes;
  assert.match(view("brief-live").viewBox, /^0 0 480 \d+$/); assert.equal(view("brief-live").width, "480"); assert.equal(view("brief-gaps").width, "480");
  assert.equal(seen.observers.length, CHARTS.length, "one observer per chart slot");
  const first = chartParts(page, "brief-live").svg;
  seen.trigger(480); assert.equal(chartParts(page, "brief-live").svg, first, "the same width again is not a reason to draw");
  page.resize(900); seen.trigger(900);
  assert.match(view("brief-live").viewBox, /^0 0 600 \d+$/, "the hero chart stops at 600"); assert.match(view("brief-gaps").viewBox, /^0 0 520 \d+$/, "the problem charts stop at 520"); assert.match(view("brief-weights").viewBox, /^0 0 440 \d+$/);
  assert.equal(byClass(page.el("brief-live"), "bf-grow").length, 0, "a redraw is not an entrance");
  page.resize(260); seen.trigger(260); CHARTS.forEach((id) => { assert.match(view(id).viewBox, /^0 0 260 \d+$/); assertClean(page.el(id), id + " at 260px"); });
  const narrow = chartParts(page, "brief-live").svg; page.resize(0); seen.trigger(0);
  assert.equal(chartParts(page, "brief-live").svg, narrow, "a hidden slot is left as it was");
  page.resize(700); seen.trigger(700); assert.match(view("brief-live").viewBox, /^0 0 600 \d+$/, "and it draws again once it has a width");
});

test("a slot that is hidden when the book arrives is not drawn into; it draws when it gets a width", async () => {
  const seen = fakeResize(); const page = makePage(base, { width: 0, browser: { ResizeObserver: seen.ResizeObserver } }); page.connect(); await settle();
  CHARTS.forEach((id) => assert.equal(page.el(id).children[0].children.length, 0, id + " draws nothing at width 0"));
  page.resize(500); seen.trigger(500);
  CHARTS.forEach((id) => assert.ok(chartParts(page, id).svg, id + " draws once visible"));
});

test("without a layout engine the charts fall back to their own width", async () => {
  const page = makePage(base); page.connect(); await settle();
  assert.match(chartParts(page, "brief-live").svg.attributes.viewBox, /^0 0 600 \d+$/); assert.match(chartParts(page, "brief-gaps").svg.attributes.viewBox, /^0 0 520 \d+$/);
});

test("the observers are released when the book is cleared", async () => {
  const seen = fakeResize(); const page = makePage(base, { width: 500, browser: { ResizeObserver: seen.ResizeObserver } }); page.connect(); await settle();
  assert.ok(seen.observers.some((watcher) => watcher.nodes.length === 1));
  page.server.session = false; page.disconnect(); await settle();
  assert.ok(seen.observers.every((watcher) => watcher.nodes.length === 0), "every observer is disconnected with its slot");
});

test("zero rows, one row and a book with nothing eligible all draw clean, labelled charts", async () => {
  const none = makePage(withBook((data) => { data.models = []; data.kpis.basis = null; }), { width: 520 }); none.connect(); await settle(); assertLive(none);
  assert.match(chartParts(none, "brief-live").svg.textContent, /Nothing to show yet/); assert.equal(byClass(none.el("brief-live"), "bf-bar").length, 0);
  BRIEF_SLOTS.forEach((id) => assertClean(none.el(id), id));
  const lone = makePage(withBook((data) => { data.models = data.models.slice(0, 1); }), { width: 520 }); lone.connect(); await settle();
  assert.equal(byClass(chartParts(lone, "brief-live").svg, "bf-row").length, 2, "one model and the All models row");
  BRIEF_SLOTS.forEach((id) => assertClean(lone.el(id), id));
  const stuck = makePage(withBook((data) => { data.models.forEach((entry) => { entry.best = null; entry.basis = null; }); data.kpis.basis = null; }), { width: 520 }); stuck.connect(); await settle();
  assert.equal(textsOf(chartParts(stuck, "brief-live").svg, "bf-note").filter((text) => text === "No eligible seller").length, base.models.length, "every row says so in place of a bar");
});

test("the engine takes hostile input and still prints no NaN, undefined or Infinity", () => {
  const { landing } = makePage(base); layout.width = 320;
  const host = new El("div"); host.className = "bf-chart-host";
  landing.bars(host, { rows: [{ key: "a", label: undefined, value: NaN, text: "NaN" }, { label: null, value: Infinity, sub: "undefined", text: "[object Object]" }, { value: -5 }, { label: "x".repeat(300), value: 1e12, text: "$" + 1e12 }, { parts: [{ value: NaN }, { value: 1e-12 }, { value: null }] }, null, undefined, "text", { key: "a", label: "duplicate key", value: 3, chip: "D", tip: { head: NaN, lines: [undefined, null, "ok"] } }],
    axis: { step: 10, floor: 20 }, title: undefined, description: NaN, table: { head: [undefined] } });
  assertClean(host, "hostile rows"); assert.ok(byTag(host, "svg").length >= 1);
  const empty = new El("div"); empty.className = "bf-chart-host"; landing.bars(empty, { rows: [] }); assertClean(empty, "no rows"); landing.bars(empty, undefined); landing.bars(empty, {});
  assert.doesNotThrow(() => landing.bars(null, {}));
});

test("a chart that fails is logged and skipped; the poll, the status and the other charts carry on", async () => {
  await quiet(async () => {
    const { landing } = makePage(base); const host = new El("div"); host.className = "bf-chart-host";
    assert.doesNotThrow(() => landing.bars(host, { get rows() { throw new Error("boom"); } }));
    const page = makePage(base, { width: 520 }); const failing = page.el("brief-gaps"); const replaceChildren = failing.replaceChildren.bind(failing);
    failing.replaceChildren = () => { throw new Error("this slot cannot be drawn"); };
    page.connect(); await settle();
    assertLive(page); assert.equal(failing.children.length, 0, "the failed slot is skipped");
    assert.ok(chartParts(page, "brief-live").svg && chartParts(page, "brief-weights").svg, "the other charts still draw"); assert.match(page.el("brief-eligible").textContent, /of/);
    failing.replaceChildren = replaceChildren; await show(page, withBook(() => {})); assertLive(page); assert.ok(chartParts(page, "brief-gaps").svg, "and the next good poll draws it");
  });
});

test("a chart is never rebuilt under the pointer or the keyboard focus, but its numbers still move in place", async () => {
  for (const state of [":hover", ":focus-within"]) {
    const page = makePage(base, { width: 520 }); page.connect(); await settle();
    const { svg, hits } = chartParts(page, "brief-live"); const rows = byClass(svg, "bf-row").length; const bar = byClass(svg, "bf-bar")[0];
    hits.matches = (query) => query === state;
    const moved = bar.attributes.d;
    await show(page, withBook((data) => setBasis(data, "B300", 0.12)));
    assert.equal(chartParts(page, "brief-live").svg, svg, state + ": the svg stays"); assert.notEqual(bar.attributes.d, moved, state + ": a changed number still moves its bar");
    await show(page, withBook((data) => { data.models = data.models.slice(0, 3); }));
    assert.equal(chartParts(page, "brief-live").svg, svg, state + ": a changed set of rows waits"); assert.equal(byClass(svg, "bf-row").length, rows);
    hits.matches = () => false; hits.fire("pointerleave"); await settle();
    const now = chartParts(page, "brief-live"); assert.notEqual(now.svg, svg, state + ": it is rebuilt as soon as the pointer or focus is gone");
    assert.equal(byClass(now.svg, "bf-row").length, 4, "with the rows it was waiting to draw (three models and the All models row)");
  }
});

test("each row has a focusable target; a tooltip drawn in the chart follows hover, focus and tap, and Escape closes it", async () => {
  const page = makePage(base, { width: 520 }); page.connect(); await settle();
  const { svg, hits } = chartParts(page, "brief-live"); const rects = byClass(hits, "bf-hit"); const tip = byClass(hits, "bf-tip")[0];
  assert.equal(rects.length, byClass(svg, "bf-row").length); assert.deepEqual(rects.map((rect) => rect.attributes.tabindex), rects.map((_, i) => (i ? "-1" : "0")), "one tab stop per chart, arrow keys inside it");
  rects.forEach((rect) => { assert.equal(rect.attributes.role, "img"); assert.ok(rect.attributes["aria-label"].length > 0); assert.equal(byTag(rect, "title").length, 1, "the native title stays as a fallback"); });
  assert.ok(tip, "the tooltip group exists"); assert.equal(classes(tip).includes("is-on"), false); assert.match(tip.attributes.transform, /^translate\(-?[\d.]+ -?[\d.]+\)$/, "positioned with the transform attribute");
  assert.equal(tip.attributes["aria-hidden"], "true");
  rects[0].fire("pointerenter"); assert.ok(classes(tip).includes("is-on")); assert.match(textsOf(tip, "bf-tip-head")[0], /basis/); assert.ok(textsOf(tip, "bf-tip-line").some((line) => /Lowest quote \$\d+\.\d{3}/.test(line)));
  assert.equal(byTag(rects[0], "title").length, 0, "no native tooltip on top of ours");
  const width = Number(svg.attributes.width); const x = Number(/^translate\((-?[\d.]+) /.exec(tip.attributes.transform)[1]); const tipWidth = Number(byClass(tip, "bf-tip-bg")[0].attributes.width);
  assert.ok(x >= 0 && x + tipWidth <= width, "the tooltip stays inside the chart's column");
  rects[0].fire("pointerleave"); assert.equal(classes(tip).includes("is-on"), false); assert.equal(byTag(rects[0], "title").length, 1, "the title returns when the tooltip goes");
  rects[2].fire("focus"); assert.ok(classes(tip).includes("is-on")); assert.deepEqual(rects.map((rect) => rect.attributes.tabindex), rects.map((_, i) => (i === 2 ? "0" : "-1")), "the tab stop follows focus");
  hits.fire("keydown", { key: "ArrowDown", target: rects[2] }); assert.equal(rects[3].focused, true);
  hits.fire("keydown", { key: "Escape", target: rects[3] }); assert.equal(classes(tip).includes("is-on"), false, "Escape closes it");
  rects[1].fire("focus"); page.press("Escape"); assert.equal(classes(tip).includes("is-on"), false, "Escape anywhere on the page closes it");
  rects[1].fire("blur"); rects[1].fire("pointerenter", { pointerType: "touch" }); assert.equal(classes(tip).includes("is-on"), false, "a finger's hover is not a tooltip");
  await rects[1].click(); assert.ok(classes(tip).includes("is-on"), "a tap is");
  const cost = chartParts(page, "brief-anatomy"); const costTip = byClass(cost.hits, "bf-tip")[0]; byClass(cost.hits, "bf-hit")[1].fire("pointerenter");
  assert.equal(textsOf(costTip, "bf-tip-line").length, 3, "the cost chart's tooltip lists the three parts"); assert.match(textsOf(costTip, "bf-tip-head")[0], /all-in/);
});

test("every chart carries a short label on the picture and a hidden table with all of its numbers", async () => {
  const page = makePage(base, { width: 520 }); page.connect(); await settle();
  const FORBIDDEN = /→|coloured|\blive\b|\blegend\b/i; const spoken = [];
  CHARTS.forEach((id) => {
    const { svg, hits, twin, table } = chartParts(page, id);
    assert.equal(svg.attributes.role, "img"); assert.ok(svg.attributes["aria-label"].length > 20 && svg.attributes["aria-label"].length < 260, id + " has a short label"); assert.ok(classes(twin).includes("sr-only"), "the table is visually hidden");
    assert.equal(table.tagName, "table"); assert.ok(table.children[0].tagName === "caption" && table.children[0].textContent.length > 0, id + " has a caption");
    const headings = byTag(table.children[1], "th"); assert.ok(headings.length >= 2 && headings.every((th) => th.attributes.scope === "col"));
    const body = table.children[2].children; assert.equal(body.length, byClass(svg, "bf-row").length, id + " has one table row per chart row"); body.forEach((row) => assert.equal(row.children[0].attributes.scope, "row"));
    assert.equal(body[0].children.length, headings.length, "and a cell under every heading");
    spoken.push(svg.attributes["aria-label"], hits.attributes["aria-label"], table.textContent, ...byClass(hits, "bf-hit").map((rect) => rect.attributes["aria-label"]));
  });
  spoken.forEach((text) => assert.doesNotMatch(text, FORBIDDEN, "spoken text: " + text));
  const b300 = base.models.find((entry) => entry.model === "B300");
  const row = chartParts(page, "brief-live").table.children[2].children[0].children.map((cell) => cell.textContent);
  assert.equal(row[0], "B300"); assert.equal(row[1], "$" + Number(b300.cheapest.price).toFixed(3)); assert.equal(row[2], "$" + Number(b300.best.risk_adjusted).toFixed(3)); assert.match(row[3], /^\+\d+\.\d%$/);
  assert.match(chartParts(page, "brief-grades").svg.attributes["aria-label"], /below the model median/, "the grades chart says what it measures");
});

test("one precision rule: three decimals under $10 everywhere, percentages worked out from the prices printed beside them", async () => {
  const page = makePage(base, { width: 520 }); page.connect(); await settle();
  const hero = chartParts(page, "brief-live").svg; let checked = 0;
  byClass(hero, "bf-row").forEach((group) => {
    const sub = byClass(group, "bf-row-sub")[0]; const value = byClass(group, "bf-value")[0]; const pair = sub && /^\$([\d.]+) → \$([\d.]+)$/.exec(sub.textContent); if (!pair || !value) return;
    const [low, best] = [Number(pair[1]), Number(pair[2])]; const shown = Number(value.textContent.replace("%", "").replace("+", ""));
    assert.equal(shown, Math.round((best / low - 1) * 1000) / 10, byClass(group, "bf-row-label")[0].textContent + ": " + sub.textContent + " should print " + value.textContent); checked += 1;
  });
  assert.ok(checked >= 4, "the rule was checked on every ranked model");
  const everything = [spacedText(page.el("brief-fact-cost"))];
  CHARTS.forEach((id) => {
    const parts = chartParts(page, id); everything.push(spacedText(page.el(id)));
    byClass(parts.hits, "bf-hit").forEach((rect) => { everything.push(rect.attributes["aria-label"]); rect.fire("pointerenter"); everything.push(spacedText(byClass(parts.hits, "bf-tip")[0])); rect.fire("pointerleave"); });
  });
  let amounts = 0;
  everything.join(" ").replace(/\$(\d+)\.(\d+)/g, (_, whole, places) => { amounts += 1; assert.equal(places.length, Number(whole) < 10 ? 3 : 2, "$" + whole + "." + places + " has the wrong number of decimals"); return ""; });
  assert.ok(amounts > 40, "the rule was checked on many prices (" + amounts + ")");
  // the all-in formula foots: the printed parts add up to the printed total, and the big figure is that total over the quoted price
  const split = page.el("brief-anatomy").children[1]; const dollars = (node) => Number(/\$([\d.]+)/.exec(node.textContent)[1]); const [quoted, financing, loss, total] = byTag(split, "dd").map(dollars);
  assert.equal(Math.round((quoted + financing + loss) * 1000) / 1000, total, "$" + quoted + " + $" + financing + " + $" + loss + " = $" + total);
  assert.equal(textsOf(chartParts(page, "brief-anatomy").svg, "bf-value")[1], "$" + total.toFixed(3));
  assert.equal(Number(/^\+(\d+)%/.exec(page.el("brief-fact-cost").textContent)[1]), Math.round((total / quoted - 1) * 100));
  assert.deepEqual(byTag(split, "dd").map((node) => node.textContent.replace(/[\d.$]+/, "")), ["", "+", "+", "="], "it reads as a sum");
});

test("the scorecard weights are six rows in one colour, largest first, from zero to 30 percent", async () => {
  const page = makePage(base, { width: 440 }); page.connect(); await settle();
  const { svg } = chartParts(page, "brief-weights"); const values = textsOf(svg, "bf-value").map((text) => Number(text.replace("%", "")));
  assert.equal(byClass(svg, "bf-bar").length, 6); assert.deepEqual(values, [...values].sort((a, b) => b - a)); assert.equal(values[0], Math.round(Math.max(...Object.values(book.base.assumptions.weights)) * 100));
  assert.equal(new Set(byClass(svg, "bf-bar").map((bar) => classes(bar).find((name) => name.startsWith("bf-tone-")))).size, 1, "one colour, no ramp");
  assert.deepEqual(textsOf(svg, "bf-tick"), ["0", "10", "20", "30%"]); assert.equal(byClass(page.el("brief-weights"), "chart-legend").length, 0, "one series needs no legend");
});

test("the grades chart shows a neutral bar and a grade chip per row, and a key only for the grades that are present", async () => {
  const page = makePage(base, { width: 520 }); page.connect(); await settle();
  const { svg } = chartParts(page, "brief-grades"); const rows = byClass(svg, "bf-row").length;
  assert.equal(byClass(svg, "bf-chip").length, rows); assert.ok(byClass(svg, "bf-bar").every((bar) => classes(bar).includes("bf-tone-neutral")), "a grade is the chip's job, not the bar's");
  textsOf(svg, "bf-value").forEach((text) => assert.match(text, /^\d+%$/, "no repeated 'below'"));
  const present = (target) => byClass(target.el("brief-grades"), "chart-legend").flatMap((list) => list.children.map((item) => item.textContent));
  const grades = [...new Set(base.models.filter((m) => m.cheapest && m.median).map((m) => m.cheapest.grade))].sort();
  assert.deepEqual(present(page).sort(), grades.map((grade) => "Grade " + grade), "only the grades that appear"); assert.ok(present(page).length < 4);
  const allC = makePage(withBook((data) => data.models.forEach((entry) => { if (entry.cheapest) entry.cheapest.grade = "C"; })), { width: 520 }); allC.connect(); await settle();
  assert.deepEqual(present(allC), ["Grade C"]); assert.ok(byClass(chartParts(allC, "brief-grades").svg, "bf-chip").every((chip) => classes(chip).includes("g-c")));
});

test("a grade chip follows its row when the lowest quote's grade changes between polls", async () => {
  const page = makePage(base, { width: 520 }); page.connect(); await settle();
  const { svg } = chartParts(page, "brief-grades"); const chip = byClass(svg, "bf-chip")[0]; const letter = chip.children[1].textContent;
  const other = letter === "A" ? "D" : "A";
  await show(page, withBook((data) => { data.models.forEach((entry) => { if (entry.cheapest) entry.cheapest.grade = other; }); }));
  assert.equal(byClass(chartParts(page, "brief-grades").svg, "bf-chip")[0], chip, "the same chip element");
  assert.equal(chip.children[1].textContent, other); assert.ok(classes(chip).includes("g-" + other.toLowerCase()) && !classes(chip).includes("g-" + letter.toLowerCase()), "and its colour class follows the letter");
});

test("the cost parts are three colours of their own, and only the data end of each bar is rounded", async () => {
  const page = makePage(base, { width: 520 }); page.connect(); await settle();
  const { svg } = chartParts(page, "brief-anatomy"); const [quoted, allin] = byClass(svg, "bf-bar-group"); const parts = byClass(allin, "bf-bar");
  assert.deepEqual(parts.map((bar) => classes(bar).find((name) => name.startsWith("bf-tone-"))), ["bf-tone-quoted", "bf-tone-financing", "bf-tone-loss"]);
  assert.equal(byClass(quoted, "bf-bar").length, 1);
  parts.forEach((bar, index) => assert.equal((bar.attributes.d.match(/A/g) || []).length, index === parts.length - 1 ? 2 : 0, "only the data end of a bar is rounded"));
  assert.equal((byClass(quoted, "bf-bar")[0].attributes.d.match(/A/g) || []).length, 2);
  assert.ok(parts.every((bar) => bar.attributes.stroke === undefined && bar.tagName === "path"), "paths with no stroke around them");
  assert.equal(textsOf(svg, "bf-seg-label").length, 1, "the narrow financing segment prints its own amount above it"); assert.match(textsOf(svg, "bf-seg-label")[0], /^\+\$\d+\.\d{3}$/);
});

test("sparklines draw at most twelve means, keep a flat series flat, and never print a broken number", () => {
  const { landing } = makePage(base);
  const noisy = landing.sparkline(Array.from({ length: 150 }, (_, i) => 100 + Math.sin(i))); const line = byClass(noisy, "bf-spark-line")[0];
  assert.ok((line.attributes.d.match(/[ML]/g) || []).length <= 12, "bucketed to twelve points"); assert.equal(byClass(noisy, "bf-spark-last").length, 1, "the last stretch is its own mark");
  assert.deepEqual(byClass(noisy, "bf-spark-ring").map((node) => node.attributes.r), ["6"]); assert.deepEqual(byClass(noisy, "bf-spark-dot").map((node) => node.attributes.r), ["4"], "a 4px dot in a 2px ring");
  const ys = (svg) => [...byClass(svg, "bf-spark-line")[0].attributes.d.matchAll(/ (-?[\d.]+)/g)].map((match) => Number(match[1]));
  const flat = ys(landing.sparkline([7, 7, 7, 7, 7, 7])); assert.equal(new Set(flat).size, 1, "a flat series is a flat line");
  const calm = ys(landing.sparkline([100, 100.4, 99.8, 100.2, 100.1, 99.9])); assert.ok(Math.max(...calm) - Math.min(...calm) < 26, "noise within a percent does not fill the box");
  const swing = ys(landing.sparkline([10, 40, 10, 40, 10, 40])); assert.ok(Math.max(...swing) - Math.min(...swing) > 18, "a real swing does");
  [[], [3], [null, NaN, undefined], undefined].forEach((values) => { const svg = landing.sparkline(values); assertClean(svg, "sparkline"); assert.equal(byClass(svg, "bf-spark-line").length, 0); });
  assert.equal(noisy.attributes["aria-hidden"], "true");
});
