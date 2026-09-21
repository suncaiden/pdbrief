/* PD Brief writing desk.
   A visual editor: the writer never sees Markdown. Everything typed here is
   converted to Markdown on save, and back again on open. */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };

  var CALLOUTS = {
    key:     "Key takeaway",
    plain:   "In plain terms",
    caution: "Important caution",
    note:    "Note",
    context: "Background"
  };

  var state = {
    file: null, dirty: false, topics: [], papers: [],
    glossary: [], knownTopics: [], saving: false, savedRange: null
  };

  var els = {
    title: $("f-title"), date: $("f-date"), slug: $("f-slug"),
    summary: $("f-summary"), topic: $("f-topic"), compose: $("compose"),
    draft: $("f-draft"), chips: $("topic-chips"), papers: $("papers"),
    list: $("issue-list"), saveState: $("save-state"), saveBtn: $("btn-save")
  };

  /* ================================================================== utils */

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

  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  function slugify(s) {
    return String(s).toLowerCase().replace(/['’]/g, "")
      .replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60);
  }

  function markDirty() {
    state.dirty = true;
    els.saveState.textContent = "Not saved yet";
    els.saveState.className = "save-state dirty";
    schedulePreview();
  }

  function markClean(when) {
    state.dirty = false;
    els.saveState.textContent = when ? "Saved at " + when : "No changes yet";
    els.saveState.className = "save-state" + (when ? " saved" : "");
  }

  /* ==================================================== Markdown → editor DOM */

  function inlineToHtml(src) {
    var s = esc(src);
    s = s.replace(/`([^`]+)`/g, function (m, a) { return "<code>" + a + "</code>"; });
    s = s.replace(/\{\{([^}|]+)(?:\|([^}]*))?\}\}/g, function (m, term, shown) {
      var t = term.trim();
      return '<span class="term" data-term="' + t.replace(/"/g, "&quot;") + '">' +
             ((shown || term).trim()) + "</span>";
    });
    // Addresses may contain balanced brackets (DOIs often do), so match those
    // rather than stopping at the first closing bracket.
    s = s.replace(/\[([^\]]+)\]\(((?:[^()\s]|\([^()\s]*\))+)\)/g, '<a href="$2">$1</a>');
    s = s.replace(/\*\*\*(.+?)\*\*\*/g, "<strong><em>$1</em></strong>");
    s = s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/(^|[^\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])/g, "$1<em>$2</em>");
    return s;
  }

  function calloutEl(kind, innerHtml) {
    var box = document.createElement("div");
    box.className = "cbox cbox-" + kind;
    box.setAttribute("data-kind", kind);

    var label = document.createElement("div");
    label.className = "cbox-label";
    label.contentEditable = "false";
    label.textContent = CALLOUTS[kind] || kind;

    var kill = document.createElement("button");
    kill.className = "cbox-x";
    kill.type = "button";
    kill.contentEditable = "false";
    kill.title = "Remove this box, keep the words";
    kill.innerHTML = "&times;";

    var body = document.createElement("div");
    body.className = "cbox-body";
    body.innerHTML = innerHtml || "<p><br></p>";

    box.appendChild(label);
    box.appendChild(kill);
    box.appendChild(body);
    return box;
  }

  function tableEl(rows) {
    var fig = document.createElement("figure");
    fig.className = "ctable";
    var table = document.createElement("table");

    var thead = document.createElement("thead");
    var htr = document.createElement("tr");
    (rows[0] || ["", ""]).forEach(function (c) {
      var th = document.createElement("th");
      th.innerHTML = inlineToHtml(c) || "<br>";
      htr.appendChild(th);
    });
    thead.appendChild(htr);

    var tbody = document.createElement("tbody");
    rows.slice(1).forEach(function (r) {
      var tr = document.createElement("tr");
      r.forEach(function (c) {
        var td = document.createElement("td");
        td.innerHTML = inlineToHtml(c) || "<br>";
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });

    table.appendChild(thead);
    table.appendChild(tbody);
    fig.appendChild(table);
    fig.appendChild(tableTools());
    return fig;
  }

  function tableTools() {
    var tools = document.createElement("div");
    tools.className = "ctable-tools";
    tools.contentEditable = "false";
    [["row", "Add row"], ["col", "Add column"], ["delrow", "Remove last row"],
     ["kill", "Delete table"]].forEach(function (pair) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "ctbtn";
      b.setAttribute("data-tact", pair[0]);
      b.textContent = pair[1];
      tools.appendChild(b);
    });
    return tools;
  }

  function rawEl(text) {
    var d = document.createElement("div");
    d.className = "rawblock";
    d.setAttribute("data-raw", "");
    d.textContent = text;
    return d;
  }

  /* Turn a Markdown document into editor blocks. Anything this does not
     recognise is preserved verbatim in a raw block, so nothing is ever lost. */
  function mdToBlocks(src) {
    var lines = String(src || "").replace(/\r\n/g, "\n").split("\n");
    var frag = document.createDocumentFragment();
    var i = 0;

    function isBlockStart(l) {
      var t = l.trim();
      return /^#{1,6}\s/.test(t) || /^[-*]\s/.test(t) || /^\d+\.\s/.test(t) ||
             t.startsWith("> ") || t.startsWith(":::") || t.startsWith("|") ||
             /^(-{3,}|\*{3,})$/.test(t);
    }

    while (i < lines.length) {
      var line = lines[i], t = line.trim();

      if (!t) { i++; continue; }

      if (/^(-{3,}|\*{3,})$/.test(t)) {
        frag.appendChild(document.createElement("hr"));
        i++; continue;
      }

      if (t.startsWith(":::")) {
        var kind = t.slice(3).trim().toLowerCase() || "note";
        var body = [];
        i++;
        while (i < lines.length && lines[i].trim() !== ":::") { body.push(lines[i]); i++; }
        i++;
        var inner = document.createElement("div");
        inner.appendChild(mdToBlocks(body.join("\n")));
        frag.appendChild(calloutEl(kind, inner.innerHTML));
        continue;
      }

      var h = t.match(/^(#{1,6})\s+(.*)$/);
      if (h) {
        var lvl = Math.min(Math.max(h[1].length, 2), 3);   // the site uses h2/h3
        var el = document.createElement("h" + lvl);
        el.innerHTML = inlineToHtml(h[2].trim()) || "<br>";
        frag.appendChild(el);
        i++; continue;
      }

      if (t.startsWith("|")) {
        var rows = [];
        while (i < lines.length && lines[i].trim().startsWith("|")) {
          var cells = lines[i].trim().replace(/^\||\|$/g, "").split("|")
                        .map(function (c) { return c.trim(); });
          if (!/^[\s|:-]+$/.test(lines[i].trim())) rows.push(cells);
          i++;
        }
        frag.appendChild(tableEl(rows));
        continue;
      }

      if (t.startsWith(">")) {
        var q = document.createElement("blockquote");
        while (i < lines.length && lines[i].trim().startsWith(">")) {
          var text = lines[i].replace(/^\s*>\s?/, "").trim();
          if (text) {
            var p = document.createElement("p");
            p.innerHTML = inlineToHtml(text);
            q.appendChild(p);
          }
          i++;
        }
        if (!q.children.length) q.innerHTML = "<p><br></p>";
        frag.appendChild(q);
        continue;
      }

      var ulm = /^[-*]\s+/, olm = /^\d+\.\s+/;
      if (ulm.test(t) || olm.test(t)) {
        var ordered = olm.test(t);
        var listEl = document.createElement(ordered ? "ol" : "ul");
        var pattern = ordered ? olm : ulm;
        while (i < lines.length) {
          var lt = lines[i].trim();
          if (!lt) {
            if (i + 1 < lines.length && pattern.test(lines[i + 1].trim())) { i++; continue; }
            break;
          }
          if (!pattern.test(lt)) break;
          var itemText = lt.replace(pattern, "");
          i++;
          while (i < lines.length && lines[i].trim() && !isBlockStart(lines[i])) {
            itemText += " " + lines[i].trim(); i++;
          }
          var li = document.createElement("li");
          li.innerHTML = inlineToHtml(itemText) || "<br>";
          listEl.appendChild(li);
        }
        frag.appendChild(listEl);
        continue;
      }

      // Paragraph
      var buf = [t];
      i++;
      while (i < lines.length && lines[i].trim() && !isBlockStart(lines[i])) {
        buf.push(lines[i].trim()); i++;
      }
      var para = document.createElement("p");
      para.innerHTML = inlineToHtml(buf.join(" "));
      frag.appendChild(para);
    }

    return frag;
  }

  /* ==================================================== editor DOM → Markdown */

  function inlineToMd(node) {
    var out = "";
    node.childNodes.forEach(function (n) {
      if (n.nodeType === 3) { out += n.nodeValue; return; }
      if (n.nodeType !== 1) return;
      var tag = n.tagName.toLowerCase();
      if (tag === "br") { out += " "; return; }
      if (n.classList && n.classList.contains("term")) {
        var term = n.getAttribute("data-term") || n.textContent;
        var shown = n.textContent;
        // Compare exactly: "dopamine" mid-sentence must not become "Dopamine".
        out += (shown.trim() === term.trim())
          ? "{{" + term + "}}" : "{{" + term + "|" + shown.trim() + "}}";
        return;
      }
      if (tag === "strong" || tag === "b") { out += "**" + inlineToMd(n) + "**"; return; }
      if (tag === "em" || tag === "i") { out += "*" + inlineToMd(n) + "*"; return; }
      if (tag === "code") { out += "`" + n.textContent + "`"; return; }
      if (tag === "a") { out += "[" + inlineToMd(n) + "](" + (n.getAttribute("href") || "") + ")"; return; }
      out += inlineToMd(n);
    });
    return out.replace(/ /g, " ");
  }

  function blockToMd(el) {
    if (el.nodeType !== 1) return null;
    if (el.hasAttribute && el.hasAttribute("data-raw")) return el.textContent;

    var tag = el.tagName.toLowerCase();

    if (el.classList.contains("cbox")) {
      var kind = el.getAttribute("data-kind") || "note";
      var body = el.querySelector(".cbox-body");
      var inner = body ? blocksToMd(body) : "";
      return ":::" + kind + "\n" + inner + "\n:::";
    }

    if (el.classList.contains("ctable")) {
      var table = el.querySelector("table");
      if (!table) return null;
      var out = [];
      var head = table.querySelectorAll("thead th");
      if (head.length) {
        out.push("| " + Array.prototype.map.call(head, inlineToMd).join(" | ") + " |");
        out.push("| " + Array.prototype.map.call(head, function () { return "---"; }).join(" | ") + " |");
      }
      table.querySelectorAll("tbody tr").forEach(function (tr) {
        out.push("| " + Array.prototype.map.call(tr.children, inlineToMd).join(" | ") + " |");
      });
      return out.join("\n");
    }

    if (tag === "hr") return "---";
    if (tag === "h1" || tag === "h2") return "## " + inlineToMd(el);
    if (tag === "h3" || tag === "h4" || tag === "h5" || tag === "h6") return "### " + inlineToMd(el);

    if (tag === "ul" || tag === "ol") {
      var n = 1;
      return Array.prototype.map.call(el.children, function (li) {
        return (tag === "ol" ? (n++) + ". " : "- ") + inlineToMd(li);
      }).join("\n");
    }

    if (tag === "blockquote") {
      var parts = el.children.length
        ? Array.prototype.map.call(el.children, inlineToMd)
        : [inlineToMd(el)];
      return parts.filter(function (s) { return s.trim(); })
                  .map(function (s) { return "> " + s; }).join("\n>\n");
    }

    var text = inlineToMd(el);
    return text.trim() ? text : null;
  }

  function blocksToMd(container) {
    var out = [];
    Array.prototype.forEach.call(container.children, function (el) {
      var md = blockToMd(el);
      if (md !== null && md !== undefined && String(md).trim() !== "") out.push(String(md));
    });
    return out.join("\n\n");
  }

  function getBody() { return blocksToMd(els.compose); }

  function setBody(md) {
    els.compose.innerHTML = "";
    els.compose.appendChild(mdToBlocks(md));
    ensureTrailingParagraph();
    if (!els.compose.children.length) {
      els.compose.innerHTML = "<p><br></p>";
    }
    updateEmptyState();
  }

  function updateEmptyState() {
    var blank = !els.compose.textContent.trim() &&
                !els.compose.querySelector(".ctable, .cbox, img");
    els.compose.classList.toggle("is-empty", blank);
  }

  function ensureTrailingParagraph() {
    var last = els.compose.lastElementChild;
    if (!last || last.tagName !== "P" || last.textContent.trim()) {
      var p = document.createElement("p");
      p.innerHTML = "<br>";
      els.compose.appendChild(p);
    }
  }

  /* ================================================== selection and block ops */

  function currentBlock() {
    var sel = window.getSelection();
    if (!sel || !sel.rangeCount) return null;
    var node = sel.getRangeAt(0).startContainer;
    if (node.nodeType === 3) node = node.parentNode;
    while (node && node !== els.compose) {
      if (node.parentNode === els.compose ||
          (node.parentNode && node.parentNode.classList &&
           node.parentNode.classList.contains("cbox-body"))) return node;
      node = node.parentNode;
    }
    return null;
  }

  function replaceBlock(block, tagName) {
    if (!block) return;
    var parent = block.parentNode;

    if (tagName === "ul" || tagName === "ol") {
      var list = document.createElement(tagName);
      var li = document.createElement("li");
      li.innerHTML = block.innerHTML || "<br>";
      list.appendChild(li);
      parent.replaceChild(list, block);
      placeCaretAtEnd(li);
      return;
    }

    if (block.tagName === "UL" || block.tagName === "OL") {
      var frag = document.createDocumentFragment();
      var lastEl = null;
      Array.prototype.forEach.call(block.children, function (li) {
        var el = document.createElement(tagName === "blockquote" ? "p" : tagName);
        el.innerHTML = li.innerHTML || "<br>";
        frag.appendChild(el);
        lastEl = el;
      });
      if (tagName === "blockquote") {
        var bq = document.createElement("blockquote");
        bq.appendChild(frag);
        parent.replaceChild(bq, block);
        placeCaretAtEnd(bq.lastElementChild);
      } else {
        parent.replaceChild(frag, block);
        placeCaretAtEnd(lastEl);
      }
      return;
    }

    if (tagName === "blockquote") {
      var q = document.createElement("blockquote");
      var p = document.createElement("p");
      p.innerHTML = block.innerHTML || "<br>";
      q.appendChild(p);
      parent.replaceChild(q, block);
      placeCaretAtEnd(p);
      return;
    }

    var fresh = document.createElement(tagName);
    fresh.innerHTML = block.innerHTML || "<br>";
    parent.replaceChild(fresh, block);
    placeCaretAtEnd(fresh);
  }

  function placeCaretAtEnd(el) {
    if (!el) return;
    var r = document.createRange();
    r.selectNodeContents(el);
    r.collapse(false);
    var s = window.getSelection();
    s.removeAllRanges();
    s.addRange(r);
    els.compose.focus();
  }

  function syncStyleSelect() {
    var b = currentBlock();
    var sel = $("style-select");
    if (!b) { sel.value = "p"; return; }
    var t = b.tagName.toLowerCase();
    if (b.parentNode && b.parentNode.tagName === "BLOCKQUOTE") t = "blockquote";
    else if (t === "li") t = b.parentNode.tagName.toLowerCase();
    else if (["ul", "ol", "h2", "h3", "blockquote", "p"].indexOf(t) === -1) t = "p";
    sel.value = t;
  }

  $("style-select").addEventListener("change", function () {
    var b = currentBlock();
    if (!b) return;
    if (b.tagName === "LI") b = b.parentNode;
    if (b.parentNode && b.parentNode.tagName === "BLOCKQUOTE") b = b.parentNode;
    replaceBlock(b, this.value);
    markDirty();
  });

  function insertBlockEl(el) {
    var b = currentBlock();
    var host = (b && b.parentNode) || els.compose;
    if (b && b.parentNode) host.insertBefore(el, b.nextSibling);
    else els.compose.appendChild(el);
    // Remove the empty paragraph the writer was sitting in.
    if (b && !b.textContent.trim() && b.tagName === "P" && b.parentNode) b.parentNode.removeChild(b);
    ensureTrailingParagraph();
    markDirty();
    return el;
  }

  /* ======================================================== toolbar behaviour */

  document.addEventListener("selectionchange", function () {
    if (document.activeElement === els.compose) syncStyleSelect();
  });

  $("toolbar").addEventListener("click", function (e) {
    var btn = e.target.closest(".tb[data-act]");
    if (!btn) return;
    e.preventDefault();
    var act = btn.getAttribute("data-act");
    if (act === "bold") { document.execCommand("bold"); markDirty(); }
    else if (act === "italic") { document.execCommand("italic"); markDirty(); }
    else if (act === "link") openLinkBar();
    else if (act === "term") openGlossary();
  });

  var insertMenu = $("insert-menu");
  $("btn-insert").addEventListener("click", function (e) {
    e.preventDefault();
    saveRange();
    var open = insertMenu.hidden;
    insertMenu.hidden = !open;
    this.setAttribute("aria-expanded", open ? "true" : "false");
  });
  document.addEventListener("click", function (e) {
    if (!e.target.closest(".tmenu")) {
      insertMenu.hidden = true;
      $("btn-insert").setAttribute("aria-expanded", "false");
    }
  });

  insertMenu.addEventListener("click", function (e) {
    var item = e.target.closest(".tmi");
    if (!item) return;
    e.preventDefault();
    insertMenu.hidden = true;
    $("btn-insert").setAttribute("aria-expanded", "false");
    restoreRange();
    var act = item.getAttribute("data-act");

    if (CALLOUTS[act]) {
      var box = calloutEl(act, "<p><br></p>");
      insertBlockEl(box);
      placeCaretAtEnd(box.querySelector(".cbox-body p"));
    } else if (act === "table") {
      var t = insertBlockEl(tableEl([["", "Group A", "Group B"],
                                     ["Participants", "", ""], ["Result", "", ""]]));
      placeCaretAtEnd(t.querySelector("tbody td"));
    } else if (act === "structure") {
      ["What the researchers were trying to find out", "What they did", "What they found",
       "Why it matters", "What this doesn't tell us", "What to watch next"].forEach(function (h) {
        var head = document.createElement("h2");
        head.textContent = h;
        els.compose.appendChild(head);
        var p = document.createElement("p");
        p.innerHTML = "<br>";
        els.compose.appendChild(p);
      });
      ensureTrailingParagraph();
      markDirty();
      toast("Added the six standard sections");
    }
  });

  /* Remove a callout but keep what was written inside it. */
  els.compose.addEventListener("click", function (e) {
    var x = e.target.closest(".cbox-x");
    if (x) {
      e.preventDefault();
      var box = x.closest(".cbox");
      var body = box.querySelector(".cbox-body");
      while (body.firstChild) box.parentNode.insertBefore(body.firstChild, box);
      box.parentNode.removeChild(box);
      markDirty();
      return;
    }

    var tbtn = e.target.closest(".ctbtn");
    if (tbtn) {
      e.preventDefault();
      var fig = tbtn.closest(".ctable");
      var table = fig.querySelector("table");
      var act = tbtn.getAttribute("data-tact");
      if (act === "row") {
        var cols = table.querySelectorAll("thead th").length;
        var tr = document.createElement("tr");
        for (var c = 0; c < cols; c++) { var td = document.createElement("td"); td.innerHTML = "<br>"; tr.appendChild(td); }
        table.querySelector("tbody").appendChild(tr);
      } else if (act === "col") {
        var th = document.createElement("th"); th.innerHTML = "<br>";
        table.querySelector("thead tr").appendChild(th);
        table.querySelectorAll("tbody tr").forEach(function (r) {
          var td = document.createElement("td"); td.innerHTML = "<br>"; r.appendChild(td);
        });
      } else if (act === "delrow") {
        var rows = table.querySelectorAll("tbody tr");
        if (rows.length) rows[rows.length - 1].remove();
      } else if (act === "kill") {
        if (confirm("Delete this table?")) fig.remove();
      }
      ensureTrailingParagraph();
      markDirty();
      return;
    }

    var term = e.target.closest(".term");
    if (term) { openGlossary(term); }
  });

  /* ============================================================== the link bar */

  function saveRange() {
    var s = window.getSelection();
    if (s && s.rangeCount && els.compose.contains(s.getRangeAt(0).commonAncestorContainer)) {
      state.savedRange = s.getRangeAt(0).cloneRange();
    }
  }
  function restoreRange() {
    if (!state.savedRange) { els.compose.focus(); return; }
    var s = window.getSelection();
    s.removeAllRanges();
    s.addRange(state.savedRange);
    els.compose.focus();
  }

  function currentLink() {
    var s = window.getSelection();
    if (!s || !s.rangeCount) return null;
    var n = s.getRangeAt(0).startContainer;
    if (n.nodeType === 3) n = n.parentNode;
    return n.closest ? n.closest("a") : null;
  }

  function openLinkBar() {
    saveRange();
    var a = currentLink();
    var bar = $("linkbar");
    $("link-input").value = a ? a.getAttribute("href") : "";
    $("link-remove").hidden = !a;
    bar.hidden = false;

    var r = state.savedRange ? state.savedRange.getBoundingClientRect() : null;
    if (r && r.width + r.height > 0) {
      bar.style.top = (r.bottom + window.scrollY + 8) + "px";
      bar.style.left = Math.max(12, Math.min(r.left, window.innerWidth - bar.offsetWidth - 12)) + "px";
    } else {
      bar.style.top = "50%"; bar.style.left = "50%";
    }
    $("link-input").focus();
  }

  function closeLinkBar() { $("linkbar").hidden = true; els.compose.focus(); }

  $("link-apply").addEventListener("click", function () {
    var url = $("link-input").value.trim();
    if (!url) { toast("Type a web address first.", true); return; }
    if (!/^(https?:|mailto:|\/)/i.test(url)) url = "https://" + url;
    restoreRange();
    if (window.getSelection().isCollapsed) {
      document.execCommand("insertHTML", false,
        '<a href="' + esc(url) + '">' + esc(url) + "</a>");
    } else {
      document.execCommand("createLink", false, url);
    }
    closeLinkBar();
    markDirty();
  });
  $("link-remove").addEventListener("click", function () {
    restoreRange();
    document.execCommand("unlink");
    closeLinkBar();
    markDirty();
  });
  $("link-cancel").addEventListener("click", closeLinkBar);
  $("link-input").addEventListener("keydown", function (e) {
    if (e.key === "Enter") { e.preventDefault(); $("link-apply").click(); }
    if (e.key === "Escape") { e.preventDefault(); closeLinkBar(); }
  });

  /* ========================================================= glossary picking */

  var editingTerm = null;

  function openGlossary(existing) {
    editingTerm = existing || null;
    saveRange();
    var seed = existing ? existing.getAttribute("data-term")
                        : String(window.getSelection()).trim();
    $("gloss-search").value = seed;
    $("gloss-modal").hidden = false;
    renderGlossResults(seed);
    $("gloss-search").focus();
    $("gloss-search").select();
  }

  function closeGlossary() {
    $("gloss-modal").hidden = true;
    editingTerm = null;
    els.compose.focus();
  }

  function renderGlossResults(query) {
    var q = String(query || "").toLowerCase().trim();
    var box = $("gloss-results");
    box.innerHTML = "";

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
    if (q) hits.sort(function (a, b) { return rank(a) - rank(b) || a.term.localeCompare(b.term); });
    hits = hits.slice(0, 40);

    if (editingTerm) {
      var rm = document.createElement("button");
      rm.className = "gres gres-remove";
      rm.type = "button";
      rm.innerHTML = '<span class="gres-term">Remove the explanation</span>' +
                     '<span class="gres-def">Keep the words, drop the definition</span>';
      rm.addEventListener("click", function () {
        var parent = editingTerm.parentNode;
        while (editingTerm.firstChild) parent.insertBefore(editingTerm.firstChild, editingTerm);
        parent.removeChild(editingTerm);
        closeGlossary();
        markDirty();
      });
      box.appendChild(rm);
    }

    if (!hits.length) {
      var p = document.createElement("p");
      p.className = "checks-empty";
      p.textContent = "No matching word in your glossary yet.";
      box.appendChild(p);
      return;
    }

    hits.forEach(function (g) {
      var b = document.createElement("button");
      b.className = "gres";
      b.type = "button";
      b.innerHTML = '<span class="gres-term">' + esc(g.term) + "</span>" +
                    '<span class="gres-def">' + esc(g.definition) + "</span>";
      b.addEventListener("click", function () { applyTerm(g.term); });
      box.appendChild(b);
    });
  }

  function applyTerm(term) {
    if (editingTerm) {
      editingTerm.setAttribute("data-term", term);
      closeGlossary();
      markDirty();
      return;
    }
    restoreRange();
    var sel = window.getSelection();
    var shown = String(sel).trim();
    if (!shown) { shown = term; }
    var span = '<span class="term" data-term="' + esc(term) + '">' + esc(shown) + "</span>";
    document.execCommand("insertHTML", false, span);
    closeGlossary();
    markDirty();
  }

  $("gloss-search").addEventListener("input", function () { renderGlossResults(this.value); });
  $("gloss-cancel").addEventListener("click", closeGlossary);
  $("gloss-modal").addEventListener("click", function (e) { if (e.target === this) closeGlossary(); });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    if (!$("gloss-modal").hidden) closeGlossary();
    else if (!$("linkbar").hidden) closeLinkBar();
  });

  /* ========================================================= typing behaviour */

  try { document.execCommand("defaultParagraphSeparator", false, "p"); } catch (e) {}

  els.compose.addEventListener("input", function () {
    if (!els.compose.children.length) els.compose.innerHTML = "<p><br></p>";
    updateEmptyState();
    markDirty();
  });

  els.compose.addEventListener("keydown", function (e) {
    if (e.metaKey || e.ctrlKey) {
      var k = e.key.toLowerCase();
      if (k === "b") { e.preventDefault(); document.execCommand("bold"); markDirty(); }
      else if (k === "i") { e.preventDefault(); document.execCommand("italic"); markDirty(); }
      else if (k === "k") { e.preventDefault(); openLinkBar(); }
      return;
    }
    // Enter after a heading should return to body text, not make another heading.
    if (e.key === "Enter" && !e.shiftKey) {
      var b = currentBlock();
      if (b && /^H[23]$/.test(b.tagName)) {
        e.preventDefault();
        var p = document.createElement("p");
        p.innerHTML = "<br>";
        b.parentNode.insertBefore(p, b.nextSibling);
        placeCaretAtEnd(p);
        markDirty();
      }
    }
  });

  // Paste as plain text, so nothing from another site drags its styling in.
  els.compose.addEventListener("paste", function (e) {
    e.preventDefault();
    var text = (e.clipboardData || window.clipboardData).getData("text/plain");
    document.execCommand("insertText", false, text);
  });

  els.compose.addEventListener("blur", ensureTrailingParagraph);

  /* ================================================================== the form */

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
    els.draft.checked = !!data.draft;
    setBody(data.body || "");
    state.topics = (data.topics || []).map(String);
    state.papers = (data.papers && data.papers.length)
      ? data.papers.map(function (p) {
          return { title: p.title || "", authors: p.authors || "", journal: p.journal || "",
                   year: p.year || "", doi: p.doi || "", url: p.url || "", access: p.access || "" };
        })
      : [blankPaper()];
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

  function autosize(el) { el.style.height = "auto"; el.style.height = el.scrollHeight + "px"; }

  /* ------------------------------------------------------------------- chips */

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
      x.addEventListener("click", function () { state.topics.splice(i, 1); renderChips(); markDirty(); });
      chip.appendChild(x);
      els.chips.appendChild(chip);
    });
  }

  function addTopic(v) {
    var t = String(v || "").trim().replace(/,$/, "");
    if (!t) return;
    if (state.topics.some(function (x) { return x.toLowerCase() === t.toLowerCase(); })) return;
    state.topics.push(t);
    renderChips();
    markDirty();
  }

  els.topic.addEventListener("keydown", function (e) {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault(); addTopic(els.topic.value); els.topic.value = "";
    } else if (e.key === "Backspace" && !els.topic.value && state.topics.length) {
      state.topics.pop(); renderChips(); markDirty();
    }
  });
  els.topic.addEventListener("blur", function () {
    if (els.topic.value.trim()) { addTopic(els.topic.value); els.topic.value = ""; }
  });

  /* ------------------------------------------------------------------ papers */

  var PAPER_FIELDS = [
    { key: "title", label: "Title of the paper", full: true },
    { key: "authors", label: "Authors", full: true, ph: "Lastname A, Lastname B, et al." },
    { key: "journal", label: "Journal" },
    { key: "year", label: "Year", ph: "2026" },
    { key: "doi", label: "DOI", ph: "10.1056/NEJMoa2312323" },
    { key: "access", label: "Is it free to read?", ph: "Free abstract" }
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
        inp.addEventListener("input", function () { state.papers[idx][f.key] = inp.value; markDirty(); });
        wrap.appendChild(lab); wrap.appendChild(inp); grid.appendChild(wrap);
      });

      card.appendChild(grid);
      if (state.papers.length > 1) {
        var foot = document.createElement("div");
        foot.className = "paper-remove";
        var rm = document.createElement("button");
        rm.className = "dbtn dbtn-small dbtn-danger";
        rm.type = "button";
        rm.textContent = "Remove this study";
        rm.addEventListener("click", function () { state.papers.splice(idx, 1); renderPapers(); markDirty(); });
        foot.appendChild(rm);
        card.appendChild(foot);
      }
      els.papers.appendChild(card);
    });
  }

  $("btn-add-paper").addEventListener("click", function () {
    state.papers.push(blankPaper()); renderPapers(); markDirty();
  });

  /* ------------------------------------------------------------ live preview */

  var previewTimer, previewSeq = 0;
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

    var sp = $("slug-preview");
    if (sp) {
      sp.textContent = meta.slug
        ? "Readers will find this issue at pdbrief.org/issues/" + slugify(meta.slug)
        : "Readers will find this issue at pdbrief.org/issues/…";
    }

    var n = els.summary.value.trim().length;
    var sc = $("summary-count");
    sc.textContent = n ? n + " characters" : "";
    sc.className = "counter" + (n > 300 ? " over" : "");

    var seq = ++previewSeq;
    api("/api/preview", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ body: getBody(), meta: meta })
    }).then(function (res) {
      if (seq !== previewSeq) return;   // a newer preview is already on its way
      $("prev-body").innerHTML = res.html ||
        '<p style="color:var(--muted)">Your writing will appear here as you type.</p>';
      $("prev-papers").innerHTML = res.papers_html || "";
      $("body-count").textContent = res.words + " words, about " + res.minutes + " minutes to read";
      $("length-stat").textContent = res.words + " words, about " + res.minutes +
        " minutes to read. Issues usually run between 900 and 1,400 words.";
      renderChecks(res);
    }).catch(function () { /* the preview is best-effort */ });
  }

  function renderChecks(res) {
    var sl = $("structure-list");
    sl.innerHTML = "";
    var missing = 0;
    res.checklist.forEach(function (c) {
      if (!c.present) missing++;
      var li = document.createElement("li");
      li.innerHTML = '<span class="ci ' + (c.present ? "ci-yes" : "ci-no") + '">' +
        (c.present ? "✓" : "–") + "</span><span" + (c.present ? "" : ' class="missing"') + ">" +
        esc(c.section.charAt(0).toUpperCase() + c.section.slice(1)) + "</span>";
      sl.appendChild(li);
    });

    var wl = $("warning-list");
    wl.innerHTML = "";
    if (!res.warnings.length) {
      wl.innerHTML = '<li><span class="ci ci-yes">✓</span><span>Nothing to flag.</span></li>';
    } else {
      res.warnings.forEach(function (w) {
        var li = document.createElement("li");
        li.innerHTML = '<span class="ci ci-warn">!</span><span>' + esc(w) + "</span>";
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

  /* ------------------------------------------------------------------- list */

  function loadList(selectFile) {
    return api("/api/issues").then(function (res) {
      state.knownTopics = res.topics || [];
      var dl = $("topic-options");
      dl.innerHTML = "";
      state.knownTopics.forEach(function (t) {
        var o = document.createElement("option"); o.value = t; dl.appendChild(o);
      });

      var live = res.issues.filter(function (i) { return !i.draft && !i.template; });
      var drafts = res.issues.filter(function (i) { return i.draft && !i.template; });

      els.list.innerHTML = "";
      if (drafts.length) { addLabel("Still drafts"); drafts.forEach(addItem); }
      if (live.length) { addLabel("Published"); live.forEach(addItem); }
      if (!live.length && !drafts.length) {
        els.list.innerHTML = '<p class="empty-desk">Nothing here yet.<br>Start your first issue above.</p>';
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
          '<span class="ilist-title">' + esc(it.title) + "</span>" +
          '<span class="ilist-meta">' +
            '<span class="pill ' + (it.draft ? "pill-draft" : "pill-live") + '">' +
              (it.draft ? "Draft" : "Live") + "</span>" +
            "<span>" + esc(it.date) + "</span>" +
            "<span>" + it.words + " words</span>" +
          "</span>";
        b.addEventListener("click", function () { openIssue(it.file); });
        els.list.appendChild(b);
      }
    });
  }

  function openIssue(file) {
    if (state.dirty && !confirm("This issue has changes you have not saved. Open a different one anyway?")) return;
    api("/api/issue/" + encodeURIComponent(file)).then(function (data) {
      if (data.error) { toast("Could not open that issue.", true); return; }
      fill(data);
      loadList(file);
    });
  }

  $("btn-new").addEventListener("click", function () {
    if (state.dirty && !confirm("This issue has changes you have not saved. Start a new one anyway?")) return;
    api("/api/new").then(function (res) {
      fill({ date: res.date, draft: true, papers: [blankPaper()], topics: [], body: "" });
      loadList(null);
      els.title.focus();
      toast("New draft started");
    });
  });

  /* ----------------------------------------------------------------- saving */

  function save() {
    if (state.saving) return;
    var meta = collect();
    if (!meta.title) { toast("Give the issue a headline first.", true); els.title.focus(); return; }
    if (!meta.date) { toast("Give the issue a date first.", true); els.date.focus(); return; }

    state.saving = true;
    els.saveBtn.disabled = true;
    els.saveState.textContent = "Saving";

    api("/api/save", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ meta: meta, body: getBody(), original_file: state.file })
    }).then(function (res) {
      if (!res.ok) { toast(res.error || "Could not save.", true); markDirty(); return; }
      state.file = res.file;
      // Pin the web address. Otherwise it would follow the headline, and editing
      // the headline of a published issue would quietly break every link to it.
      if (!els.slug.value.trim() && res.slug) els.slug.value = res.slug;
      markClean(res.saved_at);
      toast(meta.draft ? "Saved as a draft"
                       : "Saved. Push it in GitHub Desktop to put it on pdbrief.org");
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
  document.addEventListener("keydown", function (e) {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s") { e.preventDefault(); save(); }
  });

  $("btn-delete").addEventListener("click", function () {
    if (!state.file) { toast("This issue has not been saved yet.", true); return; }
    if (!confirm("Delete this issue for good?\n\nThis cannot be undone from here.")) return;
    api("/api/delete", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file: state.file })
    }).then(function (res) {
      if (!res.ok) { toast(res.error || "Could not delete.", true); return; }
      toast("Issue deleted");
      state.file = null; state.dirty = false;
      return api("/api/new").then(function (r) {
        fill({ date: r.date, draft: true, papers: [blankPaper()], topics: [], body: "" });
        loadList(null);
      });
    });
  });

  window.addEventListener("beforeunload", function (e) {
    if (state.dirty) { e.preventDefault(); e.returnValue = ""; }
  });

  /* ---------------------------------------------------------------- wiring */

  [els.title, els.date, els.slug, els.summary].forEach(function (el) {
    el.addEventListener("input", markDirty);
  });
  els.draft.addEventListener("change", markDirty);
  els.title.addEventListener("input", function () { autosize(els.title); });

  $("btn-theme").addEventListener("click", function () {
    var root = document.documentElement;
    var dark = root.getAttribute("data-theme") === "dark";
    var next = dark ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try { localStorage.setItem("pdb-theme", next); } catch (e) {}
  });

  api("/api/glossary").then(function (res) { state.glossary = res.terms || []; });

  loadList()
    .then(function () { return api("/api/new"); })
    .then(function (res) {
      fill({ date: res.date, draft: true, papers: [blankPaper()], topics: [], body: "" });
    });
})();
