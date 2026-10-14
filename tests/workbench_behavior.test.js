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

function harness({ prefersDark = false } = {}) {
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
  const window = new Node("window"); window.matchMedia = () => ({ matches: prefersDark }); const documentElement = new Node("html"); const calls = []; const responses = []; const timers = new Map(); const intervals = []; let timerId = 0;
  let initializing = false; let logoutWait = null;
  const allCalls = []; const sessionCalls = []; const logoutResponses = [];
  const resolved = (body) => Promise.resolve({ ok: true, status: 200, json: async () => structuredClone(body) });
  const fetch = (url, options) => {
    allCalls.push({ url, options });
    if (url.startsWith("/v1/session/")) sessionCalls.push({ url, options });
    else if (!initializing || url === "/v1/demo/market") calls.push({ url, options });
    if (url === "/v1/session/logout") return logoutResponses.shift() || logoutWait || resolved({ auth_mode: "disconnected" });
    if (initializing && url === "/v1/session/bootstrap") return resolved({ auth_mode: "local_session", csrf_token: "c".repeat(64), expires_at: "2099-05-06T00:00:00Z" });
    if (initializing && url === "/v1/demo/contract") return resolved(demoContractFixture());
    if (initializing && url === "/v1/market/refresh/status") return resolved({ enabled: true, running: false, scopes: [] });
    if (initializing && url.startsWith("/v1/inventory")) return resolved({ revision: null, as_of: "2033-05-06T00:00:00Z", state: { schema_version: "paper-inventory/1.0", sites: [], lots: [], positions: [] }, summary: { by_unit_kind: {} }, sites: [], lots: [], timeline: [] });
    if (initializing && url === "/v1/underwriting/template") return resolved({ requirements_version: "invented-public-7", requirements: [], scope_options: [], request: { scopes: [], subjects: {}, requirements: [], evidence: [] } });
    if (initializing && url === "/workbench/assets/world-land.json") return resolved(landFixture);
    const response = responses.shift(); assert.ok(response, "Unexpected request: " + url); return response(options);
  };
  const context = vm.createContext({ document: { documentElement, getElementById: (id) => { assert.ok(nodes.has(id), "Missing DOM element " + id); return nodes.get(id); }, createElement: (tag) => new Node(tag), createElementNS: (_, tag) => new Node(tag), querySelectorAll: () => nav }, window, fetch, AbortController, structuredClone, crypto: { randomUUID }, setTimeout: (fn, delay) => { timers.set(++timerId, { fn, delay }); return timerId; }, clearTimeout: (id) => timers.delete(id), setInterval: (fn) => intervals.push(fn), console });
  vm.runInContext(draftScript, context, { filename: "workbench-drafts.js" });
  vm.runInContext(script, context, { filename: "workbench.js" });
  function reply(body, status = 200) { responses.push(async () => ({ ok: status >= 200 && status < 300, status, json: async () => structuredClone(body), text: async () => typeof body === "string" ? body : JSON.stringify(body) })); }
  function pending(ignoreAbort = false) {
    let resolve; let reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    responses.push((options) => { if (!ignoreAbort) options.signal.addEventListener("abort", () => { const error = new Error("aborted"); error.name = "AbortError"; reject(error); }, { once: true }); return promise; });
    return { resolve: (body, status = 200) => resolve({ ok: status >= 200 && status < 300, status, json: async () => body, text: async () => body }), reject };
  }
  async function connect(index = indexFixture()) {
    initializing = true; reply(index);
    try { await window.emit("load"); } finally { initializing = false; }
  }
  function delayLogout() { let resolve; logoutWait = new Promise((yes) => { resolve = yes; }); return () => { resolve({ ok: true, status: 200 }); logoutWait = null; }; }
  return { replyLogout: (body, status) => logoutResponses.push(Promise.resolve({ok: status >= 200 && status < 300, status, json: async () => body})), node: (id) => nodes.get(id), calls, allCalls, sessionCalls, reply, pending, timers, intervals, window, documentElement, connect, nav, delayLogout };
}

const observation = (id, amount, overrides = {}) => ({ id, source_id: "feed:prices", kind: "listing_ask", hardware: { model: id, accelerator_count: "1" }, price: { amount, currency: "USD", unit: "gpu_hour" }, observed_at: "2026-01-01T00:00:00Z", expires_at: "2099-01-01T00:00:00Z", status: "claimed", region: { country_code: "US" }, ...overrides });
function demoContractFixture() {
  const inputs = { gpu_count: "2", delivery_start: "2061-03-09T00:00:00Z", delivery_end: "2061-03-10T00:00:00Z", supplier_rate: "2.125", buyer_rate: "4.35", billed_utilization: "0.81", collection_share: "0.96", opening_cash: "280", reference_rate: "2.9", fee_on_collected: "0.01", fee_on_gross: "0.003", fixed_operating_cost: "17", minimum_cash: "12", required_margin: "0.18", tick_size: "0.005", payment_dates: { supplier_payment_on: "2061-03-09", buyer_invoice_on: "2061-03-09", buyer_receipt_on: "2061-03-10", operating_cost_on: "2061-03-09", fees_on: "2061-03-10", writeoff_on: "2061-03-10" } };
  const fields = Object.keys(inputs).filter(name => name !== "payment_dates").map(name => ({name, label:name.replaceAll("_", " "), type:name.startsWith("delivery_") ? "utc" : "decimal", group:["reference_rate", "fee_on_collected", "fee_on_gross", "fixed_operating_cost", "minimum_cash", "required_margin", "tick_size"].includes(name) ? "assumptions" : "primary", required:true}));
  Object.keys(inputs.payment_dates).forEach(name => fields.push({name:"payment_dates." + name,label:name,type:"date",group:"payment_dates",required:true}));
  return { schema_version:"demo-scenario/1.0.0", fields, sample:{classification:"synthetic", inputs}, template_unknown:{} };
}
function demoField(h, name) {
  const id = "demo-field-" + name.replaceAll(".", "-");
  return [h.node("demo-primary-fields"), h.node("demo-additional-fields")].flatMap(container => container.children).flatMap(label => label.children).find(node => node.id === id);
}
function indexFixture(overrides = {}) {
  const scopes = [{ captured_at: "2026-01-01T00:00:00Z", observation_count: 1, catalog_record_count: 0, filters: {}, stale: false, coverage: { complete: false } }];
  return { as_of: "2026-01-01T00:00:00Z", sources: [{ source_id: "feed:prices", enabled: true, can_attempt_read: true, rights_status: "allowed", permissions: { benchmark: "PASS" }, max_age_s: 7200, scopes, latest: scopes[0] }], observations: [observation("GPU-A", "2.0000000000000000000000001")], catalog_records: [], snapshots: [{ snapshot_id: "a".repeat(64), source_id: "feed:prices" }], ...overrides };
}
const tick = () => new Promise((resolve) => setImmediate(resolve));
const renderedPrices = (h) => h.node("records-body").children.map((row) => row.children[2]?.textContent);

test("startup is locked and performs no fetch or sample insertion", () => {
  const h = harness(); assert.equal(h.calls.length, 0); assert.equal(h.node("pricing-input").value, ""); assert.equal(h.node("reload-index").disabled, true); assert.equal(h.node("refresh-market").disabled, true);
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

test("MVP starts with three primary workflows and retains advanced tools", () => {
  const h = harness(); const primary = html.match(/<nav class="navigation"[^>]*>([\s\S]*?)<\/nav>/)[1];
  assert.deepEqual([...primary.matchAll(/data-view="([^"]+)"/g)].map(match => match[1]), ["market", "pricing", "inventory"]);
  assert.equal(h.node("market-view").hidden, false); assert.equal(h.node("dashboard-view").hidden, true);
  assert.ok(h.nav.some(node => node.dataset.view === "policy"));
});

test("scenario form remains unknown until explicit sample action and submits exact flat strings", async () => {
  const h = harness(); await h.connect();
  assert.equal(demoField(h, "gpu_count").value, ""); assert.equal(demoField(h, "payment_dates.buyer_receipt_on").value, "");
  await h.node("demo-scenario-form").emit("submit"); assert.equal(h.calls.length, 1); assert.match(h.node("notice").textContent, /Unknown inputs remain empty/);
  await h.node("demo-load-sample").emit("click"); assert.match(h.node("demo-scenario-mode").textContent, /Invented scenario/);
  const exact = "2.125000000000000000001"; demoField(h, "supplier_rate").value = exact; await demoField(h, "supplier_rate").emit("input");
  h.reply({result:{status:"held",bid:null,pricing_provenance:{source_evidence_eligible:false},cash_constraint:{tested_purchase_tick:"1.905",supplied_ask_required_extra_cash:"7.031",supplied_ask_cash_feasible:false},ask:{sell_floor_tick:"3.275"},economics:{currency:"USD",economic_profit:"41.032",gross_billings:"169.128",expected_collections:"162.36288",economic_cost:"121.33088",fees:"2.13188",capital_charge:"0"},scenario_supplier_cash_schedule:{currency:"USD",days:[{on:"2061-03-09",free_cash:"5",minimum_ordered_free_cash:"-2.031"},{on:"2061-03-10",free_cash:"46.032",minimum_ordered_free_cash:"5"}]},hold_reasons:["source_evidence_not_bound"]}});
  await h.node("demo-scenario-form").emit("submit");
  const call = h.calls.at(-1); assert.equal(call.url, "/v1/demo/scenario"); const sent = JSON.parse(call.options.body);
  assert.equal(sent.supplier_rate, exact); assert.equal(sent.payment_dates.buyer_receipt_on, "2061-03-10"); assert.equal(sent.inputs, undefined);
  assert.match(h.node("demo-results").textContent, /1\.905 USD/); assert.match(h.node("demo-results").textContent, /7\.04 USD/); assert.equal(h.node("demo-results").children[3].children[1].attributes.title,"Exact: 7.031 USD");
  assert.equal(h.node("demo-cash-blocker").hidden, false); assert.match(h.node("demo-provenance").textContent, /actual submitted bid remains held/);
  assert.match(h.node("demo-cash-caption").textContent, /At your supplier price/); assert.equal(h.node("demo-cash-empty").hidden, true);
  assert.ok(h.node("demo-cash-chart").children.some(node => node.tagName === "polyline" && node.attributes.class === "chart-trough"));
  demoField(h, "opening_cash").value = "300"; await demoField(h, "opening_cash").emit("input"); assert.equal(h.node("demo-result-state").textContent, "Previous input");
  const draft = demoField(h, "opening_cash").value; h.reply(indexFixture()); h.reply({enabled:true,running:true,scopes:[]}); await h.intervals[0](); assert.equal(demoField(h, "opening_cash").value, draft);
  await h.node("disconnect").emit("click"); assert.equal(h.node("demo-primary-fields").children.length, 0); assert.equal(h.node("demo-cash-chart").children.length, 0); assert.equal(h.node("demo-output").textContent, "");
});

test("scenario totals use exact cent presentation, funding rounds upward and rates retain tick precision", async () => {
  const h = harness(); await h.connect(); await h.node("demo-load-sample").emit("click");
  const result = {status:"held",bid:null,ask:{sell_floor_tick:"4.005"},cash_constraint:{tested_purchase_tick:"3.875",supplied_ask_required_extra_cash:"0.000000000000000001"},economics:{currency:"USD",economic_profit:"12345678901234567890.1251",economic_cost:null,economic_margin:"0.1234567890123456789",margin_basis:"gross_billings"},scenario_supplier_cash_schedule:{currency:"USD",minimum_cash_floor:"12",days:[{on:"2061-03-09",free_cash:"21",minimum_ordered_free_cash:"11.999999999999999999"}]}};
  h.reply({result}); await h.node("demo-scenario-form").emit("submit"); const cards = h.node("demo-results").children;
  assert.equal(cards[0].children[1].textContent,"3.875 USD"); assert.equal(cards[1].children[1].textContent,"4.005 USD");
  assert.equal(cards[2].children[1].textContent,"12,345,678,901,234,567,890.13 USD"); assert.equal(cards[2].children[1].attributes.title,"Exact: 12345678901234567890.1251 USD");
  assert.equal(cards[3].children[1].textContent,"0.01 USD"); assert.match(h.node("demo-cost-breakdown").textContent,/Economic margin \/ gross billings12\.35%/);
  assert.equal(h.node("demo-cost-breakdown").children[2].children[1].textContent,"—");
  assert.ok(h.node("demo-cash-chart").children.some(node => node.attributes.class === "chart-floor" && node.children[0].textContent === "Minimum cash floor: 12 USD"));
  h.reply({result:{...result,economics:{...result.economics,economic_profit:"-0.0049",economic_margin:null},cash_constraint:{...result.cash_constraint,supplied_ask_required_extra_cash:"0"}}}); await h.node("demo-scenario-form").emit("submit");
  assert.equal(h.node("demo-results").children[2].children[1].textContent,"0.00 USD"); assert.equal(h.node("demo-results").children[3].children[1].textContent,"0.00 USD");
  assert.equal(h.node("demo-cost-breakdown").children.at(-1).children[1].textContent,"—");
});

test("commitment chart keeps native currency, gaps and billing weeks separate with no curve interpolation", async () => {
  const h = harness();
  const node = (months, rate) => ({reservation_months:months,rate_per_gpu_hour:rate,status:"observed_reference",references:[{captured_at:"2099-01-08T02:14:06.123Z"}]});
  const group = (billing, currency, week, nodes) => ({cohort:{source_id:"getdeploying",hardware:{model:"Example-GPU"},currency,billing_type:billing,week_start:week},nodes});
  await h.connect(indexFixture({commitment_curves:{groups:[group("CUSTOM","USD","2099-01-05",[node(null,"9.4")]),group("RESERVATION","EUR","2099-01-05",[node(null,"2.7"),node(1,"2.125000000000000000001"),node(12,"1.8")]),group("RESERVATION","USD","2098-12-29",[node(6,"4.7")])]},sources:[{source_id:"getdeploying",scopes:[{captured_at:"2099-01-08T02:14:06.123Z",stale:false}],can_attempt_read:true}]}));
  assert.equal(h.node("curve-group").value,"1"); assert.equal(h.node("curve-unit").textContent,"EUR / GPU-hour");
  assert.match(h.node("market-selected-reference").textContent,/1\.8 EUR/); assert.match(h.node("market-selected-reference").textContent,/12 month average/);
  assert.match(h.node("curve-nodes").textContent,/Unspecified term/); assert.doesNotMatch(h.node("curve-nodes").textContent,/No reserved term/);
  await h.node("curve-nodes").children[1].emit("click"); assert.match(h.node("market-selected-reference").textContent,/2\.125000000000000000001 EUR/);
  const plot = h.node("commitment-chart"); assert.equal(plot.children.filter(child => child.tagName === "circle").length, 3); assert.equal(plot.children.filter(child => child.tagName === "polyline").length, 0);
  assert.doesNotMatch(h.node("curve-nodes").textContent,/6 months/);
  h.node("curve-group").value="2"; await h.node("curve-group").emit("change"); assert.equal(h.node("curve-unit").textContent,"USD / GPU-hour"); assert.match(h.node("curve-caption").textContent,/2098-12-29/);
  await h.node("market-compare-deal").emit("click"); assert.equal(h.node("pricing-view").hidden,false); assert.equal(demoField(h,"reference_rate").value,"");
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

test("resume serializes an older bootstrap before opening a fresh workspace", async () => {
  const h = harness(); const earlier = h.pending(true); const first = h.node("connect-session").emit("click"); await tick();
  await h.node("disconnect").emit("click"); const resumed = h.connect(indexFixture({ observations: [observation("NEW", "3")] }));
  await tick(); assert.equal(h.sessionCalls.filter((call) => call.url.endsWith("bootstrap")).length, 1);
  earlier.resolve({ detail: "expired" }, 401); await first; await resumed;
  assert.equal(h.node("session-state").textContent, "Workspace ready"); assert.match(h.node("records-body").textContent, /NEW/); assert.equal(h.node("reload-index").disabled, false);
});

test("stop waiting and timeout retain drafts, abort transport, and do not duplicate feed reads", async () => {
  const h = harness(); await h.connect(); h.node("pricing-input").value = '{"draft":"kept"}';
  h.pending(); const reading = h.node("refresh-market").emit("click"); await tick(); await h.node("cancel-request").emit("click"); await reading;
  assert.match(h.node("notice").textContent, /Server work may continue/); assert.equal(h.node("pricing-input").value, '{"draft":"kept"}'); assert.equal(h.calls.length, 2);
  h.pending(); const reloading = h.node("reload-index").emit("click"); await tick(); const timer = [...h.timers.values()][0]; assert.equal(timer.delay, 30000); timer.fn(); await reloading;
  assert.match(h.node("notice").textContent, /timed out/); assert.equal(h.node("reload-index").disabled, false);
});

test("expired read renews its session, while expired mutation is never retried", async () => {
  const h = harness(); await h.connect(); h.node("inference-input").value = '{"invented_private_draft":"kept"}';
  h.reply({ detail: "expired" }, 401); h.reply({ auth_mode: "local_session", csrf_token: "d".repeat(64) }); h.reply(indexFixture());
  await h.node("reload-index").emit("click"); assert.match(h.node("inference-input").value, /kept/);
  h.node("cash-input").value = '{}'; await h.node("cash-input").emit("input"); h.reply({ detail: "expired" }, 401); h.reply({ auth_mode: "local_session", csrf_token: "restored-client-token" });
  await h.node("evaluate-cash").emit("click"); assert.match(h.node("notice").textContent, /no mutation was retried/);
  assert.equal(h.sessionCalls.filter((call) => call.url.endsWith("bootstrap")).length, 3);
  assert.equal(h.calls.filter((call) => call.url === "/v1/cash/evaluate").length, 1);
  assert.equal(h.calls.at(-1).options.headers["X-Compute-CSRF"], "d".repeat(64));
});

test("a stale tab protection token is repaired without resubmitting its request", async () => {
  const h = harness(); await h.connect(); const raw = '{"opening_cash":"0.000000000000000000009"}';
  h.node("cash-input").value = raw; await h.node("cash-input").emit("input");
  h.reply({ detail: "browser_csrf_required" }, 403); h.reply({ auth_mode: "local_session", csrf_token: "fresh-tab-token" });
  await h.node("evaluate-cash").emit("click");
  assert.match(h.node("notice").textContent, /no mutation was retried/); assert.match(h.node("notice").textContent, /Workspace resumed/);
  assert.equal(h.node("cash-input").value, raw); assert.equal(h.calls.filter(call => call.url === "/v1/cash/evaluate").length, 1);
  h.reply({ result: { currency: "USD", minimum_free_cash: "0" } }); await h.node("evaluate-cash").emit("click");
  assert.equal(h.calls.at(-1).options.headers["X-Compute-CSRF"], "fresh-tab-token"); assert.equal(h.calls.at(-1).options.body, raw);
});

test("an origin denial stays denied without a new handshake", async () => {
  const h = harness(); await h.connect(); h.node("cash-input").value = '{}'; await h.node("cash-input").emit("input");
  h.reply({ detail: "browser_origin_not_allowed" }, 403); await h.node("evaluate-cash").emit("click");
  assert.equal(h.sessionCalls.filter(call => call.url.endsWith("bootstrap")).length, 1); assert.match(h.node("notice").textContent, /browser_origin_not_allowed/);
});

test("the optional GPU ceiling has explicit three-state coverage controls", async () => {
  const h = harness(); await h.connect(); const action = walk(h.node("inference-fields")).find(entry => entry.tagName === "button" && entry.textContent === "Add supplier economic ceiling");
  await action.emit("click"); const independence = walk(h.node("inference-fields")).find(entry => entry.attributes["data-field-path"] === "supplier_ceiling_policy.nonpurchase_costs_rate_independent");
  assert.equal(independence.value, ""); independence.value = "true"; await independence.emit("change");
  const request = JSON.parse(h.node("inference-input").value); assert.equal(request.supplier_ceiling_policy.nonpurchase_costs_rate_independent, true); assert.equal(request.supplier_ceiling_policy.nonpurchase_costs_complete, null);
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
  const h = harness(); assert.match(h.node("inventory-totals").textContent, /No declared capacity/); await h.connect(); h.reply(inventoryFixture()); await h.node("inventory-load").emit("click");
  assert.match(h.node("inventory-totals").textContent, /gpu \/ declared units/); assert.match(h.node("inventory-totals").textContent, /node \/ declared units/); assert.match(h.node("inventory-map-state").textContent, /1 located sites \/ 1 unmapped/);
  const markers = h.node("inventory-map").children.filter((node) => node.attributes.role === "button"); assert.equal(markers.length, 1); assert.equal(markers[0].attributes.tabindex, "0");
  assert.equal(markers[0].children.filter((node) => node.attributes.role === "button").length, 0); assert.equal(markers[0].children.filter((node) => node.attributes.class === "map-hit-target").length, 1);
  const css = fs.readFileSync(path.join(assets, "workbench.css"), "utf8"); assert.match(css, /stroke-width: 44px; vector-effect: non-scaling-stroke; pointer-events: all/);
  await markers[0].emit("keydown", { key: "Enter" }); assert.match(h.node("inventory-count").textContent, /1 lots \/ 2 declared/); assert.match(h.node("lot-detail").textContent, /12\.3456789012345678901 EUR/); assert.match(h.node("lot-detail").textContent, /2026-01-05T00:00:00Z/);
  await h.node("inventory-clear-site").emit("click"); assert.match(h.node("inventory-count").textContent, /2 lots/); assert.equal(h.calls.length, 2);
});

test("fixed UTC inventory requests encode the timestamp and reject impossible dates without a fetch", async () => {
  const h = harness(); await h.connect(); h.node("inventory-live").checked = false; await h.node("inventory-live").emit("change"); h.node("inventory-at").value = "2026-02-30T00:00:00Z"; await h.node("inventory-load").emit("click"); assert.equal(h.calls.length, 1); assert.match(h.node("notice").textContent, /valid UTC instant/);
  h.node("inventory-at").value = "2026-01-10T00:00:00Z"; h.reply(inventoryFixture()); await h.node("inventory-load").emit("click"); assert.equal(h.calls[1].url, "/v1/inventory?as_of=2026-01-10T00%3A00%3A00Z");
});

test("unsold uses backend counts and includes reserved capacity while available remains distinct", async () => {
  const h = harness(); await h.connect(); const report = inventoryFixture();
  const reserved = { position_id: "invented:reserved", lot_id: report.lots[0].lot_id, unit_ids: ["g1", "g2"], status: "reserved", start_at: "2026-01-05T00:00:00Z", end_at: "2026-01-20T00:00:00Z" };
  const counts = { total: 2, available: 0, reserved: 2, sold: 0, maintenance: 0, unavailable: 0, unsold: 2 };
  report.state.positions = [reserved]; report.lots[0].counts = counts; report.lots[0].positions = [reserved]; report.summary.by_unit_kind.gpu = counts; report.sites[0].by_unit_kind.gpu = counts;
  report.timeline = report.timeline.filter((row) => row.kind === "availability").concat({ ...reserved, kind: "reserved", active_at_as_of: true });
  h.reply(report); await h.node("inventory-load").emit("click");
  const gpuTotals = h.node("inventory-totals").children[0].children[1].children;
  assert.equal(gpuTotals.find((pair) => pair.children[0].textContent === "unsold").children[1].textContent, "2");
  assert.equal(gpuTotals.find((pair) => pair.children[0].textContent === "available").children[1].textContent, "0");
  h.node("inventory-query").value = "Invented accelerator"; h.node("inventory-status").value = "unsold"; await h.node("inventory-status").emit("input"); assert.match(h.node("inventory-count").textContent, /1 lots \/ 2 declared/); assert.match(h.node("inventory-body").textContent, /2 gpu/);
  h.node("inventory-status").value = "available"; await h.node("inventory-status").emit("input"); assert.match(h.node("inventory-count").textContent, /0 lots \/ 2 declared/); assert.match(html, /Unsold includes available, reserved and maintenance units within active supply/);
});

test("inventory demo uses pure validation and cannot be persisted by its save button", async () => {
  const h = harness(); await h.connect(); const report = inventoryFixture(); report.revision = null; report.persisted = false; h.reply(report); await h.node("inventory-demo").emit("click");
  assert.equal(h.calls[1].url, "/v1/inventory/evaluate"); assert.equal(h.calls[1].options.method, "POST"); assert.match(h.calls[1].options.body, /independently_invented_synthetic_ui_demo/); assert.match(h.node("inventory-mode").textContent, /SYNTHETIC/); assert.equal(h.node("inventory-save").disabled, true);
  const packet = JSON.parse(h.calls[1].options.body); assert.deepEqual(Object.keys(packet.state).sort(), ["lots", "positions", "provenance", "schema_version", "sites"]); assert.equal(packet.state.provenance, "synthetic");
  await h.node("inventory-save").emit("click"); assert.equal(h.calls.length, 2); await h.node("inventory-demo").emit("click"); assert.equal(h.node("inventory-input").value, ""); assert.equal(h.node("inventory-mode").textContent, "No inventory loaded");
});

test("inventory revision conflict preserves duplicate-key draft bytes and displays reload action", async () => {
  const h = harness(); await h.connect(); h.reply(inventoryFixture()); await h.node("inventory-load").emit("click"); const raw = '{"schema_version":"paper-inventory/1.0","sites":[],"lots":[],"positions":[],"positions":[]}'; h.node("inventory-input").value = raw; await h.node("inventory-input").emit("input");
  h.reply({ detail: { code: "inventory_revision_conflict", current_revision: 2 } }, 409); await h.node("inventory-save").emit("click"); assert.equal(h.calls[2].options.body, '{"expected_revision":1,"state":' + raw + '}'); assert.equal(h.node("inventory-input").value, raw); assert.match(h.node("notice").textContent, /Reload current versions/);
});

test("late inventory response cannot repaint holdings cleared on session end", async () => {
  const h = harness(); await h.connect(); const delayed = h.pending(true); const loading = h.node("inventory-load").emit("click");
  await tick(); await h.node("disconnect").emit("click"); delayed.resolve(inventoryFixture()); await loading;
  assert.equal(h.node("inventory-output").textContent, ""); assert.equal(h.node("inventory-input").value, "");
  assert.match(h.node("notice").textContent, /Session ended/); assert.equal(h.node("inventory-map").children.some((node) => node.attributes.role === "button"), false);
});

test("retained synchronization updates untouched inventory but preserves edited and fixed-time drafts", async () => {
  const h = harness(); await h.connect(); h.reply(inventoryFixture()); await h.node("inventory-load").emit("click");
  const inventoryReads = () => h.calls.filter((call) => call.url === "/v1/inventory").length;
  const synchronize = async (includeInventory) => {
    h.reply(indexFixture()); h.reply({ enabled: true, running: false, scopes: [] });
    if (includeInventory) h.reply(inventoryFixture()); await h.intervals[0]();
  };
  await synchronize(true); assert.equal(inventoryReads(), 2);
  h.node("inventory-input").value = '{"invented_unsaved":"kept"}'; await synchronize(false);
  assert.equal(inventoryReads(), 2); assert.equal(h.node("inventory-input").value, '{"invented_unsaved":"kept"}');
  h.node("inventory-input").value = JSON.stringify(inventoryFixture().state, null, 2); h.node("inventory-live").checked = false;
  await synchronize(false); assert.equal(inventoryReads(), 2);
  assert.equal(h.calls.filter((call) => call.url === "/v1/demo/market").length, 4);
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

function walk(node) { return [node, ...node.children.flatMap(walk)]; }
function draftHarness(raw, requirements = []) {
  const container = new Node("div"); container.root = true; const messages = [];
  const window = {}; const context = vm.createContext({ window, document: { createElement: (tag) => new Node(tag) } });
  vm.runInContext(draftScript, context, { filename: "workbench-drafts.js" });
  const mount = () => window.ComputeDrafts.mount(container, JSON.parse(raw), {
    parse: JSON.parse, raw, readRaw: () => raw, changed: (value) => { raw = value; }, message: (text) => messages.push(text), requirements,
  });
  return { container, component: window.ComputeDrafts, mount, messages, raw: () => raw,
    setAdvanced: (text) => { raw = text; }, field: (location) => walk(container).find((node) => node.attributes["data-field-path"] === location) };
}

test("fresh draft contracts have no invented prices, money, location or qualification", () => {
  const h = draftHarness('{}'); const pricing = h.component.template("pricing"); const inference = h.component.template("inference");
  assert.equal(pricing.commercial, null); assert.equal(pricing.target.country_code, null); assert.equal(pricing.market.policy, null);
  assert.equal(inference.costs.gpu_rate_per_gpu_hour, null); assert.equal(inference.qualification.status, null);
  assert.equal(inference.workload.tensor_parallel, null); assert.equal(inference.qualification.memory.includes_kv_cache, null);
  assert.equal(inference.pricing_policy, null);
  assert.equal(h.component.template("cash").opening_cash, null); assert.equal(h.component.template("inventory").sites.length, 0);
});

test("exact monetary text preserves digits and explicit zero differs from unknown", async () => {
  const h = draftHarness('{"opening_cash":null,"extensions":{"declared_rate":"200.12500000000000000000009"}}'); h.mount();
  const opening = h.field("opening_cash"); opening.value = "0"; await opening.emit("input");
  assert.equal(JSON.parse(h.raw()).opening_cash, "0"); assert.equal(JSON.parse(h.raw()).extensions.declared_rate, "200.12500000000000000000009");
  opening.value = ""; await opening.emit("input"); assert.equal(JSON.parse(h.raw()).opening_cash, null);
});

test("registered coverage booleans and whole values use explicit supported types", async () => {
  const requirements = [{ requirement_id: "check:flag", value_type: "boolean" }, { requirement_id: "check:count", value_type: "integer" }];
  const h = draftHarness('{"evidence":[{"requirement_id":"check:flag","value":null},{"requirement_id":"check:count","value":null}],"tensor_parallel":null}', requirements); h.mount();
  const flag = h.field("evidence.0.value"); flag.value = "false"; await flag.emit("change");
  const count = h.field("evidence.1.value"); count.value = "17"; await count.emit("input");
  const parallel = h.field("tensor_parallel"); parallel.value = "3"; await parallel.emit("input");
  const result = JSON.parse(h.raw()); assert.equal(result.evidence[0].value, false); assert.equal(result.evidence[1].value, "17"); assert.equal(result.tensor_parallel, 3);
});

test("malformed existing boolean choice cannot silently become a false assertion", async () => {
  const h = draftHarness('{"includes_kv_cache":"unreviewed"}'); h.mount();
  const control = h.field("includes_kv_cache"); control.value = "unreviewed"; await control.emit("change");
  assert.equal(JSON.parse(h.raw()).includes_kv_cache, "unreviewed");
  control.value = "false"; await control.emit("change"); assert.equal(JSON.parse(h.raw()).includes_kv_cache, false);
});

test("ordinary prototype-named extension fields cannot activate registered shapes", async () => {
  const h = draftHarness('{"extensions":{"toString":null,"hasOwnProperty":null}}'); h.mount();
  const control = h.field("extensions.toString"); assert.ok(control); assert.equal(control.value, "");
  control.value = "explicit custom value"; await control.emit("input");
  assert.equal(JSON.parse(h.raw()).extensions.toString, "explicit custom value");
  assert.equal(JSON.parse(h.raw()).extensions.hasOwnProperty, null); assert.equal(h.component.template("toString"), undefined);
});

test("advanced draft replacement prevents older mounted handlers overwriting it", async () => {
  const h = draftHarness('{"opening_cash":"7"}'); h.mount(); const field = h.field("opening_cash");
  h.setAdvanced('{"opening_cash":"9","new_input":true}'); field.value = "100"; await field.emit("input");
  assert.equal(h.raw(), '{"opening_cash":"9","new_input":true}'); assert.match(h.messages[0], /newer input was preserved/);
});

test("renderer failure is atomic and complete large arrays are preserved without conversion", async () => {
  let deep = { value: "invented-private-draft" }; for (let i = 0; i < 12; i++) deep = { next: deep };
  const invalid = draftHarness(JSON.stringify({ account_id: "account:invented-secret", extensions: deep }));
  assert.throws(() => invalid.mount(), /budget/); assert.equal(invalid.container.children.length, 0);
  const unsafe = draftHarness('{"opening_cash":"1","__proto__":{"polluted":true}}'); assert.throws(() => unsafe.mount(), /Reserved/); assert.equal(unsafe.container.children.length, 0);
  const values = Array.from({ length: 43 }, (_, index) => ({ id: "claim:" + index, amount: "1.0000000000000000000003" }));
  const retained = draftHarness(JSON.stringify({ opening_cash: "5", entries: values })); const editor = retained.mount();
  assert.match(retained.container.textContent, /43 entries preserved/); retained.field("opening_cash").value = "6"; await retained.field("opening_cash").emit("input");
  assert.deepEqual(JSON.parse(retained.raw()).entries, values); editor.clear(); assert.equal(retained.container.children.length, 0);
});

test("physical identity arrays edit individual strings and new sites retain unknown coordinates", async () => {
  const h = draftHarness('{"sites":[],"unit_ids":["unit:gamma"]}'); h.mount(); const identity = h.field("unit_ids.0");
  identity.value = "unit:delta"; await identity.emit("input");
  const add = walk(h.container).find((node) => node.tagName === "button" && node.textContent === "Add sites"); await add.emit("click");
  const value = JSON.parse(h.raw()); assert.deepEqual(value.unit_ids, ["unit:delta"]); assert.equal(value.sites[0].country_code, null); assert.equal(value.sites[0].latitude, null); assert.equal(value.sites[0].longitude, null);
});

test("new extension fields remain explicit typed inputs without adding monetary effects", async () => {
  const h = draftHarness('{"opening_cash":"12","extensions":{}}'); h.mount();
  const details = walk(h.container).find((node) => node.className === "add-field");
  const name = details.children.find((node) => node.tagName === "input"); const type = details.children.find((node) => node.tagName === "select");
  const button = details.children.find((node) => node.tagName === "button"); name.value = "reviewed_flag"; type.value = "boolean"; await button.emit("click");
  const field = h.field("extensions.reviewed_flag"); assert.equal(field.value, ""); field.value = "false"; await field.emit("change");
  const value = JSON.parse(h.raw()); assert.equal(value.extensions.reviewed_flag, false); assert.equal(value.opening_cash, "12");
});

test("inference price policy remains unknown until explicit ticks and margin terms are supplied", async () => {
  const h = draftHarness('{"pricing_policy":null}'); h.mount();
  const add = walk(h.container).find((node) => node.tagName === "button" && node.textContent === "Add pricing policy"); await add.emit("click");
  let request = JSON.parse(h.raw()); assert.equal(request.pricing_policy.required_margin, null); assert.equal(request.pricing_policy.task_price_tick, null);
  assert.equal(request.pricing_policy.rate_ticks.request_fee, null);
  const tick = h.field("pricing_policy.rate_ticks.request_fee"); tick.value = "0.000000001"; await tick.emit("input");
  request = JSON.parse(h.raw()); assert.equal(request.pricing_policy.rate_ticks.request_fee, "0.000000001"); assert.equal(request.pricing_policy.rate_ticks.input_per_million, null);
});

test("adding a routed quote cannot implicitly assert zero platform operating costs", async () => {
  const h = draftHarness('{"external_route":null}'); h.mount();
  const add = walk(h.container).find((node) => node.tagName === "button" && node.textContent === "Add external route"); await add.emit("click");
  assert.equal(JSON.parse(h.raw()).external_route.cost_items, null);
  const declare = walk(h.container).find((node) => node.tagName === "button" && node.textContent === "Declare routed operating cost list"); await declare.emit("click");
  assert.deepEqual(JSON.parse(h.raw()).external_route.cost_items, []);
  const item = walk(h.container).find((node) => node.tagName === "button" && node.textContent === "Add cost items"); await item.emit("click");
  const basis = h.field("external_route.cost_items.0.basis"); assert.deepEqual(basis.children.map((node) => node.value), ["", "whole_horizon", "per_request"]);
  assert.equal(JSON.parse(h.raw()).external_route.cost_items[0].amount, null);
});

test("resumed workspace waits for prior logout before issuing another cookie bootstrap", async () => {
  const h = harness(); await h.connect(); const finishLogout = h.delayLogout(); await h.node("disconnect").emit("click");
  const reopening = h.connect(indexFixture({ observations: [observation("AFTER-LOGOUT", "7")] })); await tick();
  assert.equal(h.sessionCalls.filter((call) => call.url.endsWith("bootstrap")).length, 1);
  finishLogout(); await reopening; assert.equal(h.sessionCalls.filter((call) => call.url.endsWith("bootstrap")).length, 2);
  assert.match(h.node("records-body").textContent, /AFTER-LOGOUT/);
});

test("workspace startup uses same-origin session cookies and structural unknown inputs", async () => {
  const h = harness(); await h.connect(); const setup = h.sessionCalls[0];
  assert.equal(setup.url, "/v1/session/bootstrap"); assert.equal(setup.options.credentials, "same-origin");
  assert.equal(setup.options.headers.Authorization, undefined); assert.equal(setup.options.body, "{}");
  assert.ok(h.allCalls.some((call) => call.url === "/v1/market/refresh/status"));
  const cash = JSON.parse(h.node("cash-input").value); assert.equal(cash.opening_cash, null); assert.equal(cash.currency, null);
  const inference = JSON.parse(h.node("inference-input").value); assert.equal(inference.workload.model_id, null); assert.equal(inference.qualification.status, null);
  assert.equal(h.node("overview-decision").textContent, "Unevaluated");
});

test("session end during startup parallel reads cannot recreate cleared forms or feedback", async () => {
  const h = harness(); h.reply({ auth_mode: "local_session", csrf_token: "e".repeat(64) }); h.reply(indexFixture());
  h.pending(); h.pending(); h.pending(); const opening = h.window.emit("load"); await tick();
  await h.node("disconnect").emit("click"); await opening;
  for (const kind of ["pricing", "inference", "cash", "portfolio", "inventory", "underwriting"]) {
    assert.equal(h.node(kind + "-input").value, ""); assert.equal(h.node(kind + "-fields").children.length, 0);
  }
  assert.match(h.node("notice").textContent, /Session ended/);
});

test("shipped structured edit retains exact strings and marks prior pricing decision stale", async () => {
  const h = harness(); await h.connect();
  h.node("pricing-input").value = '{"commercial":{"buyer_rate":"33.123456789012345678901","supplier_ask":null},"extensions":{"customer_declared":"kept"}}';
  await h.node("pricing-input").emit("input"); await h.node("pricing-read-fields").emit("click");
  h.reply({ result: { status: "indicative", bid: { submitted_limit: "4.2" }, economics: { currency: "EUR" } } });
  await h.node("evaluate-pricing").emit("click"); assert.equal(h.node("overview-decision").textContent, "indicative");
  const ask = walk(h.node("pricing-fields")).find((node) => node.attributes["data-field-path"] === "commercial.supplier_ask");
  ask.value = "0"; await ask.emit("input"); const result = JSON.parse(h.node("pricing-input").value);
  assert.equal(result.commercial.supplier_ask, "0"); assert.equal(result.commercial.buyer_rate, "33.123456789012345678901");
  assert.equal(result.extensions.customer_declared, "kept"); assert.equal(h.node("overview-decision").textContent, "Draft changed");
  assert.equal(h.node("pricing-result-state").textContent, "Previous input");
});

test("shipped structured transformations reject duplicate keys and unsafe numeric literals", async () => {
  const h = harness(); await h.connect();
  for (const raw of ['{"opening_cash":"1","opening_cash":"2"}', '{"opening_cash":9007199254740995}']) {
    h.node("cash-input").value = raw; await h.node("cash-read-fields").emit("click");
    assert.equal(h.node("cash-input").value, raw); assert.match(h.node("notice").textContent, /Duplicate JSON key|exact decimal strings/);
  }
});

test("first failing shipped field mount and subsequent logout leave no partial identifiers", async () => {
  const h = harness(); await h.connect(); let nested = { note: "invented-sensitive" };
  for (let i = 0; i < 12; i++) nested = { next: nested };
  const raw = JSON.stringify({ buyer_entity_id: "buyer:invented-sensitive", extensions: nested });
  h.node("portfolio-input").value = raw; await h.node("portfolio-read-fields").emit("click");
  assert.equal(h.node("portfolio-input").value, raw); assert.match(h.node("notice").textContent, /budget/);
  assert.equal(h.node("portfolio-fields").children.length, 0); await h.node("disconnect").emit("click");
  assert.equal(h.node("portfolio-input").value, ""); assert.equal(h.node("portfolio-fields").children.length, 0);
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
