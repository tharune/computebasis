/* The landing view: the Brief. A one-page argument, drawn from the live simulated book. */
(() => {
  "use strict";
  const D = window.ComputeDemo; if (!D) return;
  const { charts, state, h, int, pct, compact, gradeClass, replace, empty, live, lowestPrice, GRADES, CATEGORIES, byId } = D;
  const showView = D.host.showView;

  /* ---- Brief ---- */
  /* The landing view. Its charts come from LandingCharts (landing-charts.js), which draws each one at the width it is shown at and
     keeps it alive between polls; colour still arrives only through CSS classes, keeping both themes and the CSP intact. A chart
     that fails to draw is logged and left as it was: it never stops the poll or blanks the page. Every figure and sentence below is
     worked out from the book on screen (LandingData holds the derivations), so none of it can go stale when a scenario runs. */
  const landing = window.LandingCharts || { bars: () => null, release: () => {}, sparkline: () => null, money: (v) => "$" + Number(v).toFixed(3), printed: Number, afterEntrance: () => {}, flushEntrances: () => {} };
  const Data = window.LandingData || {};
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
  const plural = (n, one, many = one + "s") => (n === 1 ? one : many);
  const count = (value) => (Number.isFinite(value) ? int(value) : "—");
  const lowerFirst = (text) => (/^[A-Z][a-z]/.test(text) ? text.charAt(0).toLowerCase() + text.slice(1) : text);
  /* "A", "A and B", "A, B and C" */
  const andList = (items) => (items.length < 2 ? items.join("") : items.slice(0, -1).join(", ") + " and " + items[items.length - 1]);
  const signed = (value) => (value > 0 ? "+" : value < 0 ? "−" : "") + Math.abs(value).toFixed(1) + "%";
  /* The rows that tie for the top of a ranked list, so a sentence never names one of two equals as "the most". */
  const leaders = (rows) => rows.filter((row) => row.value === (rows[0] ? rows[0].value : null));

  function renderBrief() {
    const slots = ["brief-facts", "brief-fact-gaps", "brief-gaps", "brief-fact-cost", "brief-anatomy", "brief-fact-grades", "brief-grades", "brief-weights", "brief-odds", "brief-eligible", "brief-basis-live"];
    if (!live()) {
      frames.forEach((_, id) => dropFrame(id)); swaps.clear();
      replace("brief-live", empty(state.error ? "The simulated book is not loading. " + state.error : "Opening the simulated book…")); slots.forEach((id) => replace(id)); return;
    }
    landing.flushEntrances();
    const grow = !briefDrawn; briefDrawn = true;
    section("hero", () => briefHero(state.data, grow)); section("numbers", () => briefNumbers(state.data, grow));
    briefProblems(state.data, grow); briefMethod(state.data, grow);
  }
  function briefHero(data, grow) {
    const kpis = data.kpis;
    /* A model's basis is worked out from the two prices printed under its name, so a reader can reproduce every percentage. */
    const rows = data.models.map((entry) => {
      const low = lowestPrice(entry); const best = entry.best; const cheap = entry.cheapest;
      const lowShown = landing.printed(low); const bestShown = best ? landing.printed(best.risk_adjusted) : NaN;
      const ranked = Boolean(best) && Boolean(cheap) && entry.basis !== null && lowShown > 0 && Number.isFinite(bestShown);
      const basis = ranked ? Math.round((bestShown / lowShown - 1) * 1000) / 1000 : null; const text = ranked ? pct(basis, 1, true) : "";
      const none = low === null ? "No live quotes" : "No eligible seller";
      return {
        key: entry.model, label: entry.model, sub: ranked ? money(low) + " → " + money(best.risk_adjusted) : low !== null ? money(low) : "No quotes",
        value: ranked ? basis * 100 : 0, text, note: ranked ? "" : none,
        tip: ranked ? { head: text + " basis", lines: ["Lowest quote " + money(low) + " · " + gradeName(cheap.grade), "Best all-in " + money(best.risk_adjusted) + " · " + gradeName(best.grade)] } : { head: none, lines: low !== null ? ["Lowest quote " + money(low) + (cheap ? " · " + gradeName(cheap.grade) : "")] : [] },
        aria: ranked ? entry.model + ": lowest quote " + cheap.ref + " (" + cheap.provider + ", " + gradeInline(cheap.grade) + ") " + money(low) + "; best eligible quote " + best.ref + " (" + best.provider + ", " + gradeInline(best.grade) + ") " + money(best.risk_adjusted) + " all-in; basis " + text : entry.model + ": " + none.toLowerCase() + (low !== null ? "; lowest quote " + money(low) : ""),
        cells: [entry.model, low !== null ? money(low) : "No quotes", ranked ? money(best.risk_adjusted) : "No eligible seller", ranked ? text : "None"],
      };
    });
    const weighted = Number.isFinite(kpis.basis);
    if (weighted) {
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
    const quoted = Number.isFinite(kpis.live_quotes) ? " " + int(kpis.live_quotes) + " live " + plural(kpis.live_quotes, "quote") + (Number.isFinite(kpis.providers_quoting) ? " from " + int(kpis.providers_quoting) + " " + plural(kpis.providers_quoting, "seller") : "") + "." : "";
    setText(frame.caption, "Under each model: its lowest live quote, then its best eligible all-in cost, in dollars per GPU-hour. Basis is the second price over the first, less one." + (weighted ? " The last row weights each model by the GPUs quoted." : "") + quoted);
  }
  function briefNumbers(data, grow) {
    const k = data.kpis; const s = data.series || {}; const lowest = Data.lowestQuotes ? Data.lowestQuotes(data) : { priced: 0, ineligible: 0 };
    const pass = Data.share ? Data.share(k.eligible_quotes, k.live_quotes) : null;
    const items = [
      { label: "Live quotes", value: count(k.live_quotes), sub: Number.isFinite(k.providers_quoting) ? "from " + int(k.providers_quoting) + " " + plural(k.providers_quoting, "seller") : "", spark: s.live },
      { label: "GPUs quoted", value: Number.isFinite(k.gpus) ? compact(k.gpus) : "—", sub: Number.isFinite(k.models) ? "across " + int(k.models) + " " + plural(k.models, "model") : "", spark: s.gpus },
      { label: "Eligible quotes", value: pass ? pass.text : "—", sub: pass ? int(k.eligible_quotes) + " of " + int(k.live_quotes) + " pass every check" : k.live_quotes === 0 ? "No live quotes" : "", spark: s.eligible_share },
      { label: "Lowest quote ineligible", value: lowest.priced ? int(lowest.ineligible) + " of " + int(lowest.priced) : "—", sub: lowest.priced ? plural(lowest.priced, "GPU model") : "No priced quotes", spark: null },
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
    // 1. Terms left blank, over every quote in the book (the server counts blanks over all of them, live or not)
    section("terms", () => {
      const gaps = Data.termGaps ? Data.termGaps(data) : null;
      if (!gaps) { refresh("brief-fact-gaps", statLine("—", "The book holds no quotes yet.")); clearSlot("brief-gaps", empty("No quotes to count.")); return; }
      const book = int(gaps.total) + " " + plural(gaps.total, "quote") + " in the book";
      const blank = Data.share(gaps.quotesWithBlank, gaps.total);
      refresh("brief-fact-gaps", statLine(blank.text, gaps.quotesWithBlank
        ? "of the " + book + " (" + int(gaps.quotesWithBlank) + ") leave at least one key term blank." + (gaps.unrated ? " " + int(gaps.unrated) + " more come from a seller with no grade." : "")
        : "of the " + book + " leave a key term blank." + (gaps.unrated ? " " + int(gaps.unrated) + " come from a seller with no grade." : "")));
      const rows = gaps.terms.slice(0, 5).map((term) => {
        const { text, value } = Data.share(term.count, gaps.total);
        return { key: term.field, label: term.name, value, text, tip: { head: text, lines: [int(term.count) + " of " + int(gaps.total) + " quotes leave it blank"] }, aria: term.name + ": " + int(term.count) + " of " + int(gaps.total) + " quotes in the book leave it blank, " + text, cells: [term.name, int(term.count) + " of " + int(gaps.total), text] };
      });
      const top = leaders(rows);
      const frame = slotFrame("brief-gaps", ["chart"]);
      landing.bars(frame.chart, {
        rows, axis: axisPercent(5, 20, 1.1), maxWidth: 520, pitch: 40, grow, resetKey: String(data.meta.epoch), title: "Quotes that leave each term blank", empty: "No quote in the book leaves a key term blank.",
        table: { head: ["Term", "Quotes that leave it blank", "Share of the quotes in the book"] },
        description: "Share of the " + book + " that leave each key term blank." + (top.length ? " " + andList(top.map((row, i) => (i ? lowerFirst(row.label) : row.label))) + (top.length > 1 ? " are" : " is") + " left blank most often, " + (top.length > 1 ? "each " : "") + "in " + top[0].text + " of quotes." : " No quote leaves a key term blank."),
      });
    });
    // 2. What the headline price leaves out
    section("cost", () => {
      const example = briefExample(data);
      if (!example) { clearSlot("brief-anatomy", empty("No comparison available yet.")); refresh("brief-fact-cost", statLine("—", "No live quote has a price and a stated term to cost yet.")); return; }
      const quote = example.quote;
      /* Every figure is the number printed, to the thousandth, and the all-in total is the sum of the three printed parts. */
      const price = landing.printed(quote.price); const financing = landing.printed(quote.financing || 0); const exposure = landing.printed(quote.exposure || 0);
      const allin = Math.round((price + financing + exposure) * 1000) / 1000; const uplift = price > 0 ? allin / price - 1 : 0;
      refresh("brief-fact-cost", statLine(pct(uplift, uplift < 0.095 ? 1 : 0, true), ["Quote " + quote.ref + ", the lowest " + example.entry.model + " offer, asks " + money(price) + " ", h("span", "bf-nowrap", "per GPU-hour"), ". All-in it costs " + money(allin) + "."]));
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
      setText(frame.caption, briefExampleNote(data, quote));
    });
    // 3. The lowest quotes come from sellers of any grade
    section("grades", () => {
      const lowest = Data.lowestQuotes(data);
      const weak = lowest.weak;
      if (lowest.priced) refresh("brief-fact-grades", statLine(int(weak) + " of " + int(lowest.priced), plural(lowest.priced, "GPU model") + " " + (lowest.priced === 1 ? "has" : "have") + " a grade C or D seller as the lowest quote."));
      else refresh("brief-fact-grades", statLine("—", "No GPU model has a priced live quote yet."));
      const below = data.models.filter((m) => m.cheapest && m.median).map((m) => ({ entry: m, gap: Math.max(0, 1 - lowestPrice(m) / m.median) })).filter(({ gap }) => Number.isFinite(gap));
      const rows = below.map(({ entry, gap }) => {
        const cheap = entry.cheapest; const { text, value } = Data.share(gap, 1);
        return { key: entry.model, label: entry.model, chip: cheap.grade, tone: "neutral", value, text, tip: { head: text + " below the median", lines: [cheap.ref + " · " + gradeName(cheap.grade), money(lowestPrice(entry)) + " against " + money(entry.median)] },
          aria: entry.model + ": the lowest quote " + cheap.ref + " (" + cheap.provider + ", " + gradeInline(cheap.grade) + ") " + money(lowestPrice(entry)) + " is " + text + " below the model median " + money(entry.median),
          cells: [entry.model, gradeName(cheap.grade), money(lowestPrice(entry)), money(entry.median), text] };
      });
      const frame = slotFrame("brief-grades", ["chart", "legend"]); const top = rows.slice().sort((a, b) => b.value - a.value)[0];
      landing.bars(frame.chart, {
        rows, axis: axisPercent(), maxWidth: 520, pitch: 48, grow, resetKey: String(data.meta.epoch), title: "Lowest quote, below the model median", empty: "No GPU model has a median price yet.",
        table: { head: ["GPU model", "Seller grade of the lowest quote", "Lowest quote, dollars per GPU-hour", "Model median, dollars per GPU-hour", "Below the model median"] },
        description: "Lowest quote for each GPU model, as a percentage below the model median. " + (top ? top.label + " sits furthest below, at " + top.text + ", with " + gradeInline(top.chip) + " seller." : "No model has a median yet."),
      });
      const present = [...GRADES, "U"].filter((grade) => below.some(({ entry }) => entry.cheapest.grade === grade));
      setKids(frame.legend, present.length ? charts.legend(present.map((grade) => ({ label: gradeName(grade), className: gradeClass(grade) }))) : null);
    });
  }
  /* The line under the example: who sells it, whether it is eligible, and what the two added costs are made of. */
  function briefExampleNote(data, quote) {
    const apr = data.assumptions.deposit_apr; const deposit = quote.down_payment; const months = quote.months; const fail = quote.failure_probability;
    const status = quote.eligible ? "eligible" : quote.reason_codes.length ? "not eligible: " + quote.reason_codes.map((code) => Data.reasonName(code)).join(", ") : "not eligible";
    const lines = [[quote.ref, quote.provider, gradeName(quote.grade), status].join(" · ") + "."];
    if (Number.isFinite(deposit) && Number.isFinite(apr) && Number.isFinite(months)) {
      lines.push(deposit > 0 ? "Financing: " + pct(apr, 1) + " a year on the " + pct(deposit, 0) + " down payment, for " + int(months) + " " + plural(months, "month") + "." : "Financing: none, because no down payment is asked.");
    }
    if (Number.isFinite(fail)) lines.push("Expected loss: the " + pct(fail, 1) + " chance that the seller fails during the term, times what a failure would cost the buyer.");
    return lines.join(" ");
  }
  function briefMethod(data, grow) {
    section("weights", () => {
      const weights = Object.entries(data.assumptions.weights).filter(([, weight]) => Number.isFinite(weight)).sort((a, b) => b[1] - a[1]);
      const rows = weights.map(([key, weight]) => { const name = CATEGORIES[key] || Data.termName(key); const { text, value } = Data.share(weight, 1); return { key, label: name, value, text, tip: { head: text, lines: ["of the seller scorecard"] }, aria: name + ": " + text + " of the seller scorecard", cells: [name, text] }; });
      const top = leaders(rows);
      landing.bars(slotFrame("brief-weights", ["chart"]).chart, {
        rows, axis: axisPercent(10, 30, 1), maxWidth: 440, pitch: 34, grow, resetKey: "weights", title: "Scorecard weights", empty: "No scorecard weights in the book.",
        table: { head: ["Category", "Weight in the seller scorecard"] },
        description: "Scorecard weights by category." + (top.length ? " " + andList(top.map((row) => row.label)) + (top.length > 1 ? " each carry" : " carries") + " the most weight, at " + top[0].text + "." : ""),
      });
    });
    section("odds", () => {
      const grades = data.assumptions.grades.filter((entry) => GRADES.includes(entry.grade) && Number.isFinite(entry.annual_failure)).sort((a, b) => GRADES.indexOf(a.grade) - GRADES.indexOf(b.grade));
      const bands = new Map(data.assumptions.grades.filter((entry) => Number.isFinite(entry.minimum)).sort((a, b) => b.minimum - a.minimum).map((entry, index, all) => [entry.grade, index === 0 ? "score " + entry.minimum + " and above" : entry.minimum > 0 ? "score " + entry.minimum + " up to " + all[index - 1].minimum : "score below " + all[index - 1].minimum]));
      const rows = grades.map((entry) => {
        const text = pct(entry.annual_failure, 1); const band = bands.get(entry.grade) || "";
        return { key: entry.grade, label: gradeName(entry.grade), sub: band, value: entry.annual_failure * 100, text, tip: { head: text + " a year", lines: [gradeName(entry.grade) + (band ? " · " + band : "")] },
          aria: gradeName(entry.grade) + (band ? " (" + band + ")" : "") + ": a " + text + " chance of failing in a year", cells: [gradeName(entry.grade), band || "Not stated", text] };
      });
      const recovery = data.assumptions.recovery_fraction;
      const frame = slotFrame("brief-odds", ["chart", "caption"]);
      landing.bars(frame.chart, {
        rows, axis: axisPercent(5, 20, 1.1), maxWidth: 440, pitch: 40, grow, resetKey: String(data.meta.epoch), title: "Chance a seller fails in a year, by grade", empty: "No failure odds in the book.",
        table: { head: ["Seller grade", "Score band", "Chance of failing in a year"] },
        description: "Chance that a seller fails in a year, by grade." + (rows.length > 1 ? " " + rows[0].label + " is " + rows[0].text + " and " + rows[rows.length - 1].label.toLowerCase() + " is " + rows[rows.length - 1].text + "." : ""),
      });
      setText(frame.caption, rows.length ? "The chance that a seller of each grade fails in a year." + (Number.isFinite(recovery) ? " After a failure the buyer recovers " + pct(recovery, 0) + " of the down payment." : "") : "");
    });
    section("eligible", () => {
      const e = Data.eligibility(data);
      if (!e) { refresh("brief-eligible", statLine("—", "The book does not say how many quotes are live.")); return; }
      if (!e.live) { refresh("brief-eligible", statLine("—", "There are no live quotes to check.")); return; }
      let text = "live " + plural(e.live, "quote") + " " + (e.eligible === 1 ? "passes" : "pass") + " every check.";
      if (e.failing > 0 && e.known && e.reasons.length) {
        text += " The other " + int(e.failing) + " " + (e.failing === 1 ? "fails" : "fail") + " at least one: " + e.reasons.map((reason) => reason.name + " (" + int(reason.count) + ")").join(", ") + ".";
        if (e.overlap) text += " A quote can fail more than one.";
        if (e.dominant && e.dominant.code === "contract_start_precedes_as_of" && e.dominantMost) text += " Most fail on the start date, which says more about how the simulation dates its quotes than about the sellers.";
      }
      refresh("brief-eligible", statLine(int(e.eligible) + " of " + int(e.live), text));
    });
    section("basis", () => briefBasis(data, grow));
  }
  /* Where the market basis comes from: the lowest quotes failing the eligibility screen, then what financing and expected loss add. */
  function briefBasis(data, grow) {
    const parts = Data.basisBreakdown(data);
    if (!parts) { clearSlot("brief-basis-live", empty("No model has an eligible quote yet, so there is no basis to explain.")); return; }
    const detail = parts.price !== null;
    const sources = detail
      ? [["screen", parts.screen], ["financing", parts.financing], ["loss", parts.loss], ["price", parts.price]]
      : [["screen", parts.screen], ["costing", parts.costing]];
    const shown = Data.apportion(sources.map(([, value]) => value * 100), 1); const total = shown.reduce((a, b) => a + b, 0);
    const value = Object.fromEntries(sources.map(([key], index) => [key, shown[index]]));
    const text = (key) => signed(value[key]);
    const costing = detail ? value.financing + value.loss + value.price : value.costing;
    const row = (key, label, tone, tip, line, explain) => ({ key, label, parts: [{ value: value[key], tone }], text: text(key), tip: { head: text(key) + " of the basis", lines: tip }, aria: label + ": " + text(key) + ". " + line, cells: [label, text(key), explain] });
    const rows = [
      row("screen", "Lowest quotes ineligible", "quoted", ["Cheapest eligible quote against", "the lowest quote, in each model"], "Where the lowest quote fails a check, the cheapest eligible quote costs more.", "The cheapest eligible quote against the lowest quote"),
    ].concat(detail ? [
      row("financing", "Financing", "financing", ["Financing on the down payment", "of the best all-in quote"], "Financing on the best eligible quote's down payment.", "Financing on the best quote's down payment"),
      row("loss", "Expected loss", "loss", ["Expected loss from seller failure", "on the best all-in quote"], "Expected loss from seller failure on the best eligible quote.", "Expected loss on the best quote"),
      row("price", "Pricier but cheaper all-in", "neutral", ["Where the best all-in quote is priced", "above the cheapest eligible one"], "Where the quote with the lowest all-in cost is priced above the cheapest eligible quote, the difference.", "Price difference to the cheapest eligible quote"),
    ] : [
      row("costing", "Financing and expected loss", "financing", ["Best eligible all-in cost against", "the cheapest eligible quoted price"], "Best eligible all-in cost against the cheapest eligible quote's price.", "Best all-in cost against the cheapest eligible price"),
    ]);
    rows.push({ key: "basis", ref: true, label: "Market basis", sub: "Weighted by GPUs", parts: [{ value: total, tone: "accent" }], text: signed(total), tip: { head: signed(total) + " basis", lines: ["Best eligible all-in cost over", "the lowest quote"] }, aria: "Market basis " + signed(total) + ": the sum of the rows above", cells: ["Market basis", signed(total), "The best eligible all-in cost against the lowest quote"] });
    const frame = slotFrame("brief-basis-live", ["chart", "caption"]);
    landing.bars(frame.chart, {
      rows, axis: axisPercent(2, 6, 1.1), maxWidth: 560, pitch: 44, grow, resetKey: String(data.meta.epoch), title: "Where the market basis comes from",
      table: { head: ["Source", "Added to the basis", "What it is"] },
      description: "Market basis " + signed(total) + ", made of " + rows.slice(0, -1).map((item) => item.label.toLowerCase() + " " + item.text).join(", ") + ".",
    });
    const lead = "The best eligible all-in cost is " + total.toFixed(1) + "% above the lowest quote. ";
    const split = value.screen > 0 && costing > 0
      ? value.screen.toFixed(1) + " points of that come from the lowest quotes being ineligible; the other " + costing.toFixed(1) + " points are " + (detail ? "financing, expected loss and, where the quote with the lowest all-in cost is priced above the cheapest eligible one, that price difference." : "what financing and expected loss add.")
      : value.screen > 0 ? "All of it comes from the lowest quotes being ineligible." : "All of it is what financing and expected loss add" + (detail ? ", with any price difference to the cheapest eligible quote." : ".");
    setText(frame.caption, lead + split + " Models are weighted by the GPUs quoted" + (parts.models < parts.modelsTotal ? "; " + int(parts.models) + " of " + int(parts.modelsTotal) + " models have an eligible quote." : "."));
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
  byId("lp-top").addEventListener("click", () => { window.scrollTo?.({ top: 0, left: 0, behavior: reducedMotion() ? "auto" : "smooth" }); byId("brief-title").focus({ preventScroll: true }); });
  armReveal();
  D.register("brief", { render: renderBrief, resize: true });
})();
