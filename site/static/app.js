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

    // Language filter, remembered on this device: French, English or both.
    var langBox = document.querySelector(".lang-filter");
    if (langBox) {
      var radios = all("input[name='news-lang']", langBox);
      var showLang = function (want) {
        all("ul.news > li").forEach(function (li) { li.hidden = !!want && li.getAttribute("lang") !== want; });
        all(".lang-empty").forEach(function (note) {
          note.hidden = all("ul.news > li", note.parentNode).some(function (li) { return !li.hidden; });
        });
      };
      var saved = "";
      try { saved = localStorage.getItem("news-lang") || ""; } catch (err) { /* storage blocked */ }
      if (saved !== "fr" && saved !== "en") saved = "";
      radios.forEach(function (r) {
        r.checked = r.value === saved;
        r.addEventListener("change", function () {
          try { localStorage.setItem("news-lang", r.value); } catch (err) { /* storage blocked */ }
          showLang(r.value);
        });
      });
      langBox.hidden = false;
      showLang(saved);
    }
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
        // A group left without any row for this category is hidden too.
        all(".health-group").forEach(function (group) {
          var rows = all("[data-cat]", group);
          group.hidden = rows.length > 0 && rows.every(function (r) { return r.hidden; });
        });
      });
    }
  }

  // The dotted globe, turning slowly: behind the home hero, and a slice of it
  // in the band of the other pages. Sources light up (cyan, or red for a
  // threat) and signals arc between them. Decorative only: one still frame
  // under reduced motion, paused while off screen. `place(W, H)` returns
  // [centre x, globe top y, radius] in CSS pixels.
  function globe(canvas, place, count) {
    var g = canvas.getContext && canvas.getContext("2d");
    if (!g) return;
    var hero = canvas.parentNode;
    var still = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
    var TILT = 0.72, SPIN = 0.09; // radians, radians per second
    var W, H, R, cx, cy, dpr, rim, floor, dots = [], pings = [];
    var spin = 0, lean = 0, leanTo = 0, last = 0, nextPing = 0, visible = true, frame = 0;

    function sphere(n) {
      var out = [], golden = Math.PI * (3 - Math.sqrt(5)), i, y, r, a, lat, k, m;
      for (i = 0; i < n; i++) {
        y = 1 - (i / (n - 1)) * 2; r = Math.sqrt(1 - y * y); a = golden * i;
        out.push([Math.cos(a) * r, y, Math.sin(a) * r, 0]);
      }
      for (lat = 0; lat <= 80; lat += 10) { // latitude rings, denser and brighter
        y = Math.sin(lat * Math.PI / 180); r = Math.cos(lat * Math.PI / 180);
        m = Math.round((n / 9) * r);
        for (k = 0; k < m; k++) {
          a = (k / m) * Math.PI * 2;
          out.push([Math.cos(a) * r, y, Math.sin(a) * r, 1]);
        }
      }
      return out;
    }

    // The rim glow and the dark disc never move: drawn once per size.
    function paintRim() {
      rim = document.createElement("canvas");
      rim.width = canvas.width; rim.height = canvas.height;
      var o = rim.getContext("2d"), glow = document.createElement("canvas");
      glow.width = rim.width; glow.height = rim.height;
      var q = glow.getContext("2d"), X = cx * dpr, Y = cy * dpr, S = R * dpr;
      var tint = q.createLinearGradient(X - S, 0, X + S, 0);
      tint.addColorStop(0, "#22e3ff"); tint.addColorStop(0.35, "#2f6bff");
      tint.addColorStop(0.7, "#7c5cff"); tint.addColorStop(1, "#ff3d9a");
      var halo = q.createRadialGradient(X, Y, S * 0.84, X, Y, S * 1.22);
      halo.addColorStop(0, "rgba(255,255,255,0)"); halo.addColorStop(0.42, "rgba(255,255,255,0.75)");
      halo.addColorStop(0.55, "rgba(255,255,255,0.3)"); halo.addColorStop(1, "rgba(255,255,255,0)");
      q.fillStyle = halo; q.fillRect(0, 0, glow.width, glow.height);
      q.globalCompositeOperation = "source-in";
      q.fillStyle = tint; q.fillRect(0, 0, glow.width, glow.height);
      o.drawImage(glow, 0, 0);
      var disc = o.createRadialGradient(X, Y - S * 0.3, 0, X, Y, S);
      disc.addColorStop(0, "rgba(3,5,12,0.94)"); disc.addColorStop(0.85, "rgba(5,9,24,0.82)");
      disc.addColorStop(1, "rgba(6,10,28,0.55)");
      o.fillStyle = disc; o.beginPath(); o.arc(X, Y, S, 0, Math.PI * 2); o.fill();
      o.globalAlpha = 0.9; o.strokeStyle = tint; o.lineWidth = 1.2 * dpr; o.stroke();
    }

    function size() {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      W = hero.clientWidth; H = hero.clientHeight;
      canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
      var at = place(W, H);
      cx = at[0]; R = at[2]; cy = at[1] + R;
      floor = H > 400 ? H - 60 : H; // keep signals above the home ticker
      dots = sphere(count(W));
      paintRim();
    }

    // Screen position and depth (1 facing us, -1 behind) of a point on the sphere.
    function project(p) {
      var s = spin + lean, cs = Math.cos(s), sn = Math.sin(s), ct = Math.cos(TILT), st = Math.sin(TILT);
      var x = p[0] * cs + p[2] * sn, z = -p[0] * sn + p[2] * cs;
      var y = p[1] * ct - z * st; z = p[1] * st + z * ct;
      return [cx + x * R, cy - y * R, z];
    }

    function spawn(now) {
      var a = dots[(Math.random() * dots.length) | 0], b = dots[(Math.random() * dots.length) | 0];
      var pa = project(a), pb = project(b);
      if (pa[2] < 0.2 || pa[1] > floor) return;
      pings.push({ a: a, b: Math.random() < 0.4 && pb[2] > 0.2 && pb[1] < floor ? b : null,
                   red: Math.random() < 0.22, born: now, life: 2200 });
    }

    function draw(now) {
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      g.clearRect(0, 0, W, H);
      g.drawImage(rim, 0, 0, W, H);
      var i, p, d, z, sz;
      for (i = 0; i < dots.length; i++) {
        p = project(dots[i]); z = p[2];
        if (z < 0 || p[1] > H + 4 || p[0] < -4 || p[0] > W + 4) continue;
        sz = (dots[i][3] ? 1.8 : 1.3) * (0.6 + z);
        g.fillStyle = dots[i][3] ? "rgba(200,240,255," + (0.3 + 0.7 * z) + ")"
                                 : "rgba(150,195,255," + (0.3 + 0.6 * z) + ")";
        g.fillRect(p[0] - sz / 2, p[1] - sz / 2, sz, sz);
      }
      pings = pings.filter(function (k) { return now - k.born < k.life && project(k.a)[2] > 0.05; });
      pings.forEach(function (k) {
        var t = (now - k.born) / k.life, a = project(k.a), rgb = k.red ? "255,61,113" : "34,227,255";
        g.strokeStyle = "rgba(" + rgb + "," + (1 - t) * 0.9 + ")"; g.lineWidth = 1.2;
        g.beginPath(); g.arc(a[0], a[1], 2 + 22 * t, 0, Math.PI * 2); g.stroke();
        g.fillStyle = "rgba(" + rgb + "," + Math.min(1, 1.6 * (1 - t)) + ")";
        g.beginPath(); g.arc(a[0], a[1], 2.2, 0, Math.PI * 2); g.fill();
        if (!k.b) return;
        var b = project(k.b), mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2;
        d = Math.hypot(b[0] - a[0], b[1] - a[1]);
        var ux = mx - cx, uy = my - cy, ul = Math.hypot(ux, uy) || 1;
        var qx = mx + ux / ul * d * 0.45, qy = my + uy / ul * d * 0.45;
        var head = Math.min(1, t / 0.55), n = 24, j, u, x, y;
        g.lineWidth = 1.4; g.beginPath();
        for (j = 0; j <= n * head; j++) {
          u = j / n;
          x = (1 - u) * (1 - u) * a[0] + 2 * (1 - u) * u * qx + u * u * b[0];
          y = (1 - u) * (1 - u) * a[1] + 2 * (1 - u) * u * qy + u * u * b[1];
          if (j) g.lineTo(x, y); else g.moveTo(x, y);
        }
        g.strokeStyle = "rgba(" + (k.red ? rgb : "124,92,255") + "," + (1 - t) * 0.85 + ")"; g.stroke();
        if (head < 1) { g.fillStyle = "#ffffff"; g.fillRect(x - 1.5, y - 1.5, 3, 3); }
      });
    }

    function tick(now) {
      frame = 0;
      if (!visible || document.hidden) return;
      var dt = last ? Math.min(now - last, 100) : 16;
      last = now;
      spin += SPIN * dt / 1000;
      lean += (leanTo - lean) * 0.04;
      if (now > nextPing) { spawn(now); nextPing = now + 160 + Math.random() * 320; }
      draw(now);
      frame = requestAnimationFrame(tick);
    }
    function play() { if (!still && !frame) { last = 0; frame = requestAnimationFrame(tick); } }

    size();
    draw(0);
    if (still) return;
    window.addEventListener("resize", function () { size(); draw(performance.now()); });
    hero.addEventListener("pointermove", function (ev) {
      var box = hero.getBoundingClientRect();
      leanTo = ((ev.clientX - box.left) / box.width - 0.5) * 0.5;
    });
    document.addEventListener("visibilitychange", play);
    if (window.IntersectionObserver) {
      new IntersectionObserver(function (entries) {
        visible = entries[0].isIntersecting;
        play();
      }).observe(hero);
    }
    play();
  }
  var heroGlobe = document.querySelector(".intel-globe");
  if (heroGlobe) {
    globe(heroGlobe, function (W, H) { return [W / 2, H * 0.4, Math.max(Math.min(W * 0.6, H * 1.05), 300)]; },
          function (W) { return W < 700 ? 600 : 1800; });
  }
  var bandGlobe = document.querySelector(".band-globe");
  if (bandGlobe) {
    globe(bandGlobe, function (W, H) {
      var R = Math.max(Math.min(W * 0.22, 300), 170);
      return [W < 700 ? W * 0.92 : W * 0.8, H * 0.22, R];
    }, function () { return 700; });
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
