/* Sharing Corrections across Tasks: page behaviour.
   Everything here is an enhancement: without this script the page shows all
   text, charts, value tables and clips (with native video controls), and
   every tab panel is visible. No network requests are made. */
(function () {
  "use strict";

  var root = document.documentElement;
  root.classList.add("js");

  var reduceMotion = window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function each(list, fn) { Array.prototype.forEach.call(list, fn); }

  /* ---------------------------------------------------------------- clips
     Videos carry preload="none" and a poster. A clip starts loading when it
     comes near the viewport and plays only while it is on screen. With
     reduced motion nothing plays until the viewer presses play. A clip in a
     hidden tab panel is neither loaded nor played. */
  (function setupVideos() {
    var videos = document.querySelectorAll("video[data-lazy]");
    if (!videos.length || !("IntersectionObserver" in window)) {
      return;                       // posters and native controls remain
    }
    var near = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting && e.target.preload === "none") {
          e.target.preload = "metadata";
        }
      });
    }, { rootMargin: "400px 0px" });

    var onScreen = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        var v = e.target;
        if (e.isIntersecting && e.intersectionRatio >= 0.6) {
          if (!reduceMotion && !v.dataset.userPaused) {
            var p = v.play();
            if (p && typeof p.catch === "function") { p.catch(function () {}); }
          }
        } else if (!v.paused) {
          v.dataset.auto = "1";
          v.pause();
        }
      });
    }, { threshold: [0, 0.6] });

    each(videos, function (v) {
      near.observe(v);
      onScreen.observe(v);
      // A pause by the viewer is respected until they press play again.
      v.addEventListener("pause", function () {
        if (v.dataset.auto) { delete v.dataset.auto; } else if (!v.ended) { v.dataset.userPaused = "1"; }
      });
      v.addEventListener("play", function () { delete v.dataset.userPaused; });
    });
  })();

  /* ----------------------------------------------------------------- tabs
     One component for the evidence tabs, the clip switches and the gallery:
     a row of links (data-tab) that point at panels (data-panel). Arrow keys,
     Home and End move between tabs; a link or address that names a panel, or
     something inside one, opens it. */
  var groups = [];

  function setupTabs(group) {
    var list = group.querySelector("[data-tablist]");
    if (!list) { return; }
    var tabs = Array.prototype.slice.call(list.querySelectorAll("a[data-tab]"));
    var panels = tabs.map(function (t) {
      return document.getElementById((t.getAttribute("href") || "").slice(1));
    });
    if (!tabs.length || panels.some(function (p) { return !p; })) { return; }
    var current = -1;

    function select(i, opts) {
      opts = opts || {};
      i = (i + tabs.length) % tabs.length;
      tabs.forEach(function (t, j) {
        t.setAttribute("aria-selected", j === i ? "true" : "false");
        t.setAttribute("tabindex", j === i ? "0" : "-1");
        panels[j].hidden = j !== i;
      });
      current = i;
      if (opts.focus) { tabs[i].focus(); }
      if (opts.user) {
        if (group.hasAttribute("data-hash") && window.history && window.history.replaceState) {
          window.history.replaceState(null, "", "#" + panels[i].id);
        }
        var top = panels[i].getBoundingClientRect().top;
        if (top < 0) { panels[i].scrollIntoView({ block: "start" }); }
      }
    }

    list.setAttribute("role", "tablist");
    tabs.forEach(function (t, i) {
      t.setAttribute("role", "tab");
      if (!t.id) { t.id = "tab-" + panels[i].id; }
      t.setAttribute("aria-controls", panels[i].id);
      panels[i].setAttribute("role", "tabpanel");
      panels[i].setAttribute("aria-labelledby", t.id);
      t.addEventListener("click", function (ev) {
        ev.preventDefault();
        select(i, { user: true });
      });
      t.addEventListener("keydown", function (ev) {
        var k = ev.key;
        if (k === "ArrowRight" || k === "ArrowDown") { ev.preventDefault(); select(current + 1, { focus: true, user: true }); }
        else if (k === "ArrowLeft" || k === "ArrowUp") { ev.preventDefault(); select(current - 1, { focus: true, user: true }); }
        else if (k === "Home") { ev.preventDefault(); select(0, { focus: true, user: true }); }
        else if (k === "End") { ev.preventDefault(); select(tabs.length - 1, { focus: true, user: true }); }
        else if (k === " " || k === "Spacebar") { ev.preventDefault(); select(i, { user: true }); }
      });
    });
    group.classList.add("is-tabs");
    select(0);
    groups.push({ panels: panels, select: select });
  }

  each(document.querySelectorAll("[data-tabs]"), setupTabs);

  /* A link or address that names a tab panel, something inside a panel, or a
     collapsed block opens it and brings it into view. */
  function openTarget(scroll) {
    var id = window.location.hash ? decodeURIComponent(window.location.hash.slice(1)) : "";
    var el = id ? document.getElementById(id) : null;
    if (!el) { return; }
    if (el.tagName === "DETAILS") { el.open = true; }
    var panel = el.closest ? el.closest("[data-panel]") : null;
    if (panel) {
      groups.forEach(function (g) {
        var i = g.panels.indexOf(panel);
        if (i >= 0) { g.select(i); }
      });
      if (scroll) { el.scrollIntoView({ block: "start" }); }
    }
  }
  window.addEventListener("hashchange", function () { openTarget(true); });

  // Tabs are in place: lay the page out with one panel per group, then honour the address.
  root.classList.remove("pre");
  window.scReady = true;
  openTarget(true);

  /* ------------------------------------------------------- recipe highlight
     One state for the whole page: choosing a recipe in any chart dims the
     other recipes in every chart. Colours never change. */
  function setRecipe(r) {
    if (r === "all") { root.removeAttribute("data-recipe"); } else { root.setAttribute("data-recipe", r); }
    each(document.querySelectorAll(".rtoggle button"), function (b) {
      b.setAttribute("aria-pressed", b.getAttribute("data-recipe") === r ? "true" : "false");
    });
  }
  document.addEventListener("click", function (ev) {
    var b = ev.target.closest ? ev.target.closest(".rtoggle button") : null;
    if (b) { setRecipe(b.getAttribute("data-recipe")); }
  });

  /* ------------------------------------------------------------- tooltips
     Every mark carries data-tip = "value|label|detail". The same values are
     in the table under each chart. Pointer: hover or tap a mark. Keyboard:
     focus a chart, then use the arrow keys; Escape closes. */
  var tip = document.getElementById("tip");
  var active = null;
  var keyboardChart = null;
  var keyIndex = -1;

  function showTip(mark, x, y) {
    if (!tip) { return; }
    var parts = (mark.getAttribute("data-tip") || "").split("|");
    tip.textContent = "";
    parts.forEach(function (text, i) {
      if (!text) { return; }
      var el = document.createElement(i === 0 ? "strong" : "span");
      el.textContent = text;
      tip.appendChild(el);
    });
    tip.hidden = false;
    if (active && active !== mark) { active.classList.remove("is-active"); }
    active = mark;
    mark.classList.add("is-active");
    var w = tip.offsetWidth, h = tip.offsetHeight;
    var left = Math.min(Math.max(8, x - w / 2), window.innerWidth - w - 8);
    var top = y - h - 14;
    if (top < 8) { top = y + 18; }
    tip.style.left = left + "px";
    tip.style.top = top + "px";
  }

  function hideTip() {
    if (tip) { tip.hidden = true; }
    if (active) { active.classList.remove("is-active"); active = null; }
  }

  function markAt(target) {
    return target && target.closest ? target.closest(".mark[data-tip]") : null;
  }

  document.addEventListener("pointermove", function (ev) {
    if (ev.pointerType === "touch") { return; }
    var m = markAt(ev.target);
    if (m) { showTip(m, ev.clientX, ev.clientY); } else if (active && !keyboardChart) { hideTip(); }
  });
  document.addEventListener("pointerdown", function (ev) {
    var m = markAt(ev.target);
    keyboardChart = null;
    if (m) { showTip(m, ev.clientX, ev.clientY); } else { hideTip(); }
  });
  window.addEventListener("scroll", function () { if (!keyboardChart) { hideTip(); } }, { passive: true });

  function focusMark(chart, index) {
    var marks = chart.querySelectorAll(".mark[data-tip]");
    if (!marks.length) { return; }
    keyIndex = (index + marks.length) % marks.length;
    var m = marks[keyIndex];
    var box = m.getBoundingClientRect();
    showTip(m, box.left + box.width / 2, box.top);
  }

  document.addEventListener("keydown", function (ev) {
    var chart = document.activeElement && document.activeElement.matches &&
      document.activeElement.matches("svg.chart[data-chart]") ? document.activeElement : null;
    if (!chart) { return; }
    if (ev.key === "ArrowRight" || ev.key === "ArrowDown") {
      ev.preventDefault();
      if (keyboardChart !== chart) { keyboardChart = chart; keyIndex = -1; }
      focusMark(chart, keyIndex + 1);
    } else if (ev.key === "ArrowLeft" || ev.key === "ArrowUp") {
      ev.preventDefault();
      if (keyboardChart !== chart) { keyboardChart = chart; keyIndex = 0; }
      focusMark(chart, keyIndex - 1);
    } else if (ev.key === "Escape") {
      keyboardChart = null;
      hideTip();
    }
  });
  document.addEventListener("focusout", function (ev) {
    if (ev.target === keyboardChart) { keyboardChart = null; hideTip(); }
  });

  /* ----------------------------------------------------------- copy BibTeX */
  var copyBtn = document.getElementById("copy-bib");
  if (copyBtn) {
    copyBtn.hidden = false;
    copyBtn.addEventListener("click", function () {
      var src = document.getElementById(copyBtn.getAttribute("data-copy"));
      var text = src ? src.textContent : "";
      function done(ok) {
        copyBtn.textContent = ok ? "Copied" : "Select and copy";
        window.setTimeout(function () { copyBtn.textContent = "Copy"; }, 1800);
      }
      function fallback() {
        var ok = false;
        try {
          var range = document.createRange();
          range.selectNodeContents(src);
          var sel = window.getSelection();
          sel.removeAllRanges();
          sel.addRange(range);
          ok = document.execCommand("copy");
        } catch (err) {
          ok = false;
        }
        done(ok);
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function () { done(true); }, fallback);
      } else {
        fallback();
      }
    });
  }

  /* -------------------------------------------------------------- section rail
     Mark the section that is being read in the sticky rail, and, inside the
     findings, the finding that is being read. The two levels are tracked
     separately so that a finding and its section are marked together. */
  function spyOn(links) {
    var targets = links.map(function (a) {
      return document.getElementById(a.getAttribute("href").slice(1));
    });
    if (!links.length || !("IntersectionObserver" in window)) { return; }
    var visible = {};
    var spy = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) { visible[e.target.id] = e.isIntersecting; });
      var current = null;
      for (var i = 0; i < targets.length; i++) {
        if (targets[i] && visible[targets[i].id]) { current = i; break; }
      }
      links.forEach(function (a, i) {
        if (i === current) { a.setAttribute("aria-current", "true"); } else { a.removeAttribute("aria-current"); }
      });
      if (current !== null && links[current].scrollIntoView && links[current].closest(".rail-sub") === null) {
        // Keep the current section visible when the rail scrolls sideways on a narrow screen.
        var list = links[current].closest("ol");
        if (list && list.scrollWidth > list.clientWidth) {
          var box = links[current].getBoundingClientRect(), frame = list.getBoundingClientRect();
          if (box.left < frame.left || box.right > frame.right) {
            list.scrollLeft += box.left - frame.left - 16;
          }
        }
      }
    }, { rootMargin: "-14% 0px -68% 0px" });
    targets.forEach(function (t) { if (t) { spy.observe(t); } });
  }
  var all = Array.prototype.slice.call(document.querySelectorAll(".rail a[href^='#']"));
  spyOn(all.filter(function (a) { return !a.closest(".rail-sub"); }));
  spyOn(all.filter(function (a) { return !!a.closest(".rail-sub"); }));
})();
