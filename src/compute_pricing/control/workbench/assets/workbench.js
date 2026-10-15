(() => {
  "use strict";
  const byId = (id) => document.getElementById(id);
  const state = { session: false, csrf: "", forms: new Map(), epoch: 0, synthetic: false, busy: false, action: null, controllers: new Map() };
  const EMPTY = "—";
  let bootstrap = null;
  let logoutBarrier = null;
  let darkMode = window.matchMedia?.("(prefers-color-scheme: dark)").matches === true;
  const THEME_TOGGLES = ["theme-toggle", "lp-theme-toggle"];  // the app header and the landing header
  function applyTheme() {
    document.documentElement.setAttribute("data-theme", darkMode ? "dark" : "light");
    THEME_TOGGLES.forEach((id) => {
      const toggle = byId(id);
      // The accessible name stays "Dark mode"; aria-pressed carries the state. Only the tooltip names the action.
      toggle.setAttribute("aria-pressed", String(darkMode));
      toggle.setAttribute("title", darkMode ? "Switch to light theme" : "Switch to dark theme");
    });
  }
  applyTheme();
  THEME_TOGGLES.forEach((id) => byId(id).addEventListener("click", () => { darkMode = !darkMode; applyTheme(); }));

  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined && text !== null) node.textContent = String(text);
    if (className) node.className = className;
    return node;
  }
  function text(id, value) { byId(id).textContent = value === null || value === undefined ? EMPTY : String(value); }
  function notify(message, error = false) {
    const node = byId("notice");
    node.textContent = message; node.className = error ? "notice error" : "notice"; node.hidden = !message;
  }
  function setBusy(busy) {
    state.busy = busy;
    byId("connect-session").disabled = busy;
    byId("load-sample").disabled = busy;
    byId("cancel-request").disabled = !busy;
    byId("activity-bar").hidden = !busy;
    byId("evaluate-pricing").disabled = busy || !state.session || !byId("pricing-input").value.trim();
  }
  const viewListeners = [];
  const sessionListeners = [];
  /* The landing page lives at "/" and every app page at "/#name", so a refresh or the back button lands where the person was.
     route.js, which runs before first paint, keeps its own list of the app names. */
  const VIEWS = ["brief", "desk", "quotes", "pricing"];
  const LANDING_TITLE = "ComputeBasis: GPU quotes priced all-in";
  let routing = false;
  const routeOf = () => { const name = (window.location?.hash || "").slice(1); return name !== "brief" && VIEWS.includes(name) ? name : "brief"; };
  function writeRoute(name) {
    if (routing || !window.history?.pushState || routeOf() === name) return;
    window.history.pushState({ view: name }, "", name === "brief" ? window.location.pathname + window.location.search : "#" + name);
  }
  function showView(name, focus = true) {
    const arriving = byId(name + "-view").hidden;
    VIEWS.forEach((view) => { byId(view + "-view").hidden = view !== name; });
    document.documentElement.setAttribute("data-page", name === "brief" ? "landing" : "app"); writeRoute(name);
    document.title = name === "brief" ? LANDING_TITLE : String(byId(name + "-title").textContent || "").trim() + " · ComputeBasis";
    document.querySelectorAll("[data-view]").forEach((button) => {
      const selected = button.dataset.view === name;
      button.classList.toggle("active", selected);
      if (selected) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current");
    });
    if (arriving) window.scrollTo({ top: 0, left: 0, behavior: "instant" });
    if (focus) byId(name + "-title").focus({ preventScroll: true });
    viewListeners.forEach((listener) => listener(name));
  }
  function abortRequests(reason) {
    state.controllers.forEach((request, controller) => { request.reason = reason; controller.abort(); });
  }
  function clearSession(message = "Session ended. Received data and drafts were cleared.") {
    state.epoch++; abortRequests("session"); state.action = null; state.session = false; state.csrf = ""; state.forms.forEach((editor) => editor.clear()); state.forms.clear(); state.synthetic = false;
    // A deliberate end carries a message; a failed or interrupted connection clears with none.
    const ended = Boolean(message);
    text("session-title", ended ? "Workspace paused" : "Workspace unavailable");
    text("session-help", ended ? "Resume to open a fresh workspace." : "The local service establishes your workspace automatically. Retry when it is available.");
    byId("session-card").hidden = false; byId("disconnect").hidden = true;
    byId("session-dot").classList.remove("connected", "live", "paused"); text("session-state", "Offline"); sessionListeners.forEach((listener) => listener(false));
    byId("pricing-fields").replaceChildren(); text("pricing-fields-state", "Resume the workspace to prepare or load a draft.");
    byId("pricing-input").value = ""; byId("pricing-output").textContent = ""; byId("pricing-output").hidden = true;
    byId("pricing-summary").replaceChildren(element("p", "Supply an explicit scenario to evaluate.", "empty-state"));
    text("pricing-result-state", "Not evaluated"); byId("pricing-result-state").className = "pill";
    text("pricing-input-state", "No input supplied.");
    byId("pricing-input-state").className = "field-help";
    text("pricing-mode", "Declared input · no example loaded");
    setBusy(false); notify(message);
  }
  async function request(path, options = {}, { authenticated = true, timeout = 30000, format = "json", meta = null } = {}) {
    if (authenticated && !state.session) throw new Error("The local workspace session is unavailable. Resume the workspace before retrying.");
    const epoch = state.epoch;
    const controller = new AbortController();
    const pending = { epoch, reason: null }; state.controllers.set(controller, pending);
    const timer = setTimeout(() => { pending.reason = "timeout"; controller.abort(); }, timeout);
    try {
      const mutation = !["GET", "HEAD"].includes(options.method || "GET");
      const headers = { ...(authenticated && mutation ? { "X-Compute-CSRF": state.csrf } : {}), ...(options.body ? { "Content-Type": "application/json" } : {}), ...(meta?.ifNoneMatch ? { "If-None-Match": meta.ifNoneMatch } : {}) };
      const response = await fetch(path, { ...options, headers, credentials: "same-origin", cache: "no-store", redirect: "error", signal: controller.signal });
      const unchanged = response.status === 304 && Boolean(meta?.ifNoneMatch);
      const data = unchanged ? null : format === "text" ? await response.text() : await response.json().catch(() => null);
      if (epoch !== state.epoch || authenticated && !state.session) throw new Error("The session ended while this request was running. Received data was discarded.");
      if (controller.signal.aborted) { const error = new Error("Request aborted"); error.name = "AbortError"; throw error; }
      if (meta) { meta.status = response.status; meta.etag = response.headers.get("ETag") || ""; }
      if (unchanged) return null;
      if (!response.ok) {
        if (response.status === 401) { const error = new Error("Workspace session expired. Resume the workspace; no mutation was retried."); error.status = 401; throw error; }
        const detail = typeof data?.detail === "string" ? data.detail : typeof data?.detail?.code === "string" ? data.detail.code : "Request rejected";
        if (response.status === 403 && detail === "browser_csrf_required") { const error = new Error("Workspace protection token needs renewal; no mutation was retried."); error.code = detail; throw error; }
        throw new Error("HTTP " + response.status + " · " + detail);
      }
      if (format === "json" && (!data || Array.isArray(data) || typeof data !== "object")) throw new Error("The local API returned an invalid JSON response.");
      return data;
    } catch (error) {
      if (error.name === "AbortError") throw new Error(pending.reason === "timeout" ? "Request timed out. Check the local service, then retry; the server may still be completing the work." : "Stopped waiting. Server work may continue; check its result before retrying.");
      if (error instanceof TypeError) throw new Error("The local API could not be reached. Check the local service, then retry; your draft is preserved.");
      throw error;
    } finally { clearTimeout(timer); state.controllers.delete(controller); }
  }
  async function establishSession() {
    const epoch = state.epoch;
    if (logoutBarrier) await logoutBarrier;
    if (epoch !== state.epoch) throw new Error("Workspace changed during session setup.");
    if (bootstrap) {
      const prior = bootstrap;
      try { await prior.promise; } catch (error) { if (prior.epoch === epoch) throw error; }
      if (epoch !== state.epoch) throw new Error("Workspace changed during session setup.");
      if (prior.epoch === epoch) return;
    }
    const current = { epoch, promise: null };
    current.promise = (async () => {
      const session = await request("/v1/session/bootstrap", { method: "POST", body: "{}" }, { authenticated: false });
      if (epoch !== state.epoch) throw new Error("Workspace changed during session setup.");
      if (typeof session.csrf_token !== "string" || !session.csrf_token || session.auth_mode !== "local_session") throw new Error("The local service returned an invalid workspace session.");
      state.session = true; state.csrf = session.csrf_token;
      byId("session-card").hidden = true; byId("disconnect").hidden = false;
      text("session-state", "Connected"); byId("session-dot").classList.add("connected"); sessionListeners.forEach((listener) => listener(true));
    })();
    bootstrap = current;
    try { await current.promise; } finally { if (bootstrap === current) bootstrap = null; }
  }
  async function api(path, options = {}, meta = null) {
    const settings = { timeout: 30000, meta };
    try { return await request(path, options, settings); }
    catch (error) {
      if (error.status !== 401 && error.code !== "browser_csrf_required") throw error;
      await establishSession();
      if (!["GET", "HEAD"].includes(options.method || "GET")) throw new Error("Workspace resumed. Review and retry your action; no mutation was retried. Your draft is preserved.");
      return request(path, options, settings);
    }
  }
  async function startWorkspace() {
    if (state.busy) return;
    await runAction("Opening local workspace…", async () => {
      const epoch = state.epoch;
      try {
        await establishSession();
        if (epoch !== state.epoch || !state.session) return;
        if (!byId("pricing-input").value.trim()) createBlankDraft("pricing");
      }
      catch (error) { if (epoch === state.epoch) { clearSession(""); text("session-help", error.message); } throw error; }
    });
  }
  async function runAction(label, action) {
    if (state.busy) return;
    const current = { epoch: state.epoch }; state.action = current; setBusy(true); text("activity-label", label); notify("");
    try { await action(); }
    catch (error) { if (current.epoch === state.epoch) notify(error.message, true); }
    finally { if (state.action === current && current.epoch === state.epoch) { state.action = null; setBusy(false); } }
  }
  function metric(container, label, value) { const card = element("div", undefined, "result-metric"); card.append(element("span", label), element("strong", value ?? EMPTY)); container.append(card); }
  function moneyMetric(container, label, value, currency) { metric(container, label, value === null || value === undefined ? null : String(value) + " " + (currency || "(currency not returned)")); }
  function renderEvaluation(kind, envelope) {
    const result = envelope.result || envelope; const summary = byId(kind + "-summary"); summary.replaceChildren();
    text(kind + "-result-state", result.status || "Scenario calculated");
    byId(kind + "-result-state").className = "pill " + (result.status === "held" ? "warn" : "good");
    const blockers = result.hold_reasons || result.blockers || [];
    const currency = result.economics?.currency || result.benchmark?.currency || result.benchmark?.cohort?.currency;
    const hypothetical = result.pricing_provenance?.source_evidence_eligible !== true;
    const displayedBenchmark = hypothetical ? result.scenario_diagnostics?.benchmark || result.benchmark : result.benchmark;
    moneyMetric(summary, hypothetical ? "Scenario reference · source evidence unbound" : result.benchmark?.cohort?.scope === "aggregate_reference" ? "Advertised global reference · per GPU-hour" : "Comparable reference · per GPU-hour", displayedBenchmark?.price, displayedBenchmark?.currency || displayedBenchmark?.cohort?.currency);
    moneyMetric(summary, "Submitted purchase limit · per GPU-hour", result.pricing_provenance?.source_evidence_eligible === true && result.status !== "held" ? result.bid?.submitted_limit : null, currency);
    moneyMetric(summary, hypothetical ? "Scenario sell floor · per GPU-hour" : "Required-margin sell floor · per GPU-hour", result.ask?.sell_floor_tick, currency);
    moneyMetric(summary, hypothetical ? "Scenario profit at supplied supplier ask" : "Economic profit at supplied supplier ask", result.economics?.economic_profit, currency);
    moneyMetric(summary, hypothetical || result.status === "held" ? "Scenario free cash · candidate calculation" : "Minimum free cash at selected bid", result.cash_constraint?.minimum_free_cash, currency);
    moneyMetric(summary, "Extra cash required at supplier ask", result.cash_constraint?.supplied_ask_required_extra_cash, currency);
    if (result.cash_constraint?.supplied_ask_cash_feasible === false) summary.append(element("div", "The supplied supplier ask has a funding shortfall. A positive modeled profit does not make that purchase cash-feasible.", "result-blockers"));
    if (hypothetical) summary.append(element("p", "Scenario arithmetic only. Apply a current saved policy to exact retained source observations to bind evidence; the server rechecks rights and freshness. No purchase bid is recommended.", "result-provenance"));
    if (blockers.length) summary.append(element("div", "Held: " + blockers.join(" · "), "result-blockers"));
    summary.append(element("p", "Snapshot " + (envelope.snapshot_id || EMPTY) + " · " + (envelope.created_at || result.as_of || EMPTY) + " · Indicative / held; execution disabled. Monetary values retain their source precision. Full cash paths, versions and exclusions appear below.", "result-provenance"));
    const output = byId(kind + "-output"); output.textContent = JSON.stringify(envelope, null, 2); output.hidden = false;
    byId(kind + "-input-state").className = "field-help"; text(kind + "-input-state", "Evaluated the submitted draft. Changing inputs requires another evaluation.");
  }
  function inputChanged(kind) {
    const value = byId(kind + "-input").value.trim();
    text(kind + "-input-state", value ? "Draft changed. Results, if shown, belong to the last submitted input." : "No input supplied.");
    byId(kind + "-input-state").className = "field-help";
    if (!byId(kind + "-output").hidden) { text(kind + "-result-state", "Previous input"); byId(kind + "-result-state").className = "pill warn"; }
    setBusy(state.busy);
  }
  async function evaluate(kind) {
    const raw = byId(kind + "-input").value;
    if (!raw.trim()) { notify("Paste an explicit " + kind + " JSON request first.", true); return; }
    try { JSON.parse(raw); } catch (_) { text(kind + "-input-state", "Invalid JSON. Correct the editor before evaluating."); byId(kind + "-input-state").className = "field-help error"; byId(kind + "-input").focus(); notify("The editor contains invalid JSON. No request was sent.", true); return; }
    await runAction("Evaluating declared " + kind + " inputs…", async () => {
      renderEvaluation(kind, await api("/v1/" + kind + "/evaluate", { method: "POST", body: raw }));
      if (byId(kind + "-input").value !== raw) inputChanged(kind);
      notify("Scenario saved. Review the decision state and cash constraints; the complete response contains its reproducible snapshot.");
    });
  }
  function safeEditableJson(raw) {
    // Transformations reject duplicate keys and unsafe numeric literals. Direct evaluations still send original bytes.
    const result = JSON.parse(raw); let cursor = 0;
    const white = () => { while (/\s/.test(raw[cursor] || "") && cursor < raw.length) cursor++; };
    const string = () => { const start = cursor++; while (cursor < raw.length) { if (raw[cursor] === "\\") cursor += 2; else if (raw[cursor++] === '"') break; } return JSON.parse(raw.slice(start, cursor)); };
    const value = () => {
      white(); const token = raw[cursor];
      if (token === "{") { cursor++; white(); const keys = new Set(); if (raw[cursor] === "}") { cursor++; return; } while (cursor < raw.length) { white(); const key = string(); if (keys.has(key)) throw new Error("Duplicate JSON key: " + key + ". Correct the draft before transforming it."); keys.add(key); white(); cursor++; value(); white(); if (raw[cursor++] === "}") break; } }
      else if (token === "[") { cursor++; white(); if (raw[cursor] === "]") { cursor++; return; } while (cursor < raw.length) { value(); white(); if (raw[cursor++] === "]") break; } }
      else if (token === '"') string();
      else { const match = /^(?:-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null)/.exec(raw.slice(cursor)); if (!match) throw new Error("Invalid JSON token"); cursor += match[0].length; if (/^-?\d/.test(match[0]) && (!/^-?\d+$/.test(match[0]) || !Number.isSafeInteger(Number(match[0])))) throw new Error("JSON transformations require exact decimal strings and safe whole-number literals. Correct this draft first."); }
    };
    value(); return result;
  }
  function readFields(kind) {
    const raw = byId(kind + "-input").value;
    const draft = safeEditableJson(raw);
    state.forms.get(kind)?.clear();
    let editor;
    try { editor = window.ComputeDrafts.mount(byId(kind + "-fields"), draft, {
      parse: safeEditableJson, raw, readRaw: () => byId(kind + "-input").value, message: notify,
      changed: (updated) => {
        byId(kind + "-input").value = updated;
        inputChanged(kind);
        text(kind + "-fields-state", "Unsaved draft. Empty values remain unknown; additional fields remain explicit.");
      },
    }); } catch (error) { byId(kind + "-fields").replaceChildren(); state.forms.delete(kind); throw error; }
    state.forms.set(kind, editor); text(kind + "-fields-state", "Editing the current request. Rates and amounts remain exact strings.");
  }
  function createBlankDraft(kind, supplied = null) {
    if (byId(kind + "-input").value.trim()) throw new Error("A draft already exists. Clear it in Advanced request JSON before starting a blank draft, or read it into fields.");
    const draft = supplied || window.ComputeDrafts.template(kind);
    if (!draft) throw new Error("Load the versioned backend template for this request.");
    byId(kind + "-input").value = JSON.stringify(draft, null, 2);
    readFields(kind); inputChanged(kind);
  }
  document.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", (event) => { event?.preventDefault?.(); showView(button.dataset.view); }));
  window.addEventListener("popstate", () => { routing = true; try { showView(routeOf()); } finally { routing = false; } });
  // Runs on load, after every deferred script has registered its view listeners, so a reload on "/#quotes" draws Quotes.
  function openRoutedView() { if (routeOf() === "brief") return; routing = true; try { showView(routeOf(), false); } finally { routing = false; } }
  byId("connect-session").addEventListener("click", startWorkspace);
  byId("disconnect").addEventListener("click", () => {
    const csrf = state.csrf; const inflight = bootstrap?.promise; clearSession();
    // Serialize cookie changes. Resume waits for the old handshake and revocation.
    logoutBarrier = (async () => {
      if (inflight) await inflight.catch(() => {});
      if (!csrf) return;
      const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), 30000);
      try {
        const close = token => fetch("/v1/session/logout", { method: "POST", body: "{}", headers: { "Content-Type": "application/json", "X-Compute-CSRF": token }, credentials: "same-origin", cache: "no-store", redirect: "error", signal: controller.signal });
        const response = await close(csrf);
        if (response.status === 403 && (await response.json().catch(() => null))?.detail === "browser_csrf_required") {
          const renewal = await fetch("/v1/session/bootstrap", { method: "POST", body: "{}", headers: { "Content-Type": "application/json" }, credentials: "same-origin", cache: "no-store", redirect: "error", signal: controller.signal });
          const data = await renewal.json();
          if (!renewal.ok || data.auth_mode !== "local_session" || typeof data.csrf_token !== "string" || !data.csrf_token) throw new Error("Revocation renewal failed");
          await close(data.csrf_token); // This does not reconnect or restore page data.
        }
      }
      catch (_) { /* The page is cleared; expiry bounds a failed revocation. */ }
      finally { clearTimeout(timer); }
    })();
  });
  byId("cancel-request").addEventListener("click", () => { abortRequests("user"); });
  // The example is always the labelled invented scenario. A simulated quote may replace only the supplier ask; the editor is filled, never evaluated or saved.
  async function loadPricingExample(quote) {
    const raw = await request("/workbench/assets/synthetic-pricing-request.json", {}, { authenticated: false, format: "text" });
    let body = raw, mode = "SYNTHETIC EXAMPLE · invented scenario", message = "Loaded an invented pricing scenario in the editor only. Market evidence and retained source snapshots are unchanged.";
    if (quote) {
      const packet = JSON.parse(raw);
      packet.commercial.supplier_ask = String(quote.price);
      packet.extensions.workbench_sample = { kind: "synthetic", description: "Independently invented scenario; never live inventory. Only the supplier ask comes from simulated quote " + quote.id + "." };
      body = JSON.stringify(packet, null, 2);
      mode = "SYNTHETIC EXAMPLE · supplier ask from simulated " + quote.id;
      message = "Loaded the invented scenario with " + quote.id + "'s ask of $" + quote.price + " per GPU-hour as the supplier ask. Every other term is the labelled example. Evaluate to see the bid ceiling and sell floor.";
    }
    byId("pricing-input").value = body; readFields("pricing"); state.synthetic = true; inputChanged("pricing"); text("pricing-mode", mode); notify(message);
  }
  byId("load-sample").addEventListener("click", () => runAction("Loading the labelled synthetic example…", () => loadPricingExample(null)));
  function priceQuote(quote) { showView("pricing"); return runAction("Loading the labelled synthetic example…", () => loadPricingExample(quote)); }
  byId("pricing-input").addEventListener("input", () => text("pricing-mode", state.synthetic ? "Edited synthetic scenario · declared inputs" : "Edited declared input · review evidence scope"));
  byId("clear-pricing").addEventListener("click", () => { byId("pricing-input").value = ""; state.forms.get("pricing")?.clear(); state.synthetic = false; inputChanged("pricing"); text("pricing-mode", "Declared input · no example loaded"); });
  byId("evaluate-pricing").addEventListener("click", () => evaluate("pricing")); byId("pricing-input").addEventListener("input", () => inputChanged("pricing"));
  byId("pricing-read-fields").addEventListener("click", () => { try { readFields("pricing"); } catch (error) { notify(error.message, true); } });
  byId("pricing-new-draft").addEventListener("click", () => runAction("Preparing a blank input contract…", async () => {
    // This explicit reset action changes the draft, never stored evidence.
    byId("pricing-input").value = ""; state.forms.get("pricing")?.clear(); createBlankDraft("pricing");
  }));
  window.addEventListener("pagehide", () => clearSession(""));
  setBusy(false);
  window.addEventListener("load", () => { openRoutedView(); return startWorkspace(); });
  window.ComputeHost = Object.freeze({
    api, byId, notify, showView, priceQuote, isSession: () => state.session,
    onView: (listener) => { viewListeners.push(listener); }, onSession: (listener) => { sessionListeners.push(listener); },
  });
})();
