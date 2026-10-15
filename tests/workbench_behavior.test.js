"use strict";
// Drive the shipped host script's event handlers (session, routing, theme, the Quotes-to-Pricing handoff); every fetch is an offline fixture.
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
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
  const documentElement = new Node("html"); const calls = []; const responses = []; const timers = new Map(); let timerId = 0;
  const allCalls = []; const sessionCalls = []; const logoutResponses = []; let booting = false;
  const pageDocument = {};
  const headerBag = (headers) => { const lower = Object.fromEntries(Object.entries(headers).map(([key, value]) => [key.toLowerCase(), value])); return { get: (name) => lower[name.toLowerCase()] ?? null }; };
  const fetch = (url, options) => {
    allCalls.push({ url, options });
    if (url.startsWith("/v1/session/")) sessionCalls.push({ url, options });
    else if (!booting) calls.push({ url, options });
    if (url === "/v1/session/logout") return logoutResponses.shift() || Promise.resolve({ ok: true, status: 200, json: async () => ({ ended: true }) });
    const response = responses.shift(); assert.ok(response, "Unexpected request: " + url); return response(options);
  };
  const context = vm.createContext({ document: { get title() { return pageDocument.title; }, set title(value) { pageDocument.title = value; }, documentElement, getElementById: (id) => { assert.ok(nodes.has(id), "Missing DOM element " + id); return nodes.get(id); }, createElement: (tag) => new Node(tag), createElementNS: (_, tag) => new Node(tag), querySelectorAll: () => nav }, window, fetch, AbortController, structuredClone, setTimeout: (fn, delay) => { timers.set(++timerId, { fn, delay }); return timerId; }, clearTimeout: (id) => timers.delete(id), console });
  vm.runInContext(script, context, { filename: "workbench.js" });
  function reply(body, status = 200, headers = {}) { responses.push(async () => ({ ok: status >= 200 && status < 300, status, headers: headerBag(headers), json: async () => structuredClone(body), text: async () => typeof body === "string" ? body : JSON.stringify(body) })); }
  function pending(ignoreAbort = false) {
    let resolve; let reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    responses.push((options) => { if (!ignoreAbort) options.signal.addEventListener("abort", () => { const error = new Error("aborted"); error.name = "AbortError"; reject(error); }, { once: true }); return promise; });
    return { resolve: (body, status = 200, headers = {}) => resolve({ ok: status >= 200 && status < 300, status, headers: headerBag(headers), json: async () => body, text: async () => body }), reject };
  }
  // The workspace opens with one handshake; the pages read their own data afterwards through ComputeHost.api.
  async function connect() {
    booting = true;
    reply({ auth_mode: "local_session", csrf_token: "invented-csrf-marker", expires_at: "2099-01-01T00:00:00Z" });
    await window.emit("load"); booting = false;
  }
  return { page: pageDocument, replyLogout: (body, status) => logoutResponses.push(Promise.resolve({ok: status >= 200 && status < 300, status, json: async () => body})), node: (id) => nodes.get(id), calls, reply, pending, timers, window, documentElement, connect, nav, allCalls, sessionCalls };
}

const tick = () => new Promise((resolve) => setImmediate(resolve));
const evaluated = (overrides = {}) => ({ snapshot_id: "synthetic-result", result: { status: "indicative", economics: { currency: "USD" }, ...overrides } });

test("startup is locked: no fetch happens before the load event, and the workspace opens once on it", async () => {
  const h = harness(); assert.equal(h.allCalls.length, 0); assert.equal(h.window.listeners.get("load").length, 1);
  assert.equal(h.window.ComputeHost.isSession(), false); assert.equal(h.node("cancel-request").disabled, true); assert.equal(h.node("activity-bar").hidden, true);
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
  const fresh = harness(); assert.equal(fresh.documentElement.attributes["data-theme"], "light");
});

test("each workspace navigation action has one handler and updates current page", async () => {
  const h = harness(); const nav = h.nav.find((button) => button.dataset.view === "quotes");
  assert.equal(nav.listeners.get("click").length, 1); await nav.emit("click");
  assert.equal(h.node("quotes-view").hidden, false); assert.equal(h.node("desk-view").hidden, true);
  assert.equal(nav.attributes["aria-current"], "page");
});

test("the navigation offers the Overview, Quotes and Pricing pages and the Brief, and no others", () => {
  const h = harness(); assert.deepEqual([...new Set(h.nav.map((button) => button.dataset.view))].sort(), ["brief", "desk", "pricing", "quotes"]);
  for (const view of ["brief", "desk", "quotes", "pricing"]) assert.ok(h.node(view + "-view"), view + " has a page");
});

test("arriving on another view starts at the top; choosing the current view leaves the scroll position alone", async () => {
  const h = harness(); const nav = (view) => h.nav.find((button) => button.dataset.view === view);
  h.window.scrolls.length = 0;
  await nav("quotes").emit("click");
  assert.equal(h.window.scrolls.length, 1);
  assert.equal(h.window.scrolls[0].top, 0); assert.equal(h.window.scrolls[0].behavior, "instant");
  await nav("quotes").emit("click");
  assert.equal(h.window.scrolls.length, 1, "the page does not jump when it is already showing");
});

test("the landing page is a page of its own: choosing a view writes its address, and the landing address is plain", async () => {
  const h = harness(); const nav = (view) => h.nav.find((button) => button.dataset.view === view);
  assert.equal(h.documentElement.attributes["data-page"] ?? "landing", "landing");
  await nav("quotes").emit("click");
  assert.deepEqual([...h.window.pushed], ["#quotes"]);
  assert.equal(h.documentElement.attributes["data-page"], "app");
  await nav("quotes").emit("click");
  assert.equal(h.window.pushed.length, 1, "choosing the page already showing adds no history entry");
  await nav("brief").emit("click");
  assert.deepEqual([...h.window.pushed], ["#quotes", "/"]);
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
  const deep = harness({ hash: "#quotes" }); await deep.window.emit("load");
  assert.equal(deep.node("quotes-view").hidden, false); assert.equal(deep.node("brief-view").hidden, true);
  assert.equal(deep.window.pushed.length, 0, "opening a link does not add a history entry");
  const pricing = harness({ hash: "#pricing" }); await pricing.window.emit("load");
  assert.equal(pricing.node("pricing-view").hidden, false);
  const odd = harness({ hash: "#not-a-page" }); await odd.window.emit("load");
  assert.equal(odd.node("brief-view").hidden, false);
  const loose = harness({ hash: "#brief" }); await loose.window.emit("load");
  assert.equal(loose.node("brief-view").hidden, false);
  for (const gone of ["#dashboard", "#market", "#inventory", "#underwriting", "#policy", "#inference", "#cash", "#portfolio"]) {
    const old = harness({ hash: gone }); await old.window.emit("load");
    assert.equal(old.node("brief-view").hidden, false, gone + " was removed and now opens the landing page");
  }
});

test("every page has its own tab title", async () => {
  const h = harness(); const nav = (view) => h.nav.find((button) => button.dataset.view === view);
  await nav("quotes").emit("click"); assert.match(h.page.title, / · ComputeBasis$/);
  await nav("brief").emit("click"); assert.equal(h.page.title, "ComputeBasis: GPU quotes priced all-in");
});

test("both header theme toggles stay in step", async () => {
  const h = harness(); await h.node("lp-theme-toggle").emit("click");
  assert.equal(h.documentElement.attributes["data-theme"], "dark");
  assert.equal(h.node("theme-toggle").attributes["aria-pressed"], "true");
  assert.equal(h.node("lp-theme-toggle").attributes["aria-pressed"], "true");
  await h.node("theme-toggle").emit("click");
  assert.equal(h.node("lp-theme-toggle").attributes["aria-pressed"], "false");
});

test("browser load bootstraps an HttpOnly session with one handshake and no other read", async () => {
  const h = harness(); await h.connect();
  assert.equal(h.node("session-card").hidden, true); assert.equal(h.node("session-state").textContent, "Connected");
  assert.equal(h.sessionCalls[0].url, "/v1/session/bootstrap"); assert.equal(h.sessionCalls[0].options.credentials, "same-origin");
  assert.equal(h.sessionCalls[0].options.body, "{}"); assert.equal(h.sessionCalls[0].options.headers.Authorization, undefined);
  assert.equal(h.allCalls.length, 1, "opening the workspace reads no market index, inventory or catalog");
});

test("a failed handshake leaves the workspace paused with the reason, not half open", async () => {
  const h = harness(); h.reply({ detail: "not_available" }, 503); await h.window.emit("load");
  assert.equal(h.node("session-card").hidden, false); assert.equal(h.node("session-state").textContent, "Offline");
  assert.match(h.node("session-help").textContent, /503/);
});

test("a conditional read sends its validator, and a 304 returns nothing to parse", async () => {
  const h = harness(); await h.connect(); const api = h.window.ComputeHost.api;
  const meta = { ifNoneMatch: 'W/"one"' }; h.reply(null, 304, { ETag: 'W/"one"' });
  assert.equal(await api("/v1/book", {}, meta), null);
  assert.equal(h.calls[0].options.headers["If-None-Match"], 'W/"one"'); assert.equal(meta.status, 304);
  const fresh = {}; h.reply({ meta: { tick: 1 } }, 200, { ETag: 'W/"two"' });
  assert.deepEqual(await api("/v1/book", {}, fresh), { meta: { tick: 1 } });
  assert.equal(fresh.etag, 'W/"two"'); assert.equal(h.calls[1].options.headers["If-None-Match"], undefined);
});

test("ending the session aborts active requests, and a late response cannot restore old data", async () => {
  const h = harness(); await h.connect(); const delayed = h.pending(true);
  const running = h.window.ComputeHost.api("/v1/pricing/demo/evaluate", { method: "POST", body: "{}" }).then(() => "answered", (error) => error.message); await tick();
  await h.node("disconnect").emit("click"); assert.equal(h.calls[0].options.signal.aborted, true);
  delayed.resolve({ snapshot_id: "SECRET-OLD", result: { status: "indicative" } });
  assert.match(await running, /session ended while this request was running/, "the late answer is discarded, not returned");
  assert.match(h.node("notice").textContent, /Session ended/); assert.doesNotMatch(h.node("notice").textContent, /SECRET-OLD/);
});

test("late failed bootstrap cannot clear a newer connected workspace", async () => {
  const h = harness(); const old = h.pending(true); const first = h.node("connect-session").emit("click"); await tick();
  await h.node("disconnect").emit("click"); const resumed = h.connect();
  old.resolve({ detail: "old rejected" }, 401); await first; await resumed;
  assert.equal(h.node("session-state").textContent, "Connected"); assert.equal(h.node("session-card").hidden, true); assert.equal(h.window.ComputeHost.isSession(), true);
});

test("stop waiting and a timeout abort the opening handshake and leave the workspace paused with the reason", async () => {
  const h = harness(); h.pending(); const opening = h.window.emit("load"); await tick();
  assert.equal(h.node("activity-bar").hidden, false, "waiting shows the activity bar");
  await h.node("cancel-request").emit("click"); await opening;
  assert.match(h.node("session-help").textContent, /Server work may continue/); assert.equal(h.node("session-card").hidden, false); assert.equal(h.window.ComputeHost.isSession(), false);
  assert.equal(h.node("activity-bar").hidden, true); assert.equal(h.sessionCalls.length, 1);
  h.pending(); const again = h.node("connect-session").emit("click"); await tick();
  const timer = [...h.timers.values()][0]; assert.equal(timer.delay, 30000); timer.fn(); await again;
  assert.match(h.node("session-help").textContent, /timed out/); assert.equal(h.node("connect-session").disabled, false);
});

test("expired read sessions renew once, while mutations are never replayed", async () => {
  const h = harness(); await h.connect(); const api = h.window.ComputeHost.api;
  h.reply({ detail: "unauthorized" }, 401); h.reply({ auth_mode: "local_session", csrf_token: "renewed-marker" }); h.reply({ meta: { tick: 2 } });
  assert.deepEqual(await api("/v1/book"), { meta: { tick: 2 } });
  h.reply({ detail: "unauthorized" }, 401); h.reply({ auth_mode: "local_session", csrf_token: "mutation-renewed-marker" });
  await assert.rejects(api("/v1/pricing/demo/evaluate", { method: "POST", body: "{}" }), /no mutation was retried/);
  assert.equal(h.sessionCalls.filter((call) => call.url.includes("bootstrap")).length, 3);
  assert.equal(h.calls.filter((call) => call.url === "/v1/pricing/demo/evaluate").length, 1);
});

test("Price this quote shows Pricing and hands the very same quote, with its exact price string, to the Pricing page", async () => {
  const h = harness(); const quote = { id: "q-149", ref: "Q0149", gpu: "H100", price: "3.123456789012", exact: { price: "3.123456789012" } };
  const outcome = Promise.resolve(true); const calls = [];
  h.window.ComputePricingDemo = { loadQuote: (given) => { calls.push({ given, pricingShown: h.node("pricing-view").hidden === false }); return outcome; } };
  const result = h.window.ComputeHost.priceQuote(quote);
  assert.equal(result, outcome, "the Pricing page's own promise comes back");
  assert.equal(calls.length, 1); assert.equal(calls[0].given, quote, "the same object, not a copy"); assert.equal(calls[0].given.price, "3.123456789012");
  assert.equal(calls[0].pricingShown, true, "Pricing is already showing when the quote reaches it");
  assert.equal(h.node("pricing-view").hidden, false); assert.equal(h.node("quotes-view").hidden, true); assert.equal(h.node("brief-view").hidden, true);
  assert.deepEqual([...h.window.pushed], ["#pricing"]);
  assert.equal(h.allCalls.length, 0, "the host sends no request of its own"); assert.equal(h.node("notice").hidden, true);
  assert.equal(await result, true);
});

test("a quote the Pricing page can only queue still opens Pricing and passes the answer through without a host error", async () => {
  const h = harness(); h.window.ComputePricingDemo = { loadQuote: () => Promise.resolve(false) };
  assert.equal(await h.window.ComputeHost.priceQuote({ id: "q-1", price: "2.5" }), false);
  assert.equal(h.node("pricing-view").hidden, false); assert.equal(h.node("notice").hidden, true);
});

test("if the Pricing page is missing, Price this quote still opens Pricing and says why nothing was loaded", async () => {
  const h = harness(); assert.equal(h.window.ComputePricingDemo, undefined);
  assert.equal(await h.window.ComputeHost.priceQuote({ id: "q-1", price: "2.5" }), false);
  assert.equal(h.node("pricing-view").hidden, false);
  assert.equal(h.node("notice").hidden, false); assert.equal(h.node("notice").className, "notice error"); assert.match(h.node("notice").textContent, /Pricing page is not available/);
});

test("mutations send memory CSRF while the exact request bytes and decimals are preserved", async () => {
  const h = harness(); await h.connect(); const raw = '{"amount":"12345678901234567890.000000000000001","field":1,"field":2}';
  h.reply(evaluated({ bid: { submitted_limit: "0.93000000000000000001" } }));
  const receipt = await h.window.ComputeHost.api("/v1/pricing/demo/evaluate", { method: "POST", body: raw });
  const call = h.calls.at(-1); assert.equal(call.url, "/v1/pricing/demo/evaluate"); assert.equal(call.options.method, "POST");
  assert.equal(call.options.headers["X-Compute-CSRF"], "invented-csrf-marker"); assert.equal(call.options.headers["Content-Type"], "application/json");
  assert.equal(call.options.credentials, "same-origin"); assert.equal(call.options.redirect, "error");
  assert.equal(call.options.body, raw, "the body is sent as written, never re-serialised");
  assert.equal(receipt.result.bid.submitted_limit, "0.93000000000000000001");
  h.reply({ meta: { tick: 1 } }); await h.window.ComputeHost.api("/v1/book");
  assert.equal(h.calls.at(-1).options.headers["X-Compute-CSRF"], undefined, "a read carries no protection token");
});

test("ending the session revokes it with the memory CSRF and leaves the workspace paused", async () => {
  const h = harness(); await h.connect(); assert.equal(h.window.ComputeHost.isSession(), true);
  const seen = []; h.window.ComputeHost.onSession((on) => seen.push(on));
  await h.node("disconnect").emit("click");
  assert.equal(h.sessionCalls.at(-1).url, "/v1/session/logout"); assert.equal(h.sessionCalls.at(-1).options.headers["X-Compute-CSRF"], "invented-csrf-marker");
  assert.deepEqual(seen, [false], "the pages hear that the session ended");
  assert.equal(h.window.ComputeHost.isSession(), false); assert.equal(h.node("session-card").hidden, false); assert.equal(h.node("disconnect").hidden, true);
  assert.equal(h.node("session-state").textContent, "Offline"); assert.match(h.node("notice").textContent, /Session ended/);
  await assert.rejects(h.window.ComputeHost.api("/v1/book"), /session is unavailable/, "nothing is sent once the session has ended");
});

test("ending a session while the workspace opens cannot recreate the session", async () => {
  const h = harness(); const handshake = h.pending(true); const opening = h.window.emit("load"); await tick();
  await h.node("disconnect").emit("click"); handshake.resolve({ auth_mode: "local_session", csrf_token: "invented-csrf-marker" }); await opening;
  assert.equal(h.window.ComputeHost.isSession(), false); assert.match(h.node("notice").textContent, /Session ended/); assert.equal(h.node("session-card").hidden, false);
});

test("evicted protection tokens renew without replaying a mutation", async () => {
  const h = harness(); await h.connect(); const draft = '{"opening_cash":"0.000000000000000000004"}'; const api = h.window.ComputeHost.api;
  h.reply({ detail: "browser_csrf_required" }, 403); h.reply({ auth_mode: "local_session", csrf_token: "replacement-csrf" });
  await assert.rejects(api("/v1/pricing/demo/evaluate", { method: "POST", body: draft }), /Workspace resumed.*no mutation was retried/s);
  assert.equal(h.calls.filter((call) => call.url === "/v1/pricing/demo/evaluate").length, 1);
  h.reply(evaluated()); await api("/v1/pricing/demo/evaluate", { method: "POST", body: draft });
  assert.equal(h.calls.at(-1).options.headers["X-Compute-CSRF"], "replacement-csrf"); assert.equal(h.calls.at(-1).options.body, draft);
});

test("a non-CSRF forbidden response cannot trigger session renewal", async () => {
  const h = harness(); await h.connect();
  h.reply({ detail: "browser_origin_not_allowed" }, 403);
  await assert.rejects(h.window.ComputeHost.api("/v1/pricing/demo/evaluate", { method: "POST", body: "{}" }), /browser_origin_not_allowed/);
  assert.equal(h.sessionCalls.filter((call) => call.url.includes("bootstrap")).length, 1);
});

test("logout renews an evicted token solely to revoke without reconnecting", async () => {
  const h = harness(); await h.connect();
  h.replyLogout({ detail: "browser_csrf_required" }, 403); h.reply({ auth_mode: "local_session", csrf_token: "e".repeat(64) });
  await h.node("disconnect").emit("click"); for (let i = 0; i < 8; i++) await tick();
  assert.equal(h.sessionCalls.filter((call) => call.url.endsWith("logout")).length, 2);
  assert.equal(h.sessionCalls.at(-1).options.headers["X-Compute-CSRF"], "e".repeat(64));
  assert.equal(h.window.ComputeHost.isSession(), false); assert.equal(h.node("session-card").hidden, false);
});
