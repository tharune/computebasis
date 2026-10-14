"use strict";
// Shared browserless harness for the Brief/Overview/Quotes suites: a fake DOM that throws on innerHTML and inline styles (as the CSP
// would), a fake host, and makePage(), which loads the shipped scripts in index.html order and serves the real simulator's snapshots.
// Suites: const H = require("./demo_harness.js");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const assets = process.env.COMPUTEBASIS_WORKBENCH_ASSETS;
const snapshotFile = process.env.COMPUTEBASIS_BOOK_SNAPSHOTS;
assert.ok(assets, "COMPUTEBASIS_WORKBENCH_ASSETS must point to the checked-out workbench assets");
assert.ok(snapshotFile, "COMPUTEBASIS_BOOK_SNAPSHOTS must point to simulator snapshots (see tests/test_workbench_demo_js_v10.py)");
const snapshots = JSON.parse(fs.readFileSync(snapshotFile, "utf8"));
const html = fs.readFileSync(path.join(assets, "index.html"), "utf8");
const chartsSource = fs.readFileSync(path.join(assets, "workbench-charts.js"), "utf8");
const dataSource = fs.readFileSync(path.join(assets, "landing-data.js"), "utf8");
/* The page scripts, in the order index.html loads them: demo-core first, then every page file after it. */
const DEMO_FILES = [...html.matchAll(/<script src="\/workbench\/assets\/([^"]+\.js)"/g)].map((match) => match[1]).filter((name) => /^(demo-core|page-[a-z-]+|us-[a-z-]+|desk-[a-z-]+)\.js$/.test(name));
const deskFixture = JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures", "desk-ledger.json"), "utf8"));  // the desk-ledger contract, docs/desk-ledger-contract.md
const adapterSource = fs.readFileSync(path.join(assets, "book-adapter.js"), "utf8");
const landingChartsSource = fs.readFileSync(path.join(assets, "landing-charts.js"), "utf8");
/* What a chart slot reports as its width. undefined is "no layout engine at all" (the landing charts then use their own fallback width);
   0 is a hidden slot; a number is a laid-out column. Suites set it through makePage({ width }) or page.resize(). */
const layout = { width: undefined };

class El {
  constructor(tag) {
    this.tagName = tag; this.children = []; this.attributes = {}; this.listeners = new Map(); this.className = "";
    this.disabled = false; this.hidden = false; this.dataset = {}; this._text = "";
    this.classList = { add: (name) => this.setClass(name, true), remove: (name) => this.setClass(name, false), contains: (name) => this.has(name), toggle: (name, flag) => this.setClass(name, flag === undefined ? !this.has(name) : flag) };
  }
  has(name) { return this.className.split(/\s+/).includes(name); }
  setClass(name, on) { const set = new Set(this.className.split(/\s+/).filter(Boolean)); if (on) set.add(name); else set.delete(name); this.className = [...set].join(" "); }
  get style() { throw new Error("Inline styles are blocked by the content security policy"); }
  get innerHTML() { throw new Error("innerHTML is not allowed"); }
  set innerHTML(_) { throw new Error("innerHTML is not allowed"); }
  get textContent() { return this._text + this.children.map((child) => child.textContent).join(""); }
  set textContent(value) { this._text = String(value); this.children = []; }
  append(...nodes) { nodes.forEach((node) => { assert.ok(node instanceof El, "append expects DOM nodes"); this.children.push(node); }); }
  replaceChildren(...nodes) { this.children = []; this._text = ""; this.append(...nodes); }
  setAttribute(key, value) {
    assert.ok(!/^(style|on.*)$/i.test(key), "the content security policy blocks the " + key + " attribute");  // inline styles and inline handlers, set by any route
    this.attributes[key] = String(value);
  }
  getAttribute(key) { return this.attributes[key] ?? null; }
  removeAttribute(key) { delete this.attributes[key]; }
  addEventListener(name, action) { this.listeners.set(name, [...(this.listeners.get(name) || []), action]); }
  async click() { if (this.disabled) return; await Promise.all((this.listeners.get("click") || []).map((action) => action({ preventDefault() {}, target: this }))); }
  get clientWidth() { return this.has("bf-chart-host") ? layout.width : undefined; }
  matches() { return false; }  // :hover and :focus-within, which a suite turns on by assigning its own
  contains(node) { return node === this || this.children.some((child) => child.contains(node)); }
  removeChild(node) { this.children = this.children.filter((child) => child !== node); return node; }
  fire(name, event = {}) { (this.listeners.get(name) || []).forEach((action) => action({ target: this, preventDefault() {}, ...event })); }
  focus() { this.focused = true; this.fire("focus"); }
  scrollIntoView(options) { this.scrolled = options; }
}
const walk = (node, visit) => { visit(node); node.children.forEach((child) => walk(child, visit)); };
const findAll = (node, test) => { const out = []; walk(node, (item) => { if (test(item)) out.push(item); }); return out; };
const classes = (node) => `${node.className} ${node.attributes.class || ""}`.split(/\s+/);
const byClass = (node, name) => findAll(node, (item) => classes(item).includes(name));
const byTag = (node, tag) => findAll(node, (item) => item.tagName === tag);
const settle = async () => { for (let i = 0; i < 6; i++) await new Promise((resolve) => setImmediate(resolve)); };
const BROKEN = /\b(NaN|undefined|Infinity)\b|\[object/;
function assertClean(node, label = "chart") {
  walk(node, (item) => {
    for (const [key, value] of Object.entries(item.attributes)) assert.doesNotMatch(value, BROKEN, `${label}: attribute ${key} on <${item.tagName}> is "${value}"`);
    if (item._text) assert.doesNotMatch(item._text, BROKEN, `${label}: text "${item._text}"`);
  });
}

function makePage(initial, { priceQuote, browser = {}, desk = deskFixture, width } = {}) {
  layout.width = width;
  const ids = new Map();
  for (const tag of html.matchAll(/<([a-z][a-z0-9]*)\b([^>]*)>/g)) {
    const id = /\bid="([^"]+)"/.exec(tag[2]); if (id) ids.set(id[1], new El(tag[1]));
  }
  const server = { snapshot: initial, tag: 'W/"one"', session: true, failure: "", gate: null, posts: [], desk, deskTag: 'W/"desk-one"', deskFailure: "" };
  const calls = []; const notices = []; const shown = []; const priced = [];
  const viewListeners = []; const sessionListeners = []; const intervals = []; const documentListeners = [];
  const doc = {
    hidden: false,
    createElement: (tag) => new El(tag), createElementNS: (_, tag) => new El(tag),
    createTextNode: (text) => { const node = new El("#text"); node._text = String(text); return node; },
    addEventListener: (name, action) => documentListeners.push({ name, action }),
  };
  const host = {
    api: async (url, options = {}, meta) => {
      calls.push({ url, method: options.method || "GET", ifNoneMatch: meta?.ifNoneMatch || "" });
      if (url === "/v1/book/control") { server.posts.push(JSON.parse(options.body)); if (server.gate) await server.gate; return { simulated: true }; }
      if (url === "/v1/book/desk") {
        if (server.deskFailure) throw new Error(server.deskFailure);
        if (meta?.ifNoneMatch && meta.ifNoneMatch === server.deskTag) { meta.status = 304; return null; }
        meta.status = 200; meta.etag = server.deskTag; return structuredClone(server.desk);
      }
      assert.equal(url, "/v1/book", "unexpected request " + url);
      if (server.failure) throw new Error(server.failure);
      if (meta?.ifNoneMatch && meta.ifNoneMatch === server.tag) { meta.status = 304; return null; }
      meta.status = 200; meta.etag = server.tag; return structuredClone(server.snapshot);
    },
    byId: (id) => { assert.ok(ids.has(id), "Missing DOM element " + id); return ids.get(id); },
    notify: (message, error = false) => notices.push({ message, error }),
    showView: (name) => { shown.push(name); viewListeners.forEach((listener) => listener(name)); },
    isSession: () => server.session,
    onView: (listener) => viewListeners.push(listener), onSession: (listener) => sessionListeners.push(listener),
    ...(priceQuote ? { priceQuote: (quote) => { priced.push(quote); } } : {}),
  };
  const window = { ComputeHost: host, ...browser };  // browser: IntersectionObserver and matchMedia stand-ins
  const context = vm.createContext({ window, document: doc, setInterval: (fn, ms) => intervals.push({ fn, ms }), console });
  vm.runInContext(chartsSource, context, { filename: "workbench-charts.js" });
  vm.runInContext(adapterSource, context, { filename: "book-adapter.js" });
  vm.runInContext(landingChartsSource, context, { filename: "landing-charts.js" });
  vm.runInContext(dataSource, context, { filename: "landing-data.js" });
  DEMO_FILES.forEach((name) => vm.runInContext(fs.readFileSync(path.join(assets, name), "utf8"), context, { filename: name }));
  const el = (id) => host.byId(id);
  const button = (id, label) => findAll(el(id), (item) => item.tagName === "button" && item.textContent === label)[0];
  return {
    server, calls, bookCalls: () => calls.filter((call) => call.url === "/v1/book"), deskCalls: () => calls.filter((call) => call.url === "/v1/book/desk"), notices, shown, priced, host, el, button, doc, charts: window.ComputeCharts, landing: window.LandingCharts,
    resize: (next) => { layout.width = next; },
    connect: () => sessionListeners.forEach((listener) => listener(true)),
    disconnect: () => sessionListeners.forEach((listener) => listener(false)),
    poll: () => intervals.find((item) => item.ms === 2000).fn(),
    visibility: () => documentListeners.filter((item) => item.name === "visibilitychange").forEach((item) => item.action({})),
    press: (key) => documentListeners.filter((item) => item.name === "keydown").forEach((item) => item.action({ key })),
  };
}
const { base, war, reset } = snapshots;  // what the server sends: decimal strings, reason codes
const adapterContext = vm.createContext({ window: {} }); vm.runInContext(adapterSource, adapterContext, { filename: "book-adapter.js" });
const normalize = (raw) => adapterContext.window.BookAdapter.normalizeBook(raw);
const book = { base: normalize(base), war: normalize(war), reset: normalize(reset) };  // what the pages draw
const assertLive = (page) => { assert.equal(page.el("session-state").textContent, "Live"); assert.ok(page.el("session-dot").has("live")); };


module.exports = { layout, landingChartsSource, assert, fs, path, vm, assets, snapshots, html, El, walk, findAll, classes, byClass, byTag, settle, assertClean, makePage, base, war, reset, book, normalize, assertLive, DEMO_FILES, chartsSource, dataSource, adapterSource, deskFixture };
