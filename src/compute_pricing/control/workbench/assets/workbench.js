(() => {
  "use strict";
  const byId = (id) => document.getElementById(id);
  const state = { session: false, csrf: "", refreshStatus: null, results: {}, forms: new Map(), epoch: 0, index: null, rows: [], sources: [], snapshots: [], page: 0, synthetic: false, busy: false, action: null, controllers: new Map(), detailOrigin: null, inventory: null, inventoryDemo: false, inventorySite: "", selectedLot: "", land: null, policyEntries: [], policyCatalog: [], policyRows: [], policySaved: null, policyDirty: true, policyControlsDirty: false, underwritingRows: [], underwritingCatalog: null };
  state.demoContract = null; state.demoFields = new Map(); state.demoSynthetic = false; state.demoResult = null;
  state.commitmentCurves = null; state.selectedCurveNode = null;
  const DISPLAY_SOURCES = new Set(["getdeploying", "ecb", "energinet_day_ahead"]);
  const SOURCE_LABELS = { getdeploying: "GetDeploying", ecb: "ECB", energinet_day_ahead: "Energinet" };
  const PAGE_SIZE = 100;
  const EMPTY = "—";
  let underwritingScopeFields = [];
  let sessionHandshake = null;
  let cookieRevocation = Promise.resolve();
  let darkMode = window.matchMedia?.("(prefers-color-scheme: dark)").matches === true;
  function applyTheme() {
    document.documentElement.setAttribute("data-theme", darkMode ? "dark" : "light");
    byId("theme-toggle").setAttribute("aria-pressed", String(darkMode));
    text("theme-toggle", darkMode ? "Light mode" : "Dark mode");
  }
  applyTheme();
  byId("theme-toggle").addEventListener("click", () => { darkMode = !darkMode; applyTheme(); });

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
    byId("demo-load-sample").disabled = busy || !state.session || !state.demoContract?.sample;
    byId("demo-evaluate").disabled = busy || !state.session || !state.demoFields.size;
    byId("demo-clear").disabled = busy || !state.demoFields.size;
    byId("market-compare-deal").disabled = busy || !state.session;
    ["curve-model", "curve-group"].forEach(id => { byId(id).disabled = busy || !state.session; });
  }
  function showView(name, focus = true) {
    ["dashboard", "market", "inventory", "underwriting", "pricing", "policy", "inference", "cash", "portfolio"].forEach((view) => { byId(view + "-view").hidden = view !== name; });
    document.querySelectorAll("[data-view]").forEach((button) => {
      const selected = button.dataset.view === name;
      button.classList.toggle("active", selected);
      if (selected) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current");
    });
    byId("workspace-tools").open = false;
    if (focus) byId(name + "-title").focus({ preventScroll: true });
  }
  function abortRequests(reason) {
    state.controllers.forEach((request, controller) => { request.reason = reason; controller.abort(); });
  }
  function clearSession(message = "Session ended. Received data and drafts were cleared.") {
    state.epoch++; abortRequests("session"); state.action = null; state.session = false; state.csrf = ""; state.results = {}; state.forms.forEach((editor) => editor.clear()); state.forms.clear(); state.index = null; state.rows = []; state.sources = []; state.snapshots = []; state.synthetic = false; state.page = 0;
    state.demoFields.clear(); state.demoContract = null; state.demoSynthetic = false; state.demoResult = null; state.commitmentCurves = null; state.selectedCurveNode = null;
    byId("demo-primary-fields").replaceChildren(); byId("demo-additional-fields").replaceChildren(); resetDemoResults(); renderMarketMvp();
    byId("session-card").hidden = false; byId("disconnect").hidden = true;
    byId("session-dot").classList.remove("connected"); text("session-state", "Workspace paused");
    ["pricing", "inference", "cash", "portfolio", "inventory", "underwriting"].forEach((kind) => byId(kind + "-fields").replaceChildren());
    ["pricing", "inference", "cash", "portfolio"].forEach((kind) => {
      byId(kind + "-input").value = ""; byId(kind + "-output").textContent = ""; byId(kind + "-output").hidden = true;
      byId(kind + "-summary").replaceChildren(element("p", "Connect and supply an explicit scenario to evaluate.", "empty-state"));
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
  async function request(path, options = {}, { authenticated = true, timeout = 30000, format = "json" } = {}) {
    if (authenticated && !state.session) throw new Error("Resume the local workspace before requesting data.");
    const epoch = state.epoch;
    const controller = new AbortController();
    const pending = { epoch, reason: null }; state.controllers.set(controller, pending);
    const timer = setTimeout(() => { pending.reason = "timeout"; controller.abort(); }, timeout);
    try {
      const writes = !["GET", "HEAD"].includes(options.method || "GET");
      const headers = { ...(authenticated && writes ? { "X-Compute-CSRF": state.csrf } : {}), ...(options.body ? { "Content-Type": "application/json" } : {}) };
      const response = await fetch(path, { ...options, headers, credentials: "same-origin", cache: "no-store", redirect: "error", signal: controller.signal });
      const data = format === "text" ? await response.text() : await response.json().catch(() => null);
      if (epoch !== state.epoch || authenticated && !state.session) throw new Error("The session ended while this request was running. Received data was discarded.");
      if (controller.signal.aborted) { const error = new Error("Request aborted"); error.name = "AbortError"; throw error; }
      if (!response.ok) {
        if (response.status === 401) { const failure = new Error("Session expired. Resume the workspace; no mutation was retried."); failure.status = 401; throw failure; }
        const detail = typeof data?.detail === "string" ? data.detail : typeof data?.detail?.code === "string" ? data.detail.code : "Request rejected";
        if (response.status === 403 && detail === "browser_csrf_required") { const failure = new Error("Workspace protection token requires renewal; no mutation was retried."); failure.code = detail; throw failure; }
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
  async function renewSession() {
    const generation = state.epoch;
    await cookieRevocation;
    if (generation !== state.epoch) throw new Error("Session setup was superseded.");
    const pending = sessionHandshake;
    if (pending) {
      try { await pending.done; } catch (error) { if (pending.generation === generation) throw error; }
      if (generation !== state.epoch) throw new Error("Session setup was superseded.");
      if (pending.generation === generation) return;
    }
    const handshake = { generation, done: null };
    handshake.done = (async () => {
      const response = await request("/v1/session/bootstrap", { method: "POST", body: "{}" }, { authenticated: false });
      if (generation !== state.epoch) throw new Error("Session setup was superseded.");
      if (response.auth_mode !== "local_session" || typeof response.csrf_token !== "string" || !response.csrf_token) throw new Error("Invalid workspace session response.");
      state.csrf = response.csrf_token; state.session = true;
      byId("session-card").hidden = true; byId("disconnect").hidden = false;
      text("session-state", "Workspace ready"); byId("session-dot").classList.add("connected");
    })();
    sessionHandshake = handshake;
    try { await handshake.done; } finally { if (sessionHandshake === handshake) sessionHandshake = null; }
  }
  async function api(path, options = {}) {
    const limits = { timeout: path === "/v1/market/refresh" ? 120000 : 30000 };
    try { return await request(path, options, limits); }
    catch (error) {
      if (error.status !== 401 && error.code !== "browser_csrf_required") throw error;
      await renewSession();
      if (!["GET", "HEAD"].includes(options.method || "GET")) throw new Error("Workspace resumed. Check the draft and retry; no mutation was retried. Unsaved inputs are preserved.");
      return request(path, options, limits);
    }
  }
  async function openWorkspace() {
    if (state.busy) return;
    await runAction("Opening local workspace…", async () => {
      const generation = state.epoch;
      try {
        await renewSession(); await loadIndex();
        const results = await Promise.allSettled([loadRefreshStatus(), readInventory(true), loadUnderwritingCatalog(), loadDemoContract()]);
        if (generation !== state.epoch || !state.session) return;
        const errors = results.filter((row) => row.status === "rejected");
        if (errors.length) notify(errors.map((row) => row.reason.message).join(" · "), true);
        for (const kind of ["pricing", "inference", "cash"]) if (!byId(kind + "-input").value.trim()) newBlankDraft(kind);
        renderDashboard();
      } catch (error) {
        if (generation === state.epoch) { clearSession(""); text("session-help", error.message); }
        throw error;
      }
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
    const index = await api("/v1/demo/market");
    if (!Array.isArray(index.sources) || !Array.isArray(index.observations) || !Array.isArray(index.snapshots) || index.catalog_records && !Array.isArray(index.catalog_records)) throw new Error("The retained index response has an unexpected shape. No new records were displayed.");
    state.index = index; state.sources = index.sources || []; state.snapshots = index.snapshots || [];
    state.commitmentCurves = index.commitment_curves || null;
    if (index.refresh_operations) state.refreshStatus = index.refresh_operations;
    state.rows = (index.observations || []).filter((row) => !isFx(row) && !isModelMetadata(row) && hasPublishedPrice(row)).concat((index.catalog_records || []).filter((row) => !isFx(row) && !isModelMetadata(row) && hasPublishedPrice(row)).map((row) => ({ ...row, _catalog: true })));
    state.page = 0; renderIndex(); renderDashboard(); renderMarketMvp(); return index;
  }
  function chartText(svg, x, y, value, anchor = "start") {
    const label = svgNode("text", { x, y, "text-anchor": anchor, class: "chart-label" }); label.textContent = value; svg.append(label);
  }
  function curveGroups() { return (state.commitmentCurves?.groups || []).filter(group => DISPLAY_SOURCES.has(group.cohort?.source_id)); }
  function selectedCurveGroup() { return curveGroups()[Number(byId("curve-group").value)] || null; }
  function renderCurveGroups() {
    const model = byId("curve-model").value; const select = byId("curve-group"); const previous = select.value; select.replaceChildren();
    curveGroups().forEach((group, index) => {
      const cohort = group.cohort;
      if (cohort.hardware?.model !== model) return;
      const option = element("option", cohort.currency + " · " + cohort.billing_type.replaceAll("_", " ").toLowerCase() + " · week " + cohort.week_start); option.value = String(index); select.append(option);
    });
    if (select.children.length === 0) { const option = element("option", "No current comparable cohort"); option.value = ""; select.append(option); }
    else if ([...select.children].some(option => option.value === previous)) select.value = previous;
    else {
      const preferred = curveGroups().findIndex(group => group.cohort.hardware?.model === model && group.cohort.billing_type === "RESERVATION" && group.nodes.filter(node => node.status === "observed_reference").length > 1);
      if (preferred >= 0) select.value = String(preferred);
    }
    state.selectedCurveNode = null; renderCommitmentChart();
  }
  function renderCommitmentChart() {
    const svg = byId("commitment-chart"); svg.replaceChildren(); const chips = byId("curve-nodes"); chips.replaceChildren();
    const group = selectedCurveGroup(); const cohort = group?.cohort; const nodes = group?.nodes || [];
    const points = nodes.filter(node => node.status === "observed_reference" && node.rate_per_gpu_hour !== null && Number.isFinite(Number(node.rate_per_gpu_hour)));
    byId("curve-empty").hidden = points.length > 0;
    text("curve-unit", cohort ? cohort.currency + " / GPU-hour" : "Native currency / GPU-hour");
    text("curve-caption", cohort ? SOURCE_LABELS[cohort.source_id] + " · global advertised provider median · week " + cohort.week_start + ". Configuration and regional fit require separate evidence." : "Each point preserves its source, billing term and observation week.");
    if (points.length) {
      // Floating point is used only for SVG pixel positions; exact server decimals remain the labels.
      const maxTerm = Math.max(1, ...points.map(node => node.reservation_months || 0));
      const minRate = Math.min(...points.map(node => Number(node.rate_per_gpu_hour))); const maxRate = Math.max(...points.map(node => Number(node.rate_per_gpu_hour)));
      const spread = Math.max(maxRate - minRate, Math.abs(maxRate) * .12, .01); const bottom = Math.max(0, minRate - spread * .25); const top = maxRate + spread * .25;
      const x = term => 68 + term / maxTerm * 620; const y = rate => 242 - (rate - bottom) / (top - bottom) * 210;
      for (let i = 0; i < 4; i++) { const yy = 32 + i * 70; svg.append(svgNode("line", {x1:68, x2:688, y1:yy, y2:yy, class:"chart-grid"})); chartText(svg, 56, yy + 4, (top - i / 3 * (top - bottom)).toFixed(2), "end"); }
      [...new Set(points.map(node => node.reservation_months || 0))].forEach(term => chartText(svg, x(term), 271, term ? term + " mo" : "Unspecified term", "middle"));
      points.forEach(node => {
        const circle = svgNode("circle", {cx:x(node.reservation_months || 0), cy:y(Number(node.rate_per_gpu_hour)), r:6, class:"chart-point", tabindex:"0", role:"button", "aria-label":(node.reservation_months === null ? "Unspecified term" : node.reservation_months + " months") + ": " + node.rate_per_gpu_hour + " " + cohort.currency + " per GPU-hour"});
        const title = svgNode("title", {}); title.textContent = (node.reservation_months === null ? "Unspecified term" : node.reservation_months + " months") + " · " + node.rate_per_gpu_hour + " " + cohort.currency + " / GPU-hour"; circle.append(title);
        circle.addEventListener("click", () => selectCurveNode(node)); circle.addEventListener("keydown", event => { if (["Enter", " "].includes(event.key)) { event.preventDefault(); selectCurveNode(node); } }); svg.append(circle);
      });
    }
    nodes.forEach(node => {
      const tenor = node.reservation_months === null ? "Unspecified term" : node.reservation_months + " months";
      const chip = element("button", undefined, "curve-node" + (node.status === "held" ? " held" : "")); chip.type = "button";
      chip.append(element("span", tenor), element("strong", node.rate_per_gpu_hour === null ? "Conflicting marks" : node.rate_per_gpu_hour + " " + cohort.currency));
      chip.disabled = node.status !== "observed_reference"; chip.addEventListener("click", () => selectCurveNode(node)); chips.append(chip);
    });
    state.selectedCurveNode = points.find(node => node.reservation_months === 12) || points.find(node => node.reservation_months === 6) || points.find(node => node.reservation_months !== null) || points[0] || null; renderSelectedReference();
  }
  function selectCurveNode(node) { state.selectedCurveNode = node; renderSelectedReference(); }
  function renderSelectedReference() {
    const container = byId("market-selected-reference"); container.replaceChildren(); const node = state.selectedCurveNode; const cohort = selectedCurveGroup()?.cohort;
    if (!node || !cohort) { container.append(element("p", "No current mark selected. You can still evaluate a fully declared scenario.")); return; }
    container.append(element("strong", node.rate_per_gpu_hour + " " + cohort.currency + " / GPU-hour"), element("p", cohort.hardware.model + " · " + (node.reservation_months === null ? "unspecified term" : node.reservation_months + " month average")), element("small", SOURCE_LABELS[cohort.source_id] + " · captured " + (node.references?.[0]?.captured_at || "unknown") + " · observed week " + cohort.week_start));
  }
  function renderMarketMvp() {
    const groups = curveGroups(); const select = byId("curve-model"); const previous = select.value;
    selection(select, groups.map(group => group.cohort.hardware.model), "Choose hardware");
    if (!select.value && groups.length) {
      const multi = groups.filter(group => group.cohort.billing_type === "RESERVATION" && group.nodes.filter(node => node.status === "observed_reference").length > 1);
      select.value = (multi.find(group => /H100/i.test(group.cohort.hardware.model)) || multi[0] || groups[0]).cohort.hardware.model;
    }
    renderCurveGroups();
    const sources = state.sources.filter(source => DISPLAY_SOURCES.has(source.source_id)); const health = byId("market-feed-health"); health.replaceChildren();
    text("market-source-count", sources.length + " feeds");
    sources.forEach(source => {
      const latest = sourceLatest(source); const stale = latest.scopes.some(scope => scope.stale); const row = element("div", undefined, "feed-health-row"); const name = element("div");
      name.append(element("strong", SOURCE_LABELS[source.source_id]), element("small", latest.captured ? "Captured " + latest.captured : "Awaiting first retained capture"));
      row.append(name, element("span", !latest.captured ? "Awaiting" : stale ? "Stale" : "Current", "pill " + (!latest.captured || stale ? "warn" : "good"))); health.append(row);
    });
    if (!sources.length) health.append(element("p", state.session ? "No public display source is currently returned." : "Opening the local workspace…", "muted"));
    const operations = state.index?.refresh_operations || state.refreshStatus; const scopes = operations?.scopes || operations?.automatic?.scopes || [];
    const reading = scopes.some(scope => DISPLAY_SOURCES.has(scope.source_id) && scope.in_progress === true);
    text("market-read-status", reading ? "Source read in progress" : "Backend refreshes approved feeds automatically");
    text("market-data-state", state.index ? "Retained public references" : "Opening workspace");
    text("market-asof", state.index?.as_of ? "View updated " + state.index.as_of : "Awaiting current evidence");
    const context = byId("market-context-data"); context.replaceChildren();
    const records = (state.index?.catalog_records || []).concat(state.index?.fx_records || []);
    const fx = records.find(record => record.source_id === "ecb" && isFx(record) && (record.quote_currency === "USD" || record.currency === "USD")) || records.find(record => record.source_id === "ecb" && isFx(record));
    if (fx) context.append(element("p", "1 " + (fx.base_currency || "EUR") + " = " + (fx.quote_per_base ?? fx.rate ?? EMPTY) + " " + (fx.quote_currency || fx.currency) + " · " + (fx.observed_date || fx.observed_at || "date unknown")));
    const energy = records.filter(record => record.source_id === "energinet_day_ahead");
    if (energy.length) context.append(element("p", energy.length + " retained wholesale electricity intervals. Native currencies / MWh, delivery area and timestamps remain in the reference records; these are not an all-in compute cost."));
    if (!fx && !energy.length) context.append(element("p", "No retained FX or electricity context is available in this view.", "muted"));
  }
  async function loadDemoContract() {
    const contract = await api("/v1/demo/contract");
    if (!Array.isArray(contract.fields) || !contract.fields.length) throw new Error("Scenario intake metadata is unavailable. No assumptions were inserted.");
    state.demoContract = contract; state.demoFields.clear(); byId("demo-primary-fields").replaceChildren(); byId("demo-additional-fields").replaceChildren();
    contract.fields.forEach(field => {
      if (!/^[a-z_]+(?:\.[a-z_]+)?$/.test(field.name) || !["decimal", "utc", "date"].includes(field.type) || state.demoFields.has(field.name)) throw new Error("Invalid scenario field metadata.");
      const label = element("label", field.label, "demo-field" + (field.type === "utc" ? " wide" : "")); const input = element("input"); input.id = "demo-field-" + field.name.replaceAll(".", "-"); input.type = field.type === "date" ? "date" : "text"; input.required = true; input.autocomplete = "off"; input.value = "";
      if (field.type === "decimal") input.inputMode = "decimal";
      if (field.type === "utc") input.placeholder = "YYYY-MM-DDTHH:MM:SSZ";
      input.setAttribute("aria-label", field.label); label.append(input);
      if (field.type === "decimal" && ["billed_utilization", "collection_share", "required_margin", "fee_on_collected", "fee_on_gross"].includes(field.name)) label.append(element("small", "Fraction from 0 to 1; enter 0.20 for 20%."));
      input.addEventListener("input", demoEdited); state.demoFields.set(field.name, input);
      byId(field.group === "primary" ? "demo-primary-fields" : "demo-additional-fields").append(label);
    });
    text("demo-form-help", "USD scenario · actual UTC delivery hours · margin on gross billings. Start with your terms or load the labeled invented deal."); setBusy(state.busy);
  }
  function demoPacket() {
    const packet = { payment_dates: {} };
    state.demoFields.forEach((input, name) => { const value = input.value.trim(); if (!value) { byId("demo-assumptions").open = true; input.focus(); throw new Error("Supply " + (state.demoContract.fields.find(field => field.name === name)?.label || name) + ". Unknown inputs remain empty."); } const parts = name.split("."); if (parts.length === 2) packet.payment_dates[parts[1]] = value; else packet[name] = value; });
    return packet;
  }
  function demoEdited() {
    text("demo-scenario-mode", state.demoSynthetic ? "Edited invented scenario" : "Declared scenario");
    if (state.demoResult) { text("demo-result-state", "Previous input"); byId("demo-result-state").className = "pill warn"; }
    setBusy(state.busy);
  }
  function resetDemoResults() {
    byId("demo-results").replaceChildren(element("p", "Supply your terms to see the purchase ceiling, selling floor and dated cash.", "empty-state"));
    byId("demo-cash-chart").replaceChildren(); byId("demo-cash-empty").hidden = false; byId("demo-cash-blocker").hidden = true; byId("demo-cash-blocker").textContent = "";
    byId("demo-cost-breakdown").replaceChildren(); byId("demo-provenance").replaceChildren(); text("demo-cash-caption", "Unrestricted cash · actual supplier price"); text("demo-result-state", "Not evaluated"); byId("demo-result-state").className = "pill";
    byId("demo-output").textContent = ""; byId("demo-output").hidden = true; text("demo-scenario-mode", "Declared scenario");
  }
  function presentExactDecimal(value, { places = 2, shift = 0, roundUp = false } = {}) {
    if (value === null || value === undefined) return EMPTY;
    const parsed = /^(-?)(\d+)(?:\.(\d+))?$/.exec(String(value));
    if (!parsed) return String(value);
    const negative = parsed[1] === "-"; const fraction = parsed[3] || "";
    let units = BigInt(parsed[2] + fraction); const discardedPlaces = fraction.length - places - shift;
    if (discardedPlaces > 0) {
      const divisor = 10n ** BigInt(discardedPlaces); const remainder = units % divisor; units /= divisor;
      if (roundUp ? !negative && remainder > 0n : remainder * 2n >= divisor) units += 1n;
    } else units *= 10n ** BigInt(-discardedPlaces);
    const digits = units.toString().padStart(places + 1, "0");
    const whole = (places ? digits.slice(0, -places) : digits).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    return (negative && units !== 0n ? "-" : "") + whole + (places ? "." + digits.slice(-places) : "");
  }
  function demoMoneyMetric(container, label, value, currency, roundUp = false) {
    const card = element("div", undefined, "result-metric"); const formatted = presentExactDecimal(value, {roundUp}); const amount = element("strong", formatted === EMPTY ? EMPTY : formatted + " " + currency);
    if (value !== null && value !== undefined) amount.setAttribute("title", "Exact: " + value + " " + currency);
    card.append(element("span", label), amount); container.append(card);
  }
  function renderDemoCash(schedule) {
    const svg = byId("demo-cash-chart"); svg.replaceChildren(); const days = schedule?.days || [];
    const valid = days.filter(day => Number.isFinite(Number(day.free_cash)) && Number.isFinite(Number(day.minimum_ordered_free_cash)));
    byId("demo-cash-empty").hidden = valid.length > 0;
    if (!valid.length) return;
    const values = valid.flatMap(day => [Number(day.free_cash), Number(day.minimum_ordered_free_cash)]); const floor = schedule.minimum_cash_floor === null || schedule.minimum_cash_floor === undefined ? null : Number(schedule.minimum_cash_floor);
    if (floor !== null && Number.isFinite(floor)) values.push(floor);
    const low = Math.min(0, ...values); const high = Math.max(0, ...values); const spread = high - low || 1;
    const x = i => 65 + i / Math.max(1, valid.length - 1) * 624; const y = value => 196 - (value - low) / spread * 160;
    for (let i = 0; i < 3; i++) { const value = low + spread * i / 2; svg.append(svgNode("line", {x1:65,x2:689,y1:y(value),y2:y(value),class:"chart-grid"})); chartText(svg, 54, y(value) + 4, value.toFixed(0), "end"); }
    [["free_cash", "chart-cash"], ["minimum_ordered_free_cash", "chart-trough"]].forEach(([field, css]) => {
      svg.append(svgNode("polyline", { points:valid.map((day, i) => x(i) + "," + y(Number(day[field]))).join(" "), class:css, fill:"none" }));
    });
    if (floor !== null && Number.isFinite(floor)) { const rule = svgNode("line", {x1:65,x2:689,y1:y(floor),y2:y(floor),class:"chart-floor"}); const title = svgNode("title", {}); title.textContent = "Minimum cash floor: " + schedule.minimum_cash_floor + " " + schedule.currency; rule.append(title); svg.append(rule); }
    valid.forEach((day, i) => { const point = svgNode("circle", {cx:x(i),cy:y(Number(day.free_cash)),r:3,class:"chart-point"}); const title = svgNode("title", {}); title.textContent = day.on + " · end-of-day " + day.free_cash + " " + schedule.currency + " · ordered minimum " + day.minimum_ordered_free_cash; point.append(title); svg.append(point); });
    [0, Math.floor((valid.length - 1) / 2), valid.length - 1].filter((index, i, all) => all.indexOf(index) === i).forEach(index => chartText(svg, x(index), 224, valid[index].on, index === 0 ? "start" : index === valid.length - 1 ? "end" : "middle"));
  }
  function renderDemoResult(envelope) {
    const result = envelope.result || envelope; state.demoResult = result; const currency = result.economics?.currency || "USD"; const grid = byId("demo-results"); grid.replaceChildren();
    moneyMetric(grid, "Scenario purchase ceiling / GPU-hour", result.cash_constraint?.tested_purchase_tick, currency);
    moneyMetric(grid, "Scenario selling floor / GPU-hour", result.ask?.sell_floor_tick, currency);
    demoMoneyMetric(grid, "Profit at your supplier price", result.economics?.economic_profit, currency);
    demoMoneyMetric(grid, "Additional opening cash required", result.cash_constraint?.supplied_ask_required_extra_cash, currency, true);
    text("demo-result-state", "Scenario calculated"); byId("demo-result-state").className = "pill";
    const blocker = byId("demo-cash-blocker"); blocker.hidden = result.cash_constraint?.supplied_ask_cash_feasible !== false;
    blocker.textContent = "Positive profit can still require funding before buyer receipts arrive. This supplier price needs the additional opening cash shown above.";
    const schedule = result.scenario_supplier_cash_schedule || result.cash_constraint?.selected_schedule;
    text("demo-cash-caption", (result.scenario_supplier_cash_schedule ? "At your supplier price" : "At scenario purchase ceiling") + " · " + currency + " · solid: end-of-day / dashed: ordered minimum" + (schedule?.minimum_cash_floor !== null && schedule?.minimum_cash_floor !== undefined ? " / dotted: cash floor" : "")); renderDemoCash(schedule);
    const breakdown = byId("demo-cost-breakdown"); breakdown.replaceChildren();
    for (const [label, value] of [["Gross billings", result.economics?.gross_billings], ["Expected collections", result.economics?.expected_collections], ["Economic costs", result.economics?.economic_cost], ["Fees", result.economics?.fees], ["Capital charge", result.economics?.capital_charge]]) { const row = element("div", undefined, "demo-cost-row"); const formatted = presentExactDecimal(value); const amount = element("strong", formatted === EMPTY ? EMPTY : formatted + " " + currency); if (value !== null && value !== undefined) amount.setAttribute("title", "Exact: " + value + " " + currency); row.append(element("span", label), amount); breakdown.append(row); }
    const margin = result.economics?.economic_margin; const percent = presentExactDecimal(margin, {shift:2}); const marginRow = element("div", undefined, "demo-cost-row"); const marginValue = element("strong", percent === EMPTY ? EMPTY : percent + "%");
    if (margin !== null && margin !== undefined) marginValue.setAttribute("title", "Exact margin fraction: " + margin);
    marginRow.append(element("span", "Economic margin / " + (result.economics?.margin_basis === "gross_billings" ? "gross billings" : result.economics?.margin_basis || "basis unknown")), marginValue); breakdown.append(marginRow);
    const provenance = byId("demo-provenance"); provenance.replaceChildren(element("p", "Declared scenario with a hypothetical reference. The purchase ceiling is a model diagnostic; the actual submitted bid remains held and unavailable. No trade or inventory change is made.", "field-help"));
    if (result.hold_reasons?.length) provenance.append(element("p", "Evidence holds: " + result.hold_reasons.join(" · "), "field-help"));
    byId("demo-output").textContent = JSON.stringify(envelope, null, 2); byId("demo-output").hidden = false;
  }
  function metric(container, label, value) { const card = element("div", undefined, "result-metric"); card.append(element("span", label), element("strong", value ?? EMPTY)); container.append(card); }
  function renderDashboard() {
    const index = state.index;
    text("dashboard-clock", index ? "Index as of " + index.as_of : "Local analysis");
    let retained = 0;
    const admitted = state.sources.filter((source) => source.can_attempt_read);
    const health = byId("overview-feed-health"); health.replaceChildren();
    let staleFeeds = 0;
    for (const source of state.sources) {
      const latest = sourceLatest(source); retained += latest.count + latest.catalog;
      const stale = latest.scopes.some((scope) => scope.stale);
      if (stale) staleFeeds++;
      if (!source.can_attempt_read) continue;
      const row = element("div", undefined, "feed-health-row"); const description = element("div");
      description.append(element("strong", source.source_id.replace(/^source:/, "").replaceAll("_", " ")), element("small", latest.captured ? "Captured " + latest.captured : "No successful capture"));
      row.append(description, element("span", !latest.captured ? "Awaiting" : stale ? "Stale scope" : "Current", "pill " + (stale || !latest.captured ? "warn" : "good"))); health.append(row);
    }
    if (!admitted.length) health.append(element("p", index ? "No source is admitted under the current policy." : "Opening workspace…", "empty-state"));
    text("overview-records", index ? retained.toLocaleString("en-US") : EMPTY);
    text("overview-record-detail", index ? state.rows.length.toLocaleString("en-US") + " native price records loaded · overlapping scopes retained" : "Awaiting retained evidence");
    text("overview-feeds", index ? admitted.length : EMPTY);
    text("overview-feed-detail", index ? staleFeeds + (staleFeeds === 1 ? " feed" : " feeds") + " with stale scopes · " + (state.sources.length - admitted.length) + " held" : "Source permissions checked per scope");
    const pulse = byId("overview-market"); pulse.replaceChildren(); const displayed = new Set(); let rows = 0;
    for (const record of aggregateRows()) {
      const identity = record.hardware.model + ":" + record.price.currency;
      if (displayed.has(identity)) continue;
      displayed.add(identity); const native = currencyPrice(record); const months = record.extensions.reservation_months;
      const tenor = months === null ? "unspecified term" : months + (months === 1 ? " month" : " months");
      const row = element("tr"); row.append(element("td", modelOf(record)), element("td", native.amount + " " + native.currency + " / GPU-hour", "price-cell"), element("td", record.extensions.billing_type.replaceAll("_", " ").toLowerCase() + " · " + tenor), element("td", record.source_id.replace(/^source:/, ""), "muted")); pulse.append(row);
      if (++rows === 7) break;
    }
    if (!rows) { const row = element("tr"); const cell = element("td", "No current aggregate cohort passes the admission and freshness gates. Explore native records in Markets.", "empty-state"); cell.setAttribute("colspan", "4"); row.append(cell); pulse.append(row); }
    const groups = state.inventory?.summary?.by_unit_kind || {}; const kinds = Object.keys(groups);
    text("overview-capacity", !state.inventory ? EMPTY : !kinds.length ? "None declared" : kinds.length === 1 ? groups[kinds[0]].total + " " + kinds[0] + " units" : kinds.length + " capacity units");
    text("overview-capacity-detail", state.inventory ? (state.inventoryDemo ? "Synthetic demo · " : "Declared paper ledger · ") + state.inventory.lots.length + " lots / " + state.inventory.sites.length + " sites" : "Physical inventory remains explicit");
    const holdings = byId("overview-inventory"); holdings.replaceChildren();
    for (const [unit, counts] of Object.entries(groups)) { metric(holdings, "Available · " + unit, counts.available); metric(holdings, "Sold · " + unit, counts.sold); metric(holdings, "Unsold · " + unit, counts.unsold); metric(holdings, "Reserved / maintenance · " + unit, counts.reserved + " / " + counts.maintenance); }
    if (!kinds.length) holdings.append(element("p", "Declare physical units and intervals in Inventory. Published listings are separate evidence.", "empty-state"));
    const decision = state.results.pricing;
    text("overview-decision", !decision ? "Unevaluated" : decision.stale ? "Draft changed" : decision.result.status || "Evaluated");
    text("overview-decision-detail", !decision ? "Evaluate supplied terms and evidence" : decision.stale ? "The displayed result belongs to previous input" : decision.result.pricing_provenance?.source_evidence_eligible === true && decision.result.status !== "held" && decision.result.bid?.submitted_limit != null ? "Indicative bid ceiling " + decision.result.bid.submitted_limit + " " + (decision.result.economics?.currency || "") + " / GPU-hour" : "Reference or held input · inspect the breakdown");
  }
  async function loadRefreshStatus() {
    const status = await api("/v1/market/refresh/status"); state.refreshStatus = status;
    const scopes = status.scopes || [];
    text("overview-refresh-state", status.running ? "Reading feeds" : status.enabled ? "Automatic" : "Manual runtime");
    text("auto-refresh-detail", status.enabled ? scopes.length + " configured scopes · " + scopes.filter((scope) => scope.consecutive_failures > 0).length + " with retry backoff. Vendor reads are bounded and coalesced." : "Automatic vendor reads are disabled. Retained evidence remains available.");
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
      const scenarioOnly = result.pricing_provenance?.source_evidence_eligible !== true;
      const benchmarkDisplay = scenarioOnly ? result.scenario_diagnostics?.benchmark || result.benchmark : result.benchmark;
      moneyMetric(summary, scenarioOnly ? "Scenario reference · evidence not bound" : result.benchmark?.cohort?.scope === "aggregate_reference" ? "Advertised global reference · per GPU-hour" : "Comparable reference · per GPU-hour", benchmarkDisplay?.price, benchmarkDisplay?.currency || benchmarkDisplay?.cohort?.currency);
      moneyMetric(summary, "Submitted purchase limit · per GPU-hour", result.pricing_provenance?.source_evidence_eligible === true && result.status !== "held" ? result.bid?.submitted_limit : null, currency);
      moneyMetric(summary, scenarioOnly ? "Scenario sell floor · per GPU-hour" : "Required-margin sell floor · per GPU-hour", result.ask?.sell_floor_tick, currency);
      moneyMetric(summary, scenarioOnly ? "Scenario profit at supplied supplier ask" : "Economic profit at supplied supplier ask", result.economics?.economic_profit, currency);
      moneyMetric(summary, scenarioOnly || result.status === "held" ? "Scenario free cash · candidate calculation" : "Minimum free cash at selected bid", result.cash_constraint?.minimum_free_cash, currency);
      moneyMetric(summary, "Extra cash required at supplier ask", result.cash_constraint?.supplied_ask_required_extra_cash, currency);
      if (result.cash_constraint?.supplied_ask_cash_feasible === false) summary.append(element("div", "The supplied supplier ask has a funding shortfall. A positive modeled profit does not make that purchase cash-feasible.", "result-blockers"));
      if (scenarioOnly) summary.append(element("p", "These are scenario diagnostics. Bind exact retained observations to a current saved policy; source rights and freshness are checked again by the service. No purchase recommendation is available.", "result-provenance"));
    } else if (kind === "inference") {
      metric(summary, "Allocated GPUs · full calendar cost", result.local?.allocated_gpu_count); moneyMetric(summary, "GPU cost including idle", result.local?.gpu_cost_including_idle, result.local?.currency);
      metric(summary, "Qualified whole-deployment request capacity", result.local?.request_capacity); moneyMetric(summary, "Local expected contribution", result.local?.expected_contribution, result.local?.currency);
      moneyMetric(summary, "Upstream token rates plus routing fee", result.routed_comparison?.cost, result.local?.currency);
      moneyMetric(summary, "Declared all-in routed cost", result.routed_comparison?.all_in_cost, result.local?.currency);
      moneyMetric(summary, "Required-margin task price tick", result.pricing_diagnostics?.task_floors?.required_margin_sell_tick, result.local?.currency);
      metric(summary, "Whole-request crossover", result.pricing_diagnostics?.break_even?.whole_request_threshold);
      metric(summary, "Crossover / qualified capacity", result.pricing_diagnostics?.break_even?.threshold_utilization);
      metric(summary, "Price diagnostics", result.pricing_diagnostics?.status);
      moneyMetric(summary, "Base GPU purchase ceiling · economic budget only", result.pricing_diagnostics?.supplier_buy_ceiling?.required_margin_buy_tick_ceiling, result.local?.currency);
      for (const [label, codes] of [["Price diagnostics", result.pricing_diagnostics?.blockers], ["Crossover", result.pricing_diagnostics?.break_even?.blockers]]) if (codes?.length) summary.append(element("p", label + ": " + codes.join(" · "), "result-provenance"));
    } else if (kind === "portfolio") {
      moneyMetric(summary, "Operating contribution · before financing", result.economics?.expected_contribution, result.economics?.currency);
      moneyMetric(summary, "Economic profit · before financing", result.economics?.economic_profit, result.economics?.currency);
      moneyMetric(summary, "Supply cost without route allocation", result.economics?.unallocated_supply_cost, result.economics?.currency);
      moneyMetric(summary, "One shared minimum free cash", result.cash?.minimum_free_cash, result.economics?.currency);
      metric(summary, "Offtake routes", result.routes?.length); metric(summary, "Execution", "Disabled");
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
      const policyEntry = state.policySaved && !state.policyDirty ? state.policySaved : null;
      if (policyEntry) packet.market.policy = structuredClone(policyEntry.document.policy);
      packet.pricing_provenance = { mode: policyEntry && rows.every(item => typeof item.snapshot_id === "string" && /^[0-9a-f]{64}$/.test(item.snapshot_id)) ? "retained_market" : "declared_scenario", policy_revision: policyEntry && rows.every(item => typeof item.snapshot_id === "string" && /^[0-9a-f]{64}$/.test(item.snapshot_id)) ? policyEntry.revision : null };
      state.synthetic = false; byId("pricing-input").value = JSON.stringify(packet, null, 2); text("pricing-mode", policyEntry ? "Retained evidence · saved policy / server qualification" : "Retained observations · scenario needs saved policy"); readFields("pricing"); showView("pricing");
      const raw = byId("pricing-input").value;
      renderEvaluation("pricing", await api("/v1/pricing/evaluate", { method: "POST", body: raw }));
      if (byId("pricing-input").value !== raw) inputChanged("pricing");
      notify(policyEntry ? "Retained reference assessed with the selected saved policy. Source qualification is in the response; physical capacity is unverified." : "Retained observations assessed as a scenario. Apply a current saved policy to bind source evidence; no commercial bid or capacity is implied.");
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
    const input = byId(kind + "-input"); const raw = input.value; const value = safeEditableJson(raw);
    const fields = byId(kind + "-fields"); state.forms.get(kind)?.clear();
    try {
      const editor = window.ComputeDrafts.mount(fields, value, {
        raw, parse: safeEditableJson, readRaw: () => input.value,
        requirements: state.underwritingCatalog?.requirements || [], message: notify,
        changed: (encoded) => {
          input.value = encoded;
          if (kind === "underwriting") { underwritingEdited(); syncUnderwritingScopes(); }
          else if (kind === "inventory") { setBusy(state.busy); text("inventory-time-help", "Unsaved draft. Validate and save to update the declared positions."); }
          else inputChanged(kind);
          text(kind + "-fields-state", "Unsaved draft. Blank values remain unknown; exact strings are retained.");
        },
      });
      state.forms.set(kind, editor); text(kind + "-fields-state", "Editing the current request; rates and amounts remain exact strings.");
    } catch (error) { fields.replaceChildren(); state.forms.delete(kind); throw error; }
  }
  function newBlankDraft(kind, supplied) {
    const request = supplied || window.ComputeDrafts.template(kind);
    if (!request) throw new Error("Load the backend's current blank request contract.");
    byId(kind + "-input").value = JSON.stringify(request, null, 2); readFields(kind);
    if (kind === "inventory" || kind === "underwriting") setBusy(state.busy); else inputChanged(kind);
  }
  async function loadUnderwritingCatalog() {
    const catalog = await api("/v1/underwriting/template");
    if (!Array.isArray(catalog.requirements) || !Array.isArray(catalog.scope_options) || !catalog.request) throw new Error("Invalid requirement catalog; the draft was preserved.");
    state.underwritingCatalog = catalog; text("underwriting-catalog-version", "Requirements " + catalog.requirements_version);
    if (!byId("underwriting-input").value.trim()) {
      const request = structuredClone(catalog.request); request.as_of = new Date().toISOString().replace(/\.\d{3}Z$/, "Z"); request.request_id = "request:" + crypto.randomUUID();
      request.subjects = Object.fromEntries([...new Set(catalog.requirements.map((item) => item.subject_kind))].map((kind) => [kind, null]));
      byId("underwriting-input").value = JSON.stringify(request, null, 2); state.underwritingRows = catalog.requirements;
      renderUnderwritingRows(); underwritingEdited(); readFields("underwriting");
    }
    renderUnderwritingScopes(catalog.scope_options);
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
  byId("underwriting-template").addEventListener("click", () => runAction("Reading requirement definitions…", loadUnderwritingCatalog));
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
  document.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => showView(button.dataset.view)));
  byId("curve-model").addEventListener("change", renderCurveGroups);
  byId("curve-group").addEventListener("change", () => { state.selectedCurveNode = null; renderCommitmentChart(); });
  byId("market-compare-deal").addEventListener("click", () => { showView("pricing"); byId("demo-form-help").focus(); });
  byId("demo-load-sample").addEventListener("click", () => {
    const sample = state.demoContract?.sample;
    if (sample?.classification !== "synthetic" || !sample.inputs) { notify("No labeled invented scenario is available.", true); return; }
    state.demoFields.forEach((input, name) => { const parts = name.split("."); const value = parts.length === 2 ? sample.inputs[parts[0]]?.[parts[1]] : sample.inputs[name]; input.value = value === null || value === undefined ? "" : String(value); });
    state.demoSynthetic = true; demoEdited(); text("demo-scenario-mode", "Invented scenario · editable");
    notify("Invented deal loaded into this form only. Retained market references and inventory are unchanged.");
  });
  byId("demo-clear").addEventListener("click", () => { state.demoFields.forEach(input => { input.value = ""; }); state.demoSynthetic = false; state.demoResult = null; resetDemoResults(); setBusy(state.busy); });
  byId("demo-scenario-form").addEventListener("submit", event => {
    event.preventDefault();
    return runAction("Calculating the declared deal and dated cash…", async () => {
      const packet = demoPacket(); const raw = JSON.stringify(packet);
      const envelope = await api("/v1/demo/scenario", {method:"POST", body:raw}); renderDemoResult(envelope);
      try { if (JSON.stringify(demoPacket()) !== raw) demoEdited(); } catch (_) { demoEdited(); }
      notify("Scenario calculated from your explicit terms. Source admission and execution remain held.");
    });
  });
  byId("connect-session").addEventListener("click", openWorkspace);
  byId("disconnect").addEventListener("click", () => {
    const csrf = state.csrf; const handshake = sessionHandshake?.done; clearSession();
    cookieRevocation = (async () => {
      if (handshake) await handshake.catch(() => {});
      if (!csrf) return;
      const abort = new AbortController(); const timer = setTimeout(() => abort.abort(), 30000);
      try {
        const revoke = token => fetch("/v1/session/logout", { method: "POST", body: "{}", headers: { "Content-Type": "application/json", "X-Compute-CSRF": token }, credentials: "same-origin", cache: "no-store", redirect: "error", signal: abort.signal });
        const attempted = await revoke(csrf);
        const rejected = attempted.status === 403 ? await attempted.json().catch(() => null) : null;
        if (rejected?.detail === "browser_csrf_required") {
          const opened = await fetch("/v1/session/bootstrap", { method: "POST", body: "{}", headers: { "Content-Type": "application/json" }, credentials: "same-origin", cache: "no-store", redirect: "error", signal: abort.signal });
          const token = await opened.json();
          if (!opened.ok || token.auth_mode !== "local_session" || typeof token.csrf_token !== "string" || !token.csrf_token) throw new Error("Session close could not renew its token");
          await revoke(token.csrf_token); // Revocation only; all local state stays empty.
        }
      }
      catch (_) { /* Page data stays cleared; the session expires on the server. */ }
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
  byId("load-sample").addEventListener("click", () => runAction("Loading the labelled synthetic example…", async () => {
    const raw = await request("/workbench/assets/synthetic-pricing-request.json", {}, { authenticated: false, format: "text" });
    byId("pricing-input").value = raw; readFields("pricing"); state.synthetic = true; inputChanged("pricing"); text("pricing-mode", "SYNTHETIC EXAMPLE · invented scenario"); notify("Loaded an invented pricing scenario in the editor only. Market evidence and retained source snapshots are unchanged.");
  }));
  byId("pricing-input").addEventListener("input", () => text("pricing-mode", state.synthetic ? "Edited synthetic scenario · declared inputs" : "Edited declared input · review evidence scope"));
  byId("clear-pricing").addEventListener("click", () => { byId("pricing-input").value = ""; state.forms.get("pricing")?.clear(); state.synthetic = false; inputChanged("pricing"); text("pricing-mode", "Declared input · no example loaded"); });
  ["pricing", "inference", "cash", "portfolio"].forEach((kind) => { byId("evaluate-" + kind).addEventListener("click", () => evaluate(kind)); byId(kind + "-input").addEventListener("input", () => inputChanged(kind)); });
  byId("live-model").addEventListener("change", renderLiveTerms); byId("live-terms").addEventListener("change", () => setBusy(state.busy)); byId("evaluate-live-reference").addEventListener("click", liveReference);
  window.addEventListener("pagehide", () => clearSession(""));
  for (const view of ["market", "inventory", "underwriting", "pricing", "portfolio"]) byId("overview-open-" + view).addEventListener("click", () => showView(view));
  for (const kind of ["pricing", "inference", "cash", "inventory", "underwriting", "portfolio"]) {
    byId(kind + "-read-fields").addEventListener("click", () => { try { readFields(kind); } catch (error) { notify(error.message, true); } });
    byId(kind + "-new-draft").addEventListener("click", () => runAction("Preparing blank inputs…", async () => {
      const reset = () => { state.forms.get(kind)?.clear(); byId(kind + "-input").value = ""; };
      if (kind === "portfolio") { const template = await api("/v1/portfolio/template"); reset(); newBlankDraft(kind, template.request); }
      else if (kind === "underwriting") { reset(); await loadUnderwritingCatalog(); }
      else { reset(); newBlankDraft(kind); }
    }));
  }
  setInterval(() => {
    if (!state.session || state.busy) return;
    return runAction("Synchronizing retained evidence…", async () => {
      await loadIndex(); await loadRefreshStatus(); renderMarketMvp();
      const untouched = state.inventory && byId("inventory-input").value === JSON.stringify(state.inventory.state, null, 2);
      if (untouched && !state.inventoryDemo && byId("inventory-live").checked) await readInventory(true);
      renderDashboard();
    });
  }, 60000);
  setBusy(false);
  renderInventory(); renderDashboard(); renderMarketMvp(); resetDemoResults(); showView("market", false);
  window.addEventListener("load", openWorkspace);
})();
