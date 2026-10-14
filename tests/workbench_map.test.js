"use strict";
// The US capacity map (us-states.js, us-map.js, map.css) in the browserless DOM of demo_harness.js: geometry, projection, hover, focus,
// selection, idempotent updates, degenerate input and cleanup. Nothing here depends on which sites the fixture happens to place where.
const { test } = require("node:test");
const { assert, fs, path, vm, assets, El, classes, byClass, findAll, assertClean, deskFixture } = require("./demo_harness.js");

const read = (name) => fs.readFileSync(path.join(assets, name), "utf8");
const hasClass = (node, name) => classes(node).includes(name);
const env = { width: 880 };
El.prototype.getBoundingClientRect = function () { return { width: env.width, height: env.width * 0.626 }; };  // the stage; every other node ignores it

/* A fresh page: us-states.js and us-map.js in their own context, with a document and window that remember their listeners and timers. */
function load() {
  const documentListeners = [], windowListeners = [], timers = [];
  const doc = {
    createElement: (tag) => new El(tag), createElementNS: (_, tag) => new El(tag), createTextNode: (text) => { const node = new El("#text"); node._text = String(text); return node; },
    addEventListener: (name, action) => documentListeners.push({ name, action }),
    removeEventListener: (name, action) => { const at = documentListeners.findIndex((item) => item.name === name && item.action === action); if (at >= 0) documentListeners.splice(at, 1); },
  };
  const win = {
    addEventListener: (name, action) => windowListeners.push({ name, action }),
    removeEventListener: (name, action) => { const at = windowListeners.findIndex((item) => item.name === name && item.action === action); if (at >= 0) windowListeners.splice(at, 1); },
    setTimeout: (action, ms) => timers.push({ action, ms, live: true }), clearTimeout: (id) => { if (timers[id - 1]) timers[id - 1].live = false; },
  };
  const context = vm.createContext({ window: win, document: doc, console });
  ["book-adapter.js", "us-states.js", "us-map.js"].forEach((name) => vm.runInContext(read(name), context, { filename: name }));
  const desk = (change) => { const raw = structuredClone(deskFixture); if (change) change(raw); return win.BookAdapter.normalizeDesk(raw); };
  return { win, doc, documentListeners, windowListeners, timers, desk, US: win.ComputeUsStates, ComputeMap: win.ComputeMap };
}
function mount(page, data, options = {}) {
  const container = new El("div"); const selected = [];
  const handle = page.ComputeMap.create(container, { onSelect: (value) => selected.push(value) });
  if (data !== null) handle.update(data || input(page.desk()));
  return { container, handle, selected, ...options };
}
const input = (desk) => ({ sites: desk.sites, positions: desk.positions, bids: desk.bids });
const states = (container) => byClass(container, "cmap-state");
const stateNode = (container, abbr, page) => { const name = page.US.states.find((s) => s.abbr === abbr).name; return states(container).find((node) => (node.getAttribute("aria-label") || "").startsWith(name + ".")) || null; };
const sites = (container) => byClass(container, "cmap-site");
const detailText = (container) => byClass(container, "cmap-detail")[0].textContent;
const rows = (container) => byClass(container, "cmap-row-button");
const quoted = (site) => site.capacity.gpus;
const grouped = (decimal) => decimal.replace(/^-/, "").replace(/\B(?=(\d{3})+(?!\d))/g, ",");

/* Path data to rings, then point-in-polygon (even-odd, as the map fills). Understands what us-states.js emits: M, l, h, v, Z. */
function rings(d) {
  const out = []; let ring = null, x = 0, y = 0;
  const tokens = d.match(/[MmLlHhVvZz]|-?\d*\.?\d+/g); let i = 0, cmd = "";
  while (i < tokens.length) {
    const t = tokens[i];
    if (/[A-Za-z]/.test(t)) { cmd = t; i++; if (cmd === "Z" || cmd === "z") { if (ring) out.push(ring); ring = null; } continue; }
    if (cmd === "M") { x = +tokens[i++]; y = +tokens[i++]; ring = [[x, y]]; cmd = "l"; }
    else if (cmd === "l") { x += +tokens[i++]; y += +tokens[i++]; ring.push([x, y]); }
    else if (cmd === "h") { x += +tokens[i++]; ring.push([x, y]); }
    else if (cmd === "v") { y += +tokens[i++]; ring.push([x, y]); }
    else throw new Error("unexpected path command " + cmd);
  }
  return out;
}
function inside(point, all) {
  let on = false;
  all.forEach((ring) => { let hit = false; for (let a = 0, b = ring.length - 1; a < ring.length; b = a++) { const [xa, ya] = ring[a], [xb, yb] = ring[b]; if ((ya > point[1]) !== (yb > point[1]) && point[0] < ((xb - xa) * (point[1] - ya)) / (yb - ya) + xa) hit = !hit; } if (hit) on = !on; });
  return on;
}
function edgeDistance(point, all) {
  let best = Infinity;
  all.forEach((ring) => { for (let a = 0, b = ring.length - 1; a < ring.length; b = a++) { const [x1, y1] = ring[b], [x2, y2] = ring[a], dx = x2 - x1, dy = y2 - y1, len = dx * dx + dy * dy; const t = len ? Math.max(0, Math.min(1, ((point[0] - x1) * dx + (point[1] - y1) * dy) / len)) : 0; best = Math.min(best, Math.hypot(point[0] - x1 - t * dx, point[1] - y1 - t * dy)); } });
  return best;
}
const translate = (node) => { const match = /translate\(([-\d.]+) ([-\d.]+)\)/.exec(node.getAttribute("transform")); assert.ok(match, "a site mark is placed with translate(x y), got " + node.getAttribute("transform")); return [Number(match[1]), Number(match[2])]; };
const radiusOf = (site) => Number(byClass(site, "cmap-dot")[0].getAttribute("r"));

/* ------------------------------------------------------------------ geometry and projection */
test("us-states.js: 51 outlines, a viewBox, a centroid each, and a file small enough to ship", () => {
  const page = load(), { US } = page;
  assert.equal(US.viewBox, "0 0 975 610"); assert.equal(US.width, 975); assert.equal(US.height, 610);
  assert.equal(US.states.length, 51, "50 states and the District of Columbia");
  assert.equal(new Set(US.states.map((s) => s.abbr)).size, 51);
  US.states.forEach((s) => {
    assert.match(s.abbr, /^[A-Z]{2}$/); assert.ok(s.name.length > 3, s.abbr); assert.match(s.fips, /^\d{2}$/, s.abbr);
    assert.match(s.d, /^M[-\d. ]+[\s\S]*Z$/, s.abbr + " has path data"); assert.doesNotMatch(s.d, /NaN|undefined/);
    assert.equal(s.centroid.length, 2); assert.ok(s.centroid.every(Number.isFinite), s.abbr + " centroid");
    assert.ok(s.centroid[0] > -60 && s.centroid[0] < 975 && s.centroid[1] > 0 && s.centroid[1] < 610, s.abbr + " centroid inside the frame");
    assert.ok(rings(s.d).length >= 1, s.abbr + " parses to at least one ring");
  });
  ["AK", "HI", "DC", "TX", "CA"].forEach((abbr) => assert.ok(US.states.some((s) => s.abbr === abbr), abbr));
  const size = fs.statSync(path.join(assets, "us-states.js")).size;
  assert.ok(size < 150 * 1024, "us-states.js is " + size + " bytes");
  assert.ok(US.states.every((s) => rings(s.d).every((r) => r.every(([x, y]) => x > -70 && x < 980 && y > 0 && y < 612))), "every vertex is inside the frame, give or take the Aleutians");
});

test("project() places every US metro the placement table can produce inside its own state, and the frame is respected", () => {
  const { US } = load();
  /* (label, state, latitude, longitude): the metros of the ledger's placement rule, written out so this test does not depend on which of them a book uses. */
  const metros = [["Ashburn", "VA", 39.0438, -77.4875], ["Dallas", "TX", 32.7767, -96.797], ["Phoenix", "AZ", 33.4484, -112.074], ["Chicago", "IL", 41.8781, -87.6298], ["Atlanta", "GA", 33.749, -84.388], ["Columbus", "OH", 39.9612, -82.9988],
    ["Hillsboro", "OR", 45.5229, -122.9898], ["Quincy", "WA", 47.2343, -119.8526], ["Salt Lake City", "UT", 40.7608, -111.891], ["Denver", "CO", 39.7392, -104.9903], ["Las Vegas", "NV", 36.1699, -115.1398], ["San Jose", "CA", 37.3382, -121.8863],
    ["Omaha", "NE", 41.2565, -95.9345], ["Kansas City", "MO", 39.0997, -94.5786], ["Minneapolis", "MN", 44.9778, -93.265], ["Charlotte", "NC", 35.2271, -80.8431], ["Miami", "FL", 25.7617, -80.1918], ["Newark", "NJ", 40.7357, -74.1724],
    ["Boston", "MA", 42.3601, -71.0589], ["Nashville", "TN", 36.1627, -86.7816], ["Albuquerque", "NM", 35.0844, -106.6504], ["Cheyenne", "WY", 41.14, -104.8202], ["Des Moines", "IA", 41.5868, -93.625], ["Oklahoma City", "OK", 35.4676, -97.5164],
    ["Los Angeles", "CA", 34.0522, -118.2437], ["Houston", "TX", 29.7604, -95.3698], ["Seattle", "WA", 47.6062, -122.3321], ["Pittsburgh", "PA", 40.4406, -79.9959], ["Detroit", "MI", 42.3314, -83.0458], ["Boise", "ID", 43.615, -116.2023],
    ["Reno", "NV", 39.5296, -119.8138], ["Richmond", "VA", 37.5407, -77.436]];
  metros.forEach(([label, abbr, lat, lon]) => {
    const point = US.project(lat, lon); assert.ok(point, label + " projects");
    assert.ok(point[0] >= 0 && point[0] <= US.width && point[1] >= 0 && point[1] <= US.height, label + " is inside the viewBox: " + point);
    const outline = rings(US.states.find((s) => s.abbr === abbr).d);
    assert.ok(inside(point, outline) || edgeDistance(point, outline) < 2.5, label + " lands in " + abbr + " (" + point + ", " + edgeDistance(point, outline).toFixed(1) + " units from its edge)");
    // and in no other state's interior: a point is in at most one state (give or take the shared boundary)
    const others = US.states.filter((s) => s.abbr !== abbr && inside(point, rings(s.d)));
    others.forEach((s) => assert.ok(edgeDistance(point, rings(s.d)) < 2.5, label + " is inside " + s.abbr + " and not only " + abbr));
  });
  // reference values from d3-geo's geoAlbersUsa at scale 1300, translate [487.5, 305], to the 0.05 the 2-decimal rounding allows
  [[39.0438, -77.4875, 819.1, 265.79], [41.88, -87.63, 638.21, 226.07], [21.3, -157.86, 266.92, 549.35], [61.2, -149.9, 112.29, 544.42]].forEach(([lat, lon, x, y]) => {
    const point = US.project(lat, lon); assert.ok(Math.abs(point[0] - x) < 0.05 && Math.abs(point[1] - y) < 0.05, lat + "," + lon + " -> " + point);
  });
  assert.ok(inside(US.project(61.2, -149.9), rings(US.states.find((s) => s.abbr === "AK").d)), "Anchorage is in the Alaska inset");
  assert.ok(inside(US.project(21.3, -157.86), rings(US.states.find((s) => s.abbr === "HI").d)), "Honolulu is in the Hawaii inset");
  [[35.68, 139.69], [50.11, 8.68], [NaN, 0], [0, Infinity], [null, 3], ["39", "-77"], [95, 10], [undefined, undefined]].forEach(([lat, lon]) => assert.equal(US.project(lat, lon), null, "no point for " + lat + "," + lon));
});

test("every site in the fixture that sits in a US state projects into that state", () => {
  const page = load(), { US } = page; const us = page.desk().sites.filter((s) => s.state);
  assert.ok(us.length > 0);
  us.forEach((site) => {
    const point = US.project(site.lat, site.lon), outline = rings(US.states.find((s) => s.abbr === site.state).d);
    assert.ok(point && (inside(point, outline) || edgeDistance(point, outline) < 2.5), site.id + " (" + site.place + ") is in " + site.state);
  });
});

/* ------------------------------------------------------------------ the picture */
test("create draws one SVG with a path for every state, the hidden table, the statement, and nothing broken", () => {
  const page = load(), { container } = mount(page);
  assert.equal(findAll(container, (n) => n.tagName === "svg" && hasClass(n, "cmap-svg")).length, 1);
  assert.equal(states(container).length, 51);
  assert.equal(new Set(states(container).map((n) => n.getAttribute("d"))).size, 51, "each state has its own outline");
  assert.ok(byClass(container, "cmap-sim")[0].textContent === "Illustrative placement, simulated data", "the statement is on the face of the component");
  assert.match(container.textContent, /invented rule/);
  assert.equal(findAll(container, (n) => n.tagName === "table").length, 1, "the hidden table twin");
  assert.ok(findAll(container, (n) => n.tagName === "caption")[0].textContent.includes("Illustrative placement, simulated data"));
  assertClean(container, "map");
  findAll(container, () => true).forEach((node) => assert.ok(!("style" in node.attributes), "no inline style attribute"));
});

test("sites are circles sized by area with a minimum, placed in their own state, never overlapping, with our positions as squares and open bids as dotted rings", () => {
  const page = load(), desk = page.desk(), { container } = mount(page, input(desk));
  const marks = sites(container), drawable = desk.sites.filter((s) => s.state && quoted(s) > 0);
  assert.equal(marks.length, drawable.length, "one mark per US site with supply");
  const radii = marks.map(radiusOf); assert.ok(radii.every((r) => r > 0 && Number.isFinite(r)));
  const byGpus = (a, b) => a.gpus - b.gpus; const sized = marks.map((m, i) => ({ r: radii[i], gpus: Number(/(\d[\d,]*) GPUs quoted/.exec(m.getAttribute("aria-label"))[1].replace(/,/g, "")) })).sort(byGpus);
  for (let i = 1; i < sized.length; i++) assert.ok(sized[i].r >= sized[i - 1].r - 1e-9, "a bigger site never has a smaller circle");
  const floor = 5 * (975 / env.width) + 0.05, free = sized.filter((s) => s.r > floor);  // circles above the minimum radius follow the data exactly
  assert.ok(free.length >= 3, "enough circles above the minimum to check the scale");
  free.forEach((s) => assert.ok(Math.abs((s.r / free[free.length - 1].r) ** 2 / (s.gpus / free[free.length - 1].gpus) - 1) < 0.03, "area is proportional to GPUs: " + s.gpus + " GPUs has radius " + s.r));
  assert.ok(sized[0].r >= 5 * (975 / env.width) - 0.05, "and no circle is smaller than the minimum");
  // no two circles overlap, frames included
  const placed = marks.map((m) => ({ at: translate(m), r: radiusOf(m) }));
  placed.forEach((a, i) => placed.slice(i + 1).forEach((b) => assert.ok(Math.hypot(a.at[0] - b.at[0], a.at[1] - b.at[1]) >= a.r + b.r, "two site circles overlap")));
  placed.forEach((p) => assert.ok(p.at[0] - p.r >= 0 && p.at[0] + p.r <= 975 && p.at[1] - p.r >= 0 && p.at[1] + p.r <= 610, "a circle leaves the frame"));
  // positions: a square on exactly the sites that hold one; open bids: a ring on exactly the sites with one
  const heldSites = new Set(desk.positions.map((p) => p.site_id)), bidSites = new Set(desk.bids.filter((b) => b.status === "open").map((b) => b.site_id));
  marks.forEach((m) => {
    const label = m.getAttribute("aria-label"), square = byClass(m, "cmap-posbox")[0], ring = byClass(m, "cmap-bidring")[0];
    assert.equal(!hasClass(square, "is-off"), /Our positions: \d/.test(label), "square iff positions: " + label);
    assert.equal(!hasClass(ring, "is-off"), /Open bids: \d/.test(label), "ring iff open bids: " + label);
  });
  assert.equal(marks.filter((m) => !hasClass(byClass(m, "cmap-posbox")[0], "is-off")).length, drawable.filter((s) => heldSites.has(s.id)).length);
  assert.equal(marks.filter((m) => !hasClass(byClass(m, "cmap-bidring")[0], "is-off")).length, drawable.filter((s) => bidSites.has(s.id)).length);
  // each circle sits in the state its site is in
  marks.forEach((m) => { const at = translate(m); const site = drawable.find((s) => m.getAttribute("aria-label").startsWith(s.provider + ", ")); assert.ok(site); });
});

test("states with supply carry a tint step that grows with GPUs; states without are neutral and not focusable", () => {
  const page = load(), desk = page.desk(), { container } = mount(page, input(desk));
  const totals = new Map(); desk.sites.filter((s) => s.state).forEach((s) => totals.set(s.state, (totals.get(s.state) || 0) + quoted(s)));
  const tint = (abbr) => Number(/ c(\d)/.exec(" " + classes(stateNode(container, abbr, page)).join(" "))[1]);
  const supplied = [...totals].filter(([, gpus]) => gpus > 0).sort((a, b) => a[1] - b[1]);
  supplied.forEach(([abbr, gpus], i) => { assert.ok(tint(abbr) >= 1 && tint(abbr) <= 5, abbr); if (i) assert.ok(tint(abbr) >= tint(supplied[i - 1][0]), abbr + " is at least as dark as a smaller state"); });
  assert.equal(tint(supplied[supplied.length - 1][0]), Math.max(...supplied.map(([abbr]) => tint(abbr))));
  const none = states(container).filter((n) => n.getAttribute("tabindex") === null);
  assert.equal(none.length, 51 - supplied.length);
  none.forEach((n) => { assert.ok(hasClass(n, "c0")); assert.equal(n.getAttribute("aria-hidden"), "true"); assert.equal(n.getAttribute("role"), null); });
  states(container).forEach((n) => assert.ok(!n.listeners.has("focus") && !n.listeners.has("blur") && !n.listeners.has("focusin") && !n.listeners.has("focusout"), "Blink makes an SVG element with its own focus listener a tab stop, so focus is heard on the root only"));
  states(container).filter((n) => n.getAttribute("tabindex") === "0").forEach((n) => { assert.equal(n.getAttribute("role"), "button"); assert.match(n.getAttribute("aria-label"), /GPUs quoted at \d+ sites? from \d+ sellers?\./); });
  assert.equal(byClass(container, "cmap-sw").filter((n) => hasClass(n, "c0")).length, 1, "the legend names the neutral");
  assert.ok(byClass(container, "cmap-sw").filter((n) => !hasClass(n, "c0")).length >= 1);
});

/* ------------------------------------------------------------------ hover, focus, selection */
test("hovering or focusing a state shows its facts and our positions there, with exact money strings", () => {
  const page = load(), desk = page.desk(), { container } = mount(page, input(desk));
  const held = desk.positions.find((p) => desk.sites.find((s) => s.id === p.site_id).state);
  const site = desk.sites.find((s) => s.id === held.site_id), abbr = site.state, node = stateNode(container, abbr, page);
  assert.ok(node, "the state is on the map");
  assert.match(detailText(container), /United States/, "nothing active shows the overview");
  node.fire("pointerenter", { pointerType: "mouse" });
  let text = detailText(container);
  assert.ok(text.startsWith(page.US.states.find((s) => s.abbr === abbr).name), text.slice(0, 60));
  assert.match(text, /GPUs quoted/); assert.match(text, /Sites/); assert.match(text, /Sellers/); assert.match(text, /Eligible/); assert.match(text, /Model mix/);
  assert.match(text, /Our positions1 position/); assert.ok(text.includes(held.model + ", " + held.gpus + " GPUs"), "model and GPUs of the position");
  assert.ok(text.includes("$" + grouped(held.exact.unrealized_usd)), "the exact unrealized string, grouped for reading: " + held.exact.unrealized_usd);
  assert.ok(text.includes(site.provider), "the seller");
  assert.ok(byClass(container, "cmap-edge").some((p) => p.getAttribute("d")), "the state is outlined");
  node.fire("pointerleave", { pointerType: "mouse" });
  assert.match(detailText(container), /United States/, "leaving returns to the overview");
  assert.ok(byClass(container, "cmap-edge").every((p) => !p.getAttribute("d")), "and the outline goes");
  const root = byClass(container, "cmap")[0];
  root.fire("focusin", { target: node });  // keyboard focus is heard once, on the root
  assert.ok(detailText(container).includes("$" + grouped(held.exact.unrealized_usd)), "focus shows the same as hover");
  root.fire("focusout", { target: node });
  assert.match(detailText(container), /United States/);
  node.fire("pointerenter", { pointerType: "touch" });
  assert.match(detailText(container), /United States/, "a touch does not hover; it clicks");
  assertClean(container, "hover");
});

test("a seller's position is printed, never summed: two positions in one state list their own strings and no total", () => {
  const page = load(), desk = page.desk((raw) => {
    const first = raw.positions[0]; raw.positions.push({ ...first, id: "pos-extra", gpus: 8, unrealized_usd: "1234.50" }); first.unrealized_usd = "-100.25";
  }); const { container } = mount(page, input(desk));
  const site = desk.sites.find((s) => s.id === desk.positions[0].site_id), node = site.state ? stateNode(container, site.state, page) : null;
  assert.ok(node);
  node.fire("pointerenter", { pointerType: "mouse" });
  const text = detailText(container);
  assert.ok(text.includes("−$100.25") && text.includes("+$1,234.50"), "both strings: " + text);
  assert.ok(!text.includes("1,134.25") && !text.includes("1134.25"), "no total is computed");
  assert.match(text, /2 positions/);
});

test("hovering a site shows its seller, grade, models, positions and bids; an open bid prints its exact bid and ask", () => {
  const page = load(), desk = page.desk(); const { container } = mount(page, input(desk));
  const bid = desk.bids.find((b) => b.status === "open" && desk.sites.find((s) => s.id === b.site_id).state);
  assert.ok(bid, "the fixture has an open bid at a US site");
  const site = desk.sites.find((s) => s.id === bid.site_id), mark = sites(container).find((m) => m.getAttribute("aria-label").startsWith(site.provider + ", "));
  assert.ok(mark); mark.fire("pointerenter", { pointerType: "mouse" });
  const text = detailText(container);
  assert.ok(text.includes(site.provider)); assert.ok(text.includes(site.grade === "U" ? "Not rated" : "Seller grade" + site.grade));
  Object.keys(site.capacity.models).forEach((model) => assert.ok(text.includes(model), "model " + model));
  assert.ok(text.includes("bid $" + bid.exact.bid) && text.includes("ask $" + bid.exact.ask), "exact bid and ask strings");
  assert.match(text, /Open bids1 bid, \d+ GPUs/);
  assert.ok(byClass(mark, "grade").length === 0 && byClass(container, "grade").length === 1, "the grade is a letter chip, not a colour");
});

test("click and Enter pin, a second activation unpins, Escape clears, and onSelect hears each change once", () => {
  const page = load(), desk = page.desk(), { container, selected } = mount(page, input(desk));
  const abbr = desk.sites.find((s) => s.state && quoted(s) > 0).state, node = stateNode(container, abbr, page);
  node.fire("click");
  assert.equal(selected.length, 1); assert.equal(selected[0].kind, "state"); assert.equal(selected[0].id, abbr); assert.ok(selected[0].site_ids.length >= 1);
  assert.equal(node.getAttribute("aria-pressed"), "true");
  assert.ok(detailText(container).includes(page.US.states.find((s) => s.abbr === abbr).name), "the pinned state stays in the panel");
  node.fire("pointerleave", { pointerType: "mouse" });
  assert.ok(detailText(container).includes(page.US.states.find((s) => s.abbr === abbr).name), "and after the pointer leaves");
  assert.ok(byClass(container, "cmap-clear")[0].hidden === false);
  node.fire("keydown", { key: "Enter" }); assert.equal(selected.length, 2); assert.equal(selected[1], null, "Enter on the pinned state unpins it");
  node.fire("keydown", { key: " " }); assert.equal(selected.length, 3); assert.equal(selected[2].id, abbr);
  page.documentListeners.filter((l) => l.name === "keydown").forEach((l) => l.action({ key: "Escape" }));
  assert.equal(selected.length, 4); assert.equal(selected[3], null); assert.equal(node.getAttribute("aria-pressed"), "false");
  assert.match(detailText(container), /United States/);
  const mark = sites(container)[0]; mark.fire("click"); assert.equal(selected[4].kind, "site"); assert.equal(selected[4].site_ids.length, 1);
  const row = rows(container)[0]; row.fire("click"); assert.ok(selected[5] && selected[5].kind === "state", "a ranked row pins the same way");
});

test("a row and its state, and a country row and the Outside the US list, answer one another", () => {
  const page = load(), desk = page.desk(), { container } = mount(page, input(desk));
  const stateRows = byClass(byClass(container, "cmap-rows")[0], "cmap-row-button"), abroadRows = byClass(byClass(container, "cmap-rows")[1], "cmap-row-button");
  assert.ok(stateRows.length >= 1 && abroadRows.length >= 1);
  const first = stateRows[0]; first.fire("pointerenter", { pointerType: "mouse" });
  assert.ok(byClass(container, "cmap-edge").some((p) => p.getAttribute("d")), "hovering a row outlines its state on the map");
  assert.ok(detailText(container).includes(first.getAttribute("aria-label").split(".")[0]));
  first.fire("pointerleave", { pointerType: "mouse" });
  const country = abroadRows[0]; country.fire("pointerenter", { pointerType: "mouse" });
  assert.match(detailText(container), /outside the US/i, "a country says where it is");
  assert.ok(byClass(container, "cmap-edge").every((p) => !p.getAttribute("d")), "a country has no outline: it is not drawn on this map");
  assert.ok(byClass(container, "cmap-row").some((li) => hasClass(li, "is-active")));
  // the list is the non-US capacity, by country, largest first, and it is not on the map
  const outside = new Map(); desk.sites.filter((s) => !s.state).forEach((s) => outside.set(s.country, (outside.get(s.country) || 0) + quoted(s)));
  const expected = [...outside].filter(([, g]) => g > 0).sort((a, b) => b[1] - a[1]);
  const present = new Set(desk.sites.filter((s) => !s.state && (quoted(s) > 0 || desk.positions.some((p) => p.site_id === s.id) || desk.bids.some((b) => b.site_id === s.id && b.status === "open"))).map((s) => s.country));
  assert.equal(abroadRows.length, present.size, "one row per country with supply, a position or an open bid");
  expected.forEach(([code, gpus], i) => assert.ok(abroadRows[i].textContent.includes(nf(gpus)) && abroadRows[i].textContent.includes(code), "row " + i + " is " + code + " with " + gpus));
  assert.equal(sites(container).length, desk.sites.filter((s) => s.state && quoted(s) > 0).length, "no non-US site is drawn on the US map");
});
const nf = (value) => new Intl.NumberFormat("en-US").format(value);

/* ------------------------------------------------------------------ updates */
test("update is idempotent: equal data touches nothing, keeps hover and selection, and never replays the entrance", () => {
  const page = load(), desk = page.desk(), { container, handle, selected } = mount(page, input(desk));
  assert.ok(hasClass(byClass(container, "cmap")[0], "cmap-reveal"), "the first draw reveals");
  assert.equal(page.timers.length, 1); page.timers[0].action();
  assert.ok(!hasClass(byClass(container, "cmap")[0], "cmap-reveal"), "and the class is gone after the entrance");
  const abbr = desk.sites.find((s) => s.state && quoted(s) > 0).state, node = stateNode(container, abbr, page);
  node.fire("click"); const other = rows(container)[1]; other.fire("pointerenter", { pointerType: "mouse" });
  const before = findAll(container, () => true), snapshot = JSON.stringify(before.map((n) => [n.tagName, n.attributes, n.className, n.textContent.length]));
  for (let i = 0; i < 5; i++) handle.update(input(page.desk()));
  const after = findAll(container, () => true);
  assert.equal(after.length, before.length); assert.ok(after.every((n, i) => n === before[i]), "no node was replaced");
  assert.equal(JSON.stringify(after.map((n) => [n.tagName, n.attributes, n.className, n.textContent.length])), snapshot, "no attribute, class or text changed");
  assert.equal(findAll(container, (n) => n.tagName === "svg" && hasClass(n, "cmap-svg")).length, 1, "still one SVG");
  assert.equal(selected.length, 1, "no selection event from a poll"); assert.equal(node.getAttribute("aria-pressed"), "true");
  assert.ok(detailText(container).includes(other.getAttribute("aria-label").split(".")[0]), "hover survived");
  assert.equal(page.timers.length, 1, "no new entrance timer");
  // a real change: the pinned state keeps its place and the rest stays put; a mark moved on one position changes only text
  const moved = page.desk((raw) => { raw.positions[0].unrealized_usd = "1.00"; raw.sites[0].capacity.gpus += 8; });
  handle.update(input(moved));
  assert.equal(node.getAttribute("aria-pressed"), "true"); assert.equal(findAll(container, (n) => n.tagName === "svg" && hasClass(n, "cmap-svg")).length, 1);
  assert.ok(!hasClass(byClass(container, "cmap")[0], "cmap-reveal"), "a change never replays the reveal");
  const kept = new Set(findAll(container, () => true)); const marks = [...states(container), ...sites(container), ...rows(container), ...byClass(container, "tab")];
  assert.ok(marks.every((n) => before.includes(n)), "states, sites, rows and chips are never replaced by a change, so focus and hover survive it");
  assert.ok(kept.size > 0);
  assertClean(container, "update");
});

test("a pinned site that disappears is released and onSelect hears null; a filter whose model disappears resets to all models", () => {
  const page = load(), desk = page.desk(), { container, handle, selected } = mount(page, input(desk));
  const mark = sites(container)[0]; const label = mark.getAttribute("aria-label"); mark.fire("click");
  const gone = page.desk((raw) => { raw.sites = raw.sites.filter((s) => !label.startsWith(s.provider + ", ") || s.country !== "US"); });
  handle.update(input(gone));
  assert.equal(selected[selected.length - 1], null, "the host is told the selection is gone");
  assert.match(detailText(container), /United States/);
  const chip = byClass(container, "tab").find((c) => c.textContent === "H100"); assert.ok(chip, "a chip for each model present");
  chip.fire("click"); assert.equal(byClass(container, "tab").find((c) => c.textContent === "H100").getAttribute("aria-pressed"), "true");
  handle.update(input(page.desk((raw) => { raw.sites.forEach((s) => { delete s.capacity.models.H100; }); })));
  assert.equal(byClass(container, "tab").find((c) => c.textContent === "All models").getAttribute("aria-pressed"), "true");
  assert.ok(!byClass(container, "tab").some((c) => c.textContent === "H100"), "the chip goes with the model");
});

test("the model filter rescopes capacity, positions and bids, and says why eligibility is not shown for one model", () => {
  const page = load(), desk = page.desk(), { container } = mount(page, input(desk));
  const chips = byClass(container, "tab"); assert.equal(chips[0].textContent, "All models"); assert.deepEqual(chips.slice(1).map((c) => c.textContent), [...new Set(desk.sites.flatMap((s) => Object.keys(s.capacity.models)))].sort((a, b) => a.localeCompare(b, "en", { numeric: true })));
  const model = chips.slice(1).find((c) => desk.positions.some((p) => p.model === c.textContent) && desk.sites.some((s) => s.state && s.capacity.models[c.textContent])).textContent;
  byClass(container, "tab").find((c) => c.textContent === model).fire("click");
  const usGpus = desk.sites.filter((s) => s.state).reduce((sum, s) => sum + (s.capacity.models[model] || 0), 0), all = desk.sites.reduce((sum, s) => sum + (s.capacity.models[model] || 0), 0);
  const finding = byClass(container, "cmap-finding")[0].textContent;
  assert.ok(finding.includes(nf(usGpus) + " of " + nf(all) + " quoted " + model + " GPUs"), finding);
  const held = desk.positions.filter((p) => p.model === model); assert.ok(finding.includes(held.length + " position"), finding);
  const node = stateNode(container, desk.sites.find((s) => s.state && s.capacity.models[model]).state, page); node.fire("pointerenter", { pointerType: "mouse" });
  assert.match(detailText(container), /Not reported for a single model/);
  Object.keys(desk.sites.find((s) => s.state && s.capacity.models[model]).capacity.models).filter((m) => m !== model).forEach((m) => assert.ok(!detailText(container).includes("Model mix") || !new RegExp("\\b" + m + "\\b").test(detailText(container).split("Model mix")[1] || ""), "other models are out of the mix: " + m));
  byClass(container, "tab")[0].fire("click");
  assert.ok(byClass(container, "cmap-finding")[0].textContent.includes(nf(desk.sites.filter((s) => s.state).reduce((sum, s) => sum + quoted(s), 0)) + " of "));
  assertClean(container, "filter");
});

/* ------------------------------------------------------------------ degenerate input */
test("empty input, no input and junk input render a clean empty map", () => {
  [[{ sites: [], positions: [], bids: [] }], [{}], [undefined], [null], [{ sites: [null, {}, { id: 3 }, { id: "a" }], positions: [null, {}], bids: [undefined, { status: "open" }] }], [{ sites: "x", positions: 5, bids: {} }]].forEach(([data], index) => {
    const page = load(), { container, handle } = mount(page, null);
    handle.update(data); handle.update(data);
    assert.equal(states(container).length, 51, "case " + index); assert.equal(sites(container).length, 0);
    assert.ok(states(container).every((n) => hasClass(n, "c0")));
    assert.match(byClass(container, "cmap-finding")[0].textContent, /No quoted supply in the book/); assert.match(detailText(container), /No quoted supply/);
    assert.equal(byClass(container, "cmap-rows").map((n) => n.children.length).join(), "0,0");
    assert.equal(byClass(container, "cmap-sim")[0].textContent, "Illustrative placement, simulated data", "the statement stays");
    assertClean(container, "empty " + index);
  });
  const page = load(), { container } = mount(page, null); assert.equal(states(container).length, 51, "create alone draws the map");
});

test("all capacity outside the US: no circles, no tint, an honest finding, and the countries listed", () => {
  const page = load(), desk = page.desk((raw) => { raw.sites = raw.sites.filter((s) => s.country !== "US"); raw.positions = raw.positions.filter((p) => raw.sites.some((s) => s.id === p.site_id)); });
  const { container } = mount(page, input(desk));
  assert.equal(sites(container).length, 0); assert.ok(states(container).every((n) => hasClass(n, "c0")));
  assert.match(byClass(container, "cmap-finding")[0].textContent, /None of the [\d,]+ quoted GPUs are at US sites/);
  assert.match(byClass(byClass(container, "cmap-list")[0], "cmap-list-note")[0].textContent, /No state has quoted supply/);
  assert.ok(byClass(byClass(container, "cmap-rows")[1], "cmap-row").length >= 5);
  assert.ok(!byClass(container, "cmap-lg").some((n) => hasClass(n, "size")), "no size key when no circle is drawn");
  assertClean(container, "no-us");
});

test("a site without lat/lon is counted in its state but not drawn, and a site that projects nowhere does not break the map", () => {
  const page = load(), desk = page.desk((raw) => { raw.sites.forEach((s, i) => { if (s.placement.state && i % 2 === 0) { s.placement.lat = null; s.placement.lon = null; } else if (s.placement.state) { s.placement.lat = 61.2; s.placement.lon = -149.9; } }); });
  const { container } = mount(page, input(desk));
  const us = desk.sites.filter((s) => s.state && quoted(s) > 0);
  assert.equal(us.filter((s) => s.lat === null).length > 0, true);
  assert.ok(sites(container).length <= us.filter((s) => s.lat !== null).length);
  states(container).filter((n) => n.getAttribute("tabindex") === "0").forEach((n) => assert.match(n.getAttribute("aria-label"), /GPUs quoted/));
  assert.ok(states(container).filter((n) => !hasClass(n, "c0")).length >= us.length - 1, "the state tints still say where the supply is");
  const bad = page.desk((raw) => { raw.sites.forEach((s) => { if (s.placement.state) { s.placement.lat = 35.68; s.placement.lon = 139.69; } }); });
  const second = mount(load(), input(bad)); assert.equal(sites(second.container).length, 0); assertClean(second.container, "projects nowhere");
  assertClean(container, "no coordinates");
});

test("a US site with no capacity is not drawn; with a position or an open bid it is a small clean mark; two sites at one point both draw, apart", () => {
  const page = load(), base = page.desk(), template = base.sites.find((s) => s.state && quoted(s) > 0);
  const make = (id, metro, gpus, extra) => ({ ...JSON.parse(JSON.stringify(template)), id, name: id, provider: "Seller " + id, provider_id: "p-" + id, placement: metro, capacity: { gpus, quotes: gpus ? 1 : 0, eligible_quotes: 0, eligible_gpus: 0, models: gpus ? { H100: gpus } : {} }, position_gpus: 0, open_bid_gpus: 0, ...extra });
  const desk = page.desk((raw) => {
    raw.sites = raw.sites.filter((s) => s.country !== "US");
    const sjc = { label: "San Jose, CA", state: "CA", lat: 37.3382, lon: -121.8863 }, den = { label: "Denver, CO", state: "CO", lat: 39.7392, lon: -104.9903 }, lv = { label: "Las Vegas, NV", state: "NV", lat: 36.1699, lon: -115.1398 }, omaha = { label: "Omaha, NE", state: "NE", lat: 41.2565, lon: -95.9345 };
    raw.sites.push(make("empty-plain", den, 0), make("empty-held", lv, 0), make("empty-bid", omaha, 0), make("twin-a", sjc, 400), make("twin-b", sjc, 900), make("twin-c", sjc, 150));
    raw.positions = [{ ...raw.positions[0], id: "pos-held", site_id: "empty-held", model: "H100", gpus: 16, unrealized_usd: "-12.50" }];
    raw.bids = [{ ...raw.bids[0], id: "bid-open", site_id: "empty-bid", status: "open", model: "H100", gpus: 8 }];
  });
  const { container } = mount(page, input(desk)); const labels = sites(container).map((m) => m.getAttribute("aria-label"));
  assert.ok(!labels.some((l) => l.startsWith("Seller empty-plain")), "no capacity, no position, no bid: not drawn");
  assert.ok(labels.some((l) => l.startsWith("Seller empty-held")) && labels.some((l) => l.startsWith("Seller empty-bid")), "a position or an open bid keeps the site on the map");
  const held = sites(container).find((m) => m.getAttribute("aria-label").startsWith("Seller empty-held")); assert.ok(hasClass(held, "is-empty")); held.fire("pointerenter", { pointerType: "mouse" });
  assert.match(detailText(container), /0 GPUs quoted/); assert.ok(detailText(container).includes("−$12.50"));
  const twins = sites(container).filter((m) => /^Seller twin-/.test(m.getAttribute("aria-label"))); assert.equal(twins.length, 3);
  const placed = sites(container).map((m) => ({ at: translate(m), r: radiusOf(m), label: m.getAttribute("aria-label") }));
  placed.forEach((a, i) => placed.slice(i + 1).forEach((b) => assert.ok(Math.hypot(a.at[0] - b.at[0], a.at[1] - b.at[1]) >= a.r + b.r - 1e-6, a.label + " overlaps " + b.label)));
  assert.ok(byClass(container, "cmap-leader").length >= 1, "a circle that had to move is tied to its true point");
  const gone = states(container).find((n) => (n.getAttribute("aria-label") || "").startsWith("Colorado")); assert.equal(gone, undefined, "a state with only an empty site has no supply and no stop");
  assertClean(container, "zero capacity");
});

test("circles never overlap and labels stay inside the frame at every width, with many sites packed into one book", () => {
  const page = load(), template = page.desk().sites.find((s) => s.state && quoted(s) > 0);
  const metros = [["Ashburn, VA", "VA", 39.0438, -77.4875], ["Dallas, TX", "TX", 32.7767, -96.797], ["Phoenix, AZ", "AZ", 33.4484, -112.074], ["Chicago, IL", "IL", 41.8781, -87.6298], ["Atlanta, GA", "GA", 33.749, -84.388], ["Columbus, OH", "OH", 39.9612, -82.9988], ["Hillsboro, OR", "OR", 45.5229, -122.9898], ["Quincy, WA", "WA", 47.2343, -119.8526], ["Seattle, WA", "WA", 47.6062, -122.3321], ["Boston, MA", "MA", 42.3601, -71.0589], ["Newark, NJ", "NJ", 40.7357, -74.1724], ["Reston, VA", "VA", 38.9586, -77.357], ["Richmond, VA", "VA", 37.5407, -77.436], ["Pittsburgh, PA", "PA", 40.4406, -79.9959], ["Detroit, MI", "MI", 42.3314, -83.0458], ["Los Angeles, CA", "CA", 34.0522, -118.2437], ["San Jose, CA", "CA", 37.3382, -121.8863], ["Houston, TX", "TX", 29.7604, -95.3698]];
  const desk = page.desk((raw) => { raw.sites = raw.sites.filter((s) => s.country !== "US"); metros.concat(metros.slice(0, 6)).forEach((m, i) => raw.sites.push({ ...JSON.parse(JSON.stringify(template)), id: "many-" + i, name: "Many " + i, provider: "Seller " + i, provider_id: "p" + i, placement: { label: m[0], state: m[1], lat: m[2], lon: m[3] }, capacity: { gpus: 100 + ((i * 331) % 2400), quotes: 1, eligible_quotes: 0, eligible_gpus: 0, models: { H100: 100 + ((i * 331) % 2400) } }, position_gpus: 0, open_bid_gpus: 0 })); raw.positions = []; raw.bids = []; });
  [1440, 880, 640, 358, 300].forEach((width) => {
    env.width = width; const { container } = mount(page, input(desk)); const marks = sites(container); assert.equal(marks.length, 24, "width " + width);
    const placed = marks.map((m) => ({ at: translate(m), r: radiusOf(m) }));
    placed.forEach((a, i) => { assert.ok(a.r > 0); placed.slice(i + 1).forEach((b) => assert.ok(Math.hypot(a.at[0] - b.at[0], a.at[1] - b.at[1]) >= a.r + b.r - 1e-6, "overlap at width " + width)); assert.ok(a.at[0] - a.r >= -1e-6 && a.at[0] + a.r <= 975 + 1e-6 && a.at[1] - a.r >= -1e-6 && a.at[1] + a.r <= 610 + 1e-6, "inside the frame at width " + width); });
    byClass(container, "cmap-label").forEach((t) => { const x = Number(t.getAttribute("x")), y = Number(t.getAttribute("y")); assert.ok(Number.isFinite(x) && Number.isFinite(y) && x > 0 && x < 975 && y > 0 && y < 610, "label inside the frame at width " + width); assert.ok(t.textContent.length > 0); assert.match(t.getAttribute("text-anchor"), /^(start|middle|end)$/); });
    if (width < 560) assert.ok(byClass(container, "cmap-label").every((t) => /^[A-Z]{2}$/.test(t.textContent)), "state abbreviations on a narrow map");
    else assert.ok(byClass(container, "cmap-label").some((t) => /[a-z]{3}/.test(t.textContent)), "place names on a wide one");
    assertClean(container, "width " + width);
  });
  env.width = 880;
});

test("a resize redraws the marks and nothing else, and a resize with the same width does nothing", () => {
  env.width = 880; const page = load(), desk = page.desk(), { container } = mount(page, input(desk));
  const snapshot = () => JSON.stringify(sites(container).map((m) => [m.getAttribute("transform"), radiusOf(m)])); const wide = snapshot(), shell = states(container).map((n) => n.getAttribute("d"));
  const resize = page.windowListeners.find((l) => l.name === "resize"); assert.ok(resize, "without ResizeObserver the window's resize is heard");
  resize.action(); assert.equal(snapshot(), wide);
  env.width = 390; resize.action(); const narrow = snapshot(); assert.notEqual(narrow, wide, "the circles are laid out again at the new width");
  assert.deepEqual(states(container).map((n) => n.getAttribute("d")), shell);
  assert.ok(Math.max(...sites(container).map(radiusOf)) < Math.max(...JSON.parse(wide).map(([, r]) => r)) * 3, "radii are in the frame's units, scaled for the width");
  env.width = 880; resize.action(); assert.equal(snapshot(), wide, "and back again");
  assertClean(container, "resize");
});

/* ------------------------------------------------------------------ accessibility and the table twin */
test("every focusable mark states its facts; the table twin lists every state with supply and the other states in one line", () => {
  const page = load(), desk = page.desk(), { container } = mount(page, input(desk));
  [...states(container).filter((n) => n.getAttribute("tabindex") === "0"), ...sites(container), ...rows(container)].forEach((n) => {
    assert.ok(/GPUs/.test(n.getAttribute("aria-label")), "an aria-label with the facts"); assert.ok(n.getAttribute("aria-pressed") !== null || n.tagName === "button", "a toggle state");
    assert.match(n.getAttribute("aria-label"), /No positions|Our positions: \d+/);
  });
  assert.ok(sites(container).every((n) => n.getAttribute("tabindex") === "0" && n.getAttribute("role") === "button"));
  const table = findAll(container, (n) => n.tagName === "table")[0], bodyRows = findAll(table, (n) => n.tagName === "tr").slice(1);
  const totals = new Map(); desk.sites.filter((s) => s.state).forEach((s) => totals.set(s.state, (totals.get(s.state) || 0) + quoted(s)));
  const withSupply = [...totals].filter(([, g]) => g > 0);
  withSupply.forEach(([abbr, gpus]) => { const name = page.US.states.find((s) => s.abbr === abbr).name; const row = bodyRows.find((r) => findAll(r, (n) => n.tagName === "th")[0].textContent === name); assert.ok(row, name + " has a row"); assert.equal(findAll(row, (n) => n.tagName === "td")[0].textContent, nf(gpus)); });
  assert.ok(bodyRows.some((r) => /other states? with no quoted supply/.test(r.textContent)), "the states with none are one line");
  findAll(table, (n) => n.tagName === "th").forEach((n) => assert.ok(n.getAttribute("scope") === "col" || n.getAttribute("scope") === "row"));
  assert.ok(byClass(container, "sr-only").some((n) => n.getAttribute("aria-live") === "polite"), "a polite live region");
  const live = byClass(container, "sr-only").find((n) => n.getAttribute("aria-live") === "polite"); stateNode(container, withSupply[0][0], page).fire("click");
  assert.match(live.textContent, /^Selected .+\. [\d,]+ GPUs quoted/);
  assertClean(container, "twin");
});

test("destroy removes everything it added: nodes, document and window listeners, the entrance timer; a later update is a no-op", () => {
  const page = load(), { container, handle } = mount(page);
  assert.ok(container.children.length === 1 && page.documentListeners.some((l) => l.name === "keydown") && page.windowListeners.some((l) => l.name === "resize") && page.timers.some((t) => t.live));
  handle.destroy();
  assert.equal(container.children.length, 0, "the container is empty again"); assert.equal(page.documentListeners.length, 0); assert.equal(page.windowListeners.length, 0); assert.ok(page.timers.every((t) => !t.live), "the entrance timer is cleared");
  handle.update(input(page.desk())); handle.destroy(); assert.equal(container.children.length, 0);
  const again = mount(page); assert.equal(findAll(again.container, (n) => n.tagName === "svg" && hasClass(n, "cmap-svg")).length, 1, "a new one mounts fine");
  again.handle.destroy();
});

test("the API is exactly create(container, { onSelect }) -> { update, destroy }, and create works without options", () => {
  const page = load(); assert.deepEqual(Object.keys(page.ComputeMap), ["create"]);
  const container = new El("div"); const handle = page.ComputeMap.create(container); assert.deepEqual(Object.keys(handle).sort(), ["destroy", "update"]);
  handle.update(input(page.desk())); stateNode(container, page.desk().sites.find((s) => s.state).state, page).fire("click");
  assertClean(container, "no onSelect"); handle.destroy();
});

/* ------------------------------------------------------------------ the rules the content security policy and the design system impose */
test("the scripts keep to the CSP rules and the stylesheet keeps to the motion and theme rules", () => {
  ["us-map.js", "us-states.js"].forEach((name) => { const source = read(name); [/innerHTML/, /insertAdjacentHTML/, /\.style\b/, /localStorage|sessionStorage/, /\beval\(/, /new Function/, /setAttribute\(\s*["']style/, /document\.write/, /\.cssText/].forEach((bad) => assert.doesNotMatch(source, bad, name + " must not use " + bad)); });
  const css = read("map.css"), bare = css.replace(/\/\*[\s\S]*?\*\//g, "");
  assert.doesNotMatch(bare, /@import|url\((?!#)/, "no outside fonts, images or imports; only fragment references to the page's own patterns");
  assert.doesNotMatch(bare, /drop-shadow|backdrop-filter|text-shadow|box-shadow:\s*0\s+0\s+\d+px/, "no glow or glass");
  assert.ok(bare.indexOf("gradient(") < 0 || bare.indexOf("gradient(") > bare.indexOf("@media (forced-colors: active)"), "a gradient only as the hatching in forced colours and print");
  // motion: keyframes live only inside no-preference, and only animate opacity and transform
  const noPref = bare.indexOf("@media (prefers-reduced-motion: no-preference)"); assert.ok(noPref >= 0);
  [...bare.matchAll(/@keyframes ([\w-]+)\s*\{([\s\S]*?\})\s*\}/g)].forEach((m) => { assert.ok(m.index > noPref, m[1] + " is inside no-preference"); assert.ok([...m[2].matchAll(/([a-z-]+)\s*:/g)].every((p) => ["opacity", "transform"].includes(p[1])), m[1] + " animates only opacity and transform"); });
  assert.equal([...bare.matchAll(/(^|[^-])animation\s*:/g)].filter((m) => m.index < noPref).length, 0, "no animation outside no-preference");
  // themes: the dark block and the system-mirror block carry the same tokens and values; light defines every one of them too
  const tokens = (text) => Object.fromEntries([...text.matchAll(/(--cm-[\w-]+)\s*:\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]));
  const light = tokens(/\.cmap \{([\s\S]*?)\}/.exec(bare)[1]), dark = tokens(/:root\[data-theme="dark"\] \.cmap \{([\s\S]*?)\}/.exec(bare)[1]), mirror = tokens(/:root:not\(\[data-theme\]\) \.cmap \{([\s\S]*?)\}/.exec(bare)[1]);
  assert.deepEqual(mirror, dark, "the system-mirror block equals the dark block");
  Object.keys(dark).forEach((name) => assert.ok(name in light, name + " has a light value")); ["--cm-none", "--cm-1", "--cm-2", "--cm-3", "--cm-4", "--cm-5", "--cm-disc", "--cm-disc-line", "--cm-pos"].forEach((name) => assert.ok(name in dark && name in light, name));
  assert.match(bare, /@media \(forced-colors: active\)/); assert.match(bare, /\.cmap-state\.c5 \{ fill: url\(#cmap-t5\)/, "forced colours get hatching, one density per step");
  assert.match(bare, /@media \(max-width: 720px\)[\s\S]*min-height: 44px/, "touch targets are 44px on a phone");
});
