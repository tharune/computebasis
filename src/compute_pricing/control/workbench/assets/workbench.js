(() => {
  "use strict";
  const byId = (id) => document.getElementById(id);
  const state = { session: false, csrf: "", refreshStatus: null, results: {}, forms: new Map(), epoch: 0, index: null, indexTag: "", syncedAt: 0, rows: [], sources: [], snapshots: [], page: 0, synthetic: false, busy: false, action: null, controllers: new Map(), detailOrigin: null, inventory: null, inventoryDemo: false, inventorySite: "", selectedLot: "", land: null, policyEntries: [], policyCatalog: [], policyRows: [], policySaved: null, policyDirty: true, policyControlsDirty: false, underwritingRows: [], underwritingCatalog: null };
  const PAGE_SIZE = 100;
  const EMPTY = "—";
  let underwritingScopeFields = [];
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
  document.addEventListener("click", (event) => { const menu = byId("more-menu"); if (menu.open && !menu.contains(event.target)) menu.open = false; });
  document.addEventListener("keydown", (event) => { const menu = byId("more-menu"); if (event.key === "Escape" && menu.open) { menu.open = false; byId("more-summary").focus(); } });

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
    ["reload-index", "refresh-market", "evaluate-pricing", "evaluate-inference", "evaluate-cash", "evaluate-live-reference"].forEach((id) => {
      const button = byId(id); if (button) button.disabled = busy || !state.session;
    });
    byId("refresh-market").disabled = busy || !state.session || !state.sources.some((source) => source.can_attempt_read);
    byId("connect-session").disabled = busy;
    byId("load-sample").disabled = busy;
    byId("cancel-request").disabled = !busy;
    byId("activity-bar").hidden = !busy;
    ["pricing", "inference", "cash", "portfolio"].forEach((kind) => {
      byId("evaluate-" + kind).disabled = busy || !state.session || !byId(kind + "-input").value.trim();
    });
    ["inventory-load", "inventory-demo", "policy-load", "policy-template", "policy-read-json", "policy-add-source"].forEach((id) => { byId(id).disabled = busy || !state.session; });
    byId("inventory-at").disabled = busy || byId("inventory-live").checked;
    byId("inventory-save").disabled = busy || !state.session || state.inventoryDemo || !byId("inventory-input").value.trim();
    ["policy-update-json", "policy-save"].forEach((id) => { byId(id).disabled = busy || !state.session || !byId("policy-input").value.trim(); });
    byId("policy-apply").disabled = busy || !state.session || !state.policySaved || state.policyDirty;
    byId("underwriting-template").disabled = busy || !state.session;
    byId("underwriting-assess").disabled = busy || !state.session || !byId("underwriting-input").value.trim();
    if (byId("evaluate-live-reference")) byId("evaluate-live-reference").disabled = busy || !state.session || !byId("live-model").value || !byId("live-terms").value;
  }
  const viewListeners = [];
  const sessionListeners = [];
  const MORE_VIEWS = ["dashboard", "market", "inventory", "underwriting", "inference", "cash", "portfolio", "policy"];
  /* The landing page lives at "/" and every app page at "/#name", so a refresh or the back button lands where the person was.
     route.js, which runs before first paint, keeps its own list of the app names. */
  const VIEWS = ["brief", "desk", "quotes", "dashboard", "market", "inventory", "underwriting", "pricing", "policy", "inference", "cash", "portfolio"];
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
    byId("more-summary").classList.toggle("active", MORE_VIEWS.includes(name)); byId("more-menu").open = false;
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
    state.epoch++; abortRequests("session"); state.action = null; state.session = false; state.csrf = ""; state.refreshStatus = null; state.results = {}; state.forms.forEach((editor) => editor.clear()); state.forms.clear(); state.index = null; state.indexTag = ""; state.syncedAt = 0; state.rows = []; state.sources = []; state.snapshots = []; state.synthetic = false; state.page = 0;
    // A deliberate end carries a message; a failed or interrupted connection clears with none.
    const ended = Boolean(message);
    text("session-title", ended ? "Workspace paused" : "Workspace unavailable");
    text("session-help", ended ? "Resume to open a fresh workspace." : "The local service establishes your workspace automatically. Retry when it is available.");
    byId("session-card").hidden = false; byId("disconnect").hidden = true;
    byId("session-dot").classList.remove("connected", "live", "paused"); text("session-state", "Offline"); sessionListeners.forEach((listener) => listener(false));
    ["pricing", "inference", "cash", "portfolio", "inventory", "underwriting"].forEach((kind) => {
      byId(kind + "-fields").replaceChildren(); text(kind + "-fields-state", "Resume the workspace to prepare or load a draft.");
    });
    ["pricing", "inference", "cash", "portfolio"].forEach((kind) => {
      byId(kind + "-input").value = ""; byId(kind + "-output").textContent = ""; byId(kind + "-output").hidden = true;
      byId(kind + "-summary").replaceChildren(element("p", "Supply an explicit scenario to evaluate.", "empty-state"));
      text(kind + "-result-state", "Not evaluated"); byId(kind + "-result-state").className = "pill";
      text(kind + "-input-state", "No input supplied.");
      byId(kind + "-input-state").className = "field-help";
    });
    text("pricing-mode", "Declared input · no example loaded");
    state.underwritingRows = []; state.underwritingCatalog = null;
    underwritingScopeFields = []; byId("underwriting-scopes").replaceChildren(element("p", "Load the catalog to select contract and workload paths.", "muted"));
    byId("underwriting-input").value = ""; byId("underwriting-output").textContent = ""; byId("underwriting-output").hidden = true; byId("underwriting-query").value = "";
    text("underwriting-result-state", "Not assessed"); byId("underwriting-result-state").className = "pill";
    text("underwriting-catalog-version", "No catalog loaded"); text("underwriting-input-state", "No input supplied.");
    byId("underwriting-summary").replaceChildren(element("p", "Load the versioned catalog or supply explicit requirements and evidence.", "empty-state")); renderUnderwritingRows();
    byId("record-detail-json").textContent = ""; byId("record-detail").hidden = true;
    byId("record-query").value = ""; byId("model-query").value = ""; state.detailOrigin = null;
    state.inventory = null; state.inventoryDemo = false; state.inventorySite = ""; state.selectedLot = "";
    ["inventory-input", "inventory-at", "inventory-query", "inventory-status", "policy-input"].forEach((id) => { byId(id).value = ""; });
    ["inventory-output", "policy-output"].forEach((id) => { byId(id).textContent = ""; byId(id).hidden = true; });
    state.policyEntries = []; state.policyCatalog = []; state.policyRows = []; state.policySaved = null; state.policyDirty = true; state.policyControlsDirty = false;
    [...POLICY_FIELDS, ...BENCHMARK_FIELDS].forEach(([, id]) => { byId(id).value = ""; });
    selection(byId("policy-select"), [], "Load available versions");
    byId("policy-source-rules").replaceChildren(element("p", "No policy loaded.", "empty-state")); byId("policy-feature-registry").replaceChildren(element("p", "No registry loaded.", "empty-state"));
    byId("policy-source-catalog").replaceChildren(element("p", "Load policy versions to inspect source permissions.", "muted"));
    text("policy-state", "No policy loaded"); text("policy-feedback", "A saved version is required before applying to a pricing draft."); renderInventory();
    text("inventory-time-help", "This evaluates the declared plan at a UTC instant; it does not reconstruct historically observed holdings.");
    renderIndex(); renderDashboard(); setBusy(false); notify(message);
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
      if (meta) { meta.status = response.status; meta.etag = response.headers.get("ETag") || ""; meta.asOf = response.headers.get("X-Index-As-Of") || ""; }
      if (unchanged) return null;
      if (!response.ok) {
        if (response.status === 401) { const error = new Error("Workspace session expired. Resume the workspace; no mutation was retried."); error.status = 401; throw error; }
        const detail = typeof data?.detail === "string" ? data.detail : typeof data?.detail?.code === "string" ? data.detail.code : "Request rejected";
        if (response.status === 403 && detail === "browser_csrf_required") { const error = new Error("Workspace protection token needs renewal; no mutation was retried."); error.code = detail; throw error; }
        const action = detail === "feature_changes_require_successor_registry_version" ? ". Increase the feature registry version as well as the policy version, then validate again." : /revision_conflict/.test(detail) ? ". Reload current versions before retrying; your unsaved draft is preserved." : "";
        throw new Error("HTTP " + response.status + " · " + detail + action);
      }
      if (format === "json" && (!data || Array.isArray(data) || typeof data !== "object")) throw new Error("The local API returned an invalid JSON response. Reload the retained index before retrying.");
      return data;
    } catch (error) {
      if (error.name === "AbortError") throw new Error(pending.reason === "timeout" ? "Request timed out. Reload the retained index before retrying; a source read may still be completing." : "Stopped waiting. Server work may continue; reload the retained index before retrying a source read.");
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
    const settings = { timeout: path === "/v1/market/refresh" ? 120000 : 30000, meta };
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
        await establishSession(); await loadIndex();
        const outcomes = await Promise.allSettled([loadRefreshStatus(), readInventory(true), loadUnderwritingCatalog()]);
        if (epoch !== state.epoch || !state.session) return;
        const failures = outcomes.filter((outcome) => outcome.status === "rejected");
        if (failures.length) notify("Workspace opened. " + failures.map((outcome) => outcome.reason.message).join(" · "), true);
        ["pricing", "inference", "cash"].forEach((kind) => { if (!byId(kind + "-input").value.trim()) createBlankDraft(kind); });
        renderDashboard();
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
  function currencyPrice(record) {
    const price = record.price || record.native_price || record.native_unit_price;
    if (price && price.amount !== undefined) return { amount: String(price.amount), currency: price.currency || record.currency || EMPTY, unit: price.unit || record.unit || EMPTY };
    if (record.retailPrice !== undefined || record.retail_price !== undefined) return { amount: String(record.retailPrice ?? record.retail_price), currency: record.currencyCode || record.currency || EMPTY, unit: record.unitOfMeasure || record.unit || EMPTY };
    return { amount: EMPTY, currency: record.currency || EMPTY, unit: record.unit || EMPTY };
  }
  function modelOf(record) { return record.hardware?.model || record.hardware_model || record.extensions?.cloud_sku || record.sku || record.sku_name || record.armSkuName || record.model_id || record.model || record.id || "Unmapped hardware / SKU"; }
  function regionOf(record) { return (typeof record.region === "string" ? record.region : record.region?.country_code || record.region?.locality || record.region?.name) || record.provider_region || record.extensions?.provider_region || record.region_name || record.armRegionName || record.location || "Unknown / global"; }
  function kindOf(record) { return record.extensions?.price_scope || record.kind || record.role || (record._catalog ? "native_catalog_reference" : "unknown_scope"); }
  function isFx(record) { return /(?:fx|exchange_rate)/i.test(record.kind || record.role || "") || Boolean(record.base_currency && (record.quote_currency || record.currency) && (record.quote_per_base !== undefined || record.rate !== undefined)); }
  function isModelMetadata(record) { return record.kind === "model_metadata" || record.role === "model_metadata" || record.price_eligible === false && Boolean(record.model_id); }
  function hasPublishedPrice(record) { return Boolean((record.price || record.native_price || record.native_unit_price)?.amount !== undefined || record.retailPrice !== undefined || record.retail_price !== undefined); }
  function freshness(record) {
    if (record.index_stale === true) return "Stale index / source record";
    if (!record.expires_at) return "Expiry unknown";
    const expires = Date.parse(record.expires_at);
    if (!Number.isFinite(expires)) return "Expiry unknown";
    return expires <= Date.now() || record.status === "stale" ? "Stale" : "Within stated expiry";
  }
  function selection(select, values, label) {
    const previous = select.value; select.replaceChildren(element("option", label)); select.firstChild.value = "";
    [...new Set(values)].sort().forEach((value) => { const option = element("option", value); option.value = value; select.append(option); });
    if (values.includes(previous)) select.value = previous;
  }
  function sourceLatest(source) {
    const latest = source.latest || source.latest_collection || {};
    const scopes = source.scopes || latest.scopes || [];
    return { captured: latest.captured_at || latest.created_at, count: scopes.length ? scopes.reduce((sum, scope) => sum + (scope.observation_count || 0), 0) : latest.observation_count ?? latest.record_count ?? latest.records ?? 0, catalog: scopes.length ? scopes.reduce((sum, scope) => sum + (scope.catalog_record_count || 0), 0) : latest.catalog_record_count ?? latest.catalog_count ?? 0, scopes };
  }
  function renderSources() {
    const grid = byId("sources-grid"); grid.replaceChildren();
    if (!state.sources.length) { grid.append(element("p", state.session ? "No source registry was returned." : "Connect to see implementation, access and permission states.", "empty-state")); return; }
    state.sources.forEach((source) => {
      const card = element("article", undefined, "source-card");
      const heading = element("div", undefined, "source-name"); heading.append(element("span", source.source_id || "Unknown source"), element("span", source.can_attempt_read ? "Read admitted" : "Held", "pill " + (source.can_attempt_read ? "good" : "warn")));
      card.append(heading, element("p", source.role || source.normalization || "Source scope unknown"));
      const latest = sourceLatest(source);
      card.append(element("p", latest.captured ? latest.count + " price observations · " + latest.catalog + " catalog records · " + latest.scopes.length + " retained scopes" : state.index?.coverage?.history_scan_truncated ? "No collection found in the bounded indexed history" : "No retained collection"));
      card.append(element("p", "Last successful capture: " + (latest.captured || "not available")));
      if (source.coverage?.complete === false || latest.scopes.some((scope) => scope.coverage?.complete === false)) card.append(element("p", "Partial coverage within configured scopes", "blocker"));
      if (source.coverage?.price_coverage_complete === false || latest.scopes.some((scope) => scope.coverage?.price_coverage_complete === false)) card.append(element("p", "Pricing coverage is partial; some model catalogs have missing or invalid advertised rate dimensions.", "blocker"));
      if (latest.scopes.some((scope) => scope.stale)) card.append(element("p", "One or more retained scopes are stale", "blocker"));
      if (latest.scopes.some((scope) => scope.display_truncated)) card.append(element("p", "Some retained rows are outside this bounded display; scope counts include them.", "blocker"));
      const detail = element("details"); detail.append(element("summary", "Permissions, scope & last attempt"));
      const meta = element("div", undefined, "source-meta");
      [source.implementation_state || "implementation unknown", "rights: " + (source.rights_status || "unknown"), "auth: " + (source.auth_state || "unknown"), "observed: " + (source.observed_liveness || "not probed")].forEach((label) => meta.append(element("span", label, "pill")));
      detail.append(meta);
      latest.scopes.forEach((scope) => detail.append(element("p", JSON.stringify(scope.filters || {}) + " · " + (scope.stale ? "stale" : "within collection policy") + " · " + (scope.captured_at || scope.created_at || EMPTY))));
      latest.scopes.filter((scope) => scope.display_truncated).forEach((scope) => detail.append(element("p", "Loaded " + scope.returned_observation_count + " / " + scope.observation_count + " observations and " + scope.returned_catalog_record_count + " / " + scope.catalog_record_count + " catalog rows for " + JSON.stringify(scope.filters || {}) + ". Display selection is separate from benchmark weighting.", "muted")));
      if (source.blockers?.length) detail.append(element("p", source.blockers.join(" · "), "blocker"));
      (source.last_attempts || []).forEach((attempt) => detail.append(element("p", "Last attempt " + attempt.status + " · " + (attempt.filters?.region || "configured scope") + " · " + (attempt.reason || attempt.at || "Review source receipt"), attempt.status === "updated" ? "muted" : "blocker")));
      card.append(detail);
      grid.append(card);
    });
  }
  function compareText(a, b) { return String(a).localeCompare(String(b), "en"); }
  function compareDecimal(a, b) {
    const parts = (value) => {
      const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(value);
      if (!match) return null;
      const integer = match[2].replace(/^0+(?=\d)/, ""); const fraction = (match[3] || "").replace(/0+$/, "");
      return { negative: Boolean(match[1]) && (integer !== "0" || fraction !== ""), integer, fraction };
    };
    const left = parts(a); const right = parts(b);
    if (!left || !right) return compareText(a, b);
    if (left.negative !== right.negative) return left.negative ? -1 : 1;
    const digits = Math.max(left.fraction.length, right.fraction.length);
    const lexical = (x, y) => x === y ? 0 : x < y ? -1 : 1;
    const magnitude = left.integer.length - right.integer.length || lexical(left.integer, right.integer) || lexical(left.fraction.padEnd(digits, "0"), right.fraction.padEnd(digits, "0"));
    return left.negative ? -magnitude : magnitude;
  }
  function observedOf(record) { return record.observed_at || record.effective_start || record.effectiveStartDate || ""; }
  function compareRows(a, b) {
    const order = byId("record-sort").value;
    if (order.startsWith("price-")) {
      const left = currencyPrice(a); const right = currencyPrice(b);
      // A rank across different currencies or native units would imply a conversion.
      const group = compareText(left.currency, right.currency) || compareText(left.unit, right.unit);
      if (group) return group;
      const amount = compareDecimal(left.amount, right.amount);
      if (amount) return order === "price-desc" ? -amount : amount;
    } else if (order === "hardware-asc") {
      const hardware = compareText(modelOf(a), modelOf(b)); if (hardware) return hardware;
    } else {
      const left = Date.parse(observedOf(a)); const right = Date.parse(observedOf(b));
      if (Number.isFinite(left) !== Number.isFinite(right)) return Number.isFinite(left) ? -1 : 1;
      if (Number.isFinite(left) && left !== right) return right - left;
    }
    return compareText(a.source_id || "", b.source_id || "") || compareText(a.id || "", b.id || "");
  }
  function filteredRows() {
    const query = byId("record-query").value.trim().toLowerCase();
    return state.rows.filter((record) => (!byId("source-filter").value || record.source_id === byId("source-filter").value) && (!byId("region-filter").value || regionOf(record) === byId("region-filter").value) && (!byId("kind-filter").value || kindOf(record) === byId("kind-filter").value) && (!query || (modelOf(record) + " " + (record.id || "")).toLowerCase().includes(query))).sort(compareRows);
  }
  function showRecord(record, origin = null) {
    state.detailOrigin = origin;
    byId("record-detail-json").textContent = JSON.stringify(record, null, 2); byId("record-detail").hidden = false;
    byId("detail-title").focus({ preventScroll: true }); byId("record-detail").scrollIntoView({ block: "nearest" });
  }
  function renderRows() {
    const rows = filteredRows(); const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE)); state.page = Math.min(state.page, pages - 1);
    const body = byId("records-body"); body.replaceChildren();
    const selected = rows.slice(state.page * PAGE_SIZE, (state.page + 1) * PAGE_SIZE);
    selected.forEach((record) => {
      const row = element("tr");
      const hardware = element("td", modelOf(record)); hardware.append(element("span", record.hardware?.accelerator_count ? record.hardware.accelerator_count + " stated GPUs per node" : "GPU mapping / count unverified", "subtext"));
      const source = element("td", record.source_id || EMPTY); source.append(element("span", kindOf(record), "subtext"));
      const price = currencyPrice(record); const status = element("td", record.status || "Source claim");
      status.append(element("span", freshness(record), "subtext"));
      const action = element("button", "Inspect", "quiet-button"); action.setAttribute("aria-label", "Inspect " + modelOf(record) + " from " + (record.source_id || "unknown source")); action.addEventListener("click", () => showRecord(record, action));
      const actionCell = element("td"); actionCell.append(action);
      row.append(hardware, source, element("td", price.amount + " " + price.currency, "price-cell"), element("td", price.unit), element("td", regionOf(record)), status, element("td", observedOf(record) || EMPTY, "observed-cell"), actionCell);
      body.append(row);
    });
    if (!selected.length) { const row = element("tr"); const cell = element("td", state.rows.length ? "No price records match these filters. Clear filters to see all retained prices." : state.session ? "No price records are retained. Read admitted feeds to collect configured scopes." : "Connect to load retained market evidence. Synthetic examples stay in the scenario editor.", "empty-state"); cell.colSpan = 8; row.append(cell); body.append(row); }
    text("record-count", rows.length + " matching records");
    text("page-label", rows.length ? "Showing " + (state.page * PAGE_SIZE + 1) + "–" + Math.min(rows.length, (state.page + 1) * PAGE_SIZE) + " of " + rows.length + " · Native price units remain separate" : "No records");
    byId("previous-page").disabled = state.page === 0; byId("next-page").disabled = state.page >= pages - 1;
  }
  function renderSnapshots() {
    const container = byId("snapshot-list"); container.replaceChildren();
    text("receipt-count", state.index ? state.snapshots.length + " receipts" : "Not loaded");
    if (!state.snapshots.length) { container.append(element("p", "No retained source snapshots returned.", "empty-state")); return; }
    state.snapshots.slice(0, 30).forEach((snapshot) => {
      const row = element("div", undefined, "snapshot-row");
      const label = element("div", (snapshot.source_id || "Source receipt") + " · " + (snapshot.captured_at || snapshot.created_at || EMPTY));
      label.append(element("br"), element("code", snapshot.snapshot_id || snapshot.digest || EMPTY)); row.append(label);
      const identity = snapshot.snapshot_id || snapshot.digest;
      if (identity) { const action = element("button", "Open audit receipt", "quiet-button"); action.addEventListener("click", () => runAction("Loading retained receipt…", async () => { showRecord(await api("/v1/decisions/" + encodeURIComponent(identity)), action); })); row.append(action); }
      container.append(row);
    });
    if (state.snapshots.length > 30) container.append(element("p", "Showing the first 30 of " + state.snapshots.length + " retained receipts. Full scope metadata remains in the index response.", "muted"));
  }
  function renderFx(index) {
    const rows = (index?.fx_records || []).concat((index?.catalog_records || []).filter(isFx));
    byId("fx-section").hidden = !rows.length; const container = byId("fx-records"); container.replaceChildren();
    text("fx-record-count", rows.length + " informational FX records");
    rows.slice(0, 50).forEach((record) => {
      const row = element("div", undefined, "snapshot-row");
      const base = record.base_currency || record.base || EMPTY; const quote = record.quote_currency || record.currency || record.quote || EMPTY;
      row.append(element("span", "1 " + base), element("code", (record.quote_per_base ?? record.rate ?? record.value ?? EMPTY) + " " + quote), element("span", (record.observed_at || record.observed_date || record.date || EMPTY) + (record.index_stale || record.status === "stale" ? " · stale" : " · published reference"), "muted")); container.append(row);
    });
    if (rows.length > 50) container.append(element("p", "Showing 50 of " + rows.length + " references.", "muted"));
  }
  function renderModelDiscovery(index) {
    const records = (index?.model_discovery || []).concat((index?.catalog_records || []).filter((record) => !isFx(record) && (isModelMetadata(record) || !hasPublishedPrice(record))));
    const container = byId("model-records"); container.replaceChildren(); byId("model-section").hidden = !records.length;
    const priceCatalogs = records.filter((record) => record.kind === "model_price_catalog");
    const isUnpriced = (record) => record.price_eligible === false || record.price_status?.startsWith("unpriced_") || !record.metadata?.pricing || (record.metadata.pricing.prompt === undefined && record.metadata.pricing.completion === undefined);
    const unpriced = priceCatalogs.filter(isUnpriced).length;
    text("model-record-count", records.length + " catalog records / " + (priceCatalogs.length - unpriced) + " advertised rate catalogs / " + unpriced + " unpriced model catalogs / " + (records.length - priceCatalogs.length) + " metadata only");
    const query = byId("model-query").value.trim().toLowerCase();
    const filtered = records.filter((record) => [record.model_id, record.id, record.source_id, record.kind, record.task, record.card_license, record.license_claim, ...(record.license_tags || []), ...(record.recipes || []).map((recipe) => recipe.engine)].filter(Boolean).join(" ").toLowerCase().includes(query));
    filtered.slice(0, 100).forEach((record) => {
      const row = element("div", undefined, "snapshot-row");
      const description = element("div", record.model_id || record.id || "Model metadata");
      description.append(element("br"), element("code", "Revision " + (record.repository_revision || "unknown") + " · License declared: " + (record.card_license || record.license_claim || record.license_tags?.join(", ") || "unknown")));
      if (Array.isArray(record.recipes)) description.append(element("p", record.source_id + " · " + record.recipes.length + " selected recipes · " + [...new Set(record.recipes.map((recipe) => recipe.engine + " / " + recipe.accelerator))].join(", ") + " · Configuration claims only", "muted"));
      const scope = record.kind === "model_price_catalog" ? isUnpriced(record) ? "UNPRICED / " + (record.price_status === "unpriced_invalid_advertised_dimensions" ? "invalid advertised dimensions quarantined" : "input/output token rates not published") : (record.price_status === "partial_token_rates" ? "Partial current-default token rates" : "Advertised current-default token rates") + " / " + (record.conditional_pricing_present ? "conditional pricing retained, unapplied" : "other billing dimensions require workload qualification") : record.gated ? "Gated access; permission review required" : "Public metadata; serving permissions unverified";
      description.append(element("p", scope + " · " + freshness(record) + " · No measured runtime qualification", "muted"));
      const inspect = element("button", "Inspect metadata", "quiet-button"); inspect.addEventListener("click", () => showRecord(record, inspect));
      row.append(description, inspect); container.append(row);
    });
    if (!filtered.length) container.append(element("p", "No catalog records match this filter.", "empty-state"));
    container.append(element("p", "Showing " + Math.min(100, filtered.length) + " of " + filtered.length + " matching records / " + records.length + " retained catalogs. Source coverage remains bounded.", "muted"));
  }
  function aggregateRows() {
    return state.rows.filter((record) => {
      const source = state.sources.find((candidate) => candidate.source_id === record.source_id);
      return record.kind === "aggregate_advertised_index" && record.price?.unit === "gpu_hour" && record.hardware?.model && record.index_stale !== true && ["claimed", "verified"].includes(record.status) && record.expires_at && Date.parse(record.expires_at) > Date.now() && record.rights?.benchmark === "PASS" && record.rights?.observe === "PASS" && source?.enabled && source?.rights_status === "allowed" && source?.permissions?.benchmark === "PASS" && record.extensions?.billing_type && Object.prototype.hasOwnProperty.call(record.extensions, "reservation_months");
    });
  }
  function renderLiveTerms() {
    const model = byId("live-model").value;
    const select = byId("live-terms"); const previous = select.value; select.replaceChildren();
    const terms = new Map();
    aggregateRows().filter((record) => record.hardware.model === model).forEach((record) => {
      const term = { billing_type: record.extensions.billing_type, reservation_months: record.extensions.reservation_months, currency: record.price.currency };
      terms.set(JSON.stringify(term), term);
    });
    terms.forEach((term, value) => { const option = element("option", term.currency + " / " + term.billing_type + (term.reservation_months === null ? " / unspecified term" : " / " + term.reservation_months + " reserved months")); option.value = value; select.append(option); });
    if (!terms.size) { const option = element("option", model ? "No current eligible terms" : "Choose a model first"); option.value = ""; select.append(option); }
    if (terms.has(previous)) select.value = previous;
    text("live-reference-state", !state.session ? "Connect to see eligible current aggregate cohorts." : !aggregateRows().length ? "No current aggregate cohort passes the source rights and expiry gates. Inspect admission and refresh coverage." : model ? terms.size + " currency / billing cohorts available. Exploration weights remain unvalidated." : "Select a model to choose exact currency and billing terms.");
    setBusy(state.busy);
  }
  function renderIndex() {
    const index = state.index;
    renderSources();
    selection(byId("source-filter"), state.rows.map((r) => r.source_id).filter(Boolean), "All price sources");
    selection(byId("region-filter"), state.rows.map(regionOf), "All regions");
    selection(byId("kind-filter"), state.rows.map(kindOf), "All scopes");
    selection(byId("live-model"), aggregateRows().map((r) => r.hardware.model), "Choose an admitted aggregate model");
    renderLiveTerms(); renderRows(); renderSnapshots(); renderFx(index); renderModelDiscovery(index);
    text("metric-observations", index ? state.rows.length : EMPTY);
    text("metric-sources", index ? new Set(state.rows.map((row) => row.source_id)).size : EMPTY);
    text("metric-source-total", index ? state.sources.filter((source) => source.scopes?.length || source.latest).length + " sources with retained data / " + state.sources.length + " configured across all roles" : "FX and model metadata counted separately");
    text("metric-admitted", index ? state.sources.filter((source) => source.can_attempt_read).length : EMPTY);
    text("metric-admitted-detail", index ? "Of " + state.sources.length + " configured price, FX and catalog sources" : "All source roles; admission gates apply");
    text("metric-asof", index?.as_of || EMPTY);
    text("metric-snapshots", index ? state.snapshots.length + " receipts across all roles; prices exclude FX / model metadata" : "No source snapshots loaded");
    const truncated = index?.truncated || index?.coverage?.truncated || index?.coverage?.display_truncated || index?.row_limit_reached;
    const coverage = [];
    if (truncated) coverage.push("API row limit reached");
    if (index?.coverage?.history_scan_truncated || index?.coverage?.possible_missing_scopes) coverage.push("History scan bounded; older source scopes may be missing");
    text("coverage-note", !index ? "Connect to load retained evidence." : coverage.length ? coverage.join(". ") + ". Inspect source coverage." : "Configured scopes only; coverage is source-specific.");
    const refresh = index?.last_refresh; const output = refresh?.document?.output || refresh?.result || refresh;
    text("refresh-state", output ? "Last read: " + (output.updated?.length || 0) + " updated / " + (output.held?.length || 0) + " held / " + (output.failed?.length || 0) + " failed" : "No refresh receipt");
    byId("refresh-state").className = "pill" + (output?.held?.length || output?.failed?.length ? " warn" : "");
  }
  async function loadIndex() {
    // The tag describes only the index held in memory; the server answers 304 when the retained
    // evidence is unchanged, which spares a 25 MB download, its parse, and a full re-render.
    const meta = { ifNoneMatch: state.index ? state.indexTag : "" };
    const index = await api("/v1/market/current", {}, meta);
    if (index === null && meta.status === 304) {
      // Without the server's clock the held index cannot be re-stamped honestly, so read it in full instead.
      if (!state.index || !meta.asOf) { state.indexTag = ""; return loadIndex(); }
      state.index.as_of = meta.asOf; state.syncedAt = Date.now();
      text("metric-asof", meta.asOf); renderDashboard(); return state.index;
    }
    if (!Array.isArray(index.sources) || !Array.isArray(index.observations) || !Array.isArray(index.snapshots) || index.catalog_records && !Array.isArray(index.catalog_records)) throw new Error("The retained index response has an unexpected shape. No new records were displayed.");
    state.index = index; state.indexTag = meta.etag; state.syncedAt = Date.now(); state.sources = index.sources || []; state.snapshots = index.snapshots || [];
    state.rows = (index.observations || []).filter((row) => !isFx(row) && !isModelMetadata(row) && hasPublishedPrice(row)).concat((index.catalog_records || []).filter((row) => !isFx(row) && !isModelMetadata(row) && hasPublishedPrice(row)).map((row) => ({ ...row, _catalog: true })));
    state.page = 0; renderIndex(); renderDashboard(); return index;
  }
  function metric(container, label, value) { const card = element("div", undefined, "result-metric"); card.append(element("span", label), element("strong", value ?? EMPTY)); container.append(card); }
  // Display helpers. They change presentation only: retained values stay exact in tooltips and evidence packets.
  const SOURCE_NAMES = { aws_public_pricing: "AWS public pricing", azure: "Azure", ecb: "ECB", getdeploying: "GetDeploying", huggingface: "Hugging Face", huggingface_catalog: "Hugging Face catalog", openrouter: "OpenRouter" };
  function sourceKey(id) { return String(id ?? "").replace(/^source:/, ""); }
  function sourceName(id) { const key = sourceKey(id); return SOURCE_NAMES[key] || key.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase()); }
  function utcStamp(value) {
    if (typeof value !== "string" || !value) return EMPTY;
    const zoned = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : value + "Z";
    const time = Date.parse(zoned.replace(/(\.\d{3})\d+/, "$1"));
    return Number.isFinite(time) ? new Date(time).toISOString().slice(0, 16).replace("T", " ") + " UTC" : value;
  }
  // Split a plain decimal at its point so a column of rates aligns on the point. The digits are never rounded or reformatted.
  function amountNode(amount) {
    const parts = /^(-?\d+)(\.\d+)?$/.exec(amount); const node = element("span", undefined, "num");
    if (parts) node.append(element("span", parts[1], "num-int"), element("span", parts[2] || "", "num-frac"));
    else node.append(element("span", amount, "num-raw"));
    return node;
  }
  function setMetric(id, value, empty) { text(id, value); byId(id).classList.toggle("is-empty", empty); }
  function emptyBlock(title, detail) { const block = element("div", undefined, "empty-block"); block.append(element("strong", title), element("p", detail)); return block; }
  function skeletonFeed() { const row = element("div", undefined, "feed-health-row is-skeleton"); row.append(element("span", undefined, "skeleton mid"), element("span", undefined, "skeleton short")); return row; }
  function skeletonRow() { const row = element("tr"); ["mid", "short", "mid", "short"].forEach((width) => { const cell = element("td"); cell.append(element("span", undefined, "skeleton " + width)); row.append(cell); }); return row; }
  function renderRefreshState() {
    const report = state.refreshStatus; const paused = !byId("session-card").hidden;
    // "running" only says the scheduler loop is alive. A feed is being read only while a scope is in progress.
    const reading = report?.enabled && report.running && (report.scopes || []).some((scope) => scope.status === "in_progress");
    const mode = !report ? "idle" : !report.enabled ? "manual" : !report.running ? "stopped" : reading ? "running" : "automatic";
    text("overview-refresh-state", { idle: paused ? "Paused" : "Starting", manual: "Manual runtime", stopped: "Scheduler stopped", running: "Reading feeds", automatic: "Automatic reads" }[mode]);
    byId("overview-refresh-state").dataset.state = mode;
    if (!report) { text("auto-refresh-detail", "Automatic reads follow source permissions, freshness and cooldowns."); return; }
    const scopes = report.scopes || []; const failed = scopes.filter((scope) => scope.consecutive_failures > 0).length;
    text("auto-refresh-detail", report.enabled ? scopes.length + (scopes.length === 1 ? " configured scope" : " configured scopes") + " · " + failed + " with retry backoff. Reads are bounded and coalesced; vendor data stays on the backend." : "Automatic reads are disabled for this runtime. The retained index remains available.");
  }
  function renderDashboard() {
    const clock = byId("dashboard-clock");
    if (state.index?.as_of) { const stamp = element("time", utcStamp(state.index.as_of)); stamp.setAttribute("datetime", state.index.as_of); stamp.setAttribute("title", state.index.as_of); clock.replaceChildren(element("span", "Index as of"), stamp); }
    else clock.replaceChildren(element("span", "Local / indicative analysis"));
    // Without an index the workspace is either still opening (placeholders) or paused (an explicit prompt).
    const opening = !state.index && byId("session-card").hidden;
    const retained = state.sources.reduce((total, source) => { const latest = sourceLatest(source); return total + latest.count + latest.catalog; }, 0);
    setMetric("overview-records", state.index ? retained.toLocaleString("en-US") : EMPTY, !state.index);
    text("overview-record-detail", state.index ? state.rows.length.toLocaleString("en-US") + " native price records loaded · overlapping scopes retained" : "Waiting for the retained index");
    const admitted = state.sources.filter((source) => source.can_attempt_read);
    setMetric("overview-feeds", state.index ? admitted.length : EMPTY, !state.index);
    const stale = state.sources.filter((source) => sourceLatest(source).scopes.some((scope) => scope.stale));
    text("overview-feed-detail", state.index ? stale.length + (stale.length === 1 ? " feed" : " feeds") + " with stale scopes · " + state.sources.filter((source) => !source.can_attempt_read).length + " held" : "Permissions and freshness checked per scope");
    const health = byId("overview-feed-health"); health.replaceChildren();
    admitted.forEach((source) => {
      const latest = sourceLatest(source); const isStale = latest.scopes.some((scope) => scope.stale); const row = element("div", undefined, "feed-health-row");
      const name = element("strong", sourceName(source.source_id), "feed-name"); name.setAttribute("title", source.source_id);
      const meta = element("small", latest.captured ? "Captured " + utcStamp(latest.captured) : "Awaiting first successful capture", "feed-meta"); if (latest.captured) meta.setAttribute("title", latest.captured);
      const description = element("div"); description.append(name, meta);
      row.append(description, element("span", !latest.captured ? "Awaiting" : isStale ? "Stale scope" : "Current", "feed-status " + (!latest.captured || isStale ? "warn" : "good"))); health.append(row);
    });
    if (!admitted.length) {
      if (opening) { for (let count = 0; count < 4; count++) health.append(skeletonFeed()); health.append(element("p", "Opening the local workspace…", "sr-only")); }
      else health.append(element("p", state.index ? "No feeds are admitted under the current source policy" : "Resume the workspace to read feed status", "empty-state"));
    }
    renderRefreshState();
    const pulse = byId("overview-market"); pulse.replaceChildren();
    const hardware = new Set(); const cohorts = aggregateRows().filter((record) => { const key = record.hardware.model + ":" + record.price.currency; if (hardware.has(key)) return false; hardware.add(key); return true; }).slice(0, 7);
    cohorts.forEach((record) => {
      const row = element("tr"); const price = currencyPrice(record); const months = record.extensions.reservation_months;
      const rate = element("td", undefined, "price-cell"); rate.append(amountNode(price.amount), element("span", " " + price.currency + " / GPU-hour", "num-unit"));
      const billing = record.extensions.billing_type.replaceAll("_", " ").toLowerCase(); const terms = element("td");
      terms.append(element("span", billing.charAt(0).toUpperCase() + billing.slice(1), "term-type"), element("span", " · " + (months === null ? "unspecified term" : months + (months === 1 ? " month" : " months")), "term-tenor"));
      const source = element("td", sourceName(record.source_id), "source-cell"); source.setAttribute("title", record.source_id);
      row.append(element("td", modelOf(record), "hardware-cell"), rate, terms, source); pulse.append(row);
    });
    if (!cohorts.length) {
      if (opening) { for (let count = 0; count < 5; count++) pulse.append(skeletonRow()); }
      else { const row = element("tr"); const cell = element("td", state.index ? "No current aggregate cohort passes the source and expiry gates. Inspect Markets for native prices and coverage." : "Resume the workspace to load current cohorts", "empty-state"); cell.setAttribute("colspan", "4"); row.append(cell); pulse.append(row); }
    }
    const groups = state.inventory?.summary?.by_unit_kind || {}; const kinds = Object.keys(groups);
    setMetric("overview-capacity", kinds.length === 1 ? groups[kinds[0]].total + " " + kinds[0] + " units" : kinds.length ? kinds.length + " capacity units" : state.inventory ? "None declared" : EMPTY, !kinds.length);
    text("overview-capacity-detail", state.inventory ? (state.inventoryDemo ? "Synthetic demo · " : "Declared paper ledger · ") + state.inventory.lots.length + " lots / " + state.inventory.sites.length + " sites" : "Load your physical inventory");
    const inventory = byId("overview-inventory"); inventory.replaceChildren();
    kinds.forEach((kind) => { const group = groups[kind]; metric(inventory, "Available · " + kind, group.available); metric(inventory, "Sold · " + kind, group.sold); metric(inventory, "Unsold · " + kind, group.unsold); metric(inventory, "Reserved / maintenance · " + kind, group.reserved + " / " + group.maintenance); });
    if (!kinds.length) inventory.append(emptyBlock("No capacity declared", "Declare physical sites, lots and commitments in Inventory. Published offers do not become holdings."));
    const pricing = state.results.pricing;
    setMetric("overview-decision", pricing ? pricing.stale ? "Draft changed" : pricing.result.status || "Evaluated" : "Unevaluated", !pricing || pricing.stale);
    text("overview-decision-detail", pricing ? pricing.stale ? "Evaluate again before using the previous result" : pricing.result.pricing_provenance?.source_evidence_eligible === true && pricing.result.status !== "held" && pricing.result.bid?.submitted_limit !== null && pricing.result.bid?.submitted_limit !== undefined ? "Bid ceiling " + pricing.result.bid.submitted_limit + " " + (pricing.result.economics?.currency || "") + " / GPU-hour · indicative" : "Reference or held input · inspect decision breakdown" : "Commercial terms and evidence required");
  }
  async function loadRefreshStatus() {
    state.refreshStatus = await api("/v1/market/refresh/status"); renderRefreshState();
  }
  function coverageReason(code) {
    const reasons = { missing_subject_identity: "Declare the subject identity", missing_requirement_evidence: "Add supporting evidence", missing_value: "Supply the declared value", registered_unit_mismatch: "Supplied and registered units differ", whole_decimal_string_required: "Supply a whole number as an exact string", below_registered_bound: "Value is below the declared bound", above_registered_bound: "Value is above the declared bound", registered_boolean_required: "Supply an explicit true or false", registered_nonempty_string_required: "Supply a nonempty declaration", outside_registered_categories: "Value is outside the declared categories", exact_decimal_string_required: "Supply an exact decimal string", evidence_subject_mismatch: "Evidence describes a different or missing subject", not_applicable_requires_allowed_reviewed_reason_and_null_value: "N/A needs permission, a reviewed reason and no asserted value", missing_review_owner: "Identify the reviewer", missing_evidence_validity_interval: "Declare the evidence validity interval", evidence_not_yet_valid: "Evidence is not yet valid", expired_evidence_interval: "Evidence validity has expired", no_current_scope_matching_qualified_evidence: "Add current evidence matching the required subject, scope and use rights" };
    if (reasons[code]) return reasons[code];
    if (code.startsWith("evidence_status:")) return "Evidence remains " + code.split(":")[1];
    if (code.startsWith("scope_has_no_required_requirements:")) return "Add required entries for the selected path: " + code.split(":")[1];
    return code.replaceAll("_", " ");
  }
  function renderUnderwritingRows() {
    const container = byId("underwriting-groups"); container.replaceChildren();
    const query = byId("underwriting-query").value.trim().toLowerCase();
    const rows = state.underwritingRows.filter((row) => [row.title, row.group, row.requirement_id, row.status, row.owner_model, row.owning_path, ...(row.blockers || [])].filter(Boolean).join(" ").toLowerCase().includes(query));
    text("underwriting-count", rows.length + " / " + state.underwritingRows.length + " requirements");
    if (!rows.length) { container.append(element("p", state.underwritingRows.length ? "No requirements match this filter." : "No assessment or catalog loaded.", "empty-state")); return; }
    rows.forEach((row) => {
      const card = element("article", undefined, "requirement-row"); const heading = element("div", undefined, "section-heading");
      heading.append(element("strong", row.title || row.requirement_id), element("span", (row.status || "not_assessed").replaceAll("_", " "), "pill " + (row.status === "verified" ? "good" : !row.status || row.applicable === false ? "" : "warn")));
      card.append(heading, element("p", (row.group || "Custom") + " / " + row.requirement_id + " / " + (row.required ? "Required" : "Optional"), "muted"));
      if (row.description) card.append(element("p", row.description, "muted"));
      const subject = row.subject_id || row.subject_kind || "Subject not supplied";
      const owner = [row.owning_path, row.owner_model].filter(Boolean).join(" / ");
      card.append(element("p", "Subject: " + subject + (owner ? " · Owner: " + owner : ""), "field-help"));
      if (row.value !== undefined && row.value !== null) {
        const suppliedUnit = Object.prototype.hasOwnProperty.call(row, "supplied_unit") ? row.supplied_unit : row.unit;
        const value = typeof row.value === "object" ? "Composite value; inspect the complete report" : String(row.value);
        card.append(element("p", "Declared value: " + value + (suppliedUnit ? " " + suppliedUnit : ""), "field-help"));
        if (suppliedUnit !== row.unit) card.append(element("p", "Registered unit: " + (row.unit || "unitless") + " · Supplied unit differs; no conversion performed.", "requirement-blockers"));
      }
      if (row.blockers?.length) card.append(element("p", row.blockers.map(coverageReason).join(" · "), "requirement-blockers"));
      if (row.evidence_ids?.length) card.append(element("p", "Evidence: " + row.evidence_ids.join(" · "), "field-help"));
      container.append(card);
    });
  }
  function syncUnderwritingScopes() {
    try { const draft = JSON.parse(byId("underwriting-input").value); if (Array.isArray(draft.scopes)) underwritingScopeFields.forEach(({ scope, input }) => { input.checked = draft.scopes.includes(scope); }); } catch (_) { /* Preserve the explicit unfinished draft. */ }
  }
  function underwritingEdited() {
    syncUnderwritingScopes();
    text("underwriting-input-state", byId("underwriting-input").value.trim() ? "Draft changed. Assess explicitly; any displayed result belongs to the previous input." : "No input supplied.");
    if (!byId("underwriting-output").hidden) { text("underwriting-result-state", "Previous input"); byId("underwriting-result-state").className = "pill warn"; }
    setBusy(state.busy);
  }
  function renderUnderwritingScopes(options) {
    const container = byId("underwriting-scopes"); container.replaceChildren(); underwritingScopeFields = [];
    options.forEach((scope) => {
      const input = element("input"); input.type = "checkbox"; input.setAttribute("aria-label", "Assess " + scope);
      const labels = { resale: "Node resale", forward: "Forward delivery", securitization: "Receivable financing", hedging: "Hedging", inference: "Inference serving" };
      const label = element("label", labels[scope] || scope); label.append(input); container.append(label); underwritingScopeFields.push({ scope, input });
      input.addEventListener("change", () => {
        try {
          const draft = safeEditableJson(byId("underwriting-input").value);
          if (!Array.isArray(draft.scopes) || draft.scopes.some((value) => typeof value !== "string") || new Set(draft.scopes).size !== draft.scopes.length) throw new Error("Correct malformed or duplicate scope values before using path controls.");
          draft.scopes = [...draft.scopes.filter((value) => !options.includes(value)), ...underwritingScopeFields.filter(({ input: field }) => field.checked).map(({ scope: value }) => value)];
          byId("underwriting-input").value = JSON.stringify(draft, null, 2); underwritingEdited(); readFields("underwriting");
        } catch (error) { underwritingEdited(); notify(error.message, true); }
      });
    });
    syncUnderwritingScopes();
  }
  function renderUnderwriting(result) {
    if (!Array.isArray(result.rows) || !result.summary || typeof result.assessment_hash !== "string") throw new Error("Unexpected coverage response. No assessment was displayed.");
    state.underwritingRows = result.rows; const summary = byId("underwriting-summary"); summary.replaceChildren();
    metric(summary, "Required variables", result.summary.required_total); metric(summary, "Current qualifying declarations", result.summary.required_covered);
    metric(summary, "Required evidence gaps", result.summary.required_blocked); metric(summary, "Explicitly not applicable", result.summary.required_not_applicable);
    text("underwriting-result-state", result.status === "held" ? "Evidence gaps" : "Declared coverage complete"); byId("underwriting-result-state").className = "pill " + (result.status === "held" ? "warn" : "good");
    if (result.versions?.requirements) text("underwriting-catalog-version", "Assessed requirements " + result.versions.requirements);
    summary.append(element("p", "Coverage does not establish accuracy, commercial suitability, calibration or execution authority.", "result-provenance"));
    const globalGaps = (result.blockers || []).filter((row) => row.requirement_id === null).flatMap((row) => row.reasons || []);
    if (globalGaps.length) summary.append(element("p", globalGaps.map(coverageReason).join(" · "), "result-blockers"));
    if (result.warnings?.includes("extensions_retained_in_input_hash_but_not_used_in_assessment")) summary.append(element("p", "Additional fields were retained in the input hash and excluded from coverage checks. Register a typed requirement to assess them.", "result-provenance"));
    byId("underwriting-output").textContent = JSON.stringify(result, null, 2); byId("underwriting-output").hidden = false;
    renderUnderwritingRows(); text("underwriting-input-state", "Assessed the submitted requirements and evidence. Changes require another assessment.");
  }
  function moneyMetric(container, label, value, currency) { metric(container, label, value === null || value === undefined ? null : String(value) + " " + (currency || "(currency not returned)")); }
  function hasUnresolved(value) {
    if (value && typeof value === "object") return Object.values(value).some(hasUnresolved);
    return !/^-?0(?:\.0+)?$/.test(String(value));
  }
  function renderEvaluation(kind, envelope) {
    const result = envelope.result || envelope; state.results[kind] = { result, stale: false }; renderDashboard(); const summary = byId(kind + "-summary"); summary.replaceChildren();
    text(kind + "-result-state", result.status || "Scenario calculated");
    byId(kind + "-result-state").className = "pill " + (result.status === "held" ? "warn" : "good");
    const blockers = result.hold_reasons || result.blockers || [];
    if (kind === "pricing") {
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
    } else if (kind === "inference") {
      metric(summary, "Allocated GPUs · full calendar cost", result.local?.allocated_gpu_count); moneyMetric(summary, "GPU cost including idle", result.local?.gpu_cost_including_idle, result.local?.currency);
      metric(summary, "Qualified whole-deployment request capacity", result.local?.request_capacity); moneyMetric(summary, "Local expected contribution", result.local?.expected_contribution, result.local?.currency);
      moneyMetric(summary, "Routed upstream token & route-fee cost", result.routed_comparison?.cost, result.local?.currency); moneyMetric(summary, "Routed all-in cost · explicit operating items", result.routed_comparison?.all_in_cost, result.local?.currency);
      moneyMetric(summary, "Required-margin floor · per declared task", result.pricing_diagnostics?.task_floors?.required_margin_sell_tick, result.local?.currency);
      metric(summary, "Local/routed whole-request crossover", result.pricing_diagnostics?.break_even?.whole_request_threshold);
      metric(summary, "Crossover / qualified capacity", result.pricing_diagnostics?.break_even?.threshold_utilization); metric(summary, "Price diagnostics", result.pricing_diagnostics?.status);
      moneyMetric(summary, "Supplier GPU ceiling · expected economics only", result.pricing_diagnostics?.supplier_buy_ceiling?.required_margin_buy_tick_ceiling, result.local?.currency);
      if (result.pricing_diagnostics?.blockers?.length) summary.append(element("p", "Price diagnostics: " + result.pricing_diagnostics.blockers.join(" · "), "result-provenance"));
      if (result.pricing_diagnostics?.break_even?.blockers?.length) summary.append(element("p", "Crossover: " + result.pricing_diagnostics.break_even.blockers.join(" · "), "result-provenance"));
    } else if (kind === "portfolio") {
      moneyMetric(summary, "Operating contribution · before financing", result.economics?.expected_contribution, result.economics?.currency);
      moneyMetric(summary, "Economic profit · before financing", result.economics?.economic_profit, result.economics?.currency);
      moneyMetric(summary, "Unallocated supply cost", result.economics?.unallocated_supply_cost, result.economics?.currency);
      moneyMetric(summary, "Shared minimum free cash", result.cash?.minimum_free_cash, result.economics?.currency);
      metric(summary, "Routes reconciled", result.routes?.length); metric(summary, "Firm eligibility", result.firm_price_eligible ? "Review response" : "Indicative / held");
    } else {
      moneyMetric(summary, "Minimum unrestricted free cash", result.minimum_free_cash, result.currency); metric(summary, "Minimum free cash date", result.minimum_free_cash_date);
      moneyMetric(summary, "Minimum funding headroom", result.minimum_headroom, result.currency); metric(summary, "Final unresolved balances", result.unresolved_balances && !hasUnresolved(result.unresolved_balances) ? "Settled in declared scenario" : "Review required");
    }
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
    if (state.results[kind]) state.results[kind].stale = true; renderDashboard();
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
  async function liveReference() {
    const selectedModel = byId("live-model").value; const selectedTerms = byId("live-terms").value;
    if (!selectedModel || !selectedTerms) return;
    await runAction("Loading retained evidence for the selected cohort…", async () => {
      const index = await loadIndex(); const cohort = JSON.parse(selectedTerms);
      const term = { billing_type: cohort.billing_type, reservation_months: cohort.reservation_months };
      const rows = aggregateRows().filter((row) => row.hardware.model === selectedModel && row.price.currency === cohort.currency && row.extensions.billing_type === term.billing_type && row.extensions.reservation_months === term.reservation_months);
      if (!rows.length) throw new Error("No current admitted aggregate records remain for that model and term. Refresh source data or choose another cohort.");
      const rules = Object.create(null);
      rows.forEach((row) => {
        const source = state.sources.find((candidate) => candidate.source_id === row.source_id);
        const maxAge = Number(source?.max_age_s);
        if (!Number.isFinite(maxAge) || maxAge <= 0) throw new Error("Source freshness policy is missing. Supply an explicit reviewed policy in the editor.");
        rules[row.source_id] = { enabled: true, quality: "1", max_age_hours: String(maxAge / 3600), half_life_hours: String(maxAge / 3600) };
      });
      const asOf = index.as_of;
      if (!asOf) throw new Error("The market index did not provide a current as-of timestamp.");
      const packet = { market: { request_id: "workbench-reference-" + crypto.randomUUID(), as_of: asOf, observations: rows, policy: { policy_id: "workbench-exploration", version: "0.1.0", model_version: "inverse-linear/1.0.0", registry_version: "1.0.0", effective_at: asOf, parameters: { benchmark: { estimator: "weighted_median", max_source_share: "1", max_provider_share: "1", min_observations: 1, min_sources: 1, min_provider_groups: 1, source_rules: rules } } } }, target: { scope: "aggregate_reference", currency: cohort.currency, hardware_model: selectedModel, country_code: null, configuration: {}, gpu_count: "1", duration_hours: "1", aggregate_terms: term }, commercial: null, extensions: { workbench_mode: "live_source_global_reference", policy_basis: "uncalibrated_exploration_weights_one_gpu_hour_reference_no_physical_capacity" } };
      const saved = state.policySaved && !state.policyDirty ? state.policySaved : null;
      if (saved) packet.market.policy = structuredClone(saved.document.policy);
      packet.pricing_provenance = { mode: saved && rows.every(row => typeof row.snapshot_id === "string" && /^[0-9a-f]{64}$/.test(row.snapshot_id)) ? "retained_market" : "declared_scenario", policy_revision: saved && rows.every(row => typeof row.snapshot_id === "string" && /^[0-9a-f]{64}$/.test(row.snapshot_id)) ? saved.revision : null };
      state.synthetic = false; byId("pricing-input").value = JSON.stringify(packet, null, 2); text("pricing-mode", saved ? "Retained evidence · saved policy / server gates apply" : "Retained source · scenario awaiting saved policy"); readFields("pricing"); showView("pricing");
      const raw = byId("pricing-input").value;
      renderEvaluation("pricing", await api("/v1/pricing/evaluate", { method: "POST", body: raw }));
      if (byId("pricing-input").value !== raw) inputChanged("pricing");
      notify(saved ? "Retained global evidence evaluated under the selected saved policy. Review server source gates; no physical capacity is asserted." : "Retained source observations explored as a scenario. Save and apply a current policy to bind evidence; no commercial bid or physical capacity is asserted.");
    });
  }
  const POLICY_FIELDS = [["policy_id", "policy-id"], ["version", "policy-version"], ["model_version", "policy-model-version"], ["registry_version", "policy-registry-version"], ["effective_at", "policy-effective"], ["expires_at", "policy-expiry"]];
  const BENCHMARK_FIELDS = [["estimator", "policy-estimator"], ["max_source_share", "policy-source-cap"], ["max_provider_share", "policy-provider-cap"], ["min_observations", "policy-min-observations"], ["min_sources", "policy-min-sources"], ["min_provider_groups", "policy-min-providers"]];
  const CAPACITY_STATES = ["available", "reserved", "sold", "maintenance", "unavailable"];
  function utcSelection() {
    if (byId("inventory-live").checked) return null;
    const value = byId("inventory-at").value.trim(); if (!value) return null;
    if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(value) || !Number.isFinite(Date.parse(value)) || new Date(value).toISOString().replace(".000Z", "Z") !== value) throw new Error("Enter a valid UTC instant in YYYY-MM-DDTHH:MM:SSZ format. Local timestamps are ambiguous.");
    return value;
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
      requirements: state.underwritingCatalog?.requirements || [],
      changed: (updated) => {
        byId(kind + "-input").value = updated;
        if (kind === "underwriting") { underwritingEdited(); syncUnderwritingScopes(); }
        else if (kind === "inventory") { setBusy(state.busy); text("inventory-time-help", "Unsaved inventory draft. Validate and save to update the map and positions."); }
        else inputChanged(kind);
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
    readFields(kind); if (!["inventory", "underwriting"].includes(kind)) inputChanged(kind); else setBusy(state.busy);
  }
  async function loadUnderwritingCatalog() {
    const template = await api("/v1/underwriting/template");
    if (!Array.isArray(template.requirements) || !template.request || !Array.isArray(template.scope_options)) throw new Error("Unexpected requirement catalog. Your draft was preserved.");
    state.underwritingCatalog = template; text("underwriting-catalog-version", "Requirements " + template.requirements_version);
    if (byId("underwriting-input").value.trim()) { renderUnderwritingScopes(template.scope_options); return; }
    const draft = structuredClone(template.request); draft.as_of = new Date().toISOString().replace(/\.\d{3}Z$/, "Z"); draft.request_id = "request:" + crypto.randomUUID();
    draft.subjects = Object.fromEntries([...new Set(template.requirements.map((requirement) => requirement.subject_kind))].map((kind) => [kind, null]));
    byId("underwriting-input").value = JSON.stringify(draft, null, 2); state.underwritingRows = template.requirements;
    renderUnderwritingRows(); renderUnderwritingScopes(template.scope_options); underwritingEdited(); readFields("underwriting");
  }
  function svgNode(tag, attributes = {}) { const node = document.createElementNS("http://www.w3.org/2000/svg", tag); Object.entries(attributes).forEach(([name, value]) => node.setAttribute(name, String(value))); return node; }
  function project(longitude, latitude) { return [(longitude + 180) * 960 / 360, (90 - latitude) * 460 / 180 + 20]; }
  function landPath(rings) {
    return rings.map((ring) => { let last = null; return ring.map((point, index) => { const xy = project(point[0], point[1]); const command = !index || last && Math.abs(xy[0] - last[0]) > 480 ? "M" : "L"; last = xy; return command + xy.map((coordinate) => coordinate.toFixed(2)).join(","); }).join(" ") + " Z"; }).join(" ");
  }
  function siteCapacityState(site) {
    const active = CAPACITY_STATES.filter((kind) => Object.values(site.by_unit_kind || {}).some((counts) => Number(counts[kind]) > 0));
    return active.length === 1 ? active[0] : active.length ? "mixed" : "unavailable";
  }
  function renderInventoryMap() {
    const map = byId("inventory-map"); map.replaceChildren();
    [-120, -60, 0, 60, 120].forEach((longitude) => { const x = project(longitude, 0)[0]; map.append(svgNode("line", { x1: x, x2: x, y1: 20, y2: 480, class: "map-grid" })); });
    [-60, -30, 0, 30, 60].forEach((latitude) => { const y = project(0, latitude)[1]; map.append(svgNode("line", { x1: 0, x2: 960, y1: y, y2: y, class: "map-grid" })); });
    (state.land?.features || []).forEach((feature) => {
      const geometry = feature.geometry; const polygons = geometry?.type === "Polygon" ? [geometry.coordinates] : geometry?.type === "MultiPolygon" ? geometry.coordinates : [];
      polygons.forEach((rings) => map.append(svgNode("path", { d: landPath(rings), class: "world-land" })));
    });
    const sites = state.inventory?.sites || []; let mapped = 0;
    sites.forEach((site) => {
      if (site.latitude === null || site.latitude === undefined || site.longitude === null || site.longitude === undefined) return;
      const latitude = Number(site.latitude); const longitude = Number(site.longitude);
      if (!Number.isFinite(latitude) || !Number.isFinite(longitude) || Math.abs(latitude) > 90 || Math.abs(longitude) > 180) return;
      mapped++; const [x, y] = project(longitude, latitude);
      const marker = svgNode("g", { class: "map-site-control", tabindex: "0", role: "button", "aria-label": (site.name || site.site_id) + ", " + siteCapacityState(site) + ". Select site to filter inventory." });
      const title = svgNode("title"); title.textContent = (site.name || site.site_id) + " / " + (site.country_code || "country unknown");
      marker.append(title, svgNode("circle", { cx: x, cy: y, r: 6, class: "map-hit-target", "aria-hidden": "true" }), svgNode("circle", { cx: x, cy: y, r: 6, class: "map-site " + siteCapacityState(site) + (state.inventorySite === site.site_id ? " selected" : ""), "aria-hidden": "true" }));
      const select = () => { state.inventorySite = site.site_id; state.selectedLot = (state.inventory?.lots || []).find((lot) => lot.site_id === site.site_id)?.lot_id || ""; renderInventory(); byId("lot-detail-title").focus({ preventScroll: true }); };
      marker.addEventListener("click", select); marker.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); select(); } }); map.append(marker);
      if (state.inventorySite === site.site_id) { const label = svgNode("text", { x: Math.min(850, x + 10), y: Math.max(15, y - 10), class: "map-site-label" }); label.textContent = site.name || site.site_id; map.append(label); }
    });
    byId("map-empty").hidden = sites.length > 0;
    text("inventory-map-state", state.inventory ? mapped + " located sites / " + (sites.length - mapped) + " unmapped" + (state.inventorySite ? " / selected: " + state.inventorySite : "") : "No site locations loaded.");
    byId("inventory-clear-site").hidden = !state.inventorySite;
  }
  function inventoryLots() {
    const query = byId("inventory-query").value.trim().toLowerCase(); const filter = byId("inventory-status").value;
    return (state.inventory?.lots || []).filter((lot) => (!state.inventorySite || lot.site_id === state.inventorySite) && (!query || [lot.lot_id, lot.site_id, lot.hardware_model, (state.inventory?.sites || []).find((site) => site.site_id === lot.site_id)?.name].join(" ").toLowerCase().includes(query)) && (!filter || Number(lot.counts?.[filter]) > 0));
  }
  function showInventoryLot(lotId) { state.selectedLot = lotId; state.inventorySite = state.inventory?.lots?.find((lot) => lot.lot_id === lotId)?.site_id || ""; renderInventory(); byId("lot-detail-title").focus({ preventScroll: true }); }
  function renderLotDetail() {
    const container = byId("lot-detail"); container.replaceChildren(); const lot = state.inventory?.lots?.find((record) => record.lot_id === state.selectedLot);
    text("lot-detail-state", lot ? lot.unit_kind : "No selection");
    if (!lot) { container.append(element("p", "Select a site marker or inventory row to inspect capacity and contract intervals.", "empty-state")); return; }
    const facts = element("dl", undefined, "lot-facts"); const site = state.inventory.sites.find((record) => record.site_id === lot.site_id);
    [["Lot", lot.lot_id], ["Hardware", lot.hardware_model || "not declared"], ["Site", site?.name || lot.site_id], ["Location", site?.latitude !== null && site?.latitude !== undefined && site?.longitude !== null && site?.longitude !== undefined ? site.latitude + ", " + site.longitude : "Unmapped / no coordinates declared"], ["Supply interval", lot.start_at + " → " + lot.end_at], ["Declared purchase value", lot.purchase_value ? lot.purchase_value.amount + " " + lot.purchase_value.currency + " / " + lot.purchase_value.unit : "not declared"]].forEach(([name, value]) => facts.append(element("dt", name), element("dd", value))); container.append(facts);
    const timeline = element("div", undefined, "lot-timeline"); timeline.append(element("strong", "Contract intervals", "small-label"));
    const start = Date.parse(lot.start_at); const end = Date.parse(lot.end_at); const instant = Date.parse(state.inventory.as_of);
    const range = element("div", undefined, "timeline-range"); range.append(element("span", lot.start_at), element("span", lot.end_at)); timeline.append(range);
    (state.inventory.timeline || []).filter((interval) => interval.lot_id === lot.lot_id).forEach((interval) => {
      const line = element("div", undefined, "timeline-line"); const caption = element("div"); caption.append(element("span", (interval.kind === "availability" ? "Supply window" : interval.kind) + " / " + interval.unit_ids.length + " " + lot.unit_kind, "capacity-status " + interval.kind), element("span", interval.position_id || "supply", "muted")); line.append(caption);
      const track = svgNode("svg", { viewBox: "0 0 300 13", class: "timeline-track", "aria-hidden": "true" });
      if (end > start) { const left = Math.max(0, (Date.parse(interval.start_at) - start) / (end - start) * 300); const right = Math.min(300, (Date.parse(interval.end_at) - start) / (end - start) * 300); if (right > left) track.append(svgNode("rect", { x: left.toFixed(3), y: "0", width: (right - left).toFixed(3), height: "13", class: "timeline-interval " + interval.kind })); const now = (instant - start) / (end - start) * 300; if (now >= 0 && now <= 300) track.append(svgNode("line", { x1: now.toFixed(3), x2: now.toFixed(3), y1: "0", y2: "13", class: "timeline-now" })); }
      line.append(track, element("p", interval.start_at + " → " + interval.end_at + (interval.active_at_as_of ? " / active at selected instant" : " / outside selected instant"), "muted")); timeline.append(line);
    }); container.append(timeline);
    const positions = lot.positions || []; positions.filter((position) => position.sale_value).forEach((position) => container.append(element("p", "Declared sale " + position.position_id + ": " + position.sale_value.amount + " " + position.sale_value.currency + " / " + position.sale_value.unit, "muted")));
    const details = element("details", undefined, "response-details"); details.append(element("summary", "Unit IDs & complete lot record"), element("pre", JSON.stringify(lot, null, 2))); container.append(details);
  }
  function renderInventory() {
    const inventory = state.inventory; const totals = byId("inventory-totals"); totals.replaceChildren();
    text("inventory-mode", inventory ? state.inventoryDemo ? "SYNTHETIC / not saved" : "Paper inventory / revision " + (inventory.revision ?? EMPTY) : "No inventory loaded"); byId("inventory-mode").className = "pill" + (state.inventoryDemo ? " warn" : "");
    text("inventory-demo", state.inventoryDemo ? "Exit synthetic demo" : "Load synthetic demo"); text("inventory-load", state.inventoryDemo ? "Re-evaluate demo at UTC" : "Load positions");
    const groups = Object.entries(inventory?.summary?.by_unit_kind || {});
    groups.forEach(([unit, counts]) => { const card = element("article", undefined, "inventory-total"); card.append(element("h2", unit + " / declared units")); const list = element("dl"); ["total", "unsold", "available", "reserved", "sold", "maintenance", "unavailable"].forEach((name) => { const pair = element("div"); pair.append(element("dt", name), element("dd", counts[name] ?? EMPTY)); list.append(pair); }); card.append(list); totals.append(card); });
    if (!groups.length) totals.append(element("p", "No declared capacity. Market offers do not become holdings automatically.", "empty-state"));
    renderInventoryMap(); renderLotDetail(); const body = byId("inventory-body"); body.replaceChildren(); const lots = inventoryLots();
    lots.forEach((lot) => { const row = element("tr", undefined, lot.lot_id === state.selectedLot ? "selected" : ""); const hardware = element("td", lot.lot_id); hardware.append(element("span", lot.hardware_model || "Hardware not declared", "subtext")); const site = inventory.sites.find((record) => record.site_id === lot.site_id); const place = element("td", site?.name || lot.site_id); place.append(element("span", site?.latitude === null || site?.latitude === undefined || site?.longitude === null || site?.longitude === undefined ? "Unmapped" : site.country_code || "country not declared", "subtext")); row.append(hardware, place); ["total", "available", "reserved", "sold", "maintenance"].forEach((kind) => row.append(element("td", (lot.counts?.[kind] ?? EMPTY) + " " + lot.unit_kind))); row.append(element("td", lot.active ? "Declared / active supply" : "Outside supply interval")); const button = element("button", "Select", "quiet-button"); button.setAttribute("aria-label", "Select inventory lot " + lot.lot_id); button.addEventListener("click", () => showInventoryLot(lot.lot_id)); const action = element("td"); action.append(button); row.append(action); body.append(row); });
    if (!lots.length) { const row = element("tr"); const cell = element("td", inventory?.lots?.length ? "No lots match the selected site and filters." : "No holdings loaded. Published market quotes are separate from inventory.", "empty-state"); cell.colSpan = 9; row.append(cell); body.append(row); }
    text("inventory-count", lots.length + " lots / " + (inventory?.lots?.length || 0) + " declared");
  }
  async function loadLand() {
    if (state.land) return;
    const epoch = state.epoch;
    try { const land = await request("/workbench/assets/world-land.json", {}, { authenticated: false }); if (land.type !== "FeatureCollection" || !Array.isArray(land.features)) throw new Error("Invalid map geometry"); state.land = land; renderInventoryMap(); }
    catch (error) { if (epoch !== state.epoch || /Stopped waiting|timed out/.test(error.message)) throw error; text("map-attribution", "Local land geometry unavailable. Declared site coordinates and the capacity table remain usable."); }
  }
  function acceptInventory(report, demo) {
    if (!report || !Array.isArray(report.lots) || !Array.isArray(report.sites) || !report.state || !report.summary?.by_unit_kind) throw new Error("Unexpected inventory response. No holdings were replaced.");
    state.inventorySite = report.sites.some((site) => site.site_id === state.inventorySite) ? state.inventorySite : ""; state.selectedLot = report.lots.some((lot) => lot.lot_id === state.selectedLot) ? state.selectedLot : "";
    state.inventory = report; state.inventoryDemo = demo; byId("inventory-at").value = report.as_of;
    byId("inventory-input").value = JSON.stringify(report.state, null, 2); byId("inventory-output").textContent = JSON.stringify(report, null, 2); byId("inventory-output").hidden = false; renderInventory(); renderDashboard(); readFields("inventory");
  }
  function syntheticInventory(asOf) {
    const instant = Date.parse(asOf); const stamp = (days) => new Date(instant + days * 86400000).toISOString().replace(".000Z", "Z");
    return { schema_version: "paper-inventory/1.0", provenance: "synthetic", sites: [{ site_id: "synthetic:north", name: "Synthetic North", country_code: "US", latitude: "41.9", longitude: "-87.6", extensions: { provenance: "independently_invented_synthetic_ui_demo_not_a_real_holding" } }, { site_id: "synthetic:west", name: "Synthetic West", country_code: "NL", latitude: "52.3", longitude: "4.9" }, { site_id: "synthetic:unmapped", name: "Synthetic / location withheld", latitude: null, longitude: null }], lots: [{ lot_id: "synthetic:gpu-a", site_id: "synthetic:north", unit_kind: "gpu", unit_ids: ["demo:a1", "demo:a2", "demo:a3", "demo:a4"], hardware_model: "Invented accelerator A", start_at: stamp(-7), end_at: stamp(21) }, { lot_id: "synthetic:node-b", site_id: "synthetic:west", unit_kind: "node", unit_ids: ["demo:b1", "demo:b2"], hardware_model: "Invented node bundle B", start_at: stamp(-7), end_at: stamp(21) }, { lot_id: "synthetic:gpu-c", site_id: "synthetic:unmapped", unit_kind: "gpu", unit_ids: ["demo:c1", "demo:c2"], hardware_model: "Invented accelerator C", start_at: stamp(-7), end_at: stamp(21) }], positions: [{ position_id: "demo:sale", lot_id: "synthetic:gpu-a", unit_ids: ["demo:a1", "demo:a2"], status: "sold", start_at: stamp(-1), end_at: stamp(7) }, { position_id: "demo:reservation", lot_id: "synthetic:gpu-a", unit_ids: ["demo:a3"], status: "reserved", start_at: stamp(0), end_at: stamp(10) }, { position_id: "demo:maintenance", lot_id: "synthetic:gpu-c", unit_ids: ["demo:c1"], status: "maintenance", start_at: stamp(-2), end_at: stamp(2) }] };
  }
  function policyEdited(controls = false) { state.policyDirty = true; if (controls) state.policyControlsDirty = true; text("policy-state", "Unsaved policy draft"); text("policy-feedback", state.policyControlsDirty ? "Control edits are not in the JSON yet. Choose Write controls to JSON, then validate and save the successor version." : "Changes need validation and a saved successor version before applying to pricing."); setBusy(state.busy); }
  function sourceRule(sourceId = "", rule = {}) {
    const card = element("div", undefined, "policy-source-rule"); const inputs = {};
    [["source_id", "Source ID", sourceId], ["quality", "Quality / declared weight", rule.quality ?? ""], ["max_age_hours", "Maximum age (hours)", rule.max_age_hours ?? ""], ["half_life_hours", "Recency half-life (hours)", rule.half_life_hours ?? ""]].forEach(([name, label, value]) => { const input = element("input"); input.type = "text"; input.value = value; input.setAttribute("aria-label", label); input.addEventListener("input", () => policyEdited(true)); inputs[name] = input; const field = element("label", label); field.append(input); card.append(field); });
    const enabled = element("input"); enabled.type = "checkbox"; enabled.checked = rule.enabled === true; enabled.addEventListener("change", () => policyEdited(true)); const label = element("label", "Enabled for benchmark", "source-enabled"); label.append(enabled); card.append(label); inputs.enabled = enabled;
    const remove = element("button", "Remove source", "quiet-button"); remove.addEventListener("click", () => { state.policyRows = state.policyRows.filter((row) => row.inputs !== inputs); card.remove(); policyEdited(true); }); card.append(remove); state.policyRows.push({ inputs, card }); byId("policy-source-rules").append(card);
  }
  function displayPolicy(document, entry = null) {
    if (!document?.policy || !document.policy.parameters?.benchmark || !Array.isArray(document.feature_definitions)) throw new Error("Supply a policy document with policy.parameters.benchmark and feature_definitions.");
    const policy = document.policy; const benchmark = policy.parameters.benchmark;
    POLICY_FIELDS.forEach(([name, id]) => { byId(id).value = policy[name] ?? ""; }); BENCHMARK_FIELDS.forEach(([name, id]) => { byId(id).value = benchmark[name] ?? ""; });
    state.policyRows = []; byId("policy-source-rules").replaceChildren(); Object.entries(benchmark.source_rules || {}).forEach(([id, rule]) => sourceRule(id, rule));
    const registry = byId("policy-feature-registry"); registry.replaceChildren(); document.feature_definitions.forEach((feature) => { const card = element("article", undefined, "feature-definition"); card.append(element("strong", feature.feature_id), element("code", feature.owning_path + " / " + feature.owner_model), element("p", "Type: " + feature.value_type + " / unit: " + (feature.unit || "none") + " / " + (feature.required ? "required" : "optional")), element("p", "Bounds: " + (feature.minimum ?? "unknown") + " → " + (feature.maximum ?? "unknown") + (feature.allowed_values?.length ? " / values: " + feature.allowed_values.join(", ") : "")), element("p", "Registered definition only. Pricing activation requires a supported qualified owning model.")); registry.append(card); });
    if (!document.feature_definitions.length) registry.append(element("p", "No custom feature definitions. Add typed definitions to the full JSON; unsupported critical factors will hold pricing.", "empty-state"));
    byId("policy-input").value = JSON.stringify(document, null, 2); state.policySaved = entry; state.policyDirty = !entry; state.policyControlsDirty = false;
    text("policy-state", entry ? policy.policy_id + " / " + policy.version : "Unsaved policy draft"); text("policy-feedback", entry ? "Saved revision " + entry.revision + ". Applying changes the pricing draft; evaluate it explicitly." : "Review source weights and gates, then validate and save a new version."); setBusy(state.busy);
  }
  function policyControlsDocument() {
    const document = safeEditableJson(byId("policy-input").value); if (!document.policy?.parameters?.benchmark) throw new Error("Read a complete policy JSON document into the controls first.");
    POLICY_FIELDS.forEach(([name, id]) => { document.policy[name] = byId(id).value.trim() || (name === "expires_at" ? null : ""); });
    const benchmark = document.policy.parameters.benchmark;
    BENCHMARK_FIELDS.forEach(([name, id]) => { const value = byId(id).value.trim(); if (name.startsWith("min_")) { if (!/^[1-9]\d*$/.test(value) || !Number.isSafeInteger(Number(value))) throw new Error("Minimum support counts must be positive safe integers."); benchmark[name] = Number(value); } else benchmark[name] = value; });
    benchmark.source_rules = Object.create(null); state.policyRows.forEach(({ inputs }) => { const id = inputs.source_id.value.trim(); if (!id || Object.prototype.hasOwnProperty.call(benchmark.source_rules, id)) throw new Error("Each source rule needs a unique source ID."); benchmark.source_rules[id] = { enabled: inputs.enabled.checked, quality: inputs.quality.value.trim(), max_age_hours: inputs.max_age_hours.value.trim(), half_life_hours: inputs.half_life_hours.value.trim() }; });
    return document;
  }
  async function readInventory(quiet = false) {
    const asOf = utcSelection();
    if (state.inventoryDemo) { acceptInventory(await api("/v1/inventory/evaluate", { method: "POST", body: JSON.stringify({ state: state.inventory.state, as_of: asOf || new Date().toISOString().replace(/\.\d{3}Z$/, "Z") }) }), true); }
    else acceptInventory(await api("/v1/inventory" + (asOf ? "?as_of=" + encodeURIComponent(asOf) : "")), false);
    await loadLand();
    text("inventory-time-help", (byId("inventory-live").checked ? "Following current UTC / last local read " : "Fixed selected instant / last local read ") + state.inventory.as_of + ". Declared-plan availability, not reconstructed historical observations.");
    if (!quiet) notify(state.inventoryDemo ? "Synthetic availability recalculated by the inventory validator. Nothing was saved." : "Declared paper inventory loaded at " + state.inventory.as_of + ". Market quotes remain separate.");
  }
  byId("inventory-load").addEventListener("click", () => runAction("Loading declared inventory at the selected UTC instant…", readInventory));
  byId("inventory-demo").addEventListener("click", () => {
    if (state.inventoryDemo) { state.inventory = null; state.inventoryDemo = false; state.inventorySite = ""; state.selectedLot = ""; byId("inventory-input").value = ""; byId("inventory-output").textContent = ""; byId("inventory-output").hidden = true; renderInventory(); setBusy(state.busy); notify("Synthetic demo cleared. Load stored positions to view declared inventory."); return; }
    return runAction("Validating the explicitly labelled synthetic demo…", async () => { const asOf = utcSelection() || new Date().toISOString().replace(/\.\d{3}Z$/, "Z"); const report = await api("/v1/inventory/evaluate", { method: "POST", body: JSON.stringify({ state: syntheticInventory(asOf), as_of: asOf }) }); acceptInventory(report, true); await loadLand(); notify("SYNTHETIC DEMO: invented sites, hardware and commitments. No inventory was persisted. Exit demo before importing declared holdings."); });
  });
  byId("inventory-save").addEventListener("click", () => runAction("Validating and saving declared paper inventory…", async () => {
    if (state.inventoryDemo) throw new Error("Synthetic demo cannot be saved from this view. Exit demo and load declared inventory before importing.");
    const raw = byId("inventory-input").value; JSON.parse(raw); const asOf = utcSelection();
    const current = state.inventory?.revision === null || state.inventory?.revision === undefined ? await api("/v1/inventory") : state.inventory;
    if (!Number.isSafeInteger(current.revision)) throw new Error("Current inventory revision is unavailable. Reload before importing.");
    const body = '{"expected_revision":' + current.revision + ',"state":' + raw + '}'; await api("/v1/inventory", { method: "PUT", body });
    const report = await api("/v1/inventory" + (asOf ? "?as_of=" + encodeURIComponent(asOf) : "")); const currentDraft = byId("inventory-input").value; acceptInventory(report, false);
    if (currentDraft !== raw) { byId("inventory-input").value = currentDraft; text("inventory-time-help", "Submitted packet saved. The editor changed while saving and still contains an unsaved draft; the map shows the saved revision."); }
    notify("Declared inventory saved with an immutable revision. No booking, lease, trade or payment was placed.");
  }));
  ["inventory-query", "inventory-status"].forEach((id) => byId(id).addEventListener("input", renderInventory));
  byId("inventory-input").addEventListener("input", () => setBusy(state.busy));
  byId("inventory-at").addEventListener("input", () => text("inventory-time-help", "Changed UTC draft. Choose " + (state.inventoryDemo ? "Re-evaluate demo" : "Load positions") + " to recalculate availability."));
  byId("inventory-live").addEventListener("change", () => { setBusy(state.busy); text("inventory-time-help", byId("inventory-live").checked ? "Following current UTC. Local inventory reloads every minute while this pane is open and the inventory editor is unchanged." : "Fixed UTC instant. Edit the timestamp, then load positions to evaluate this declared plan; automatic reads are paused."); });
  byId("inventory-clear-site").addEventListener("click", () => { state.inventorySite = ""; renderInventory(); });
  byId("policy-load").addEventListener("click", () => runAction("Loading immutable policy versions…", async () => {
    const result = await api("/v1/policies"); if (!Array.isArray(result.entries) || !Array.isArray(result.source_catalog)) throw new Error("Unexpected policy catalog response.");
    state.policyEntries = result.entries; state.policyCatalog = result.source_catalog;
    const catalog = byId("policy-source-catalog"); catalog.replaceChildren(); result.source_catalog.forEach((source) => { const row = element("div", undefined, "feature-definition"); row.append(element("strong", source.source_id), element("p", (source.normalization || source.role || "scope not returned") + " / rights: " + (source.rights_status || "unknown") + " / " + (source.can_attempt_read ? "read eligible" : "read held"))); catalog.append(row); });
    const select = byId("policy-select"); select.replaceChildren(element("option", result.entries.length ? "Choose a saved policy version" : "No saved versions / supply a policy JSON")); select.firstChild.value = "";
    result.entries.forEach((entry) => { const option = element("option", entry.policy_id + " / " + entry.version); option.value = entry.revision; select.append(option); });
    if (!result.entries.length) { text("policy-state", "No saved policy"); text("policy-feedback", "Supply a complete versioned policy JSON. No weights or risk parameters are inserted automatically."); }
    notify("Loaded " + result.entries.length + " saved versions and " + result.source_catalog.length + " configured sources" + (result.truncated ? ". The policy catalog is bounded; earlier versions may be omitted." : ". Choose a version or supply a new policy packet."));
  }));
  byId("policy-select").addEventListener("change", () => runAction("Loading the selected saved policy…", async () => { const revision = byId("policy-select").value; state.policySaved = null; state.policyDirty = true; if (!revision) return; const entry = await api("/v1/policies/" + encodeURIComponent(revision)); displayPolicy(entry.document, entry); byId("policy-output").textContent = JSON.stringify(entry, null, 2); byId("policy-output").hidden = false; }));
  byId("policy-template").addEventListener("click", () => runAction("Loading an explicitly unvalidated policy template…", async () => { const document = await request("/workbench/assets/synthetic-policy-document.json", {}, { authenticated: false }); displayPolicy(document); text("policy-state", "SYNTHETIC / unvalidated template"); notify("Loaded an invented, unvalidated policy template. Review every rule, assign a new policy ID/version, and validate before saving. No source permissions or factor price effects were granted."); }));
  byId("policy-read-json").addEventListener("click", () => { try { displayPolicy(safeEditableJson(byId("policy-input").value)); notify("Read the policy JSON into editable controls. This is an unsaved, unvalidated draft."); } catch (error) { notify(error.message, true); } });
  byId("policy-update-json").addEventListener("click", () => { try { byId("policy-input").value = JSON.stringify(policyControlsDocument(), null, 2); state.policyControlsDirty = false; policyEdited(); notify("Wrote explicit controls to the policy JSON. Review registry, critical fields and notes before saving."); } catch (error) { notify(error.message, true); } });
  byId("policy-add-source").addEventListener("click", () => { if (!byId("policy-input").value.trim()) { notify("Supply a complete policy document first.", true); return; } sourceRule(); policyEdited(true); });
  byId("policy-save").addEventListener("click", () => runAction("Validating and saving a new policy version…", async () => {
    if (state.policyControlsDirty) throw new Error("Write controls to JSON before saving so the submitted version includes your control edits.");
    const raw = byId("policy-input").value; const draft = JSON.parse(raw); if (!draft.policy?.policy_id) throw new Error("Policy ID is required.");
    const validation = await api("/v1/policies/validate", { method: "POST", body: '{"document":' + raw + '}' });
    const previous = state.policyEntries.find((entry) => entry.policy_id === draft.policy.policy_id);
    const entry = await api("/v1/policies", { method: "POST", body: '{"expected_revision":' + JSON.stringify(previous?.revision || null) + ',"document":' + raw + '}' });
    state.policyEntries = [entry, ...state.policyEntries.filter((candidate) => candidate.revision !== entry.revision)];
    if (byId("policy-input").value === raw) displayPolicy(entry.document, entry); else { state.policySaved = entry; policyEdited(); text("policy-feedback", "Submitted version saved, but the current draft changed while saving. Reload its saved version before applying."); }
    byId("policy-output").textContent = JSON.stringify({ validation, saved: entry }, null, 2); byId("policy-output").hidden = false;
    const option = element("option", entry.policy_id + " / " + entry.version); option.value = entry.revision; byId("policy-select").append(option); byId("policy-select").value = entry.revision;
    notify("Policy version saved. Source quality, recency and concentration settings remain declared assumptions; registry definitions do not activate unsupported price factors.");
  }));
  byId("policy-apply").addEventListener("click", () => runAction("Checking the original pricing draft before applying the saved policy…", async () => {
    if (!state.policySaved || state.policyDirty) throw new Error("Save or load an immutable policy version before applying."); const saved = state.policySaved; const raw = byId("pricing-input").value; safeEditableJson(raw);
    const parsed = await api("/v1/requests/parse", { method: "POST", body: raw }); if (byId("pricing-input").value !== raw) throw new Error("Pricing draft changed while it was being checked. Retry the explicit apply action on the current draft."); if (state.policySaved !== saved || state.policyDirty) throw new Error("Policy draft changed during the check. Save or reload the intended version before applying.");
    const draft = parsed.request; if (!draft?.market || typeof draft.market !== "object" || Array.isArray(draft.market)) throw new Error("Supply a pricing request with a market packet first."); const document = saved.document; draft.market.policy = structuredClone(document.policy); draft.pricing_provenance = { mode: Array.isArray(draft.market.observations) && draft.market.observations.length > 0 && draft.market.observations.every(row => typeof row.snapshot_id === "string" && /^[0-9a-f]{64}$/.test(row.snapshot_id)) ? "retained_market" : "declared_scenario", policy_revision: Array.isArray(draft.market.observations) && draft.market.observations.length > 0 && draft.market.observations.every(row => typeof row.snapshot_id === "string" && /^[0-9a-f]{64}$/.test(row.snapshot_id)) ? saved.revision : null }; draft.extensions = { ...(draft.extensions || {}), policy_registry_document: { revision: saved.revision, feature_definitions: document.feature_definitions, notes: document.notes } }; byId("pricing-input").value = JSON.stringify(draft, null, 2); inputChanged("pricing"); text("pricing-mode", "Saved policy applied / evaluate this draft"); showView("pricing"); notify("Applied saved policy " + document.policy.policy_id + " / " + document.policy.version + " to the draft. Evaluate explicitly; registered features remain subject to model activation gates.");
  }));
  [...POLICY_FIELDS, ...BENCHMARK_FIELDS].forEach(([, id]) => byId(id).addEventListener("input", () => policyEdited(true))); byId("policy-input").addEventListener("input", () => policyEdited());
  byId("underwriting-template").addEventListener("click", () => runAction("Loading the versioned requirement catalog…", loadUnderwritingCatalog));
  byId("underwriting-assess").addEventListener("click", async () => {
    const raw = byId("underwriting-input").value; if (!raw.trim()) return;
    try {
      const draft = JSON.parse(raw);
      if (!Array.isArray(draft?.scopes) || !draft.scopes.length) { notify("Select at least one path to assess, or declare scopes in the request.", true); return; }
    } catch (_) { text("underwriting-input-state", "Invalid JSON. No assessment request was sent."); notify("Correct the assessment JSON before submitting.", true); return; }
    await runAction("Assessing declared evidence coverage…", async () => {
      renderUnderwriting(await api("/v1/underwriting/assess", { method: "POST", body: raw }));
      if (byId("underwriting-input").value !== raw) underwritingEdited();
      notify("Coverage assessed for the submitted version only. Inspect evidence gaps and the complete report before using the financial models.");
    });
  });
  byId("underwriting-input").addEventListener("input", underwritingEdited);
  byId("underwriting-query").addEventListener("input", renderUnderwritingRows);
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
  byId("reload-index").addEventListener("click", () => runAction("Reloading the retained index…", async () => { await loadIndex(); notify("Retained index reloaded. No vendor request was made."); }));
  byId("refresh-market").addEventListener("click", async () => {
    const ids = state.sources.filter((source) => source.can_attempt_read).map((source) => source.source_id);
    if (!ids.length) { notify("No source is currently admitted for read. Review source rights, schema, credentials and configured coverage.", true); return; }
    await runAction("Reading " + ids.length + " admitted sources in configured scopes…", async () => {
      const result = await api("/v1/market/refresh", { method: "POST", body: JSON.stringify({ source_ids: ids }) }); await loadIndex();
      const updated = result.updated?.length ?? 0; const held = result.held?.length ?? 0; const failed = result.failed?.length ?? 0;
      notify("Feed read completed: " + updated + " scopes updated, " + held + " held, " + failed + " failed. " + (held || failed ? "Inspect source admission and last-attempt details before retrying." : "Review each source's coverage and timestamps."), Boolean(held || failed));
    });
  });
  ["record-query", "source-filter", "region-filter", "kind-filter", "record-sort"].forEach((id) => byId(id).addEventListener("input", () => { state.page = 0; renderRows(); }));
  byId("model-query").addEventListener("input", () => renderModelDiscovery(state.index));
  byId("reset-filters").addEventListener("click", () => { ["record-query", "source-filter", "region-filter", "kind-filter"].forEach((id) => { byId(id).value = ""; }); state.page = 0; renderRows(); byId("record-query").focus(); });
  byId("previous-page").addEventListener("click", () => { state.page--; renderRows(); }); byId("next-page").addEventListener("click", () => { state.page++; renderRows(); });
  byId("close-detail").addEventListener("click", () => { byId("record-detail").hidden = true; byId("record-detail-json").textContent = ""; if (state.detailOrigin?.isConnected) state.detailOrigin.focus(); else byId("market-title").focus(); state.detailOrigin = null; });
  byId("pricing-open-market").addEventListener("click", () => { showView("market"); byId("reference-title").scrollIntoView({ block: "center" }); });
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
  ["pricing", "inference", "cash", "portfolio"].forEach((kind) => { byId("evaluate-" + kind).addEventListener("click", () => evaluate(kind)); byId(kind + "-input").addEventListener("input", () => inputChanged(kind)); });
  byId("live-model").addEventListener("change", renderLiveTerms); byId("live-terms").addEventListener("change", () => setBusy(state.busy)); byId("evaluate-live-reference").addEventListener("click", liveReference);
  ["market", "inventory", "underwriting", "pricing", "portfolio"].forEach((kind) => byId("overview-open-" + kind).addEventListener("click", () => showView(kind)));
  ["pricing", "inference", "cash", "inventory", "underwriting", "portfolio"].forEach((kind) => {
    byId(kind + "-read-fields").addEventListener("click", () => { try { readFields(kind); } catch (error) { notify(error.message, true); } });
    byId(kind + "-new-draft").addEventListener("click", () => runAction("Preparing a blank input contract…", async () => {
      // This explicit reset action changes the draft, never stored inventory or evidence.
      const reset = () => { byId(kind + "-input").value = ""; state.forms.get(kind)?.clear(); };
      if (kind === "underwriting") { reset(); await loadUnderwritingCatalog(); }
      else if (kind === "portfolio") { const template = await api("/v1/portfolio/template"); reset(); createBlankDraft(kind, template.request); }
      else { reset(); createBlankDraft(kind); }
    }));
  });
  window.addEventListener("pagehide", () => clearSession(""));
  const SYNC_INTERVAL = 60000;
  function synchronize() {
    // A hidden tab has nobody to show the result to, so it neither polls nor holds the busy lock.
    if (!state.session || state.busy || document.hidden) return;
    return runAction("Synchronizing retained evidence…", async () => {
      await loadIndex(); await loadRefreshStatus();
      if (state.inventory && !state.inventoryDemo && byId("inventory-live").checked && byId("inventory-input").value === JSON.stringify(state.inventory.state, null, 2)) await readInventory(true);
      renderDashboard();
    });
  }
  setInterval(synchronize, SYNC_INTERVAL);
  document.addEventListener("visibilitychange", () => { if (!document.hidden && Date.now() - state.syncedAt >= SYNC_INTERVAL) return synchronize(); });
  setBusy(false);
  renderInventory(); renderDashboard();
  window.addEventListener("load", () => { openRoutedView(); return startWorkspace(); });
  window.ComputeHost = Object.freeze({
    api, element, byId, notify, showView, priceQuote, isSession: () => state.session,
    onView: (listener) => { viewListeners.push(listener); }, onSession: (listener) => { sessionListeners.push(listener); },
  });
})();
