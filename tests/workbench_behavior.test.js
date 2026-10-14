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
  addEventListener(name, action) { this.listeners.set(name, [...(this.listeners.get(name) || []), action]); }
  async emit(name) { if (this.disabled && name === "click") return; await Promise.all((this.listeners.get(name) || []).map((action) => action({ preventDefault() {}, target: this }))); }
  focus() { this.focused = true; }
  scrollIntoView() { this.scrolled = true; }
}

function harness() {
  const nodes = new Map();
  for (const tag of html.matchAll(/<([a-z][a-z0-9]*)\b([^>]*)>/g)) {
    const attributes = Object.fromEntries([...tag[2].matchAll(/([a-z-]+)="([^"]*)"/g)].map((match) => [match[1], match[2]]));
    if (!attributes.id) continue;
    const node = new Node(tag[1], { ...attributes, ...( /\bhidden\b/.test(tag[2]) ? { hidden: "" } : {}), ...(/\bdisabled\b/.test(tag[2]) ? { disabled: "" } : {}) }); node.root = true;
    nodes.set(attributes.id, node);
  }
  for (const match of html.matchAll(/<select\b[^>]*id="([^"]+)"[^>]*>([\s\S]*?)<\/select>/g)) {
    const select = nodes.get(match[1]);
    for (const option of match[2].matchAll(/<option\b[^>]*value="([^"]*)"[^>]*>([^<]*)<\/option>/g)) { const node = new Node("option"); node.value = option[1]; node.textContent = option[2]; select.append(node); }
  }
  const nav = [...html.matchAll(/data-view="([^"]+)"/g)].map((match) => { const node = new Node("button"); node.dataset.view = match[1]; node.root = true; return node; });
  const window = new Node("window"); const calls = []; const responses = []; const timers = new Map(); const intervals = []; let timerId = 0;
  const fetch = (url, options) => { calls.push({ url, options }); const response = responses.shift(); assert.ok(response, "Unexpected request: " + url); return response(options); };
  const context = vm.createContext({ document: { getElementById: (id) => { assert.ok(nodes.has(id), "Missing DOM element " + id); return nodes.get(id); }, createElement: (tag) => new Node(tag), querySelectorAll: () => nav }, window, fetch, AbortController, crypto: { randomUUID }, setTimeout: (fn, delay) => { timers.set(++timerId, { fn, delay }); return timerId; }, clearTimeout: (id) => timers.delete(id), setInterval: (fn) => intervals.push(fn), console });
  vm.runInContext(script, context, { filename: "workbench.js" });
  function reply(body, status = 200) { responses.push(async () => ({ ok: status >= 200 && status < 300, status, json: async () => structuredClone(body), text: async () => typeof body === "string" ? body : JSON.stringify(body) })); }
  function pending(ignoreAbort = false) {
    let resolve; let reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    responses.push((options) => { if (!ignoreAbort) options.signal.addEventListener("abort", () => { const error = new Error("aborted"); error.name = "AbortError"; reject(error); }, { once: true }); return promise; });
    return { resolve: (body, status = 200) => resolve({ ok: status >= 200 && status < 300, status, json: async () => body, text: async () => body }), reject };
  }
  async function connect(index = indexFixture()) { reply(index); nodes.get("api-key").value = "test-key-" + "k".repeat(40); await nodes.get("session-form").emit("submit"); }
  return { node: (id) => nodes.get(id), calls, reply, pending, timers, intervals, window, connect, nav };
}

const observation = (id, amount, overrides = {}) => ({ id, source_id: "feed:prices", kind: "listing_ask", hardware: { model: id, accelerator_count: "1" }, price: { amount, currency: "USD", unit: "gpu_hour" }, observed_at: "2026-01-01T00:00:00Z", expires_at: "2099-01-01T00:00:00Z", status: "claimed", region: { country_code: "US" }, ...overrides });
function indexFixture(overrides = {}) {
  const scopes = [{ captured_at: "2026-01-01T00:00:00Z", observation_count: 1, catalog_record_count: 0, filters: {}, stale: false, coverage: { complete: false } }];
  return { as_of: "2026-01-01T00:00:00Z", sources: [{ source_id: "feed:prices", enabled: true, can_attempt_read: true, rights_status: "allowed", permissions: { benchmark: "PASS" }, max_age_s: 7200, scopes, latest: scopes[0] }], observations: [observation("GPU-A", "2.0000000000000000000000001")], catalog_records: [], snapshots: [{ snapshot_id: "a".repeat(64), source_id: "feed:prices" }], ...overrides };
}
const tick = () => new Promise((resolve) => setImmediate(resolve));
const renderedPrices = (h) => h.node("records-body").children.map((row) => row.children[2]?.textContent);

test("startup is locked and performs no fetch or sample insertion", () => {
  const h = harness(); assert.equal(h.calls.length, 0); assert.equal(h.node("pricing-input").value, ""); assert.equal(h.node("reload-index").disabled, true); assert.equal(h.node("refresh-market").disabled, true);
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
  h.reply({ snapshot_id: "synthetic-result", result: { status: "indicative", economics: { currency: "EUR" }, bid: { submitted_limit: "0.93000000000000000001" } } });
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

test("late failed connection cannot clear a newer connected session", async () => {
  const h = harness(); const old = h.pending(true); h.node("api-key").value = "old-key-" + "a".repeat(40); const first = h.node("session-form").emit("submit"); await tick();
  await h.node("disconnect").emit("click"); await h.connect(indexFixture({ observations: [observation("NEW", "3")] }));
  old.resolve(indexFixture()); await first;
  assert.equal(h.node("session-state").textContent, "Local session connected"); assert.match(h.node("records-body").textContent, /NEW/); assert.equal(h.node("reload-index").disabled, false);
});

test("stop waiting and timeout retain drafts, abort transport, and do not duplicate feed reads", async () => {
  const h = harness(); await h.connect(); h.node("pricing-input").value = '{"draft":"kept"}';
  h.pending(); const reading = h.node("refresh-market").emit("click"); await tick(); await h.node("cancel-request").emit("click"); await reading;
  assert.match(h.node("notice").textContent, /Server work may continue/); assert.equal(h.node("pricing-input").value, '{"draft":"kept"}'); assert.equal(h.calls.length, 2);
  h.pending(); const reloading = h.node("reload-index").emit("click"); await tick(); const timer = [...h.timers.values()][0]; assert.equal(timer.delay, 30000); timer.fn(); await reloading;
  assert.match(h.node("notice").textContent, /timed out/); assert.equal(h.node("reload-index").disabled, false);
});

test("401 clears session and sensitive drafts while preserving the rejection action", async () => {
  const h = harness(); await h.connect(); h.node("inference-input").value = '{"sensitive":"draft"}'; h.reply({ detail: "unauthorized" }, 401); await h.node("reload-index").emit("click");
  assert.equal(h.node("inference-input").value, ""); assert.equal(h.node("disconnect").hidden, true); assert.match(h.node("notice").textContent, /Enter the current local key/);
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
  assert.match(h.node("pricing-mode").textContent, /unvalidated exploration/); assert.match(h.node("pricing-summary").textContent, /4\.01 EUR/); assert.equal(h.node("pricing-view").hidden, false);
});
