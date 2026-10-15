/* Pricing demonstration, part 2 of 5: how contract terms are named, grouped and drawn as a form.
   The backend lists every field with a path, a type and a label. Where it has only spelled out the key ("Dc tier", "Sla"),
   LABELS gives the proper wording. A field the maps do not know keeps the backend's label and lands in the last section of
   its group, so a field added on the server appears in the form without a code change here. */
(() => {
  "use strict";
  const P = window.PricingDemo;
  const { h, num, percent, humanize } = P;

  const GROUP_LABELS = { provider: "Provider", capacity: "Hardware and site", pricing: "Pricing and costs", settlement: "Settlement", treasury: "Funding dates" };

  /* path: [label, unit, short help]. Units sit beside the value; help stays to one short sentence. */
  const FRACTION = "fraction";
  const PER_HOUR = "USD per GPU-hour";
  const META = {
    "provider.id": ["Provider ID"],
    "provider.label": ["Provider name"],
    "provider.credit_score": ["Credit score", "of 100", "Declared, not verified. Not a default probability."],
    "provider.credit_band": ["Credit band", "", "Declared classification, separate from verified credit."],
    "provider.uptime_fraction": ["Uptime", FRACTION, "Declared history. Does not replace billed utilization."],
    "provider.sla_fraction": ["SLA commitment", FRACTION, "Contract assertion, not verified."],
    "provider.response_hours": ["Response time", "hours", "Declared commitment."],
    "provider.compliance": ["Compliance claim"],
    "provider.privacy": ["Privacy claim"],
    "provider.evidence_basis": ["Evidence basis"],
    "provider.ratings.certification": ["Certification", "0 to 4"],
    "provider.ratings.dc_tier": ["Data center tier", "0 to 4"],
    "provider.ratings.sla": ["SLA", "0 to 4"],
    "provider.ratings.delivery": ["Delivery record", "0 to 4"],
    "provider.ratings.credit": ["Credit", "0 to 4"],
    "provider.ratings.responsiveness": ["Responsiveness", "0 to 4"],
    "capacity.model": ["GPU model"],
    "capacity.memory_gib": ["GPU memory", "GiB"],
    "capacity.gpus_per_node": ["GPUs per node", "GPUs"],
    "capacity.node_count": ["Nodes", "nodes"],
    "capacity.cpu_cores": ["CPU cores", "cores"],
    "capacity.ram_gib": ["System memory", "GiB"],
    "capacity.network_gbps": ["Network", "Gbps"],
    "capacity.interconnect": ["Interconnect"],
    "capacity.country_code": ["Country", "ISO code"],
    "capacity.location": ["Region"],
    "capacity.colocation": ["Facility"],
    "capacity.ownership": ["Ownership"],
    "capacity.starts_at": ["Service starts", "UTC", "For example 2027-02-01T00:00:00Z."],
    "capacity.ends_at": ["Service ends", "UTC", "For example 2027-03-03T00:00:00Z."],
    "pricing.supplier_rate": ["Supplier price", PER_HOUR],
    "pricing.rate_type": ["Rate type"],
    "pricing.variable_low": ["Variable range, low", PER_HOUR],
    "pricing.variable_high": ["Variable range, high", PER_HOUR],
    "pricing.buyer_rate": ["Buyer price", PER_HOUR],
    "pricing.billed_utilization": ["Billed utilization", FRACTION, "Share of supplier capacity billed to the buyer."],
    "pricing.collection_share": ["Collection share", FRACTION, "Share of billings expected to be collected."],
    "pricing.fee_on_collected": ["Fee on collections", FRACTION],
    "pricing.fee_on_gross": ["Fee on billings", FRACTION],
    "pricing.required_margin": ["Required margin", FRACTION],
    "pricing.target_margin": ["Target margin", FRACTION],
    "pricing.tick_size": ["Price tick", "USD"],
    "pricing.fixed_operating_cost": ["Fixed operating cost", "USD"],
    "pricing.risk_allowance_per_gpu_hour": ["Capital budget", PER_HOUR, "The one capital-budget channel. No extra grade or location premium."],
    "pricing.discount_apr": ["Discount rate (APR)", FRACTION, "Simple annual rate for NPV."],
    "pricing.power.inclusion": ["Power in the price", "", "Included adds no cost. Excluded adds it once."],
    "pricing.power.payer": ["Power payer", "", "The model supports the broker paying."],
    "pricing.power.tariff_per_kwh": ["Power tariff", "USD per kWh"],
    "pricing.power.idle_watts_per_gpu": ["Idle power per GPU", "W"],
    "pricing.power.load_watts_per_gpu": ["Load power per GPU", "W"],
    "pricing.power.shared_it_watts": ["Shared host power", "W"],
    "pricing.power.pue": ["PUE", "ratio"],
    "pricing.power.utilization": ["Power utilization", FRACTION],
    "surface.annual_volatility": ["Annual rate volatility", FRACTION, "Declared and unfitted, not a market estimate."],
    "surface.tenor_days": ["Tenors", "days", "Whole days from 1 to 365, comma-separated. At most 12."],
    "surface.shocks": ["Rate shocks", "std. dev.", "From -3 to 3, comma-separated. At most 9."],
    "surface.collection_shocks": ["Collection-share cuts", FRACTION, "From 0 to 1, comma-separated. At most 9."],
    "settlement.mode": ["Settlement mode"],
    "settlement.buyer_label": ["Buyer name"],
    "settlement.down_payment_fraction": ["Supplier deposit", FRACTION, "Share of the supplier cost paid before service."],
    "settlement.financing_apr": ["Deposit financing rate (APR)", FRACTION, "Simple annual rate. A scenario, not a lender quote."],
    "settlement.provider_collateral_usd": ["Provider collateral", "USD", "Proposed. Never usable as cash."],
    "settlement.collateral_fraction": ["Collateral share", FRACTION, "Of the largest provider obligation."],
    "settlement.buffer_hours": ["Buffer", "hours"],
    "settlement.vesting_basis": ["Vesting basis"],
    "settlement.prefunded_principal": ["Prefunded principal", "asset units"],
    "settlement.asset_kind": ["Escrow asset"],
    "settlement.asset_unit": ["Asset unit"],
    "settlement.asset_price_usd": ["Asset price", "USD per unit", "Declared mark, not verified."],
    "settlement.liquidity": ["Liquidity"],
    "settlement.depeg_status": ["Depeg status"],
    "settlement.service_basis": ["Service basis"],
    "settlement.service_fraction": ["Service delivered", FRACTION],
    "settlement.release_authorized": ["Principal release authorized"],
    "settlement.refund_at_end": ["Refund remainder at end"],
    "settlement.yield_apr": ["Yield rate (APR)", FRACTION, "A hypothesis, not a current account rate."],
    "settlement.yield_access": ["Yield access"],
    "settlement.yield_share_provider": ["Provider yield share", FRACTION, "The three shares sum to 1."],
    "settlement.yield_share_broker": ["Broker yield share", FRACTION],
    "settlement.yield_share_buyer": ["Buyer yield share", FRACTION],
    "treasury.opening_cash": ["Opening cash", "USD"],
    "treasury.minimum_cash": ["Minimum cash floor", "USD"],
    "treasury.supplier_payment_on": ["Supplier deposit paid", "date"],
    "treasury.supplier_balance_on": ["Supplier balance paid", "date"],
    "treasury.buyer_invoice_on": ["Buyer invoiced", "date"],
    "treasury.buyer_receipt_on": ["Buyer pays", "date"],
    "treasury.operating_cost_on": ["Operating costs paid", "date"],
    "treasury.fees_on": ["Fees paid", "date"],
    "treasury.writeoff_on": ["Uncollected balance written off", "date"],
  };

  const YES_NO = { true: "Yes", false: "No" };
  const UNKNOWN_CHOICES = { unknown: "Unknown" };
  const CHOICES = {
    "provider.credit_band": { strong: "Strong", balanced: "Balanced", weak: "Weak", ...UNKNOWN_CHOICES },
    "capacity.ownership": { owned: "Owned", leased: "Leased", mixed: "Mixed", ...UNKNOWN_CHOICES },
    "pricing.rate_type": { fixed: "Fixed", variable: "Variable" },
    "pricing.power.inclusion": { included: "Included (no added cost)", excluded: "Excluded (cost added once)", ...UNKNOWN_CHOICES },
    "pricing.power.payer": { broker: "Broker", provider: "Provider", buyer: "Buyer", ...UNKNOWN_CHOICES },
    "settlement.mode": { upfront: "Upfront", milestone: "Milestone", hourly_escrow: "Hourly escrow" },
    "settlement.asset_kind": { bank_deposit: "Bank deposit", stable_asset: "Stable asset" },
    "settlement.liquidity": { liquid: "Liquid", illiquid: "Illiquid", ...UNKNOWN_CHOICES },
    "settlement.depeg_status": { not_applicable: "Not applicable", normal: "Normal", depegged: "Depegged", ...UNKNOWN_CHOICES },
    "settlement.yield_access": { hourly_withdrawable: "Withdrawable hourly", accrued_only: "Accrued only", ...UNKNOWN_CHOICES },
    "settlement.service_basis": { delivered: "Delivered service", available_sla: "Available under SLA" },
    "pricing.risk_cost_owner": { "demo:declared-capital-budget": "Declared capital budget" },
    "pricing.power.cost_owner": { "allocated-power-cost/1.0.0": "Allocated power cost model" },
    "settlement.collateral_owner": { provider_restricted_performance_security: "Provider restricted performance security" },
  };
  const WIDE = new Set(["surface.tenor_days", "surface.shocks", "surface.collection_shocks", "provider.label", "provider.compliance", "provider.privacy", "provider.evidence_basis", "capacity.interconnect", "capacity.colocation", "settlement.buyer_label", "settlement.vesting_basis"]);

  const SECTIONS = {
    provider: [
      ["Counterparty", ["provider.id", "provider.label", "provider.credit_band", "provider.credit_score"]],
      ["Declared service", ["provider.uptime_fraction", "provider.sla_fraction", "provider.response_hours"]],
      ["Claims", ["provider.compliance", "provider.privacy", "provider.evidence_basis"]],
      ["Quality ratings", ["provider.ratings.certification", "provider.ratings.dc_tier", "provider.ratings.sla", "provider.ratings.delivery", "provider.ratings.credit", "provider.ratings.responsiveness"]],
    ],
    capacity: [
      ["Hardware", ["capacity.model", "capacity.memory_gib", "capacity.gpus_per_node", "capacity.node_count", "capacity.cpu_cores", "capacity.ram_gib", "capacity.network_gbps", "capacity.interconnect"]],
      ["Site", ["capacity.country_code", "capacity.location", "capacity.colocation", "capacity.ownership"]],
      ["Service window", ["capacity.starts_at", "capacity.ends_at"]],
    ],
    pricing: [
      ["Prices", ["pricing.supplier_rate", "pricing.rate_type", "pricing.variable_low", "pricing.variable_high", "pricing.buyer_rate", "pricing.billed_utilization", "pricing.collection_share"]],
      ["Margins and fees", ["pricing.required_margin", "pricing.target_margin", "pricing.fee_on_collected", "pricing.fee_on_gross", "pricing.tick_size"]],
      ["Operating costs", ["pricing.fixed_operating_cost", "pricing.risk_allowance_per_gpu_hour", "pricing.discount_apr"]],
      ["Power", ["pricing.power.inclusion", "pricing.power.payer", "pricing.power.tariff_per_kwh", "pricing.power.idle_watts_per_gpu", "pricing.power.load_watts_per_gpu", "pricing.power.shared_it_watts", "pricing.power.pue", "pricing.power.utilization"]],
      ["Sensitivity grid", ["surface.annual_volatility", "surface.tenor_days", "surface.shocks", "surface.collection_shocks"]],
    ],
    settlement: [
      ["Payment", ["settlement.mode", "settlement.buyer_label", "settlement.down_payment_fraction", "settlement.financing_apr"]],
      ["Protection", ["settlement.provider_collateral_usd", "settlement.collateral_fraction", "settlement.buffer_hours", "settlement.vesting_basis"]],
      ["Hourly escrow", ["settlement.asset_kind", "settlement.asset_unit", "settlement.asset_price_usd", "settlement.prefunded_principal", "settlement.liquidity", "settlement.depeg_status", "settlement.service_basis", "settlement.service_fraction", "settlement.release_authorized", "settlement.refund_at_end"]],
      ["Yield", ["settlement.yield_apr", "settlement.yield_access", "settlement.yield_share_provider", "settlement.yield_share_broker", "settlement.yield_share_buyer"]],
    ],
    treasury: [
      ["Opening position", ["treasury.opening_cash", "treasury.minimum_cash"]],
      ["Payment dates", ["treasury.supplier_payment_on", "treasury.supplier_balance_on", "treasury.buyer_invoice_on", "treasury.buyer_receipt_on", "treasury.operating_cost_on", "treasury.fees_on", "treasury.writeoff_on"]],
    ],
  };

  const labelFor = (path, fallback) => (META[path] && META[path][0]) || fallback || humanize(path.split(".").pop());
  const unitFor = (path) => (META[path] && META[path][1]) || "";
  const groupLabel = (group) => GROUP_LABELS[group.id] || group.label;
  function choiceLabel(path, value) {
    if (value === null || value === undefined || value === "") return P.NOT_SUPPLIED;
    if (typeof value === "boolean") return YES_NO[String(value)];
    const table = CHOICES[path];
    return table && Object.hasOwn(table, String(value)) ? table[String(value)] : humanize(String(value));
  }
  function helpFor(field) {
    const entry = META[field.path];
    if (entry && entry[2]) return entry[2];
    return typeof field.help === "string" && field.help.length <= 100 ? field.help : "";
  }

  /* The editable fields of one group, in section order. Returns [{ title, fields }]. */
  function sectionsFor(contract, groupId) {
    const fields = contract.fields.filter((field) => field.group === groupId && field.editable !== false);
    const byPath = new Map(fields.map((field) => [field.path, field]));
    const used = new Set(); const out = [];
    (SECTIONS[groupId] || []).forEach(([title, paths]) => {
      const members = paths.filter((path) => byPath.has(path)).map((path) => { used.add(path); return byPath.get(path); });
      if (members.length) out.push({ title, fields: members });
    });
    const rest = fields.filter((field) => !used.has(field.path));
    if (rest.length) out.push({ title: out.length ? "Other terms" : "Terms", fields: rest });
    return out;
  }

  const valueAt = (object, path) => path.split(".").reduce((value, key) => (value === null || value === undefined ? null : value[key]), object);
  function put(object, path, value) {
    const keys = path.split("."); const last = keys.pop();
    const parent = keys.reduce((node, key) => node[key] || (node[key] = {}), object);
    parent[last] = value;
  }
  const isBlank = (value) => value === null || value === undefined || value === "" || (Array.isArray(value) && value.every((item) => item === null || item === ""));

  /* What the person typed, as the value the backend expects. Validation stays with the backend. */
  function parse(field, raw) {
    if (raw === "") return null;
    if (field.type === "boolean") return raw === "true";
    if (field.type === "integer") return /^\d+$/.test(raw) && Number.isSafeInteger(Number(raw)) ? Number(raw) : raw;
    if (field.type === "decimal_list") return raw.split(",").map((item) => item.trim());
    return raw;
  }
  const display = (value) => (value === null || value === undefined ? "" : Array.isArray(value) ? value.join(", ") : String(value));
  const fieldId = (path) => "pd-f-" + path.replaceAll(".", "-");

  /* A fraction shows what it means as a percentage while it is typed: 0.9995 reads 99.95%. */
  function unitText(path, raw) {
    const unit = unitFor(path);
    if (unit !== FRACTION) return unit;
    const value = num(raw);
    return value !== null && value >= 0 && value <= 1 ? percent(value, 4) : "0 to 1";
  }

  function controlFor(field, value, disabled) {
    const choices = Array.isArray(field.choices) && field.choices.length ? field.choices.map((item) => (typeof item === "object" ? item.value : item)) : field.type === "boolean" ? [true, false] : null;
    const id = fieldId(field.path);
    let input;
    if (choices) {
      input = h("select"); input.id = id;
      const blank = h("option", "", P.NOT_SUPPLIED); blank.value = ""; input.append(blank);
      choices.forEach((choice) => { const option = h("option", "", choiceLabel(field.path, choice)); option.value = String(choice); input.append(option); });
    } else {
      input = h("input"); input.id = id; input.type = "text"; input.autocomplete = "off"; input.spellcheck = false;
      input.inputMode = field.type === "decimal" || field.type === "decimal_list" ? "decimal" : field.type === "integer" ? "numeric" : "text";
      input.placeholder = field.type === "utc" ? "YYYY-MM-DDTHH:MM:SSZ" : field.type === "date" ? "YYYY-MM-DD" : field.type === "decimal_list" ? "Comma-separated" : P.NOT_SUPPLIED;
    }
    input.value = display(value); input.disabled = disabled;
    input.dataset.path = field.path;
    return input;
  }

  /* Draw one group's sections into `target`. Returns the inputs by path so the caller can focus the first one left blank.
     options: { contract, group, draft, invalid: Set of paths, disabled, onChange(field, value) } */
  function renderForm(target, options) {
    const { contract, group, draft, invalid = new Set(), disabled = false, onChange } = options;
    const inputs = new Map();
    target.replaceChildren();
    sectionsFor(contract, group).forEach((section) => {
      const block = h("section", "pd-fieldset"); const heading = h("h3", "pd-set-title", section.title);
      heading.id = "pd-sec-" + group + "-" + section.title.toLowerCase().replace(/[^a-z0-9]+/g, "-"); block.setAttribute("role", "group"); block.setAttribute("aria-labelledby", heading.id); block.append(heading);
      const grid = h("div", "pd-field-grid");
      section.fields.forEach((field) => {
        const value = draft ? valueAt(draft, field.path) : null;
        const wide = WIDE.has(field.path) || (field.type === "text" && display(value).length > 30);
        const wrapper = h("div", "pd-field" + (wide ? " is-wide" : "") + (invalid.has(field.path) ? " is-missing" : ""));
        const label = h("label", "", labelFor(field.path, field.label)); label.setAttribute("for", fieldId(field.path));
        const input = controlFor(field, value, disabled);
        const box = h("div", "pd-control" + (input.tagName.toLowerCase() === "select" ? " is-select" : ""));
        box.append(input);
        let unit = null;
        if (input.tagName.toLowerCase() !== "select" && unitFor(field.path)) { unit = h("span", "pd-unit", unitText(field.path, input.value)); box.append(unit); }
        wrapper.append(label, box);
        const help = helpFor(field);
        if (help) { const note = h("p", "pd-help", help); note.id = fieldId(field.path) + "-help"; input.setAttribute("aria-describedby", note.id); wrapper.append(note); }
        if (invalid.has(field.path)) input.setAttribute("aria-invalid", "true");
        input.addEventListener("input", () => {
          if (unit) unit.textContent = unitText(field.path, input.value);
          if (invalid.has(field.path) && input.value !== "") { invalid.delete(field.path); wrapper.classList.remove("is-missing"); input.removeAttribute("aria-invalid"); }
          onChange(field, parse(field, input.value));
        });
        // A select cannot hold a value that is not one of its options; the blank option stands for "not supplied".
        inputs.set(field.path, input); grid.append(wrapper);
      });
      block.append(grid); target.append(block);
    });
    return inputs;
  }

  P.fields = Object.freeze({ GROUP_LABELS, META, CHOICES, SECTIONS, labelFor, unitFor, groupLabel, choiceLabel, helpFor, sectionsFor, valueAt, put, isBlank, parse, display, fieldId, unitText, renderForm });
})();
