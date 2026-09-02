/* PD Brief writing desk.
   Talks to the local preview server; nothing here ever runs on the public site. */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };

  var state = {
    file: null,        // filename on disk, null for a new unsaved issue
    dirty: false,
    topics: [],
    papers: [],
    glossary: [],
    knownTopics: [],
    saving: false
  };

  var els = {
    title: $("f-title"), date: $("f-date"), slug: $("f-slug"),
    summary: $("f-summary"), topic: $("f-topic"), body: $("f-body"),
    draft: $("f-draft"), chips: $("topic-chips"), papers: $("papers"),
    list: $("issue-list"), saveState: $("save-state"), saveBtn: $("btn-save")
  };

  /* ---------------------------------------------------------------- utils */

  function api(path, opts) {
    return fetch(path, opts).then(function (r) {
      if (!r.ok && r.status !== 400) throw new Error("Request failed (" + r.status + ")");
      return r.json();
    });
  }

  var toastTimer;
  function toast(msg, bad) {
    var t = $("toast");
    t.textContent = msg;
    t.className = "toast" + (bad ? " bad" : "");
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.hidden = true; }, bad ? 5000 : 2600);
  }

  function slugify(s) {
    return String(s).toLowerCase().replace(/['’]/g, "")
      .replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60);
  }

  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  function markDirty() {
    state.dirty = true;
    els.saveState.textContent = "Unsaved changes";
    els.saveState.className = "save-state dirty";
    schedulePreview();
  }

  function markClean(when) {
    state.dirty = false;
    els.saveState.textContent = when ? "Saved " + when : "No changes";
    els.saveState.className = "save-state" + (when ? " saved" : "");
  }

  /* ------------------------------------------------------------- the form */

  function collect() {
    return {
      title: els.title.value.trim(),
      date: els.date.value,
      slug: els.slug.value.trim() || slugify(els.title.value),
      summary: els.summary.value.trim(),
      topics: state.topics.slice(),
      papers: state.papers.slice(),
      draft: els.draft.checked
    };
  }

  function fill(data) {
    els.title.value = data.title || "";
    els.date.value = (data.date || "").slice(0, 10);
    els.slug.value = data.slug || "";
    els.summary.value = data.summary || "";
    els.body.value = data.body || "";
    els.draft.checked = !!data.draft;
    state.topics = (data.topics || []).map(String);
    state.papers = (data.papers && data.papers.length) ? data.papers.map(function (p) {
      return {
        title: p.title || "", authors: p.authors || "", journal: p.journal || "",
        year: p.year || "", doi: p.doi || "", url: p.url || "", access: p.access || ""
      };
    }) : [blankPaper()];
    state.file = data.file || null;
    renderChips();
    renderPapers();
    autosize(els.title);
    markClean();
    refreshPreview();
  }

  function blankPaper() {
    return { title: "", authors: "", journal: "", year: "", doi: "", url: "", access: "Free abstract" };
  }

  function autosize(el) {
    el.style.height = "auto";
    el.style.height = el.scrollHeight + "px";
  }

  /* ---------------------------------------------------------------- chips */

  function renderChips() {
    els.chips.innerHTML = "";
    state.topics.forEach(function (t, i) {
      var chip = document.createElement("span");
      chip.className = "chip";
      chip.appendChild(document.createTextNode(t));
      var x = document.createElement("button");
      x.type = "button";
      x.innerHTML = "&times;";
      x.title = "Remove " + t;
      x.addEventListener("click", function () {
        state.topics.splice(i, 1);
        renderChips();
        markDirty();
      });
      chip.appendChild(x);
      els.chips.appendChild(chip);
    });
  }

  function addTopic(value) {
    var t = String(value || "").trim().replace(/,$/, "");
    if (!t) return;
    if (state.topics.some(function (x) { return x.toLowerCase() === t.toLowerCase(); })) return;
    state.topics.push(t);
    renderChips();
    markDirty();
  }

  els.topic.addEventListener("keydown", function (e) {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      addTopic(els.topic.value);
      els.topic.value = "";
    } else if (e.key === "Backspace" && !els.topic.value && state.topics.length) {
      state.topics.pop(); renderChips(); markDirty();
    }
  });
  els.topic.addEventListener("blur", function () {
    if (els.topic.value.trim()) { addTopic(els.topic.value); els.topic.value = ""; }
  });

  /* --------------------------------------------------------------- papers */

  var PAPER_FIELDS = [
    { key: "title", label: "Title of the paper", full: true },
    { key: "authors", label: "Authors", full: true, ph: "Lastname A, Lastname B, et al." },
    { key: "journal", label: "Journal" },
    { key: "year", label: "Year", ph: "2026" },
    { key: "doi", label: "DOI", ph: "10.1056/NEJMoa2312323" },
    { key: "access", label: "Access", ph: "Free abstract" }
  ];

  function renderPapers() {
    els.papers.innerHTML = "";
    state.papers.forEach(function (paper, idx) {
      var card = document.createElement("div");
      card.className = "paper-card";

      var grid = document.createElement("div");
      grid.className = "paper-grid";

      PAPER_FIELDS.forEach(function (f) {
        var wrap = document.createElement("div");
        if (f.full) wrap.className = "full";
        var lab = document.createElement("p");
        lab.className = "paper-mini";
        lab.textContent = f.label;
        var inp = document.createElement("input");
        inp.className = "fi";
        inp.type = "text";
        inp.value = paper[f.key] || "";
        if (f.ph) inp.placeholder = f.ph;
        inp.addEventListener("input", function () {
          state.papers[idx][f.key] = inp.value;
          markDirty();
        });
        wrap.appendChild(lab);
        wrap.appendChild(inp);
        grid.appendChild(wrap);
      });

      card.appendChild(grid);

      if (state.papers.length > 1) {
        var foot = document.createElement("div");
        foot.className = "paper-remove";
        var rm = document.createElement("button");
        rm.className = "dbtn dbtn-small dbtn-danger";
        rm.type = "button";
        rm.textContent = "Remove this study";
        rm.addEventListener("click", function () {
          state.papers.splice(idx, 1);
          renderPapers();
          markDirty();
        });
        foot.appendChild(rm);
        card.appendChild(foot);
      }
      els.papers.appendChild(card);
    });
  }

  $("btn-add-paper").addEventListener("click", function () {
    state.papers.push(blankPaper());
    renderPapers();
    markDirty();
  });

  /* -------------------------------------------------------------- toolbar */

  function surround(before, after) {
    var ta = els.body, s = ta.selectionStart, e = ta.selectionEnd;
    var sel = ta.value.slice(s, e);
    ta.setRangeText(before + sel + after, s, e, "end");
    if (!sel) ta.selectionStart = ta.selectionEnd = s + before.length;
    ta.focus();
    markDirty();
  }

  function atLineStart(prefix) {
    var ta = els.body, s = ta.selectionStart, e = ta.selectionEnd;
    var start = ta.value.lastIndexOf("\n", s - 1) + 1;
    var end = ta.value.indexOf("\n", e);
    if (end === -1) end = ta.value.length;
    var lines = ta.value.slice(start, end).split("\n");
    var n = 1;
    var out = lines.map(function (l) {
      return prefix === "1. " ? (n++) + ". " + l.replace(/^\s*(\d+\.|[-*])\s+/, "")
                              : prefix + l.replace(/^\s*(\d+\.|[-*]|>)\s+/, "");
    }).join("\n");
    ta.setRangeText(out, start, end, "end");
    ta.focus();
    markDirty();
  }

  function insertBlock(text) {
    var ta = els.body, s = ta.selectionStart, e = ta.selectionEnd;
    var sel = ta.value.slice(s, e);
    var before = ta.value.slice(0, s);
    var pad = (before && !/\n\n$/.test(before)) ? (/\n$/.test(before) ? "\n" : "\n\n") : "";
    var block = text.replace("{sel}", sel || "");
    ta.setRangeText(pad + block + "\n", s, e, "end");
    // Drop the caret onto the first empty line inside the block.
    var pos = s + pad.length + block.indexOf("{caret}");
    var cleaned = ta.value.replace("{caret}", "");
    if (block.indexOf("{caret}") !== -1) {
      ta.value = cleaned;
      ta.selectionStart = ta.selectionEnd = pos;
    }
    ta.focus();
    markDirty();
  }

  var ACTIONS = {
    bold:    function () { surround("**", "**"); },
    italic:  function () { surround("*", "*"); },
    link:    function () {
      var url = prompt("Link address (paste the URL):", "https://");
      if (url) surround("[", "](" + url + ")");
    },
    h2:      function () { atLineStart("## "); },
    h3:      function () { atLineStart("### "); },
    ul:      function () { atLineStart("- "); },
    ol:      function () { atLineStart("1. "); },
    quote:   function () { atLineStart("> "); },
    table:   function () {
      insertBlock("| | Group A | Group B |\n| --- | --- | --- |\n| Participants | | |\n| Result | | |");
    },
    key:     function () { insertBlock(":::key\n{sel}{caret}\n:::"); },
    plain:   function () { insertBlock(":::plain\n{sel}{caret}\n:::"); },
    caution: function () { insertBlock(":::caution\n{sel}{caret}\n:::"); },
    gloss:   function () { openGlossary(); }
  };

  $("toolbar").addEventListener("click", function (e) {
    var btn = e.target.closest("[data-act]");
    if (!btn) return;
    e.preventDefault();
    var fn = ACTIONS[btn.getAttribute("data-act")];
    if (fn) fn();
  });

  $("btn-structure").addEventListener("click", function () {
    if (els.body.value.trim() &&
        !confirm("Insert the standard section headings at the end of what you have written?")) return;
    var scaffold = [
      "## What the researchers were trying to find out", "",
      "## What they did", "",
      "## What they found", "",
      "## Why it matters", "",
      "## What this doesn't tell us", "",
      "## What to watch next", ""
    ].join("\n");
    els.body.value = els.body.value.replace(/\s*$/, "\n\n") + scaffold;
    els.body.focus();
    markDirty();
  });

  els.body.addEventListener("keydown", function (e) {
    if (!(e.metaKey || e.ctrlKey)) return;
    var k = e.key.toLowerCase();
    if (k === "b") { e.preventDefault(); ACTIONS.bold(); }
    else if (k === "i") { e.preventDefault(); ACTIONS.italic(); }
    else if (k === "k") { e.preventDefault(); ACTIONS.link(); }
  });

  document.addEventListener("keydown", function (e) {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s") {
      e.preventDefault();
      save();
    }
  });

  /* ------------------------------------------------------- glossary picker */

  function openGlossary() {
    var sel = els.body.value.slice(els.body.selectionStart, els.body.selectionEnd).trim();
    $("gloss-search").value = sel;
    $("gloss-modal").hidden = false;
    renderGlossResults(sel);
    $("gloss-search").focus();
    $("gloss-search").select();
  }

  function closeGlossary() { $("gloss-modal").hidden = true; els.body.focus(); }

  function renderGlossResults(query) {
    var q = String(query || "").toLowerCase().trim();
    var box = $("gloss-results");
    box.innerHTML = "";
    // Rank an exact term match first, then terms that start with the query,
    // then other term matches, and only then matches found in a definition.
    function rank(g) {
      var t = g.term.toLowerCase();
      if (t === q) return 0;
      if (t.indexOf(q) === 0) return 1;
      if (t.indexOf(q) !== -1) return 2;
      return 3;
    }
    var hits = state.glossary.filter(function (g) {
      return !q || g.term.toLowerCase().indexOf(q) !== -1 ||
             g.definition.toLowerCase().indexOf(q) !== -1;
    });
    if (q) {
      hits.sort(function (a, b) {
        return rank(a) - rank(b) || a.term.localeCompare(b.term);
      });
    }
    hits = hits.slice(0, 40);

    if (!hits.length) {
      box.innerHTML = '<p class="checks-empty">No matching term in your glossary yet.</p>';
      return;
    }
    hits.forEach(function (g) {
      var b = document.createElement("button");
      b.className = "gres";
      b.type = "button";
      b.innerHTML = '<span class="gres-term">' + esc(g.term) + '</span>' +
                    '<span class="gres-def">' + esc(g.definition) + '</span>';
      b.addEventListener("click", function () { insertTerm(g.term); });
      box.appendChild(b);
    });
  }

  function insertTerm(term) {
    var ta = els.body, s = ta.selectionStart, e = ta.selectionEnd;
    var sel = ta.value.slice(s, e).trim();
    // Keep the writer's own wording visible when it differs from the entry.
    var snippet = (sel && sel.toLowerCase() !== term.toLowerCase())
      ? "{{" + term + "|" + sel + "}}"
      : "{{" + term + "}}";
    ta.setRangeText(snippet, s, e, "end");
    closeGlossary();
    markDirty();
  }

  $("gloss-search").addEventListener("input", function () { renderGlossResults(this.value); });
  $("gloss-cancel").addEventListener("click", closeGlossary);
  $("gloss-modal").addEventListener("click", function (e) {
    if (e.target === this) closeGlossary();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !$("gloss-modal").hidden) closeGlossary();
  });

  /* --------------------------------------------------------- live preview */

  var previewTimer;
  function schedulePreview() {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(refreshPreview, 350);
  }

  function refreshPreview() {
    var meta = collect();

    $("prev-title").textContent = meta.title || "Your headline appears here";
    $("prev-summary").textContent = meta.summary;
    $("prev-meta").textContent = (meta.draft ? "Draft · " : "") +
      (meta.date ? new Date(meta.date + "T12:00:00").toLocaleDateString(undefined,
        { year: "numeric", month: "long", day: "numeric" }) : "No date set");

    var tags = $("prev-tags");
    tags.innerHTML = "";
    meta.topics.forEach(function (t) {
      var s = document.createElement("span");
      s.className = "prev-tag";
      s.textContent = t;
      tags.appendChild(s);
    });

    var n = els.summary.value.trim().length;
    var sc = $("summary-count");
    sc.textContent = n ? n + " characters" : "";
    sc.className = "counter" + (n > 300 ? " over" : "");

    api("/api/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ body: els.body.value, meta: meta })
    }).then(function (res) {
      $("prev-body").innerHTML = res.html ||
        '<p style="color:var(--muted)">Your writing will appear here as you type.</p>';
      $("prev-papers").innerHTML = res.papers_html || "";
      $("body-count").textContent = res.words + " words · " + res.minutes + " min read";
      $("length-stat").textContent = res.words + " words, about a " + res.minutes +
        " minute read. Issues usually run 900 to 1,400 words.";
      renderChecks(res);
    }).catch(function () { /* preview is best-effort */ });
  }

  function renderChecks(res) {
    var sl = $("structure-list");
    sl.innerHTML = "";
    var missing = 0;
    res.checklist.forEach(function (c) {
      if (!c.present) missing++;
      var li = document.createElement("li");
      li.innerHTML = '<span class="ci ' + (c.present ? "ci-yes" : "ci-no") + '">' +
        (c.present ? "✓" : "–") + '</span><span' + (c.present ? "" : ' class="missing"') + '>' +
        esc(c.section.charAt(0).toUpperCase() + c.section.slice(1)) + '</span>';
      sl.appendChild(li);
    });

    var wl = $("warning-list");
    wl.innerHTML = "";
    if (!res.warnings.length) {
      wl.innerHTML = '<li><span class="ci ci-yes">✓</span><span>Nothing to flag.</span></li>';
    } else {
      res.warnings.forEach(function (w) {
        var li = document.createElement("li");
        li.innerHTML = '<span class="ci ci-warn">!</span><span>' + esc(w) + '</span>';
        wl.appendChild(li);
      });
    }

    var badge = $("check-badge");
    var total = missing + res.warnings.length;
    badge.textContent = total;
    badge.className = "badge" + (total ? " show" : "");
  }

  document.querySelectorAll(".ptab").forEach(function (tab) {
    tab.addEventListener("click", function () {
      document.querySelectorAll(".ptab").forEach(function (t) { t.classList.remove("is-active"); });
      tab.classList.add("is-active");
      var want = tab.getAttribute("data-panel");
      $("panel-preview").hidden = want !== "preview";
      $("panel-checks").hidden = want !== "checks";
    });
  });

  /* ------------------------------------------------------------- the list */

  function loadList(selectFile) {
    return api("/api/issues").then(function (res) {
      state.knownTopics = res.topics || [];
      var dl = $("topic-options");
      dl.innerHTML = "";
      state.knownTopics.forEach(function (t) {
        var o = document.createElement("option");
        o.value = t;
        dl.appendChild(o);
      });

      var live = res.issues.filter(function (i) { return !i.draft && !i.template; });
      var drafts = res.issues.filter(function (i) { return i.draft && !i.template; });

      els.list.innerHTML = "";
      if (drafts.length) {
        addLabel("Drafts");
        drafts.forEach(addItem);
      }
      if (live.length) {
        addLabel("Published");
        live.forEach(addItem);
      }
      if (!live.length && !drafts.length) {
        els.list.innerHTML = '<p class="empty-desk">No issues yet.<br>Start one with “New issue”.</p>';
      }

      function addLabel(text) {
        var p = document.createElement("p");
        p.className = "list-label";
        p.textContent = text;
        els.list.appendChild(p);
      }

      function addItem(it) {
        var b = document.createElement("button");
        b.className = "ilist-item" + (it.file === (selectFile || state.file) ? " is-active" : "");
        b.type = "button";
        b.innerHTML =
          '<span class="ilist-title">' + esc(it.title) + '</span>' +
          '<span class="ilist-meta">' +
            '<span class="pill ' + (it.draft ? "pill-draft" : "pill-live") + '">' +
              (it.draft ? "Draft" : "Live") + '</span>' +
            '<span>' + esc(it.date) + '</span>' +
            '<span>· ' + it.words + ' words</span>' +
          '</span>';
        b.addEventListener("click", function () { openIssue(it.file); });
        els.list.appendChild(b);
      }
    });
  }

  function openIssue(file) {
    if (state.dirty && !confirm("You have unsaved changes. Open a different issue anyway?")) return;
    api("/api/issue/" + encodeURIComponent(file)).then(function (data) {
      if (data.error) { toast("Could not open that issue.", true); return; }
      fill(data);
      loadList(file);
    });
  }

  $("btn-new").addEventListener("click", function () {
    if (state.dirty && !confirm("You have unsaved changes. Start a new issue anyway?")) return;
    api("/api/new").then(function (res) {
      fill({ date: res.date, draft: true, papers: [blankPaper()], topics: [] });
      loadList(null);
      els.title.focus();
      toast("New draft started");
    });
  });

  /* ---------------------------------------------------------------- saving */

  function save() {
    if (state.saving) return;
    var meta = collect();
    if (!meta.title) { toast("Give the issue a headline first.", true); els.title.focus(); return; }
    if (!meta.date) { toast("Give the issue a date first.", true); els.date.focus(); return; }

    state.saving = true;
    els.saveBtn.disabled = true;
    els.saveState.textContent = "Saving…";

    api("/api/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ meta: meta, body: els.body.value, original_file: state.file })
    }).then(function (res) {
      if (!res.ok) { toast(res.error || "Could not save.", true); markDirty(); return; }
      state.file = res.file;
      markClean(res.saved_at);
      toast(meta.draft ? "Saved as a draft" : "Saved and published to your site");
      loadList(res.file);
    }).catch(function (err) {
      toast(String(err.message || err), true);
      markDirty();
    }).finally(function () {
      state.saving = false;
      els.saveBtn.disabled = false;
    });
  }

  els.saveBtn.addEventListener("click", save);

  $("btn-delete").addEventListener("click", function () {
    if (!state.file) { toast("This issue has not been saved yet.", true); return; }
    if (!confirm("Delete this issue permanently?\n\n" + state.file +
                 "\n\nThis cannot be undone from here.")) return;
    api("/api/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file: state.file })
    }).then(function (res) {
      if (!res.ok) { toast(res.error || "Could not delete.", true); return; }
      toast("Issue deleted");
      state.file = null;
      state.dirty = false;
      return api("/api/new").then(function (r) {
        fill({ date: r.date, draft: true, papers: [blankPaper()], topics: [] });
        loadList(null);
      });
    });
  });

  window.addEventListener("beforeunload", function (e) {
    if (state.dirty) { e.preventDefault(); e.returnValue = ""; }
  });

  /* ---------------------------------------------------------------- wiring */

  [els.title, els.date, els.slug, els.summary, els.body].forEach(function (el) {
    el.addEventListener("input", markDirty);
  });
  els.draft.addEventListener("change", markDirty);
  els.title.addEventListener("input", function () { autosize(els.title); });

  $("btn-theme").addEventListener("click", function () {
    var root = document.documentElement;
    var dark = root.getAttribute("data-theme") === "dark" ||
      (!root.getAttribute("data-theme") &&
        window.matchMedia("(prefers-color-scheme: dark)").matches);
    var next = dark ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try { localStorage.setItem("pdb-theme", next); } catch (e) {}
  });

  /* ------------------------------------------------------------- start up */

  api("/api/glossary").then(function (res) { state.glossary = res.terms || []; });

  loadList().then(function () {
    return api("/api/new");
  }).then(function (res) {
    fill({ date: res.date, draft: true, papers: [blankPaper()], topics: [] });
  });
})();
