/* Backend-owned scenarios, explicit contract inputs and a saved assessment. */
(() => {
  "use strict";
  const host = window.ComputeHost;
  if (!host) return;
  const $ = (id) => document.getElementById(id);
  const state = { contract: null, draft: null, assessedInput: null, selected: "", group: "provider", receipt: null, busy: false, generation: 0, references: [] };
  const valueAt = (object, path) => path.split(".").reduce((value, key) => value == null ? null : value[key], object);
  function put(object, path, value) { const keys = path.split("."); const last = keys.pop(); const parent = keys.reduce((node, key) => node[key] || (node[key] = {}), object); parent[last] = value; }
  const finite = (value) => value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value));
  const usd = (value, digits = 2) => finite(value) ? "$" + Number(value).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits }) : "Unknown";
  const percent = (value) => finite(value) ? (Number(value) * 100).toFixed(1) + "%" : "Unknown";
  const label = (key) => key.replaceAll("_", " ").replace(/^./, (s) => s.toUpperCase());
  function node(tag, className, text) { const el = document.createElement(tag); if (className) el.className = className; if (text !== undefined) el.textContent = text; return el; }
  function status(message, error = false) { $("pd-input-state").textContent = message; $("pd-input-state").classList.toggle("pd-inline-error", error); }
  function busy(on) { state.busy = on; $("pd-evaluate").disabled = on || !state.draft || !host.isSession(); $("pd-evaluate").textContent = on ? "Evaluating…" : "Evaluate contract"; $("pd-blank").disabled = on; document.querySelectorAll(".pd-example button,#pd-fields input,#pd-fields select").forEach((el) => { el.disabled = on || !host.isSession(); }); }
  function renderExamples() {
    const target = $("pd-examples"); target.replaceChildren();
    state.contract.scenarios.forEach((example, index) => {
      const card = node("article", "pd-example"); card.dataset.selected = String(state.selected === example.id);
      card.append(node("span", "pd-example-index", "0" + (index + 1)), node("h3", "", example.label), node("p", "", example.summary));
      const actions = node("div", "pd-example-actions");
      const use = node("button", "secondary-button", "Edit terms"); use.type = "button"; use.addEventListener("click", () => loadExample(example.id));
      const simulate = node("button", "primary-button", "Simulate"); simulate.type = "button"; simulate.dataset.scenario = example.id;
      simulate.addEventListener("click", async () => { loadExample(example.id); await evaluate(); });
      actions.append(use, simulate); card.append(actions); target.append(card);
    });
    busy(state.busy);
  }
  function renderTabs() {
    const target = $("pd-tabs"); target.replaceChildren();
    state.contract.groups.forEach((group) => {
      const button = node("button", "", group.label); button.type = "button"; button.setAttribute("role", "tab"); button.setAttribute("aria-selected", String(state.group === group.id));
      button.addEventListener("click", () => { state.group = group.id; renderTabs(); renderFields(); }); target.append(button);
    });
  }
  function renderFields() {
    const target = $("pd-fields"); target.replaceChildren();
    state.contract.fields.filter((field) => field.group === state.group && field.editable !== false).forEach((field) => {
      const wrapper = node("label", "pd-field"); wrapper.append(node("span", "", field.label));
      const choices = Array.isArray(field.choices) && field.choices.length ? field.choices : (field.type === "boolean" ? [{ value: true, label: "Yes" }, { value: false, label: "No" }] : null);
      const input = node(choices ? "select" : "input"); input.dataset.path = field.path;
      if (choices) {
        const blank = node("option", "", "Unknown / not supplied"); blank.value = ""; input.append(blank);
        choices.forEach((choice) => { const item = typeof choice === "object" ? choice : { value: choice, label: String(choice) }; const option = node("option", "", item.label || String(item.value)); option.value = String(item.value); input.append(option); });
      } else { input.type = "text"; input.inputMode = ["decimal", "integer"].includes(field.type) ? "decimal" : "text"; input.autocomplete = "off"; }
      const value = state.draft ? valueAt(state.draft, field.path) : null; input.value = value === null || value === undefined ? "" : Array.isArray(value) ? value.join(", ") : String(value);
      input.addEventListener("input", () => {
        if (!state.draft) state.draft = structuredClone(state.contract.template);
        let value = input.value;
        if (value === "") value = null;
        else if (field.type === "boolean") value = value === "true";
        else if (field.type === "integer") value = /^\d+$/.test(value) && Number.isSafeInteger(Number(value)) ? Number(value) : value;
        else if (field.type === "decimal_list") value = value.split(",").map((item) => item.trim());
        put(state.draft, field.path, value); status("Edited terms · evaluate to create a new assessment"); if (field.path === "capacity.model" || field.path === "capacity.gpu_model") refreshReferences(); busy(state.busy);
      });
      wrapper.append(input); input.title = input.value; if (String(input.value).length > 48) wrapper.classList.add("pd-field-wide"); if (field.help) wrapper.append(node("small", "", field.help)); target.append(wrapper);
    });
  }
  function loadExample(id) {
    const example = state.contract.scenarios.find((row) => row.id === id); if (!example) return;
    state.draft = structuredClone(example.inputs); state.selected = id;
    $("pd-selected").textContent = example.label + " · independently invented terms";
    status("All example fields populated · edit any term or evaluate"); renderExamples(); renderTabs(); renderFields(); refreshReferences(); busy(false);
  }
  function referenceTable(rows, compact = false) {
    if (!rows.length) return node("p", "empty-state", "No permitted current reference matches this hardware. The scenario remains separately priced.");
    const table = node("table", "pd-reference-table"); const head = node("thead"); const tr = node("tr");
    (compact ? ["Source", "Native rate"] : ["Source / provider", "Hardware & terms", "Native rate", "Observed"]).forEach((text) => tr.append(node("th", "", text))); head.append(tr); table.append(head);
    const body = node("tbody"); rows.slice(0, compact ? 5 : 14).forEach((row) => {
      const line = node("tr"); const name = node("td", "", row.provider || row.source_id); name.append(node("small", "", row.status || "published reference")); line.append(name);
      if (!compact) line.append(node("td", "", (row.hardware_model || "") + " · " + (row.terms || row.kind || "reference")));
      const rate = node("td", "pd-money", finite(row.amount) ? Number(row.amount).toLocaleString("en-US", {minimumFractionDigits:3,maximumFractionDigits:3}) : "Unknown"); rate.append(node("small", "", (row.currency || "USD") + " / " + (row.unit || "unknown"))); line.append(rate);
      if (!compact) line.append(node("td", "", row.observed_at ? row.observed_at.slice(0, 16).replace("T", " ") + " UTC" : "Unknown")); body.append(line);
    }); table.append(body); return table;
  }
  async function refreshReferences() {
    const model = valueAt(state.draft, "capacity.gpu_model") || valueAt(state.draft, "capacity.model");
    $("pd-market-context").textContent = model ? model + " · retained source observations" : "Select hardware to inspect permitted current references.";
    if (!model || !host.isSession()) return;
    const generation = state.generation;
    try { const result = await host.api("/v1/pricing/demo/references?hardware_model=" + encodeURIComponent(model)); if (generation !== state.generation || model !== (valueAt(state.draft, "capacity.gpu_model") || valueAt(state.draft, "capacity.model"))) return; state.references = result.references; $("pd-live-rates").replaceChildren(referenceTable(result.references, true)); }
    catch (error) { $("pd-live-rates").replaceChildren(node("p", "pd-note", "References unavailable: " + error.message)); }
  }
  function kpis(target, items) { target.replaceChildren(); items.forEach(([title, value, help]) => { const item = node("div", "pd-kpi"); item.append(node("span", "", title), node("strong", "", value), node("small", "", help)); target.append(item); }); }
  function terms(target, entries) { const list = node("dl", "pd-term-list"); entries.forEach(([key, value]) => { const row = node("div"); row.append(node("dt", "", label(key)), node("dd", "", value === null || value === undefined ? "Unknown" : typeof value === "object" ? JSON.stringify(value) : String(value))); list.append(row); }); target.replaceChildren(list); }
  function bars(target, values) {
    target.replaceChildren(); const max = Math.max(0.001, ...values.filter((v) => finite(v[1])).map((v) => Number(v[1])));
    values.forEach(([name, value]) => { const bar = node("div", "pd-bar"); const track = node("div", "pd-bar-track"); const fill = node("div", "pd-bar-fill"); fill.style.width = Math.max(0, Math.min(100, Number(value || 0) / max * 100)) + "%"; track.append(fill); bar.append(node("span", "", name), track, node("span", "pd-bar-value", usd(value, 3))); target.append(bar); });
  }
  function lineChart(target, points, series) {
    target.replaceChildren(); if (!points || points.length < 2) { target.append(node("p", "empty-state", "No hourly path for this settlement mode.")); return; }
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg"); svg.setAttribute("viewBox", "0 0 580 240"); svg.setAttribute("class", "pd-line-chart"); svg.setAttribute("role", "img"); svg.setAttribute("aria-label", series.map((row) => row.label).join(", "));
    const values = series.flatMap((row) => points.map((p) => p[row.key])).filter(finite).map(Number); const min = Math.min(0, ...values); const max = Math.max(1, ...values); const range = max - min || 1;
    const x = (i) => 56 + i / (points.length - 1) * 500; const y = (value) => 210 - (Number(value) - min) / range * 190;
    function add(tag, attrs, text) { const el = document.createElementNS(svg.namespaceURI, tag); Object.entries(attrs).forEach(([key, value]) => el.setAttribute(key, String(value))); if (text !== undefined) el.textContent = text; svg.append(el); }
    for (let n = 0; n <= 3; n++) { const value = min + range * n / 3; add("line", { x1:56, x2:556, y1:y(value), y2:y(value), class:"pd-grid" }); add("text", { x:50, y:y(value) + 4, "text-anchor":"end" }, "$" + Number(value).toLocaleString("en-US", { maximumFractionDigits:0 })); }
    series.forEach((row, index) => { const path = points.map((p, i) => finite(p[row.key]) ? (i ? "L" : "M") + x(i).toFixed(1) + " " + y(p[row.key]).toFixed(1) : "").join(" "); add("path", { d:path, class:"pd-series " + (index === 1 ? "second" : index === 2 ? "third" : "") }); });
    add("text", { x:56, y:235 }, String(points[0].hour ?? points[0].on ?? "Start")); add("text", { x:556, y:235, "text-anchor":"end" }, String(points.at(-1).hour ?? points.at(-1).on ?? "End"));
    const legend = node("div", "pd-chart-legend"); series.forEach((row, i) => { const item = node("span", i === 1 ? "second" : i === 2 ? "third" : ""); item.append(node("i"), document.createTextNode(row.label)); legend.append(item); }); target.append(svg, legend);
  }
  function drawSurface(surface) {
    const canvas = $("pd-surface"); const ctx = canvas.getContext("2d"); if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const data = surface?.points || surface?.nodes || []; const style = getComputedStyle(document.documentElement); const ink = style.getPropertyValue("--muted").trim(); const accent = style.getPropertyValue("--accent").trim();
    ctx.font = "18px ui-monospace, monospace"; ctx.fillStyle = ink;
    if (!data.length) { ctx.fillText("Surface unavailable for these terms", 35, 150); return; }
    const xs = [...new Set(data.map((p) => Number(p.tenor_days ?? p.tenor_months)))].sort((a,b) => a-b); const ys = [...new Set(data.map((p) => Number(p.shock ?? p.volatility ?? p.demand_shock)))].sort((a,b) => a-b); const zs = data.map((p) => Number(p.rate ?? p.price ?? p.amount)); const lo = Math.min(...zs); const hi = Math.max(...zs); const a = Number($("pd-surface-angle").value) * Math.PI / 180;
    const project = (p) => { const x = (xs.indexOf(Number(p.tenor_days ?? p.tenor_months)) / Math.max(1,xs.length-1) - .5) * 450; const y = (ys.indexOf(Number(p.shock ?? p.volatility ?? p.demand_shock)) / Math.max(1,ys.length-1) - .5) * 280; const z = (Number(p.rate ?? p.price ?? p.amount) - lo) / Math.max(.001,hi-lo) * 180; return [450 + x * Math.cos(a) - y * Math.sin(a), 295 + (x * Math.sin(a) + y * Math.cos(a)) * .42 - z]; };
    const at = (x, y) => data.find((p) => Number(p.tenor_days) === x && Number(p.shock) === y);
    const faces = [];
    for(let i=0;i<xs.length-1;i++) for(let j=0;j<ys.length-1;j++) {
      const corners = [at(xs[i],ys[j]),at(xs[i+1],ys[j]),at(xs[i+1],ys[j+1]),at(xs[i],ys[j+1])];
      if(corners.every(Boolean)) faces.push(corners.map(project));
    }
    faces.sort((left,right) => left.reduce((s,p)=>s+p[1],0)-right.reduce((s,p)=>s+p[1],0));
    ctx.fillStyle=accent; ctx.globalAlpha=.13;
    faces.forEach((corners) => { ctx.beginPath(); corners.forEach(([x,y],i) => i ? ctx.lineTo(x,y) : ctx.moveTo(x,y)); ctx.closePath(); ctx.fill(); });
    ctx.strokeStyle = accent; ctx.lineWidth = 1.4; ctx.globalAlpha = .75;
    const lines = [...xs.map((value) => data.filter((p) => Number(p.tenor_days ?? p.tenor_months) === value)), ...ys.map((value) => data.filter((p) => Number(p.shock ?? p.volatility ?? p.demand_shock) === value))];
    lines.forEach((points) => { ctx.beginPath(); points.forEach((p,i) => { const [x,y] = project(p); if(i) ctx.lineTo(x,y); else ctx.moveTo(x,y); }); ctx.stroke(); }); ctx.globalAlpha = 1;
    ctx.fillStyle = ink; ctx.fillText("Tenor · " + xs[0] + "–" + xs.at(-1) + " days", 45, 410); ctx.fillText("Rate · " + usd(lo) + "–" + usd(hi) + "/GPU-h", 500, 410);
    ctx.font="15px ui-monospace, monospace"; ctx.fillText("Standardized shock · " + ys[0] + " to +" + ys.at(-1),45,443);
    $("pd-surface-accessible").textContent = "Illustrative sensitivity surface from " + xs[0] + " to " + xs.at(-1) + " days, rates " + usd(lo) + " to " + usd(hi) + " per GPU hour.";
  }
  function renderResult() {
    const r = state.receipt.result; const s = r.summary;
    const draft = state.assessedInput;
    $("pd-dialog-title").textContent = draft.provider.label + " · " + draft.capacity.model;
    $("pd-dialog-subtitle").textContent = draft.capacity.location + " · " + draft.capacity.node_count + " nodes × " + draft.capacity.gpus_per_node + " GPUs · USD per GPU-hour";
    $("pd-modal-status").textContent = r.status === "held" ? "Assessment held · " + r.hold_reasons.map(label).join("; ") : "Scenario estimate · " + (s.cash_feasible ? "funded under declared terms" : "additional funding required") + ". Market references and projected yields remain separate.";
    kpis($("pd-kpis"), [["Scenario purchase ceiling",usd(s.purchase_ceiling,3),"Economic limit · not a market bid"],["Minimum selling rate",usd(s.sell_floor,3),"Cost recovery at supplier ask"],["Target selling rate",usd(s.target_ask,3),"Declared target margin"],["Scenario economic profit",usd(s.expected_profit),"After capital budget; before treasury yield"]]);
    bars($("pd-rate-chart"), [["Supplier offer",s.supplier_rate],["Power / GPU-hour",s.power_rate],["Purchase ceiling",s.purchase_ceiling],["Minimum selling rate",s.sell_floor],["Target selling rate",s.target_ask]]);
    terms($("pd-price-explanation"), [["Expected margin",percent(s.expected_margin)],["Quality tier",r.quality?.grade],["Minimum-margin ask",usd(s.minimum_margin_ask,3)],["Settlement",draft.settlement.mode]]);
    $("pd-surface-caption").textContent = r.surface?.label || "Declared volatility and tenor sensitivity; no fitted market forward curve.";
    $("pd-modal-rates").replaceChildren(referenceTable(r.live_references?.references || state.references));
    const e = r.escrow;
    kpis($("pd-cash-kpis"), [["Prefunded / required",usd(e?.prefunding?.declared_value_usd ?? s.cash_required),"Restricted principal kept separate"],["Provider released",usd(e?.settlement?.provider_service_paid_usd),"Hourly qualified service"],["Projected treasury yield",finite(e?.yield?.total_accrued_asset_units) ? Number(e.yield.total_accrued_asset_units).toFixed(4) + " " + e.asset.unit : "Not used","Declared APR · not guaranteed"],["Platform yield share",usd(e?.yield?.broker_economic_entitlement_usd,4),"Accrued entitlement; cash is separate"]]);
    const escrow = (e?.chart?.rows || []).map((row) => ({...row,
      locked_principal: finite(e.asset.declared_price_usd) ? Number(row.closing_restricted_principal_asset_units) * Number(e.asset.declared_price_usd) : null,
      provider_paid: row.cumulative_provider_service_paid_usd,
      broker_paid: Number(row.broker_cash_usd) - Number(e.broker.opening_cash_usd)}));
    lineChart($("pd-escrow-chart"),escrow,[{key:"locked_principal",label:"Principal · declared USD value"},{key:"provider_paid",label:"Provider received"}]);
    const cash = r.cash?.chart_points || r.cash?.days || [];
    lineChart($("pd-cash-chart"),cash,[{key:"free_cash",label:"Free after reserves"},{key:"cash",label:"Cash balance"}]);
    terms($("pd-cash-detail"),e ? [["Refundable principal",e.settlement.refundable_principal_before_terminal_refund_asset_units + " " + e.asset.unit],["Unearned principal available for operations","0 USD"],["Provider unpaid",usd(e.settlement.provider_service_owed_usd)],["Accrued platform yield",usd(e.yield.broker_economic_entitlement_usd,4)],["Platform yield cash received",usd(e.yield.broker_cash_received_usd,4)],["Asset",e.asset.kind + " / " + e.asset.unit],["Full-route funding",s.cash_feasible === true ? "Scenario funded" : s.cash_feasible === false ? "Scenario funding shortfall" : "Unknown liquidity or mark"],["Minimum free cash",usd(r.cash?.minimum_free_cash)],["Additional route funding",usd(s.cash_shortfall)],["Yield access",e.yield.access]] : Object.entries(r.cash?.summary || {}).slice(0,18));
    if(!e) {
      kpis($("pd-cash-kpis"),[["Scenario cash required",usd(s.cash_required),"Purchase, costs and reserve"],["Minimum free cash",usd(r.cash?.minimum_free_cash),"Dated complete route ledger"],["Additional funding",usd(s.cash_shortfall),"To satisfy declared cash floor"],["Net operating cash",usd(s.net_cash_flow),"Before hypothetical treasury yield"]]);
      terms($("pd-cash-detail"),[["Settlement",draft.settlement.mode],["Supplier deposit",percent(draft.settlement.down_payment_fraction)],["Minimum free cash",usd(r.cash?.minimum_free_cash)],["Funding feasibility",s.cash_feasible === true ? "Scenario funded" : s.cash_feasible === false ? "Funding shortfall" : "Unknown"],["Owned capital reserve",usd(s.capital_budget)],["Deposit financing carry",percent(s.financing_carry_fraction)],["NPV",usd(s.npv)],["Ending unresolved balances",r.cash?.unresolved_balances]]);
    }
    terms($("pd-terms"),[["Supplier",draft.provider.label],["Buyer",draft.settlement.buyer_label || "Invented demo buyer"],["Hardware",draft.capacity.model + " / " + draft.capacity.memory_gib + " GiB"],["Physical allocation",draft.capacity.node_count + " nodes × " + draft.capacity.gpus_per_node + " GPUs"],["Site",draft.capacity.location + " / " + draft.capacity.colocation],["Delivery",draft.capacity.starts_at + " to " + draft.capacity.ends_at],["Rate structure",draft.pricing.rate_type],["Supplier / buyer rates",usd(draft.pricing.supplier_rate,3) + " / " + usd(draft.pricing.buyer_rate,3) + " per GPU-hour"],["SLA / responsiveness",percent(draft.provider.sla_fraction) + " / " + draft.provider.response_hours + " hours"],["Power ownership",draft.pricing.power.inclusion],["Settlement",draft.settlement.mode],["Provider security",usd(draft.settlement.provider_collateral_usd) + " pledged; no posting verified"],["Yield entitlement",percent(draft.settlement.yield_share_provider) + " provider / " + percent(draft.settlement.yield_share_broker) + " platform / " + percent(draft.settlement.yield_share_buyer) + " buyer"],["Governing law","Unresolved in public demonstration"]]);
    $("pd-receipt").textContent = "Saved assessment " + state.receipt.snapshot_id.slice(0,12) + " · " + state.receipt.created_at.slice(0,16).replace("T"," ") + " UTC";
    $("pd-pdf").disabled = !r.agreement_terms; $("pd-last-result").replaceChildren(node("h3","","Last assessment"),node("p","",usd(s.sell_floor,3) + "/GPU-h minimum selling rate · " + percent(s.expected_margin) + " expected margin"));
    showResult("quote"); drawSurface(r.surface);
  }
  function showResult(name) { document.querySelectorAll("[data-pd-result]").forEach((el) => el.setAttribute("aria-selected", String(el.dataset.pdResult === name))); ["quote","cash","terms"].forEach((key) => { $("pd-result-"+key).hidden = name !== key; }); }
  async function evaluate() {
    if (state.busy || !state.draft) return;
    const request = structuredClone(state.draft); const generation = state.generation;
    const missing = state.contract.fields.filter((field) => field.required !== false && (valueAt(request,field.path) === null || valueAt(request,field.path) === ""));
    if (missing.length) { state.group = missing[0].group; renderTabs(); renderFields(); status("Supply " + missing.map((field) => field.label).slice(0,4).join(", "),true); return; }
    busy(true); status("Evaluating exact terms and dated cash…");
    try { const receipt = await host.api("/v1/pricing/demo/evaluate",{method:"POST",body:JSON.stringify(request)}); if (generation !== state.generation) return; state.receipt = receipt; state.assessedInput = request; renderResult(); if (!$("pd-dialog").open) $("pd-dialog").showModal(); status("Assessment saved · edit terms to run a new scenario"); }
    catch(error) { status(error.message,true); host.notify(error.message,true); }
    finally { if (generation === state.generation) busy(false); }
  }
  async function bootstrap() {
    if (!host.isSession() || state.contract) return;
    try { const contract = await host.api("/v1/pricing/demo/contract"); if (!host.isSession()) return; state.contract = contract; state.draft = null; renderExamples(); renderTabs(); renderFields(); status("Choose a scenario or supply explicit contract terms"); }
    catch(error) { status("Contract unavailable: " + error.message,true); }
  }
  function download(blob,name) { const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url),1000); }
  $("pd-evaluate").addEventListener("click",evaluate);
  $("pd-blank").addEventListener("click",() => { if (!state.contract) return; state.draft = structuredClone(state.contract.template); state.selected = ""; $("pd-selected").textContent = "Blank contract · no favorable default inputs"; renderExamples(); renderFields(); busy(false); status("Every required term must be supplied"); });
  $("pd-close").addEventListener("click",() => $("pd-dialog").close());
  $("pd-dialog").addEventListener("keydown",(event) => { if(event.key === "Escape") { event.preventDefault(); event.stopPropagation(); $("pd-dialog").close(); } });
  $("pd-dialog").addEventListener("click",(event) => { if(event.target === $("pd-dialog")) { const rect = $("pd-dialog").getBoundingClientRect(); if(event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) $("pd-dialog").close(); } });
  document.querySelectorAll("[data-pd-result]").forEach((button) => button.addEventListener("click",() => showResult(button.dataset.pdResult)));
  $("pd-surface-angle").addEventListener("input",() => drawSurface(state.receipt?.result.surface));
  $("pd-copy-json").addEventListener("click",() => { if(state.receipt) download(new Blob([JSON.stringify(state.receipt,null,2)],{type:"application/json"}),"computebasis-assessment-"+state.receipt.snapshot_id.slice(0,12)+".json"); });
  $("pd-pdf").addEventListener("click",async () => { if(!state.receipt) return; const receipt=state.receipt; const generation=state.generation; const button=$("pd-pdf"); button.disabled=true; button.textContent="Preparing PDF…"; try { await host.api("/v1/pricing/demo/contract"); const response=await fetch("/v1/pricing/demo/"+receipt.snapshot_id+"/agreement.pdf",{credentials:"same-origin"}); if(!response.ok) throw new Error("Agreement download failed ("+response.status+")"); const blob=await response.blob(); if(generation===state.generation) download(blob,"computebasis-agreement-"+receipt.snapshot_id.slice(0,12)+".pdf"); } catch(error) { host.notify(error.message,true); } finally { button.textContent="Download agreement PDF"; button.disabled=!state.receipt || !host.isSession(); } });
  host.onSession((active) => { if(active) bootstrap(); else { state.generation++; state.contract=null; state.draft=null; state.receipt=null; state.references=[]; $("pd-pdf").disabled=true; if($("pd-dialog").open) $("pd-dialog").close(); busy(false); } });
  host.onView((view) => { if(view==="pricing") { bootstrap(); refreshReferences(); } });
  setInterval(() => { if(host.isSession() && state.draft && !$("pricing-view").hidden) refreshReferences(); },30000);
  window.ComputePricingDemo=Object.freeze({loadQuote:async (quote) => {
    host.showView("pricing"); await bootstrap(); if(!state.contract || state.busy) return;
    state.draft=structuredClone(state.contract.template); state.selected=""; state.group="capacity";
    const known={"provider.id":quote.provider_id,"provider.label":quote.provider,"capacity.model":quote.gpu,
      "capacity.gpus_per_node":quote.gpus_per_node,"capacity.node_count":quote.nodes,"capacity.country_code":quote.country,
      "capacity.location":quote.location,"capacity.interconnect":quote.interconnect,
      "pricing.supplier_rate":quote.price,"settlement.down_payment_fraction":quote.down_payment};
    Object.entries(known).forEach(([path,value])=>{if(value!==undefined && value!==null) put(state.draft,path,value);});
    $("pd-selected").textContent="Simulated supplier quote "+quote.id+" · buyer, service and funding terms need completion";
    renderExamples(); renderTabs(); renderFields(); refreshReferences(); busy(false);
    status("Known supplier fields loaded. Unknown configuration, buyer and cash terms remain blank.");
  }});
  bootstrap();
})();
