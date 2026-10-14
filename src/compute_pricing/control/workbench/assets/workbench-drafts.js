/* Structural request editors. No prices, credit estimates or commercial defaults. */
(() => {
  "use strict";
  const own = (object, key) => Object.prototype.hasOwnProperty.call(object, key) ? object[key] : undefined;
  const blank = (...keys) => Object.fromEntries(keys.map((key) => [key, null]));
  const setup = () => blank("model_id", "runtime_id", "runtime_version", "hardware_model", "precision", "quantization", "tensor_parallel", "pipeline_parallel", "data_replicas", "context_tokens", "batch_size", "input_tokens_per_request", "output_tokens_per_request", "cached_input_tokens_per_request");
  const rates = () => blank("currency", "input_per_million", "output_per_million", "cached_input_per_million", "request_fee");
  const cash = () => ({ ...blank("legal_entity_id", "cash_account_id", "currency", "opening_cash", "start_date", "end_date"), events: [], reserves: [], facility: null });
  const commercial = () => ({ ...blank("currency", "exclusive_node_gpu_count", "buyer_billed_gpu_hours", "buyer_rate", "supplier_ask", "collection_share", "fee_on_collected", "fee_on_gross", "required_margin", "margin_basis", "tick_size", "market_discount", "stress_price_cap"), cost_owners: {}, costs: [] });
  const templates = {
    pricing: () => ({ market: { ...blank("request_id", "as_of"), observations: [], policy: null }, target: { ...blank("scope", "currency", "hardware_model", "country_code", "gpu_count", "duration_hours", "starts_at", "ends_at"), configuration: {} }, commercial: null, cash_template: null, pricing_provenance: { mode: "declared_scenario", policy_revision: null }, extensions: {} }),
    inference: () => ({ ...blank("as_of", "policy_version", "model_version"), workload: { ...setup(), ...blank("request_count", "starts_at", "ends_at", "availability_fraction"), slo: blank("max_ttft_ms", "max_p95_latency_ms") }, qualification: { ...blank("id", "status", "evidence_sha256", "measured_at", "expires_at", "whole_deployment_slo_goodput_requests_per_second", "measured_ttft_ms", "measured_p95_latency_ms"), setup: setup(), memory: blank("per_gpu_required_gib", "per_gpu_available_gib", "includes_kv_cache", "includes_runtime_overhead", "bandwidth_qualification") }, costs: { ...blank("currency", "gpu_rate_per_gpu_hour", "collection_share", "fee_fraction_of_collected_revenue", "fee_fraction_of_gross_revenue"), cost_items: [] }, sale_rates: rates(), external_route: null, pricing_policy: null, supplier_ceiling_policy: null }),
    cash,
    inventory: () => ({ schema_version: "paper-inventory/1.0", sites: [], lots: [], positions: [] }),
  };
  const objectShapes = {
    commercial, cash_template: () => ({ minimum_cash: null, deal_event_ids: [], purchase_coefficients: {}, schedule: cash() }),
    external_route: () => ({ ...rates(), ...blank("prices_include_route_fees", "route_fee_fraction", "source_id", "model_id", "precision", "quantization", "observed_at", "expires_at"), cost_items: null }),
    pricing_provenance: () => ({ mode: "declared_scenario", policy_revision: null }),
    supplier_ceiling_policy: () => blank("buy_tick_per_gpu_hour", "nonpurchase_costs_complete", "nonpurchase_costs_rate_independent"),
    pricing_policy: () => ({ ...blank("required_margin", "margin_basis", "policy_capital_amount", "task_price_tick"), rate_ticks: blank("input_per_million", "output_per_million", "cached_input_per_million", "request_fee") }),
    facility: () => blank("facility_id", "currency", "committed_limit", "opening_outstanding", "opening_drawn_total", "opening_accrued_interest", "annual_rate", "available_from", "maturity_date", "day_count", "revolving"),
    purchase_value: () => ({ amount: null, currency: null, unit: "lot_total" }), sale_value: () => ({ amount: null, currency: null, unit: "position_total" }),
    policy: () => ({ ...blank("policy_id", "version", "model_version", "registry_version", "effective_at", "expires_at"), parameters: { benchmark: { ...blank("estimator", "max_source_share", "max_provider_share", "min_observations", "min_sources", "min_provider_groups"), source_rules: {} } } }),
  };
  const arrayShapes = {
    events: () => blank("event_id", "obligation_id", "on", "kind", "amount", "currency", "invoice_id", "advance_account"),
    reserves: () => blank("reserve_id", "coverage_id", "amount", "start_date", "end_date"),
    cost_items: () => blank("id", "ownership_channel", "amount", "currency", "basis"),
    costs: () => blank("id", "channel", "owner_model", "amount", "basis", "kind"),
    sites: () => ({ ...blank("site_id", "name", "country_code", "latitude", "longitude"), extensions: {} }),
    lots: () => ({ ...blank("lot_id", "site_id", "unit_kind", "start_at", "end_at", "hardware_model"), unit_ids: [], purchase_value: null, extensions: {} }),
    positions: () => ({ ...blank("position_id", "lot_id", "status", "start_at", "end_at", "contract_id"), unit_ids: [], sale_value: null, extensions: {} }),
    exposures: () => blank("exposure_id", "entity_id", "group_id", "site_id", "currency", "amount"),
    limits: () => blank("limit_id", "scope", "member_id", "currency", "maximum_amount"),
    reservations: () => ({ ...blank("reservation_id", "allocation_id", "lot_id", "start_at", "end_at"), unit_ids: [] }),
    maintenance: () => ({ ...blank("maintenance_id", "lot_id", "start_at", "end_at"), unit_ids: [] }),
    supplies: () => ({ ...blank("supply_id", "lot_id", "purchase_cost", "currency"), cash_event_ids: [] }),
    supply_cost_allocations: () => blank("supply_id", "amount"),
    routes: () => ({ ...blank("route_id", "kind", "buyer_entity_id", "reservation_id", "underwriting_request_id"), cash_event_ids: [], exposure_ids: [], economics: blank("currency", "gross_billings", "expected_collections", "distribution_fees", "nonpurchase_cost", "policy_capital"), supply_cost_allocations: [], inference_request: null }),
    evidence: () => ({ ...blank("requirement_id", "subject_id", "value", "unit", "status", "reviewed_by", "valid_from", "valid_until", "not_applicable_reason"), evidence: [], extensions: {} }),
  };
  const integerKeys = new Set(["tensor_parallel", "pipeline_parallel", "data_replicas", "context_tokens", "batch_size", "min_observations", "min_sources", "min_provider_groups", "reservation_months"]);
  const booleanKeys = new Set(["revolving", "includes_kv_cache", "includes_runtime_overhead", "prices_include_route_fees", "required", "enabled", "allow_not_applicable", "nonpurchase_costs_complete", "nonpurchase_costs_rate_independent"]);
  const enums = { unit_kind: ["gpu", "node", "cpu", "accelerator"], margin_basis: ["gross_billings", "collected_revenue"], estimator: ["weighted_median", "weighted_mean"], day_count: ["ACT/365F", "ACT/360"], bandwidth_qualification: ["measured_under_declared_parallelism"] };
  const labels = { pricing_provenance: "Source evidence binding", policy_revision: "Saved policy revision", supplier_ceiling_policy: "Supplier economic ceiling", buy_tick_per_gpu_hour: "Supplier price tick / GPU-hour", nonpurchase_costs_complete: "All nonpurchase costs included", nonpurchase_costs_rate_independent: "Nonpurchase costs independent of GPU rate", gpu_count: "Allocated GPU count", duration_hours: "Supply duration (hours)", hardware_model: "Hardware model / exact SKU", country_code: "Country code (ISO)", max_ttft_ms: "Maximum time to first token (ms)", max_p95_latency_ms: "Maximum p95 latency (ms)", tensor_parallel: "Tensor parallel GPUs", pipeline_parallel: "Pipeline stages", data_replicas: "Deployment replicas", gpu_rate_per_gpu_hour: "GPU rate / GPU-hour", input_per_million: "Uncached input / million tokens", output_per_million: "Output / million tokens", cached_input_per_million: "Cached input / million tokens", fee_on_collected: "Fee / collected revenue (fraction)", fee_on_gross: "Fee / gross billings (fraction)", collection_share: "Expected collection (fraction)", exclusive_node_gpu_count: "GPUs per exclusive node", buyer_billed_gpu_hours: "Buyer billed GPU-hours", buyer_rate: "Buyer rate / GPU-hour", supplier_ask: "Supplier ask / GPU-hour", tick_size: "Price tick / GPU-hour", minimum_free_cash: "Minimum unrestricted cash", gross_billings: "Gross billings", expected_collections: "Expected collections", nonpurchase_cost: "Nonpurchase cost", policy_capital: "Policy capital", unit_ids: "Physical unit IDs", cost_owners: "Cost channel ownership", evidence_refs: "Supporting evidence pointers", qualification: "Measured deployment qualification", cash_template: "Dated pricing cash path" };
  const title = (key) => own(labels, key) || key.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
  const node = (tag, text, className) => { const result = document.createElement(tag); if (text !== undefined) result.textContent = text; if (className) result.className = className; return result; };
  const forbiddenKey = (key) => ["__proto__", "constructor", "prototype"].includes(key);
  function choices(key, path) {
    if (key === "mode" && path.includes("pricing_provenance")) return ["declared_scenario", "retained_market"];
    if (key === "status" && path.includes("positions")) return ["reserved", "sold", "maintenance"];
    if (key === "status" && path.includes("qualification")) return ["qualified", "unqualified"];
    if (key === "status" && path.includes("evidence")) return ["declared", "verified", "missing", "stale", "conflicted", "invalid", "not_applicable"];
    if (key === "scope" && path.includes("target")) return ["physical_offer", "aggregate_reference"];
    if (key === "scope" && path.includes("limits")) return ["entity", "group", "site", "currency"];
    if (key === "kind" && path.includes("events")) return ["buyer_invoice", "supplier_invoice", "revenue", "expense", "buyer_receipt", "buyer_deposit", "deposit_apply", "deposit_refund", "supplier_prepayment", "prepaid_apply", "supplier_payment", "other_inflow", "other_outflow", "facility_draw", "facility_repay", "facility_release", "facility_interest"];
    if (key === "kind" && path.includes("routes")) return ["inference", "resale", "forward"];
    if (key === "kind" && path.includes("costs")) return ["expected_cost", "policy_capital"];
    if (key === "basis" && path.includes("cost_items")) return path.includes("external_route") ? ["whole_horizon", "per_request"] : ["whole_horizon", "per_request", "per_gpu_hour"];
    if (key === "basis" && path.includes("costs")) return ["fixed_contract", "supply_gpu_hour", "fraction_of_supply_purchase"];
    return own(enums, key);
  }
  function mount(container, documentValue, { parse, changed, message, raw, readRaw, requirements = [] }) {
    let model = structuredClone(documentValue); let baseline = raw;
    const assertCurrent = () => { if (readRaw() !== baseline) throw new Error("The advanced draft changed. Read it into fields before editing so no input is overwritten."); };
    const commit = () => { assertCurrent(); const encoded = JSON.stringify(model, null, 2); changed(encoded); baseline = encoded; };
    const action = (callback) => { try { callback(); } catch (error) { message(error.message, true); } };
    let rendered = 0;
    function render() {
      container.replaceChildren(); rendered = 0;
      if (!model || typeof model !== "object" || Array.isArray(model)) throw new Error("Structured inputs require a request object.");
      Object.entries(model).forEach(([key, value]) => {
        if (forbiddenKey(key)) throw new Error("Unsafe request key. Correct the advanced JSON before editing.");
        if (value && typeof value === "object" || own(objectShapes, key)) {
          const group = node("details", undefined, "input-group"); group.open = !["qualification", "extensions", "market", "capacity", "underwriting_requests"].includes(key);
          group.append(node("summary", title(key))); draw(group, model, key, [key], 0); container.append(group);
        } else { const field = node("div", undefined, "input-group scalar-group"); draw(field, model, key, [key], 0); container.append(field); }
      });
    }
    function draw(parent, object, key, path, depth) {
      rendered++; if (rendered > 1600 || depth > 8) throw new Error("This request exceeds the structured editor budget. Use advanced JSON for the complete packet.");
      const value = object[key]; const location = path.join(".");
      if (value === null && key === "cost_items" && path.includes("external_route")) {
        parent.append(node("p", "Routed operating costs are unknown. Declare a complete item list to enable an all-in comparison.", "field-help"));
        const declare = node("button", "Declare routed operating costs", "secondary-button"); declare.type = "button";
        declare.addEventListener("click", () => action(() => { assertCurrent(); object[key] = []; commit(); render(); })); parent.append(declare); return;
      }
      if (Array.isArray(value)) {
        if (value.length > 40 || ["observations", "requirements", "underwriting_requests"].includes(key)) { parent.append(node("p", value.length + " retained entries. Edit this evidence packet in advanced JSON; fields preserve it without conversion.", "field-help")); return; }
        value.forEach((item, index) => {
          const row = node("section", undefined, "array-row"); const heading = node("div", undefined, "array-heading"); heading.append(node("strong", title(key) + " " + (index + 1)));
          const remove = node("button", "Remove", "quiet-button"); remove.type = "button"; remove.addEventListener("click", () => action(() => { assertCurrent(); value.splice(index, 1); commit(); render(); })); heading.append(remove); row.append(heading);
          draw(row, value, index, [...path, String(index)], depth + 1); parent.append(row);
        });
        if (!value.length) parent.append(node("p", "No " + title(key).toLowerCase() + " supplied.", "field-help"));
        const add = node("button", "Add " + title(key).toLowerCase(), "secondary-button"); add.type = "button"; add.addEventListener("click", () => action(() => {
          assertCurrent(); let item = own(arrayShapes, key)?.() ?? null;
          if (key === "evidence" && path.length > 1) item = { ...blank("id", "source_id", "artifact_sha256", "locator", "event_at", "accessed_at", "verifier", "status", "expires_at"), scope: [], permission: { status: null, observe: null, benchmark: null, execution: null, verified_by: null, scope: [], expires_at: null } };
          if (key === "lots" && path.includes("capacity")) item = { ...blank("lot_id", "site_id", "unit_kind", "start_at", "end_at", "supplier_entity_id", "hardware_model", "accelerators_per_unit"), unit_ids: [] };
          value.push(item); commit(); render();
        })); parent.append(add); return;
      }
      if (value && typeof value === "object") {
        const grid = node("div", undefined, "input-grid");
        Object.entries(value).forEach(([childKey, item]) => {
          if (forbiddenKey(childKey)) throw new Error("Unsafe request key. Correct the advanced JSON before editing.");
          if (item && typeof item === "object" || own(objectShapes, childKey)) { const block = node("details", undefined, "nested-input-group"); block.open = !["extensions", "setup", "policy"].includes(childKey); block.append(node("summary", title(childKey))); draw(block, value, childKey, [...path, childKey], depth + 1); grid.append(block); }
          else draw(grid, value, childKey, [...path, childKey], depth + 1);
        });
        parent.append(grid);
        const extension = node("details", undefined, "add-field"); extension.append(node("summary", "Add explicit field"));
        const name = node("input"); name.type = "text"; name.setAttribute("aria-label", "New field name at " + location); name.placeholder = "Field name";
        const type = node("select"); type.setAttribute("aria-label", "New field type at " + location);
        [["string", "Text / exact decimal"], ["boolean", "Boolean"], ["integer", "Whole-number literal"], ["object", "Object"], ["array", "Array"]].forEach(([entry, label]) => { const option = node("option", label); option.value = entry; type.append(option); });
        const add = node("button", "Add field", "quiet-button"); add.type = "button"; add.addEventListener("click", () => action(() => {
          assertCurrent(); const field = name.value.trim(); if (!/^[A-Za-z][A-Za-z0-9_.:/-]{0,127}$/.test(field) || forbiddenKey(field) || Object.prototype.hasOwnProperty.call(value, field)) throw new Error("Use a unique, explicit field name without reserved keys.");
          value[field] = type.value === "object" ? {} : type.value === "array" ? [] : null;
          customTypes.set(JSON.stringify([...path, field]), type.value); commit(); render();
        })); extension.append(name, type, add); parent.append(extension); return;
      }
      if (value === null && own(objectShapes, key)) {
        parent.append(node("p", "Not supplied. Add this structure only when its terms are known.", "field-help")); const add = node("button", "Add " + title(key).toLowerCase(), "secondary-button"); add.type = "button";
        add.addEventListener("click", () => action(() => { assertCurrent(); object[key] = own(objectShapes, key)(); commit(); render(); })); parent.append(add); return;
      }
      const scalarKey = typeof key === "number" ? path[path.length - 2] : key;
      const label = node("label", title(String(scalarKey)), "input-field");
      const definition = scalarKey === "value" ? requirements.find((entry) => entry.requirement_id === object.requirement_id) : null;
      // Registered underwriting integers are exact strings, not JSON count literals.
      const type = customTypes.get(JSON.stringify(path)) || (definition?.value_type === "boolean" || typeof value === "boolean" || booleanKeys.has(scalarKey) ? "boolean" : !definition && (typeof value === "number" || integerKeys.has(scalarKey)) ? "integer" : "string");
      const allowed = scalarKey === "requirement_id" && requirements.length ? requirements.map((entry) => entry.requirement_id) : definition?.allowed_values?.length ? definition.allowed_values : choices(scalarKey, path);
      const control = node(type === "boolean" || allowed ? "select" : "input"); control.setAttribute("data-field-path", location); control.setAttribute("aria-label", title(String(scalarKey)) + " at " + location);
      if (type === "boolean" || allowed) {
        const first = node("option", "Not supplied"); first.value = ""; control.append(first);
        const options = type === "boolean" ? [["true", "Yes / true"], ["false", "No / false"]] : allowed.map((entry) => [entry, title(entry)]);
        if (value !== null && !options.some(([entry]) => entry === String(value))) options.push([String(value), String(value)]);
        options.forEach(([entry, text]) => { const option = node("option", text); option.value = entry; control.append(option); });
      } else { control.type = "text"; control.placeholder = "Not supplied"; if (type === "integer") control.inputMode = "numeric"; }
      control.value = value === null ? "" : String(value);
      control.addEventListener(type === "boolean" || allowed ? "change" : "input", () => action(() => {
        assertCurrent(); const supplied = control.value;
        // No implicit zero or boolean false. Invalid count text reaches backend validation.
        object[key] = supplied === "" ? null : type === "boolean" ? supplied === "true" ? true : supplied === "false" ? false : supplied : type === "integer" && /^-?\d+$/.test(supplied) && Number.isSafeInteger(Number(supplied)) ? Number(supplied) : supplied;
        commit(); if (scalarKey === "requirement_id") render();
      }));
      label.append(control); if (type === "integer") label.append(node("small", "Whole-number literal")); else if (/_at$/.test(String(scalarKey))) label.append(node("small", "UTC · YYYY-MM-DDTHH:MM:SSZ"));
      parent.append(label);
    }
    const customTypes = new Map();
    // The caller's strict parser rejects duplicate keys and lossy numeric literals.
    model = parse(raw); render();
    return { clear: () => { model = null; baseline = ""; customTypes.clear(); container.replaceChildren(); } };
  }
  window.ComputeDrafts = Object.freeze({ template: (kind) => own(templates, kind)?.(), mount });
})();
