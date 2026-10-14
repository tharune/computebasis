/* Small SVG chart set for the workbench. Charts are plain data in, an <svg> out.
   Colour comes only from CSS classes, so both themes and the strict CSP apply unchanged;
   every chart has a text alternative and each mark carries a <title> tooltip.
   Bars start at zero, labels sit on the marks, and callers draw at the width they are shown at. */
(() => {
  "use strict";
  const NS = "http://www.w3.org/2000/svg";
  function svg(tag, attributes = {}, ...children) {
    const node = document.createElementNS(NS, tag);
    Object.entries(attributes).forEach(([name, value]) => { if (value !== null && value !== undefined) node.setAttribute(name, String(value)); });
    children.flat().forEach((child) => { if (child) node.append(child); });
    return node;
  }
  const label = (content, x, y, className, anchor = "start", dy = "0.32em") => {
    const node = svg("text", { x: round(x), y: round(y), class: className, "text-anchor": anchor, dy });
    node.textContent = content; return node;
  };
  const tip = (node, content) => { if (content) node.append(Object.assign(svg("title"), { textContent: content })); return node; };
  const round = (value) => Math.round(value * 100) / 100;
  const finite = (value) => typeof value === "number" && Number.isFinite(value);
  const numeric = (value) => {
    if (typeof value !== "number" && !(typeof value === "string" && /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/.test(value))) return null;
    const parsed = Number(value); return finite(parsed) ? parsed : null;
  };
  const root = (width, height, description, className = "chart") =>
    svg("svg", { viewBox: "0 0 " + width + " " + height, class: className, role: "img", "aria-label": description, focusable: "false" });

  function linear(domain, range) {
    const [d0, d1] = domain; const [r0, r1] = range; const span = d1 - d0 || 1;
    return (value) => r0 + ((value - d0) / span) * (r1 - r0);
  }
  /* Round tick values that cover [low, high] with about `count` steps. */
  function ticks(low, high, count = 4) {
    if (!(high > low)) return [low];
    const raw = (high - low) / count; const magnitude = 10 ** Math.floor(Math.log10(raw));
    const step = [1, 2, 2.5, 5, 10].map((unit) => unit * magnitude).find((candidate) => candidate >= raw);
    const out = []; for (let value = Math.ceil(low / step) * step; value <= high + step * 1e-9; value += step) out.push(round(value * 1e6) / 1e6);
    return out;
  }
  /* An axis from zero up to a round tick at or above `high`, using the smallest round step that needs at most `count` intervals.
     Bars never touch the frame and the axis never reaches far past the longest bar. */
  function zeroAxis(high, count = 5) {
    const peak = high > 0 ? high : 1; const magnitude = 10 ** Math.floor(Math.log10(peak));
    const steps = [0.1, 0.2, 0.25, 0.5, 1, 2, 2.5, 5, 10].map((unit) => unit * magnitude);
    const step = steps.find((candidate) => Math.ceil(peak / candidate - 1e-9) <= count) || steps[steps.length - 1];
    const intervals = Math.max(1, Math.ceil(peak / step - 1e-9)); const out = [];
    for (let i = 0; i <= intervals; i++) out.push(Math.round(i * step * 1e6) / 1e6);
    return { top: out[out.length - 1], ticks: out };
  }
  /* Spread labels that would overlap vertically, preserving order. */
  function spread(items, gap) {
    const sorted = items.slice().sort((a, b) => a.y - b.y);
    for (let i = 1; i < sorted.length; i++) if (sorted[i].y - sorted[i - 1].y < gap) sorted[i].y = sorted[i - 1].y + gap;
    return sorted;
  }
  /* The grade letter in a box, the same mark the tables use. */
  function chip(cx, cy, grade, size = 16) {
    const group = svg("g", { class: "ch-chip g-" + String(grade).toLowerCase() });
    group.append(svg("rect", { x: round(cx - size / 2), y: round(cy - size / 2), width: size, height: size, rx: 3.5, class: "ch-chip-box" }), label(grade, cx, cy, "ch-chip-text", "middle", "0.35em"));
    return group;
  }

  function sparkline(values, { width = 96, height = 26, className = "spark" } = {}) {
    values = values.map(numeric);
    const data = values.map((value, index) => ({ value, index })).filter((point) => finite(point.value));
    const chart = root(width, height, "Trend", className + " chart-inline"); chart.setAttribute("aria-hidden", "true"); chart.removeAttribute("role"); chart.removeAttribute("aria-label");
    if (data.length < 2) return chart;
    const low = Math.min(...data.map((p) => p.value)); const high = Math.max(...data.map((p) => p.value));
    const x = linear([0, values.length - 1], [2, width - 4]); const y = linear([low, high === low ? low + 1 : high], [height - 3, 3]);
    chart.append(svg("path", { d: data.map((p, i) => (i ? "L" : "M") + round(x(p.index)) + " " + round(y(p.value))).join(""), class: "spark-line", fill: "none" }));
    const last = data[data.length - 1]; chart.append(svg("circle", { cx: round(x(last.index)), cy: round(y(last.value)), r: 2.2, class: "spark-dot" }));
    return chart;
  }

  /* Where scenario flags sit above a line chart: each is a short rule with its name beside it.
     Names that would collide share up to three rows; near the right edge they flip to the left of the rule. */
  function flagLayout(markers, points, x, width) {
    const placed = []; const ends = [];
    markers.filter((m) => m.index >= 0 && m.index <= points - 1).slice().sort((a, b) => a.index - b.index).forEach((marker) => {
      const at = x(marker.index); const text = String(marker.label || ""); const size = text.length * 5.8 + 10; const flip = at + size > width;
      const from = flip ? at - size : at; const to = flip ? at : at + size;
      let row = ends.findIndex((end) => from > end + 4); if (row < 0 && ends.length < 3) row = ends.length;
      const crowded = row < 0; if (crowded) row = ends.length - 1;  // a fourth overlapping flag keeps its rule and tooltip but drops its name
      else ends[row] = Math.max(ends[row] === undefined ? -Infinity : ends[row], to);
      placed.push({ marker, text: crowded ? "" : text, at, row, flip });
    });
    return { placed, rows: ends.length };
  }

  /* Lines over market time. `gap: [upper, lower]` shades the distance between two series; `hover(index)` adds a tooltip column per step.
     The y axis is fitted to the data (never forced to zero) so movement is visible. */
  function lineChart({ points, series, gap, format = String, width = 640, height = 250, description, markers = [], xLabel = () => "", pad = 0.08, marginRight = 112, endLabels = "full", yTickCount = 4, xTickCount = 3, hover }) {
    series = series.map((entry) => ({ ...entry, values: entry.values.map(numeric) }));
    const chart = root(width, height, description);
    const all = series.flatMap((s) => s.values).filter(finite);
    if (!all.length || points < 2) { chart.append(label("Waiting for history", width / 2, height / 2, "ch-empty", "middle")); return chart; }
    const margin = { left: 46, right: marginRight, top: 14, bottom: 26 };
    const x = linear([0, points - 1], [margin.left, width - margin.right]);
    const flags = flagLayout(markers, points, x, width); if (flags.rows) margin.top = 14 + flags.rows * 13;
    let low = Math.min(...all); let high = Math.max(...all); const room = (high - low || Math.abs(high) || 1) * pad; low -= room; high += room;
    const y = linear([low, high], [height - margin.bottom, margin.top]);
    ticks(low, high, yTickCount).forEach((value) => {
      chart.append(svg("line", { x1: margin.left, x2: width - margin.right, y1: round(y(value)), y2: round(y(value)), class: "ch-grid" }), label(format(value), margin.left - 8, y(value), "ch-tick", "end"));
    });
    const count = Math.max(2, xTickCount);
    for (let k = 0; k < count; k++) { const index = Math.round((k * (points - 1)) / (count - 1)); chart.append(label(xLabel(index), x(index), height - 6, "ch-tick", k === 0 ? "start" : k === count - 1 ? "end" : "middle", "0")); }
    if (gap) {
      const upper = series.find((s) => s.key === gap[0]).values; const lower = series.find((s) => s.key === gap[1]).values;
      const both = upper.map((value, index) => ({ index, a: value, b: lower[index] })).filter((p) => finite(p.a) && finite(p.b));
      if (both.length > 1) chart.append(svg("path", { d: both.map((p, i) => (i ? "L" : "M") + round(x(p.index)) + " " + round(y(p.a))).join("") + both.slice().reverse().map((p) => "L" + round(x(p.index)) + " " + round(y(p.b))).join("") + "Z", class: "ch-gap" }));
    }
    flags.placed.forEach(({ marker, text, at, row, flip }) => {
      const top = 1 + row * 13; const dim = marker.dim ? " dim" : "";
      chart.append(tip(svg("line", { x1: round(at), x2: round(at), y1: top, y2: height - margin.bottom, class: "ch-marker" + dim }), marker.title));
      if (text) chart.append(label(text, at + (flip ? -5 : 5), top + 6, "ch-marker-label" + dim, flip ? "end" : "start"));
    });
    const ends = [];
    series.forEach((s) => {
      const data = s.values.map((value, index) => ({ value, index })).filter((p) => finite(p.value));
      if (!data.length) return;
      chart.append(tip(svg("path", { d: data.map((p, i) => (i && data[i - 1].index === p.index - 1 ? "L" : "M") + round(x(p.index)) + " " + round(y(p.value))).join(""), class: "ch-line " + (s.className || ""), fill: "none" }), s.name));
      const last = data[data.length - 1]; chart.append(svg("circle", { cx: round(x(last.index)), cy: round(y(last.value)), r: 3, class: "ch-end " + (s.className || "") }));
      ends.push({ y: y(last.value), text: (endLabels === "value" ? "" : s.name + " ") + format(last.value), className: s.className || "" });
    });
    spread(ends, 13).forEach((end) => chart.append(label(end.text, width - margin.right + 10, end.y, "ch-direct " + end.className)));
    if (hover) {
      const slot = (width - margin.left - margin.right) / (points - 1);
      for (let index = 0; index < points; index++) chart.append(tip(svg("rect", { x: round(x(index) - slot / 2), y: margin.top, width: round(slot), height: height - margin.bottom - margin.top, class: "ch-hit" }), hover(index)));
    }
    return chart;
  }

  /* Grouped horizontal bars on one zero-based axis, one row per category.
     row: { label, sub, bars: [{ value, text, className, grade, title, absent }], trail, trailClass }.
     A bar without a value but with `absent` prints that note where the bar would be. `trail` is a text column on the right. */
  function groupedBars({ rows, width = 640, description, format = String, labelWidth = 108, trailWidth = 60, valueRoom = 82, trailTitle = "", barHeight = 12, barGap = 3, rowHeight = 46, tickCount = 7 }) {
    rows = rows.map((row) => ({ ...row, bars: row.bars.map((bar) => ({ ...bar, value: numeric(bar.value) })) }));
    const head = 26; const height = head + rows.length * rowHeight + 2; const chart = root(width, height, description, "chart chart-grouped");
    const high = Math.max(0, ...rows.flatMap((row) => row.bars.map((bar) => bar.value)).filter(finite));
    const axis = zeroAxis(high || 1, tickCount); const right = width - trailWidth - valueRoom;
    const x = linear([0, axis.top], [labelWidth, right]);
    axis.ticks.forEach((value) => chart.append(svg("line", { x1: round(x(value)), x2: round(x(value)), y1: head - 8, y2: height, class: value === 0 ? "ch-axis" : "ch-grid" }), label(format(value), x(value), 6, "ch-tick", "middle", "0.5em")));
    if (trailTitle) chart.append(label(trailTitle, width, 6, "ch-tick ch-head", "end", "0.5em"));
    rows.forEach((row, index) => {
      const top = head + index * rowHeight; const cy = top + rowHeight / 2; const stack = row.bars.length * barHeight + (row.bars.length - 1) * barGap;
      if (index) chart.append(svg("line", { x1: 0, x2: width, y1: top, y2: top, class: "ch-rule" }));
      chart.append(label(row.label, 0, cy - 6, "ch-row-label"), label(row.sub || "", 0, cy + 9, "ch-row-sub"));
      row.bars.forEach((bar, position) => {
        const by = cy - stack / 2 + position * (barHeight + barGap); const mid = by + barHeight / 2;
        if (!finite(bar.value)) { if (bar.absent) chart.append(label(bar.absent, x(0) + 8, mid, "ch-note")); return; }
        const end = x(bar.value);
        chart.append(tip(svg("rect", { x: round(x(0)), y: round(by), width: Math.max(2, round(end - x(0))), height: barHeight, class: "ch-part " + (bar.className || "") }), bar.title));
        const gx = end + 9; if (bar.grade) chart.append(tip(chip(gx + 7, mid, bar.grade, 15), "Seller grade " + bar.grade));
        chart.append(label(bar.text === undefined ? format(bar.value) : bar.text, bar.grade ? gx + 20 : gx, mid, "ch-value"));
      });
      chart.append(label(row.trail || "", width, cy, "ch-trail " + (row.trailClass || ""), "end"));
    });
    return chart;
  }

  /* Grouped columns on one zero-based axis. col: { label (grade letter), sub, bars: [{ value, text, className, title }] }. */
  function groupedColumns({ cols, width = 440, height = 240, description, format = String, tickCount = 5 }) {
    cols = cols.map((col) => ({ ...col, bars: col.bars.map((bar) => ({ ...bar, value: numeric(bar.value) })) }));
    const margin = { left: 40, right: 6, top: 22, bottom: 46 }; const chart = root(width, height, description, "chart chart-columns");
    const high = Math.max(0, ...cols.flatMap((col) => col.bars.map((bar) => bar.value)).filter(finite));
    const axis = zeroAxis(high || 1, tickCount); const y = linear([0, axis.top], [height - margin.bottom, margin.top]); const slot = (width - margin.left - margin.right) / cols.length;
    axis.ticks.forEach((value) => chart.append(svg("line", { x1: margin.left, x2: width - margin.right, y1: round(y(value)), y2: round(y(value)), class: value === 0 ? "ch-axis" : "ch-grid" }), label(format(value), margin.left - 6, y(value), "ch-tick", "end")));
    cols.forEach((col, index) => {
      const centre = margin.left + index * slot + slot / 2; const barWidth = Math.min(34, slot * 0.32); const gap = 3; const span = col.bars.length * barWidth + (col.bars.length - 1) * gap;
      col.bars.forEach((bar, position) => {
        if (!finite(bar.value)) return;
        const bx = centre - span / 2 + position * (barWidth + gap); const top = y(bar.value);
        chart.append(tip(svg("rect", { x: round(bx), y: round(top), width: round(barWidth), height: Math.max(1, round(y(0) - top)), class: "ch-part " + (bar.className || "") }), bar.title));
        chart.append(label(bar.text === undefined ? format(bar.value) : bar.text, bx + barWidth / 2, top - 8, "ch-value-top", "middle"));
      });
      chart.append(chip(centre, height - margin.bottom + 16, col.label, 16), label(col.sub || "", centre, height - 8, "ch-tick", "middle", "0"));
    });
    return chart;
  }

  /* Horizontal stacked rows. normalize: each row fills the width; otherwise rows share one scale (set `max`).
     `inside(part, share, total)` may return a label drawn in the segment when it is wide enough to hold it. */
  function stackedBars({ rows, width = 520, description, normalize = false, max, labelWidth = 76, valueWidth = 64, rowHeight = 26, barHeight = 14, inside, valueText = (row, total) => total === null ? "—" : String(total) }) {
    rows = rows.map((row) => ({ ...row, parts: row.parts.map((part) => ({ ...part, value: numeric(part.value) })) }));
    const height = rows.length * rowHeight + 4; const chart = root(width, height, description, "chart chart-bars");
    const scaleMax = normalize ? 1 : numeric(max) || Math.max(1, ...rows.map((r) => r.parts.reduce((sum, p) => sum + (p.value === null ? 0 : p.value), 0)));
    const x = linear([0, scaleMax], [labelWidth, width - valueWidth]); const half = barHeight / 2;
    rows.forEach((row, index) => {
      const cy = index * rowHeight + rowHeight / 2 + 2; const known = row.parts.every((part) => finite(part.value)); const total = row.parts.reduce((sum, p) => sum + (p.value === null ? 0 : p.value), 0);
      chart.append(label(row.label, 0, cy, "ch-row-label"));
      chart.append(svg("rect", { x: labelWidth, y: cy - half, width: width - valueWidth - labelWidth, height: barHeight, class: "ch-bed" }));
      let cursor = 0;
      row.parts.forEach((part) => {
        if (!(part.value > 0)) return;
        const size = normalize ? part.value / (total || 1) : part.value; const span = x(cursor + size) - x(cursor);
        const rect = svg("rect", { x: round(x(cursor)), y: cy - half, width: Math.max(1, round(span - 1)), height: barHeight, class: "ch-part " + (part.className || "") });
        chart.append(tip(rect, part.title));
        const text = inside && known && span >= 30 ? inside(part, part.value / (total || 1), total) : ""; if (text) chart.append(label(text, x(cursor) + span / 2, cy, "ch-inside", "middle"));
        cursor += size;
      });
      chart.append(label(valueText(row, known ? total : null), width, cy, "ch-value", "end"));
    });
    return chart;
  }

  /* Vertical stacked columns on one shared scale; `divider` draws a rule between two column indexes; `totals` prints each column's total above it. */
  function columns({ cols, width = 520, height = 220, description, divider, dividerLabel, totals = false, axisTitle = "Key terms missing per quote" }) {
    cols = cols.map((col) => ({ ...col, parts: col.parts.map((part) => ({ ...part, value: numeric(part.value) })) }));
    const margin = { left: 34, right: 8, top: totals ? 24 : 14, bottom: 34 }; const chart = root(width, height, description, "chart chart-columns");
    const sums = cols.map((c) => c.parts.reduce((sum, p) => sum + (p.value === null ? 0 : p.value), 0)); const top = Math.max(1, ...sums);
    const axis = totals ? zeroAxis(top, 6) : { top: top * 1.08, ticks: ticks(0, top * 1.08, 4) };
    const y = linear([0, axis.top], [height - margin.bottom, margin.top]); const slot = (width - margin.left - margin.right) / cols.length;
    axis.ticks.forEach((value) => chart.append(svg("line", { x1: margin.left, x2: width - margin.right, y1: round(y(value)), y2: round(y(value)), class: totals && value === 0 ? "ch-axis" : "ch-grid" }), label(String(value), margin.left - 6, y(value), "ch-tick", "end")));
    cols.forEach((col, index) => {
      let base = 0;
      col.parts.forEach((part) => {
        if (!(part.value > 0)) return;
        chart.append(tip(svg("rect", { x: round(margin.left + index * slot + slot * 0.16), y: round(y(base + part.value)), width: round(slot * 0.68), height: Math.max(1, round(y(base) - y(base + part.value) - 1)), class: "ch-part " + (part.className || "") }), part.title));
        base += part.value;
      });
      if (totals) chart.append(label(col.parts.every((part) => finite(part.value)) ? String(sums[index]) : "—", margin.left + index * slot + slot / 2, y(base) - 8, "ch-value-top", "middle"));
      chart.append(label(col.label, margin.left + index * slot + slot / 2, height - 20, "ch-tick", "middle"));
    });
    if (divider !== undefined) {
      const at = margin.left + (divider + 1) * slot;
      chart.append(svg("line", { x1: round(at), x2: round(at), y1: margin.top - 6, y2: height - margin.bottom, class: "ch-marker" }), label(dividerLabel, at + 6, margin.top - 2, "ch-marker-label", "start"));
    }
    chart.append(label(axisTitle, margin.left + (width - margin.left - margin.right) / 2, height - 4, "ch-axis-title", "middle", "0"));
    return chart;
  }

  /* Single-series horizontal bars. A row may carry its own `text` for the value label. */
  function bars({ rows, width = 520, description, labelWidth = 104, valueWidth = 30, rowHeight = 24 }) {
    rows = rows.map((row) => ({ ...row, value: numeric(row.value) }));
    const chart = root(width, rows.length * rowHeight + 4, description, "chart chart-bars"); const top = Math.max(1, ...rows.map((r) => r.value).filter(finite));
    const x = linear([0, top], [labelWidth, width - valueWidth]);
    rows.forEach((row, index) => {
      const cy = index * rowHeight + rowHeight / 2 + 2;
      const bar = row.value === null ? null : tip(svg("rect", { x: labelWidth, y: cy - 6, width: Math.max(row.value ? 2 : 0, round(x(row.value) - labelWidth)), height: 12, class: "ch-part " + (row.className || "") }), row.title);
      chart.append(label(row.label, 0, cy, "ch-row-label")); if (bar) chart.append(bar);
      chart.append(label(row.text === undefined ? row.value === null ? "—" : String(row.value) : row.text, width, cy, "ch-value", "end"));
    });
    return chart;
  }

  function legend(items) {
    const list = document.createElement("ul"); list.className = "chart-legend";
    items.forEach((item) => {
      const entry = document.createElement("li"); const mark = document.createElement("span"); mark.className = "swatch " + item.className; mark.setAttribute("aria-hidden", "true");
      entry.append(mark, document.createTextNode(item.label)); list.append(entry);
    });
    return list;
  }

  window.ComputeCharts = Object.freeze({ svg, sparkline, lineChart, stackedBars, columns, bars, legend, ticks, groupedBars, groupedColumns, zeroAxis });
})();
