/* Figures the landing page derives from one book snapshot. Pure functions, no DOM, so they can be checked against the server's own numbers. */
(function () {
  "use strict";
  const finite = (value) => typeof value === "number" && Number.isFinite(value);

  /* Where the market basis comes from. The basis is how much more the best eligible all-in cost is than the lowest quoted price,
     weighted by the GPUs on offer in each model. It has two sources, and the page should say which is which:
       screen   what leaving out the ineligible quotes does: the cheapest ELIGIBLE quoted price against the lowest quoted price;
       costing  what financing and expected loss add: the best eligible all-in cost against that cheapest eligible price.
     screen + costing equals the basis exactly. Models with no eligible, fully priced quote are left out, as the server's basis does. */
  function basisBreakdown(data) {
    const quotes = Array.isArray(data?.quotes) ? data.quotes : []; const models = Array.isArray(data?.models) ? data.models : [];
    let weight = 0, total = 0, screen = 0, counted = 0;
    models.forEach((entry) => {
      if (!entry || !entry.best || !finite(entry.best.risk_adjusted) || !(entry.gpus > 0)) return;
      const mine = quotes.filter((quote) => quote.gpu === entry.model);
      const prices = mine.map((quote) => Number(quote.price)).filter(finite);
      const eligible = mine.filter((quote) => quote.eligible).map((quote) => Number(quote.price)).filter(finite);
      if (!prices.length || !eligible.length) return;
      const lowest = Math.min(...prices); const cheapestEligible = Math.min(...eligible);
      if (!(lowest > 0)) return;
      weight += entry.gpus; counted++;
      total += entry.gpus * (entry.best.risk_adjusted / lowest - 1);
      screen += entry.gpus * (cheapestEligible / lowest - 1);
    });
    if (!(weight > 0)) return null;
    return { basis: total / weight, screen: screen / weight, costing: (total - screen) / weight, models: counted, modelsTotal: models.length, gpus: weight };
  }

  window.LandingData = Object.freeze({ basisBreakdown });
})();
