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

/* The proof panel: [data-hidup="<url>"] loads the sample sweep summary written by scripts/build_pages.py and sets data-status
   to muat | ada | kosong | ralat; ?keadaan=muat|kosong|ralat forces one state (for the page checks). [data-format] holds a
   locale sentence whose {field} markers are filled from the summary; [data-code] rows get their action's count. */
(function () {
  "use strict";
  var forced = new URLSearchParams(location.search).get("keadaan"), lang = document.documentElement.lang || "en";
  function fill(template, data) {
    return template.replace(/\{(\w+)\}/g, function (all, key) {
      var v = data[key];
      return v == null ? all : typeof v === "number" ? v.toLocaleString(lang) : String(v);
    });
  }
  function show(slot, data) {
    var counts = {};
    (data.actions || []).forEach(function (a) { counts[a.code] = a.count; });
    slot.querySelectorAll("[data-format]").forEach(function (el) { el.textContent = fill(el.dataset.format, data); });
    slot.querySelectorAll(".tally [data-code]").forEach(function (el) {
      var n = counts[el.dataset.code] || 0;
      el.style.setProperty("--n", n);
      el.hidden = n === 0;
    });
    slot.querySelectorAll(".legend [data-code]").forEach(function (el) {
      el.querySelector("[data-count]").textContent = (counts[el.dataset.code] || 0).toLocaleString(lang);
    });
    var label = slot.querySelector(".tally");
    if (label) label.setAttribute("aria-label", label.getAttribute("aria-label") + ": " + Array.prototype.map.call(
      slot.querySelectorAll(".legend [data-code]"), function (li) { return li.textContent.replace(/\s+/g, " ").trim(); }).join(", "));
  }
  document.querySelectorAll("[data-hidup]").forEach(function (slot) {
    slot.dataset.status = "muat";
    if (forced === "muat") return;
    fetch(slot.dataset.hidup, { cache: "no-store" })
      .then(function (r) { if (!r.ok || forced === "ralat") throw new Error(String(r.status)); return r.json(); })
      .then(function (data) {
        if (forced === "kosong" || !data || !data.threads) { slot.dataset.status = "kosong"; return; }
        show(slot, data);
        slot.dataset.status = "ada";
      })
      .catch(function () { slot.dataset.status = "ralat"; });
  });
})();

/* Copy buttons in the demo section: copy the command next to the button and confirm in the button's own text. */
(function () {
  "use strict";
  document.querySelectorAll(".copy").forEach(function (button) {
    var label = button.textContent;
    button.addEventListener("click", function () {
      var code = button.parentElement.querySelector("pre code");
      if (!code || !navigator.clipboard) return;
      navigator.clipboard.writeText(code.textContent).then(function () {
        button.textContent = button.dataset.copied;
        setTimeout(function () { button.textContent = label; }, 1800);
      }, function () { /* clipboard refused: the command stays selectable */ });
    });
  });
})();
