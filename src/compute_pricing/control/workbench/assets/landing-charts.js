/* The landing page's chart engine: horizontal bar lists drawn at the size they are shown at.
   LandingCharts.bars(host, spec) draws into (or patches) a host element and keeps the same <svg> alive across polls:
   it skips the work when nothing printed has changed, moves bars in place when a number has, and never rebuilds a chart
   while the pointer is over it or focus is inside it. Colour comes only from CSS classes (bf-tone-*), so both themes and
   the strict content security policy apply: no inline styles, no markup built from strings, positions by presentation attributes.
   Each chart is three things in the host: an <svg role="img"> with a short label (the picture), an overlay <svg> of
   focusable row targets and one tooltip (the interaction), and a visually hidden <table> carrying every number (the data). */
(() => {
  "use strict";
  const NS = "http://www.w3.org/2000/svg";
  /* [font-size, weight] of every kind of chart text. Nothing is smaller than 13px, and charts draw 1:1, so these are the sizes read. */
  const TEXT = { label: [15, 600], sub: [13, 400], tick: [13, 400], value: [15, 600], tip: [13, 400], tipHead: [15, 700] };
  const BAR = 14, RADIUS = 4, GAP = 2, CHIP = 22, VALUE_GAP = 10, MIN_WIDTH = 160, MAX_INTERVALS = 6, ENTRANCE_MS = 1800;
  const BROKEN = /NaN|undefined|Infinity|\[object/g;

  const finite = (value) => typeof value === "number" && Number.isFinite(value);
  const safe = (value) => (value === null || value === undefined ? "" : String(value).replace(BROKEN, "—"));
  const r2 = (value) => Math.round(value * 100) / 100;
  /* One precision rule for a cost per GPU-hour: three decimals under $10, two from there. */
  function money(value) {
    const v = Number(value); if (value === null || value === undefined || value === "" || !Number.isFinite(v)) return "—";
    return (v < 0 ? "−$" : "$") + (Math.abs(v) < 10 ? Math.abs(v).toFixed(3) : Math.abs(v).toFixed(2));
  }
  /* The number money() prints, so a percentage can be worked out from the figures on the page. */
  const printed = (value) => { const text = money(value); return text === "—" ? NaN : Number(text.replace("−$", "-").replace("$", "")); };

  function el(tag, attributes, ...children) {
    const node = document.createElementNS(NS, tag);
    Object.entries(attributes || {}).forEach(([name, value]) => { if (value !== null && value !== undefined) node.setAttribute(name, String(value)); });
    children.flat().forEach((child) => { if (child) node.append(child); });
    return node;
  }
  const html = (tag, className) => { const node = document.createElement(tag); if (className) node.className = className; return node; };
  const setAttr = (node, name, value) => { const text = String(value); if (node.getAttribute(name) !== text) node.setAttribute(name, text); };
  const setText = (node, value) => { const text = safe(value); if (node.textContent !== text) node.textContent = text; };
  function label(className, content, attributes) { const node = el("text", { class: className, ...attributes }); node.textContent = safe(content); return node; }
  const move = (x, y) => "translate(" + r2(x) + " " + r2(y) + ")";

  /* ---- text measurement: the canvas where there is one, an estimate where there is not ---- */
  let canvas;
  function measurer(host) {
    if (canvas === undefined) {
      canvas = null;
      try { const node = document.createElement("canvas"); const context = typeof node.getContext === "function" ? node.getContext("2d") : null; if (context && typeof context.measureText === "function") canvas = context; } catch (_) { canvas = null; }
    }
    let family = "system-ui, sans-serif";
    try { const found = window.getComputedStyle && window.getComputedStyle(host).fontFamily; if (found) family = found; } catch (_) { /* keep the default */ }
    return (content, [size, weight]) => {
      const text = safe(content); if (!text) return 0;
      if (canvas) { try { canvas.font = weight + " " + size + "px " + family; const width = canvas.measureText(text).width; if (finite(width) && width > 0) return Math.ceil(width * 1.04); } catch (_) { /* estimate below */ } }
      return Math.ceil(text.length * size * (weight >= 600 ? 0.6 : 0.55));
    };
  }
  function fitText(measure, content, font, room) {
    const text = safe(content); if (!text || measure(text, font) <= room) return text;
    let cut = text.length; while (cut > 1 && measure(text.slice(0, cut) + "…", font) > room) cut -= 1;
    return text.slice(0, cut).trimEnd() + "…";
  }

  /* ---- entrance bookkeeping: a class that plays once, then is dropped ---- */
  const waiting = [];
  function afterEntrance(action) {
    if (typeof setTimeout === "function") setTimeout(action, ENTRANCE_MS); else waiting.push(action);  // without timers, at the next update
  }
  function flushEntrances() { waiting.splice(0).forEach((action) => { try { action(); } catch (_) { /* a stale node */ } }); }

  /* ---- geometry ---- */
  function segmentPath(x0, x1, y, height, radius, end) {
    if (!end) return "M" + x0 + " " + y + "H" + x1 + "V" + (y + height) + "H" + x0 + "Z";
    const r = Math.max(0, Math.min(radius, x1 - x0, height / 2));  // the same commands at any width, so a path can move smoothly
    return "M" + x0 + " " + y + "H" + (x1 - r) + "A" + r + " " + r + " 0 0 1 " + x1 + " " + (y + r) + "V" + (y + height - r) + "A" + r + " " + r + " 0 0 1 " + (x1 - r) + " " + (y + height) + "H" + x0 + "Z";
  }
  function niceStep(span) {
    const raw = (span > 0 ? span : 1) / 5; const magnitude = 10 ** Math.floor(Math.log10(raw));
    return [1, 2, 2.5, 5, 10].map((unit) => unit * magnitude).find((candidate) => candidate >= raw - 1e-12);
  }
  /* The axis only ever grows (until the epoch or `resetKey` changes), so a bar crossing a round number does not rescale the others. */
  function domainFor(st, axis, peak, resetKey) {
    if (st.resetKey !== resetKey) { st.resetKey = resetKey; st.reach = 0; st.labelW = 0; st.valueW = 0; }
    const need = Math.max(axis.floor || 0, peak * (axis.headroom || 1), 1e-9);
    let reach = axis.grow === false ? need : Math.max(need, st.reach || 0);
    let step;
    if (axis.step) { step = axis.step; for (let k = 0; Math.ceil(reach / step - 1e-9) > MAX_INTERVALS && k < 200; k++) step *= [2, 2.5, 2][k % 3]; } else step = niceStep(reach);  // a fixed step grows 1-2-5 until it fits
    reach = Math.ceil(reach / step - 1e-9) * step; if (axis.grow !== false) st.reach = reach;
    const ticks = []; for (let i = 0; i * step <= reach + 1e-9; i++) ticks.push(r2(i * step));
    return { reach, step, ticks };
  }

  /* One row of a spec as plain data. `value` is a single bar; `parts` is a stack that shares the row's scale. */
  function rowOf(row, index, spec) {
    const source = row || {};
    const parts = (Array.isArray(source.parts) ? source.parts : [{ value: source.value, tone: source.tone }])
      .map((part) => ({ value: finite(part && part.value) && part.value > 0 ? part.value : 0, tone: (part && part.tone) || source.tone || spec.tone || "accent", above: safe(part && part.above) }));
    const tip = source.tip || {};
    return {
      key: safe(source.key === undefined ? index : source.key) || String(index), label: safe(source.label), sub: safe(source.sub), parts, total: parts.reduce((sum, part) => sum + part.value, 0),
      valueText: safe(source.text), note: safe(source.note), chip: source.chip ? safe(source.chip) : "", ref: source.ref === true,
      tip: { head: safe(tip.head), lines: (Array.isArray(tip.lines) ? tip.lines : []).map(safe).filter(Boolean) },
      aria: safe(source.aria) || [source.label, source.sub, source.text, source.note].map(safe).filter(Boolean).join(", "), cells: (Array.isArray(source.cells) ? source.cells : [source.label, source.sub, source.text]).map(safe),
    };
  }

  function layout(st, spec, width) {
    st.measure = measurer(st.host); const measure = st.measure; const rows = (Array.isArray(spec.rows) ? spec.rows : []).map((row, index) => rowOf(row, index, spec));
    const axis = spec.axis || {}; const peak = Math.max(0, ...rows.map((row) => row.total));
    const dom = domainFor(st, axis, peak, spec.resetKey);
    if (st.frameWidth !== width) { st.frameWidth = width; st.labelW = 0; st.valueW = 0; }
    const hasLabels = rows.some((row) => row.label || row.sub);
    let labelNeed = 0; let valueNeed = 0;
    rows.forEach((row) => {
      labelNeed = Math.max(labelNeed, measure(row.label, TEXT.label), measure(row.sub, TEXT.sub));
      if (row.valueText) valueNeed = Math.max(valueNeed, measure(row.valueText, TEXT.value) + (row.chip ? CHIP + 8 : 0));
    });
    if (hasLabels) st.labelW = Math.max(st.labelW, Math.min(Math.ceil((labelNeed + 16) / 4) * 4, Math.floor(width * 0.5)));
    if (valueNeed) st.valueW = Math.max(st.valueW, Math.min(Math.ceil((valueNeed + VALUE_GAP + 4) / 4) * 4, Math.floor(width * 0.34)));
    const valueW = valueNeed ? st.valueW : 0;
    const compact = spec.compact === true || (spec.compact !== false && hasLabels && width - st.labelW - valueW < 140);
    const labelW = hasLabels && !compact ? st.labelW : 0;
    const pitch = compact && hasLabels ? (spec.compactPitch || 54) : (spec.pitch || 48);
    const base = compact ? 0 : Math.round(labelW); const x0 = base + 1; const right = Math.max(x0 + 40, Math.min(Math.round(width - valueW), width - 1)); const plotW = right - x0;
    const X = (value) => x0 + (Math.min(Math.max(value, 0), dom.reach) / dom.reach) * plotW;
    const top = dom.ticks.length > 1 && axis.show !== false ? 30 : 4;
    const every = plotW / Math.max(1, dom.ticks.length - 1) < 40 ? 2 : 1;  // thin the labels, never the gridlines, when they would crowd
    const lastShown = dom.ticks.length - 1 - ((dom.ticks.length - 1) % every);
    const ticks = dom.ticks.map((value, index) => {
      const x = index === 0 ? base + 0.5 : Math.round(X(value)) + 0.5; const text = axis.show === false || index % every ? "" : safe(axis.format ? axis.format(value, index === lastShown) : value);
      const w = measure(text, TEXT.tick); const anchor = x - w / 2 < 0 ? "start" : x + w / 2 > width ? "end" : "middle";
      return { value, x, text, anchor, tx: anchor === "start" ? Math.max(0, x - 0.5) : anchor === "end" ? Math.min(width, x + 0.5) : x };
    });
    let cursor = top; const spans = []; const views = rows.map((row, index) => {
      if (row.ref) { cursor += 12; }
      const rowTop = cursor; cursor += pitch;
      const hasText = Boolean(row.label || row.sub);
      const cy = compact && hasText ? rowTop + 34 : rowTop + pitch / 2;
      const segs = []; let cum = 0; const live = row.parts.filter((part) => part.value > 0); let seen = 0;
      row.parts.forEach((part) => {
        if (!(part.value > 0)) return;
        const a = Math.round(X(cum)); cum += part.value; const b = Math.round(X(cum)); seen += 1;
        const first = seen === 1; const last = seen === live.length; const s0 = a + (first ? 0 : GAP / 2); const s1 = Math.max(b - (last ? 0 : GAP / 2), s0 + 3);
        const seg = { d: segmentPath(s0, s1, cy - BAR / 2, BAR, RADIUS, last), tone: part.tone, x0: s0, x1: s1, above: null };
        if (part.above) { const w = measure(part.above, TEXT.tick); const mid = (s0 + s1) / 2; seg.above = { text: part.above, x: Math.round(Math.min(Math.max(mid, w / 2), width - w / 2)), y: cy - BAR / 2 - 12 }; }
        segs.push(seg);
      });
      const barEnd = segs.length ? segs[segs.length - 1].x1 : x0;
      const labelFit = compact ? width - 8 : labelW - 16;
      const labelText = fitText(measure, row.label, TEXT.label, labelFit); const subText = fitText(measure, row.sub, TEXT.sub, compact ? Math.max(40, width - measure(labelText, TEXT.label) - 18) : labelFit);
      const view = {
        key: row.key, rank: Math.min(index, 6), ref: row.ref, top: rowTop, cy, anchor: barEnd,
        label: labelText, sub: subText, labelX: 0, labelY: compact ? rowTop + 12 : subText ? cy - 9 : cy, subX: compact ? measure(labelText, TEXT.label) + 10 : 0, subY: compact ? rowTop + 12 : cy + 10,
        segs, value: row.valueText && !row.note ? { text: row.valueText, x: barEnd + VALUE_GAP + (row.chip ? CHIP + 8 : 0), y: cy } : null,
        chip: row.chip && !row.note ? { grade: row.chip, x: barEnd + VALUE_GAP, y: cy - CHIP / 2 } : null,
        note: row.note ? { text: row.note, x: x0 + 12, y: cy } : null,
        h: pitch, tip: row.tip, aria: row.aria, cells: row.cells,
      };
      spans.push(compact && hasText ? [cy - BAR / 2 - 5, cy + BAR / 2 + 5] : null);
      return view;
    });
    const height = Math.max(cursor + 6, top + 56);
    const vertical = (x) => (compact && hasLabels ? spans.filter(Boolean).map(([y1, y2]) => "M" + x + " " + y1 + "V" + y2).join("") : "M" + x + " " + (top - 8) + "V" + (cursor));
    const grid = ticks.slice(1).map((tick) => vertical(tick.x)).join("");
    const first = views.findIndex((row) => row.ref);
    const view = {
      width, height, compact, labelW, valueW, base, x0, right, ticks, grid, baseline: vertical(base + 0.5), separator: first >= 0 ? views[first].top - 6 : null,
      rows: views, empty: rows.length ? "" : safe(spec.empty || "Nothing to show yet."), description: safe(spec.description), title: safe(spec.title),
      table: { caption: safe(spec.title), head: (spec.table && Array.isArray(spec.table.head) ? spec.table.head : ["Row", "Detail", "Value"]).map(safe), rows: views.map((row) => row.cells) },
      grow: spec.grow === true,
    };
    view.shape = JSON.stringify([width, height, compact, labelW, valueW, ticks.map((tick) => [tick.value, tick.x, tick.text]), view.separator, view.empty,
      views.map((row) => [row.key, row.ref, row.segs.map((seg) => Boolean(seg.above)), Boolean(row.sub), Boolean(row.chip), Boolean(row.note), Boolean(row.value), row.top]), view.table.head, view.table.rows.map((cells) => cells.length)]);
    view.sig = JSON.stringify(view);
    return view;
  }

  /* A grade chip takes its colour from its letter, so a poll that changes the letter changes the class too. */
  const chipClass = (row) => "bf-chip g-" + row.chip.grade.toLowerCase().slice(0, 1) + " bf-r" + row.rank;

  /* ---- drawing ---- */
  const states = new WeakMap(); const registry = new Set(); let documentWired = false;

  function stateFor(host) {
    let st = states.get(host);
    if (!st) {
      st = { host, spec: null, svg: null, hits: null, table: null, refs: null, sig: "", shape: "", reach: 0, resetKey: undefined, labelW: 0, valueW: 0, frameWidth: 0, entered: false, tipRow: -1, pending: false, ro: null, observed: -1, measure: null };
      states.set(host, st); registry.add(st); wireDocument(); observe(st);
    }
    return st;
  }
  function wireDocument() {
    if (documentWired || typeof document.addEventListener !== "function") return; documentWired = true;
    document.addEventListener("keydown", (event) => { if (event && event.key === "Escape") registry.forEach(hideTip); });
    document.addEventListener("pointerdown", (event) => registry.forEach((st) => { if (st.tipRow >= 0 && !(st.hits && typeof st.hits.contains === "function" && st.hits.contains(event && event.target))) hideTip(st); }));
  }
  function observe(st) {
    if (typeof window.ResizeObserver !== "function") return;
    try {
      st.ro = new window.ResizeObserver((entries) => {
        const box = entries && entries[0] && entries[0].contentRect; const width = Math.floor(box && finite(box.width) ? box.width : Number(st.host.clientWidth) || 0);
        if (width === st.observed) return; st.observed = width;  // a change of height alone is not a reason to redraw
        if (st.spec) { try { draw(st); } catch (error) { report(error); } }
      });
      st.observed = Math.floor(Number(st.host.clientWidth) || 0); st.ro.observe(st.host);
    } catch (_) { st.ro = null; }
  }
  const report = (error) => { try { if (window.console && console.error) console.error("LandingCharts:", error); } catch (_) { /* nothing to report to */ } };
  function pickWidth(host, spec) {
    const cap = spec.maxWidth > 0 ? spec.maxWidth : 560; const measured = host.clientWidth;
    if (measured === 0) return 0;  // not shown (a hidden tab): there is nothing to draw into; the observer redraws when it has a width
    const available = finite(measured) && measured > 0 ? Math.floor(measured) : (spec.fallbackWidth || cap);
    return Math.max(MIN_WIDTH, Math.min(cap, available));
  }
  function busy(st) {
    const node = st.hits || st.svg; if (!node || typeof node.matches !== "function") return false;
    try { return Boolean(node.matches(":hover") || node.matches(":focus-within")); } catch (_) { return false; }
  }
  const later = (action) => { if (typeof setTimeout === "function") setTimeout(action, 60); else Promise.resolve().then(action); };
  function flush(st) { later(() => { if (st.pending && st.spec && !busy(st)) { try { draw(st); } catch (error) { report(error); } } }); }

  function draw(st) {
    const spec = st.spec; const width = pickWidth(st.host, spec); if (!width) return st.svg;
    const view = layout(st, spec, width);
    if (st.svg && view.sig === st.sig) return st.svg;
    if (st.svg && view.shape === st.shape) { patch(st, view); st.sig = view.sig; st.pending = false; return st.svg; }
    if (st.svg && busy(st)) { st.pending = true; return st.svg; }  // never replace the chart under the pointer or the keyboard focus
    build(st, view); st.sig = view.sig; st.shape = view.shape; st.pending = false;
    return st.svg;
  }

  function build(st, view) {
    const refs = { rows: [] }; const size = { width: view.width, height: view.height, viewBox: "0 0 " + view.width + " " + view.height };
    const svg = el("svg", { ...size, class: "bf-chart", role: "img", "aria-label": view.description, focusable: "false" });
    const hits = el("svg", { ...size, class: "bf-hits", role: "group", "aria-label": view.title ? view.title + " rows" : "Chart rows" });
    view.ticks.forEach((tick) => { if (tick.text) svg.append(label("bf-tick", tick.text, { x: tick.tx, y: 8, "text-anchor": tick.anchor, dy: "0.35em" })); });
    if (view.grid) svg.append(el("path", { class: "bf-grid", d: view.grid }));
    if (view.baseline) svg.append(el("path", { class: "bf-base", d: view.baseline }));
    if (view.separator !== null) svg.append(el("path", { class: "bf-sep", d: "M0 " + (view.separator + 0.5) + "H" + view.width }));
    if (view.empty) svg.append(label("bf-note", view.empty, { x: 0, y: 26, dy: "0.35em" }));
    view.rows.forEach((row, index) => {
      const rank = " bf-r" + row.rank; const ref = { row, bars: [], titled: true };
      const group = el("g", { class: "bf-row" + (row.ref ? " bf-ref" : "") });
      if (row.label) ref.label = label("bf-row-label" + rank, row.label, { x: row.labelX, y: row.labelY, dy: "0.35em" });
      if (row.sub) ref.sub = label("bf-row-sub" + rank, row.sub, { x: row.subX, y: row.subY, dy: "0.35em" });
      ref.aboves = [];
      row.segs.forEach((seg) => { ref.bars.push(el("path", { class: "bf-bar bf-tone-" + seg.tone, d: seg.d })); ref.aboves.push(seg.above ? label("bf-seg-label" + rank, seg.above.text, { transform: move(seg.above.x, seg.above.y), "text-anchor": "middle", dy: "0.35em" }) : null); });
      if (ref.bars.length) ref.group = el("g", { class: "bf-bar-group" + rank }, ref.bars);
      if (row.value) ref.value = label("bf-value" + rank, row.value.text, { transform: move(row.value.x, row.value.y), dy: "0.35em" });
      if (row.note) ref.note = label("bf-note" + rank, row.note.text, { transform: move(row.note.x, row.note.y), dy: "0.35em" });
      if (row.chip) {
        ref.chip = el("g", { class: chipClass(row), transform: move(row.chip.x, row.chip.y) });
        ref.chipText = label("bf-chip-text", row.chip.grade, { x: CHIP / 2, y: CHIP / 2, "text-anchor": "middle", dy: "0.35em" });
        ref.chip.append(el("rect", { class: "bf-chip-box", x: 0.75, y: 0.75, width: CHIP - 1.5, height: CHIP - 1.5, rx: 4 }), ref.chipText);
      }
      [ref.label, ref.sub, ref.group, ...ref.aboves, ref.chip, ref.value, ref.note].forEach((part) => { if (part) group.append(part); }); svg.append(group);
      /* the row target bleeds 8px past the text, so the wash and the focus ring have air around it */
      ref.hit = el("rect", { class: "bf-hit", x: -8, y: row.top + 1, width: view.width + 16, height: row.h - 2, rx: 8, tabindex: index === 0 ? "0" : "-1", role: "img", "aria-label": row.aria });
      ref.title = el("title"); ref.title.textContent = safe(row.aria); ref.hit.append(ref.title);
      wireRow(st, ref, index); hits.append(ref.hit); refs.rows.push(ref);
    });
    refs.tip = tipNode(); hits.append(refs.tip.group);
    hits.addEventListener("keydown", (event) => keyboard(st, event));
    hits.addEventListener("focusout", () => { if (st.pending) flush(st); });
    hits.addEventListener("pointerleave", () => { if (st.pending) flush(st); });
    st.svg = svg; st.hits = hits; st.refs = refs; st.tipRow = -1;
    const table = html("table", "bf-table"); st.table = table; syncTable(st, view);
    const twin = html("div", "sr-only"); twin.append(table);  // a table ignores the 1px clip of .sr-only, so the clip sits on its wrapper
    st.host.replaceChildren(svg, hits, twin);
    if (view.grow && !st.entered) { st.entered = true; svg.classList.add("bf-grow"); afterEntrance(() => svg.classList.remove("bf-grow")); }
  }

  function patch(st, view) {
    const { refs, svg } = st; setAttr(svg, "aria-label", view.description);
    view.rows.forEach((row, index) => {
      const ref = refs.rows[index]; ref.row = row;
      if (ref.label) setText(ref.label, row.label); if (ref.sub) setText(ref.sub, row.sub);
      row.segs.forEach((seg, k) => { setAttr(ref.bars[k], "d", seg.d); if (seg.above && ref.aboves[k]) { setText(ref.aboves[k], seg.above.text); setAttr(ref.aboves[k], "transform", move(seg.above.x, seg.above.y)); } });
      if (ref.value && row.value) { setText(ref.value, row.value.text); setAttr(ref.value, "transform", move(row.value.x, row.value.y)); }
      if (ref.note && row.note) { setText(ref.note, row.note.text); setAttr(ref.note, "transform", move(row.note.x, row.note.y)); }
      if (ref.chip && row.chip) { setText(ref.chipText, row.chip.grade); setAttr(ref.chip, "class", chipClass(row)); setAttr(ref.chip, "transform", move(row.chip.x, row.chip.y)); }
      setAttr(ref.hit, "aria-label", row.aria); setText(ref.title, row.aria);
    });
    syncTable(st, view);
    if (st.tipRow >= 0) showTip(st, st.tipRow);  // a tooltip that is open follows its row's new numbers
  }

  /* The hidden table: every number the chart shows, updated in place. */
  function syncTable(st, view) {
    const table = st.table; const spec = view.table; const body = table.children[2];
    const sameShape = body && table.children[1].children[0].children.length === spec.head.length && body.children.length === spec.rows.length && spec.rows.every((cells, i) => body.children[i].children.length === cells.length);
    if (sameShape) {
      setText(table.children[0], spec.caption);
      spec.head.forEach((text, i) => setText(table.children[1].children[0].children[i], text));
      spec.rows.forEach((cells, i) => cells.forEach((text, k) => setText(body.children[i].children[k], text)));
      return;
    }
    const cell = (tag, text, scope) => { const node = html(tag); node.textContent = safe(text); if (scope) node.setAttribute("scope", scope); return node; };
    const caption = html("caption"); caption.textContent = safe(spec.caption);
    const head = html("thead"); const headRow = html("tr"); spec.head.forEach((text) => headRow.append(cell("th", text, "col"))); head.append(headRow);
    const tbody = html("tbody"); spec.rows.forEach((cells) => { const tr = html("tr"); cells.forEach((text, i) => tr.append(i ? cell("td", text) : cell("th", text, "row"))); tbody.append(tr); });
    table.replaceChildren(caption, head, tbody);
  }

  /* ---- the tooltip: native SVG, positioned with the transform attribute, shown on hover, focus and tap ---- */
  function tipNode() {
    const group = el("g", { class: "bf-tip", transform: move(0, 0), "aria-hidden": "true" });
    const background = el("rect", { class: "bf-tip-bg", x: 0, y: 0, width: 10, height: 10, rx: 8 });
    const head = label("bf-tip-head", "", { x: 12, y: 21, dy: "0.35em" });
    group.append(background, head); return { group, background, head, lines: [] };
  }
  function showTip(st, index) {
    const ref = st.refs && st.refs.rows[index]; if (!ref) return; const tip = ref.row.tip; const node = st.refs.tip;
    if (!tip.head && !tip.lines.length) { hideTip(st); return; }
    if (st.tipRow !== index) { hideTip(st); }
    while (node.lines.length < tip.lines.length) { const line = label("bf-tip-line", "", { x: 12, dy: "0.35em" }); node.lines.push(line); node.group.append(line); }
    setText(node.head, tip.head);
    node.lines.forEach((line, k) => { setText(line, tip.lines[k] || ""); setAttr(line, "y", 42 + k * 18); });
    const m = st.measure; const w = Math.max(60, m(tip.head, TEXT.tipHead), ...tip.lines.map((line) => m(line, TEXT.tip))) + 24;
    const h = tip.lines.length ? 33 + tip.lines.length * 18 + 8 : 42; const width = st.frameWidth || w;
    setAttr(node.background, "width", w); setAttr(node.background, "height", h);
    const x = Math.round(Math.min(Math.max(ref.row.anchor - w / 2, 0), Math.max(0, width - w)));
    const count = st.refs.rows.length; const below = index < count / 2; const y = Math.round(below ? ref.row.top + ref.row.h - 6 : ref.row.top - h + 14);
    setAttr(node.group, "transform", move(x, y)); node.group.classList.add("is-on");
    if (ref.titled) { ref.hit.removeChild(ref.title); ref.titled = false; }  // the native tooltip would stack on top of this one
    st.tipRow = index;
  }
  function hideTip(st) {
    if (!st.refs) return;
    st.refs.tip.group.classList.remove("is-on");
    const ref = st.refs.rows[st.tipRow]; if (ref && !ref.titled) { ref.hit.append(ref.title); ref.titled = true; }
    st.tipRow = -1;
  }
  function wireRow(st, ref, index) {
    const touch = (event) => event && event.pointerType === "touch";
    ref.hit.addEventListener("pointerenter", (event) => { if (!touch(event)) showTip(st, index); });
    ref.hit.addEventListener("pointerleave", (event) => { if (!touch(event) && st.tipRow === index) hideTip(st); if (st.pending) flush(st); });
    ref.hit.addEventListener("click", () => showTip(st, index));
    ref.hit.addEventListener("focus", () => { st.refs.rows.forEach((other, k) => setAttr(other.hit, "tabindex", k === index ? "0" : "-1")); showTip(st, index); });
    ref.hit.addEventListener("blur", () => { if (st.tipRow === index) hideTip(st); });
  }
  function keyboard(st, event) {
    const key = event && event.key; if (!key) return;
    if (key === "Escape") { hideTip(st); return; }
    const rows = st.refs.rows; const at = rows.findIndex((ref) => ref.hit === event.target); if (at < 0) return;
    const next = key === "ArrowDown" || key === "ArrowRight" ? at + 1 : key === "ArrowUp" || key === "ArrowLeft" ? at - 1 : key === "Home" ? 0 : key === "End" ? rows.length - 1 : null;
    if (next === null) return;
    if (typeof event.preventDefault === "function") event.preventDefault();
    const target = rows[Math.min(rows.length - 1, Math.max(0, next))]; if (target && typeof target.hit.focus === "function") target.hit.focus();
  }

  /* ---- public ---- */
  function bars(host, spec) {
    if (!host) return null;
    try { const st = stateFor(host); st.spec = spec || {}; return draw(st); } catch (error) { report(error); const st = states.get(host); return st ? st.svg : null; }
  }
  function release(host) {
    const st = states.get(host); if (!st) return;
    try { if (st.ro) st.ro.disconnect(); } catch (_) { /* already gone */ }
    registry.delete(st); states.delete(host);
  }

  /* A trend for a figure tile: at most 12 means, a faint line whose last stretch and end dot carry the accent, and a scale that
     keeps noise small (the vertical range is never narrower than 6% of the mean). */
  function sparkline(values, { width = 120, height = 32 } = {}) {
    const series = (Array.isArray(values) ? values : []).filter(finite);
    const chart = el("svg", { viewBox: "0 0 " + width + " " + height, width, height, class: "bf-spark chart-inline", "aria-hidden": "true", focusable: "false" });
    if (series.length < 2) return chart;
    const count = Math.min(12, series.length); const means = [];
    for (let i = 0; i < count; i++) { const from = Math.floor((i * series.length) / count); const to = Math.max(from + 1, Math.floor(((i + 1) * series.length) / count)); const slice = series.slice(from, to); means.push(slice.reduce((a, b) => a + b, 0) / slice.length); }
    const low = Math.min(...means); const high = Math.max(...means); const mean = means.reduce((a, b) => a + b, 0) / means.length;
    const half = Math.max((high - low) / 2, Math.abs(mean) * 0.06, 1e-9); const mid = (high + low) / 2;
    const x = (i) => 3 + (i * (width - 12)) / (count - 1); const y = (v) => 6 + (1 - (v - (mid - half)) / (2 * half)) * (height - 12);
    const point = (i) => r2(x(i)) + " " + r2(y(means[i]));
    chart.append(el("path", { class: "bf-spark-line", d: means.map((_, i) => (i ? "L" : "M") + point(i)).join("") }),
      el("path", { class: "bf-spark-last", d: "M" + point(count - 2) + "L" + point(count - 1) }),
      el("circle", { class: "bf-spark-ring", cx: r2(x(count - 1)), cy: r2(y(means[count - 1])), r: 6 }), el("circle", { class: "bf-spark-dot", cx: r2(x(count - 1)), cy: r2(y(means[count - 1])), r: 4 }));
    return chart;
  }

  window.LandingCharts = Object.freeze({ bars, release, sparkline, money, printed, afterEntrance, flushEntrances });
})();
