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
    document.addEventListener("click", function (e) {
      if (nav.classList.contains("is-open") && !nav.contains(e.target) &&
          !navToggle.contains(e.target)) {
        nav.classList.remove("is-open");
        navToggle.setAttribute("aria-expanded", "false");
      }
    });
  }

  /* --- Glossary pop-ups ------------------------------------------------- */
  var pop = document.getElementById("gloss-pop");
  var popTerm = document.getElementById("gloss-pop-term");
  var popDef = document.getElementById("gloss-pop-def");
  var popClose = document.getElementById("gloss-close");
  var activeTrigger = null;

  function hidePop(returnFocus) {
    if (!pop) return;
    pop.hidden = true;
    if (activeTrigger) {
      activeTrigger.setAttribute("aria-expanded", "false");
      if (returnFocus === true) activeTrigger.focus();
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
    // Flip above the word if there is not enough room below it.
    if (r.bottom + pop.offsetHeight + 20 > window.innerHeight) {
      top = r.top + window.scrollY - pop.offsetHeight - 8;
    }
    // Then keep it inside the window whatever happened above, so a long
    // definition near an edge is never cut off.
    var minTop = window.scrollY + margin;
    var maxTop = window.scrollY + window.innerHeight - pop.offsetHeight - margin;
    if (maxTop < minTop) maxTop = minTop;
    top = Math.max(minTop, Math.min(top, maxTop));

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
  if (popClose) popClose.addEventListener("click", function () { hidePop(true); });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && pop && !pop.hidden) hidePop(true);
  });
  // Phones fire "resize" whenever the address bar slides away during a scroll,
  // so only a real change of width (rotating, resizing a window) closes it.
  var lastWidth = window.innerWidth;
  window.addEventListener("resize", function () {
    if (window.innerWidth !== lastWidth) { lastWidth = window.innerWidth; hidePop(); }
  });

  /* --- Archive search and topic filter --------------------------------- */
  var search = document.getElementById("archive-search");
  var filters = document.querySelectorAll(".filter");
  var rows = document.querySelectorAll(".arch-row");
  var countEl = document.getElementById("results-count");
  var noResults = document.getElementById("no-results");
  var activeTopic = "all";

  // Full issue text, fetched the first time someone searches. Until it
  // arrives, searching still works across titles, summaries and topics.
  var fullText = null, fullTextAsked = false;

  function loadFullText() {
    if (fullTextAsked) return;
    fullTextAsked = true;
    fetch("/search-index.json")
      .then(function (r) { return r.json(); })
      .then(function (list) {
        fullText = {};
        list.forEach(function (item) { fullText[item.u] = item.b || ""; });
        applyArchiveFilters();
      })
      .catch(function () { /* titles and summaries still search fine */ });
  }

  function applyArchiveFilters() {
    var q = (search && search.value ? search.value : "").trim().toLowerCase();
    var shown = 0;
    if (q) loadFullText();

    rows.forEach(function (row) {
      var topics = row.getAttribute("data-topics") || "";
      var matchesTopic = activeTopic === "all" || topics.split(" ").indexOf(activeTopic) !== -1;
      var matchesText = !q || row.textContent.toLowerCase().indexOf(q) !== -1;
      if (!matchesText && q && fullText) {
        var link = row.querySelector(".arch-link");
        var body = link && fullText[link.getAttribute("href")];
        if (body && body.indexOf(q) !== -1) matchesText = true;
      }
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
        : "Showing " + shown + " of " + rows.length + " issues" +
          (q && fullText ? ", searching the full text of each" : "");
    }
    if (noResults) noResults.hidden = shown !== 0;
  }

  if (search) search.addEventListener("input", applyArchiveFilters);
  filters.forEach(function (btn) {
    btn.setAttribute("aria-pressed", btn.classList.contains("is-active") ? "true" : "false");
    btn.addEventListener("click", function () {
      activeTopic = btn.getAttribute("data-topic");
      filters.forEach(function (b) {
        b.classList.toggle("is-active", b === btn);
        b.setAttribute("aria-pressed", b === btn ? "true" : "false");
      });
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

  /* --- Wide tables ------------------------------------------------------ */
  // A table wider than the screen scrolls sideways. Keyboard users can only
  // scroll it if it can take focus, so give it that, and a name, when needed.
  function markScrollableTables() {
    document.querySelectorAll(".table-wrap").forEach(function (wrap) {
      if (wrap.scrollWidth > wrap.clientWidth + 1) {
        wrap.setAttribute("tabindex", "0");
        wrap.setAttribute("role", "region");
        wrap.setAttribute("aria-label", "Table, scrolls sideways");
      } else {
        wrap.removeAttribute("tabindex");
        wrap.removeAttribute("role");
        wrap.removeAttribute("aria-label");
      }
    });
  }
  markScrollableTables();
  window.addEventListener("resize", markScrollableTables);

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
