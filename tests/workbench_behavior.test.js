"use strict";
// Drive the shipped script's event handlers; every fetch is an offline fixture.
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { randomUUID } = require("node:crypto");
const assets = process.env.COMPUTEBASIS_WORKBENCH_ASSETS;
assert.ok(assets, "COMPUTEBASIS_WORKBENCH_ASSETS must point to the checked-out workbench assets");
const html = fs.readFileSync(path.join(assets, "index.html"), "utf8");
const script = fs.readFileSync(path.join(assets, "workbench.js"), "utf8");
const draftScript = fs.readFileSync(path.join(assets, "workbench-drafts.js"), "utf8");

class Node {
  constructor(tag = "div", attributes = {}) {
    this.tagName = tag; this.attributes = { ...attributes }; this.children = []; this.listeners = new Map();
    this.dataset = {}; this.hidden = "hidden" in attributes; this.disabled = "disabled" in attributes;
    this._text = ""; this._value = tag === "select" ? null : ""; this.className = attributes.class || "";
    this.classList = { add: (name) => this.toggleClass(name, true), remove: (name) => this.toggleClass(name, false), toggle: (name, flag) => this.toggleClass(name, flag) };
  }
  toggleClass(name, flag) { const classes = new Set(this.className.split(/\s+/).filter(Boolean)); if (flag) classes.add(name); else classes.delete(name); this.className = [...classes].join(" "); }
  get textContent() { return this._text + this.children.map((child) => child.textContent).join(""); }
  set textContent(value) { this._text = String(value); this.children = []; }
  get value() { return this.tagName === "select" ? this._value ?? this.firstChild?.value ?? "" : this._value; }
  set value(value) { this._value = String(value); }
  get firstChild() { return this.children[0]; }
  get isConnected() { return Boolean(this.root || this.parentNode?.isConnected); }
  append(...nodes) { nodes.forEach((node) => { node.parentNode = this; this.children.push(node); }); }
  replaceChildren(...nodes) { this.children.forEach((node) => { node.parentNode = null; }); this.children = []; this._text = ""; if (this.tagName === "select") this._value = null; this.append(...nodes); }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  removeAttribute(key) { delete this.attributes[key]; }
  remove() { if (this.parentNode) { this.parentNode.children = this.parentNode.children.filter((child) => child !== this); this.parentNode = null; } }
  addEventListener(name, action) { this.listeners.set(name, [...(this.listeners.get(name) || []), action]); }
  async emit(name, extra = {}) { if (this.disabled && name === "click") return; await Promise.all((this.listeners.get(name) || []).map((action) => action({ preventDefault() {}, target: this, ...extra }))); }
  focus() { this.focused = true; }
  scrollIntoView() { this.scrolled = true; }
}

function harness({ prefersDark = false, hash = "" } = {}) {
  const nodes = new Map();
  for (const tag of html.matchAll(/<([a-z][a-z0-9]*)\b([^>]*)>/g)) {
    const attributes = Object.fromEntries([...tag[2].matchAll(/([a-z-]+)="([^"]*)"/g)].map((match) => [match[1], match[2]]));
    if (!attributes.id) continue;
    const node = new Node(tag[1], { ...attributes, ...( /\bhidden\b/.test(tag[2]) ? { hidden: "" } : {}), ...(/\bdisabled\b/.test(tag[2]) ? { disabled: "" } : {}) }); node.root = true; node.checked = /\bchecked\b/.test(tag[2]);
    nodes.set(attributes.id, node);
  }
  for (const match of html.matchAll(/<select\b[^>]*id="([^"]+)"[^>]*>([\s\S]*?)<\/select>/g)) {
    const select = nodes.get(match[1]);
    for (const option of match[2].matchAll(/<option\b[^>]*value="([^"]*)"[^>]*>([^<]*)<\/option>/g)) { const node = new Node("option"); node.value = option[1]; node.textContent = option[2]; select.append(node); }
  }
  const nav = [...html.matchAll(/data-view="([^"]+)"/g)].map((match) => { const node = new Node("button"); node.dataset.view = match[1]; node.root = true; return node; });
  const window = new Node("window"); window.matchMedia = () => ({ matches: prefersDark }); window.scrolls = []; window.scrollTo = (options) => window.scrolls.push(options);
  window.location = { pathname: "/", search: "", hash }; window.pushed = [];
  window.history = { pushState: (_state, _title, url) => { window.pushed.push(url); window.location.hash = url.startsWith("#") ? url : ""; } };
  const documentElement = new Node("html"); const calls = []; const responses = []; const timers = new Map(); const intervals = []; let timerId = 0;
  const allCalls = []; const sessionCalls = []; const logoutResponses = []; let booting = false;
  let clockNow = Date.now(); class ClockDate extends Date { static now() { return clockNow; } }
  const documentListeners = new Map(); const pageDocument = { hidden: false, addEventListener: (name, action) => documentListeners.set(name, [...(documentListeners.get(name) || []), action]) };
  const headerBag = (headers) => { const lower = Object.fromEntries(Object.entries(headers).map(([key, value]) => [key.toLowerCase(), value])); return { get: (name) => lower[name.toLowerCase()] ?? null }; };
  const fetch = (url, options) => {
    allCalls.push({ url, options });
    if (url.startsWith("/v1/session/")) sessionCalls.push({ url, options });
    else if (!booting || url === "/v1/market/current") calls.push({ url, options });
    if (url === "/v1/session/logout") return logoutResponses.shift() || Promise.resolve({ ok: true, status: 200, json: async () => ({ ended: true }) });
    const response = responses.shift(); assert.ok(response, "Unexpected request: " + url); return response(options);
  };
  const context = vm.createContext({ Date: ClockDate, document: { ...pageDocument, get hidden() { return pageDocument.hidden; }, documentElement, getElementById: (id) => { assert.ok(nodes.has(id), "Missing DOM element " + id); return nodes.get(id); }, createElement: (tag) => new Node(tag), createElementNS: (_, tag) => new Node(tag), querySelectorAll: () => nav }, window, fetch, AbortController, structuredClone, crypto: { randomUUID }, setTimeout: (fn, delay) => { timers.set(++timerId, { fn, delay }); return timerId; }, clearTimeout: (id) => timers.delete(id), setInterval: (fn) => intervals.push(fn), console });
  vm.runInContext(draftScript, context, { filename: "workbench-drafts.js" });
  vm.runInContext(script, context, { filename: "workbench.js" });
  function reply(body, status = 200, headers = {}) { responses.push(async () => ({ ok: status >= 200 && status < 300, status, headers: headerBag(headers), json: async () => structuredClone(body), text: async () => typeof body === "string" ? body : JSON.stringify(body) })); }
  function pending(ignoreAbort = false) {
    let resolve; let reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    responses.push((options) => { if (!ignoreAbort) options.signal.addEventListener("abort", () => { const error = new Error("aborted"); error.name = "AbortError"; reject(error); }, { once: true }); return promise; });
    return { resolve: (body, status = 200, headers = {}) => resolve({ ok: status >= 200 && status < 300, status, headers: headerBag(headers), json: async () => body, text: async () => body }), reject };
  }
  async function connect(index = indexFixture(), indexHeaders = {}) {
    booting = true;
    reply({ auth_mode: "local_session", csrf_token: "invented-csrf-marker", expires_at: "2099-01-01T00:00:00Z" }); reply(index, 200, indexHeaders);
    reply({ enabled: true, running: false, scopes: [] });
    reply({ revision: null, as_of: "2026-01-01T00:00:00Z", state: { schema_version: "paper-inventory/1.0", sites: [], lots: [], positions: [] }, summary: { by_unit_kind: {} }, sites: [], lots: [], timeline: [] });
    reply({ requirements_version: "invented", requirements: [], scope_options: [], request: { scopes: [], subjects: {}, evidence: [], requirements: [] } });
    reply({ features: [] });
    await window.emit("load"); booting = false;
  }
  async function visibility(hidden) { pageDocument.hidden = hidden; await Promise.all((documentListeners.get("visibilitychange") || []).map((action) => action({}))); }
  const clock = { advance: (ms) => { clockNow += ms; } };
  return { visibility, clock, page: pageDocument, replyLogout: (body, status) => logoutResponses.push(Promise.resolve({ok: status >= 200 && status < 300, status, json: async () => body})), node: (id) => nodes.get(id), calls, reply, pending, timers, intervals, window, documentElement, connect, nav, allCalls, sessionCalls };
}

const observation = (id, amount, overrides = {}) => ({ id, source_id: "feed:prices", kind: "listing_ask", hardware: { model: id, accelerator_count: "1" }, price: { amount, currency: "USD", unit: "gpu_hour" }, observed_at: "2026-01-01T00:00:00Z", expires_at: "2099-01-01T00:00:00Z", status: "claimed", region: { country_code: "US" }, ...overrides });
function indexFixture(overrides = {}) {
  const scopes = [{ captured_at: "2026-01-01T00:00:00Z", observation_count: 1, catalog_record_count: 0, filters: {}, stale: false, coverage: { complete: false } }];
  return { as_of: "2026-01-01T00:00:00Z", sources: [{ source_id: "feed:prices", enabled: true, can_attempt_read: true, rights_status: "allowed", permissions: { benchmark: "PASS" }, max_age_s: 7200, scopes, latest: scopes[0] }], observations: [observation("GPU-A", "2.0000000000000000000000001")], catalog_records: [], snapshots: [{ snapshot_id: "a".repeat(64), source_id: "feed:prices" }], ...overrides };
}
const tick = () => new Promise((resolve) => setImmediate(resolve));
const renderedPrices = (h) => h.node("records-body").children.map((row) => row.children[2]?.textContent);

test("startup is locked and performs no fetch or sample insertion", () => {
  const h = harness(); assert.equal(h.calls.length, 0); assert.equal(h.node("pricing-input").value, ""); assert.equal(h.window.listeners.get("load").length, 1); assert.equal(h.node("reload-index").disabled, true); assert.equal(h.node("refresh-market").disabled, true);
});

test("theme starts from system preference and toggles without fetch or session retention", async () => {
  const h = harness({ prefersDark: true });
  assert.equal(h.documentElement.attributes["data-theme"], "dark");
  assert.equal(h.node("theme-toggle").attributes["aria-pressed"], "true");
  await h.node("theme-toggle").emit("click");
  assert.equal(h.documentElement.attributes["data-theme"], "light");
  assert.equal(h.node("theme-toggle").attributes["aria-pressed"], "false");
  assert.equal(h.calls.length, 0);
  await h.connect(); await h.node("theme-toggle").emit("click"); await h.node("disconnect").emit("click");
  assert.equal(h.documentElement.attributes["data-theme"], "dark");
  assert.equal(h.node("pricing-input").value, "");
  const fresh = harness(); assert.equal(fresh.documentElement.attributes["data-theme"], "light");
});

test("each workspace navigation action has one handler and updates current page", async () => {
  const h = harness(); const nav = h.nav.find((button) => button.dataset.view === "inventory");
  assert.equal(nav.listeners.get("click").length, 1); await nav.emit("click");
  assert.equal(h.node("inventory-view").hidden, false); assert.equal(h.node("market-view").hidden, true);
  assert.equal(nav.attributes["aria-current"], "page");
});

test("arriving on another view starts at the top; choosing the current view leaves the scroll position alone", async () => {
  const h = harness(); const nav = (view) => h.nav.find((button) => button.dataset.view === view);
  h.window.scrolls.length = 0;
  await nav("inventory").emit("click");
  assert.equal(h.window.scrolls.length, 1);
  assert.equal(h.window.scrolls[0].top, 0); assert.equal(h.window.scrolls[0].behavior, "instant");
  await nav("inventory").emit("click");
  assert.equal(h.window.scrolls.length, 1, "the page does not jump when it is already showing");
});

test("the landing page is a page of its own: choosing a view writes its address, and the landing address is plain", async () => {
  const h = harness(); const nav = (view) => h.nav.find((button) => button.dataset.view === view);
  assert.equal(h.documentElement.attributes["data-page"] ?? "landing", "landing");
  await nav("inventory").emit("click");
  assert.deepEqual([...h.window.pushed], ["#inventory"]);
  assert.equal(h.documentElement.attributes["data-page"], "app");
  await nav("inventory").emit("click");
  assert.equal(h.window.pushed.length, 1, "choosing the page already showing adds no history entry");
  await nav("brief").emit("click");
  assert.deepEqual([...h.window.pushed], ["#inventory", "/"]);
  assert.equal(h.documentElement.attributes["data-page"], "landing");
});

test("back and forward restore the page without writing history again", async () => {
  const h = harness(); await h.nav.find((button) => button.dataset.view === "quotes").emit("click");
  assert.deepEqual([...h.window.pushed], ["#quotes"]);
  h.window.location.hash = ""; await h.window.emit("popstate");
  assert.equal(h.node("brief-view").hidden, false); assert.equal(h.node("quotes-view").hidden, true);
  assert.equal(h.documentElement.attributes["data-page"], "landing");
  h.window.location.hash = "#quotes"; await h.window.emit("popstate");
  assert.equal(h.node("quotes-view").hidden, false);
  assert.equal(h.window.pushed.length, 1, "restoring a page from history never pushes");
});

test("opening on an app address shows that page, and an unknown address shows the landing page", async () => {
  const deep = harness({ hash: "#inventory" }); await deep.window.emit("load");
  assert.equal(deep.node("inventory-view").hidden, false); assert.equal(deep.node("brief-view").hidden, true);
  assert.equal(deep.window.pushed.length, 0, "opening a link does not add a history entry");
  const odd = harness({ hash: "#not-a-page" }); await odd.window.emit("load");
  assert.equal(odd.node("brief-view").hidden, false);
  const loose = harness({ hash: "#brief" }); await loose.window.emit("load");
  assert.equal(loose.node("brief-view").hidden, false);
});

test("both header theme toggles stay in step", async () => {
  const h = harness(); await h.node("lp-theme-toggle").emit("click");
  assert.equal(h.documentElement.attributes["data-theme"], "dark");
  assert.equal(h.node("theme-toggle").attributes["aria-pressed"], "true");
  assert.equal(h.node("lp-theme-toggle").attributes["aria-pressed"], "true");
  await h.node("theme-toggle").emit("click");
  assert.equal(h.node("lp-theme-toggle").attributes["aria-pressed"], "false");
});

test("actual ECB quote_per_base is exact, separate from prices and model metadata", async () => {
  const h = harness(); const metadata = { role: "model_metadata", model_id: "invented/model", price_eligible: false };
  const fx = { role: "informational_reference_fx", base_currency: "EUR", quote_currency: "USD", quote_per_base: "1.123456789012345678901", observed_date: "2026-01-01" };
  const index = indexFixture(); index.catalog_records = [fx, metadata];
  index.sources.push({ source_id: "feed:fx", can_attempt_read: true, scopes: [{ catalog_record_count: 1 }] }, { source_id: "feed:models", can_attempt_read: true, scopes: [{ catalog_record_count: 1 }] });
  await h.connect(index);
  assert.equal(h.node("metric-observations").textContent, "1"); assert.equal(h.node("metric-sources").textContent, "1");
  assert.match(h.node("metric-snapshots").textContent, /receipts across all roles; prices exclude FX/);
  assert.match(h.node("metric-source-total").textContent, /3 sources with retained data/); assert.equal(h.node("metric-admitted").textContent, "3");
  assert.match(h.node("fx-records").textContent, /1\.123456789012345678901 USD/); assert.match(h.node("fx-records").textContent, /1 EUR/);
  assert.equal(h.node("fx-section").hidden, false); assert.equal(h.node("model-section").hidden, false);
});

test("native price sort retains digits and groups currency and units before ranking", async () => {
  const h = harness(); await h.connect(indexFixture({ observations: [observation("higher", "2.0000000000000000000000002"), observation("lower", "2.0000000000000000000000001"), observation("node", "0.1", { price: { amount: "0.1", currency: "USD", unit: "node_hour" } }), observation("eur", "999", { price: { amount: "999", currency: "EUR", unit: "gpu_hour" } })] }));
  h.node("record-sort").value = "price-asc"; await h.node("record-sort").emit("input");
  assert.deepEqual(renderedPrices(h), ["999 EUR", "2.0000000000000000000000001 USD", "2.0000000000000000000000002 USD", "0.1 USD"]);
  h.node("record-sort").value = "price-desc"; await h.node("record-sort").emit("input");
  assert.deepEqual(renderedPrices(h), ["999 EUR", "2.0000000000000000000000002 USD", "2.0000000000000000000000001 USD", "0.1 USD"]);
});

test("filtering combines scope and search, reset restores rows without fetching", async () => {
  const h = harness(); await h.connect(indexFixture({ observations: [observation("GPU-A", "1"), observation("GPU-B", "2", { kind: "aggregate_advertised_index" })] }));
  h.node("record-query").value = "gpu"; h.node("kind-filter").value = "aggregate_advertised_index"; await h.node("record-query").emit("input");
  assert.equal(h.node("record-count").textContent, "1 matching records"); assert.match(h.node("records-body").textContent, /GPU-B/); assert.doesNotMatch(h.node("records-body").textContent, /GPU-A/);
  await h.node("reset-filters").emit("click"); assert.equal(h.node("record-count").textContent, "2 matching records"); assert.equal(h.calls.length, 1);
});

test("money-looking JSON is submitted byte-for-byte and edited responses are labelled previous input", async () => {
  const h = harness(); await h.connect(); const raw = '{"amount":"12345678901234567890.000000000000001","field":1,"field":2}';
  h.node("pricing-input").value = raw; await h.node("pricing-input").emit("input");
  h.reply({ snapshot_id: "synthetic-result", result: { status: "indicative", pricing_provenance: {source_evidence_eligible: true}, economics: { currency: "EUR" }, bid: { submitted_limit: "0.93000000000000000001" } } });
  await h.node("evaluate-pricing").emit("click"); assert.equal(h.calls[1].options.body, raw); assert.match(h.node("pricing-summary").textContent, /0\.93000000000000000001 EUR/);
  h.node("pricing-input").value = "{}"; await h.node("pricing-input").emit("input"); assert.equal(h.node("pricing-result-state").textContent, "Previous input");
});

test("invalid JSON gives an actionable editor error and makes no request", async () => {
  const h = harness(); await h.connect(); h.node("cash-input").value = "{"; await h.node("cash-input").emit("input"); await h.node("evaluate-cash").emit("click");
  assert.equal(h.calls.length, 1); assert.match(h.node("cash-input-state").textContent, /Invalid JSON/); assert.equal(h.node("cash-input").focused, true);
});

test("logout aborts active requests and late responses cannot restore old data or feedback", async () => {
  const h = harness(); await h.connect(); const delayed = h.pending(true); const running = h.node("reload-index").emit("click"); await tick();
  await h.node("disconnect").emit("click"); assert.equal(h.calls[1].options.signal.aborted, true);
  delayed.resolve(indexFixture({ observations: [observation("SECRET-OLD", "9")] })); await running;
  assert.equal(h.node("metric-observations").textContent, "—"); assert.doesNotMatch(h.node("records-body").textContent, /SECRET-OLD/); assert.match(h.node("notice").textContent, /Session ended/); assert.equal(h.node("pricing-input").value, "");
});

test("late failed bootstrap cannot clear a newer connected workspace", async () => {
  const h = harness(); const old = h.pending(true); const first = h.node("connect-session").emit("click"); await tick();
  await h.node("disconnect").emit("click"); const resumed = h.connect(indexFixture({ observations: [observation("NEW", "3")] }));
  old.resolve({ detail: "old rejected" }, 401); await first; await resumed;
  assert.equal(h.node("session-state").textContent, "Connected"); assert.match(h.node("records-body").textContent, /NEW/); assert.equal(h.node("reload-index").disabled, false);
});

test("stop waiting and timeout retain drafts, abort transport, and do not duplicate feed reads", async () => {
  const h = harness(); await h.connect(); h.node("pricing-input").value = '{"draft":"kept"}';
  h.pending(); const reading = h.node("refresh-market").emit("click"); await tick(); await h.node("cancel-request").emit("click"); await reading;
  assert.match(h.node("notice").textContent, /Server work may continue/); assert.equal(h.node("pricing-input").value, '{"draft":"kept"}'); assert.equal(h.calls.length, 2);
  h.pending(); const reloading = h.node("reload-index").emit("click"); await tick(); const timer = [...h.timers.values()][0]; assert.equal(timer.delay, 30000); timer.fn(); await reloading;
  assert.match(h.node("notice").textContent, /timed out/); assert.equal(h.node("reload-index").disabled, false);
});

test("expired read sessions renew once, while mutations are never replayed", async () => {
  const h = harness(); await h.connect(); h.node("inference-input").value = '{"sensitive":"draft"}';
  h.reply({ detail: "unauthorized" }, 401); h.reply({ auth_mode: "local_session", csrf_token: "renewed-marker" }); h.reply(indexFixture());
  await h.node("reload-index").emit("click"); assert.equal(h.node("inference-input").value, '{"sensitive":"draft"}');
  h.node("cash-input").value = '{}'; await h.node("cash-input").emit("input"); h.reply({ detail: "unauthorized" }, 401); h.reply({ auth_mode: "local_session", csrf_token: "mutation-renewed-marker" });
  await h.node("evaluate-cash").emit("click"); assert.match(h.node("notice").textContent, /no mutation was retried/);
  assert.equal(h.sessionCalls.filter((call) => call.url.includes("bootstrap")).length, 3);
  assert.equal(h.calls.filter((call) => call.url === "/v1/cash/evaluate").length, 1);
});

test("source admission disables refresh when held and exposes bounded coverage independently of success notices", async () => {
  const h = harness(); const index = indexFixture(); index.sources[0].can_attempt_read = false; index.coverage = { display_truncated: true, history_scan_truncated: true }; await h.connect(index);
  assert.equal(h.node("refresh-market").disabled, true); assert.match(h.node("coverage-note").textContent, /row limit reached/); assert.match(h.node("coverage-note").textContent, /older source scopes may be missing/); assert.match(h.node("sources-grid").textContent, /Partial coverage/);
});

test("synthetic load is explicit, unauthenticated, separate, and discarded after pagehide", async () => {
  const h = harness(); const delayed = h.pending(true); const loading = h.node("load-sample").emit("click"); await tick();
  assert.equal(h.calls[0].options.headers.Authorization, undefined); await h.window.emit("pagehide"); delayed.resolve('{"synthetic":"late"}'); await loading;
  assert.equal(h.node("pricing-input").value, ""); assert.equal(h.node("notice").hidden, true);
});

test("live reference uses only current eligible exact currency/billing cohorts with no commercial terms", async () => {
  const h = harness(); const row = observation("model-x", "4.01", { kind: "aggregate_advertised_index", price: { amount: "4.01", currency: "EUR", unit: "gpu_hour" }, rights: { observe: "PASS", benchmark: "PASS" }, extensions: { billing_type: "reserved", reservation_months: 6 } });
  const index = indexFixture({ observations: [row, { ...row, id: "stale-x", index_stale: true }] }); await h.connect(index); h.node("live-model").value = "model-x"; await h.node("live-model").emit("change");
  h.reply(index); h.reply({ snapshot_id: "live-result", result: { status: "indicative", benchmark: { price: "4.01", currency: "EUR", cohort: { scope: "aggregate_reference" } } } }); await h.node("evaluate-live-reference").emit("click");
  assert.equal(h.calls.length, 3, h.node("notice").textContent + " / " + h.node("live-reference-state").textContent);
  const packet = JSON.parse(h.calls[2].options.body); assert.equal(packet.target.currency, "EUR"); assert.deepEqual(packet.target.aggregate_terms, { billing_type: "reserved", reservation_months: 6 }); assert.equal(packet.market.observations.length, 1); assert.equal(packet.commercial, null); assert.equal(packet.market.policy.parameters.benchmark.source_rules["feed:prices"].quality, "1");
  assert.match(h.node("pricing-mode").textContent, /scenario.*saved policy/); assert.match(h.node("pricing-summary").textContent, /4\.01 EUR/); assert.equal(h.node("pricing-view").hidden, false);
});

function inventoryFixture() {
  const sites = [{ site_id: "invented:east", name: "Invented East", latitude: "40.5", longitude: "-70.1", country_code: "US" }, { site_id: "invented:unknown", name: "Invented location withheld", latitude: null, longitude: null }];
  const lots = [{ lot_id: "invented:gpus", site_id: sites[0].site_id, unit_kind: "gpu", unit_ids: ["g1", "g2"], hardware_model: "Invented accelerator", start_at: "2026-01-01T00:00:00Z", end_at: "2026-02-01T00:00:00Z" }, { lot_id: "invented:node", site_id: sites[1].site_id, unit_kind: "node", unit_ids: ["n1"], start_at: "2026-01-01T00:00:00Z", end_at: "2026-02-01T00:00:00Z" }];
  const position = { position_id: "invented:sale", lot_id: lots[0].lot_id, unit_ids: ["g1"], status: "sold", start_at: "2026-01-05T00:00:00Z", end_at: "2026-01-20T00:00:00Z", sale_value: { amount: "12.3456789012345678901", currency: "EUR", unit: "position_total" } };
  const counts = { total: 2, available: 1, reserved: 0, sold: 1, maintenance: 0, unavailable: 0, unsold: 1 }; const nodeCounts = { total: 1, available: 1, reserved: 0, sold: 0, maintenance: 0, unavailable: 0, unsold: 1 };
  return { revision: 1, persisted: true, as_of: "2026-01-10T00:00:00Z", state: { schema_version: "paper-inventory/1.0", sites, lots, positions: [position] }, sites: [{ ...sites[0], by_unit_kind: { gpu: counts } }, { ...sites[1], by_unit_kind: { node: nodeCounts } }], lots: [{ ...lots[0], active: true, counts, positions: [position] }, { ...lots[1], active: true, counts: nodeCounts, positions: [] }], summary: { by_unit_kind: { gpu: counts, node: nodeCounts } }, timeline: [{ kind: "availability", lot_id: lots[0].lot_id, unit_ids: ["g1", "g2"], start_at: lots[0].start_at, end_at: lots[0].end_at, active_at_as_of: true }, { kind: "sold", ...position, active_at_as_of: true }], audit: { recent: [], truncated: false } };
}
const landFixture = { type: "FeatureCollection", features: [{ geometry: { type: "Polygon", coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] } }] };
function policyFixture() { return { policy: { schema_version: "1.0.0", policy_id: "invented:policy", version: "0.1.0", model_version: "inverse-linear/1.0.0", registry_version: "1.0.0", effective_at: "2026-01-01T00:00:00Z", expires_at: null, critical_market_fields: [], critical_feature_ids: [], parameters: { benchmark: { estimator: "weighted_median", max_source_share: "0.8", max_provider_share: "0.7", min_observations: 2, min_sources: 1, min_provider_groups: 1, source_rules: { "feed:prices": { enabled: true, quality: "0.123456789012345678901", max_age_hours: "2", half_life_hours: "1" } } } }, extensions: {} }, feature_definitions: [], notes: "Invented policy; not calibrated" }; }
async function loadSavedPolicy(h) { const document = policyFixture(); const entry = { revision: "b".repeat(64), policy_id: document.policy.policy_id, version: document.policy.version, document }; h.reply({ entries: [entry], source_catalog: [] }); await h.node("policy-load").emit("click"); h.reply(entry); h.node("policy-select").value = entry.revision; await h.node("policy-select").emit("change"); return entry; }

test("native cloud meter tariffs are displayed exactly and cannot enter GPU benchmark cohorts", async () => {
  const h = harness(); await h.connect(indexFixture({ observations: [], catalog_records: [{ id: "native-meter", source_id: "feed:tariffs", kind: "cloud_meter_tariff", provider_region: "invented-east-1", native_price: { amount: "14.000000000000000001", currency: "EUR", unit: "node_hour" }, gpu_hour_benchmark_eligible: false }] }));
  assert.deepEqual(renderedPrices(h), ["14.000000000000000001 EUR"]); assert.match(h.node("records-body").textContent, /node_hour/); assert.match(h.node("records-body").textContent, /invented-east-1/); assert.equal(h.node("evaluate-live-reference").disabled, true);
});

test("published model rate catalogs remain distinct from metadata-only model discovery and measured qualification", async () => {
  const h = harness(); await h.connect(indexFixture({ observations: [], catalog_records: [{ kind: "model_price_catalog", model_id: "invented/routed-model", conditional_pricing_present: true, metadata: { pricing: { prompt: "0.00000001", overrides: [{ min_prompt_tokens: 50 }] } } }, { kind: "model_metadata", model_id: "invented/metadata-only", price_eligible: false }] }));
  assert.equal(h.node("metric-observations").textContent, "0"); assert.match(h.node("model-record-count").textContent, /1 advertised rate catalogs \/ 0 unpriced model catalogs \/ 1 metadata only/); assert.match(h.node("model-records").textContent, /conditional pricing retained, unapplied/); assert.match(h.node("model-records").textContent, /No measured runtime qualification/);
});

test("quarantined and missing token rates remain explicitly unpriced while retrieval and pricing coverage stay distinct", async () => {
  const h = harness(); const index = indexFixture({ observations: [], catalog_records: [{ kind: "model_price_catalog", model_id: "invented/invalid-rate", price_eligible: false, price_status: "unpriced_invalid_advertised_dimensions", metadata: { pricing: null } }, { kind: "model_price_catalog", model_id: "invented/missing-rates", price_eligible: false, price_status: "unpriced_missing_token_rates", metadata: { pricing: {} } }, { kind: "model_price_catalog", model_id: "invented/partial-rates", price_status: "partial_token_rates", metadata: { pricing: { prompt: "0" } } }] }); index.sources[0].scopes[0].coverage = { complete: true, price_coverage_complete: false }; await h.connect(index);
  assert.equal(h.node("metric-observations").textContent, "0"); assert.match(h.node("model-record-count").textContent, /1 advertised rate catalogs \/ 2 unpriced model catalogs/); assert.match(h.node("model-records").textContent, /UNPRICED \/ invalid advertised dimensions quarantined/); assert.match(h.node("model-records").textContent, /UNPRICED \/ input\/output token rates not published/); assert.match(h.node("model-records").textContent, /Partial current-default token rates/); assert.match(h.node("sources-grid").textContent, /Pricing coverage is partial/);
});

test("inventory starts empty and map/table selection retains typed unit counts without geocoding", async () => {
  const h = harness(); assert.match(h.node("inventory-totals").textContent, /No declared capacity/); await h.connect(); h.reply(inventoryFixture()); h.reply(landFixture); await h.node("inventory-load").emit("click");
  assert.match(h.node("inventory-totals").textContent, /gpu \/ declared units/); assert.match(h.node("inventory-totals").textContent, /node \/ declared units/); assert.match(h.node("inventory-map-state").textContent, /1 located sites \/ 1 unmapped/);
  const markers = h.node("inventory-map").children.filter((node) => node.attributes.role === "button"); assert.equal(markers.length, 1); assert.equal(markers[0].attributes.tabindex, "0");
  assert.equal(markers[0].children.filter((node) => node.attributes.role === "button").length, 0); assert.equal(markers[0].children.filter((node) => node.attributes.class === "map-hit-target").length, 1);
  const css = fs.readFileSync(path.join(assets, "workbench.css"), "utf8"); assert.match(css, /stroke-width: 44px; vector-effect: non-scaling-stroke; pointer-events: all/);
  await markers[0].emit("keydown", { key: "Enter" }); assert.match(h.node("inventory-count").textContent, /1 lots \/ 2 declared/); assert.match(h.node("lot-detail").textContent, /12\.3456789012345678901 EUR/); assert.match(h.node("lot-detail").textContent, /2026-01-05T00:00:00Z/);
  await h.node("inventory-clear-site").emit("click"); assert.match(h.node("inventory-count").textContent, /2 lots/); assert.equal(h.calls.length, 3);
});

test("fixed UTC inventory requests encode the timestamp and reject impossible dates without a fetch", async () => {
  const h = harness(); await h.connect(); h.node("inventory-live").checked = false; await h.node("inventory-live").emit("change"); h.node("inventory-at").value = "2026-02-30T00:00:00Z"; await h.node("inventory-load").emit("click"); assert.equal(h.calls.length, 1); assert.match(h.node("notice").textContent, /valid UTC instant/);
  h.node("inventory-at").value = "2026-01-10T00:00:00Z"; h.reply(inventoryFixture()); h.reply(landFixture); await h.node("inventory-load").emit("click"); assert.equal(h.calls[1].url, "/v1/inventory?as_of=2026-01-10T00%3A00%3A00Z");
});

test("unsold uses backend counts and includes reserved capacity while available remains distinct", async () => {
  const h = harness(); await h.connect(); const report = inventoryFixture();
  const reserved = { position_id: "invented:reserved", lot_id: report.lots[0].lot_id, unit_ids: ["g1", "g2"], status: "reserved", start_at: "2026-01-05T00:00:00Z", end_at: "2026-01-20T00:00:00Z" };
  const counts = { total: 2, available: 0, reserved: 2, sold: 0, maintenance: 0, unavailable: 0, unsold: 2 };
  report.state.positions = [reserved]; report.lots[0].counts = counts; report.lots[0].positions = [reserved]; report.summary.by_unit_kind.gpu = counts; report.sites[0].by_unit_kind.gpu = counts;
  report.timeline = report.timeline.filter((row) => row.kind === "availability").concat({ ...reserved, kind: "reserved", active_at_as_of: true });
  h.reply(report); h.reply(landFixture); await h.node("inventory-load").emit("click");
  const gpuTotals = h.node("inventory-totals").children[0].children[1].children;
  assert.equal(gpuTotals.find((pair) => pair.children[0].textContent === "unsold").children[1].textContent, "2");
  assert.equal(gpuTotals.find((pair) => pair.children[0].textContent === "available").children[1].textContent, "0");
  h.node("inventory-query").value = "Invented accelerator"; h.node("inventory-status").value = "unsold"; await h.node("inventory-status").emit("input"); assert.match(h.node("inventory-count").textContent, /1 lots \/ 2 declared/); assert.match(h.node("inventory-body").textContent, /2 gpu/);
  h.node("inventory-status").value = "available"; await h.node("inventory-status").emit("input"); assert.match(h.node("inventory-count").textContent, /0 lots \/ 2 declared/); assert.match(html, /Unsold includes available, reserved and maintenance units within active supply/);
});

test("inventory demo uses pure validation and cannot be persisted by its save button", async () => {
  const h = harness(); await h.connect(); const report = inventoryFixture(); report.revision = null; report.persisted = false; h.reply(report); h.reply(landFixture); await h.node("inventory-demo").emit("click");
  assert.equal(h.calls[1].url, "/v1/inventory/evaluate"); assert.equal(h.calls[1].options.method, "POST"); assert.match(h.calls[1].options.body, /independently_invented_synthetic_ui_demo/); assert.match(h.node("inventory-mode").textContent, /SYNTHETIC/); assert.equal(h.node("inventory-save").disabled, true);
  const packet = JSON.parse(h.calls[1].options.body); assert.deepEqual(Object.keys(packet.state).sort(), ["lots", "positions", "provenance", "schema_version", "sites"]); assert.equal(packet.state.provenance, "synthetic");
  await h.node("inventory-save").emit("click"); assert.equal(h.calls.length, 3); await h.node("inventory-demo").emit("click"); assert.equal(h.node("inventory-input").value, ""); assert.equal(h.node("inventory-mode").textContent, "No inventory loaded");
});

test("inventory revision conflict preserves duplicate-key draft bytes and displays reload action", async () => {
  const h = harness(); await h.connect(); h.reply(inventoryFixture()); h.reply(landFixture); await h.node("inventory-load").emit("click"); const raw = '{"schema_version":"paper-inventory/1.0","sites":[],"lots":[],"positions":[],"positions":[]}'; h.node("inventory-input").value = raw; await h.node("inventory-input").emit("input");
  h.reply({ detail: { code: "inventory_revision_conflict", current_revision: 2 } }, 409); await h.node("inventory-save").emit("click"); assert.equal(h.calls[3].options.body, '{"expected_revision":1,"state":' + raw + '}'); assert.equal(h.node("inventory-input").value, raw); assert.match(h.node("notice").textContent, /Reload current versions/);
});

test("new inventory response and geometry are discarded together on logout", async () => {
  const h = harness(); await h.connect(); h.reply(inventoryFixture()); const delayed = h.pending(true); const loading = h.node("inventory-load").emit("click"); await tick(); await h.node("disconnect").emit("click"); delayed.resolve(landFixture); await loading;
  assert.equal(h.node("inventory-output").textContent, ""); assert.equal(h.node("inventory-input").value, ""); assert.match(h.node("notice").textContent, /Session ended/); assert.equal(h.node("inventory-map").children.some((node) => node.attributes.role === "button"), false);
});

test("automatic index propagation preserves edited and fixed-time inventory drafts", async () => {
  const h = harness(); await h.connect(); h.reply(inventoryFixture()); h.reply(landFixture); await h.node("inventory-load").emit("click");
  h.reply(indexFixture()); h.reply({ enabled: true, running: false, scopes: [] }); h.reply(inventoryFixture());
  await h.intervals[0](); assert.equal(h.calls.at(-1).url, "/v1/inventory");
  h.node("inventory-input").value = '{"draft":"kept"}';
  h.reply(indexFixture()); h.reply({ enabled: true, running: false, scopes: [] }); await h.intervals[0]();
  assert.equal(h.calls.at(-1).url, "/v1/market/refresh/status"); assert.equal(h.node("inventory-input").value, '{"draft":"kept"}');
  h.node("inventory-input").value = JSON.stringify(inventoryFixture().state, null, 2); h.node("inventory-live").checked = false;
  h.reply(indexFixture()); h.reply({ enabled: true, running: false, scopes: [] }); await h.intervals[0]();
  assert.equal(h.calls.at(-1).url, "/v1/market/refresh/status"); assert.equal(h.calls.filter((call) => call.url === "/v1/market/refresh").length, 0);
});

test("policy controls preserve decimal strings and require explicit JSON write before saving", async () => {
  const h = harness(); await h.connect(); const entry = await loadSavedPolicy(h); assert.equal(h.node("policy-apply").disabled, false);
  assert.match(h.node("policy-feedback").textContent, new RegExp(entry.revision));
  assert.match(fs.readFileSync(path.join(assets, "workbench.css"), "utf8"), /\.field-help\s*\{[^}]*overflow-wrap:\s*anywhere/);
  h.node("policy-source-cap").value = "0.3333333333333333333333333"; await h.node("policy-source-cap").emit("input"); assert.equal(h.node("policy-apply").disabled, true); await h.node("policy-save").emit("click"); assert.equal(h.calls.length, 3); assert.match(h.node("notice").textContent, /Write controls to JSON/);
  await h.node("policy-update-json").emit("click"); const draft = JSON.parse(h.node("policy-input").value); assert.equal(draft.policy.parameters.benchmark.max_source_share, "0.3333333333333333333333333"); assert.equal(draft.policy.parameters.benchmark.source_rules["feed:prices"].quality, "0.123456789012345678901");
});

test("policy validation receives duplicate JSON bytes and registry conflicts explain the successor action", async () => {
  const h = harness(); await h.connect(); const raw = '{"policy":{"policy_id":"invented:policy","version":"0.2.0","version":"0.3.0"},"feature_definitions":[],"notes":"test"}'; h.node("policy-input").value = raw; await h.node("policy-input").emit("input"); h.reply({ detail: "duplicate_json_key" }, 422); await h.node("policy-save").emit("click"); assert.equal(h.calls[1].options.body, '{"document":' + raw + '}'); assert.equal(h.node("policy-input").value, raw);
  h.node("policy-input").value = JSON.stringify(policyFixture()); await h.node("policy-input").emit("input"); h.reply({ document: policyFixture(), calibration_state: "unvalidated" }); h.reply({ detail: "feature_changes_require_successor_registry_version" }, 409); await h.node("policy-save").emit("click"); assert.match(h.node("notice").textContent, /Increase the feature registry version/);
});

test("explicit policy apply validates original draft then changes only policy and declared registry provenance", async () => {
  const h = harness(); await h.connect(); const entry = await loadSavedPolicy(h); const draft = { market: { request_id: "invented:request", policy: { old: true } }, commercial: null, extensions: { existing: "kept" } }; const raw = JSON.stringify(draft); h.node("pricing-input").value = raw; h.reply({ request: draft, boundary_validation: "json_only", execution_enabled: false }); await h.node("policy-apply").emit("click"); assert.equal(h.calls[3].url, "/v1/requests/parse"); assert.equal(h.calls[3].options.body, raw);
  const applied = JSON.parse(h.node("pricing-input").value); assert.equal(applied.market.policy.version, entry.document.policy.version); assert.equal(applied.extensions.existing, "kept"); assert.equal(applied.extensions.policy_registry_document.revision, entry.revision); assert.equal(applied.commercial, null); assert.equal(applied.pricing_provenance.mode, "declared_scenario"); assert.equal(applied.pricing_provenance.policy_revision, null); assert.equal(h.calls.length, 4); assert.match(h.node("notice").textContent, /Evaluate explicitly/);
});

test("policy transformations reject duplicate keys and unsafe numeric literals without changing pricing bytes", async () => {
  const h = harness(); await h.connect(); await loadSavedPolicy(h); for (const raw of ['{"market":{},"amount":1,"amount":2}', '{"market":{},"amount":123456789012345678901}']) { h.node("pricing-input").value = raw; await h.node("policy-apply").emit("click"); assert.equal(h.node("pricing-input").value, raw); assert.equal(h.calls.length, 3); }
});

test("policy apply cannot overwrite a draft edited during the strict boundary check", async () => {
  const h = harness(); await h.connect(); await loadSavedPolicy(h); h.node("pricing-input").value = '{"market":{}}'; const delayed = h.pending(true); const applying = h.node("policy-apply").emit("click"); await tick(); h.node("pricing-input").value = '{"market":{"edited":true}}'; delayed.resolve({ request: { market: {} } }); await applying; assert.equal(h.node("pricing-input").value, '{"market":{"edited":true}}'); assert.match(h.node("notice").textContent, /draft changed/);
});

const underwritingTemplate = () => {
  const requirements = [{ requirement_id: "custom:memory", title: "Invented memory proof", group: "hardware", required: true, subject_kind: "lot", owning_path: "constraint", owner_model: "review:invented" }];
  return { requirements_version: "1.0.0", scope_options: ["inference", "resale"], requirements, request: { schema_version: "underwriting-assessment/1.0", request_id: null, as_of: null, requirements_version: "1.0.0", scopes: [], subjects: {}, requirements, evidence: [] } };
};
const underwritingReport = () => ({ status: "held", assessment_hash: "c".repeat(64), summary: { required_total: 1, required_covered: 0, required_blocked: 1, required_not_applicable: 0 }, rows: [{ requirement_id: "custom:memory", title: "Invented memory proof", group: "hardware", required: true, applicable: true, status: "missing", subject_kind: "lot", subject_id: null, unit: "GiB", value: null, blockers: ["missing_subject_identity", "missing_requirement_evidence"], evidence_ids: [] }], warnings: ["caller_verified_evidence_pointers_not_independent_authenticity_verification"], execution_enabled: false, monetary_effects_enabled: false });

test("underwriting template adds no evidence and path controls preserve custom scopes and exact inputs", async () => {
  const h = harness(); await h.connect(); h.reply(underwritingTemplate()); await h.node("underwriting-template").emit("click");
  let draft = JSON.parse(h.node("underwriting-input").value); assert.deepEqual(draft.evidence, []); assert.deepEqual(draft.subjects, {}); assert.deepEqual(draft.scopes, []); assert.match(draft.request_id, /^request:/); assert.match(draft.as_of, /Z$/);
  draft.scopes = ["custom-path"]; draft.extras = { exact: "1.00000000000000000000001" }; h.node("underwriting-input").value = JSON.stringify(draft); await h.node("underwriting-input").emit("input");
  const control = h.node("underwriting-scopes").children[0].children[0]; control.checked = true; await control.emit("change");
  draft = JSON.parse(h.node("underwriting-input").value); assert.deepEqual(draft.scopes, ["custom-path", "inference"]); assert.equal(draft.extras.exact, "1.00000000000000000000001");
  const original = h.node("underwriting-input").value; h.reply(underwritingTemplate()); await h.node("underwriting-template").emit("click"); assert.equal(h.node("underwriting-input").value, original);
  h.node("underwriting-input").value = '{"scopes":["resale"],"scopes":[]}'; const raw = h.node("underwriting-input").value;
  const newControl = h.node("underwriting-scopes").children[0].children[0]; newControl.checked = true; await newControl.emit("change");
  assert.equal(h.node("underwriting-input").value, raw); assert.match(h.node("notice").textContent, /Duplicate JSON key/);
});

test("underwriting sends original bytes, exposes gaps and invalidates changed drafts", async () => {
  const h = harness(); await h.connect(); const raw = '{"scopes":["resale"],"custom_exact":"1.00000000000000000001"}'; h.node("underwriting-input").value = raw; await h.node("underwriting-input").emit("input");
  const pending = h.pending(); const action = h.node("underwriting-assess").emit("click"); await tick(); assert.equal(h.calls.at(-1).url, "/v1/underwriting/assess"); assert.equal(h.calls.at(-1).options.body, raw);
  h.node("underwriting-input").value = '{"new_draft":true}'; await h.node("underwriting-input").emit("input"); pending.resolve(underwritingReport()); await action;
  assert.match(h.node("underwriting-groups").textContent, /Declare the subject identity/); assert.match(h.node("underwriting-summary").textContent, /Required evidence gaps/); assert.equal(h.node("underwriting-result-state").textContent, "Previous input");
  h.node("underwriting-query").value = "absent"; await h.node("underwriting-query").emit("input"); assert.match(h.node("underwriting-groups").textContent, /No requirements match/);
});

test("underwriting response after logout cannot restore cleared evidence or drafts", async () => {
  const h = harness(); await h.connect(); h.node("underwriting-input").value = '{"scopes":["resale"],"declared":true}'; await h.node("underwriting-input").emit("input");
  const pending = h.pending(true); const action = h.node("underwriting-assess").emit("click"); await tick(); await h.node("disconnect").emit("click"); pending.resolve(underwritingReport()); await action;
  assert.equal(h.node("underwriting-input").value, ""); assert.equal(h.node("underwriting-output").textContent, ""); assert.equal(h.node("underwriting-result-state").textContent, "Not assessed"); assert.equal(h.node("underwriting-assess").disabled, true);
  assert.doesNotMatch(h.node("underwriting-groups").textContent, /Invented memory/);
});

test("underwriting requires a path and preserves supplied units without converting values", async () => {
  const h = harness(); await h.connect(); h.node("underwriting-input").value = '{"scopes":[]}'; await h.node("underwriting-input").emit("input"); const count = h.calls.length; await h.node("underwriting-assess").emit("click"); assert.equal(h.calls.length, count); assert.match(h.node("notice").textContent, /Select at least one path/);
  h.node("underwriting-input").value = '{"scopes":["resale"]}'; await h.node("underwriting-input").emit("input");
  const report = underwritingReport(); report.rows[0].value = "48.135791357913579"; report.rows[0].supplied_unit = "GB"; report.rows[0].blockers = ["registered_unit_mismatch"];
  h.reply(report); await h.node("underwriting-assess").emit("click");
  assert.match(h.node("underwriting-groups").textContent, /Declared value: 48\.135791357913579 GB/); assert.match(h.node("underwriting-groups").textContent, /Registered unit: GiB/); assert.match(h.node("underwriting-groups").textContent, /no conversion performed/);
});

test("model recipe search exposes unpriced metadata without adding GPU price observations", async () => {
  const h = harness(); await h.connect(indexFixture({ catalog_records: [{ kind: "model_recipe_metadata", model_id: "invented/Example", source_id: "feed:recipes", price_eligible: false, license_claim: "invented-license", recipes: [{ engine: "vllm", accelerator: "gpu" }] }] }));
  assert.equal(h.node("metric-observations").textContent, "1"); h.node("model-query").value = "vllm"; await h.node("model-query").emit("input"); assert.match(h.node("model-records").textContent, /invented\/Example/); assert.match(h.node("model-records").textContent, /invented-license/); assert.match(h.node("model-records").textContent, /Configuration claims only/);
  h.node("model-query").value = "unknown-engine"; await h.node("model-query").emit("input"); assert.match(h.node("model-records").textContent, /No catalog records match/); assert.equal(h.calls.length, 1);
});

const descendants = (root) => [root, ...root.children.flatMap(descendants)];
const field = (h, kind, location) => descendants(h.node(kind + "-fields")).find((entry) => entry.attributes["data-field-path"] === location);

test("browser load bootstraps HttpOnly session without a credential form and initializes local data", async () => {
  const h = harness(); await h.connect();
  assert.equal(h.node("session-card").hidden, true); assert.equal(h.node("session-state").textContent, "Connected");
  assert.equal(h.sessionCalls[0].url, "/v1/session/bootstrap"); assert.equal(h.sessionCalls[0].options.credentials, "same-origin");
  assert.equal(h.sessionCalls[0].options.body, "{}"); assert.equal(h.calls[0].options.headers.Authorization, undefined);
  assert.ok(h.allCalls.some((call) => call.url === "/v1/underwriting/template"));
  assert.ok(h.allCalls.some((call) => call.url === "/v1/market/refresh/status"));
  assert.equal(JSON.parse(h.node("pricing-input").value).commercial, null);
  assert.equal(JSON.parse(h.node("cash-input").value).opening_cash, null);
});

test("mutations send memory CSRF while exact request bytes and decimals are preserved", async () => {
  const h = harness(); await h.connect(); h.node("cash-input").value = '{"amount":"0.000000000000000000001"}'; await h.node("cash-input").emit("input");
  h.reply({ result: { currency: "USD", minimum_free_cash: "0" } }); await h.node("evaluate-cash").emit("click");
  const call = h.calls.at(-1); assert.equal(call.options.headers["X-Compute-CSRF"], "invented-csrf-marker"); assert.equal(call.options.credentials, "same-origin");
  assert.equal(call.options.body, '{"amount":"0.000000000000000000001"}');
});

test("structured monetary edits distinguish unknown from explicit zero and retain extensions", async () => {
  const h = harness(); await h.connect(); h.node("cash-input").value = '{"opening_cash":null,"extensions":{"unknown":"12345678901234567890.000000000001"}}'; await h.node("cash-read-fields").emit("click");
  const cash = field(h, "cash", "opening_cash"); assert.equal(cash.value, "");
  cash.value = "0"; await cash.emit("input"); let result = JSON.parse(h.node("cash-input").value); assert.equal(result.opening_cash, "0"); assert.equal(result.extensions.unknown, "12345678901234567890.000000000001");
  cash.value = ""; await cash.emit("input"); result = JSON.parse(h.node("cash-input").value); assert.equal(result.opening_cash, null);
});

test("structured fields cannot overwrite a changed advanced draft or round unsafe literals", async () => {
  const h = harness(); await h.connect(); const before = h.node("cash-input").value; const cash = field(h, "cash", "opening_cash");
  h.node("cash-input").value = '{"amount":"user changed"}'; cash.value = "12"; await cash.emit("input");
  assert.equal(h.node("cash-input").value, '{"amount":"user changed"}'); assert.match(h.node("notice").textContent, /advanced draft changed/);
  h.node("cash-input").value = '{"opening_cash":9007199254740993}'; await h.node("cash-read-fields").emit("click"); assert.match(h.node("notice").textContent, /exact decimal strings/);
  assert.notEqual(before, h.node("cash-input").value);
});

test("blank inference inputs retain unknown booleans and explicitly supplied parallel counts", async () => {
  const h = harness(); await h.connect(); const parallel = field(h, "inference", "workload.tensor_parallel"); parallel.value = "2"; await parallel.emit("input");
  const memory = field(h, "inference", "qualification.memory.includes_kv_cache"); assert.equal(memory.value, ""); memory.value = "false"; await memory.emit("change");
  const request = JSON.parse(h.node("inference-input").value); assert.equal(request.workload.tensor_parallel, 2); assert.equal(request.qualification.memory.includes_kv_cache, false); assert.equal(request.costs.gpu_rate_per_gpu_hour, null);
});

test("inventory structured unit lists preserve physical identities and add no invented location", async () => {
  const h = harness(); await h.connect(); const add = descendants(h.node("inventory-fields")).find((entry) => entry.tagName === "button" && entry.textContent === "Add sites");
  await add.emit("click"); const latitude = field(h, "inventory", "sites.0.latitude"); assert.equal(latitude.value, "");
  const site = field(h, "inventory", "sites.0.site_id"); site.value = "declared:site"; await site.emit("input");
  const draft = JSON.parse(h.node("inventory-input").value); assert.equal(draft.sites[0].site_id, "declared:site"); assert.equal(draft.sites[0].latitude, null); assert.equal(draft.lots.length, 0);
});

test("logout clears structured field nodes and dashboard decisions along with raw input", async () => {
  const h = harness(); await h.connect(); const cash = field(h, "cash", "opening_cash"); cash.value = "19"; await cash.emit("input");
  await h.node("disconnect").emit("click"); assert.equal(h.node("cash-fields").children.length, 0); assert.equal(h.node("overview-decision").textContent, "Unevaluated");
  assert.equal(h.sessionCalls.at(-1).url, "/v1/session/logout"); assert.equal(h.sessionCalls.at(-1).options.headers["X-Compute-CSRF"], "invented-csrf-marker");
});

test("portfolio template remains blank and shared assessment uses its dedicated evaluator", async () => {
  const h = harness(); await h.connect(); const request = { schema_version: "portfolio-assessment/1.0", request_id: null, cash: { opening_cash: null }, capacity: { lots: [] }, routes: [], exposures: [], limits: [], minimum_free_cash: null };
  h.reply({ request }); await h.node("portfolio-new-draft").emit("click"); assert.deepEqual(JSON.parse(h.node("portfolio-input").value), request);
  h.reply({ result: { status: "held", execution_enabled: false, firm_price_eligible: false, blockers: ["missing inputs"], economics: null } }); await h.node("evaluate-portfolio").emit("click");
  assert.equal(h.calls.at(-1).url, "/v1/portfolio/evaluate"); assert.match(h.node("portfolio-summary").textContent, /missing inputs/);
});

test("ending a session during startup secondary reads cannot recreate cleared drafts", async () => {
  const h = harness(); h.reply({ auth_mode: "local_session", csrf_token: "invented-csrf-marker" }); h.reply(indexFixture());
  h.pending(); h.pending(); h.pending(); const opening = h.window.emit("load"); await tick();
  await h.node("disconnect").emit("click"); await opening;
  assert.equal(h.node("pricing-input").value, ""); assert.match(h.node("notice").textContent, /Session ended/);
});

test("a failed first structured mount leaves no private fields before or after ending a session", async () => {
  const h = harness(); await h.connect(); let nested = { value: "invented-sensitive-nested" };
  for (let i = 0; i < 12; i++) nested = { next: nested };
  h.node("portfolio-input").value = JSON.stringify({ buyer_entity_id: "invented-sensitive-entity", extensions: nested });
  await h.node("portfolio-read-fields").emit("click"); assert.match(h.node("notice").textContent, /budget/);
  assert.equal(h.node("portfolio-fields").children.length, 0); await h.node("disconnect").emit("click"); assert.equal(h.node("portfolio-fields").children.length, 0);
});

test("registered underwriting boolean values use explicit booleans and retain independent units", async () => {
  const h = harness(); await h.connect(); const requirements = [{ requirement_id: "requirement:privacy", subject_kind: "workload", value_type: "boolean", allowed_values: [] }];
  h.node("underwriting-input").value = ""; h.reply({ requirements_version: "invented", requirements, scope_options: ["inference"], request: { scopes: [], subjects: {}, evidence: [], requirements } });
  await h.node("underwriting-template").emit("click"); const add = descendants(h.node("underwriting-fields")).find((entry) => entry.tagName === "button" && entry.textContent === "Add evidence"); await add.emit("click");
  const identity = field(h, "underwriting", "evidence.0.requirement_id"); identity.value = "requirement:privacy"; await identity.emit("change");
  const value = field(h, "underwriting", "evidence.0.value"); value.value = "false"; await value.emit("change");
  const draft = JSON.parse(h.node("underwriting-input").value); assert.equal(draft.evidence[0].value, false); assert.equal(draft.evidence[0].unit, null); assert.equal(draft.evidence[0].status, null);
});

test("unknown Boolean choices and prototype-named extension keys remain explicit inputs", async () => {
  const h = harness(); await h.connect(); h.node("cash-input").value = '{"facility":{"revolving":"unknown assertion"},"extensions":{"toString":null}}'; await h.node("cash-read-fields").emit("click");
  const revolving = field(h, "cash", "facility.revolving"); revolving.value = "unknown assertion"; await revolving.emit("change");
  assert.equal(JSON.parse(h.node("cash-input").value).facility.revolving, "unknown assertion");
  const extension = field(h, "cash", "extensions.toString"); extension.value = "kept"; await extension.emit("input"); assert.equal(JSON.parse(h.node("cash-input").value).extensions.toString, "kept");
});

test("evicted protection tokens renew without replaying a mutation or discarding the draft", async () => {
  const h = harness(); await h.connect(); const draft = '{"opening_cash":"0.000000000000000000004"}';
  h.node("cash-input").value = draft; await h.node("cash-input").emit("input");
  h.reply({ detail: "browser_csrf_required" }, 403); h.reply({ auth_mode: "local_session", csrf_token: "replacement-csrf" });
  await h.node("evaluate-cash").emit("click");
  assert.match(h.node("notice").textContent, /Workspace resumed/); assert.match(h.node("notice").textContent, /no mutation was retried/);
  assert.equal(h.node("cash-input").value, draft); assert.equal(h.calls.filter(call => call.url === "/v1/cash/evaluate").length, 1);
  h.reply({ result: { currency: "USD", minimum_free_cash: "0" } }); await h.node("evaluate-cash").emit("click");
  assert.equal(h.calls.at(-1).options.headers["X-Compute-CSRF"], "replacement-csrf"); assert.equal(h.calls.at(-1).options.body, draft);
});

test("a non-CSRF forbidden response cannot trigger session renewal", async () => {
  const h = harness(); await h.connect(); h.node("cash-input").value = '{}'; await h.node("cash-input").emit("input");
  h.reply({ detail: "browser_origin_not_allowed" }, 403); await h.node("evaluate-cash").emit("click");
  assert.equal(h.sessionCalls.filter(call => call.url.includes("bootstrap")).length, 1); assert.match(h.node("notice").textContent, /browser_origin_not_allowed/);
});

test("supplier ceiling controls keep coverage unknown until explicitly declared", async () => {
  const h = harness(); await h.connect(); const add = descendants(h.node("inference-fields")).find(entry => entry.tagName === "button" && entry.textContent === "Add supplier economic ceiling");
  await add.emit("click"); const coverage = field(h, "inference", "supplier_ceiling_policy.nonpurchase_costs_complete");
  assert.equal(coverage.value, ""); coverage.value = "false"; await coverage.emit("change");
  const draft = JSON.parse(h.node("inference-input").value); assert.equal(draft.supplier_ceiling_policy.nonpurchase_costs_complete, false); assert.equal(draft.supplier_ceiling_policy.buy_tick_per_gpu_hour, null);
});

test("logout renews an evicted token solely to revoke without restoring page state", async () => {
  const h = harness(); await h.connect(); h.node("cash-input").value = JSON.stringify({opening_cash: "17.0000000000000003"});
  h.replyLogout({detail: "browser_csrf_required"}, 403); h.reply({auth_mode: "local_session", csrf_token: "e".repeat(64)});
  await h.node("disconnect").emit("click"); for (let i=0; i<8; i++) await tick();
  assert.equal(h.sessionCalls.filter(call => call.url.endsWith("logout")).length, 2);
  assert.equal(h.sessionCalls.at(-1).options.headers["X-Compute-CSRF"], "e".repeat(64));
  assert.equal(h.node("cash-input").value, ""); assert.equal(h.node("session-card").hidden, false);
});

test("missing source eligibility cannot label a qualified reference or purchase bid", async () => {
  const h=harness(); await h.connect(); h.node("pricing-input").value="{}"; await h.node("pricing-input").emit("input");
  h.reply({result:{status:"indicative", benchmark:{price:"9.123456789", currency:"EUR"}, bid:{submitted_limit:"8.333333333"}, economics:{currency:"EUR"}}});
  await h.node("evaluate-pricing").emit("click");
  assert.match(h.node("pricing-summary").textContent,/Scenario reference/); assert.doesNotMatch(h.node("pricing-summary").textContent,/8\.333333333/);
  assert.doesNotMatch(h.node("overview-decision-detail").textContent,/8\.333333333/);
});

const unchanged = (tag, asOf = "2026-01-01T00:05:00Z") => ({ etag: tag, headers: { ETag: tag, "X-Index-As-Of": asOf } });
const indexCalls = (h) => h.calls.filter((call) => call.url === "/v1/market/current");

test("a conditional index reload keeps the held index and its view when the server confirms it unchanged", async () => {
  const h = harness(); await h.connect(indexFixture(), { ETag: 'W/"one"' });
  assert.equal(indexCalls(h)[0].options.headers["If-None-Match"], undefined);
  const firstRow = h.node("records-body").children[0]; assert.ok(firstRow);
  h.reply(null, 304, unchanged('W/"one"').headers); await h.node("reload-index").emit("click");
  assert.equal(indexCalls(h)[1].options.headers["If-None-Match"], 'W/"one"');
  assert.equal(h.node("records-body").children[0], firstRow, "the records table was not rebuilt");
  assert.equal(h.node("metric-asof").textContent, "2026-01-01T00:05:00Z");
  assert.match(h.node("dashboard-clock").textContent, /2026-01-01 00:05 UTC/);
  assert.match(h.node("notice").textContent, /Retained index reloaded/); assert.equal(h.node("notice").className, "notice");
});

test("a changed index replaces the held view and the validator", async () => {
  const h = harness(); await h.connect(indexFixture(), { ETag: 'W/"one"' });
  const firstRow = h.node("records-body").children[0];
  h.reply(indexFixture({ observations: [observation("GPU-B", "3.5")] }), 200, { ETag: 'W/"two"' }); await h.node("reload-index").emit("click");
  assert.notEqual(h.node("records-body").children[0], firstRow); assert.match(h.node("records-body").textContent, /GPU-B/);
  h.reply(null, 304, unchanged('W/"two"').headers); await h.node("reload-index").emit("click");
  assert.equal(indexCalls(h)[2].options.headers["If-None-Match"], 'W/"two"');
});

test("a confirmation that omits the server clock is not trusted and the index is read in full", async () => {
  const h = harness(); await h.connect(indexFixture(), { ETag: 'W/"one"' });
  h.reply(null, 304, { ETag: 'W/"one"' }); h.reply(indexFixture({ observations: [observation("GPU-C", "4")] }), 200, { ETag: 'W/"four"' });
  await h.node("reload-index").emit("click");
  const reads = indexCalls(h); assert.equal(reads.length, 3);
  assert.equal(reads[1].options.headers["If-None-Match"], 'W/"one"'); assert.equal(reads[2].options.headers["If-None-Match"], undefined);
  assert.match(h.node("records-body").textContent, /GPU-C/);
});

test("ending a session discards the validator together with the index it described", async () => {
  const h = harness(); await h.connect(indexFixture(), { ETag: 'W/"one"' });
  await h.window.emit("pagehide"); assert.doesNotMatch(h.node("records-body").textContent, /GPU-A/);
  await h.connect(indexFixture(), { ETag: 'W/"three"' });
  assert.equal(indexCalls(h).at(-1).options.headers["If-None-Match"], undefined);
  h.reply(null, 304, unchanged('W/"three"').headers); await h.node("reload-index").emit("click");
  assert.equal(indexCalls(h).at(-1).options.headers["If-None-Match"], 'W/"three"');
});

test("a server error during a conditional read keeps the held index and reports the failure", async () => {
  const h = harness(); await h.connect(indexFixture(), { ETag: 'W/"one"' });
  const firstRow = h.node("records-body").children[0];
  h.reply({ detail: "snapshot_store_unavailable" }, 503); await h.node("reload-index").emit("click");
  assert.match(h.node("notice").textContent, /503 · snapshot_store_unavailable/); assert.equal(h.node("notice").className, "notice error");
  assert.equal(h.node("records-body").children[0], firstRow);
  h.reply(null, 304, unchanged('W/"one"').headers); await h.node("reload-index").emit("click");
  assert.equal(indexCalls(h).at(-1).options.headers["If-None-Match"], 'W/"one"');
});

test("a hidden tab neither polls nor takes the busy lock, and returning refreshes only when the data is old", async () => {
  const h = harness(); await h.connect(indexFixture(), { ETag: 'W/"one"' }); const baseline = h.calls.length;
  await h.visibility(true); await h.intervals[0](); assert.equal(h.calls.length, baseline, "no request while hidden");
  await h.visibility(false); assert.equal(h.calls.length, baseline, "returning inside the interval does not refetch");
  const sync = () => { h.reply(null, 304, unchanged('W/"one"').headers); h.reply({ enabled: true, running: false, scopes: [] }); h.reply(inventoryFixture()); };
  h.clock.advance(61000); sync(); h.reply(landFixture); await h.visibility(false);
  assert.deepEqual(h.calls.slice(baseline).map((call) => call.url), ["/v1/market/current", "/v1/market/refresh/status", "/v1/inventory", "/workbench/assets/world-land.json"]);
  assert.equal(h.calls[baseline].options.headers["If-None-Match"], 'W/"one"');
  await h.visibility(false); assert.equal(h.calls.length, baseline + 4, "a fresh confirmation resets the clock");
  sync(); await h.intervals[0]();
  assert.equal(h.calls.length, baseline + 7, "the visible tab still polls on schedule");
});
