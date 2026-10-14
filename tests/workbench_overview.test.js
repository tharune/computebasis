"use strict";
// The Overview drawn from real simulator snapshots in the browserless DOM (see demo_harness.js).
const { test } = require("node:test");
const { assert, findAll, classes, byClass, byTag, settle, assertClean, makePage, base, war, reset, book, normalize, assertLive, deskFixture } = require("./demo_harness.js");

test("a changed book redraws the Overview and highlights only what moved", async () => {
  const page = makePage(base); page.connect(); await settle();
  page.host.showView("desk"); await settle();
  const kpis = page.el("desk-kpis");
  assert.equal(byClass(kpis, "kpi").length, 6);
  assert.equal(byClass(kpis, "flash").length, 0, "nothing flashes on first paint");
  assert.match(kpis.textContent, new RegExp((base.kpis.basis * 100).toFixed(1) + "%"));
  assert.equal(byClass(page.el("desk-basis"), "ch-part").length, book.base.models.reduce((count, entry) => count + 1 + (entry.best ? 1 : 0), 0), "a bar for each model's lowest quote and one for its best eligible quote");
  ["desk-kpis", "desk-basis", "desk-trend", "desk-supply", "desk-completeness", "desk-grades", "desk-providers", "desk-activity", "desk-expiry"].forEach((id) => { assertClean(page.el(id), id); assert.ok(page.el(id).children.length > 0, id + " is empty"); });
  page.server.snapshot = war; page.server.tag = 'W/"two"';
  page.poll(); await settle();
  assert.match(kpis.textContent, new RegExp((war.kpis.basis * 100).toFixed(1) + "%"));
  assert.ok(byClass(kpis, "flash").length > 0, "changed figures are highlighted");
  assert.ok(byClass(page.el("desk-trend"), "ch-marker-label").some((node) => /price war/i.test(node.textContent)), "the scenario is annotated on the chart");
  assert.ok(byClass(page.el("desk-activity"), "flash").length > 0, "new events are highlighted");
});

test("the Overview basis bars carry the book's own numbers, and a model with no eligible seller says so", async () => {
  const drawn = structuredClone(base); const lone = drawn.models[drawn.models.length - 1];
  lone.best = null; lone.basis = null; lone.eligible = 0; lone.eligible_count = 0;  // one market with nobody eligible
  const expected = normalize(drawn);
  const page = makePage(drawn); page.connect(); await settle(); page.host.showView("desk"); await settle();
  const basis = page.el("desk-basis");
  const labels = byClass(basis, "ch-value").map((node) => node.textContent); const trails = byClass(basis, "ch-trail").map((node) => node.textContent);
  assert.equal(trails.length, expected.models.length);
  expected.models.forEach((entry, index) => {
    assert.ok(labels.includes("$" + Number(entry.cheapest.price).toFixed(2)), entry.model + " lowest quote is labelled");
    if (entry.best) { assert.ok(labels.includes("$" + entry.best.risk_adjusted.toFixed(3)), entry.model + " best eligible all-in is labelled"); assert.equal(trails[index], "+" + (entry.basis * 100).toFixed(1) + "%"); }
    else assert.equal(trails[index], "—");
  });
  assert.match(basis.textContent, /No eligible seller/);
  const bars = byClass(basis, "ch-part"); assert.ok(bars.every((bar) => Number(bar.attributes.width) > 0 && Number(bar.attributes.x) >= 0), "bars start at the zero line");
});

test("the Overview price chart flags each scenario and names the market a flag belongs to", async () => {
  const page = makePage(war); page.connect(); await settle(); page.host.showView("desk"); await settle();
  const flags = byClass(page.el("desk-trend"), "ch-marker-label"); assert.ok(flags.some((node) => /^Price war/.test(node.textContent)));
  page.server.snapshot = { ...war, alerts: war.alerts.filter((alert) => !alert.scenario) }; page.server.tag = 'W/"quiet"'; page.poll(); await settle();
  assert.ok(byClass(page.el("desk-trend"), "ch-marker-label").some((node) => /^Price war/.test(node.textContent)), "a flag stays on the chart after the feed has moved past its alert");
  const other = page.el("desk-model-tabs").children.find((button) => button.dataset.model !== "B300"); await other.click(); await settle();
  assert.ok(byClass(page.el("desk-trend"), "ch-marker-label").some((node) => /^Price war$/.test(node.textContent)), "a scenario moves the whole market, so the same flag is on every model");
  assert.equal(page.el("desk-model-tabs").children.length, book.base.models.length);
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
