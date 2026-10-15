/* Pricing demonstration, part 3 of 5: the charts. Plain SVG built from data, drawn at the width the slot is shown at.
   Colour arrives only through classes (c-main, c-ref, c-s1..c-s3, pd-hm-0..5), so both themes and the strict CSP apply as they are.
   Every chart prints its values or labels its lines, answers hover and keyboard focus with a tooltip, and has a table twin (table()). */
(() => {
  "use strict";
  const P = window.PricingDemo;
  const { svg, svgText, h, group } = P;

  const r2 = (value) => Math.round(value * 100) / 100;
  const finite = (value) => typeof value === "number" && Number.isFinite(value);
  const linear = (d0, d1, r0, r1) => { const span = d1 - d0 || 1; return (value) => r0 + ((value - d0) / span) * (r1 - r0); };
  const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
  const widthOf = (slot, fallback = 640) => { const width = slot && slot.clientWidth; return finite(width) && width > 0 ? Math.floor(width) : fallback; };

  /* Round tick values that cover [low, high]. Both ends are ticks, so an axis never stops between two gridlines. */
  function niceTicks(low, high, count = 4) {
    if (!(high > low)) return [low];
    const raw = (high - low) / count; const magnitude = 10 ** Math.floor(Math.log10(raw));
    const step = [1, 2, 2.5, 5, 10].map((unit) => unit * magnitude).find((candidate) => candidate >= raw);
    const first = Math.floor(low / step + 1e-9); const last = Math.ceil(high / step - 1e-9); const out = [];
    for (let index = first; index <= last; index++) out.push(Number((index * step).toPrecision(12)));
    return out;
  }
  const decimalsFor = (step) => { for (let places = 0; places < 5; places++) if (Math.abs(step * 10 ** places - Math.round(step * 10 ** places)) < 1e-9) return places; return 4; };

  /* A horizontal bar: square at the baseline, 4px radius at the data end. */
  function barPath(x, y, width, height, radius = 4) {
    const w = Math.max(width, 0); const r = Math.max(0, Math.min(radius, w, height / 2));
    if (r === 0) return "M" + r2(x) + " " + r2(y) + "h" + r2(w) + "v" + r2(height) + "h" + r2(-w) + "z";
    return "M" + r2(x) + " " + r2(y) + "h" + r2(w - r) + "a" + r + " " + r + " 0 0 1 " + r + " " + r + "v" + r2(height - 2 * r) + "a" + r + " " + r + " 0 0 1 " + (-r) + " " + r + "h" + r2(-(w - r)) + "z";
  }

  function root(width, height, description, className) {
    return svg("svg", { viewBox: "0 0 " + width + " " + height, width, height, class: "pd-chart " + className, role: "group", "aria-label": description, focusable: "false" });
  }
  const label = (content, x, y, className, anchor = "start", dy = "0.32em") => svgText(content, { x: r2(x), y: r2(y), class: className, "text-anchor": anchor, dy });

  /* One tooltip per chart, drawn inside the SVG so it needs no coordinates from the page. Text widths come from the browser when it can
     measure them and from a per-character estimate when it cannot. Create it after the marks so it paints on top.
     spec: { title, head, rows: [{ name, value, key }], notes: [] } */
  function tooltip(chart, width, height) {
    const box = svg("g", { class: "pd-tip", "aria-hidden": "true" });
    chart.append(box);
    const measure = (node, fallback) => { try { const w = typeof node.getBBox === "function" ? node.getBBox().width : 0; return w > 0 ? w : fallback; } catch (error) { return fallback; } };
    function show(ax, ay, spec) {
      box.replaceChildren(); box.classList.add("is-on");
      const frame = svg("rect", { x: 0, y: 0, rx: 6, class: "pd-tip-box" }); box.append(frame);
      const pad = 10; const rowH = 17; const rows = spec.rows || []; const notes = spec.notes || [];
      let y = pad + 9; const singles = [];
      const single = (text, className, estimate, dy) => { const node = label(text, pad, y + (dy || 0), className, "start", "0"); box.append(node); singles.push({ node, fallback: text.length * estimate }); };
      if (spec.title) { single(spec.title, "pd-tip-title", 6.2); y += rowH; }
      if (spec.head) { single(spec.head, "pd-tip-head", 7.6, 1); y += rowH + 2; }
      const pairs = rows.map((row) => {
        const indent = row.key ? 18 : 0;
        if (row.key) box.append(svg("line", { x1: pad, x2: pad + 12, y1: y - 4, y2: y - 4, class: "pd-tip-key " + row.key }));
        const name = label(row.name, pad + indent, y, "pd-tip-name", "start", "0"); const value = label(row.value, 0, y, "pd-tip-value", "end", "0");
        box.append(name, value); y += rowH; return { name, value, indent, nameText: row.name, valueText: row.value };
      });
      notes.forEach((note) => { single(note, "pd-tip-note", 5.9); y += rowH - 2; });
      let inner = Math.max(0, ...singles.map((item) => measure(item.node, item.fallback)));
      pairs.forEach((pair) => { inner = Math.max(inner, pair.indent + measure(pair.name, pair.nameText.length * 6.1) + 18 + measure(pair.value, pair.valueText.length * 6.8)); });
      const boxWidth = Math.min(width - 8, Math.ceil(inner + pad * 2)); const boxHeight = y + pad - 12;
      pairs.forEach((pair) => pair.value.setAttribute("x", String(r2(boxWidth - pad))));
      frame.setAttribute("width", String(boxWidth)); frame.setAttribute("height", String(r2(boxHeight)));
      const left = ax + 14 + boxWidth > width - 4 ? ax - 14 - boxWidth : ax + 14;
      box.setAttribute("transform", "translate(" + r2(clamp(left, 4, Math.max(4, width - boxWidth - 4))) + " " + r2(clamp(ay - boxHeight / 2, 4, Math.max(4, height - boxHeight - 4))) + ")");
    }
    function hide() { box.classList.remove("is-on"); box.replaceChildren(); }
    return { show, hide };
  }

  /* Horizontal bars on one zero-based axis. rows: [{ label, note, value, text, className, tip }].
     A wide slot puts each name left of its bar; a narrow one puts it above, so nothing is squeezed or clipped. */
  function barChart({ rows, width, axisTitle, description, animate = false }) {
    const narrow = width < 520; const valueRoom = narrow ? 72 : 80;
    const labelW = narrow ? 0 : clamp(Math.round(width * 0.36), 150, 236); const rowH = narrow ? 62 : 46; const barH = narrow ? 14 : 16;
    const top = 8; const axisH = 40; const height = top + rows.length * rowH + axisH;
    const left = labelW; const right = width - valueRoom;
    const high = Math.max(0, ...rows.map((row) => row.value).filter(finite));
    const ticks = niceTicks(0, high > 0 ? high : 1, narrow ? 4 : 5); const axisTop = ticks[ticks.length - 1];
    const x = linear(0, axisTop, left, right); const step = ticks.length > 1 ? ticks[1] - ticks[0] : 1; const places = step >= 1 ? decimalsFor(step) : Math.max(2, decimalsFor(step));
    const chart = root(width, height, description, "pd-bars" + (animate ? " is-entering" : ""));
    const body = height - axisH + 6; let tip = null;
    ticks.forEach((tick) => {
      chart.append(svg("line", { x1: r2(x(tick)), x2: r2(x(tick)), y1: top - 2, y2: body, class: tick === 0 ? "pd-axis" : "pd-grid" }));
      chart.append(label("$" + group(tick, places, places), x(tick), body + 15, "pd-tick", "middle", "0"));
    });
    if (axisTitle) chart.append(label(axisTitle, (left + right) / 2, height - 5, "pd-axis-title", "middle", "0"));
    rows.forEach((row, index) => {
      const y = top + index * rowH; const mid = narrow ? y + 42 : y + rowH / 2;
      const g = svg("g", { class: "pd-bar-group r" + Math.min(index, 9) });
      if (index) g.append(svg("line", { x1: 0, x2: width, y1: y, y2: y, class: "pd-rule" }));
      if (narrow) { g.append(label(row.label, 0, y + 16, "pd-row-label", "start", "0")); if (row.note) g.append(label(row.note, 0, y + 31, "pd-row-note", "start", "0")); }
      else { g.append(label(row.label, 0, mid - (row.note ? 7 : 0), "pd-row-label")); if (row.note) g.append(label(row.note, 0, mid + 9, "pd-row-note")); }
      const known = finite(row.value); const end = known ? x(row.value) : left;
      if (known) g.append(svg("path", { d: barPath(left, mid - barH / 2, Math.max(2, end - left), barH, 4), class: "pd-bar " + row.className }));
      g.append(label(row.text, end + 8, mid, "pd-value" + (known ? "" : " is-empty")));
      const hit = svg("rect", { x: 0, y: r2(y), width, height: rowH, class: "pd-hit", tabindex: "0", role: "img", "aria-label": row.label + ": " + row.text + (row.note ? ". " + row.note : "") });
      const on = () => { chart.classList.add("has-active"); g.classList.add("is-active"); tip.show(end + 8 + row.text.length * 6.6, mid, row.tip); };
      const off = () => { chart.classList.remove("has-active"); g.classList.remove("is-active"); tip.hide(); };
      ["pointerenter", "focus"].forEach((name) => hit.addEventListener(name, on)); ["pointerleave", "blur"].forEach((name) => hit.addEventListener(name, off));
      g.append(hit); chart.append(g);
    });
    tip = tooltip(chart, width, height);
    return chart;
  }

  /* Cut values into up to `parts` bins of equal count. Equal counts keep a skewed grid readable; the legend names every edge. */
  function quantileBins(values, parts = 6) {
    const sorted = values.filter(finite).slice().sort((a, b) => a - b);
    if (!sorted.length) return { edges: [], bin: () => 0, count: 0 };
    const edges = [];
    for (let i = 0; i <= parts; i++) { const value = sorted[Math.round((i * (sorted.length - 1)) / parts)]; if (!edges.length || value > edges[edges.length - 1]) edges.push(value); }
    if (edges.length < 2) edges.push(edges[0]);
    const count = edges.length - 1;
    const bin = (value) => { let found = 0; for (let i = 0; i < count; i++) if (value >= edges[i]) found = i; return found; };
    return { edges, bin, count };
  }
  const rampClass = (index, count) => "pd-hm-" + (count <= 1 ? 5 : Math.round((index * 5) / (count - 1)));

  /* A grid of cells shaded by value. cell(col, row) -> { value, text, flag, aria, tip } or null. Rows run top to bottom. The whole grid is one
     tab stop; arrow keys, Home and End move between cells, and the tooltip follows focus as it follows the pointer. */
  function heatmap({ cols, rows, cell, width, bins, colTitle, rowTitle, description, animate = false }) {
    const left = 40; const topPad = 22; const cellH = width < 460 ? 28 : 32; const cellW = (width - left - 2) / cols.length;
    const height = topPad + rows.length * cellH + 40;
    const chart = root(width, height, description, "pd-heat" + (animate ? " is-entering" : ""));
    chart.append(label(rowTitle, 0, 8, "pd-axis-title", "start", "0"));
    const grid = svg("g", { role: "grid", "aria-label": description });
    const cells = []; let current = 0; let tip = null;
    rows.forEach((row, r) => {
      chart.append(label(row.label, left - 8, topPad + r * cellH + cellH / 2, "pd-tick", "end"));
      const line = svg("g", { role: "row" });
      cols.forEach((col, c) => {
        const data = cell(col, row);
        if (!data || !finite(data.value)) return;
        const x = left + c * cellW; const y = topPad + r * cellH; const ramp = rampClass(bins.bin(data.value), bins.count); const position = cells.length;
        const node = svg("g", { class: "pd-cell c" + Math.min(c, 11), role: "gridcell", tabindex: position === 0 ? "0" : "-1", "aria-label": data.aria });
        node.append(svg("rect", { x: r2(x + 1), y: r2(y + 1), width: r2(Math.max(1, cellW - 2)), height: cellH - 2, rx: 3, class: "pd-hm " + ramp }));
        if (cellW >= 27) node.append(label(data.text, x + cellW / 2, y + cellH / 2 + 2, "pd-hm-text " + ramp, "middle"));
        if (data.flag) node.append(svg("circle", { cx: r2(x + cellW - 6), cy: r2(y + 6), r: 2.2, class: "pd-hm-flag " + ramp }));
        cells.push(node);
        const on = () => { current = position; cells.forEach((item, k) => item.setAttribute("tabindex", k === position ? "0" : "-1")); node.classList.add("is-active"); chart.classList.add("has-active"); tip.show(x + cellW / 2, y + cellH / 2, data.tip); };
        const off = () => { node.classList.remove("is-active"); chart.classList.remove("has-active"); tip.hide(); };
        ["pointerenter", "focus"].forEach((name) => node.addEventListener(name, on)); ["pointerleave", "blur"].forEach((name) => node.addEventListener(name, off));
        node.addEventListener("keydown", (event) => {
          const move = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: cols.length, ArrowUp: -cols.length, Home: -current, End: cells.length - 1 - current }[event.key];
          if (move === undefined) return;
          event.preventDefault(); const next = clamp(current + move, 0, cells.length - 1);
          if (next !== current && typeof cells[next].focus === "function") cells[next].focus();
        });
        line.append(node);
      });
      grid.append(line);
    });
    cols.forEach((col, c) => chart.append(label(col.label, left + c * cellW + cellW / 2, topPad + rows.length * cellH + 14, "pd-tick", "middle", "0")));
    chart.append(label(colTitle, left + (width - left) / 2, height - 6, "pd-axis-title", "middle", "0"));
    chart.append(grid);
    tip = tooltip(chart, width, height);
    return chart;
  }

  /* Lines over an ordered x axis. series: [{ name, short, className, values }] with one value per point (null for a gap).
     xs: numeric x per point. xTicks: [{ value, label }]. reference: { value, label } draws a rule. Hover and the arrow keys read every
     series at one x. End labels sit beside the lines only while the slot is wide enough; the legend and tooltip carry the rest. */
  function lineChart({ xs, xTicks, series, width, height = 260, format, exact, title, reference, description, animate = false, axisTitle }) {
    const direct = width >= 560 && series.length <= 3;
    const margin = { left: 54, right: direct ? 124 : 16, top: 14, bottom: axisTitle ? 46 : 28 };
    const values = series.flatMap((s) => s.values).filter(finite).concat(reference && finite(reference.value) ? [reference.value] : []);
    const chart = root(width, height, description, "pd-lines" + (animate ? " is-entering" : ""));
    if (xs.length < 2 || !values.length) { chart.append(label("No path for these terms", width / 2, height / 2, "pd-empty", "middle")); return chart; }
    const ticks = niceTicks(Math.min(0, ...values), Math.max(...values, 0) || 1, 4);
    const x = linear(xs[0], xs[xs.length - 1], margin.left, width - margin.right); const y = linear(ticks[0], ticks[ticks.length - 1], height - margin.bottom, margin.top);
    ticks.forEach((tick) => {
      chart.append(svg("line", { x1: margin.left, x2: width - margin.right, y1: r2(y(tick)), y2: r2(y(tick)), class: tick === 0 ? "pd-axis" : "pd-grid" }));
      chart.append(label(format(tick), margin.left - 8, y(tick), "pd-tick", "end"));
    });
    xTicks.forEach((tick) => chart.append(label(tick.label, x(tick.value), height - margin.bottom + 15, "pd-tick", "middle", "0")));
    if (axisTitle) chart.append(label(axisTitle, (margin.left + width - margin.right) / 2, height - 5, "pd-axis-title", "middle", "0"));
    if (reference && finite(reference.value)) {
      chart.append(svg("line", { x1: margin.left, x2: width - margin.right, y1: r2(y(reference.value)), y2: r2(y(reference.value)), class: "pd-ref-line" }));
      chart.append(label(reference.label, margin.left + 6, y(reference.value) - 7, "pd-ref-label", "start", "0"));
    }
    series.forEach((s) => {
      const d = s.values.map((v, i) => (finite(v) ? (i && finite(s.values[i - 1]) ? "L" : "M") + r2(x(xs[i])) + " " + r2(y(v)) : "")).join("");
      if (d) chart.append(svg("path", { d, pathLength: 1, class: "pd-line " + s.className }));
    });
    const ends = [];
    series.forEach((s) => {
      let last = -1; s.values.forEach((v, i) => { if (finite(v)) last = i; });
      if (last < 0) return;
      chart.append(svg("circle", { cx: r2(x(xs[last])), cy: r2(y(s.values[last])), r: 4, class: "pd-dot " + s.className }));
      ends.push({ s, at: y(s.values[last]), y: y(s.values[last]), px: x(xs[last]), value: s.values[last] });
    });
    if (direct) {
      const placed = ends.slice().sort((a, b) => a.y - b.y);
      for (let i = 1; i < placed.length; i++) if (placed[i].y - placed[i - 1].y < 32) placed[i].y = placed[i - 1].y + 32;
      placed.forEach((end) => {
        if (Math.abs(end.y - end.at) > 4) chart.append(svg("line", { x1: r2(end.px + 5), x2: r2(width - margin.right + 6), y1: r2(end.at), y2: r2(end.y), class: "pd-leader" }));
        chart.append(label(end.s.short || end.s.name, width - margin.right + 10, end.y - 7, "pd-direct", "start", "0.32em"));
        chart.append(label(exact(end.value), width - margin.right + 10, end.y + 8, "pd-direct-value", "start", "0.32em"));
      });
    }
    const cross = svg("line", { y1: margin.top, y2: height - margin.bottom, class: "pd-cross" }); chart.append(cross);
    const marks = series.map((s) => { const dot = svg("circle", { r: 4, class: "pd-dot pd-hover-dot " + s.className }); chart.append(dot); return dot; });
    const plot = svg("g", { class: "pd-plot", tabindex: "0", role: "group", "aria-label": "Chart readout. Use the left and right arrow keys to read each point." });
    let at = -1; let tip = null;
    function select(index) {
      at = clamp(index, 0, xs.length - 1); const px = x(xs[at]);
      cross.setAttribute("x1", String(r2(px))); cross.setAttribute("x2", String(r2(px))); cross.classList.add("is-on");
      marks.forEach((dot, k) => { const v = series[k].values[at]; if (finite(v)) { dot.setAttribute("cx", String(r2(px))); dot.setAttribute("cy", String(r2(y(v)))); dot.classList.add("is-on"); } else dot.classList.remove("is-on"); });
      const spec = { title: title(at), rows: series.filter((s) => finite(s.values[at])).map((s) => ({ name: s.name, value: exact(s.values[at]), key: s.className })) };
      if (reference && finite(reference.value)) spec.notes = [reference.label];
      tip.show(px, margin.top + 44, spec);
      plot.setAttribute("aria-label", spec.title + ": " + spec.rows.map((row) => row.name + " " + row.value).join(", "));
    }
    function clear() { at = -1; cross.classList.remove("is-on"); marks.forEach((dot) => dot.classList.remove("is-on")); tip.hide(); }
    xs.forEach((value, i) => {
      const from = i === 0 ? margin.left : (x(xs[i - 1]) + x(value)) / 2; const to = i === xs.length - 1 ? width - margin.right : (x(value) + x(xs[i + 1])) / 2;
      const slot = svg("rect", { x: r2(from), y: margin.top, width: r2(Math.max(1, to - from)), height: height - margin.bottom - margin.top, class: "pd-band" });
      ["pointerenter", "pointermove"].forEach((name) => slot.addEventListener(name, () => select(i))); plot.append(slot);
    });
    plot.addEventListener("pointerleave", clear); plot.addEventListener("blur", clear);
    plot.addEventListener("focus", () => select(at < 0 ? xs.length - 1 : at));
    plot.addEventListener("keydown", (event) => {
      const next = { ArrowRight: at + 1, ArrowLeft: at - 1, Home: 0, End: xs.length - 1 }[event.key];
      if (next === undefined) return;
      event.preventDefault(); select(at < 0 ? xs.length - 1 : next);
    });
    chart.append(plot);
    tip = tooltip(chart, width, height);
    return chart;
  }

  /* Legends are HTML beside the chart. kind: "bar" (a square), "line" (a short rule) or "flag" (a dot). className picks the colour. */
  function legend(items) {
    const list = h("ul", "pd-legend");
    items.forEach((item) => {
      const entry = h("li"); const mark = h("span", "pd-key pd-key-" + (item.kind || "bar") + " " + item.className); mark.setAttribute("aria-hidden", "true");
      entry.append(mark, document.createTextNode(item.label)); list.append(entry);
    });
    return list;
  }

  /* The table twin of a chart: the same numbers, closed until asked for, in a region that scrolls inside itself. */
  function table({ summary, caption, columns, rows }) {
    const details = h("details", "pd-data"); details.append(h("summary", "", summary));
    const wrap = h("div", "pd-table-wrap"); const grid = h("table", "pd-table");
    grid.append(h("caption", "sr-only", caption));
    const head = h("thead"); const headRow = h("tr");
    columns.forEach((column) => { const th = h("th", column.numeric ? "is-num" : "", column.label); th.setAttribute("scope", "col"); headRow.append(th); });
    head.append(headRow); grid.append(head);
    const body = h("tbody");
    rows.forEach((row) => {
      const tr = h("tr");
      row.forEach((cell, index) => {
        const node = h(index === 0 ? "th" : "td", columns[index].numeric ? "is-num" : "", cell);
        if (index === 0) node.setAttribute("scope", "row");
        tr.append(node);
      });
      body.append(tr);
    });
    grid.append(body); wrap.append(grid); details.append(wrap);
    return details;
  }

  P.charts = Object.freeze({ niceTicks, decimalsFor, barPath, widthOf, quantileBins, rampClass, barChart, heatmap, lineChart, legend, table, finite, clamp });
})();
