/* Structural request editors. No prices, credit estimates or commercial defaults. */
(() => {
  "use strict";
  const own = (object, key) => Object.prototype.hasOwnProperty.call(object, key) ? object[key] : undefined;
  const blank = (...keys) => Object.fromEntries(keys.map((key) => [key, null]));
  const cash = () => ({ ...blank("legal_entity_id", "cash_account_id", "currency", "opening_cash", "start_date", "end_date"), events: [], reserves: [], facility: null });
  const commercial = () => ({ ...blank("currency", "exclusive_node_gpu_count", "buyer_billed_gpu_hours", "buyer_rate", "supplier_ask", "collection_share", "fee_on_collected", "fee_on_gross", "required_margin", "margin_basis", "tick_size", "market_discount", "stress_price_cap"), cost_owners: {}, costs: [] });
  const templates = {
    pricing: () => ({ market: { ...blank("request_id", "as_of"), observations: [], policy: null }, target: { ...blank("scope", "currency", "hardware_model", "country_code", "gpu_count", "duration_hours", "starts_at", "ends_at"), configuration: {} }, commercial: null, cash_template: null, pricing_provenance: { mode: "declared_scenario", policy_revision: null }, extensions: {} }),
  };
  const objectShapes = {
    commercial, cash_template: () => ({ minimum_cash: null, deal_event_ids: [], purchase_coefficients: {}, schedule: cash() }),
    pricing_provenance: () => ({ mode: "declared_scenario", policy_revision: null }),
    facility: () => blank("facility_id", "currency", "committed_limit", "opening_outstanding", "opening_drawn_total", "opening_accrued_interest", "annual_rate", "available_from", "maturity_date", "day_count", "revolving"),
    policy: () => ({ ...blank("policy_id", "version", "model_version", "registry_version", "effective_at", "expires_at"), parameters: { benchmark: { ...blank("estimator", "max_source_share", "max_provider_share", "min_observations", "min_sources", "min_provider_groups"), source_rules: {} } } }),
  };
  const arrayShapes = {
    events: () => blank("event_id", "obligation_id", "on", "kind", "amount", "currency", "invoice_id", "advance_account"),
    reserves: () => blank("reserve_id", "coverage_id", "amount", "start_date", "end_date"),
    costs: () => blank("id", "channel", "owner_model", "amount", "basis", "kind"),
  };
  const integerKeys = new Set(["min_observations", "min_sources", "min_provider_groups", "reservation_months"]);
  const booleanKeys = new Set(["revolving", "required", "enabled"]);
  const enums = { margin_basis: ["gross_billings", "collected_revenue"], estimator: ["weighted_median", "weighted_mean"], day_count: ["ACT/365F", "ACT/360"] };
  const labels = { pricing_provenance: "Source evidence binding", policy_revision: "Saved policy revision", gpu_count: "Allocated GPU count", duration_hours: "Supply duration (hours)", hardware_model: "Hardware model / exact SKU", country_code: "Country code (ISO)", fee_on_collected: "Fee / collected revenue (fraction)", fee_on_gross: "Fee / gross billings (fraction)", collection_share: "Expected collection (fraction)", exclusive_node_gpu_count: "GPUs per exclusive node", buyer_billed_gpu_hours: "Buyer billed GPU-hours", buyer_rate: "Buyer rate / GPU-hour", supplier_ask: "Supplier ask / GPU-hour", tick_size: "Price tick / GPU-hour", minimum_free_cash: "Minimum unrestricted cash", gross_billings: "Gross billings", expected_collections: "Expected collections", nonpurchase_cost: "Nonpurchase cost", policy_capital: "Policy capital", cost_owners: "Cost channel ownership", evidence_refs: "Supporting evidence pointers", cash_template: "Dated pricing cash path" };
  const title = (key) => own(labels, key) || key.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
  const node = (tag, text, className) => { const result = document.createElement(tag); if (text !== undefined) result.textContent = text; if (className) result.className = className; return result; };
  const forbiddenKey = (key) => ["__proto__", "constructor", "prototype"].includes(key);
  function choices(key, path) {
    if (key === "mode" && path.includes("pricing_provenance")) return ["declared_scenario", "retained_market"];
    if (key === "scope" && path.includes("target")) return ["physical_offer", "aggregate_reference"];
    if (key === "kind" && path.includes("events")) return ["buyer_invoice", "supplier_invoice", "revenue", "expense", "buyer_receipt", "buyer_deposit", "deposit_apply", "deposit_refund", "supplier_prepayment", "prepaid_apply", "supplier_payment", "other_inflow", "other_outflow", "facility_draw", "facility_repay", "facility_release", "facility_interest"];
    if (key === "kind" && path.includes("costs")) return ["expected_cost", "policy_capital"];
    if (key === "basis" && path.includes("costs")) return ["fixed_contract", "supply_gpu_hour", "fraction_of_supply_purchase"];
    return own(enums, key);
  }
  function mount(container, documentValue, { parse, changed, message, raw, readRaw }) {
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
          const group = node("details", undefined, "input-group"); group.open = !["extensions", "market"].includes(key);
          group.append(node("summary", title(key))); draw(group, model, key, [key], 0); container.append(group);
        } else { const field = node("div", undefined, "input-group scalar-group"); draw(field, model, key, [key], 0); container.append(field); }
      });
    }
    function draw(parent, object, key, path, depth) {
      rendered++; if (rendered > 1600 || depth > 8) throw new Error("This request exceeds the structured editor budget. Use advanced JSON for the complete packet.");
      const value = object[key]; const location = path.join(".");
      if (Array.isArray(value)) {
        if (value.length > 40 || key === "observations") { parent.append(node("p", value.length + " retained entries. Edit this evidence packet in advanced JSON; fields preserve it without conversion.", "field-help")); return; }
        value.forEach((item, index) => {
          const row = node("section", undefined, "array-row"); const heading = node("div", undefined, "array-heading"); heading.append(node("strong", title(key) + " " + (index + 1)));
          const remove = node("button", "Remove", "quiet-button"); remove.type = "button"; remove.addEventListener("click", () => action(() => { assertCurrent(); value.splice(index, 1); commit(); render(); })); heading.append(remove); row.append(heading);
          draw(row, value, index, [...path, String(index)], depth + 1); parent.append(row);
        });
        if (!value.length) parent.append(node("p", "No " + title(key).toLowerCase() + " supplied.", "field-help"));
        const add = node("button", "Add " + title(key).toLowerCase(), "secondary-button"); add.type = "button"; add.addEventListener("click", () => action(() => {
          assertCurrent(); let item = own(arrayShapes, key)?.() ?? null;
          value.push(item); commit(); render();
        })); parent.append(add); return;
      }
      if (value && typeof value === "object") {
        const grid = node("div", undefined, "input-grid");
        Object.entries(value).forEach(([childKey, item]) => {
          if (forbiddenKey(childKey)) throw new Error("Unsafe request key. Correct the advanced JSON before editing.");
          if (item && typeof item === "object" || own(objectShapes, childKey)) { const block = node("details", undefined, "nested-input-group"); block.open = !["extensions", "policy"].includes(childKey); block.append(node("summary", title(childKey))); draw(block, value, childKey, [...path, childKey], depth + 1); grid.append(block); }
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
      const type = customTypes.get(JSON.stringify(path)) || (typeof value === "boolean" || booleanKeys.has(scalarKey) ? "boolean" : typeof value === "number" || integerKeys.has(scalarKey) ? "integer" : "string");
      const allowed = choices(scalarKey, path);
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
        commit();
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
