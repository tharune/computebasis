"use strict";
// Quotes drawn from real simulator snapshots in the browserless DOM (see demo_harness.js).
const { test } = require("node:test");
const { assert, findAll, classes, byClass, byTag, settle, assertClean, makePage, base, war, reset, book, normalize, assertLive, deskFixture } = require("./demo_harness.js");

test("the Quotes cost bars print every component and the all-in total straight from the quote", async () => {
  const page = makePage(base); page.connect(); await settle(); page.host.showView("quotes"); await settle();
  const b300 = book.base.models.find((entry) => entry.model === "B300"); const best = book.base.quotes.find((quote) => quote.id === b300.best.id);
  const callout = page.el("quotes-callout"); assert.equal(byClass(callout, "cost-row").length, 2);
  assert.ok(byClass(callout, "cost-total").some((node) => node.textContent.startsWith("$" + best.risk_adjusted.toFixed(3))));
  ["$" + Number(best.price).toFixed(2), "$" + best.financing.toFixed(3), "$" + best.exposure.toFixed(3)].forEach((value) => assert.ok(callout.textContent.includes(value), value + " is printed"));
  assert.equal(byClass(page.el("quotes-detail"), "cost-row").length, 1);
  assert.equal(byClass(callout, "ch-part").length >= 3, true);
});

test("Quotes ranks every quote for the selected model and Price this quote hands off the selected one", async () => {
  const page = makePage(base, { priceQuote: true }); page.connect(); await settle(); page.host.showView("quotes"); await settle();
  const rows = byTag(page.el("quotes-table"), "tbody")[0].children;
  const b300 = book.base.quotes.filter((quote) => quote.gpu === "B300");
  assert.equal(rows.length, b300.length);
  ["quotes-lede", "quotes-callout", "quotes-table", "quotes-detail", "quotes-models"].forEach((id) => assertClean(page.el(id), id));
  const first = findAll(rows[0], (node) => node.tagName === "button")[0];
  const chosen = b300.slice().sort((a, b) => (a.risk_rank ?? 1e9) - (b.risk_rank ?? 1e9) || Number(a.price) - Number(b.price))[0];
  assert.equal(first.textContent, chosen.id, "the top row is the best all-in quote");
  await first.click(); await settle();
  assert.match(page.el("quotes-detail").textContent, new RegExp(chosen.id));
  await page.button("quotes-detail", "Price this quote").click();
  assert.equal(page.priced.length, 1);
  assert.equal(page.priced[0].id, chosen.id);
  assert.equal(page.priced[0].price, chosen.exact.price, "the exact decimal the server sent, not a rounded number");
  assert.equal(typeof page.priced[0].price, "string", "prices stay decimal strings");
});

test("without a pricing handler the button simply opens Pricing", async () => {
  const page = makePage(base); page.connect(); await settle(); page.host.showView("quotes"); await settle();
  await page.button("quotes-detail", "Price this quote").click();
  assert.equal(page.shown.at(-1), "pricing");
});
