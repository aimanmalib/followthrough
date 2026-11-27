/* Follow-Through landing page: the light/dark switch. The choice is kept in localStorage under the key in
   data-storage-key (config/pages.toml theme_storage_key); data-tema on <html> is read by token.css. */
(function () {
  "use strict";
  var root = document.documentElement, toggle = document.querySelector(".theme-switch");
  if (!toggle) return;
  function dark() { return root.dataset.tema ? root.dataset.tema === "gelap" : matchMedia("(prefers-color-scheme: dark)").matches; }
  function label() { toggle.setAttribute("aria-label", dark() ? toggle.dataset.labelLight : toggle.dataset.labelDark); }
  toggle.addEventListener("click", function () {
    root.dataset.tema = dark() ? "terang" : "gelap";
    try { localStorage.setItem(toggle.dataset.storageKey, root.dataset.tema); } catch (e) { /* storage blocked: the choice lasts for this visit */ }
    label();
  });
  label();
})();
