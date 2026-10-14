(() => {
  "use strict";
  const byId = (id) => document.getElementById(id);
  const state = { key: "", epoch: 0, index: null, rows: [], sources: [], snapshots: [], page: 0, synthetic: false, busy: false, action: null, controllers: new Map(), detailOrigin: null };
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
    if (byId("evaluate-live-reference")) byId("evaluate-live-reference").disabled = busy || !state.key || !byId("live-model").value || !byId("live-terms").value;
  }
  function showView(name, focus = true) {
    ["market", "pricing", "inference", "cash"].forEach((view) => { byId(view + "-view").hidden = view !== name; });
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
        const detail = typeof data?.detail === "string" ? data.detail : "Request rejected";
        throw new Error("HTTP " + response.status + " · " + detail);
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
  function regionOf(record) { return (typeof record.region === "string" ? record.region : record.region?.country_code || record.region?.locality || record.region?.name) || record.extensions?.provider_region || record.region_name || record.armRegionName || record.location || "Unknown / global"; }
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
    text("model-record-count", records.length + " metadata records · no prices / goodput");
    records.slice(0, 100).forEach((record) => {
      const row = element("div", undefined, "snapshot-row");
      const description = element("div", record.model_id || record.id || "Model metadata");
      description.append(element("br"), element("code", "Revision " + (record.repository_revision || "unknown") + " · License declared: " + (record.card_license || record.license_tags?.join(", ") || "unknown")));
      description.append(element("p", (record.gated ? "Gated access; permission review required" : "Public metadata; serving permissions unverified") + " · " + freshness(record) + " · No measured runtime qualification", "muted"));
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
      const rules = {};
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
  setInterval(() => { if (state.key && !state.busy) { renderRows(); selection(byId("live-model"), aggregateRows().map((row) => row.hardware.model), "Choose an admitted aggregate model"); renderLiveTerms(); } }, 60000);
  setBusy(false);
})();
