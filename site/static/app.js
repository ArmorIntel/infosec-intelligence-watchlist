// Progressive enhancement only: every section is readable without JavaScript.
(function () {
  "use strict";
  var page = document.body.getAttribute("data-page");
  var lang = document.documentElement.lang || "en";

  function all(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function hashId() {
    var raw = location.hash.replace(/^#/, "");
    try { return decodeURIComponent(raw); } catch (err) { return raw; } // malformed, e.g. "#%"
  }
  function byId(sections, id) { return sections.filter(function (s) { return s.id === id; })[0]; }

  // On user navigation: react only to hashes naming one of `sections` (or no
  // hash), so other anchors such as the "Skip to content" link (#content) keep
  // the current view; then scroll the shown section into view, so a tap on a
  // category or tab visibly does something on small screens.
  function onHashChange(sections, show) {
    window.addEventListener("hashchange", function () {
      var id = hashId();
      if (id && !byId(sections, id)) return;
      show();
      var target = id && byId(sections, id);
      if (target && !target.hidden) target.scrollIntoView({ block: "start" });
    });
  }

  // Show one section among `sections`, mark the matching link as current.
  function showOnly(sections, links, id) {
    var target = byId(sections, id) || sections[0];
    sections.forEach(function (s) { s.hidden = s !== target; });
    links.forEach(function (a) {
      if (a.getAttribute("href") === "#" + (target && target.id)) a.setAttribute("aria-current", "true");
      else a.removeAttribute("aria-current");
    });
    return target;
  }

  // Catalogue: one category at a time, search across all of them.
  if (page === "catalogue") {
    var sections = all("section.category");
    var links = all(".sidebar a");
    var box = document.querySelector(".search");
    var input = document.getElementById("search");
    var none = document.querySelector(".search-empty");
    var cards = all("article.card");
    var byHash = function () { showOnly(sections, links, hashId()); };

    var filter = function () {
      var q = input.value.trim().toLowerCase();
      if (!q) { cards.forEach(function (c) { c.hidden = false; }); none.hidden = true; byHash(); return; }
      var words = q.split(/\s+/);
      var any = false;
      cards.forEach(function (c) {
        var text = c.getAttribute("data-search") || "";
        c.hidden = !words.every(function (w) { return text.indexOf(w) !== -1; });
      });
      sections.forEach(function (s) {
        var visible = all("article.card", s).some(function (c) { return !c.hidden; });
        s.hidden = !visible;
        any = any || visible;
      });
      links.forEach(function (a) { a.removeAttribute("aria-current"); });
      none.hidden = any;
    };

    if (box && input) {
      box.hidden = false;
      input.addEventListener("input", filter);
    }
    onHashChange(sections, function () {
      if (input && input.value) { input.value = ""; filter(); } else byHash();
    });
    byHash();
  }

  // News: one tab at a time, "all" by default.
  if (page === "news") {
    var tabs = all("section.tab");
    var tabLinks = all(".tabs a");
    var showTab = function () { showOnly(tabs, tabLinks, hashId() || "all"); };
    onHashChange(tabs, showTab);
    showTab();
  }

  // Health: filter the rows of every group by category.
  if (page === "health") {
    var picker = document.getElementById("health-cat");
    if (picker) {
      picker.parentNode.hidden = false;
      picker.addEventListener("change", function () {
        var cat = picker.value;
        all("[data-cat]").forEach(function (row) {
          row.hidden = !!cat && row.getAttribute("data-cat") !== cat;
        });
      });
    }
  }

  // Copy buttons.
  all("button.copy").forEach(function (btn) {
    var label = btn.textContent;
    btn.addEventListener("click", function () {
      var done = function (ok) {
        btn.textContent = btn.getAttribute(ok ? "data-copied" : "data-failed");
        btn.classList.toggle("done", ok);
        setTimeout(function () { btn.textContent = label; btn.classList.remove("done"); }, 1800);
      };
      if (!navigator.clipboard) { done(false); return; }
      navigator.clipboard.writeText(btn.getAttribute("data-copy")).then(
        function () { done(true); }, function () { done(false); });
    });
  });

  // Relative dates; the absolute date stays available as a tooltip.
  if (window.Intl && Intl.RelativeTimeFormat) {
    var rtf = new Intl.RelativeTimeFormat(lang, { numeric: "auto" });
    var units = [["year", 31536000], ["month", 2592000], ["week", 604800],
                 ["day", 86400], ["hour", 3600], ["minute", 60]];
    var now = Date.now();
    all("time[datetime]").forEach(function (t) {
      var when = Date.parse(t.getAttribute("datetime"));
      if (isNaN(when)) return;
      var diff = (when - now) / 1000;
      var abs = Math.abs(diff);
      var unit = units.filter(function (u) { return abs >= u[1]; })[0] || ["minute", 60];
      t.title = new Date(when).toLocaleString(lang);
      t.textContent = rtf.format(Math.round(diff / unit[1]), unit[0]);
    });
  }
})();
