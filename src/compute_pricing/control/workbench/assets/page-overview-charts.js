/* Overview chart primitives. Plain data in, an <svg> (or a small DOM block) out.
   They follow docs/interface-design.md and the dataviz marks: bars no thicker than 24px with a 4px rounded data end and a square
   baseline, 2px gaps between touching fills, 2px lines, end dots of at least 8px with a 2px surface ring, solid hairline grids,
   tabular numerals, one colour for a single series. Colour arrives only through CSS classes (--gc) and SVG attributes, so the strict
   CSP holds. Every chart is paired with a hidden data table (twin) so no value depends on hover or on colour. */
(() => {
  "use strict";
  const base = window.ComputeCharts; if (!base) return;
  const { svg } = base;
  const r2 = (value) => Math.round(value * 100) / 100;
  const finite = (value) => typeof value === "number" && Number.isFinite(value);
  const linear = (domain, range) => { const span = domain[1] - domain[0] || 1; return (value) => range[0] + ((value - domain[0]) / span) * (range[1] - range[0]); };

  function label(content, x, y, className, anchor = "start", dy = "0.34em") {
    const node = svg("text", { x: r2(x), y: r2(y), class: className, "text-anchor": anchor, dy }); node.textContent = content; return node;
  }
  function tip(node, content) { if (content) node.append(Object.assign(svg("title"), { textContent: content })); return node; }
  function root(width, height, description, className) {
    return svg("svg", { viewBox: "0 0 " + r2(width) + " " + r2(height), class: "chart ov-chart " + className, role: "img", "aria-label": description, focusable: "false" });
  }
  const el = (tag, className, ...children) => {
    const node = document.createElement(tag); if (className) node.className = className;
    children.flat(Infinity).forEach((child) => { if (child !== null && child !== undefined && child !== false) node.append(typeof child === "object" ? child : document.createTextNode(String(child))); });
    return node;
  };

  /* A bar with a rounded data end. `end` is the side that carries the data ("right", "left", "up", "down"); the baseline side stays square. */
  function barPath(x, y, w, h, radius, end = "right") {
    if (![x, y, w, h].every(finite) || w <= 0 || h <= 0) return "";
    const r = r2(Math.max(0, Math.min(radius, w / 2, h / 2))); const n = (v) => r2(v);
    if (end === "left") return "M" + n(x + w) + " " + n(y) + "H" + n(x + r) + "A" + r + " " + r + " 0 0 0 " + n(x) + " " + n(y + r) + "V" + n(y + h - r) + "A" + r + " " + r + " 0 0 0 " + n(x + r) + " " + n(y + h) + "H" + n(x + w) + "Z";
    if (end === "up") return "M" + n(x) + " " + n(y + h) + "V" + n(y + r) + "A" + r + " " + r + " 0 0 1 " + n(x + r) + " " + n(y) + "H" + n(x + w - r) + "A" + r + " " + r + " 0 0 1 " + n(x + w) + " " + n(y + r) + "V" + n(y + h) + "Z";
    if (end === "none") return "M" + n(x) + " " + n(y) + "H" + n(x + w) + "V" + n(y + h) + "H" + n(x) + "Z";
    return "M" + n(x) + " " + n(y) + "H" + n(x + w - r) + "A" + r + " " + r + " 0 0 1 " + n(x + w) + " " + n(y + r) + "V" + n(y + h - r) + "A" + r + " " + r + " 0 0 1 " + n(x + w - r) + " " + n(y + h) + "H" + n(x) + "Z";
  }
  /* rank: the mark's place in the first-draw stagger (class ov-r0..ov-r7); only drawn charts that are entering carry .ov-in. */
  const rankClass = (rank) => (Number.isInteger(rank) && rank > 0 ? " ov-r" + Math.min(rank, 8) : "");
  function bar(x, y, w, h, { className = "", end = "right", title = "", hollow = false, rank = 0 } = {}) {
    const d = barPath(x, y, w, h, 4, end); if (!d) return null;
    return tip(svg("path", { d, class: "ov-bar " + className + (hollow ? " ov-hollow" : "") + rankClass(rank) }), title);
  }
  /* The grade letter in a box, the same mark the tables use. An unrated seller gets a neutral box: U is never coloured as a grade. */
  function chip(cx, cy, grade, size = 15) {
    const letter = /^[A-D]$/.test(grade) ? grade : "U";
    const group = svg("g", { class: "ch-chip g-" + letter.toLowerCase() });
    group.append(svg("rect", { x: r2(cx - size / 2), y: r2(cy - size / 2), width: size, height: size, rx: 3.5, class: "ch-chip-box" }), label(letter, cx, cy, "ch-chip-text", "middle", "0.35em"));
    return tip(group, letter === "U" ? "Seller not rated" : "Seller grade " + letter);
  }
  const money = (value, places = 2) => "$" + Number(value).toFixed(places);

  /* ---- hidden data table: every chart's twin ---- */
  function twin(caption, head, rows) {
    const table = el("table", "ov-twin"); table.append(el("caption", "", caption));
    const row = el("tr"); head.forEach((name) => { const cell = el("th", "", name); cell.scope = "col"; row.append(cell); }); table.append(el("thead", "", row));
    const body = el("tbody"); rows.forEach((values) => { const line = el("tr"); values.forEach((value, i) => { const cell = el(i === 0 ? "th" : "td", "", value === null || value === undefined ? "" : String(value)); if (i === 0) cell.scope = "row"; line.append(cell); }); body.append(line); });
    table.append(body); return el("div", "sr-only ov-twin-box", table);  // a wrapper clips it: a table ignores the 1px box and would widen the page
  }
  function legend(items) {
    const list = el("ul", "ov-legend");
    items.forEach((item) => list.append(el("li", "", el("span", "ov-swatch " + item.className), item.label)));
    return list;
  }

  /* ---- Basis by model: two bars per row on one zero-based dollar axis, the premium printed at the right ---- */
  function pairedBars({ rows, width, description, enter = false, format = (v) => "$" + v, tickCount = 6, labelWidth = 96, trailWidth = 58, valueRoom = 84, trailTitle = "Basis", rowHeight = 58, barHeight = 10, barGap = 7 }) {
    const head = 28; const height = head + rows.length * rowHeight; const chart = root(width, height, description, "ov-paired" + (enter ? " ov-in" : ""));
    const high = Math.max(0, ...rows.flatMap((row) => row.bars.map((b) => b.value)).filter(finite));
    const axis = base.zeroAxis(high || 1, tickCount); const right = width - trailWidth - valueRoom; const x = linear([0, axis.top], [labelWidth, right]);
    axis.ticks.forEach((value) => chart.append(svg("line", { x1: r2(x(value)), x2: r2(x(value)), y1: head - 10, y2: height, class: value === 0 ? "ov-axis" : "ov-grid" }), label(format(value), x(value), 6, "ov-tick", "middle")));
    if (trailTitle) chart.append(label(trailTitle, width, 6, "ov-tick", "end"));
    rows.forEach((row, index) => {
      const top = head + index * rowHeight; const cy = top + rowHeight / 2; const stack = row.bars.length * barHeight + (row.bars.length - 1) * barGap;
      if (index) chart.append(svg("line", { x1: 0, x2: width, y1: top, y2: top, class: "ov-rule" }));
      chart.append(label(row.label, 0, cy - 7, "ov-lab"), label(row.sub || "", 0, cy + 9, "ov-sub"));
      row.bars.forEach((item, position) => {
        const by = cy - stack / 2 + position * (barHeight + barGap); const mid = by + barHeight / 2;
        if (!finite(item.value)) { if (item.absent) chart.append(label(item.absent, x(0) + 8, mid, "ov-note")); return; }
        const w = Math.max(3, x(item.value) - x(0)); const shape = bar(x(0), by, w, barHeight, { className: item.className, title: item.title, rank: index + 1 }); if (shape) chart.append(shape);
        const gx = x(0) + w + 10; if (item.grade) chart.append(chip(gx + 7.5, mid, item.grade, 15));
        chart.append(label(item.text, item.grade ? gx + 21 : gx, mid, "ov-val"));
      });
      chart.append(label(row.trail || "", width, cy, "ov-trail", "end"));
    });
    return chart;
  }

  /* ---- Single-series horizontal bars with a value at the end of each. Narrow widths put the label above its bar. ---- */
  function hbars({ rows, width, description, enter = false, labelWidth = 170, valueWidth = 76, barHeight = 10, rowHeight = 34, className = "ov-one", stack = width < 420 }) {
    const stacked = stack; const height = rows.length * (stacked ? 46 : rowHeight);
    const chart = root(width, Math.max(height, 4), description, "ov-hbars" + (enter ? " ov-in" : ""));
    const left = stacked ? 0 : labelWidth; const peak = Math.max(1, ...rows.map((row) => row.value).filter(finite)); const x = linear([0, peak], [left, width - valueWidth]);
    chart.append(svg("line", { x1: left, x2: left, y1: 0, y2: height, class: "ov-axis" }));
    rows.forEach((row, index) => {
      const slot = stacked ? 46 : rowHeight; const top = index * slot; const cy = stacked ? top + 31 : top + slot / 2;
      chart.append(label(row.label, 0, stacked ? top + 11 : cy, "ov-lab ov-lab-light"));
      const w = finite(row.value) && row.value > 0 ? Math.max(3, x(row.value) - left) : 0;
      if (w) { const shape = bar(left, cy - barHeight / 2, w, barHeight, { className: (row.className || className), hollow: row.hollow, title: row.title, rank: index + 1 }); if (shape) chart.append(shape); }
      chart.append(label(row.text, left + w + (w ? 10 : 8), cy, "ov-val"));
    });
    return chart;
  }

  /* ---- Share bars, split by grade on an ordinal ramp: A is the strongest tone. Each row fills the width; the total is printed at the right ---- */
  function gradeStack({ rows, width, description, enter = false, labelWidth = 72, barHeight = 16, rowHeight = 38, gap = 2 }) {
    const trailWidth = Math.ceil(Math.max(0, ...rows.map((row) => String(row.trail || "").length)) * 7.2) + 14; const height = rows.length * rowHeight; const chart = root(width, Math.max(height, 4), description, "ov-stack" + (enter ? " ov-in" : ""));
    const x0 = labelWidth; const x1 = width - trailWidth; const span = x1 - x0;
    rows.forEach((row, index) => {
      const cy = index * rowHeight + rowHeight / 2; const total = row.parts.reduce((sum, part) => sum + (part.value > 0 ? part.value : 0), 0);
      chart.append(label(row.label, 0, cy, "ov-lab"));
      if (!(total > 0)) { chart.append(label(row.none || "None", x0, cy, "ov-note")); } else {
        const live = row.parts.filter((part) => part.value > 0); let cursor = 0;
        live.forEach((part, i) => {
          const from = x0 + (cursor / total) * span; cursor += part.value; const to = x0 + (cursor / total) * span; const last = i === live.length - 1;
          const w = to - from - (last ? 0 : gap); const shape = bar(from, cy - barHeight / 2, w, barHeight, { className: part.className, end: last ? "right" : "none", title: part.title, rank: index + 1 }); if (shape) chart.append(shape);
          const share = part.value / total; if (w >= 38 && share >= 0.1) chart.append(label(Math.round(share * 100) + "%", from + w / 2, cy, "ov-seg " + part.className, "middle"));
        });
      }
      chart.append(label(row.trail || "", width, cy, "ov-val", "end"));
    });
    return chart;
  }

  /* ---- A signed bar on a shared scale, drawn small enough to sit in a table cell. Zero sits where the data puts it. ---- */
  function signedBar({ value, low, high, width = 120, height = 14, title = "" }) {
    const chart = svg("svg", { viewBox: "0 0 " + width + " " + height, class: "ov-signed", width, height, role: "img", "aria-label": title, focusable: "false" });
    if (!finite(value)) return chart;
    const reach = (Math.max(0, high) + Math.max(0, -low)) || 1; const zero = r2((Math.max(0, -low) / reach) * (width - 2) + 1);
    const w = Math.max(2, (Math.abs(value) / reach) * (width - 2)); const positive = value >= 0;
    chart.append(svg("line", { x1: zero, x2: zero, y1: 0, y2: height, class: "ov-axis" }));
    const shape = bar(positive ? zero : zero - w, (height - 10) / 2, w, 10, { className: positive ? "ov-gain" : "ov-loss", end: positive ? "right" : "left", rank: 1 }); if (shape) chart.append(shape);
    return tip(chart, title);
  }

  /* ---- Price history: two lines over market time, the basis as the shaded band between them, scenario flags above ---- */
  function flagRows(markers, x, width) {
    const placed = []; const ends = [];
    markers.slice().sort((a, b) => a.index - b.index).forEach((marker) => {
      const at = x(marker.index); const words = String(marker.label || ""); const size = words.length * 6 + 12; const flip = at + size > width; const from = flip ? at - size : at; const to = flip ? at : at + size;
      let row = ends.findIndex((end) => from > end + 6); if (row < 0 && ends.length < 3) row = ends.length;
      const crowded = row < 0; if (crowded) row = ends.length - 1; else ends[row] = Math.max(ends[row] === undefined ? -Infinity : ends[row], to);
      placed.push({ marker, text: crowded ? "" : words, at, row, flip });
    });
    return { placed, rows: ends.length };
  }
  function historyChart({ times, series, gap, markers = [], width, height = 250, description, enter = false, format = (v) => "$" + v.toFixed(2), xLabel = () => "", onHover, hoverIndex = null, yTicks = 4, xTicks = 3, hoverText = () => "" }) {
    const points = times.length; const chart = root(width, height, description, "ov-history" + (enter ? " ov-in" : ""));
    const all = series.flatMap((line) => line.values).filter(finite); if (points < 2 || !all.length) return chart;
    const margin = { left: 50, right: 60, top: 12, bottom: 26 }; const x = linear([0, points - 1], [margin.left, width - margin.right]);
    const flags = flagRows(markers.filter((m) => m.index >= 0 && m.index <= points - 1), x, width); if (flags.rows) margin.top = 12 + flags.rows * 14;
    let low = Math.min(...all); let high = Math.max(...all); const pad = (high - low || Math.abs(high) * 0.02 || 1) * 0.12; low -= pad; high += pad; const y = linear([low, high], [height - margin.bottom, margin.top]);
    base.ticks(low, high, yTicks).forEach((value) => chart.append(svg("line", { x1: margin.left, x2: width - margin.right, y1: r2(y(value)), y2: r2(y(value)), class: "ov-grid" }), label(format(value), margin.left - 8, y(value), "ov-tick", "end")));
    chart.append(svg("line", { x1: margin.left, x2: width - margin.right, y1: height - margin.bottom, y2: height - margin.bottom, class: "ov-axis" }));
    const count = Math.max(2, Math.min(xTicks, points)); for (let k = 0; k < count; k++) { const index = Math.round((k * (points - 1)) / (count - 1)); chart.append(label(xLabel(index), x(index), height - 8, "ov-tick", k === 0 ? "start" : k === count - 1 ? "end" : "middle", "0")); }
    if (gap) {
      const upper = series.find((line) => line.key === gap[0]); const lower = series.find((line) => line.key === gap[1]);
      if (upper && lower) {
        const both = upper.values.map((value, index) => ({ index, a: value, b: lower.values[index] })).filter((p) => finite(p.a) && finite(p.b));
        if (both.length > 1) chart.append(svg("path", { d: both.map((p, i) => (i ? "L" : "M") + r2(x(p.index)) + " " + r2(y(p.a))).join("") + both.slice().reverse().map((p) => "L" + r2(x(p.index)) + " " + r2(y(p.b))).join("") + "Z", class: "ov-gap" }));
      }
    }
    flags.placed.forEach(({ marker, text, at, row, flip }) => {
      const top = 4 + row * 14; chart.append(tip(svg("line", { x1: r2(at), x2: r2(at), y1: top + 8, y2: height - margin.bottom, class: "ov-flag" }), marker.title));
      if (text) chart.append(label(text, at + (flip ? -5 : 5), top + 4, "ov-flag-label", flip ? "end" : "start"));
    });
    const ends = [];
    series.forEach((line) => {
      const data = line.values.map((value, index) => ({ value, index })).filter((p) => finite(p.value)); if (!data.length) return;
      chart.append(tip(svg("path", { d: data.map((p, i) => (i && data[i - 1].index === p.index - 1 ? "L" : "M") + r2(x(p.index)) + " " + r2(y(p.value))).join(""), class: "ov-line " + line.className, fill: "none" }), line.name));
      const last = data[data.length - 1]; ends.push({ y: y(last.value), text: format(last.value), line, cx: x(last.index), cy: y(last.value) });
    });
    ends.sort((a, b) => a.y - b.y); for (let i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < 14) ends[i].y = ends[i - 1].y + 14;
    ends.forEach((end) => chart.append(svg("circle", { cx: r2(end.cx), cy: r2(end.cy), r: 6, class: "ov-ring" }), svg("circle", { cx: r2(end.cx), cy: r2(end.cy), r: 4, class: "ov-dot " + end.line.className }), label(end.text, width - margin.right + 12, end.y, "ov-val")));
    /* Hover: a crosshair that snaps to the nearest reading, and the readout above the chart follows it. Pointer events only enhance;
       every reading is also in the data table. */
    const cross = svg("line", { x1: 0, x2: 0, y1: margin.top, y2: height - margin.bottom, class: "ov-cross" });
    const dots = series.map((line) => svg("circle", { cx: 0, cy: 0, r: 4, class: "ov-hdot ov-dot " + line.className }));
    chart.append(cross, ...dots);
    const show = (index) => {
      const on = Number.isInteger(index) && index >= 0 && index < points;
      cross.setAttribute("class", "ov-cross" + (on ? " on" : "")); if (on) { cross.setAttribute("x1", r2(x(index))); cross.setAttribute("x2", r2(x(index))); }
      series.forEach((line, i) => { const v = line.values[index]; const visible = on && finite(v); dots[i].setAttribute("class", "ov-hdot ov-dot " + line.className + (visible ? " on" : "")); if (visible) { dots[i].setAttribute("cx", r2(x(index))); dots[i].setAttribute("cy", r2(y(v))); } });
      if (onHover) onHover(on ? index : null);
    };
    const slot = (width - margin.left - margin.right) / (points - 1);
    for (let index = 0; index < points; index++) {
      const hit = svg("rect", { x: r2(x(index) - slot / 2), y: margin.top, width: r2(slot), height: height - margin.bottom - margin.top, class: "ov-hit" });
      hit.append(Object.assign(svg("title"), { textContent: hoverText(index) })); hit.addEventListener("pointerenter", () => show(index)); chart.append(hit);
    }
    chart.addEventListener("pointerleave", () => show(null));
    if (finite(hoverIndex)) show(hoverIndex);
    return chart;
  }

  /* ---- Where this model's quotes sit now. Stands in for the history chart until the book has two readings. ---- */
  function rangeStrip({ low, median, high, marks, width, description, format = (v) => "$" + v.toFixed(2) }) {
    const items = marks.filter((m) => finite(m.value)); const lo = Math.min(low, ...items.map((m) => m.value)); const hi = Math.max(high, ...items.map((m) => m.value));
    const height = 112; const chart = root(width, height, description, "ov-range");
    const left = 8; const right = width - 8; const pad = (hi - lo || 1) * 0.04; const x = linear([lo - pad, hi + pad], [left, right]); const railY = 66;
    chart.append(svg("path", { d: barPath(x(low), railY - 5, Math.max(4, x(high) - x(low)), 10, 4, "none"), class: "ov-rail" }));
    if (finite(median)) chart.append(svg("line", { x1: r2(x(median)), x2: r2(x(median)), y1: railY - 9, y2: railY + 9, class: "ov-axis" }));
    /* Axis row under the rail: lowest, median, highest quote. A label that would touch its neighbour is dropped (the table keeps it). */
    const axis = [{ value: low, text: format(low) + " lowest", anchor: "start" }, { value: median, text: format(median) + " median", anchor: "middle" }, { value: high, text: format(high) + " highest", anchor: "end" }].filter((a) => finite(a.value));
    let edge = -Infinity; axis.forEach((a) => {
      const w = a.text.length * 6.2; const at = x(a.value); const from = a.anchor === "start" ? at : a.anchor === "end" ? at - w : at - w / 2;
      if (from < edge + 10) return; edge = from + w; chart.append(label(a.text, at, railY + 30, "ov-tick", a.anchor));
    });
    /* Marks above the rail, each with a leader; labels share two rows and flip left when they would run off the edge. */
    const ends = []; items.slice().sort((a, b) => a.value - b.value).forEach((m) => {
      const at = x(m.value); const text = m.text; const w = text.length * 6.4 + 4; const flip = at + w > width - 4; const from = flip ? at - w : at; const to = flip ? at : at + w;
      let row = ends.findIndex((end) => from > end + 8); if (row < 0) row = ends.length < 2 ? ends.length : 1; ends[row] = Math.max(ends[row] === undefined ? -Infinity : ends[row], to);
      const ty = 10 + row * 18;
      chart.append(svg("line", { x1: r2(at), x2: r2(at), y1: ty + 7, y2: railY, class: "ov-leader" }), label(text, at + (flip ? -4 : 4), ty, "ov-val", flip ? "end" : "start"));
      chart.append(svg("circle", { cx: r2(at), cy: railY, r: 6, class: "ov-ring" }), tip(svg("circle", { cx: r2(at), cy: railY, r: 4, class: "ov-dot " + m.className }), m.title));
    });
    return chart;
  }

  window.OverviewCharts = Object.freeze({ pairedBars, hbars, gradeStack, signedBar, historyChart, rangeStrip, twin, legend, barPath, chip, el, label, money, finite, r2 });
})();
