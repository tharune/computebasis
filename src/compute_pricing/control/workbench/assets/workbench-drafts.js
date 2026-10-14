/* Exact, explicit draft editing. This component assigns no commercial values. */
(() => {
  "use strict";
  const unknown = (...names) => Object.fromEntries(names.map((name) => [name, null]));
  const deployment = () => unknown("model_id", "runtime_id", "runtime_version", "hardware_model", "precision", "quantization", "tensor_parallel", "pipeline_parallel", "data_replicas", "context_tokens", "batch_size", "input_tokens_per_request", "output_tokens_per_request", "cached_input_tokens_per_request");
  const tokenRates = () => unknown("currency", "input_per_million", "output_per_million", "cached_input_per_million", "request_fee");
  const cashContract = () => ({ ...unknown("legal_entity_id", "cash_account_id", "currency", "opening_cash", "start_date", "end_date"), events: [], reserves: [], facility: null });
  const inferenceContract = () => ({
    ...unknown("as_of", "policy_version", "model_version"),
    workload: { ...deployment(), ...unknown("request_count", "starts_at", "ends_at", "availability_fraction"), slo: unknown("max_ttft_ms", "max_p95_latency_ms") },
    qualification: { ...unknown("id", "status", "evidence_sha256", "measured_at", "expires_at", "whole_deployment_slo_goodput_requests_per_second", "measured_ttft_ms", "measured_p95_latency_ms"), setup: deployment(), memory: unknown("per_gpu_required_gib", "per_gpu_available_gib", "includes_kv_cache", "includes_runtime_overhead", "bandwidth_qualification") },
    costs: { ...unknown("currency", "gpu_rate_per_gpu_hour", "collection_share", "fee_fraction_of_collected_revenue", "fee_fraction_of_gross_revenue"), cost_items: [] },
    sale_rates: tokenRates(), external_route: null, pricing_policy: null, supplier_ceiling_policy: null,
  });
  const templates = {
    pricing: () => ({ market: { ...unknown("request_id", "as_of"), observations: [], policy: null }, target: { ...unknown("scope", "currency", "hardware_model", "country_code", "gpu_count", "duration_hours", "starts_at", "ends_at"), configuration: {} }, commercial: null, cash_template: null, pricing_provenance: { mode: "declared_scenario", policy_revision: null }, extensions: {} }),
    cash: cashContract,
    inference: inferenceContract,
    inventory: () => ({ schema_version: "paper-inventory/1.0", sites: [], lots: [], positions: [] }),
  };
  const objects = {
    commercial: () => ({ ...unknown("currency", "exclusive_node_gpu_count", "buyer_billed_gpu_hours", "buyer_rate", "supplier_ask", "collection_share", "fee_on_collected", "fee_on_gross", "required_margin", "margin_basis", "tick_size", "market_discount", "stress_price_cap"), cost_owners: {}, costs: [] }),
    cash_template: () => ({ minimum_cash: null, deal_event_ids: [], purchase_coefficients: {}, schedule: cashContract() }),
    facility: () => unknown("facility_id", "currency", "committed_limit", "opening_outstanding", "opening_drawn_total", "opening_accrued_interest", "annual_rate", "available_from", "maturity_date", "day_count", "revolving"),
    external_route: () => ({ ...tokenRates(), ...unknown("prices_include_route_fees", "route_fee_fraction", "source_id", "model_id", "precision", "quantization", "observed_at", "expires_at"), cost_items: null }),
    pricing_provenance: () => ({ mode: "declared_scenario", policy_revision: null }),
    supplier_ceiling_policy: () => unknown("buy_tick_per_gpu_hour", "nonpurchase_costs_complete", "nonpurchase_costs_rate_independent"),
    pricing_policy: () => ({ ...unknown("required_margin", "margin_basis", "policy_capital_amount", "task_price_tick"), rate_ticks: unknown("input_per_million", "output_per_million", "cached_input_per_million", "request_fee") }),
    inference_request: inferenceContract,
    purchase_value: () => ({ amount: null, currency: null, unit: "lot_total" }),
    sale_value: () => ({ amount: null, currency: null, unit: "position_total" }),
    policy: () => ({ ...unknown("policy_id", "version", "model_version", "registry_version", "effective_at", "expires_at"), parameters: { benchmark: { ...unknown("estimator", "max_source_share", "max_provider_share", "min_observations", "min_sources", "min_provider_groups"), source_rules: {} } } }),
  };
  const arrays = {
    sites: () => ({ ...unknown("site_id", "name", "country_code", "latitude", "longitude"), extensions: {} }),
    lots: () => ({ ...unknown("lot_id", "site_id", "unit_kind", "start_at", "end_at", "hardware_model"), unit_ids: [], purchase_value: null, extensions: {} }),
    positions: () => ({ ...unknown("position_id", "lot_id", "status", "start_at", "end_at", "contract_id"), unit_ids: [], sale_value: null, extensions: {} }),
    events: () => unknown("event_id", "obligation_id", "on", "kind", "amount", "currency", "invoice_id", "advance_account"),
    reserves: () => unknown("reserve_id", "coverage_id", "amount", "start_date", "end_date"),
    cost_items: () => unknown("id", "ownership_channel", "amount", "currency", "basis"),
    costs: () => unknown("id", "channel", "owner_model", "amount", "basis", "kind"),
    exposures: () => unknown("exposure_id", "entity_id", "group_id", "site_id", "currency", "amount"),
    limits: () => unknown("limit_id", "scope", "member_id", "currency", "maximum_amount"),
    reservations: () => ({ ...unknown("reservation_id", "allocation_id", "lot_id", "start_at", "end_at"), unit_ids: [] }),
    maintenance: () => ({ ...unknown("maintenance_id", "lot_id", "start_at", "end_at"), unit_ids: [] }),
    supplies: () => ({ ...unknown("supply_id", "lot_id", "purchase_cost", "currency"), cash_event_ids: [] }),
    supply_cost_allocations: () => unknown("supply_id", "amount"),
    routes: () => ({ ...unknown("route_id", "kind", "buyer_entity_id", "reservation_id", "underwriting_request_id"), cash_event_ids: [], exposure_ids: [], economics: unknown("currency", "gross_billings", "expected_collections", "distribution_fees", "nonpurchase_cost", "policy_capital"), supply_cost_allocations: [], inference_request: null }),
    evidence: () => ({ ...unknown("requirement_id", "subject_id", "value", "unit", "status", "reviewed_by", "valid_from", "valid_until", "not_applicable_reason"), evidence: [], extensions: {} }),
  };
  const countKeys = new Set(["tensor_parallel", "pipeline_parallel", "data_replicas", "context_tokens", "batch_size", "min_observations", "min_sources", "min_provider_groups", "reservation_months"]);
  const flagKeys = new Set(["revolving", "includes_kv_cache", "includes_runtime_overhead", "prices_include_route_fees", "required", "enabled", "allow_not_applicable", "nonpurchase_costs_complete", "nonpurchase_costs_rate_independent"]);
  const selects = { unit_kind: ["gpu", "node", "cpu", "accelerator"], margin_basis: ["gross_billings", "collected_revenue"], estimator: ["weighted_median", "weighted_mean"], day_count: ["ACT/365F", "ACT/360"], bandwidth_qualification: ["measured_under_declared_parallelism"] };
  const labels = { pricing_provenance: "Source evidence binding", policy_revision: "Saved policy revision", supplier_ceiling_policy: "Supplier economic ceiling", buy_tick_per_gpu_hour: "Supplier price tick / GPU-hour", nonpurchase_costs_complete: "All nonpurchase costs included", nonpurchase_costs_rate_independent: "Nonpurchase costs independent of GPU rate", gpu_rate_per_gpu_hour: "GPU charge per GPU-hour", input_per_million: "Uncached input per million tokens", output_per_million: "Output per million tokens", cached_input_per_million: "Cached input per million tokens", buyer_rate: "Buyer rate per GPU-hour", supplier_ask: "Supplier ask per GPU-hour", tick_size: "Rate tick per GPU-hour", exclusive_node_gpu_count: "Accelerators per exclusive node", collection_share: "Expected collection fraction", fee_on_collected: "Fee fraction of collections", fee_on_gross: "Fee fraction of gross billings", minimum_cash: "Minimum unrestricted cash", cash_template: "Dated shared-account cash path", unit_ids: "Physical unit identities", qualification: "Measured deployment evidence" };
  const own = (table, key) => Object.prototype.hasOwnProperty.call(table, key) ? table[key] : undefined;
  const forbidden = (key) => ["__proto__", "prototype", "constructor"].includes(key);
  const title = (key) => own(labels, key) || String(key).replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
  const element = (tag, text, className) => {
    const node = document.createElement(tag); if (text !== undefined) node.textContent = String(text); if (className) node.className = className; return node;
  };
  function enumValues(key, path) {
    if (key === "mode" && path.includes("pricing_provenance")) return ["declared_scenario", "retained_market"];
    if (key === "status" && path.includes("positions")) return ["reserved", "sold", "maintenance"];
    if (key === "status" && path.includes("qualification")) return ["qualified", "unqualified"];
    if (key === "status" && path.includes("evidence")) return ["declared", "verified", "missing", "stale", "conflicted", "invalid", "not_applicable"];
    if (key === "scope" && path.includes("target")) return ["physical_offer", "aggregate_reference"];
    if (key === "scope" && path.includes("limits")) return ["entity", "group", "site", "currency"];
    if (key === "kind" && path.includes("routes")) return ["inference", "resale", "forward"];
    if (key === "kind" && path.includes("events")) return ["buyer_invoice", "supplier_invoice", "revenue", "expense", "buyer_receipt", "buyer_deposit", "deposit_apply", "deposit_refund", "supplier_prepayment", "prepaid_apply", "supplier_payment", "other_inflow", "other_outflow", "facility_draw", "facility_repay", "facility_release", "facility_interest"];
    if (key === "kind" && path.includes("costs")) return ["expected_cost", "policy_capital"];
    if (key === "basis" && path.includes("cost_items")) return path.includes("external_route") ? ["whole_horizon", "per_request"] : ["whole_horizon", "per_request", "per_gpu_hour"];
    if (key === "basis" && path.includes("costs")) return ["fixed_contract", "supply_gpu_hour", "fraction_of_supply_purchase"];
    return own(selects, key);
  }
  function mount(container, draft, options) {
    const { parse, raw, readRaw, changed, message, requirements = [] } = options;
    let model = parse(raw); let baseline = raw; let count = 0;
    const declaredTypes = new Map();
    const pathKey = (path) => JSON.stringify(path);
    const checkCurrent = () => { if (readRaw() !== baseline) throw new Error("Advanced JSON changed. Reload it into fields before editing; the newer input was preserved."); };
    const commit = () => { checkCurrent(); const encoded = JSON.stringify(model, null, 2); changed(encoded); baseline = encoded; };
    const act = (callback) => { try { callback(); } catch (error) { message(error.message, true); } };

    function render() {
      // Build detached nodes first. A failed budget/key check never leaves a
      // partially rendered packet with unregistered live editing callbacks.
      container.replaceChildren(); count = 0;
      if (!model || typeof model !== "object" || Array.isArray(model)) throw new Error("Fields require a request object.");
      const staging = element("div");
      Object.entries(model).forEach(([key, value]) => {
        if (forbidden(key)) throw new Error("Reserved request key. Correct the advanced JSON before editing.");
        const structured = Boolean(value && typeof value === "object" || own(objects, key));
        const group = element(structured ? "details" : "div", undefined, structured ? "input-group" : "input-group scalar-group");
        if (structured) { group.open = !["extensions", "market", "capacity", "underwriting_requests", "qualification"].includes(key); group.append(element("summary", title(key))); }
        draw(group, model, key, [key], 0); staging.append(group);
      });
      container.append(...staging.children);
    }

    function draw(parent, holder, key, path, depth) {
      if (++count > 1600 || depth > 8) throw new Error("Structured editor budget exceeded. Keep the complete packet in advanced JSON.");
      const value = holder[key]; const location = path.join(".");
      if (Array.isArray(value)) {
        if (value.length > 40 || ["observations", "requirements", "underwriting_requests"].includes(key)) {
          parent.append(element("p", value.length + " entries preserved. Edit this complete evidence array in advanced JSON.", "field-help")); return;
        }
        value.forEach((item, index) => {
          const row = element("section", undefined, "array-row"); const heading = element("div", undefined, "array-heading"); heading.append(element("strong", title(key) + " " + (index + 1)));
          const remove = element("button", "Remove", "quiet-button"); remove.type = "button";
          remove.addEventListener("click", () => act(() => { checkCurrent(); value.splice(index, 1); declaredTypes.clear(); commit(); render(); })); heading.append(remove); row.append(heading);
          draw(row, value, index, [...path, String(index)], depth + 1); parent.append(row);
        });
        if (!value.length) parent.append(element("p", "No entries supplied.", "field-help"));
        const add = element("button", "Add " + title(key).toLowerCase(), "secondary-button"); add.type = "button";
        add.addEventListener("click", () => act(() => {
          checkCurrent(); let row = own(arrays, key)?.() ?? null;
          if (key === "lots" && path.includes("capacity")) row = { ...unknown("lot_id", "site_id", "unit_kind", "start_at", "end_at", "supplier_entity_id", "hardware_model", "accelerators_per_unit"), unit_ids: [] };
          if (key === "evidence" && path.length > 1) row = { ...unknown("id", "source_id", "artifact_sha256", "locator", "event_at", "accessed_at", "verifier", "status", "expires_at"), scope: [], permission: { ...unknown("status", "observe", "retain", "benchmark", "execution", "verified_by", "expires_at"), scope: [] } };
          value.push(row); commit(); render();
        })); parent.append(add); return;
      }
      if (value && typeof value === "object") {
        const grid = element("div", undefined, "input-grid");
        Object.keys(value).forEach((child) => {
          if (forbidden(child)) throw new Error("Reserved request key. Correct the advanced JSON before editing.");
          const item = value[child];
          if (item && typeof item === "object" || own(objects, child)) {
            const group = element("details", undefined, "nested-input-group"); group.open = !["extensions", "setup", "policy"].includes(child); group.append(element("summary", title(child))); draw(group, value, child, [...path, child], depth + 1); grid.append(group);
          } else draw(grid, value, child, [...path, child], depth + 1);
        }); parent.append(grid);
        const extra = element("details", undefined, "add-field"); extra.append(element("summary", "Add an explicit field"));
        const name = element("input"); name.type = "text"; name.placeholder = "Unique field name"; name.setAttribute("aria-label", "Additional field name at " + location);
        const type = element("select"); type.setAttribute("aria-label", "Additional field type at " + location);
        [["string", "Text or exact decimal"], ["boolean", "Boolean"], ["integer", "Whole-number literal"], ["object", "Object"], ["array", "Array"]].forEach(([key, label]) => { const option = element("option", label); option.value = key; type.append(option); });
        const add = element("button", "Add field", "quiet-button"); add.type = "button";
        add.addEventListener("click", () => act(() => {
          checkCurrent(); const field = name.value.trim();
          if (!/^[A-Za-z][A-Za-z0-9_.:/-]{0,127}$/.test(field) || forbidden(field) || Object.prototype.hasOwnProperty.call(value, field)) throw new Error("Choose a unique explicit field name without reserved keys.");
          value[field] = type.value === "object" ? {} : type.value === "array" ? [] : null;
          declaredTypes.set(pathKey([...path, field]), type.value); commit(); render();
        })); extra.append(name, type, add); parent.append(extra); return;
      }
      if (value === null && key === "cost_items" && path.includes("external_route")) {
        parent.append(element("p", "Routed operating costs are not declared. An explicit empty list asserts zero additional platform costs.", "field-help"));
        const declare = element("button", "Declare routed operating cost list", "secondary-button"); declare.type = "button";
        declare.addEventListener("click", () => act(() => { checkCurrent(); holder[key] = []; commit(); render(); })); parent.append(declare); return;
      }
      if (value === null && own(objects, key)) {
        parent.append(element("p", "Unknown. Add this structure only when its terms are supplied.", "field-help"));
        const add = element("button", "Add " + title(key).toLowerCase(), "secondary-button"); add.type = "button";
        add.addEventListener("click", () => act(() => { checkCurrent(); holder[key] = own(objects, key)(); commit(); render(); })); parent.append(add); return;
      }
      const scalar = typeof key === "number" ? path[path.length - 2] : String(key);
      const definition = scalar === "value" ? requirements.find((row) => row.requirement_id === holder.requirement_id) : null;
      const registeredType = definition ? definition.value_type === "boolean" ? "boolean" : "string" : null;
      const type = declaredTypes.get(pathKey(path)) || registeredType || (typeof value === "boolean" || flagKeys.has(scalar) ? "boolean" : typeof value === "number" || countKeys.has(scalar) ? "integer" : "string");
      const allowed = scalar === "requirement_id" && requirements.length ? requirements.map((row) => row.requirement_id) : definition?.allowed_values?.length ? definition.allowed_values : enumValues(scalar, path);
      const choice = type === "boolean" || Boolean(allowed);
      const label = element("label", title(scalar), "input-field");
      const control = element(choice ? "select" : "input"); control.setAttribute("data-field-path", location); control.setAttribute("aria-label", title(scalar) + " at " + location);
      if (choice) {
        const empty = element("option", "Unknown / not supplied"); empty.value = ""; control.append(empty);
        const values = type === "boolean" ? [["true", "True"], ["false", "False"]] : allowed.map((item) => [String(item), title(item)]);
        if (value !== null && !values.some(([item]) => item === String(value))) values.push([String(value), String(value)]);
        values.forEach(([item, text]) => { const option = element("option", text); option.value = item; control.append(option); });
      } else { control.type = "text"; control.placeholder = "Unknown / not supplied"; if (type === "integer") control.inputMode = "numeric"; }
      control.value = value === null ? "" : String(value);
      control.addEventListener(choice ? "change" : "input", () => act(() => {
        checkCurrent(); const text = control.value;
        holder[key] = text === "" ? null : type === "boolean" && ["true", "false"].includes(text) ? text === "true" : type === "integer" && /^-?\d+$/.test(text) && Number.isSafeInteger(Number(text)) ? Number(text) : text;
        commit(); if (scalar === "requirement_id") render();
      }));
      label.append(control);
      if (type === "integer") label.append(element("small", "Whole-number literal"));
      else if (/_at$/.test(scalar)) label.append(element("small", "UTC seconds: YYYY-MM-DDTHH:MM:SSZ"));
      parent.append(label);
    }
    render();
    return { clear: () => { model = null; baseline = ""; declaredTypes.clear(); container.replaceChildren(); } };
  }
  window.ComputeDrafts = Object.freeze({ template: (kind) => own(templates, kind)?.(), mount });
})();
