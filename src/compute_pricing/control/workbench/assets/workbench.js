(() => {
  "use strict";
  const byId = (id) => document.getElementById(id);
  const state = { key: "", epoch: 0, index: null, rows: [], sources: [], snapshots: [], page: 0, synthetic: false, busy: false };
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
    if (byId("evaluate-live-reference")) byId("evaluate-live-reference").disabled = busy || !state.key || !byId("live-model").value || !byId("live-terms").value;
  }
  function showView(name) {
    ["market", "pricing", "inference", "cash"].forEach((view) => { byId(view + "-view").hidden = view !== name; });
    document.querySelectorAll("[data-view]").forEach((button) => {
      const selected = button.dataset.view === name;
      button.classList.toggle("active", selected);
      if (selected) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current");
    });
  }
  function clearSession(message = "Session ended. Received data and drafts were cleared.") {
    state.epoch++; state.key = ""; state.index = null; state.rows = []; state.sources = []; state.snapshots = []; state.synthetic = false;
    byId("api-key").value = ""; byId("session-card").hidden = false; byId("disconnect").hidden = true;
    byId("session-dot").classList.remove("connected"); text("session-state", "Session locked");
    ["pricing", "inference", "cash"].forEach((kind) => {
      byId(kind + "-input").value = ""; byId(kind + "-output").textContent = ""; byId(kind + "-output").hidden = true;
      byId(kind + "-summary").replaceChildren(element("p", "Connect and supply an explicit scenario to evaluate.", "empty-state"));
      text(kind + "-result-state", "Not evaluated");
    });
    text("pricing-mode", "Declared input · no example loaded");
    byId("record-detail-json").textContent = ""; byId("record-detail").hidden = true;
    renderIndex(); setBusy(false); if (message) notify(message);
  }
  async function api(path, options = {}) {
    if (!state.key) throw new Error("Connect with your local API key first.");
    const epoch = state.epoch;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 120000);
    try {
      const response = await fetch(path, { ...options, headers: { "Authorization": "Bearer " + state.key, ...(options.body ? { "Content-Type": "application/json" } : {}) }, credentials: "omit", cache: "no-store", redirect: "error", signal: controller.signal });
      const data = await response.json().catch(() => ({}));
      if (epoch !== state.epoch || !state.key) throw new Error("The session ended while this request was running. Received data was discarded.");
      if (!response.ok) {
        if (response.status === 401) { clearSession(""); throw new Error("The API rejected this session. Enter the current local key."); }
        const detail = typeof data.detail === "string" ? data.detail : "Request rejected";
        throw new Error("HTTP " + response.status + " · " + detail);
      }
      return data;
    } catch (error) {
      if (error.name === "AbortError") throw new Error("Request timed out. Reload snapshots before retrying; a source read may still be completing.");
      throw error;
    } finally { clearTimeout(timer); }
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
  function isFx(record) { return /(?:fx|exchange_rate)/i.test(record.kind || record.role || "") || Boolean(record.base_currency && (record.quote_currency || record.currency) && record.rate !== undefined); }
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
      const meta = element("div", undefined, "source-meta");
      [source.implementation_state || "implementation unknown", "rights: " + (source.rights_status || "unknown"), "auth: " + (source.auth_state || "unknown"), "observed: " + (source.observed_liveness || "not probed")].forEach((label) => meta.append(element("span", label, "pill")));
      card.append(meta);
      const latest = sourceLatest(source);
      if (latest.captured) card.append(element("p", "Captured " + latest.captured + " · " + latest.count + " observations · " + latest.catalog + " catalog records"));
      if (latest.scopes.length) card.append(element("p", "Configured scopes: " + latest.scopes.length));
      if (source.coverage?.complete === false || latest.scopes.some((scope) => scope.coverage?.complete === false)) card.append(element("p", "Coverage is partial for the configured scopes.", "blocker"));
      if (source.blockers?.length) card.append(element("p", source.blockers.join(" · "), "blocker"));
      (source.last_attempts || []).filter((attempt) => attempt.status !== "updated").forEach((attempt) => card.append(element("p", "Last attempt " + attempt.status + " · " + (attempt.filters?.region || "configured scope") + " · " + (attempt.reason || "Review source receipt"), "blocker")));
      grid.append(card);
    });
  }
  function filteredRows() {
    const query = byId("record-query").value.trim().toLowerCase();
    return state.rows.filter((record) => (!byId("source-filter").value || record.source_id === byId("source-filter").value) && (!byId("region-filter").value || regionOf(record) === byId("region-filter").value) && (!byId("kind-filter").value || kindOf(record) === byId("kind-filter").value) && (!query || (modelOf(record) + " " + (record.id || "")).toLowerCase().includes(query)));
  }
  function showRecord(record) {
    byId("record-detail-json").textContent = JSON.stringify(record, null, 2); byId("record-detail").hidden = false;
    byId("record-detail").scrollIntoView({ behavior: "smooth", block: "nearest" });
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
      const action = element("button", "Inspect", "quiet-button"); action.addEventListener("click", () => showRecord(record));
      const actionCell = element("td"); actionCell.append(action);
      row.append(hardware, source, element("td", price.amount + " " + price.currency, "price-cell"), element("td", price.unit), element("td", regionOf(record)), status, element("td", record.observed_at || record.effective_start || record.effectiveStartDate || EMPTY), actionCell);
      body.append(row);
    });
    if (!selected.length) { const row = element("tr"); const cell = element("td", state.key ? "No retained records match this view. Refresh admitted feeds or change filters." : "No market data has been loaded. Synthetic examples never appear here.", "empty-state"); cell.colSpan = 8; row.append(cell); body.append(row); }
    text("record-count", rows.length + " matching records");
    text("page-label", rows.length ? "Showing " + (state.page * PAGE_SIZE + 1) + "–" + Math.min(rows.length, (state.page + 1) * PAGE_SIZE) + " of " + rows.length + " · Native price units remain separate" : "No records");
    byId("previous-page").disabled = state.page === 0; byId("next-page").disabled = state.page >= pages - 1;
  }
  function renderSnapshots() {
    const container = byId("snapshot-list"); container.replaceChildren();
    if (!state.snapshots.length) { container.append(element("p", "No retained source snapshots returned.", "empty-state")); return; }
    state.snapshots.slice(0, 30).forEach((snapshot) => {
      const row = element("div", undefined, "snapshot-row");
      const label = element("div", (snapshot.source_id || "Source receipt") + " · " + (snapshot.captured_at || snapshot.created_at || EMPTY));
      label.append(element("br"), element("code", snapshot.snapshot_id || snapshot.digest || EMPTY)); row.append(label);
      const identity = snapshot.snapshot_id || snapshot.digest;
      if (identity) { const action = element("button", "Open audit receipt", "quiet-button"); action.addEventListener("click", async () => { try { showRecord(await api("/v1/decisions/" + encodeURIComponent(identity))); } catch (error) { notify(error.message, true); } }); row.append(action); }
      container.append(row);
    });
  }
  function renderFx(index) {
    const rows = (index?.fx_records || []).concat((index?.catalog_records || []).filter(isFx));
    byId("fx-section").hidden = !rows.length; const container = byId("fx-records"); container.replaceChildren();
    rows.slice(0, 50).forEach((record) => {
      const row = element("div", undefined, "snapshot-row");
      row.append(element("span", (record.base_currency || record.base || EMPTY) + " → " + (record.quote_currency || record.currency || record.quote || EMPTY)), element("code", record.rate ?? record.value ?? EMPTY), element("span", (record.observed_at || record.observed_date || record.date || EMPTY) + (record.index_stale ? " · stale" : " · published reference"), "muted")); container.append(row);
    });
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
      const inspect = element("button", "Inspect metadata", "quiet-button"); inspect.addEventListener("click", () => showRecord(record));
      row.append(description, inspect); container.append(row);
    });
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
      const term = { billing_type: record.extensions.billing_type, reservation_months: record.extensions.reservation_months };
      terms.set(JSON.stringify(term), term);
    });
    terms.forEach((term, value) => { const option = element("option", term.billing_type + (term.reservation_months === null ? " · no reserved-month tenor" : " · " + term.reservation_months + " reserved months")); option.value = value; select.append(option); });
    if (terms.has(previous)) select.value = previous; setBusy(state.busy);
  }
  function renderIndex() {
    const index = state.index;
    renderSources();
    selection(byId("source-filter"), state.rows.map((r) => r.source_id).filter(Boolean), "All sources");
    selection(byId("region-filter"), state.rows.map(regionOf), "All regions");
    selection(byId("kind-filter"), state.rows.map(kindOf), "All scopes");
    selection(byId("live-model"), aggregateRows().map((r) => r.hardware.model), "Choose an admitted aggregate model");
    renderLiveTerms(); renderRows(); renderSnapshots(); renderFx(index); renderModelDiscovery(index);
    text("metric-observations", index ? state.rows.length : EMPTY);
    text("metric-sources", index ? new Set(state.rows.map((row) => row.source_id)).size : EMPTY);
    text("metric-admitted", index ? state.sources.filter((source) => source.can_attempt_read).length : EMPTY);
    text("metric-asof", index?.as_of || EMPTY);
    text("metric-snapshots", index ? state.snapshots.length + " retained source snapshots · FX references excluded · model metadata excluded" : "No source snapshots loaded");
    if (index?.truncated || index?.coverage?.truncated || index?.coverage?.display_truncated || index?.row_limit_reached) notify("The API returned a bounded subset. Coverage is partial; inspect source scope and truncation metadata.");
  }
  async function loadIndex() {
    const index = await api("/v1/market/index");
    state.index = index; state.sources = index.sources || []; state.snapshots = index.snapshots || [];
    state.rows = (index.observations || []).filter((row) => !isFx(row) && !isModelMetadata(row) && hasPublishedPrice(row)).concat((index.catalog_records || []).filter((row) => !isFx(row) && !isModelMetadata(row) && hasPublishedPrice(row)).map((row) => ({ ...row, _catalog: true })));
    state.page = 0; renderIndex(); return index;
  }
  function metric(container, label, value) { const card = element("div", undefined, "result-metric"); card.append(element("span", label), element("strong", value ?? EMPTY)); container.append(card); }
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
      metric(summary, result.benchmark?.cohort?.scope === "aggregate_reference" ? "Advertised global reference · per GPU-hour" : "Comparable reference · per GPU-hour", result.benchmark?.price);
      metric(summary, "Submitted purchase limit · per GPU-hour", result.bid?.submitted_limit);
      metric(summary, "Required-margin sell floor · per GPU-hour", result.ask?.sell_floor_tick);
      metric(summary, "Economic profit at supplied supplier ask", result.economics?.economic_profit);
      metric(summary, "Minimum free cash at selected bid", result.cash_constraint?.minimum_free_cash);
      metric(summary, "Extra cash required at supplier ask", result.cash_constraint?.supplied_ask_required_extra_cash);
      if (result.cash_constraint?.supplied_ask_cash_feasible === false) summary.append(element("div", "The supplied supplier ask has a funding shortfall. A positive modeled profit does not make that purchase cash-feasible.", "result-blockers"));
    } else if (kind === "inference") {
      metric(summary, "Allocated GPUs · full calendar cost", result.local?.allocated_gpu_count); metric(summary, "GPU cost including idle", result.local?.gpu_cost_including_idle);
      metric(summary, "Qualified whole-deployment request capacity", result.local?.request_capacity); metric(summary, "Local expected contribution", result.local?.expected_contribution);
      metric(summary, "Routed cost · matched model and token units", result.routed_comparison?.cost); metric(summary, "Routed comparison state", result.routed_comparison?.status);
    } else {
      metric(summary, "Minimum unrestricted free cash", result.minimum_free_cash); metric(summary, "Minimum free cash date", result.minimum_free_cash_date);
      metric(summary, "Minimum funding headroom", result.minimum_headroom); metric(summary, "Final unresolved balances", result.unresolved_balances && !hasUnresolved(result.unresolved_balances) ? "Settled in declared scenario" : "Review required");
    }
    if (blockers.length) summary.append(element("div", "Held: " + blockers.join(" · "), "result-blockers"));
    summary.append(element("p", "Snapshot " + (envelope.snapshot_id || EMPTY) + " · " + (envelope.created_at || result.as_of || EMPTY) + " · Indicative / held; execution disabled. Monetary values retain their source precision. Full cash paths, versions and exclusions appear below.", "result-provenance"));
    const output = byId(kind + "-output"); output.textContent = JSON.stringify(envelope, null, 2); output.hidden = false;
  }
  async function evaluate(kind) {
    const raw = byId(kind + "-input").value;
    if (!raw.trim()) { notify("Paste an explicit " + kind + " JSON request first.", true); return; }
    try { JSON.parse(raw); } catch (_) { notify("The editor contains invalid JSON. No request was sent.", true); return; }
    setBusy(true); notify("Evaluating declared " + kind + " inputs…");
    try { renderEvaluation(kind, await api("/v1/" + kind + "/evaluate", { method: "POST", body: raw })); notify("Scenario saved with a reproducible snapshot. Review holds, source scope and the complete breakdown."); }
    catch (error) { notify(error.message, true); } finally { setBusy(false); }
  }
  async function liveReference() {
    const selectedModel = byId("live-model").value; const selectedTerms = byId("live-terms").value;
    if (!selectedModel || !selectedTerms) return;
    setBusy(true); notify("Loading current retained source evidence for an indicative reference…");
    try {
      const index = await loadIndex(); const term = JSON.parse(selectedTerms);
      const rows = aggregateRows().filter((row) => row.hardware.model === selectedModel && row.extensions.billing_type === term.billing_type && row.extensions.reservation_months === term.reservation_months);
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
      const packet = { market: { request_id: "workbench-reference-" + crypto.randomUUID(), as_of: asOf, observations: rows, policy: { policy_id: "workbench-exploration", version: "0.1.0", model_version: "inverse-linear/1.0.0", registry_version: "1.0.0", effective_at: asOf, parameters: { benchmark: { estimator: "weighted_median", max_source_share: "1", max_provider_share: "1", min_observations: 1, min_sources: 1, min_provider_groups: 1, source_rules: rules } } } }, target: { scope: "aggregate_reference", currency: "USD", hardware_model: selectedModel, country_code: null, configuration: {}, gpu_count: "1", duration_hours: "1", aggregate_terms: term }, commercial: null, extensions: { workbench_mode: "live_source_global_reference", policy_basis: "uncalibrated_exploration_weights_one_gpu_hour_reference_no_physical_capacity" } };
      state.synthetic = false; byId("pricing-input").value = JSON.stringify(packet, null, 2); text("pricing-mode", "Live source reference · unvalidated exploration policy"); showView("pricing");
      renderEvaluation("pricing", await api("/v1/pricing/evaluate", { method: "POST", body: byId("pricing-input").value }));
      notify("Live retained source evidence evaluated as a global advertised reference. No commercial bid, ask, localized premium or physical capacity is asserted.");
    } catch (error) { notify(error.message, true); } finally { setBusy(false); }
  }
  document.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => showView(button.dataset.view)));
  byId("session-form").addEventListener("submit", async (event) => {
    event.preventDefault(); const key = byId("api-key").value;
    if (key.length < 32 || key.length > 256 || !/^[!-~]+$/.test(key)) { notify("Enter a 32–256 character printable local bearer key without whitespace.", true); return; }
    state.epoch++; state.key = key; byId("api-key").value = ""; setBusy(true);
    try { await loadIndex(); byId("session-card").hidden = true; byId("disconnect").hidden = false; text("session-state", "Local session connected"); byId("session-dot").classList.add("connected"); notify("Loaded retained source snapshots. Collection runs only when you explicitly refresh admitted feeds."); }
    catch (error) { state.key = ""; notify(error.message, true); } finally { setBusy(false); }
  });
  byId("disconnect").addEventListener("click", () => clearSession());
  byId("reload-index").addEventListener("click", async () => { setBusy(true); try { await loadIndex(); notify("Retained snapshots reloaded; no vendor request was made."); } catch (error) { notify(error.message, true); } finally { setBusy(false); } });
  byId("refresh-market").addEventListener("click", async () => {
    const ids = state.sources.filter((source) => source.can_attempt_read).map((source) => source.source_id);
    if (!ids.length) { notify("No source is currently admitted for read. Review source rights, schema, credentials and configured coverage.", true); return; }
    setBusy(true); notify("Refreshing admitted sources in their configured scopes. Existing snapshots remain auditable…");
    try { const result = await api("/v1/market/refresh", { method: "POST", body: JSON.stringify({ source_ids: ids }) }); await loadIndex(); notify("Refresh finished. Review source coverage and held/failed requests: " + JSON.stringify(result.summary || { updated: result.updated?.length ?? 0, held: result.held?.length ?? 0, failed: result.failed?.length ?? 0 })); }
    catch (error) { notify(error.message, true); } finally { setBusy(false); }
  });
  ["record-query", "source-filter", "region-filter", "kind-filter"].forEach((id) => byId(id).addEventListener("input", () => { state.page = 0; renderRows(); }));
  byId("previous-page").addEventListener("click", () => { state.page--; renderRows(); }); byId("next-page").addEventListener("click", () => { state.page++; renderRows(); });
  byId("close-detail").addEventListener("click", () => { byId("record-detail").hidden = true; byId("record-detail-json").textContent = ""; });
  byId("load-sample").addEventListener("click", async () => {
    try { const response = await fetch("/workbench/assets/synthetic-pricing-request.json", { cache: "no-store", credentials: "omit", redirect: "error" }); if (!response.ok) throw new Error("Synthetic example is unavailable."); byId("pricing-input").value = await response.text(); state.synthetic = true; text("pricing-mode", "SYNTHETIC EXAMPLE · invented scenario"); notify("Loaded an invented pricing scenario in the editor only. Market evidence and retained source snapshots are unchanged."); }
    catch (error) { notify(error.message, true); }
  });
  byId("pricing-input").addEventListener("input", () => text("pricing-mode", state.synthetic ? "Edited synthetic scenario · declared inputs" : "Edited declared input · review evidence scope"));
  byId("clear-pricing").addEventListener("click", () => { byId("pricing-input").value = ""; state.synthetic = false; text("pricing-mode", "Declared input · no example loaded"); });
  ["pricing", "inference", "cash"].forEach((kind) => byId("evaluate-" + kind).addEventListener("click", () => evaluate(kind)));
  byId("live-model").addEventListener("change", renderLiveTerms); byId("evaluate-live-reference").addEventListener("click", liveReference);
  window.addEventListener("pagehide", () => clearSession(""));
  setInterval(() => { if (state.key && !state.busy) { renderRows(); renderLiveTerms(); } }, 60000);
})();
