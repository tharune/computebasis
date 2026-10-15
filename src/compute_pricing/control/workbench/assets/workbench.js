(() => {
  "use strict";
  const byId = (id) => document.getElementById(id);
  const state = { session: false, csrf: "", epoch: 0, busy: false, action: null, controllers: new Map() };
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

  function text(id, value) { byId(id).textContent = value === null || value === undefined ? EMPTY : String(value); }
  function notify(message, error = false) {
    const node = byId("notice");
    node.textContent = message; node.className = error ? "notice error" : "notice"; node.hidden = !message;
  }
  function setBusy(busy) {
    state.busy = busy;
    byId("connect-session").disabled = busy;
    byId("cancel-request").disabled = !busy;
    byId("activity-bar").hidden = !busy;
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
    state.epoch++; abortRequests("session"); state.action = null; state.session = false; state.csrf = "";
    // A deliberate end carries a message; a failed or interrupted connection clears with none.
    const ended = Boolean(message);
    text("session-title", ended ? "Workspace paused" : "Workspace unavailable");
    text("session-help", ended ? "Resume to open a fresh workspace." : "The local service establishes your workspace automatically. Retry when it is available.");
    byId("session-card").hidden = false; byId("disconnect").hidden = true;
    byId("session-dot").classList.remove("connected", "live", "paused"); text("session-state", "Offline"); sessionListeners.forEach((listener) => listener(false));
    setBusy(false); notify(message);
  }
  async function request(path, options = {}, { authenticated = true, timeout = 30000, meta = null } = {}) {
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
      const data = unchanged ? null : await response.json().catch(() => null);
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
      if (!data || Array.isArray(data) || typeof data !== "object") throw new Error("The local API returned an invalid JSON response.");
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
      try { await establishSession(); }
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
  /* "Price this quote" on the Quotes page. The Pricing page owns the form, so the quote goes to it: it fills the supplier ask now, or holds
     the quote until the workspace session, the backend contract and any running evaluation allow it. Resolves true only when the form was
     filled now. */
  function priceQuote(quote) {
    showView("pricing");
    const pricing = window.ComputePricingDemo;
    if (!pricing || typeof pricing.loadQuote !== "function") { notify("The Pricing page is not available, so this quote was not loaded. Reload the page and try again.", true); return Promise.resolve(false); }
    return pricing.loadQuote(quote);
  }
  window.addEventListener("pagehide", () => clearSession(""));
  setBusy(false);
  window.addEventListener("load", () => { openRoutedView(); return startWorkspace(); });
  window.ComputeHost = Object.freeze({
    api, byId, notify, showView, priceQuote, isSession: () => state.session,
    onView: (listener) => { viewListeners.push(listener); }, onSession: (listener) => { sessionListeners.push(listener); },
  });
})();
