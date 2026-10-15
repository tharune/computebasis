/* Why quotes are not eligible: for one GPU model, how many quotes are eligible and how many fail each check.
   One row per reason, label above a bar on a shared scale (the model's quote count), so the bars read as a share of the book. A quote can fail
   several checks, so the reasons add up to more than the number of ineligible quotes; the page says so. The reasons the lowest quote fails
   carry its name, which answers "why is the cheapest quote not on the buy list" without leaving the chart.
   Exposed as window.QuotesCharts.reasons; page-quotes.js draws it. */
(() => {
  "use strict";
  const charts = window.ComputeCharts; if (!charts) return;
  const { svg } = charts;
  const ROW = 46;
  const round = (value) => Math.round(value * 100) / 100;
  const html = (tag, className, text) => { const node = document.createElement(tag); if (className) node.className = className; if (text !== undefined) node.textContent = text; return node; };
  const label = (content, x, y, className, anchor = "start") => { const node = svg("text", { x: round(x), y: round(y), class: className, "text-anchor": anchor, dy: "0.32em" }); node.textContent = content; return node; };
  /* A flat baseline and a 4px rounded data end. */
  function bar(x0, y, length, thickness, radius) {
    const r = Math.min(radius, length, thickness / 2); const x1 = x0 + length;
    return "M" + round(x0) + " " + round(y) + "H" + round(x1 - r) + "A" + r + " " + r + " 0 0 1 " + round(x1) + " " + round(y + r) + "V" + round(y + thickness - r) + "A" + r + " " + r + " 0 0 1 " + round(x1 - r) + " " + round(y + thickness) + "H" + round(x0) + "Z";
  }

  /* options: { quotes, model, width, lowest (quote or null), animate, name(code) } */
  function reasons(options) {
    const { quotes = [], model = "", lowest = null, animate = false } = options; const name = options.name || ((code) => code);
    const width = Math.max(240, Math.round(options.width || 380)); const total = quotes.length;
    const wrap = html("div", "qx-reasons-chart");
    if (!total) { wrap.append(html("p", "empty-state", "No " + model + " quotes in the book.")); return { node: wrap, rows: [] }; }
    const counts = new Map(); quotes.forEach((q) => q.reason_codes.forEach((code) => counts.set(code, (counts.get(code) || 0) + 1)));
    const eligible = quotes.filter((q) => q.eligible).length; const ineligible = total - eligible;
    const lowestCodes = new Set(lowest && !lowest.eligible ? lowest.reason_codes : []);
    const rows = [{ key: "eligible", text: "Eligible", count: eligible, className: "qx-bar elig", tag: "" }].concat([...counts].sort((a, b) => b[1] - a[1] || name(a[0]).localeCompare(name(b[0]))).map(([code, count]) => ({ key: code, text: name(code), count, className: "qx-bar inel", tag: lowestCodes.has(code) ? "Lowest quote" : "" })));
    /* Wide enough, the rows run in two columns so the bars keep their size instead of stretching across the page. */
    const columns = width >= 720 ? 2 : 1; const gap = 32; const colWidth = (width - gap * (columns - 1)) / columns; const perColumn = Math.ceil(rows.length / columns);
    const height = perColumn * ROW + 4;
    const description = "Of " + total + " " + model + " quotes, " + eligible + " are eligible and " + ineligible + " are not. Quotes failing each check: " + rows.slice(1).map((row) => row.text + ", " + row.count).join("; ") + ".";
    const chart = svg("svg", { viewBox: "0 0 " + width + " " + height, class: "chart qx-reasons" + (animate ? " qx-enter" : ""), role: "img", "aria-label": description, focusable: "false" });
    rows.forEach((row, index) => {
      const column = Math.floor(index / perColumn); const place = index % perColumn; const left = column * (colWidth + gap); const edge = left + colWidth; const right = edge - 34;
      const top = place * ROW + 2; const labelY = top + 12; const barTop = top + 25; const thickness = 10;
      if (index === 1) chart.append(svg("line", { x1: left, x2: edge, y1: top - 4, y2: top - 4, class: "ch-rule" }));
      chart.append(label(row.text, left, labelY, "qx-reason-name"));
      if (row.tag) chart.append(label(row.tag, edge - 1, labelY, "qx-reason-tag", "end"));
      chart.append(svg("rect", { x: left, y: barTop, width: right - left, height: thickness, rx: 4, class: "qx-track" }));
      if (row.count > 0) chart.append(svg("path", { d: bar(left, barTop, Math.max(4, (row.count / total) * (right - left)), thickness, 4), class: row.className + (animate ? " d" + Math.min(index, 9) : "") }));
      chart.append(label(String(row.count), edge - 1, barTop + thickness / 2, "qx-reason-count", "end"));
    });
    const twin = html("table", "qx-twin"); twin.append(html("caption", "", "Eligibility of " + model + " quotes: how many are eligible and how many fail each check"));
    const headRow = html("tr"); ["Check", "Quotes"].forEach((text) => { const th = html("th", "", text); th.setAttribute("scope", "col"); headRow.append(th); }); const thead = html("thead"); thead.append(headRow); twin.append(thead);
    const body = html("tbody"); rows.forEach((row) => { const tr = html("tr"); tr.append(html("td", "", row.text), html("td", "", String(row.count))); body.append(tr); }); twin.append(body);
    const hidden = html("div", "sr-only"); hidden.append(twin);
    wrap.append(chart, hidden);
    return { node: wrap, rows };
  }
  window.QuotesCharts = Object.assign(window.QuotesCharts || {}, { reasons });
})();
