/* Runs before the first paint so a reload on an app page never flashes the landing page. The page names must match
   VIEWS in workbench.js; tests hold the two together. */
(function () {
  "use strict";
  var APP = /^(desk|quotes|pricing)$/;
  document.documentElement.setAttribute("data-page", APP.test(location.hash.slice(1)) ? "app" : "landing");
  if ("scrollRestoration" in history) history.scrollRestoration = "manual";
})();
