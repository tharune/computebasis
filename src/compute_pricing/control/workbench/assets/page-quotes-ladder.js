/* Quote ladder: every quote for one GPU model on one shared dollars-per-GPU-hour axis, in a band per seller grade.
   A quote is a dot at its quoted price; where the book can price it all-in, a line runs right to the all-in cost, so the length of the
   line is what financing and expected loss add. A solid dot is an eligible quote, a ring is not. Grade is the band, not a colour, so the
   only colours are the accent (eligible) and a neutral (not eligible). The lowest quote and the best eligible buy get a hairline and a
   name. Colour and size reach the page only through classes and SVG attributes (the content security policy forbids inline styles).
   Exposed as window.QuotesCharts.ladder; page-quotes.js draws it. */
(() => {
  "use strict";
  const charts = window.ComputeCharts; if (!charts) return;
  const { svg } = charts;
  const GRADES = ["A", "B", "C", "D"];
  const SUB = 17;          // height of one line of marks inside a band
  const BAND_PAD = 11;     // space above and below the marks in a band
  const TIP_W = 212;
  const round = (value) => Math.round(value * 100) / 100;
  const money = (value) => Number(value).toFixed(4);
  const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
  const label = (content, x, y, className, anchor = "start", dy = "0.32em") => { const node = svg("text", { x: round(x), y: round(y), class: className, "text-anchor": anchor, dy }); node.textContent = content; return node; };
  const textWidth = (text, size = 11.5) => String(text).length * size * 0.54;
  const html = (tag, className, text) => { const node = document.createElement(tag); if (className) node.className = className; if (text !== undefined) node.textContent = text; return node; };

  /* Round ticks that cover [low, high]; the first and last tick are the ends of the axis, so no mark sits on the frame. */
  function axis(low, high, target) {
    const span = high - low || Math.abs(high) * 0.1 || 1; const raw = span / Math.max(2, target); const magnitude = 10 ** Math.floor(Math.log10(raw));
    const step = [1, 2, 2.5, 5, 10].map((unit) => unit * magnitude).find((candidate) => candidate >= raw);
    const first = Math.floor(low / step + 1e-9) * step; const last = Math.ceil(high / step - 1e-9) * step; const ticks = [];
    for (let value = first; value <= last + step * 1e-9; value += step) ticks.push(Math.round(value * 1e6) / 1e6);
    const places = Math.min(4, Math.max(2, Math.ceil(-Math.log10(step) - 1e-9)));
    return { ticks, low: ticks[0], high: ticks[ticks.length - 1], places, step };
  }

  /* Pack marks into as few lines as possible inside a band: the first line where a mark does not touch the one before it. */
  function pack(items) {
    const ends = []; const lines = [];
    items.slice().sort((a, b) => a.left - b.left || a.id.localeCompare(b.id)).forEach((item) => {
      let line = ends.findIndex((end) => item.left > end); if (line < 0) { line = ends.length; ends.push(-Infinity); }
      ends[line] = item.right; lines.push({ item, line });
    });
    return { lines, count: Math.max(1, ends.length) };
  }

  /* Names for the reference lines. The lowest quote's name extends left of its line and the best buy's to the right of its line, so they
     part company by themselves; a name that would run off the chart flips, and one that would run into the other drops to a second row. */
  function placeNames(names, left, right) {
    const placed = []; const rows = [[], []];
    names.forEach((entry) => {
      const width = textWidth(entry.text) + 6; let side = entry.prefer;
      if (side === "end" && entry.x - width < left) side = "start"; if (side === "start" && entry.x + width > right) side = "end";
      const from = side === "start" ? entry.x : entry.x - width; const to = from + width; let row = 0;
      if (rows[0].some((other) => from < other.to + 10 && to > other.from - 10)) row = 1;
      rows[row].push({ from, to }); placed.push({ ...entry, side, row, from, to });
    });
    return { placed, rows: rows[1].length ? 2 : 1 };
  }

  const standing = (quote) => (quote.eligible ? "eligible" : "not eligible");
  const gradeText = (quote) => (quote.grade === "U" ? "Unrated seller" : "Grade " + quote.grade);

  /* options: { quotes, lowestId, bestId, selectedId, model, width, animate, basisText, premium(quote), onSelect(id), onHover(id) } */
  function ladder(options) {
    const { selectedId = "", model = "", animate = false, onSelect = () => {}, onHover = () => {}, premium = () => null } = options;
    const all = options.quotes || []; const quotes = all.filter((q) => Number.isFinite(q.price));
    const width = Math.max(300, Math.round(options.width || 760)); const compact = width < 520;
    const gutter = compact ? 50 : 84; const left = gutter + 8; const right = width - 16;
    const wrap = html("div", "qx-ladder-chart"); const marks = new Map();
    if (!quotes.length) { wrap.append(html("p", "empty-state", "No " + model + " quotes in the book.")); return { node: wrap, marks, focus: () => false, reveal: () => false }; }
    const unpriced = quotes.filter((q) => q.risk_adjusted === null).length;

    const values = quotes.flatMap((q) => [q.price, q.risk_adjusted]).filter((v) => Number.isFinite(v));
    const scale = axis(Math.min(...values), Math.max(...values), Math.floor((right - left) / 70));
    const x = (value) => left + ((value - scale.low) / (scale.high - scale.low || 1)) * (right - left);

    const lowest = quotes.find((q) => q.id === options.lowestId) || null; const best = quotes.find((q) => q.id === options.bestId && q.risk_adjusted !== null) || null;
    const lowX = lowest ? x(lowest.price) : null; const bestX = best ? x(best.risk_adjusted) : null; const same = Boolean(lowest && best && lowest.id === best.id);
    const names = [];
    if (same) names.push({ key: "low", x: lowX, prefer: "start", text: "Lowest quote and best eligible, " + lowest.ref });
    else { if (lowest) names.push({ key: "low", x: lowX, prefer: "end", text: "Lowest quote " + lowest.ref }); if (best) names.push({ key: "best", x: bestX, prefer: "start", text: "Best eligible " + best.ref }); }
    const naming = placeNames(names, 0, width); const top = naming.rows === 2 ? 46 : 30;
    const nameRow = (key) => (naming.placed.find((entry) => entry.key === key) || naming.placed[0] || { row: 0 }).row;

    /* a band per grade, A first, then unrated sellers when the model has any */
    const order = GRADES.concat(quotes.some((q) => q.grade === "U") ? ["U"] : []);
    let cursor = top; const bands = order.map((grade) => {
      const members = quotes.filter((q) => q.grade === grade);
      const packed = pack(members.map((q) => ({ id: q.id, quote: q, left: x(q.price) - 9, right: (q.risk_adjusted !== null ? x(q.risk_adjusted) : x(q.price)) + 9 })));
      const bandHeight = members.length ? BAND_PAD * 2 + packed.count * SUB : 36; const band = { grade, members, packed, top: cursor, height: bandHeight }; cursor += bandHeight; return band;
    });
    const bottom = cursor; const height = bottom + 44;
    const description = "Quote ladder for " + model + ": " + quotes.length + " quotes by seller grade on one scale in dollars per GPU-hour. " + (lowest ? "Lowest quote " + lowest.ref + " at " + money(lowest.price) + ", " + standing(lowest) + ". " : "") + (best ? "Best eligible buy " + best.ref + " at " + money(best.risk_adjusted) + " all-in." : "No eligible quote.");
    const chart = svg("svg", { viewBox: "0 0 " + width + " " + height, class: "chart qx-ladder" + (animate ? " qx-enter" : ""), role: "group", "aria-label": description, focusable: "false" });

    /* grid, band rules and axis */
    scale.ticks.forEach((tick) => chart.append(svg("line", { x1: round(x(tick)), x2: round(x(tick)), y1: top, y2: bottom, class: "ch-grid" }), label(tick.toFixed(scale.places), x(tick), bottom + 17, "ch-tick", "middle", "0")));
    bands.forEach((band, index) => { if (index) chart.append(svg("line", { x1: 0, x2: width, y1: band.top, y2: band.top, class: "ch-rule" })); });
    chart.append(svg("line", { x1: left, x2: right, y1: bottom, y2: bottom, class: "ch-axis" }), label("US dollars per GPU-hour", (left + right) / 2, bottom + 37, "ch-axis-title", "middle", "0"));

    /* the gap between the lowest quote and the best eligible all-in cost, then the two reference lines and their names */
    if (lowX !== null && bestX !== null && Math.abs(bestX - lowX) > 0.5) {
      chart.append(svg("rect", { x: round(Math.min(lowX, bestX)), y: top, width: round(Math.abs(bestX - lowX)), height: bottom - top, class: "qx-band" }));
      const centre = (lowX + bestX) / 2; const half = textWidth(options.basisText || "", 11) / 2 + 8;
      /* the gap is named above the plot, between the two names, when there is room for it there */
      if (options.basisText && Math.abs(bestX - lowX) >= half * 2 && naming.placed.every((entry) => entry.row !== 0 || entry.to < centre - half || entry.from > centre + half)) chart.append(label(options.basisText, centre, 12, "qx-band-text", "middle"));
    }
    if (lowX !== null) chart.append(svg("line", { x1: round(lowX), x2: round(lowX), y1: 12 + nameRow("low") * 16 + 6, y2: bottom, class: "qx-ref qx-ref-low" }));
    if (bestX !== null) chart.append(svg("line", { x1: round(bestX), x2: round(bestX), y1: 12 + nameRow(same ? "low" : "best") * 16 + 6, y2: bottom, class: "qx-ref qx-ref-best" }));
    naming.placed.forEach((entry) => chart.append(label(entry.text, entry.x + (entry.side === "start" ? 5 : -5), 12 + entry.row * 16, "qx-ref-name", entry.side)));

    /* band labels, then the marks (the selected quote last, so nothing covers its ring) */
    const anchors = new Map(); const groups = [];
    const sequence = quotes.slice().sort((a, b) => a.price - b.price || a.id.localeCompare(b.id));
    const rovingId = sequence.some((q) => q.id === selectedId) ? selectedId : sequence[0].id;
    const tip = svg("g", { class: "qx-tip", "aria-hidden": "true" }); const tipBox = svg("rect", { x: 0, y: 0, width: TIP_W, height: 74, rx: 4, class: "qx-tip-box" });
    const tipText = [0, 1, 2, 3, 4].map((i) => label("", 10, 17 + i * 15, i === 0 ? "qx-tip-head" : i === 4 ? "qx-tip-note" : "qx-tip-line", "start", "0")); tip.append(tipBox, ...tipText);
    function reveal(id) {
      const anchor = anchors.get(id); if (!anchor) return false; const quote = anchor.quote;
      const pct = premium(quote); const reason = quote.eligible ? "" : (quote.reasons[0] || "Not eligible") + (quote.reasons.length > 1 ? " and " + (quote.reasons.length - 1) + " more" : "");
      const lines = [quote.ref + "  " + (quote.provider || ""), gradeText(quote) + ", " + standing(quote), "Quoted " + money(quote.price), quote.risk_adjusted === null ? "All-in cost not available" : "All-in " + money(quote.risk_adjusted) + (pct ? ", " + pct + " over lowest" : ""), reason];
      const count = reason ? 5 : 4; tipText.forEach((node, i) => { node.textContent = i < count ? lines[i] : ""; });
      const tipHeight = 14 + count * 15; tipBox.setAttribute("height", tipHeight);
      const tx = clamp(anchor.x - TIP_W / 2, 0, width - TIP_W); const above = anchor.y - tipHeight - 14;
      tip.setAttribute("transform", "translate(" + round(tx) + " " + round(above >= 0 ? above : anchor.y + 16) + ")"); tip.classList.add("is-on"); return true;
    }
    const hide = () => tip.classList.remove("is-on");
    const columnOf = (value) => clamp(Math.floor(((value - left) / (right - left || 1)) * 10), 0, 9);

    bands.forEach((band) => {
      const mid = band.top + band.height / 2;
      const chip = svg("g", { class: "ch-chip g-" + band.grade.toLowerCase() }); chip.append(svg("rect", { x: 0, y: round(mid - 8), width: 16, height: 16, rx: 3.5, class: "ch-chip-box" }), label(band.grade, 8, mid, "ch-chip-text", "middle", "0.35em"));
      const count = band.members.length; chart.append(chip, label(compact ? String(count) : count + (count === 1 ? " quote" : " quotes"), 24, mid, "qx-band-count", "start"));
      if (!count) chart.append(label("None", left + 4, mid, "qx-band-none", "start"));
      band.packed.lines.forEach(({ item, line }) => {
        const quote = item.quote; const y = band.top + BAND_PAD + line * SUB + SUB / 2; const xq = x(quote.price); const xa = quote.risk_adjusted !== null ? x(quote.risk_adjusted) : null;
        const group = svg("g", { class: "qx-q " + (quote.eligible ? "elig" : "inel") + (xa === null ? " unpriced" : "") + (quote.id === selectedId ? " is-selected" : "") + (animate ? " d" + columnOf(xq) : ""), tabindex: quote.id === rovingId ? 0 : -1, role: "button", "data-id": quote.id, "data-fk": "mark:" + quote.id,
          "aria-label": quote.ref + ", " + (quote.provider || "seller") + ", " + gradeText(quote).toLowerCase() + ", " + standing(quote) + ". Quoted " + money(quote.price) + (xa === null ? ", cannot be priced all-in" : ", all-in " + money(quote.risk_adjusted)) + " dollars per GPU-hour. Select to open it." });
        group.append(svg("line", { x1: round(xq), x2: round(xa === null ? xq : xa), y1: round(y), y2: round(y), class: "qx-hit" }));
        if (xa !== null) group.append(svg("line", { x1: round(xq), x2: round(xa), y1: round(y), y2: round(y), class: "qx-span" }), svg("line", { x1: round(xa), x2: round(xa), y1: round(y - 5), y2: round(y + 5), class: "qx-cap" }));
        group.append(svg("circle", { cx: round(xq), cy: round(y), r: 10.5, class: "qx-ring" }), svg("circle", { cx: round(xq), cy: round(y), r: 5.5, class: "qx-dot" }));
        anchors.set(quote.id, { quote, x: xa === null ? xq : (xq + xa) / 2, y });
        group.addEventListener("pointerenter", () => { onHover(quote.id); reveal(quote.id); });
        group.addEventListener("pointerleave", () => { onHover(""); hide(); });
        group.addEventListener("focus", () => reveal(quote.id)); group.addEventListener("blur", hide);
        group.addEventListener("click", () => onSelect(quote.id));
        group.addEventListener("keydown", (event) => {
          const index = sequence.findIndex((q) => q.id === quote.id); let next = null;
          if (event.key === "Enter" || event.key === " ") { event.preventDefault?.(); onSelect(quote.id); return; }
          if (event.key === "ArrowRight" || event.key === "ArrowDown") next = sequence[Math.min(sequence.length - 1, index + 1)];
          else if (event.key === "ArrowLeft" || event.key === "ArrowUp") next = sequence[Math.max(0, index - 1)];
          else if (event.key === "Home") next = sequence[0]; else if (event.key === "End") next = sequence[sequence.length - 1];
          if (!next) return; event.preventDefault?.();
          sequence.forEach((q) => marks.get(q.id)?.setAttribute("tabindex", q.id === next.id ? "0" : "-1")); marks.get(next.id)?.focus();
        });
        marks.set(quote.id, group); groups.push(group);
      });
    });
    groups.filter((g) => g.getAttribute("data-id") !== selectedId).concat(groups.filter((g) => g.getAttribute("data-id") === selectedId)).forEach((g) => chart.append(g));
    chart.append(tip);

    /* the legend says what the marks mean, once, and how many quotes cannot be priced all-in */
    const key = html("ul", "qx-key");
    const entry = (kind, text) => { const item = html("li"); const glyph = html("span", "qx-glyph " + kind); glyph.setAttribute("aria-hidden", "true"); item.append(glyph, document.createTextNode(text)); return item; };
    key.append(entry("elig", "Eligible"), entry("inel", "Not eligible"), entry("span", "Dot: quoted price. End of line: all-in cost"));
    if (unpriced) key.append(entry("lone", unpriced + (unpriced === 1 ? " quote cannot" : " quotes cannot") + " be priced all-in, so " + (unpriced === 1 ? "it is" : "they are") + " drawn with a dashed ring and no line"));

    /* the same data as a table, for screen readers and anyone who wants the numbers */
    const twin = html("table", "qx-twin"); twin.append(html("caption", "", "Quote ladder data for " + model + ", in dollars per GPU-hour"));
    const headRow = html("tr"); ["Quote", "Seller", "Grade", "Standing", "Quoted", "All-in"].forEach((name) => { const th = html("th", "", name); th.setAttribute("scope", "col"); headRow.append(th); });
    const thead = html("thead"); thead.append(headRow); twin.append(thead);
    const body = html("tbody");
    sequence.forEach((q) => { const row = html("tr"); [q.ref, q.provider || "", q.grade === "U" ? "Unrated" : q.grade, q.eligible ? "Eligible" : "Not eligible", money(q.price), q.risk_adjusted === null ? "Not available" : money(q.risk_adjusted)].forEach((value) => row.append(html("td", "", value))); body.append(row); });
    twin.append(body);

    const hidden = html("div", "sr-only"); hidden.append(twin);
    wrap.append(chart, key, hidden);
    return { node: wrap, marks, reveal, focus: (id) => { const target = marks.get(id); if (!target) return false; target.focus({ preventScroll: true }); return true; } };
  }

  window.QuotesCharts = Object.assign(window.QuotesCharts || {}, { ladder, axis });
})();
