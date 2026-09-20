/* PD Brief — interface behaviour.
   Everything here is an enhancement: the site is fully readable without it. */
(function () {
  "use strict";

  var root = document.documentElement;

  function store(key, value) {
    try { localStorage.setItem(key, value); } catch (e) { /* private mode */ }
  }
  function recall(key) {
    try { return localStorage.getItem(key); } catch (e) { return null; }
  }

  /* --- Text size ------------------------------------------------------- */
  var sizeButtons = document.querySelectorAll(".tool-btn[data-size]");

  function markSize() {
    var current = root.getAttribute("data-textsize") || "normal";
    sizeButtons.forEach(function (b) {
      var on = b.getAttribute("data-size") === current;
      b.classList.toggle("is-active", on);
      b.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }
  sizeButtons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      var size = btn.getAttribute("data-size");
      root.setAttribute("data-textsize", size);
      store("pdb-textsize", size);
      markSize();
    });
  });
  markSize();

  /* --- Theme ----------------------------------------------------------- */
  var themeBtn = document.getElementById("theme-btn");

  /* The site is light unless the reader has chosen dark here. The computer's
     own dark setting is deliberately ignored. */
  function currentlyDark() {
    return root.getAttribute("data-theme") === "dark";
  }
  if (themeBtn) {
    themeBtn.addEventListener("click", function () {
      var next = currentlyDark() ? "light" : "dark";
      root.setAttribute("data-theme", next);
      store("pdb-theme", next);
      themeBtn.setAttribute("title", next === "dark" ? "Switch to light colours" : "Switch to dark colours");
    });
  }

  /* --- Mobile navigation ----------------------------------------------- */
  var navToggle = document.querySelector(".nav-toggle");
  var nav = document.getElementById("site-nav");
  if (navToggle && nav) {
    navToggle.addEventListener("click", function () {
      var open = nav.classList.toggle("is-open");
      navToggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && nav.classList.contains("is-open")) {
        nav.classList.remove("is-open");
        navToggle.setAttribute("aria-expanded", "false");
        navToggle.focus();
      }
    });
  }

  /* --- Glossary pop-ups ------------------------------------------------- */
  var pop = document.getElementById("gloss-pop");
  var popTerm = document.getElementById("gloss-pop-term");
  var popDef = document.getElementById("gloss-pop-def");
  var popClose = document.getElementById("gloss-close");
  var activeTrigger = null;

  function hidePop() {
    if (!pop) return;
    pop.hidden = true;
    if (activeTrigger) {
      activeTrigger.setAttribute("aria-expanded", "false");
      activeTrigger = null;
    }
  }

  function showPop(btn) {
    if (!pop) return;
    if (activeTrigger === btn) { hidePop(); return; }
    hidePop();
    popTerm.textContent = btn.getAttribute("data-term") || "";
    popDef.textContent = btn.getAttribute("data-def") || "";
    pop.hidden = false;

    var r = btn.getBoundingClientRect();
    var w = pop.offsetWidth;
    var left = r.left + window.scrollX + r.width / 2 - w / 2;
    var margin = 12;
    left = Math.max(margin, Math.min(left, document.documentElement.clientWidth - w - margin));
    var top = r.bottom + window.scrollY + 8;
    // Flip above the word if there is not enough room below.
    if (r.bottom + pop.offsetHeight + 20 > window.innerHeight) {
      top = r.top + window.scrollY - pop.offsetHeight - 8;
    }
    pop.style.left = left + "px";
    pop.style.top = top + "px";

    btn.setAttribute("aria-expanded", "true");
    activeTrigger = btn;
  }

  document.addEventListener("click", function (e) {
    var btn = e.target.closest ? e.target.closest(".gloss") : null;
    if (btn) { e.preventDefault(); showPop(btn); return; }
    if (pop && !pop.hidden && !e.target.closest(".gloss-pop")) hidePop();
  });
  if (popClose) popClose.addEventListener("click", hidePop);
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") hidePop(); });
  window.addEventListener("resize", hidePop);

  /* --- Archive search and topic filter --------------------------------- */
  var search = document.getElementById("archive-search");
  var filters = document.querySelectorAll(".filter");
  var rows = document.querySelectorAll(".arch-row");
  var countEl = document.getElementById("results-count");
  var noResults = document.getElementById("no-results");
  var activeTopic = "all";

  function applyArchiveFilters() {
    var q = (search && search.value ? search.value : "").trim().toLowerCase();
    var shown = 0;

    rows.forEach(function (row) {
      var topics = row.getAttribute("data-topics") || "";
      var matchesTopic = activeTopic === "all" || topics.split(" ").indexOf(activeTopic) !== -1;
      var matchesText = !q || row.textContent.toLowerCase().indexOf(q) !== -1;
      var visible = matchesTopic && matchesText;
      row.hidden = !visible;
      if (visible) shown++;
    });

    document.querySelectorAll(".arch-year").forEach(function (section) {
      var any = section.querySelector(".arch-row:not([hidden])");
      section.hidden = !any;
    });

    if (countEl) {
      countEl.textContent = shown === rows.length
        ? "Showing all " + shown + " issue" + (shown === 1 ? "" : "s")
        : "Showing " + shown + " of " + rows.length + " issues";
    }
    if (noResults) noResults.hidden = shown !== 0;
  }

  if (search) search.addEventListener("input", applyArchiveFilters);
  filters.forEach(function (btn) {
    btn.addEventListener("click", function () {
      activeTopic = btn.getAttribute("data-topic");
      filters.forEach(function (b) { b.classList.toggle("is-active", b === btn); });
      applyArchiveFilters();
    });
  });
  if (rows.length) {
    applyArchiveFilters();
    // Allow /archive/?topic=biomarkers to open pre-filtered.
    var wanted = new URLSearchParams(window.location.search).get("topic");
    if (wanted) {
      var match = document.querySelector('.filter[data-topic="' + wanted + '"]');
      if (match) match.click();
    }
  }

  /* --- Glossary page search -------------------------------------------- */
  var glossSearch = document.getElementById("gloss-search");
  if (glossSearch) {
    var entries = document.querySelectorAll(".gl-entry");
    var glNoResults = document.getElementById("gl-no-results");
    glossSearch.addEventListener("input", function () {
      var q = glossSearch.value.trim().toLowerCase();
      var shown = 0;
      entries.forEach(function (el) {
        var hit = !q || el.textContent.toLowerCase().indexOf(q) !== -1;
        el.hidden = !hit;
        if (hit) shown++;
      });
      document.querySelectorAll(".gl-group").forEach(function (g) {
        g.hidden = !g.querySelector(".gl-entry:not([hidden])");
      });
      if (glNoResults) glNoResults.hidden = shown !== 0;
    });
  }
})();
