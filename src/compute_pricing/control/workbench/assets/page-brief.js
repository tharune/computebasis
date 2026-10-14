/* The landing view: the Brief. A one-page argument, drawn from the live simulated book. */
(() => {
  "use strict";
  const D = window.ComputeDemo; if (!D) return;
  const { charts, state, h, int, pct, compact, gradeClass, replace, empty, live, lowestPrice, GRADES, FIELD_NAMES, CATEGORIES, byId } = D;
  const showView = D.host.showView;

  /* ---- Brief ---- */
  /* The landing view. Its charts come from LandingCharts (landing-charts.js), which draws each one at the width it is shown at and
     keeps it alive between polls; colour still arrives only through CSS classes, keeping both themes and the CSP intact. A chart
     that fails to draw is logged and left as it was: it never stops the poll or blanks the page. */
  const landing = window.LandingCharts || { bars: () => null, release: () => {}, sparkline: () => null, money: (v) => "$" + Number(v).toFixed(3), printed: Number, afterEntrance: () => {}, flushEntrances: () => {} };
  const money = landing.money;
  const gradeName = (grade) => (grade === "U" ? "Unrated" : "Grade " + grade);  // U: the seller has no grade
  const gradeInline = (grade) => (grade === "U" ? "unrated" : "grade " + grade);  // inside a sentence, the letter keeps its case
  let briefDrawn = false;
  const frames = new Map(); const swaps = new Map(); const kidSigs = new WeakMap();
  const sigOf = (node) => String(node.className || "").replace(/\s*\bbf-in\b/, "") + "|" + node.textContent;
  /* A chart slot is a frame built once: the chart's host, then the plain pieces under it (legend, split, caption). The host and its
     <svg> outlive the poll; only what changed inside them is touched. */
  function slotFrame(id, parts) {
    const slot = byId(id); const known = frames.get(id); const key = parts.join(" ");
    if (known && known.key === key && slot.children.length === parts.length && parts.every((name, i) => slot.children[i] === known.nodes[name])) return known.nodes;
    dropFrame(id);
    const nodes = {}; parts.forEach((name) => { nodes[name] = name === "chart" ? h("div", "bf-chart-host") : name === "split" ? h("dl", "bf-split") : name === "caption" ? h("p", "bf-caption") : h("div", "bf-legend-host"); });
    slot.replaceChildren(...parts.map((name) => nodes[name])); frames.set(id, { key, nodes }); return nodes;
  }
  function dropFrame(id) { const known = frames.get(id); if (known) { landing.release(known.nodes.chart); frames.delete(id); } swaps.delete(id); }
  function clearSlot(id, ...children) { dropFrame(id); replace(id, ...children); }
  /* Replace a node's children only when what they print has changed, so text being read or selected survives the poll. */
  function setKids(node, children) {
    const nodes = [].concat(children).flat().filter(Boolean); const sig = nodes.map(sigOf).join("¦");
    if (kidSigs.get(node) === sig) return; kidSigs.set(node, sig); node.replaceChildren(...nodes);
  }
  function refresh(id, children, extra = "") {
    const slot = byId(id); const nodes = [].concat(children).flat().filter(Boolean); const sig = extra + "¦" + nodes.map(sigOf).join("¦");
    if (swaps.get(id) === sig && slot.children.length === nodes.length) return false;
    swaps.set(id, sig); slot.replaceChildren(...nodes); return true;
  }
  const setText = (node, value) => { if (node.textContent !== value) node.textContent = value; };
  const section = (name, draw) => { try { draw(); } catch (error) { console.error("Brief " + name + ":", error); } };
  const statLine = (value, caption) => [h("strong", "bf-stat-value", value), h("span", "bf-stat-text", caption)];
  const axisPercent = (step = 10, floor = 20, headroom = 1.1) => ({ step, floor, headroom, format: (value, last) => value + (last ? "%" : "") });
  const share = (fraction, places = 0) => { const text = pct(fraction, places); return { text, value: Number(text.replace("%", "")) }; };

  function renderBrief() {
    const slots = ["brief-facts", "brief-fact-gaps", "brief-gaps", "brief-fact-cost", "brief-anatomy", "brief-fact-grades", "brief-grades", "brief-weights", "brief-eligible", "brief-basis-live"];
    if (!live()) { frames.forEach((_, id) => dropFrame(id)); swaps.clear(); replace("brief-live", empty(state.error || "Opening the simulated book…")); slots.forEach((id) => replace(id)); return; }
    landing.flushEntrances();
    const grow = !briefDrawn; briefDrawn = true;
    section("hero", () => briefHero(state.data, grow)); section("numbers", () => briefNumbers(state.data, grow));
    briefProblems(state.data, grow); section("method", () => briefMethod(state.data, grow));
  }
  function briefHero(data, grow) {
    const kpis = data.kpis;
    /* A model's basis is worked out from the two prices printed under its name, so a reader can reproduce every percentage. */
    const rows = data.models.map((entry) => {
      const low = lowestPrice(entry); const best = entry.best; const cheap = entry.cheapest;
      const lowShown = landing.printed(low); const bestShown = best ? landing.printed(best.risk_adjusted) : NaN;
      const ranked = Boolean(best) && Boolean(cheap) && entry.basis !== null && lowShown > 0 && Number.isFinite(bestShown);
      const basis = ranked ? Math.round((bestShown / lowShown - 1) * 1000) / 1000 : null; const text = ranked ? pct(basis, 1, true) : "";
      return {
        key: entry.model, label: entry.model, sub: ranked ? money(low) + " → " + money(best.risk_adjusted) : low !== null ? money(low) : "No quotes",
        value: ranked ? basis * 100 : 0, text, note: ranked ? "" : "No eligible seller",
        tip: ranked ? { head: text + " basis", lines: ["Lowest quote " + money(low) + " · " + gradeName(cheap.grade), "Best all-in " + money(best.risk_adjusted) + " · " + gradeName(best.grade)] } : { head: "No eligible seller", lines: low !== null ? ["Lowest quote " + money(low) + (cheap ? " · " + gradeName(cheap.grade) : "")] : [] },
        aria: ranked ? entry.model + ": lowest quote " + cheap.ref + " (" + cheap.provider + ", " + gradeInline(cheap.grade) + ") " + money(low) + "; best eligible quote " + best.ref + " (" + best.provider + ", " + gradeInline(best.grade) + ") " + money(best.risk_adjusted) + " all-in; basis " + text : entry.model + ": no eligible seller" + (low !== null ? "; lowest quote " + money(low) : "; no quotes"),
        cells: [entry.model, low !== null ? money(low) : "No quotes", ranked ? money(best.risk_adjusted) : "No eligible seller", ranked ? text : "None"],
      };
    });
    if (kpis.basis !== null && kpis.basis !== undefined) {
      const text = pct(kpis.basis, 1, true);
      rows.push({ key: "all", ref: true, label: "All models", sub: "Weighted by GPUs", value: Math.round(kpis.basis * 1000) / 10, text, tip: { head: text + " basis", lines: ["All models, weighted by GPUs"] }, aria: "All models, weighted by GPUs: basis " + text, cells: ["All models, weighted by GPUs", "Not applicable", "Not applicable", text] });
    }
    const widest = rows.filter((row) => row.value > 0 && !row.ref).sort((a, b) => b.value - a.value)[0];
    const frame = slotFrame("brief-live", ["chart", "caption"]);
    landing.bars(frame.chart, {
      rows, axis: axisPercent(), maxWidth: 600, pitch: 56, grow, resetKey: String(data.meta.epoch), title: "Basis by GPU model",
      table: { head: ["GPU model", "Lowest quote, dollars per GPU-hour", "Best eligible all-in, dollars per GPU-hour", "Basis, percent above the lowest quote"] },
      description: "Basis by GPU model. " + (widest ? widest.label + " has the widest gap: its best eligible all-in cost is " + widest.text.replace("+", "") + " above the lowest quote." : "No model has an eligible seller yet."),
    });
    setText(frame.caption, "Under each model: the lowest quote → the best eligible all-in cost, per GPU-hour; basis is the second price over the first, less one. " + int(kpis.live_quotes) + " live quotes from " + kpis.providers_quoting + " providers; simulated, refreshed every few seconds.");
  }
  function briefNumbers(data, grow) {
    const k = data.kpis; const s = data.series;
    const items = [
      { label: "Live quotes", value: int(k.live_quotes), sub: "from " + k.providers_quoting + " providers", spark: s.live },
      { label: "GPUs on offer", value: compact(k.gpus), sub: "across " + k.models + " models", spark: s.gpus },
      { label: "Eligible quotes", value: k.eligible_share === null ? "—" : pct(k.eligible_share, 0), sub: int(k.eligible_quotes) + " clear the bar", spark: s.eligible_share },
      { label: "Market basis", value: k.basis === null ? "—" : pct(k.basis, 1, true), sub: "best eligible over lowest quote", spark: s.basis },
    ];
    const nodes = items.map((item) => h("div", grow ? "bf-number bf-in" : "bf-number", h("span", "bf-number-label", item.label), h("strong", "bf-number-value", item.value), h("span", "bf-number-sub", item.sub), item.spark ? landing.sparkline(item.spark, { width: 120, height: 32 }) : null));
    if (refresh("brief-facts", nodes, JSON.stringify(items.map((item) => item.spark))) && grow) landing.afterEntrance(() => nodes.forEach((node) => node.classList.remove("bf-in")));
  }
  /* One model's lowest quote whose hidden costs are worth showing. The pick sticks while it stays the lowest quote of its
     model, so the figure does not jump between quotes as the book ticks. */
  let briefPick = "";
  const briefUplift = (quote) => (quote.risk_adjusted === null ? 0 : quote.risk_adjusted / Number(quote.price) - 1);
  function briefExample(data) {
    const picks = data.models.filter((entry) => entry.cheapest).map((entry) => ({ entry, quote: data.quotes.find((q) => q.id === entry.cheapest.id) })).filter((pick) => pick.quote && pick.quote.risk_adjusted !== null);
    const kept = picks.find((pick) => pick.quote.id === briefPick && briefUplift(pick.quote) >= 0.05);
    const chosen = kept || picks.slice().sort((a, b) => briefUplift(b.quote) - briefUplift(a.quote) || b.entry.gpus - a.entry.gpus)[0] || null;
    briefPick = chosen ? chosen.quote.id : ""; return chosen;
  }
  function briefProblems(data, grow) {
    const kpis = data.kpis;
    // 1. Terms left blank
    section("terms", () => {
      const heavy = data.completeness.filter((c) => c.missing >= 4).reduce((sum, c) => sum + c.quotes, 0);
      const gaps = Object.entries(data.field_gaps).sort((a, b) => b[1] - a[1]).slice(0, 5); const total = Math.max(1, kpis.live_quotes);
      refresh("brief-fact-gaps", statLine(pct(heavy / total, 0), "of live quotes leave four or more of ten key terms blank."));
      const rows = gaps.map(([field, count]) => {
        const name = FIELD_NAMES[field] || field; const { text, value } = share(count / total);
        return { key: field, label: name, value, text, tip: { head: text, lines: [count + " of " + total + " quotes leave it blank"] }, aria: name + ": " + count + " of " + total + " current quotes leave it blank, " + text, cells: [name, count + " of " + total, text] };
      });
      const frame = slotFrame("brief-gaps", ["chart"]);
      landing.bars(frame.chart, {
        rows, axis: axisPercent(), maxWidth: 520, pitch: 40, grow, resetKey: String(data.meta.epoch), title: "Current quotes that leave each term blank",
        table: { head: ["Term", "Current quotes that leave it blank", "Share of current quotes"] },
        description: "Share of current quotes that leave each term blank." + (rows[0] ? " " + rows[0].label + " is omitted most often, in " + rows[0].text + " of quotes." : ""),
      });
    });
    // 2. What the headline price leaves out
    section("cost", () => {
      const example = briefExample(data);
      if (!example) { clearSlot("brief-anatomy", empty("No comparison available yet.")); refresh("brief-fact-cost", statLine("—", "No quote with a stated term to price yet.")); return; }
      const quote = example.quote;
      /* Every figure is the number printed, to the thousandth, and the all-in total is the sum of the three printed parts. */
      const price = landing.printed(quote.price); const financing = landing.printed(quote.financing || 0); const exposure = landing.printed(quote.exposure || 0);
      const allin = Math.round((price + financing + exposure) * 1000) / 1000; const uplift = price > 0 ? allin / price - 1 : 0;
      refresh("brief-fact-cost", statLine(pct(uplift, 0, true), ["Quote " + quote.ref + ", the lowest " + example.entry.model + " offer, asks " + money(price) + " ", h("span", "bf-nowrap", "per GPU-hour"), ". All-in it costs " + money(allin) + "."]));
      const frame = slotFrame("brief-anatomy", ["chart", "split", "caption"]);
      const parts = [{ value: price, tone: "quoted" }, { value: financing, tone: "financing", above: "+" + money(financing) }, { value: exposure, tone: "loss" }];
      landing.bars(frame.chart, {
        rows: [
          { key: "quoted", label: "Quoted", parts: [parts[0]], text: money(price), tip: { head: money(price), lines: ["Quoted price per GPU-hour"] }, aria: "Quoted price " + money(price) + " per GPU-hour", cells: ["Quoted", money(price), "Not included", "Not included", money(price)] },
          { key: "allin", label: "All-in", parts, text: money(allin), tip: { head: money(allin) + " all-in", lines: [money(price) + " quoted price", "+ " + money(financing) + " financing", "+ " + money(exposure) + " expected loss"] }, aria: "All-in " + money(allin) + " per GPU-hour: " + money(price) + " quoted, plus " + money(financing) + " financing, plus " + money(exposure) + " expected loss", cells: ["All-in", money(price), money(financing), money(exposure), money(allin)] },
        ],
        axis: { floor: 1, headroom: 1, format: (value) => "$" + value }, maxWidth: 520, pitch: 52, grow, resetKey: data.meta.epoch + ":" + quote.id, title: "One current quote, per GPU-hour",
        table: { head: ["Bar", "Quoted price", "Financing", "Expected loss", "Total per GPU-hour"] },
        description: "Quote " + quote.ref + " per GPU-hour: " + money(allin) + " all-in, which is " + money(price) + " quoted plus " + money(financing) + " financing and " + money(exposure) + " expected loss.",
      });
      const term = (name, value, tone, sign) => { const op = sign ? h("span", "bf-op", sign) : null; if (op) op.setAttribute("aria-hidden", "true"); return [h("dt", "", tone ? h("span", "swatch bf-tone-" + tone) : null, name), h("dd", "", op, money(value))]; };
      setKids(frame.split, [term("Quoted price", price, "quoted"), term("Financing", financing, "financing", "+"), term("Expected loss", exposure, "loss", "+"), term("All-in", allin, "", "=")]);
      setText(frame.caption, quote.ref + " · " + quote.provider + " · " + gradeName(quote.grade));
    });
    // 3. The lowest quotes come from the weakest sellers
    section("grades", () => {
      const weak = data.models.filter((m) => m.cheapest && ["C", "D"].includes(m.cheapest.grade)).length;
      const below = data.models.filter((m) => m.cheapest && m.median).map((m) => ({ entry: m, gap: Math.max(0, 1 - lowestPrice(m) / m.median) }));
      refresh("brief-fact-grades", statLine(weak + " of " + data.models.length, "GPU models have a grade C or D seller as the lowest quote."));
      const rows = below.map(({ entry, gap }) => {
        const cheap = entry.cheapest; const { text, value } = share(gap);
        return { key: entry.model, label: entry.model, chip: cheap.grade, tone: "neutral", value, text, tip: { head: text + " below the median", lines: [cheap.ref + " · " + gradeName(cheap.grade), money(lowestPrice(entry)) + " against " + money(entry.median)] },
          aria: entry.model + ": the lowest quote " + cheap.ref + " (" + cheap.provider + ", " + gradeInline(cheap.grade) + ") " + money(lowestPrice(entry)) + " is " + text + " below the model median " + money(entry.median),
          cells: [entry.model, cheap.grade, money(lowestPrice(entry)), money(entry.median), text] };
      });
      const frame = slotFrame("brief-grades", ["chart", "legend"]); const top = rows.slice().sort((a, b) => b.value - a.value)[0];
      landing.bars(frame.chart, {
        rows, axis: axisPercent(), maxWidth: 520, pitch: 48, grow, resetKey: String(data.meta.epoch), title: "Lowest quote, below the model median",
        table: { head: ["GPU model", "Seller grade of the lowest quote", "Lowest quote, dollars per GPU-hour", "Model median, dollars per GPU-hour", "Below the model median"] },
        description: "Lowest quote for each GPU model, as a percentage below the model median. " + (top ? top.label + " sits furthest below, at " + top.text + ", with " + gradeInline(top.chip) + " seller." : "No model has a median yet."),
      });
      const present = [...GRADES, "U"].filter((grade) => below.some(({ entry }) => entry.cheapest.grade === grade));
      setKids(frame.legend, present.length ? charts.legend(present.map((grade) => ({ label: gradeName(grade), className: gradeClass(grade) }))) : null);
    });
  }
  function briefMethod(data, grow) {
    const kpis = data.kpis;
    section("weights", () => {
      const weights = Object.entries(data.assumptions.weights).sort((a, b) => b[1] - a[1]);
      const rows = weights.map(([key, weight]) => { const name = CATEGORIES[key] || key; const { text, value } = share(weight); return { key, label: name, value, text, tip: { head: text, lines: ["of the seller scorecard"] }, aria: name + ": " + text + " of the seller scorecard", cells: [name, text] }; });
      landing.bars(slotFrame("brief-weights", ["chart"]).chart, {
        rows, axis: axisPercent(10, 30, 1), maxWidth: 440, pitch: 34, grow, resetKey: "weights", title: "Scorecard weights",
        table: { head: ["Category", "Weight in the seller scorecard"] },
        description: "Scorecard weights by category." + (rows[0] ? " " + rows[0].label + " carries the most weight, at " + rows[0].text + "." : ""),
      });
    });
    refresh("brief-eligible", statLine(int(kpis.eligible_quotes) + " of " + int(kpis.live_quotes), "live quotes clear the bar right now."));
    refresh("brief-basis-live", kpis.basis === null ? [] : [h("span", "", h("strong", "", pct(kpis.basis, 1, true)), " across today's book, weighted by GPUs.")]);
  }

  /* Motion. The Brief plays its entrance once, on first load; after the person has left it, coming back is a plain fade.
     Blocks below the fold rise in as they scroll into view (siblings follow in order, in CSS). Without IntersectionObserver, or when
     motion is reduced, nothing is hidden and the page simply shows. A block that is already above the screen (a reload part way
     down, a jump to an anchor) is shown at once rather than left hidden. */
  const REVEAL = ["brief-problem-head", "brief-problem-1", "brief-problem-2", "brief-problem-3", "brief-how-head", "brief-steps", "brief-basis", "brief-close"];
  const reducedMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches === true;
  function armReveal() {
    if (reducedMotion() || typeof window.IntersectionObserver !== "function") return;
    const watcher = new window.IntersectionObserver((entries) => entries.forEach((entry) => {
      const passed = entry.isIntersecting !== true && Number(entry.boundingClientRect?.bottom) < 0;
      if (entry.isIntersecting || passed) { entry.target.classList.add("rv-in"); watcher.unobserve(entry.target); }
    }), { threshold: 0.12, rootMargin: "0px 0px -6% 0px" });
    byId("brief-view").classList.add("rv-on"); REVEAL.forEach((id) => watcher.observe(byId(id)));
  }
  /* Leaving the landing page: the page fades out for LEAVE_MS, then the app opens (and fades in, in CSS). With reduced motion, with
     no timers, in a hidden tab or when a second click arrives, it switches at once, so a click is never lost or left waiting. */
  const LEAVE_MS = 180;
  const LEAVING = ["lp-header", "brief-view", "lp-footer"];
  let leaving = false;
  const clearLeaving = () => { leaving = false; LEAVING.forEach((id) => byId(id).classList.remove("lp-leaving")); };
  function openApp(view) {
    const wait = window.setTimeout;
    if (leaving || reducedMotion() || typeof wait !== "function" || document.hidden === true) { clearLeaving(); showView(view); return; }
    leaving = true; LEAVING.forEach((id) => byId(id).classList.add("lp-leaving"));
    wait.call(window, () => { if (leaving) { clearLeaving(); showView(view); } }, LEAVE_MS);
  }
  D.host.onView((name) => { clearLeaving(); if (name !== "brief") byId("brief-view").classList.add("bf-entered"); });
  [["lp-open", "desk"], ["brief-open-desk", "desk"], ["brief-open-desk-end", "desk"], ["brief-open-quotes", "quotes"]].forEach(([id, view]) => byId(id).addEventListener("click", () => openApp(view)));
  function goTo(sectionId, titleId) {
    byId(sectionId).scrollIntoView({ behavior: reducedMotion() ? "auto" : "smooth", block: "start" }); byId(titleId).focus({ preventScroll: true });
  }
  [["brief-see-problem", "brief-problem", "brief-problem-title"], ["lp-go-problem", "brief-problem", "brief-problem-title"], ["lp-go-how", "brief-how", "brief-how-title"]]
    .forEach(([button, section, title]) => byId(button).addEventListener("click", () => goTo(section, title)));
  armReveal();
  D.register("brief", { render: renderBrief, resize: true });
})();
