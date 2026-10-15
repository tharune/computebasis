/* Pricing demonstration, part 5 of 5: state, requests and wiring.
   Backend-owned scenarios fill an editable form; Evaluate saves an assessment and opens it in a dialog. Nothing is evaluated until the
   person asks. The page never computes a price: it sends the declared terms and prints what comes back. */
(() => {
  "use strict";
  const host = window.ComputeHost; const P = window.PricingDemo;
  if (!host || !P || !P.view) return;
  const { h, num, isNumeric, clone, money, rate, percent, shortDate, longDate, utcStamp, spanDays, plural, holdText, explainError, NOT_SUPPLIED } = P;
  const F = P.fields; const V = P.view;
  const $ = (id) => host.byId(id);
  const PER_HOUR = "per GPU-hour";
  const state = { contract: null, draft: null, assessedInput: null, selected: "", group: "provider", tab: "quote", receipt: null, busy: false, generation: 0, references: [],
    invalid: new Set(), attempted: false, cards: new Map(), tabs: new Map(), inputs: null, restore: null, reopen: null, loading: false, pendingQuote: null };

  /* ----- status line, busy state, the summary column ----------------------------------------------------------------------------- */
  /* The action bar shows once there is a contract to evaluate, or when it has something to report. */
  const syncBar = () => { $("pd-actions").hidden = !state.draft && !$("pd-input-state").classList.contains("is-error"); };
  function status(message, error = false) { const line = $("pd-input-state"); line.textContent = message; line.classList.toggle("is-error", error); syncBar(); }
  const live = () => host.isSession() && Boolean(state.contract);
  function busy(on) {
    state.busy = on; syncBar();
    const locked = on || !host.isSession();
    $("pd-evaluate").disabled = on || !state.draft || !live();
    $("pd-evaluate").textContent = on ? "Evaluating…" : "Evaluate contract";
    $("pd-blank").disabled = locked || !state.contract;
    state.cards.forEach((buttons) => { buttons.edit.disabled = locked; buttons.simulate.disabled = locked; });
    const fields = $("pd-fields"); fields.setAttribute("aria-busy", String(on));
    state.inputs && state.inputs.forEach((input) => { input.disabled = locked; });
    if (state.reopen) state.reopen.disabled = on;
  }
  const choiceName = (path, value) => F.choiceLabel(path, value);
  function renderSummary() {
    const target = $("pd-summary"); const d = state.draft;
    if (!d) { target.replaceChildren(h("p", "pd-empty-note", "No contract is loaded. Choose a scenario or start a blank contract.")); return; }
    const at = (path) => F.valueAt(d, path); const seen = (value) => (F.isBlank(value) ? NOT_SUPPLIED : String(value));
    const nodes = at("capacity.node_count"); const gpus = at("capacity.gpus_per_node"); const days = spanDays(at("capacity.starts_at"), at("capacity.ends_at"));
    const price = (path) => (isNumeric(at(path)) ? rate(at(path)) + " " + PER_HOUR : NOT_SUPPLIED);
    target.replaceChildren(V.facts([
      ["Provider", seen(at("provider.label"))],
      ["Hardware", seen(at("capacity.model"))],
      ["Capacity", isNumeric(nodes) && isNumeric(gpus) ? plural(Number(nodes) * Number(gpus), "GPU", "GPUs") + " (" + nodes + " × " + gpus + ")" : NOT_SUPPLIED],
      ["Service window", days ? shortDate(at("capacity.starts_at")) + " to " + longDate(at("capacity.ends_at")) : NOT_SUPPLIED, days ? plural(days, "day", "days") : null],
      ["Supplier price", price("pricing.supplier_rate"), at("pricing.rate_type") ? choiceName("pricing.rate_type", at("pricing.rate_type")) : null],
      ["Buyer price", price("pricing.buyer_rate")],
      ["Settlement", at("settlement.mode") ? choiceName("settlement.mode", at("settlement.mode")) : NOT_SUPPLIED, isNumeric(at("settlement.down_payment_fraction")) && Number(at("settlement.down_payment_fraction")) > 0 ? percent(at("settlement.down_payment_fraction")) + " supplier deposit" : null],
    ]));
  }
  const stale = () => Boolean(state.receipt) && JSON.stringify(state.draft) !== JSON.stringify(state.assessedInput);
  function renderLast() {
    const target = $("pd-last-result"); state.reopen = null;
    if (!state.receipt) { target.replaceChildren(h("p", "pd-empty-note", "Nothing evaluated yet. Simulate a scenario or evaluate edited terms.")); return; }
    const s = state.receipt.result.summary || {}; const held = state.receipt.result.status === "held";
    const open = h("button", "secondary-button", "Open assessment"); open.type = "button"; open.id = "pd-reopen"; open.disabled = state.busy;
    open.addEventListener("click", () => { state.restore = { type: "reopen" }; openDialog(); });
    state.reopen = open;
    target.replaceChildren(
      V.facts([
        ["Purchase ceiling", isNumeric(s.purchase_ceiling) ? rate(s.purchase_ceiling) + " " + PER_HOUR : "Not available"],
        ["Minimum selling rate", isNumeric(s.sell_floor) ? rate(s.sell_floor) + " " + PER_HOUR : "Not available"],
        ["Target selling rate", isNumeric(s.target_ask) ? rate(s.target_ask) + " " + PER_HOUR : "Not available"],
        ["Economic profit", money(s.expected_profit, 2)],
      ]),
      h("p", "pd-last-meta", (held ? "Held. " : "Scenario estimate. ") + "Saved " + utcStamp(state.receipt.created_at) + "."),
      ...(stale() ? [h("p", "pd-stale", "The terms have changed since this assessment.")] : []), open);
  }

  /* ----- scenario cards ---------------------------------------------------------------------------------------------------------- */
  function exampleFacts(example) {
    const i = example.inputs; const q = i.pricing; const c = i.capacity; const s = i.settlement; const p = i.provider;
    const days = spanDays(c.starts_at, c.ends_at);
    const price = q.rate_type === "variable" ? rate(q.variable_low) + " to " + rate(q.variable_high) : rate(q.supplier_rate);
    const deposit = isNumeric(s.down_payment_fraction) && Number(s.down_payment_fraction) > 0 ? ", " + percent(s.down_payment_fraction) + " deposit" : "";
    return { tier: F.choiceLabel("provider.credit_band", p.credit_band) + " provider",
      rows: [["Declared credit", isNumeric(p.credit_score) ? p.credit_score + " of 100" : NOT_SUPPLIED],
        ["Supplier price", price, PER_HOUR + (q.rate_type === "variable" ? ", variable" : ", fixed")], ["Term", days ? plural(days, "day", "days") : NOT_SUPPLIED, shortDate(c.starts_at) + " to " + shortDate(c.ends_at)],
        ["Capacity", plural(Number(c.node_count) * Number(c.gpus_per_node), "GPU", "GPUs"), c.node_count + " × " + c.gpus_per_node], ["Settlement", F.choiceLabel("settlement.mode", s.mode) + deposit]] };
  }
  function renderExamples() {
    const target = $("pd-examples"); target.replaceChildren(); state.cards = new Map();
    state.contract.scenarios.forEach((example) => {
      const info = exampleFacts(example); const card = h("article", "pd-example"); card.setAttribute("role", "listitem"); card.dataset.scenarioCard = example.id;
      const head = h("div", "pd-example-head"); head.append(h("h3", "", example.inputs.capacity.model), h("span", "pd-tier", info.tier));
      const name = h("p", "pd-example-name", example.inputs.provider.label);
      const facts = h("dl", "pd-example-facts");
      info.rows.forEach(([key, value, note]) => { const row = h("div"); const dd = h("dd", "", value); if (note) dd.append(h("small", "", note)); row.append(h("dt", "", key), dd); facts.append(row); });
      const actions = h("div", "pd-example-actions");
      const edit = h("button", "secondary-button", "Edit terms"); edit.type = "button"; edit.setAttribute("aria-label", "Edit terms for " + example.label);
      edit.addEventListener("click", () => { loadExample(example.id); const heading = $("pd-terms-title"); if (heading.scrollIntoView) heading.scrollIntoView({ block: "start" }); });
      const simulate = h("button", "primary-button", "Simulate"); simulate.type = "button"; simulate.dataset.scenario = example.id; simulate.setAttribute("aria-label", "Simulate " + example.label);
      simulate.addEventListener("click", async () => { state.restore = { type: "simulate", id: example.id }; loadExample(example.id); await evaluate(); });
      actions.append(edit, simulate); card.append(head, name, h("p", "pd-example-summary", example.summary), facts, actions); target.append(card);
      state.cards.set(example.id, { card, edit, simulate });
    });
    markSelected(); busy(state.busy);
  }
  function markSelected() {
    state.cards.forEach((entry, id) => {
      const on = state.selected === id; entry.card.dataset.selected = String(on);
      if (on) entry.card.setAttribute("aria-current", "true"); else entry.card.removeAttribute("aria-current");
    });
  }

  /* ----- group tabs and the form ------------------------------------------------------------------------------------------------- */
  function missingFor(groupId) { return state.contract.fields.filter((field) => field.group === groupId && state.invalid.has(field.path)).length; }
  function renderTabs() {
    const target = $("pd-tabs"); target.replaceChildren(); state.tabs = new Map();
    if (!state.draft) return;
    state.contract.groups.forEach((group) => {
      const selected = state.group === group.id; const button = h("button", "pd-tab", F.groupLabel(group));
      button.type = "button"; button.id = "pd-gtab-" + group.id; button.setAttribute("role", "tab"); button.setAttribute("aria-selected", String(selected));
      button.setAttribute("aria-controls", "pd-fields"); button.setAttribute("tabindex", selected ? "0" : "-1");
      const missing = state.attempted ? missingFor(group.id) : 0;
      if (missing) button.append(h("span", "pd-tab-count", String(missing)), h("span", "sr-only", " terms still to supply"));
      button.addEventListener("click", () => selectGroup(group.id, true));
      button.addEventListener("keydown", (event) => {
        const ids = state.contract.groups.map((item) => item.id); const index = ids.indexOf(group.id);
        const next = { ArrowRight: (index + 1) % ids.length, ArrowLeft: (index + ids.length - 1) % ids.length, Home: 0, End: ids.length - 1 }[event.key];
        if (next === undefined) return; event.preventDefault(); selectGroup(ids[next], true);
      });
      target.append(button); state.tabs.set(group.id, button);
    });
    $("pd-fields").setAttribute("aria-labelledby", "pd-gtab-" + state.group);
  }
  function selectGroup(id, focus) { state.group = id; renderTabs(); renderFields(); if (focus && state.tabs.get(id).focus) state.tabs.get(id).focus(); }
  function renderFields() {
    if (!state.contract || !state.draft) {
      $("pd-fields").replaceChildren(state.contract ? h("p", "pd-empty-note", "Choose a scenario above, or start a blank contract, to edit its terms.") : h("span")); state.inputs = null; return;
    }
    state.inputs = F.renderForm($("pd-fields"), { contract: state.contract, group: state.group, draft: state.draft, invalid: state.invalid, disabled: state.busy || !host.isSession(), onChange });
    $("pd-fields").setAttribute("aria-labelledby", "pd-gtab-" + state.group);
  }
  function currentModel() { return F.valueAt(state.draft, "capacity.gpu_model") || F.valueAt(state.draft, "capacity.model"); }
  function onChange(field, value) {
    if (!state.draft) state.draft = clone(state.contract.template);
    F.put(state.draft, field.path, value);
    if (state.invalid.has(field.path)) state.invalid.delete(field.path);
    status("Terms edited. Evaluate to create a new assessment.");
    if (field.path === "capacity.model" || field.path === "capacity.gpu_model") refreshReferences();
    renderSummary(); renderLast(); busy(state.busy);
    if (state.attempted) renderTabs();
  }
  function loadExample(id) {
    const example = state.contract.scenarios.find((row) => row.id === id); if (!example) return;
    state.draft = clone(example.inputs); state.selected = id; state.invalid = new Set(); state.attempted = false;
    $("pd-selected").textContent = example.label + ". Independently invented terms; edit any value.";
    status("Every term is filled. Edit any value, or evaluate."); markSelected(); renderTabs(); renderFields(); renderSummary(); renderLast(); refreshReferences(); busy(false);
  }
  function blank() {
    if (!state.contract) return;
    state.draft = clone(state.contract.template); state.selected = ""; state.invalid = new Set(); state.attempted = false;
    $("pd-selected").textContent = "Blank contract. No term has a favorable default; every required term must be supplied.";
    markSelected(); renderTabs(); renderFields(); renderSummary(); renderLast(); refreshReferences(); busy(false); status("Supply every required term, then evaluate.");
  }

  /* ----- reference rates --------------------------------------------------------------------------------------------------------- */
  async function refreshReferences() {
    const model = state.draft ? currentModel() : null;
    $("pd-market-context").textContent = model ? model + ": retained source observations, shown in each source's own unit." : "Choose hardware to see permitted retained references.";
    if (!model) { $("pd-live-rates").replaceChildren(); return; }
    if (!host.isSession()) return;
    const generation = state.generation;
    try {
      const result = await host.api("/v1/pricing/demo/references?hardware_model=" + encodeURIComponent(model));
      if (generation !== state.generation || model !== currentModel()) return;
      state.references = Array.isArray(result.references) ? result.references : []; $("pd-live-rates").replaceChildren(V.referenceTable(state.references, true));
    } catch (error) { $("pd-live-rates").replaceChildren(h("p", "pd-empty-note", "References unavailable: " + explainError(error))); }
  }

  /* ----- the assessment dialog --------------------------------------------------------------------------------------------------- */
  const TABS = ["quote", "cash", "terms"];
  function showTab(name, focus = false) {
    state.tab = name;
    TABS.forEach((key) => {
      const tab = $("pd-tab-" + key); const on = key === name;
      tab.setAttribute("aria-selected", String(on)); tab.setAttribute("tabindex", on ? "0" : "-1"); $("pd-result-" + key).hidden = !on;
    });
    if (focus && $("pd-tab-" + name).focus) $("pd-tab-" + name).focus();
    if (state.receipt) V.draw(name);
  }
  function openDialog() {
    if (!state.receipt) return;
    const dialog = $("pd-dialog");
    V.render(state.receipt, state.assessedInput, state.references);
    $("pd-pdf").disabled = !state.receipt.result.agreement_terms || !host.isSession();
    state.tab = "quote"; TABS.forEach((key) => { $("pd-result-" + key).hidden = key !== "quote"; $("pd-tab-" + key).setAttribute("aria-selected", String(key === "quote")); $("pd-tab-" + key).setAttribute("tabindex", key === "quote" ? "0" : "-1"); });
    if (!dialog.open) { if (typeof dialog.showModal === "function") dialog.showModal(); else dialog.setAttribute("open", ""); }
    $("pd-modal-body").scrollTop = 0;
    V.draw("quote");
    $("pd-dialog-title").focus();
  }
  function closeDialog() { const dialog = $("pd-dialog"); if (dialog.open) dialog.close(); }
  /* Put focus back where it came from, by what it was rather than by the node, which may have been rebuilt meanwhile. */
  function restoreFocus() {
    const wanted = state.restore; state.restore = null;
    let target = null;
    if (wanted && wanted.type === "simulate" && state.cards.get(wanted.id)) target = state.cards.get(wanted.id).simulate;
    else if (wanted && wanted.type === "reopen") target = state.reopen;
    if (!target || target.disabled) target = $("pd-evaluate").disabled ? $("pricing-title") : $("pd-evaluate");
    if (target.focus) target.focus();
  }
  const FOCUSABLE = new Set(["button", "input", "select", "textarea", "summary", "a"]);
  function focusables(node, out = []) {
    const tag = String(node.tagName || "").toLowerCase();
    if (node.hidden === true) return out;
    const tabindex = node.getAttribute ? node.getAttribute("tabindex") : null;
    if ((FOCUSABLE.has(tag) || (tabindex !== null && tabindex !== "-1")) && !node.disabled && tabindex !== "-1") out.push(node);
    if (tag === "details" && node.open !== true) { Array.from(node.children).filter((child) => String(child.tagName).toLowerCase() === "summary").forEach((child) => out.push(child)); return out; }
    Array.from(node.children || []).forEach((child) => focusables(child, out));
    return out;
  }
  function trapTab(event) {
    const list = focusables($("pd-dialog")); if (!list.length) return;
    const first = list[0]; const last = list[list.length - 1]; const from = event.target;
    if (event.shiftKey && (from === first || from === $("pd-dialog"))) { event.preventDefault(); if (last.focus) last.focus(); }
    else if (!event.shiftKey && from === last) { event.preventDefault(); if (first.focus) first.focus(); }
  }

  /* ----- evaluate and download --------------------------------------------------------------------------------------------------- */
  async function evaluate() {
    if (state.busy || !state.draft || !live()) return;
    const request = clone(state.draft); const generation = state.generation;
    const missing = state.contract.fields.filter((field) => field.required !== false && F.isBlank(F.valueAt(request, field.path)));
    state.attempted = missing.length > 0; state.invalid = new Set(missing.map((field) => field.path));
    if (missing.length) {
      const names = missing.map((field) => F.labelFor(field.path, field.label));
      state.group = missing[0].group; renderTabs(); renderFields();
      const first = state.inputs && state.inputs.get(missing[0].path); if (first && first.focus) first.focus();
      status("Supply " + names.slice(0, 4).join(", ") + (names.length > 4 ? " and " + (names.length - 4) + " more" : "") + " before evaluating.", true); return;
    }
    renderTabs(); busy(true); status("Evaluating the exact terms and the dated cash path…");
    try {
      const receipt = await host.api("/v1/pricing/demo/evaluate", { method: "POST", body: JSON.stringify(request) });
      if (generation !== state.generation) return;
      state.receipt = receipt; state.assessedInput = request; renderLast(); openDialog(); status("Assessment saved. Edit terms to run a new scenario.");
    } catch (error) { if (generation === state.generation) { const message = explainError(error); status(message, true); host.notify(message, true); } }
    finally { if (generation === state.generation) { busy(false); flushQuote(); } }
  }
  function download(blob, name) {
    const url = URL.createObjectURL(blob); const link = document.createElement("a"); link.href = url; link.download = name; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  async function downloadPdf() {
    if (!state.receipt) return;
    const receipt = state.receipt; const generation = state.generation; const button = $("pd-pdf");
    button.disabled = true; button.textContent = "Preparing PDF…";
    try {
      await host.api("/v1/pricing/demo/contract");
      const response = await fetch("/v1/pricing/demo/" + receipt.snapshot_id + "/agreement.pdf", { credentials: "same-origin" });
      if (!response.ok) throw new Error("Agreement download failed (HTTP " + response.status + ")");
      const blob = await response.blob();
      if (generation === state.generation) download(blob, "computebasis-agreement-" + receipt.snapshot_id.slice(0, 12) + ".pdf");
    } catch (error) { host.notify(explainError(error), true); }
    finally { button.textContent = "Download agreement PDF"; button.disabled = !state.receipt || !state.receipt.result.agreement_terms || !host.isSession(); }
  }

  /* ----- loading and the no-session state ---------------------------------------------------------------------------------------- */
  function renderUnavailable(message, retry) {
    const note = h("div", "pd-unavailable"); note.append(h("p", "", message));
    if (retry) { const again = h("button", "secondary-button", "Try again"); again.type = "button"; again.addEventListener("click", bootstrap); note.append(again); }
    $("pd-examples").replaceChildren(note); $("pd-tabs").replaceChildren(); $("pd-fields").replaceChildren(); state.cards = new Map(); state.inputs = null;
  }
  async function bootstrap() {
    if (!host.isSession() || state.contract || state.loading) return;
    state.loading = true; const generation = state.generation;
    $("pd-examples").replaceChildren(h("p", "pd-empty-note", "Loading the example contracts…"));
    try {
      const contract = await host.api("/v1/pricing/demo/contract");
      if (generation !== state.generation || !host.isSession()) return;
      state.contract = contract; state.draft = null; state.selected = ""; state.group = contract.groups[0] ? contract.groups[0].id : "provider";
      renderExamples(); renderTabs(); renderFields(); renderSummary(); renderLast(); refreshReferences(); busy(false); status("Choose a scenario or supply explicit contract terms."); flushQuote();
    } catch (error) { if (generation === state.generation) { renderUnavailable("The example contracts could not be loaded. " + explainError(error), true); status("Contract unavailable.", true); } }
    finally { state.loading = false; }
  }
  function reset() {
    state.generation++; state.contract = null; state.draft = null; state.receipt = null; state.assessedInput = null; state.references = []; state.selected = ""; state.invalid = new Set(); state.attempted = false; state.reopen = null; state.loading = false;
    V.reset(); const dialog = $("pd-dialog"); if (dialog.open) dialog.close();
    $("pd-pdf").disabled = true; $("pd-selected").textContent = "Choose a scenario to fill every term, or start from a blank contract.";
    renderUnavailable("Waiting for the local workspace session. The example contracts load when it connects.", false);
    renderSummary(); renderLast(); $("pd-live-rates").replaceChildren(); $("pd-market-context").textContent = "Choose hardware to see permitted retained references.";
    busy(false); status("No workspace session.");
  }

  /* ----- wiring ------------------------------------------------------------------------------------------------------------------ */
  $("pd-evaluate").addEventListener("click", evaluate);
  $("pd-blank").addEventListener("click", blank);
  $("pd-close").addEventListener("click", closeDialog);
  $("pd-copy-json").addEventListener("click", () => { if (state.receipt) download(new Blob([JSON.stringify(state.receipt, null, 2)], { type: "application/json" }), "computebasis-assessment-" + state.receipt.snapshot_id.slice(0, 12) + ".json"); });
  $("pd-pdf").addEventListener("click", downloadPdf);
  const dialog = $("pd-dialog");
  dialog.addEventListener("keydown", (event) => {
    if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); closeDialog(); }
    else if (event.key === "Tab") trapTab(event);
  });
  dialog.addEventListener("cancel", (event) => { event.preventDefault(); closeDialog(); });
  /* A click on the backdrop closes the dialog, but only if it began there: a drag that starts in the text and ends outside must not. */
  let pressedOnBackdrop = null;
  dialog.addEventListener("pointerdown", (event) => { pressedOnBackdrop = event.target === dialog; });
  dialog.addEventListener("click", (event) => { if (event.target === dialog && pressedOnBackdrop !== false) closeDialog(); pressedOnBackdrop = null; });
  $("pd-form").addEventListener("submit", (event) => event.preventDefault());
  dialog.addEventListener("close", restoreFocus);
  TABS.forEach((key) => {
    const tab = $("pd-tab-" + key);
    tab.addEventListener("click", () => showTab(key));
    tab.addEventListener("keydown", (event) => {
      const index = TABS.indexOf(key); const next = { ArrowRight: (index + 1) % TABS.length, ArrowLeft: (index + TABS.length - 1) % TABS.length, Home: 0, End: TABS.length - 1 }[event.key];
      if (next === undefined) return; event.preventDefault(); showTab(TABS[next], true);
    });
  });
  let resizing = null;
  if (typeof window.addEventListener === "function" && typeof setTimeout === "function") {
    window.addEventListener("resize", () => { if (!dialog.open) return; clearTimeout(resizing); resizing = setTimeout(() => V.draw(state.tab), 120); });
  }
  host.onSession((active) => { if (active) bootstrap(); else reset(); });
  host.onView((view) => { if (view === "pricing") { bootstrap(); refreshReferences(); } });
  setInterval(() => { if (host.isSession() && state.draft && !$("pricing-view").hidden) refreshReferences(); }, 30000);

  /* ----- a quote from the Quotes page -------------------------------------------------------------------------------------------- */
  const has = (path) => state.contract.fields.some((field) => field.path === path);
  const decimalText = (value) => (typeof value === "string" ? value.trim() : typeof value === "number" && Number.isFinite(value) ? String(value) : "");
  /* Fill the form from a simulated supplier quote. Only terms the quote actually states are set: its price becomes the supplier ask (a fixed
     ask, so the variable range collapses to it, as the contract defines a fixed rate), its GPU becomes the hardware model and its down
     payment, if stated, the supplier deposit. Every other term comes from the backend's labelled invented example for that GPU, or from the
     first example when none matches, and the note says so. The provider's name is not copied in: the example's claims and ratings are
     invented and must not be attributed to a real quote's seller. Nothing is evaluated or saved. */
  function applyQuote(quote) {
    const ask = decimalText(quote.price);
    if (!ask || !Number.isFinite(Number(ask)) || Number(ask) < 0) { status("This quote has no usable price, so nothing was loaded.", true); return false; }
    const examples = state.contract.scenarios || []; const model = decimalText(quote.gpu).toLowerCase();
    const base = examples.find((example) => String(F.valueAt(example.inputs, "capacity.model")).toLowerCase() === model) || examples[0] || null;
    const draft = clone(base ? base.inputs : state.contract.template);
    if (has("pricing.supplier_rate")) F.put(draft, "pricing.supplier_rate", ask);
    if (has("pricing.rate_type")) F.put(draft, "pricing.rate_type", "fixed");
    if (has("pricing.variable_low")) F.put(draft, "pricing.variable_low", ask);
    if (has("pricing.variable_high")) F.put(draft, "pricing.variable_high", ask);
    if (has("capacity.model") && decimalText(quote.gpu)) F.put(draft, "capacity.model", decimalText(quote.gpu));
    const deposit = decimalText(quote.down_payment);
    if (has("settlement.down_payment_fraction") && deposit && Number(deposit) >= 0 && Number(deposit) <= 1) F.put(draft, "settlement.down_payment_fraction", deposit);
    state.draft = draft; state.selected = ""; state.group = "pricing"; state.invalid = new Set(); state.attempted = false;
    const source = decimalText(quote.ref) || decimalText(quote.id) || "a simulated quote"; const seller = decimalText(quote.provider);
    $("pd-selected").textContent = "Supplier ask from " + source + (seller ? " (" + seller + ")" : "") + ". " + (base ? "Every other term comes from the invented \u201c" + base.label + "\u201d example; replace any that do not fit." : "Every other term is blank and must be supplied.");
    markSelected(); renderTabs(); renderFields(); renderSummary(); renderLast(); refreshReferences(); busy(false);
    status("Quote loaded. Review the terms, then evaluate. Nothing is evaluated or saved yet.");
    const heading = $("pd-terms-title"); if (heading.scrollIntoView) heading.scrollIntoView({ block: "start" });
    const askInput = state.inputs && state.inputs.get("pricing.supplier_rate"); if (askInput && askInput.focus) askInput.focus({ preventScroll: true });
    return true;
  }
  /* A quote waits here until there is a session, a loaded contract and no evaluation in flight, then fills the form. */
  function flushQuote() {
    if (!state.pendingQuote || !state.contract || state.busy || !host.isSession()) return false;
    const quote = state.pendingQuote; state.pendingQuote = null; return applyQuote(quote);
  }
  /* The public entry point: window.ComputePricingDemo.loadQuote(quote) -> Promise<boolean>, true when the form was filled now. */
  function loadQuote(quote) {
    if (!quote || typeof quote !== "object") return Promise.resolve(false);
    state.pendingQuote = quote; host.showView("pricing");
    if (!host.isSession()) { status("No workspace session. The quote from " + (decimalText(quote.ref) || "Quotes") + " loads when it connects.", true); return Promise.resolve(false); }
    if (!state.contract) { bootstrap(); return Promise.resolve(false); }
    return Promise.resolve(flushQuote());
  }
  P.loadQuote = loadQuote;
  const queued = P.takeQueuedQuote(); if (queued) state.pendingQuote = queued;

  if (host.isSession()) bootstrap(); else reset();
})();
