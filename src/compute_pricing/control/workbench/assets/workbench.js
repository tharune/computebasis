(() => {
  "use strict";
  const byId = (id) => document.getElementById(id);
  const state = { key: "", epoch: 0, index: null, rows: [], sources: [], snapshots: [], page: 0, synthetic: false, busy: false, action: null, controllers: new Map(), detailOrigin: null, inventory: null, inventoryDemo: false, inventorySite: "", selectedLot: "", land: null, policyEntries: [], policyCatalog: [], policyRows: [], policySaved: null, policyDirty: true, policyControlsDirty: false };
  const PAGE_SIZE = 100;
  const EMPTY = "—";

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
      const button = byId(id); if (button) button.disabled = busy || !state.key;
    });
    byId("refresh-market").disabled = busy || !state.key || !state.sources.some((source) => source.can_attempt_read);
    byId("connect-session").disabled = busy;
    byId("load-sample").disabled = busy;
    byId("cancel-request").disabled = !busy;
    byId("activity-bar").hidden = !busy;
    ["pricing", "inference", "cash"].forEach((kind) => {
      byId("evaluate-" + kind).disabled = busy || !state.key || !byId(kind + "-input").value.trim();
    });
    ["inventory-load", "inventory-demo", "policy-load", "policy-template", "policy-read-json", "policy-add-source"].forEach((id) => { byId(id).disabled = busy || !state.key; });
    byId("inventory-at").disabled = busy || byId("inventory-live").checked;
    byId("inventory-save").disabled = busy || !state.key || state.inventoryDemo || !byId("inventory-input").value.trim();
    ["policy-update-json", "policy-save"].forEach((id) => { byId(id).disabled = busy || !state.key || !byId("policy-input").value.trim(); });
    byId("policy-apply").disabled = busy || !state.key || !state.policySaved || state.policyDirty;
    if (byId("evaluate-live-reference")) byId("evaluate-live-reference").disabled = busy || !state.key || !byId("live-model").value || !byId("live-terms").value;
  }
  function showView(name, focus = true) {
    ["market", "inventory", "pricing", "policy", "inference", "cash"].forEach((view) => { byId(view + "-view").hidden = view !== name; });
    document.querySelectorAll("[data-view]").forEach((button) => {
      const selected = button.dataset.view === name;
      button.classList.toggle("active", selected);
      if (selected) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current");
    });
    if (focus) byId(name + "-title").focus({ preventScroll: true });
  }
  function abortRequests(reason) {
    state.controllers.forEach((request, controller) => { request.reason = reason; controller.abort(); });
  }
  function clearSession(message = "Session ended. Received data and drafts were cleared.") {
    state.epoch++; abortRequests("session"); state.action = null; state.key = ""; state.index = null; state.rows = []; state.sources = []; state.snapshots = []; state.synthetic = false; state.page = 0;
    byId("api-key").value = ""; byId("session-card").hidden = false; byId("disconnect").hidden = true;
    byId("session-dot").classList.remove("connected"); text("session-state", "Session locked");
    ["pricing", "inference", "cash"].forEach((kind) => {
      byId(kind + "-input").value = ""; byId(kind + "-output").textContent = ""; byId(kind + "-output").hidden = true;
      byId(kind + "-summary").replaceChildren(element("p", "Connect and supply an explicit scenario to evaluate.", "empty-state"));
      text(kind + "-result-state", "Not evaluated"); byId(kind + "-result-state").className = "pill";
      text(kind + "-input-state", "No input supplied.");
      byId(kind + "-input-state").className = "field-help";
    });
    text("pricing-mode", "Declared input · no example loaded");
    byId("record-detail-json").textContent = ""; byId("record-detail").hidden = true;
    byId("record-query").value = ""; state.detailOrigin = null;
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
    renderIndex(); setBusy(false); notify(message);
  }
  async function request(path, options = {}, { authenticated = true, timeout = 30000, format = "json" } = {}) {
    if (authenticated && !state.key) throw new Error("Connect with your local API key first.");
    const epoch = state.epoch;
    const controller = new AbortController();
    const pending = { epoch, reason: null }; state.controllers.set(controller, pending);
    const timer = setTimeout(() => { pending.reason = "timeout"; controller.abort(); }, timeout);
    try {
      const headers = { ...(authenticated ? { "Authorization": "Bearer " + state.key } : {}), ...(options.body ? { "Content-Type": "application/json" } : {}) };
      const response = await fetch(path, { ...options, headers, credentials: "omit", cache: "no-store", redirect: "error", signal: controller.signal });
      const data = format === "text" ? await response.text() : await response.json().catch(() => null);
      if (epoch !== state.epoch || authenticated && !state.key) throw new Error("The session ended while this request was running. Received data was discarded.");
      if (controller.signal.aborted) { const error = new Error("Request aborted"); error.name = "AbortError"; throw error; }
      if (!response.ok) {
        if (response.status === 401) { clearSession("The API rejected this session. Enter the current local key."); throw new Error("Session rejected"); }
        const detail = typeof data?.detail === "string" ? data.detail : typeof data?.detail?.code === "string" ? data.detail.code : "Request rejected";
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
  function api(path, options = {}) { return request(path, options, { timeout: path === "/v1/market/refresh" ? 120000 : 30000 }); }
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
    if (!state.sources.length) { grid.append(element("p", state.key ? "No source registry was returned." : "Connect to see implementation, access and permission states.", "empty-state")); return; }
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
      const detail = element("details"); detail.append(element("summary", "Permissions, scope & last attempt"));
      const meta = element("div", undefined, "source-meta");
      [source.implementation_state || "implementation unknown", "rights: " + (source.rights_status || "unknown"), "auth: " + (source.auth_state || "unknown"), "observed: " + (source.observed_liveness || "not probed")].forEach((label) => meta.append(element("span", label, "pill")));
      detail.append(meta);
      latest.scopes.forEach((scope) => detail.append(element("p", JSON.stringify(scope.filters || {}) + " · " + (scope.stale ? "stale" : "within collection policy") + " · " + (scope.captured_at || scope.created_at || EMPTY))));
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
    if (!selected.length) { const row = element("tr"); const cell = element("td", state.rows.length ? "No price records match these filters. Clear filters to see all retained prices." : state.key ? "No price records are retained. Read admitted feeds to collect configured scopes." : "Connect to load retained market evidence. Synthetic examples stay in the scenario editor.", "empty-state"); cell.colSpan = 8; row.append(cell); body.append(row); }
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
    records.slice(0, 100).forEach((record) => {
      const row = element("div", undefined, "snapshot-row");
      const description = element("div", record.model_id || record.id || "Model metadata");
      description.append(element("br"), element("code", "Revision " + (record.repository_revision || "unknown") + " · License declared: " + (record.card_license || record.license_tags?.join(", ") || "unknown")));
      const scope = record.kind === "model_price_catalog" ? isUnpriced(record) ? "UNPRICED / " + (record.price_status === "unpriced_invalid_advertised_dimensions" ? "invalid advertised dimensions quarantined" : "input/output token rates not published") : (record.price_status === "partial_token_rates" ? "Partial current-default token rates" : "Advertised current-default token rates") + " / " + (record.conditional_pricing_present ? "conditional pricing retained, unapplied" : "other billing dimensions require workload qualification") : record.gated ? "Gated access; permission review required" : "Public metadata; serving permissions unverified";
      description.append(element("p", scope + " · " + freshness(record) + " · No measured runtime qualification", "muted"));
      const inspect = element("button", "Inspect metadata", "quiet-button"); inspect.addEventListener("click", () => showRecord(record, inspect));
      row.append(description, inspect); container.append(row);
    });
    if (records.length > 100) container.append(element("p", "Showing 100 of " + records.length + " catalog records.", "muted"));
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
    terms.forEach((term, value) => { const option = element("option", term.currency + " / " + term.billing_type + (term.reservation_months === null ? " / no reserved tenor" : " / " + term.reservation_months + " reserved months")); option.value = value; select.append(option); });
    if (!terms.size) { const option = element("option", model ? "No current eligible terms" : "Choose a model first"); option.value = ""; select.append(option); }
    if (terms.has(previous)) select.value = previous;
    text("live-reference-state", !state.key ? "Connect to see eligible current aggregate cohorts." : !aggregateRows().length ? "No current aggregate cohort passes the source rights and expiry gates. Inspect admission and refresh coverage." : model ? terms.size + " currency / billing cohorts available. Exploration weights remain unvalidated." : "Select a model to choose exact currency and billing terms.");
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
    const index = await api("/v1/market/index");
    if (!Array.isArray(index.sources) || !Array.isArray(index.observations) || !Array.isArray(index.snapshots) || index.catalog_records && !Array.isArray(index.catalog_records)) throw new Error("The retained index response has an unexpected shape. No new records were displayed.");
    state.index = index; state.sources = index.sources || []; state.snapshots = index.snapshots || [];
    state.rows = (index.observations || []).filter((row) => !isFx(row) && !isModelMetadata(row) && hasPublishedPrice(row)).concat((index.catalog_records || []).filter((row) => !isFx(row) && !isModelMetadata(row) && hasPublishedPrice(row)).map((row) => ({ ...row, _catalog: true })));
    state.page = 0; renderIndex(); return index;
  }
  function metric(container, label, value) { const card = element("div", undefined, "result-metric"); card.append(element("span", label), element("strong", value ?? EMPTY)); container.append(card); }
  function moneyMetric(container, label, value, currency) { metric(container, label, value === null || value === undefined ? null : String(value) + " " + (currency || "(currency not returned)")); }
  function hasUnresolved(value) {
    if (value && typeof value === "object") return Object.values(value).some(hasUnresolved);
    return !/^-?0(?:\.0+)?$/.test(String(value));
  }
  function renderEvaluation(kind, envelope) {
    const result = envelope.result || envelope; const summary = byId(kind + "-summary"); summary.replaceChildren();
    text(kind + "-result-state", result.status || "Scenario calculated");
    byId(kind + "-result-state").className = "pill " + (result.status === "held" ? "warn" : "good");
    const blockers = result.hold_reasons || result.blockers || [];
    if (kind === "pricing") {
      const currency = result.economics?.currency || result.benchmark?.currency || result.benchmark?.cohort?.currency;
      moneyMetric(summary, result.benchmark?.cohort?.scope === "aggregate_reference" ? "Advertised global reference · per GPU-hour" : "Comparable reference · per GPU-hour", result.benchmark?.price, result.benchmark?.currency || result.benchmark?.cohort?.currency);
      moneyMetric(summary, "Submitted purchase limit · per GPU-hour", result.bid?.submitted_limit, currency);
      moneyMetric(summary, "Required-margin sell floor · per GPU-hour", result.ask?.sell_floor_tick, currency);
      moneyMetric(summary, "Economic profit at supplied supplier ask", result.economics?.economic_profit, currency);
      moneyMetric(summary, "Minimum free cash at selected bid", result.cash_constraint?.minimum_free_cash, currency);
      moneyMetric(summary, "Extra cash required at supplier ask", result.cash_constraint?.supplied_ask_required_extra_cash, currency);
      if (result.cash_constraint?.supplied_ask_cash_feasible === false) summary.append(element("div", "The supplied supplier ask has a funding shortfall. A positive modeled profit does not make that purchase cash-feasible.", "result-blockers"));
    } else if (kind === "inference") {
      metric(summary, "Allocated GPUs · full calendar cost", result.local?.allocated_gpu_count); moneyMetric(summary, "GPU cost including idle", result.local?.gpu_cost_including_idle, result.local?.currency);
      metric(summary, "Qualified whole-deployment request capacity", result.local?.request_capacity); moneyMetric(summary, "Local expected contribution", result.local?.expected_contribution, result.local?.currency);
      moneyMetric(summary, "Routed cost · matched model and token units", result.routed_comparison?.cost, result.local?.currency); metric(summary, "Routed comparison state", result.routed_comparison?.status);
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
      state.synthetic = false; byId("pricing-input").value = JSON.stringify(packet, null, 2); text("pricing-mode", "Live source reference · unvalidated exploration policy"); showView("pricing");
      const raw = byId("pricing-input").value;
      renderEvaluation("pricing", await api("/v1/pricing/evaluate", { method: "POST", body: raw }));
      if (byId("pricing-input").value !== raw) inputChanged("pricing");
      notify("Live retained source evidence evaluated as a global advertised reference. No commercial bid, ask, localized premium or physical capacity is asserted.");
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
    byId("inventory-input").value = JSON.stringify(report.state, null, 2); byId("inventory-output").textContent = JSON.stringify(report, null, 2); byId("inventory-output").hidden = false; renderInventory();
  }
  function syntheticInventory(asOf) {
    const instant = Date.parse(asOf); const stamp = (days) => new Date(instant + days * 86400000).toISOString().replace(".000Z", "Z");
    return { schema_version: "paper-inventory/1.0", sites: [{ site_id: "synthetic:north", name: "Synthetic North", country_code: "US", latitude: "41.9", longitude: "-87.6", extensions: { provenance: "independently_invented_synthetic_ui_demo_not_a_real_holding" } }, { site_id: "synthetic:west", name: "Synthetic West", country_code: "NL", latitude: "52.3", longitude: "4.9" }, { site_id: "synthetic:unmapped", name: "Synthetic / location withheld", latitude: null, longitude: null }], lots: [{ lot_id: "synthetic:gpu-a", site_id: "synthetic:north", unit_kind: "gpu", unit_ids: ["demo:a1", "demo:a2", "demo:a3", "demo:a4"], hardware_model: "Invented accelerator A", start_at: stamp(-7), end_at: stamp(21) }, { lot_id: "synthetic:node-b", site_id: "synthetic:west", unit_kind: "node", unit_ids: ["demo:b1", "demo:b2"], hardware_model: "Invented node bundle B", start_at: stamp(-7), end_at: stamp(21) }, { lot_id: "synthetic:gpu-c", site_id: "synthetic:unmapped", unit_kind: "gpu", unit_ids: ["demo:c1", "demo:c2"], hardware_model: "Invented accelerator C", start_at: stamp(-7), end_at: stamp(21) }], positions: [{ position_id: "demo:sale", lot_id: "synthetic:gpu-a", unit_ids: ["demo:a1", "demo:a2"], status: "sold", start_at: stamp(-1), end_at: stamp(7) }, { position_id: "demo:reservation", lot_id: "synthetic:gpu-a", unit_ids: ["demo:a3"], status: "reserved", start_at: stamp(0), end_at: stamp(10) }, { position_id: "demo:maintenance", lot_id: "synthetic:gpu-c", unit_ids: ["demo:c1"], status: "maintenance", start_at: stamp(-2), end_at: stamp(2) }] };
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
    const draft = parsed.request; if (!draft?.market || typeof draft.market !== "object" || Array.isArray(draft.market)) throw new Error("Supply a pricing request with a market packet first."); const document = saved.document; draft.market.policy = structuredClone(document.policy); draft.extensions = { ...(draft.extensions || {}), policy_registry_document: { revision: saved.revision, feature_definitions: document.feature_definitions, notes: document.notes } }; byId("pricing-input").value = JSON.stringify(draft, null, 2); inputChanged("pricing"); text("pricing-mode", "Saved policy applied / evaluate this draft"); showView("pricing"); notify("Applied saved policy " + document.policy.policy_id + " / " + document.policy.version + " to the draft. Evaluate explicitly; registered features remain subject to model activation gates.");
  }));
  [...POLICY_FIELDS, ...BENCHMARK_FIELDS].forEach(([, id]) => byId(id).addEventListener("input", () => policyEdited(true))); byId("policy-input").addEventListener("input", () => policyEdited());
  document.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => showView(button.dataset.view)));
  document.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => showView(button.dataset.view)));
  byId("session-form").addEventListener("submit", async (event) => {
    event.preventDefault(); const key = byId("api-key").value;
    if (key.length < 32 || key.length > 256 || !/^[!-~]+$/.test(key)) { notify("Enter a 32–256 character printable local bearer key without whitespace.", true); return; }
    if (state.busy) return;
    clearSession(""); state.key = key; const epoch = state.epoch; byId("api-key").value = ""; byId("disconnect").hidden = false; text("session-state", "Connecting…");
    await runAction("Connecting to the local API…", async () => {
      try { await loadIndex(); } catch (error) { if (epoch === state.epoch && state.key) clearSession(error.message); throw error; }
      byId("session-card").hidden = true; text("session-state", "Local session connected"); byId("session-dot").classList.add("connected");
      notify("Retained evidence loaded. Feed reads happen only when you explicitly choose Read admitted feeds.");
    });
  });
  byId("disconnect").addEventListener("click", () => clearSession());
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
  byId("reset-filters").addEventListener("click", () => { ["record-query", "source-filter", "region-filter", "kind-filter"].forEach((id) => { byId(id).value = ""; }); state.page = 0; renderRows(); byId("record-query").focus(); });
  byId("previous-page").addEventListener("click", () => { state.page--; renderRows(); }); byId("next-page").addEventListener("click", () => { state.page++; renderRows(); });
  byId("close-detail").addEventListener("click", () => { byId("record-detail").hidden = true; byId("record-detail-json").textContent = ""; if (state.detailOrigin?.isConnected) state.detailOrigin.focus(); else byId("market-title").focus(); state.detailOrigin = null; });
  byId("load-sample").addEventListener("click", () => runAction("Loading the labelled synthetic example…", async () => {
    const raw = await request("/workbench/assets/synthetic-pricing-request.json", {}, { authenticated: false, format: "text" });
    byId("pricing-input").value = raw; state.synthetic = true; inputChanged("pricing"); text("pricing-mode", "SYNTHETIC EXAMPLE · invented scenario"); notify("Loaded an invented pricing scenario in the editor only. Market evidence and retained source snapshots are unchanged.");
  }));
  byId("pricing-input").addEventListener("input", () => text("pricing-mode", state.synthetic ? "Edited synthetic scenario · declared inputs" : "Edited declared input · review evidence scope"));
  byId("clear-pricing").addEventListener("click", () => { byId("pricing-input").value = ""; state.synthetic = false; inputChanged("pricing"); text("pricing-mode", "Declared input · no example loaded"); });
  ["pricing", "inference", "cash"].forEach((kind) => { byId("evaluate-" + kind).addEventListener("click", () => evaluate(kind)); byId(kind + "-input").addEventListener("input", () => inputChanged(kind)); });
  byId("live-model").addEventListener("change", renderLiveTerms); byId("live-terms").addEventListener("change", () => setBusy(state.busy)); byId("evaluate-live-reference").addEventListener("click", liveReference);
  window.addEventListener("pagehide", () => clearSession(""));
  setInterval(() => {
    if (state.key && !state.busy) {
      renderRows(); selection(byId("live-model"), aggregateRows().map((row) => row.hardware.model), "Choose an admitted aggregate model"); renderLiveTerms();
      if (state.inventory && !state.inventoryDemo && !byId("inventory-view").hidden && byId("inventory-live").checked && byId("inventory-input").value === JSON.stringify(state.inventory.state, null, 2)) return runAction("Reading current local inventory…", () => readInventory(true));
    }
  }, 60000);
  setBusy(false);
  renderInventory();
})();
