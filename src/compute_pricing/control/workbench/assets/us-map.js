/* The US capacity map. window.ComputeMap.create(container, { onSelect }) -> { update({ sites, positions, bids }), destroy() }.
   Inputs are the normalised desk objects from BookAdapter.normalizeDesk. update() runs on every book poll with mostly equal data, so it
   compares first, touches only what changed and never replays the entrance. Colour and size reach the page through classes and SVG
   attributes only (no inline style); the picture is a choropleth of quoted GPUs per state with proportional circles for sites, our positions
   as squares and open bids as dotted rings. Placement is illustrative and says so on its face. */
(function () {
  "use strict";
  const US = window.ComputeUsStates;
  if (!US || !Array.isArray(US.states) || typeof US.project !== "function") return;
  const NS = "http://www.w3.org/2000/svg";
  const VB_W = US.width, VB_H = US.height;
  const STATE_BY_ABBR = new Map(US.states.map((state) => [state.abbr, state]));
  const SIM_NOTE = "Illustrative placement, simulated data";
  const MAX_TINTS = 5;
  const COUNTRIES = { JP: "Japan", DE: "Germany", NL: "Netherlands", BR: "Brazil", CL: "Chile", CA: "Canada", SG: "Singapore", GB: "United Kingdom", FR: "France", IE: "Ireland", SE: "Sweden", FI: "Finland", NO: "Norway", ES: "Spain", IT: "Italy", CH: "Switzerland", PL: "Poland", IN: "India", KR: "South Korea", AU: "Australia", AE: "United Arab Emirates", MX: "Mexico", ZA: "South Africa", US: "United States" };
  let instances = 0;

  /* ---- Text and number helpers (no arithmetic on money: exact strings are printed as given) ---- */
  const nf = new Intl.NumberFormat("en-US");
  const finite = (value) => (typeof value === "number" && Number.isFinite(value) ? value : 0);
  const str = (value) => (typeof value === "string" ? value : "");
  const int = (value) => nf.format(Math.round(finite(value)));
  const fix = (value) => (Number.isFinite(value) ? Math.round(value * 100) / 100 : 0);
  const plural = (count, one, many) => int(count) + " " + (count === 1 ? one : many || one + "s");
  const compact = (value) => (value >= 10000 ? Math.round(value / 1000) + "K" : value >= 1000 ? Math.round(value / 100) / 10 + "K" : String(Math.round(value)));
  const share = (part, whole) => (whole > 0 ? part / whole : null);
  function pctText(fraction) {
    if (fraction === null || !Number.isFinite(fraction)) return "—";
    const percent = fraction * 100;
    if (percent > 0 && percent < 0.1) return "<0.1%";
    return (percent < 10 && percent !== Math.round(percent) ? Math.round(percent * 10) / 10 : Math.round(percent)) + "%";
  }
  const MONEY = /^(-?)(\d+)(?:\.(\d+))?$/;
  function money(exact, signed) {
    if (typeof exact !== "string") return "—";
    const match = MONEY.exec(exact.trim()); if (!match) return "—";
    return (match[1] ? "−" : signed ? "+" : "") + "$" + match[2].replace(/\B(?=(\d{3})+(?!\d))/g, ",") + (match[3] ? "." + match[3] : "");
  }
  let regionNames = null;
  function countryName(code) {
    if (COUNTRIES[code]) return COUNTRIES[code];
    try { regionNames = regionNames || new Intl.DisplayNames(["en"], { type: "region" }); const name = regionNames.of(code); if (name && name !== code) return name; } catch (error) { /* an unknown code keeps its letters */ }
    return code || "Unknown location";
  }
  const cityOf = (place) => str(place).split(",")[0].trim();
  const modelOrder = (a, b) => a.localeCompare(b, "en", { numeric: true });

  /* ---- Small DOM kit. Only append, replaceChildren and attributes: the fake DOM in the tests has nothing else, and neither needs more. ---- */
  function node(tag, cls, attrs) {
    const svg = tag.slice(0, 4) === "svg:"; const name = svg ? tag.slice(4) : tag;
    const created = svg ? document.createElementNS(NS, name) : document.createElement(name);
    if (cls) created.setAttribute("class", cls);
    if (attrs) Object.keys(attrs).forEach((key) => setAttr(created, key, attrs[key]));
    return created;
  }
  function setAttr(target, key, value) {
    if (value === null || value === undefined || value === false) { if (target.getAttribute(key) !== null) target.removeAttribute(key); return; }
    const text = String(value); if (target.getAttribute(key) !== text) target.setAttribute(key, text);
  }
  const setText = (target, text) => { if (target.textContent !== text) target.textContent = text; };
  const toggle = (target, name, on) => { if (target.classList.contains(name) !== !!on) target.classList.toggle(name, !!on); };
  /* A plain description of a bit of DOM. Comparing two descriptions is how a panel knows whether anything changed. */
  const T = (tag, cls, attrs, ...kids) => ({ tag, cls: cls || "", attrs: attrs || null, kids: kids.flat(Infinity).filter((kid) => kid !== null && kid !== undefined && kid !== false) });
  function build(spec) {
    if (typeof spec === "string") return document.createTextNode(spec);
    const made = node(spec.tag, spec.cls, spec.attrs);
    spec.kids.forEach((kid) => made.append(build(kid)));
    return made;
  }
  /* Replace a node's children with `specs`, only when they differ from what is already there. */
  function mount(target, specs, memo) {
    const list = specs.filter((spec) => spec !== null && spec !== undefined && spec !== false);
    const sig = JSON.stringify(list); if (memo.sig === sig) return false;
    memo.sig = sig; target.replaceChildren(...list.map(build)); return true;
  }

  /* ---- The model: everything the picture and the panels say, derived from the three arrays and the model filter ---- */
  function buildModel(input, filter) {
    const sitesIn = Array.isArray(input.sites) ? input.sites : [], positionsIn = Array.isArray(input.positions) ? input.positions : [], bidsIn = Array.isArray(input.bids) ? input.bids : [];
    const sites = new Map(), names = new Set();
    sitesIn.forEach((raw) => {
      if (!raw || typeof raw.id !== "string" || sites.has(raw.id)) return;
      const cap = raw.capacity && typeof raw.capacity === "object" ? raw.capacity : {}, all = cap.models && typeof cap.models === "object" ? cap.models : {}, models = {};
      Object.keys(all).forEach((name) => { const gpus = finite(all[name]); if (gpus > 0) { models[name] = gpus; names.add(name); } });
      const state = typeof raw.state === "string" && STATE_BY_ABBR.has(raw.state) ? raw.state : null;
      const country = str(raw.country) || (state ? "US" : "");
      const gpus = filter ? finite(models[filter]) : finite(cap.gpus);
      sites.set(raw.id, {
        key: "site:" + raw.id, id: raw.id, name: str(raw.name), provider: str(raw.provider) || "Unnamed seller", providerId: str(raw.provider_id) || str(raw.provider) || raw.id, grade: /^[A-D]$/.test(str(raw.grade)) ? raw.grade : "U",
        state, country, place: str(raw.place), lat: typeof raw.lat === "number" && Number.isFinite(raw.lat) ? raw.lat : null, lon: typeof raw.lon === "number" && Number.isFinite(raw.lon) ? raw.lon : null,
        gpus, quotes: finite(cap.quotes), eligibleGpus: finite(cap.eligible_gpus), eligibleQuotes: finite(cap.eligible_quotes), models: filter ? (gpus > 0 ? { [filter]: gpus } : {}) : models, positions: [], bids: [],
      });
    });
    positionsIn.forEach((raw) => {
      const site = raw && sites.get(raw.site_id); if (!site || (filter && raw.model !== filter)) return;
      site.positions.push({ id: str(raw.id), model: str(raw.model), gpus: finite(raw.gpus), status: str(raw.status), unrealized: raw.exact && typeof raw.exact.unrealized_usd === "string" ? raw.exact.unrealized_usd : null });
    });
    bidsIn.forEach((raw) => {
      const site = raw && raw.status === "open" && sites.get(raw.site_id); if (!site || (filter && raw.model !== filter)) return;
      site.bids.push({ id: str(raw.id), model: str(raw.model), gpus: finite(raw.gpus), bid: raw.exact && typeof raw.exact.bid === "string" ? raw.exact.bid : null, ask: raw.exact && typeof raw.exact.ask === "string" ? raw.exact.ask : null });
    });

    const regions = new Map(), present = [];
    sites.forEach((site) => {
      if (site.gpus > 0 || site.positions.length || site.bids.length) present.push(site);
    });
    present.forEach((site) => {
      const key = site.state ? "state:" + site.state : "country:" + (site.country || "??");
      let region = regions.get(key);
      if (!region) {
        region = { key, kind: site.state ? "state" : "country", id: site.state || site.country || "??", name: site.state ? STATE_BY_ABBR.get(site.state).name : site.country === "US" ? "United States, state not given" : countryName(site.country), sites: [], providers: new Set(), gpus: 0, eligibleGpus: 0, quotes: 0, eligibleQuotes: 0, models: {}, positions: [], bids: [], places: [] };
        regions.set(key, region);
      }
      region.sites.push(site); region.providers.add(site.providerId);
      region.gpus += site.gpus; region.eligibleGpus += site.eligibleGpus; region.quotes += site.quotes; region.eligibleQuotes += site.eligibleQuotes;
      Object.keys(site.models).forEach((name) => { region.models[name] = (region.models[name] || 0) + site.models[name]; });
      site.positions.forEach((position) => region.positions.push({ ...position, site, provider: site.provider }));
      site.bids.forEach((bid) => region.bids.push({ ...bid, site, provider: site.provider }));
      if (site.place && region.places.indexOf(site.place) < 0) region.places.push(site.place);
    });
    regions.forEach((region) => { region.sites.sort((a, b) => b.gpus - a.gpus || a.id.localeCompare(b.id)); region.positionGpus = region.positions.reduce((sum, p) => sum + p.gpus, 0); region.bidGpus = region.bids.reduce((sum, b) => sum + b.gpus, 0); });
    const byGpus = (a, b) => b.gpus - a.gpus || a.name.localeCompare(b.name);
    const states = [...regions.values()].filter((r) => r.kind === "state").sort(byGpus), abroad = [...regions.values()].filter((r) => r.kind === "country").sort(byGpus);
    states.forEach((region, index) => { region.rank = index + 1; });
    const supplied = states.filter((r) => r.gpus > 0), max = supplied.reduce((m, r) => Math.max(m, r.gpus), 0);
    const total = present.reduce((sum, s) => sum + s.gpus, 0), usGpus = states.reduce((sum, r) => sum + r.gpus, 0);
    const positions = present.reduce((sum, s) => sum + s.positions.length, 0), positionGpus = present.reduce((sum, s) => sum + s.positions.reduce((a, p) => a + p.gpus, 0), 0);
    const usPositions = states.reduce((sum, r) => sum + r.positions.length, 0), usPositionGpus = states.reduce((sum, r) => sum + r.positionGpus, 0);
    const bids = present.reduce((sum, s) => sum + s.bids.length, 0), bidGpus = present.reduce((sum, s) => sum + s.bids.reduce((a, b) => a + b.gpus, 0), 0);
    const usBids = states.reduce((sum, r) => sum + r.bids.length, 0);
    return { filter, sites, present, regions, states, abroad, models: [...names].sort(modelOrder), total, usGpus, usSites: present.filter((s) => s.state).length, positions, positionGpus, usPositions, usPositionGpus, bids, bidGpus, usBids,
      abroadGpus: abroad.reduce((sum, r) => sum + r.gpus, 0), scale: tintScale(max), stateMax: max, abroadMax: abroad.reduce((m, r) => Math.max(m, r.gpus), 0) };
  }
  /* Equal-width classes with round edges, up to five: the widest the eye can tell apart on one hue. */
  function tintScale(max) {
    if (!(max > 0)) return { step: 0, count: 0 };
    const raw = max / MAX_TINTS, unit = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10].map((n) => n * unit).find((n) => n >= raw - 1e-9) || raw;
    return { step, count: Math.min(MAX_TINTS, Math.max(1, Math.ceil(max / step - 1e-9))) };
  }
  const tintOf = (scale, gpus) => (gpus > 0 && scale.step > 0 ? Math.min(scale.count, Math.max(1, Math.ceil(gpus / scale.step - 1e-9))) : 0);

  /* ---- Marks: size, nudge apart, label ---- */
  function sizing(width, gmax) {
    const rMax = Math.max(10, Math.min(22, width * 0.024)), rMin = width < 520 ? 4 : 5;
    return { rMax, rMin, gmax: Math.max(1, gmax), radius(gpus) { return gpus > 0 ? Math.max(rMin, Math.sqrt(gpus / this.gmax) * rMax) : rMin * 0.8; } };
  }
  function layoutMarks(sites, width, sizes) {
    const unit = VB_W / width, nodes = [];
    sites.forEach((site) => {
      if (!site.state || site.lat === null || site.lon === null) return;
      const at = US.project(site.lat, site.lon); if (!at) return;
      const r = sizes.radius(site.gpus), halo = site.positions.length ? 7 : site.bids.length ? 4 : 1;
      nodes.push({ site, ax: at[0] / unit, ay: at[1] / unit, x: at[0] / unit, y: at[1] / unit, r, hr: r + halo });
    });
    /* Sites that share a point start in a spiral around it (largest in the middle), so they settle as a cluster and not a row. */
    const groups = new Map();
    nodes.forEach((n) => { const key = Math.round(n.ax / 3) + ":" + Math.round(n.ay / 3); if (!groups.has(key)) groups.set(key, []); groups.get(key).push(n); });
    groups.forEach((members) => {
      if (members.length < 2) return;
      members.sort((a, b) => b.site.gpus - a.site.gpus || a.site.id.localeCompare(b.site.id));
      members.forEach((n, k) => { if (k === 0) return; const angle = k * 2.399963 + 0.6, dist = (members[0].hr + n.hr) * 0.55 * Math.sqrt(k); n.x = n.ax + Math.cos(angle) * dist; n.y = n.ay + Math.sin(angle) * dist; });
    });
    nodes.sort((a, b) => a.site.id.localeCompare(b.site.id));
    const w = width, h = VB_H / unit, gap = 3;
    for (let pass = 0; pass < 80; pass++) {
      let moved = false;
      for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i], b = nodes[j], need = a.hr + b.hr + gap; let dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy);
        if (d >= need) continue;
        if (d < 0.01) { const angle = (i * 2.4 + j) % (2 * Math.PI); dx = Math.cos(angle); dy = Math.sin(angle); d = 1; }
        const push = (need - d) / 2 + 0.05; a.x -= (dx / d) * push; a.y -= (dy / d) * push; b.x += (dx / d) * push; b.y += (dy / d) * push; moved = true;
      }
      nodes.forEach((n) => { n.x += (n.ax - n.x) * 0.04; n.y += (n.ay - n.y) * 0.04; n.x = Math.min(w - n.hr - 2, Math.max(n.hr + 2, n.x)); n.y = Math.min(h - n.hr - 2, Math.max(n.hr + 2, n.y)); });
      if (!moved && pass > 2) break;
    }
    nodes.forEach((n) => { n.moved = Math.hypot(n.x - n.ax, n.y - n.ay) > Math.max(5, n.r * 0.45); });
    nodes.sort((a, b) => b.site.gpus - a.site.gpus || a.site.id.localeCompare(b.site.id));  // biggest first: tab order, and the small circles paint on top
    return { nodes, unit, width, height: h };
  }
  /* One label per metro on the side with room: right, left, above, below. A label that fits nowhere is left out; the panel still names the site. */
  function placeLabels(layout, fontSize) {
    const out = new Map(), taken = [], { nodes, width, height } = layout, narrow = width < 560;
    const hits = (rect, other) => rect[0] < other[2] && rect[2] > other[0] && rect[1] < other[3] && rect[3] > other[1];
    const circleHits = (rect, n) => { const cx = Math.min(rect[2], Math.max(rect[0], n.x)), cy = Math.min(rect[3], Math.max(rect[1], n.y)); return Math.hypot(cx - n.x, cy - n.y) < n.hr + 2; };
    const metros = new Map();
    nodes.forEach((n) => { const key = n.site.place || n.site.state; const entry = metros.get(key); if (!entry) metros.set(key, { lead: n, count: 1 }); else entry.count++; });
    metros.forEach((entry) => {
      const n = entry.lead, base = narrow ? n.site.state : cityOf(n.site.place) || n.site.state, text = entry.count > 1 && !narrow ? base + " (" + entry.count + ")" : base;
      const textW = text.length * fontSize * 0.56 + 2, textH = fontSize + 2, off = n.hr + 4;
      const options = [["start", n.x + off, n.y], ["end", n.x - off, n.y], ["middle", n.x, n.y - off - textH / 2 + 1], ["middle", n.x, n.y + off + textH / 2 + 1]];
      for (const [anchor, x, y] of options) {
        const x0 = anchor === "start" ? x : anchor === "end" ? x - textW : x - textW / 2, rect = [x0, y - textH / 2, x0 + textW, y + textH / 2];
        if (rect[0] < 3 || rect[2] > width - 3 || rect[1] < 3 || rect[3] > height - 3) continue;
        if (nodes.some((m) => circleHits(rect, m)) || taken.some((t) => hits(rect, t))) continue;
        taken.push(rect); out.set(n.site.id, { text, anchor, x, y: y + fontSize * 0.35 }); break;
      }
    });
    return out;
  }

  /* ---- The component ---- */
  function create(container, options) {
    const onSelect = options && typeof options.onSelect === "function" ? options.onSelect : null;
    const ids = "cmap" + (++instances);
    let destroyed = false, input = { sites: [], positions: [], bids: [] }, lastSig = "", filter = null, model = buildModel(input, null);
    let hoverKey = null, focusKey = null, pinned = null, drawn = false, revealTimer = null, width = 0, lastLayout = "", lastLegend = "", paintSig = "", observer = null;
    const memo = { detail: {}, legend: {}, table: {}, finding: {} }, keyOf = new WeakMap();
    const stateNodes = new Map(), markNodes = new Map(), labelNodes = new Map(), leaderNodes = new Map(), rowNodes = new Map(), chipNodes = new Map();
    let markOrder = [], labelOrder = [], leaderOrder = [], stateRowOrder = [], abroadRowOrder = [], chipOrder = [];
    let layout = { nodes: [], unit: 1, width: VB_W, height: VB_H }, labels = new Map(), sizes = sizing(VB_W, 1);

    /* Shell */
    const root = node("div", "cmap");
    const bar = node("div", "cmap-bar");
    const filterGroup = node("div", "segmented cmap-filter", { role: "group", "aria-label": "Filter by GPU model" });
    const simNote = node("span", "pill cmap-sim"); simNote.textContent = SIM_NOTE;
    bar.append(filterGroup, simNote);
    const finding = node("p", "cmap-finding");
    const main = node("div", "cmap-main");
    const stage = node("div", "cmap-stage");
    const svg = node("svg:svg", "cmap-svg", { viewBox: US.viewBox, role: "group", "aria-label": "Map of quoted GPU capacity by US state. States with supply and site circles can be focused; the same figures are in the table that follows." , preserveAspectRatio: "xMidYMid meet" });
    const defs = node("svg:defs");
    for (let i = 1; i <= MAX_TINTS; i++) {
      const gap = [10, 8, 6.5, 5, 4][i - 1], pattern = node("svg:pattern", "cmap-pattern", { id: "cmap-t" + i, width: gap, height: gap, patternUnits: "userSpaceOnUse", patternTransform: "rotate(" + (i % 2 ? 45 : 135) + ")" });
      pattern.append(node("svg:rect", "cmap-pattern-bg", { width: gap, height: gap }), node("svg:line", "cmap-pattern-line", { x1: 0, y1: 0, x2: 0, y2: gap }));
      defs.append(pattern);
    }
    const sea = node("svg:rect", "cmap-sea", { x: 0, y: 0, width: VB_W, height: VB_H });
    const statesLayer = node("svg:g", "cmap-states"), overlay = node("svg:g", "cmap-overlay"), leadersLayer = node("svg:g", "cmap-leaders"), marksLayer = node("svg:g", "cmap-marks"), labelsLayer = node("svg:g", "cmap-labels");
    const edges = { hover: [node("svg:path", "cmap-halo"), node("svg:path", "cmap-edge soft")], pin: [node("svg:path", "cmap-halo"), node("svg:path", "cmap-edge")] };
    overlay.append(edges.hover[0], edges.pin[0], edges.hover[1], edges.pin[1]);
    svg.append(defs, sea, statesLayer, overlay, leadersLayer, marksLayer, labelsLayer);
    const legend = node("div", "cmap-legend");
    stage.append(svg, legend);
    const detail = node("section", "cmap-detail", { "aria-label": "Selected region or site" });
    const detailHead = node("div", "cmap-detail-head");
    const detailTitle = node("h3", "cmap-detail-title"), detailKind = node("p", "cmap-detail-kind");
    const clearButton = node("button", "quiet-button cmap-clear", { type: "button" }); clearButton.textContent = "Clear selection"; clearButton.hidden = true;
    const detailTitles = node("div", "cmap-detail-titles"); detailTitles.append(detailTitle, detailKind);
    detailHead.append(detailTitles, clearButton);
    const detailBody = node("div", "cmap-detail-body");
    detail.append(detailHead, detailBody);
    const lists = node("div", "cmap-lists");
    const rankSection = node("section", "cmap-list", { "aria-labelledby": ids + "-rank" }), abroadSection = node("section", "cmap-list cmap-abroad", { "aria-labelledby": ids + "-abroad" });
    const rankTitle = node("h3", "cmap-list-title", { id: ids + "-rank" }), abroadTitle = node("h3", "cmap-list-title", { id: ids + "-abroad" });
    rankTitle.textContent = "States by quoted GPUs"; abroadTitle.textContent = "Outside the US";
    const rankNote = node("p", "cmap-list-note"), abroadNote = node("p", "cmap-list-note");
    const rankList = node("ul", "cmap-rows"), abroadList = node("ul", "cmap-rows");
    rankSection.append(rankTitle, rankNote, rankList); abroadSection.append(abroadTitle, abroadNote, abroadList);
    lists.append(rankSection, abroadSection);
    main.append(stage, detail, lists);
    const foot = node("p", "cmap-foot"); foot.textContent = "Sites are placed in representative metros by an invented rule and do not show where any seller operates. Quantities are GPUs on live quotes in the simulated book. Nothing here is inventory, a firm price or executable.";
    const twin = node("div", "sr-only"), announcer = node("p", "sr-only", { "aria-live": "polite" });
    root.append(bar, finding, main, foot, twin, announcer);
    container.replaceChildren(root);

    /* One path per state, built once. */
    US.states.forEach((state) => {
      const path = node("svg:path", "cmap-state c0", { d: state.d, "fill-rule": "evenodd" });
      stateNodes.set(state.abbr, path); statesLayer.append(path);
      bindInteractive(path, "state:" + state.abbr);
    });

    /* ---- Interaction ---- */
    /* Focus is heard once, on the root: Blink makes any SVG element with its own focus or blur listener keyboard-focusable, which would put every state in the tab order. */
    root.addEventListener("focusin", (event) => { const key = event && keyOf.get(event.target); if (key) { focusKey = key; paint(); } });
    root.addEventListener("focusout", (event) => { const key = event && keyOf.get(event.target); if (key && focusKey === key) { focusKey = null; paint(); } });
    function bindInteractive(target, key) {
      target.addEventListener("pointerenter", (event) => { if (event && event.pointerType === "touch") return; hoverKey = key; paint(); });
      target.addEventListener("pointerleave", (event) => { if (event && event.pointerType === "touch") return; if (hoverKey === key) { hoverKey = null; paint(); } });
      keyOf.set(target, key);
      target.addEventListener("click", () => select(key === pinned ? null : key, true));
      target.addEventListener("keydown", (event) => { if (event && (event.key === "Enter" || event.key === " ")) { if (event.preventDefault) event.preventDefault(); select(key === pinned ? null : key, true); } });
    }
    sea.addEventListener("click", () => { if (pinned) select(null, true); });
    clearButton.addEventListener("click", () => select(null, true));
    function onKeydown(event) { if (event && event.key === "Escape" && (pinned || hoverKey)) { hoverKey = null; select(null, true); } }
    if (typeof document.addEventListener === "function") document.addEventListener("keydown", onKeydown);
    function select(key, fromUser) {
      if (key === pinned) return;
      pinned = key; paint();
      const entity = key ? resolve(key) : null;
      announcer.textContent = entity ? "Selected " + labelOf(entity) + ". " + summaryLine(entity) : "Selection cleared.";
      if (fromUser && key) showDetail();
      if (fromUser && onSelect) onSelect(entity ? selection(entity) : null);
    }
    /* In the one-column layout the detail sits under the map and does not follow the scroll: after a tap, bring it into view if it is not. */
    function showDetail() {
      if (typeof window.matchMedia !== "function" || !window.matchMedia("(max-width: 1000px)").matches || typeof detail.getBoundingClientRect !== "function" || typeof detail.scrollIntoView !== "function") return;
      const rect = detail.getBoundingClientRect(), height = window.innerHeight || 0;
      if (rect.top > height - 140 || rect.bottom < 140) detail.scrollIntoView({ block: "nearest", behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    }
    const selection = (entity) => ({ kind: entity.kind, id: entity.id, label: labelOf(entity), site_ids: entity.kind === "site" ? [entity.id] : entity.sites.map((site) => site.id) });

    /* A key names a state, a site or a country; this finds what it means in the current model. States with no supply still answer. */
    function resolve(key) {
      if (!key) return null;
      if (key.slice(0, 5) === "site:") { const site = model.sites.get(key.slice(5)); return site && (site.gpus > 0 || site.positions.length || site.bids.length) ? { ...site, kind: "site", label: site.provider } : null; }
      const region = model.regions.get(key); if (region) return region;
      if (key.slice(0, 6) === "state:") { const state = STATE_BY_ABBR.get(key.slice(6)); return state ? { key, kind: "state", id: state.abbr, name: state.name, sites: [], providers: new Set(), gpus: 0, eligibleGpus: 0, quotes: 0, eligibleQuotes: 0, models: {}, positions: [], bids: [], places: [], positionGpus: 0, bidGpus: 0, rank: 0 } : null; }
      return null;
    }
    const activeKey = () => hoverKey || focusKey || pinned;
    const labelOf = (entity) => entity.label || entity.name;
    const stateOf = (entity) => (!entity ? null : entity.kind === "state" ? entity.id : entity.kind === "site" ? entity.state : null);

    /* Cheap and idempotent: classes and attributes that are already right are not touched. */
    function paint() {
      if (destroyed) return;
      const active = activeKey(), preview = resolve(active), pin = resolve(pinned);
      if (pinned && !pin) { pinned = null; if (onSelect) onSelect(null); }
      const previewState = stateOf(preview), pinState = stateOf(pin);
      setEdge(edges.hover, previewState && previewState !== pinState ? previewState : null);
      setEdge(edges.pin, pinState);
      markNodes.forEach((mark, id) => { const key = "site:" + id; toggle(mark.group, "is-active", active === key); toggle(mark.group, "is-pinned", pinned === key); setAttr(mark.group, "aria-pressed", pinned === key ? "true" : "false"); toggle(mark.group, "is-kin", !!preview && preview.kind === "state" && preview.id === mark.state); });
      rowNodes.forEach((row, key) => { toggle(row.li, "is-active", active === key || (preview && preview.kind === "site" && "state:" + preview.state === key)); toggle(row.li, "is-pinned", pinned === key); setAttr(row.button, "aria-pressed", pinned === key ? "true" : "false"); });
      stateNodes.forEach((path, abbr) => setAttr(path, "aria-pressed", path.getAttribute("tabindex") === "0" ? (pinned === "state:" + abbr ? "true" : "false") : null));
      renderDetail(preview);
      clearButton.hidden = !pinned;
      toggle(root, "has-pin", !!pinned);
    }
    function setEdge(pair, abbr) {
      const d = abbr && STATE_BY_ABBR.get(abbr) ? STATE_BY_ABBR.get(abbr).d : "";
      pair.forEach((path) => setAttr(path, "d", d || null));
    }

    /* ---- Text that states the facts (aria-labels, the summary, the detail panel) ---- */
    function holdings(entity) {
      const parts = [];
      parts.push(entity.positions.length ? "Our positions: " + entity.positions.length + ", " + int(entity.positions.reduce((s, p) => s + p.gpus, 0)) + " GPUs" : "No positions");
      if (entity.bids.length) parts.push("Open bids: " + entity.bids.length + ", " + int(entity.bids.reduce((s, b) => s + b.gpus, 0)) + " GPUs");
      return parts.join(". ");
    }
    function summaryLine(entity) {
      if (entity.kind === "site") return int(entity.gpus) + " GPUs quoted, grade " + entity.grade + ", " + (entity.place || "placement not stated") + ". " + holdings(entity) + ".";
      return int(entity.gpus) + " GPUs quoted at " + plural(entity.sites.length, "site") + " from " + plural(entity.providers.size, "seller") + ". " + holdings(entity) + ".";
    }

    /* ---- Detail panel ---- */
    const factRow = (label, value, note) => T("div", "cmap-fact", null, T("dt", "", null, label), T("dd", "", null, value, note ? T("span", "cmap-fact-note", null, " " + note) : null));
    function bar100(fraction, cls) { return T("svg:svg", "cmap-meter " + (cls || ""), { viewBox: "0 0 100 6", preserveAspectRatio: "none", "aria-hidden": "true", focusable: "false" }, T("svg:rect", "cmap-meter-track", { x: 0, y: 0, width: 100, height: 6 }), T("svg:rect", "cmap-meter-fill", { x: 0, y: 0, width: fix(Math.max(0, Math.min(1, fraction)) * 100), height: 6 })); }
    function modelMix(entity) {
      const names = Object.keys(entity.models).sort((a, b) => entity.models[b] - entity.models[a] || modelOrder(a, b));
      if (!names.length) return null;
      return T("div", "cmap-block", null, T("h4", "cmap-h4", null, "Model mix"), T("ul", "cmap-mix", null, names.map((name) => T("li", "", null, T("span", "cmap-mix-name", null, name), bar100(entity.models[name] / entity.gpus), T("span", "cmap-mix-gpus", null, int(entity.models[name])), T("span", "cmap-mix-share", null, pctText(share(entity.models[name], entity.gpus)))))));
    }
    function positionBlock(entity) {
      const list = entity.positions, gpus = list.reduce((s, p) => s + p.gpus, 0);
      return T("div", "cmap-block", null, T("h4", "cmap-h4", null, T("svg:svg", "cmap-key", { viewBox: "0 0 12 12", "aria-hidden": "true", focusable: "false" }, T("svg:rect", "cmap-key-pos", { x: 1.5, y: 1.5, width: 9, height: 9, rx: 1.5 })), "Our positions", list.length ? T("span", "cmap-h4-note", null, plural(list.length, "position") + ", " + int(gpus) + " GPUs") : T("span", "cmap-h4-note", null, "none here")),
        list.length ? T("ul", "cmap-items", null, list.map((p) => T("li", "", null,
          T("span", "cmap-item-main", null, p.model + ", " + int(p.gpus) + " GPUs"), T("span", "cmap-item-money" + (/^-/.test(p.unrealized || "") ? " neg" : ""), null, p.unrealized === null ? "no mark" : money(p.unrealized, true)),
          T("span", "cmap-item-sub", null, [p.provider, p.status ? p.status.charAt(0).toUpperCase() + p.status.slice(1) : "", entity.kind === "site" ? "" : p.site.place].filter(Boolean).join(", ")), T("span", "cmap-item-sub right", null, p.unrealized === null ? "" : "unrealized")))) : null);
    }
    function bidBlock(entity) {
      const list = entity.bids, gpus = list.reduce((s, b) => s + b.gpus, 0);
      return T("div", "cmap-block", null, T("h4", "cmap-h4", null, T("svg:svg", "cmap-key", { viewBox: "0 0 12 12", "aria-hidden": "true", focusable: "false" }, T("svg:circle", "cmap-key-bid", { cx: 6, cy: 6, r: 4.5 })), "Open bids", list.length ? T("span", "cmap-h4-note", null, plural(list.length, "bid") + ", " + int(gpus) + " GPUs") : T("span", "cmap-h4-note", null, "none here")),
        list.length ? T("ul", "cmap-items", null, list.map((b) => T("li", "", null,
          T("span", "cmap-item-main", null, b.model + ", " + int(b.gpus) + " GPUs"), T("span", "cmap-item-money", null, "bid " + money(b.bid)),
          T("span", "cmap-item-sub", null, [b.provider, entity.kind === "site" ? "" : b.site.place].filter(Boolean).join(", ")), T("span", "cmap-item-sub right", null, "ask " + money(b.ask) + " per GPU-hour")))) : null);
    }
    function eligibleFact(entity) {
      if (model.filter) return factRow("Eligible", "Not reported for a single model");
      return factRow("Eligible", entity.gpus > 0 ? int(entity.eligibleGpus) + " of " + int(entity.gpus) + " GPUs" : "—", entity.gpus > 0 ? "(" + pctText(share(entity.eligibleGpus, entity.gpus)) + ")" : "");
    }
    function detailFor(entity) {
      const scope = model.filter ? model.filter + " GPUs" : "GPUs";
      if (!entity) {
        const noun = model.filter ? model.filter + " " : "";
        return { title: "United States", kind: model.usSites ? plural(model.usSites, "site") + " in " + plural(model.states.length, "state") : "No US sites", body: model.present.length === 0 ? [T("p", "cmap-empty", null, "No quoted supply in the book" + (model.filter ? " for " + model.filter : "") + ".")] : [
          T("p", "cmap-big", null, T("strong", "", null, int(model.usGpus)), T("span", "", null, " " + noun + "GPUs quoted in the US")),
          T("p", "cmap-sub", null, pctText(share(model.usGpus, model.total)) + " of the " + int(model.total) + " quoted " + (model.filter ? model.filter + " " : "") + "GPUs in the book"),
          T("dl", "cmap-facts", null, factRow("Sites", int(model.usSites)), factRow("Our positions", model.usPositions ? plural(model.usPositions, "position") + ", " + int(model.usPositionGpus) + " GPUs" : "None in the US"), factRow("Open bids", model.bids ? plural(model.bids, "bid") + ", " + int(model.bidGpus) + " GPUs" + (model.usBids ? "" : ", none in the US") : "None")),
          T("p", "cmap-hint", null, "Select a state, site or country for its details.")] };
      }
      if (entity.kind === "site") {
        return { title: entity.provider, kind: "Site" + (entity.name ? " " + entity.name : "") + (entity.place ? ", " + entity.place : ""), grade: entity.grade, body: [
          T("p", "cmap-big", null, T("strong", "", null, int(entity.gpus)), T("span", "", null, " " + scope + " quoted")),
          T("dl", "cmap-facts", null, factRow("Seller grade", entity.grade === "U" ? "Not rated" : entity.grade), model.filter ? null : factRow("Quotes", int(entity.quotes) + " live, " + int(entity.eligibleQuotes) + " eligible"), eligibleFact(entity)),
          modelMix(entity), positionBlock(entity), bidBlock(entity)] };
      }
      const of = entity.kind === "state" ? (entity.rank ? "Rank " + entity.rank + " of " + model.states.length + " states by quoted GPUs" : "No quoted supply") : "Outside the US";
      if (!entity.sites.length) return { title: entity.name, kind: entity.kind === "state" ? "State" : "Country", body: [T("p", "cmap-big", null, T("strong", "", null, "0"), T("span", "", null, " " + scope + " quoted")), T("p", "cmap-sub", null, "No quoted supply here" + (model.filter ? " for " + model.filter : "") + ". No positions or open bids.")] };
      return { title: entity.name, kind: (entity.kind === "state" ? "State, " : "Country, ") + of.charAt(0).toLowerCase() + of.slice(1), body: [
        T("p", "cmap-big", null, T("strong", "", null, int(entity.gpus)), T("span", "", null, " " + scope + " quoted")),
        T("p", "cmap-sub", null, pctText(share(entity.gpus, model.total)) + " of all quoted " + scope),
        T("dl", "cmap-facts", null, factRow("Sites", int(entity.sites.length), entity.sites.length <= 3 ? "(" + entity.places.map(cityOf).join(", ") + ")" : ""), factRow("Sellers", int(entity.providers.size)), model.filter ? null : factRow("Quotes", int(entity.quotes) + " live, " + int(entity.eligibleQuotes) + " eligible"), eligibleFact(entity)),
        modelMix(entity), positionBlock(entity), bidBlock(entity)] };
    }
    function renderDetail(entity) {
      const spec = detailFor(entity && entity.kind ? entity : null), titleSig = spec.title + "|" + spec.kind + "|" + (spec.grade || "");
      if (memo.detail.title !== titleSig) {
        memo.detail.title = titleSig;
        detailTitle.replaceChildren(...[spec.grade ? build(T("span", "grade g-" + spec.grade.toLowerCase(), { title: spec.grade === "U" ? "Seller not rated" : "Seller grade " + spec.grade }, spec.grade)) : null, document.createTextNode(spec.title)].filter(Boolean));
        setText(detailKind, spec.kind);
      }
      mount(detailBody, spec.body, memo.detail);
    }

    /* ---- Sync: model to states, marks, lists, legend, table ---- */
    function syncStates() {
      US.states.forEach((state) => {
        const path = stateNodes.get(state.abbr), region = model.regions.get("state:" + state.abbr), gpus = region ? region.gpus : 0, live = !!region;
        const tint = tintOf(model.scale, gpus);
        const cls = "cmap-state c" + tint + (live ? " is-live" : "") + (region && region.positions.length ? " has-pos" : "");
        setAttr(path, "class", cls);
        setAttr(path, "tabindex", live ? "0" : null); setAttr(path, "role", live ? "button" : null);
        setAttr(path, "aria-label", live ? state.name + ". " + summaryLine(region) : null); setAttr(path, "aria-hidden", live ? null : "true");
        if (!live) setAttr(path, "aria-pressed", null);
      });
    }
    function measure() {
      const rect = typeof stage.getBoundingClientRect === "function" ? stage.getBoundingClientRect() : null, measured = rect && rect.width > 40 ? rect.width : 0;
      width = measured || width || 880; return width;
    }
    function syncMarks() {
      const drawable = model.present.filter((site) => site.state);
      const gmax = drawable.reduce((m, s) => Math.max(m, s.gpus), 0), w = measure();
      sizes = sizing(w, gmax);
      const sig = [w, gmax, model.filter || "", drawable.map((s) => [s.id, s.gpus, s.lat, s.lon, s.positions.length, s.bids.length].join(":")).join("|")].join("#");
      if (sig !== lastLayout) { lastLayout = sig; layout = layoutMarks(drawable, w, sizes); labels = placeLabels(layout, w < 560 ? 10 : 11); }
      const unit = layout.unit, seen = new Set(), order = [], lOrder = [], ldOrder = [];
      layout.nodes.forEach((n) => {
        const site = n.site; seen.add(site.id);
        let mark = markNodes.get(site.id);
        if (!mark) {
          const group = node("svg:g", "cmap-site", { role: "button", tabindex: 0 }), inner = node("svg:g", "cmap-site-in");
          const parts = { hit: node("svg:circle", "cmap-hit"), poshalo: node("svg:rect", "cmap-poshalo"), posbox: node("svg:rect", "cmap-posbox"), bidring: node("svg:circle", "cmap-bidring"), dot: node("svg:circle", "cmap-dot"), focus: node("svg:circle", "cmap-focus") };
          inner.append(parts.hit, parts.poshalo, parts.posbox, parts.bidring, parts.dot, parts.focus); group.append(inner);
          bindInteractive(group, site.key); mark = { group, parts, state: site.state }; markNodes.set(site.id, mark);
        }
        mark.state = site.state;
        const r = n.r * unit, p = mark.parts, half = (n.r + (site.bids.length ? 7.5 : 5.5)) * unit;
        setAttr(mark.group, "transform", "translate(" + fix(n.x * unit) + " " + fix(n.y * unit) + ")");
        setAttr(mark.group, "aria-label", [site.provider + (site.grade === "U" ? ", not rated" : ", grade " + site.grade), site.place, int(site.gpus) + " GPUs quoted", holdings(site)].filter(Boolean).join(". ") + ".");
        setAttr(p.hit, "r", fix(Math.max(r + 8 * unit, 14 * unit)));
        setAttr(p.dot, "r", fix(r)); setAttr(p.dot, "stroke-width", fix(1.5 * unit)); setAttr(p.focus, "r", fix(r + 5 * unit)); setAttr(p.focus, "stroke-width", fix(2 * unit));
        const ringR = r + 3 * unit, dots = Math.max(8, Math.round((2 * Math.PI * ringR) / (3.8 * unit)));
        setAttr(p.bidring, "r", fix(ringR)); setAttr(p.bidring, "stroke-width", fix(1.8 * unit)); setAttr(p.bidring, "stroke-dasharray", fix(0.1 * unit) + " " + fix((2 * Math.PI * ringR) / dots - 0.1 * unit)); toggle(p.bidring, "is-off", !site.bids.length);
        [p.poshalo, p.posbox].forEach((rect, index) => { setAttr(rect, "x", fix(-half)); setAttr(rect, "y", fix(-half)); setAttr(rect, "width", fix(half * 2)); setAttr(rect, "height", fix(half * 2)); setAttr(rect, "rx", fix(2 * unit)); setAttr(rect, "stroke-width", fix((index ? 2 : 5) * unit)); toggle(rect, "is-off", !site.positions.length); });
        toggle(mark.group, "has-pos", site.positions.length > 0); toggle(mark.group, "has-bid", site.bids.length > 0); toggle(mark.group, "is-empty", site.gpus <= 0);
        order.push(mark.group);
        let leader = leaderNodes.get(site.id);
        if (n.moved) {
          if (!leader) { leader = { line: node("svg:line", "cmap-leader"), dot: node("svg:circle", "cmap-anchor") }; leaderNodes.set(site.id, leader); }
          setAttr(leader.line, "stroke-width", fix(unit)); setAttr(leader.line, "x1", fix(n.ax * unit)); setAttr(leader.line, "y1", fix(n.ay * unit)); setAttr(leader.line, "x2", fix(n.x * unit)); setAttr(leader.line, "y2", fix(n.y * unit));
          setAttr(leader.dot, "cx", fix(n.ax * unit)); setAttr(leader.dot, "cy", fix(n.ay * unit)); setAttr(leader.dot, "r", fix(2 * unit));
          ldOrder.push(leader.line, leader.dot);
        }
        const label = labels.get(site.id);
        if (label) {
          let text = labelNodes.get(site.id); if (!text) { text = node("svg:text", "cmap-label"); labelNodes.set(site.id, text); }
          setAttr(text, "x", fix(label.x * unit)); setAttr(text, "y", fix(label.y * unit)); setAttr(text, "text-anchor", label.anchor); setAttr(text, "font-size", fix((w < 560 ? 10 : 11) * unit)); setAttr(text, "stroke-width", fix(3.5 * unit)); setText(text, label.text);
          lOrder.push(text);
        }
      });
      [markNodes, leaderNodes, labelNodes].forEach((map) => map.forEach((value, id) => { if (!seen.has(id)) map.delete(id); }));
      markOrder = syncChildren(marksLayer, markOrder, order); leaderOrder = syncChildren(leadersLayer, leaderOrder, ldOrder); labelOrder = syncChildren(labelsLayer, labelOrder, lOrder);
    }
    /* Children are only moved when the set or the order changed, so a focused mark keeps its focus through a poll. */
    function syncChildren(parent, current, next) {
      if (current.length === next.length && current.every((item, index) => item === next[index])) return current;
      const focused = typeof document.activeElement !== "undefined" ? document.activeElement : null;
      parent.replaceChildren(...next);
      if (focused && next.indexOf(focused) >= 0 && typeof focused.focus === "function") focused.focus();
      return next;
    }

    function rowFor(region, max) {
      let row = rowNodes.get(region.key);
      if (!row) {
        const li = node("li", "cmap-row"), button = node("button", "cmap-row-button", { type: "button" });
        li.append(button); bindInteractive(button, region.key); row = { li, button, sig: "" }; rowNodes.set(region.key, row);
      }
      const holds = [region.positions.length ? T("span", "cmap-row-mark", { title: plural(region.positions.length, "position") }, T("svg:svg", "cmap-key", { viewBox: "0 0 12 12", "aria-hidden": "true", focusable: "false" }, T("svg:rect", "cmap-key-pos", { x: 1.5, y: 1.5, width: 9, height: 9, rx: 1.5 })), T("span", "sr-only", null, plural(region.positions.length, "position"))) : null,
        region.bids.length ? T("span", "cmap-row-mark", { title: plural(region.bids.length, "open bid") }, T("svg:svg", "cmap-key", { viewBox: "0 0 12 12", "aria-hidden": "true", focusable: "false" }, T("svg:circle", "cmap-key-bid", { cx: 6, cy: 6, r: 4.5 })), T("span", "sr-only", null, plural(region.bids.length, "open bid"))) : null];
      const spec = [T("span", "cmap-row-name", null, region.kind === "state" ? T("span", "cmap-abbr", null, region.id) : T("span", "cmap-abbr", null, region.id), region.name), bar100(max > 0 ? region.gpus / max : 0, region.kind === "state" ? "t" + tintOf(model.scale, region.gpus) : "t3"), T("span", "cmap-row-gpus", null, int(region.gpus)), T("span", "cmap-row-marks", null, holds)];
      const sig = JSON.stringify(spec); if (row.sig !== sig) { row.sig = sig; row.button.replaceChildren(...spec.map(build)); }
      setAttr(row.button, "aria-label", region.name + ". " + summaryLine(region));
      return row.li;
    }
    function syncLists() {
      const stateRows = model.states.map((region) => rowFor(region, model.stateMax)), abroadRows = model.abroad.map((region) => rowFor(region, model.abroadMax));
      const keep = new Set([...model.states, ...model.abroad].map((r) => r.key)); rowNodes.forEach((row, key) => { if (!keep.has(key)) rowNodes.delete(key); });
      stateRowOrder = syncChildren(rankList, stateRowOrder, stateRows); abroadRowOrder = syncChildren(abroadList, abroadRowOrder, abroadRows);
      setText(rankNote, model.states.length ? plural(model.states.length, "state") + " with quoted supply or a position. Bars are scaled to the largest state." : "No state has quoted supply" + (model.filter ? " for " + model.filter : "") + ".");
      setText(abroadNote, model.abroad.length ? int(model.abroadGpus) + " GPUs, " + pctText(share(model.abroadGpus, model.total)) + " of the quoted total. Not drawn on the map. Bars are scaled to the largest country." : "No supply outside the US" + (model.filter ? " for " + model.filter : "") + ".");
      toggle(abroadSection, "is-empty", !model.abroad.length);
    }
    function syncFilter() {
      const labels = ["All models"].concat(model.models), keys = [null].concat(model.models);
      const buttons = keys.map((name, index) => {
        const id = name || "__all"; let chip = chipNodes.get(id);
        if (!chip) {
          chip = node("button", "tab", { type: "button" }); chip.textContent = labels[index];
          chip.addEventListener("click", () => { filter = name; recompute(); }); chipNodes.set(id, chip);
        }
        setAttr(chip, "aria-pressed", (filter || null) === name ? "true" : "false");
        return chip;
      });
      const keep = new Set(keys.map((name) => name || "__all")); chipNodes.forEach((chip, id) => { if (!keep.has(id)) chipNodes.delete(id); });
      chipOrder = syncChildren(filterGroup, chipOrder, buttons);
      toggle(filterGroup, "is-single", model.models.length < 2); filterGroup.hidden = model.models.length < 2;
    }
    function syncFinding() {
      const noun = model.filter ? model.filter + " GPUs" : "GPUs";
      const parts = !model.present.length ? ["No quoted supply in the book" + (model.filter ? " for " + model.filter : "") + "."] : [
        model.usSites ? int(model.usGpus) + " of " + int(model.total) + " quoted " + noun + " (" + pctText(share(model.usGpus, model.total)) + ") are at " + plural(model.usSites, "US site") + "." : "None of the " + int(model.total) + " quoted " + noun + " are at US sites.",
        model.positions ? "The desk holds " + plural(model.positions, "position") + " (" + int(model.positionGpus) + " GPUs), " + int(model.usPositions) + " in the US." : "The desk holds no positions" + (model.filter ? " in " + model.filter : "") + "."];
      setText(finding, parts.join(" "));
    }
    function syncLegend() {
      const scale = model.scale, drawn = layout.nodes.length, ref = drawn ? niceRef(sizes.gmax) : 0, refs = ref ? [ref, niceRef(ref / 4) || ref / 4].filter((v, i, a) => v > 0 && a.indexOf(v) === i) : [];
      const sig = [scale.step, scale.count, refs.join(","), Math.round(sizes.rMax), model.filter || "", model.positions, model.bids, drawn].join("|");
      if (sig === lastLegend) return; lastLegend = sig;
      const swatches = []; for (let i = 1; i <= scale.count; i++) swatches.push(T("span", "cmap-sw c" + i, null, T("span", "sr-only", null, int((i - 1) * scale.step + 1) + " to " + int(i * scale.step) + " GPUs")));
      const ticks = []; for (let i = 1; i <= scale.count; i++) ticks.push(T("span", "cmap-tick", null, compact(i * scale.step)));
      const rMaxRef = refs.length ? sizes.radius(refs[0]) : sizes.rMin, boxW = Math.ceil(rMaxRef * 2) + 2;
      const circles = refs.map((value) => { const r = sizes.radius(value); return T("svg:circle", "cmap-ref", { cx: fix(boxW / 2), cy: fix(boxW - r - 1), r: fix(r) }); });
      const labelsRef = refs.map((value) => T("span", "cmap-ref-label", null, int(value)));
      const group = (cls, ...kids) => T("div", "cmap-lg " + cls, null, kids);
      const specs = [
        group("scale", T("p", "cmap-lg-title", null, "Quoted GPUs per state"), scale.count ? T("div", "cmap-sw-row", null, swatches) : null, scale.count ? T("div", "cmap-tick-row", null, ticks) : null,
          T("div", "cmap-none", null, T("span", "cmap-sw c0"), T("span", "", null, "No quoted supply"))),
        refs.length ? group("size", T("p", "cmap-lg-title", null, "Circle area is GPUs at a site"), T("div", "cmap-ref-row", null, T("svg:svg", "cmap-ref-svg", { width: boxW, height: boxW, viewBox: "0 0 " + boxW + " " + boxW, "aria-hidden": "true", focusable: "false" }, circles), T("span", "cmap-ref-labels", null, labelsRef))) : null,
        model.positions || model.bids ? group("marks", T("p", "cmap-lg-title", null, "Marks"), T("ul", "cmap-keys", null,
          model.positions ? T("li", "", null, T("svg:svg", "cmap-key", { viewBox: "0 0 12 12", "aria-hidden": "true", focusable: "false" }, T("svg:rect", "cmap-key-pos", { x: 1.5, y: 1.5, width: 9, height: 9, rx: 1.5 })), "Our position") : null,
          model.bids ? T("li", "", null, T("svg:svg", "cmap-key", { viewBox: "0 0 12 12", "aria-hidden": "true", focusable: "false" }, T("svg:circle", "cmap-key-bid", { cx: 6, cy: 6, r: 4.5 })), "Open bid") : null)) : null];
      legend.replaceChildren(...specs.filter(Boolean).map(build));
    }
    function niceRef(value) {
      if (!(value > 0)) return 0;
      const unit = Math.pow(10, Math.floor(Math.log10(value)));
      return [1, 2, 2.5, 5, 10].map((n) => n * unit).filter((n) => n <= value + 1e-9).pop() || value;
    }
    function syncTable() {
      const head = ["Region", "Quoted GPUs", "Sites", "Sellers", "Eligible GPUs", "Our positions", "Open bids"];
      const line = (region) => T("tr", "", null, T("th", "", { scope: "row" }, region.name), T("td", "", null, int(region.gpus)), T("td", "", null, int(region.sites.length)), T("td", "", null, int(region.providers.size)), T("td", "", null, model.filter ? "not reported" : int(region.eligibleGpus)),
        T("td", "", null, region.positions.length ? plural(region.positions.length, "position") + ", " + int(region.positionGpus) + " GPUs" : "none"), T("td", "", null, region.bids.length ? plural(region.bids.length, "bid") + ", " + int(region.bidGpus) + " GPUs" : "none"));
      const rest = US.states.length - model.states.length;
      const spec = [T("table", "", null, T("caption", "", null, "Quoted GPUs by US state and by country outside the US" + (model.filter ? ", " + model.filter + " only" : "") + ". " + SIM_NOTE + "."),
        T("thead", "", null, T("tr", "", null, head.map((label) => T("th", "", { scope: "col" }, label)))),
        T("tbody", "", null, model.states.map(line), rest > 0 ? T("tr", "", null, T("th", "", { scope: "row" }, plural(rest, "other state") + " with no quoted supply"), T("td", "", null, "0"), T("td", "", { colspan: 5 }, "")) : null, model.abroad.map(line)))];
      mount(twin, spec, memo.table);
    }

    function recompute() {
      if (destroyed) return;
      model = buildModel(input, filter);
      if (filter && model.models.indexOf(filter) < 0) { filter = null; model = buildModel(input, null); }
      syncFilter(); syncStates(); syncMarks(); syncLists(); syncFinding(); syncLegend(); syncTable();
      if (!drawn && model.present.length) reveal();
      paint();
    }
    function reveal() {
      drawn = true; toggle(root, "cmap-reveal", true);
      if (typeof window.setTimeout === "function") revealTimer = window.setTimeout(() => { revealTimer = null; toggle(root, "cmap-reveal", false); }, 2400);
    }
    const signature = (data) => JSON.stringify([
      (data.sites || []).map((s) => s && [s.id, s.name, s.provider, s.provider_id, s.grade, s.state, s.country, s.place, s.lat, s.lon, s.capacity]),
      (data.positions || []).map((p) => p && [p.id, p.site_id, p.model, p.gpus, p.status, p.exact && p.exact.unrealized_usd]),
      (data.bids || []).map((b) => b && [b.id, b.site_id, b.model, b.gpus, b.status, b.exact && b.exact.bid, b.exact && b.exact.ask])]);

    function update(data) {
      if (destroyed) return;
      const next = data && typeof data === "object" ? { sites: Array.isArray(data.sites) ? data.sites : [], positions: Array.isArray(data.positions) ? data.positions : [], bids: Array.isArray(data.bids) ? data.bids : [] } : { sites: [], positions: [], bids: [] };
      const sig = signature(next);
      if (sig === lastSig) { onResize(); return; }
      lastSig = sig; input = next; recompute();
    }
    function onResize() {
      if (destroyed) return;
      const before = width; measure();
      if (Math.abs(width - before) > 1) { syncMarks(); syncLegend(); }
    }
    if (typeof window.ResizeObserver === "function") { observer = new window.ResizeObserver(onResize); observer.observe(stage); }
    else if (typeof window.addEventListener === "function") window.addEventListener("resize", onResize);

    function destroy() {
      if (destroyed) return; destroyed = true;
      if (revealTimer !== null && typeof window.clearTimeout === "function") window.clearTimeout(revealTimer);
      if (observer) observer.disconnect(); else if (typeof window.removeEventListener === "function") window.removeEventListener("resize", onResize);
      if (typeof document.removeEventListener === "function") document.removeEventListener("keydown", onKeydown);
      container.replaceChildren();
      [stateNodes, markNodes, labelNodes, leaderNodes, rowNodes, chipNodes].forEach((map) => map.clear());
    }
    recompute();
    return Object.freeze({ update, destroy });
  }

  window.ComputeMap = Object.freeze({ create });
})();
