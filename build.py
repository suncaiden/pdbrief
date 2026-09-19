#!/usr/bin/env python3
"""
PD Brief static site generator.

Reads Markdown files from content/ and writes a complete static website to _site/.
No third-party dependencies -- runs on any Python 3.8+.

Usage:
    python3 build.py            # build the site into _site/
    python3 build.py --serve    # build, then serve at http://localhost:8000
    python3 build.py --check    # build and report problems, but write nothing
"""

import json
import os
import re
import shutil
import sys
import html as htmllib
from datetime import datetime, date, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.join(ROOT, "content")
ISSUES_DIR = os.path.join(CONTENT, "issues")
PAGES_DIR = os.path.join(CONTENT, "pages")
ASSETS = os.path.join(ROOT, "assets")
OUT = os.path.join(ROOT, "_site")

WARNINGS = []


def warn(msg):
    if msg not in WARNINGS:
        WARNINGS.append(msg)


# --------------------------------------------------------------------------
# Minimal YAML subset parser (frontmatter only)
# --------------------------------------------------------------------------
# Supports: key: value, nested mappings by indentation, lists of scalars,
# lists of mappings, inline lists [a, b], quoted strings, ints, bools, null.

def _scalar(raw):
    s = raw.strip()
    if s == "":
        return ""
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    low = s.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "~"):
        return None
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        return [_scalar(p) for p in _split_commas(inner)]
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    if re.fullmatch(r"-?\d+\.\d+", s):
        return float(s)
    return s


def _split_commas(s):
    """Split on commas that are not inside quotes."""
    parts, buf, quote = [], [], None
    for ch in s:
        if quote:
            if ch == quote:
                quote = None
            buf.append(ch)
        elif ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch == ",":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip() != ""]


def _indent_of(line):
    return len(line) - len(line.lstrip(" "))


def parse_yaml_block(lines, base_indent=0, start=0):
    """Parse a block of YAML lines. Returns (value, next_index)."""
    i = start
    # Skip blanks / comments
    while i < len(lines) and (not lines[i].strip() or lines[i].lstrip().startswith("#")):
        i += 1
    if i >= len(lines):
        return {}, i

    if lines[i].lstrip().startswith("- "):
        items = []
        indent = _indent_of(lines[i])
        while i < len(lines):
            line = lines[i]
            if not line.strip() or line.lstrip().startswith("#"):
                i += 1
                continue
            cur = _indent_of(line)
            if cur < indent or not line.lstrip().startswith("- "):
                break
            rest = line.lstrip()[2:]
            if ":" in rest and not rest.strip().startswith("http"):
                # list of mappings -- rebuild as a sub-block
                sub = [" " * (indent + 2) + rest]
                i += 1
                while i < len(lines):
                    nxt = lines[i]
                    if not nxt.strip():
                        i += 1
                        continue
                    if _indent_of(nxt) > indent and not nxt.lstrip().startswith("- "):
                        sub.append(nxt)
                        i += 1
                    else:
                        break
                val, _ = parse_yaml_block(sub, indent + 2, 0)
                items.append(val)
            else:
                items.append(_scalar(rest))
                i += 1
        return items, i

    mapping = {}
    indent = _indent_of(lines[i])
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        cur = _indent_of(line)
        if cur < indent:
            break
        if cur > indent:
            i += 1
            continue
        if ":" not in line:
            i += 1
            continue
        key, _, rest = line.strip().partition(":")
        key = key.strip()
        rest = rest.strip()
        if rest:
            mapping[key] = _scalar(rest)
            i += 1
        else:
            # nested block
            j = i + 1
            block = []
            while j < len(lines):
                nxt = lines[j]
                if not nxt.strip():
                    block.append(nxt)
                    j += 1
                    continue
                if _indent_of(nxt) > indent:
                    block.append(nxt)
                    j += 1
                else:
                    break
            if block:
                val, _ = parse_yaml_block(block, indent + 2, 0)
                mapping[key] = val
            else:
                mapping[key] = None
            i = j
    return mapping, i


def parse_frontmatter(text):
    """Split '---' delimited frontmatter from body. Returns (meta_dict, body_str)."""
    text = text.replace("\r\n", "\n").lstrip("﻿")
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    raw = text[3:end].strip("\n")
    body = text[end + 4:].lstrip("\n")
    meta, _ = parse_yaml_block(raw.split("\n"), 0, 0)
    if not isinstance(meta, dict):
        meta = {}
    return meta, body


# --------------------------------------------------------------------------
# Utilities
# --------------------------------------------------------------------------

def slugify(s):
    s = str(s).lower().strip()
    s = re.sub(r"['’]", "", s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "untitled"


def esc(s):
    return htmllib.escape(str(s), quote=True)


def parse_date(value, fallback_name=""):
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    s = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    warn("Could not read the date '%s' in %s -- using today instead. Use YYYY-MM-DD." % (s, fallback_name))
    return date.today()


def pretty_date(d):
    return "%s %d, %d" % (d.strftime("%B"), d.day, d.year)


def short_date(d):
    return "%s %d, %d" % (d.strftime("%b"), d.day, d.year)


def rfc822(d):
    return datetime(d.year, d.month, d.day, 12, 0, 0, tzinfo=timezone.utc).strftime(
        "%a, %d %b %Y %H:%M:%S +0000")


def reading_time(text):
    words = len(re.findall(r"[A-Za-z0-9'-]+", text))
    return max(1, round(words / 200.0))


def as_list(v):
    if v is None:
        return []
    if isinstance(v, list):
        return [x for x in v if x not in (None, "")]
    return [v]


def render(template, **vars_):
    """Replace {{name}} placeholders. Unknown placeholders become empty strings."""
    def sub(m):
        return str(vars_.get(m.group(1).strip(), ""))
    return re.sub(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}", sub, template)


def write(path, content):
    full = os.path.join(OUT, path.lstrip("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)


# --------------------------------------------------------------------------
# Markdown renderer
# --------------------------------------------------------------------------
# Supports: headings, paragraphs, bold/italic/code, links, images, ordered and
# unordered lists, blockquotes, horizontal rules, pipe tables, callout blocks
# (:::key ... :::), and {{glossary terms}}.

CALLOUT_LABELS = {
    "key": "Key takeaway",
    "note": "Note",
    "caution": "Important caution",
    "context": "Background",
    "plain": "In plain terms",
}

GLOSSARY = {}      # slug -> {"term":..., "definition":...}
GLOSSARY_USED = set()
PLAIN_GLOSS = False   # when True, glossary terms render as plain words (used for the RSS feed)


def inline(text):
    """Render inline markdown. Escapes HTML first, so raw HTML is not allowed."""
    placeholders = []

    def stash(html_str):
        placeholders.append(html_str)
        return "\x00%d\x00" % (len(placeholders) - 1)

    # Code spans first so their contents are never re-parsed.
    def code_sub(m):
        return stash("<code>%s</code>" % esc(m.group(1)))
    text = re.sub(r"`([^`]+)`", code_sub, text)

    text = esc(text)

    # Images
    def img_sub(m):
        alt, src = m.group(1), m.group(2)
        return stash('<img src="%s" alt="%s" loading="lazy">' % (src, alt))
    text = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)", img_sub, text)

    # Links
    def link_sub(m):
        label, href = m.group(1), m.group(2)
        ext = href.startswith("http")
        attrs = ' target="_blank" rel="noopener"' if ext else ""
        cls = ' class="ext"' if ext else ""
        return stash('<a href="%s"%s%s>%s</a>' % (href, cls, attrs, label))
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link_sub, text)

    # Glossary terms: {{term}} or {{term|words shown}}
    def gloss_sub(m):
        # This runs after esc(), so entities such as &#x27; are decoded first.
        inner = htmllib.unescape(m.group(1))
        term, _, shown = inner.partition("|")
        term = term.strip()
        shown = esc(shown.strip() or term)
        key = slugify(term)
        if PLAIN_GLOSS:
            return stash(shown)
        entry = GLOSSARY.get(key)
        if not entry:
            warn("Glossary term '%s' is used in an article but not defined in content/glossary.md" % term)
            return stash(shown)
        GLOSSARY_USED.add(key)
        return stash(
            '<button type="button" class="gloss" data-term="%s" data-def="%s" '
            'aria-expanded="false">%s</button>'
            % (esc(entry["term"]), esc(entry["definition"]), shown))
    text = re.sub(r"\{\{([^}]+)\}\}", gloss_sub, text)

    # Emphasis
    text = re.sub(r"\*\*\*(.+?)\*\*\*", r"<strong><em>\1</em></strong>", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", text)

    # Typography
    text = text.replace("--", "—")

    for idx, val in enumerate(placeholders):
        text = text.replace("\x00%d\x00" % idx, val)
    return text


def _is_block_start(line):
    ls = line.lstrip()
    return (ls.startswith("#") or ls.startswith("> ") or ls.startswith("- ")
            or ls.startswith("* ") or ls.startswith(":::") or ls.startswith("|")
            or re.match(r"^\d+\.\s", ls) or re.match(r"^-{3,}$", ls.strip()))


def markdown(src):
    lines = src.replace("\r\n", "\n").split("\n")
    out = []
    headings = []
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # Horizontal rule
        if re.fullmatch(r"-{3,}|\*{3,}", stripped):
            out.append("<hr>")
            i += 1
            continue

        # Callout block
        if stripped.startswith(":::"):
            name = stripped[3:].strip().lower() or "note"
            label = CALLOUT_LABELS.get(name, name.replace("-", " ").capitalize())
            body = []
            i += 1
            while i < n and lines[i].strip() != ":::":
                body.append(lines[i])
                i += 1
            i += 1  # consume closing :::
            inner, _ = markdown("\n".join(body))
            out.append(
                '<aside class="callout callout-%s"><p class="callout-label">%s</p>%s</aside>'
                % (esc(slugify(name)), esc(label), inner))
            continue

        # Heading
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            # "## Editorial policy {#policy}" pins a stable anchor for linking.
            custom = re.search(r"\s*\{#([A-Za-z0-9_-]+)\}\s*$", text)
            if custom:
                hid = custom.group(1)
                text = text[:custom.start()].strip()
            else:
                hid = slugify(text)
            if level in (2, 3):
                headings.append({"level": level, "text": re.sub(r"[*`]", "", text), "id": hid})
            out.append('<h%d id="%s">%s</h%d>' % (level, hid, inline(text), level))
            i += 1
            continue

        # Table
        if stripped.startswith("|"):
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(lines[i].strip())
                i += 1
            out.append(render_table(rows))
            continue

        # Blockquote
        if stripped.startswith(">"):
            body = []
            while i < n and lines[i].strip().startswith(">"):
                body.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            inner, _ = markdown("\n".join(body))
            out.append("<blockquote>%s</blockquote>" % inner)
            continue

        # Unordered list
        if re.match(r"^[-*]\s+", stripped):
            items, i = collect_list(lines, i, r"^[-*]\s+")
            out.append("<ul>%s</ul>" % "".join("<li>%s</li>" % it for it in items))
            continue

        # Ordered list
        if re.match(r"^\d+\.\s+", stripped):
            items, i = collect_list(lines, i, r"^\d+\.\s+")
            out.append("<ol>%s</ol>" % "".join("<li>%s</li>" % it for it in items))
            continue

        # Standalone image becomes a figure
        m = re.fullmatch(r"!\[([^\]]*)\]\(([^)\s]+)\)", stripped)
        if m:
            alt, src_ = m.group(1), m.group(2)
            cap = ('<figcaption>%s</figcaption>' % inline(alt)) if alt else ""
            out.append('<figure><img src="%s" alt="%s" loading="lazy">%s</figure>'
                       % (esc(src_), esc(alt), cap))
            i += 1
            continue

        # Paragraph
        buf = [stripped]
        i += 1
        while i < n and lines[i].strip() and not _is_block_start(lines[i]):
            buf.append(lines[i].strip())
            i += 1
        out.append("<p>%s</p>" % inline(" ".join(buf)))

    return "\n".join(out), headings


def collect_list(lines, i, pattern):
    """Gather consecutive list items, allowing wrapped continuation lines."""
    items = []
    n = len(lines)
    while i < n:
        stripped = lines[i].strip()
        if not stripped:
            # a blank line ends the list unless the next line continues it
            if i + 1 < n and re.match(pattern, lines[i + 1].strip()):
                i += 1
                continue
            break
        m = re.match(pattern, stripped)
        if not m:
            break
        text = stripped[m.end():]
        i += 1
        while i < n and lines[i].strip() and not _is_block_start(lines[i]):
            text += " " + lines[i].strip()
            i += 1
        items.append(inline(text))
    return items, i


def render_table(rows):
    def cells(row):
        return [c.strip() for c in row.strip().strip("|").split("|")]

    if not rows:
        return ""
    header = cells(rows[0])
    body_rows = rows[1:]
    if body_rows and re.fullmatch(r"[\s|:-]+", body_rows[0]):
        body_rows = body_rows[1:]

    head_html = "".join("<th scope='col'>%s</th>" % inline(c) for c in header)
    body_html = ""
    for r in body_rows:
        cs = cells(r)
        tds = ""
        for idx, c in enumerate(cs):
            tag = "th scope='row'" if idx == 0 else "td"
            close = "th" if idx == 0 else "td"
            tds += "<%s>%s</%s>" % (tag, inline(c), close)
        body_html += "<tr>%s</tr>" % tds
    return ("<div class='table-wrap'><table><thead><tr>%s</tr></thead>"
            "<tbody>%s</tbody></table></div>" % (head_html, body_html))


def plain_text(md_src, limit=None):
    """Strip markdown to plain text, for summaries and feed descriptions."""
    t = re.sub(r"^---.*?^---", "", md_src, flags=re.S | re.M)
    t = re.sub(r":::\w*", "", t)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    t = re.sub(r"\{\{([^}|]+)(\|[^}]*)?\}\}", r"\1", t)
    t = re.sub(r"[#>*_|]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    if limit and len(t) > limit:
        cut = t[:limit].rsplit(" ", 1)[0]
        return cut.rstrip(",.;:") + "…"
    return t


# --------------------------------------------------------------------------
# Templates
# --------------------------------------------------------------------------

LAYOUT = """<!doctype html>
<html lang="{{lang}}" data-theme="">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{page_title}}</title>
<meta name="description" content="{{page_description}}">
<link rel="canonical" href="{{canonical}}">
<meta property="og:type" content="{{og_type}}">
<meta property="og:site_name" content="{{site_title}}">
<meta property="og:title" content="{{og_title}}">
<meta property="og:description" content="{{page_description}}">
<meta property="og:url" content="{{canonical}}">
<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#fcfaf5">
<link rel="alternate" type="application/rss+xml" title="{{site_title}} weekly issues" href="/feed.xml">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&display=swap">
<link rel="stylesheet" href="/assets/style.css?v={{cachebust}}">
<script>
/* Applied before paint so the page never flashes the wrong theme or size. */
(function(){try{
var d=document.documentElement;
var t=localStorage.getItem('pdb-theme'); if(t){d.setAttribute('data-theme',t);}
var s=localStorage.getItem('pdb-textsize'); if(s){d.setAttribute('data-textsize',s);}
}catch(e){}})();
</script>
{{extra_head}}
</head>
<body class="{{body_class}}">
<a class="skip" href="#main">Skip to content</a>

<header class="site-header">
  <div class="wrap header-inner">
    <a class="brand" href="/">
      <span class="brand-mark" aria-hidden="true">
        <svg viewBox="0 0 32 32" width="32" height="32" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <path d="M6 24c0-8 4-12 10-12s10 4 10 12"/><circle cx="16" cy="7" r="3"/>
          <path d="M11 24v-5M16 24v-8M21 24v-5"/>
        </svg>
      </span>
      <span class="brand-text">
        <span class="brand-name">{{site_title}}</span>
        <span class="brand-sub">Parkinson's research, explained</span>
      </span>
    </a>

    <button class="nav-toggle" aria-expanded="false" aria-controls="site-nav">
      <span class="nav-toggle-bars" aria-hidden="true"><span></span><span></span><span></span></span>
      <span class="nav-toggle-label">Menu</span>
    </button>

    <nav id="site-nav" class="site-nav" aria-label="Main">
      {{nav_links}}
      <div class="nav-tools">
        <div class="tool-group" role="group" aria-label="Text size">
          <span class="tool-label" aria-hidden="true">Text</span>
          <button class="tool-btn" data-size="normal" title="Normal text size">A</button>
          <button class="tool-btn" data-size="large" title="Large text size">A</button>
          <button class="tool-btn" data-size="xlarge" title="Largest text size">A</button>
        </div>
        <button class="tool-btn theme-btn" id="theme-btn" title="Switch between light and dark">
          <span class="theme-icon" aria-hidden="true"></span>
          <span class="sr-only">Switch colour theme</span>
        </button>
      </div>
    </nav>
  </div>
</header>

<main id="main">
{{content}}
</main>

<footer class="site-footer">
  <div class="wrap footer-grid">
    <div class="footer-about">
      <p class="footer-name">{{site_title}}</p>
      <p class="footer-blurb">{{site_description}}</p>
    </div>
    <div class="footer-col">
      <p class="footer-head">Read</p>
      {{footer_nav}}
    </div>
    <div class="footer-col">
      <p class="footer-head">More</p>
      {{footer_links}}
    </div>
  </div>
  <div class="wrap footer-bottom">
    <p class="disclaimer"><strong>This is not medical advice.</strong> {{site_title}} summarises published
    research for general understanding. Nothing here is a recommendation for your own care. Always talk to
    your neurologist or doctor before changing anything about your treatment.</p>
    <p class="copyright">&copy; {{year}} {{site_title}}. Independent and not affiliated with any journal,
    university, company, or advocacy organisation. Summaries are written by a human editor; all findings
    belong to the researchers who published them.</p>
  </div>
</footer>

<div class="gloss-pop" id="gloss-pop" role="dialog" aria-live="polite" hidden>
  <p class="gloss-term" id="gloss-pop-term"></p>
  <p class="gloss-def" id="gloss-pop-def"></p>
  <button class="gloss-close" id="gloss-close" aria-label="Close definition">&times;</button>
</div>

<script src="/assets/site.js?v={{cachebust}}"></script>
{{extra_body}}
</body>
</html>
"""


def issue_card(it, featured=False):
    topics = "".join(
        '<a class="tag" href="/topics/%s/">%s</a>' % (slugify(t), esc(t))
        for t in it["topics"][:3])
    papers = ""
    if it["papers"]:
        p = it["papers"][0]
        extra = ""
        if len(it["papers"]) > 1:
            extra = ' <span class="card-more">+%d more</span>' % (len(it["papers"]) - 1)
        papers = ('<p class="card-source"><span class="card-source-label">Study:</span> %s%s</p>'
                  % (esc(p.get("journal", "")), extra))
    cls = "card card-featured" if featured else "card"
    return """<article class="%s">
  <div class="card-meta">
    <span class="issue-no">Issue %s</span>
    <span class="dot" aria-hidden="true">&middot;</span>
    <time datetime="%s">%s</time>
    <span class="dot" aria-hidden="true">&middot;</span>
    <span class="read-time">%s min read</span>
  </div>
  <h3 class="card-title"><a href="%s">%s</a></h3>
  <p class="card-summary">%s</p>
  %s
  <div class="card-foot"><div class="tags">%s</div>
    <a class="card-link" href="%s">Read the summary <span aria-hidden="true">&rarr;</span></a></div>
</article>""" % (cls, it["number"], it["date"].isoformat(), short_date(it["date"]),
                 it["reading_time"], it["url"], esc(it["title"]), esc(it["summary"]),
                 papers, topics, it["url"])


def paper_block(papers):
    """The 'what was studied' source box shown on each issue page."""
    if not papers:
        return ""
    rows = []
    for p in papers:
        title = esc(p.get("title", "Untitled study"))
        link = p.get("url") or (("https://doi.org/" + str(p["doi"])) if p.get("doi") else "")
        title_html = ('<a href="%s" target="_blank" rel="noopener">%s</a>' % (esc(link), title)
                      if link else title)
        bits = []
        if p.get("authors"):
            bits.append(esc(p["authors"]))
        if p.get("journal"):
            bits.append("<em>%s</em>" % esc(p["journal"]))
        if p.get("year"):
            bits.append(esc(p["year"]))
        meta = ", ".join(bits)
        doi = ('<p class="paper-doi">DOI: <a href="https://doi.org/%s" target="_blank" rel="noopener">%s</a></p>'
               % (esc(p["doi"]), esc(p["doi"]))) if p.get("doi") else ""
        access = ""
        if p.get("access"):
            label = str(p["access"])
            cls = "open" if "open" in label.lower() or "free" in label.lower() else "closed"
            access = '<span class="access access-%s">%s</span>' % (cls, esc(label))
        rows.append('<li class="paper"><p class="paper-title">%s %s</p><p class="paper-meta">%s</p>%s</li>'
                    % (title_html, access, meta, doi))
    heading = "The study behind this issue" if len(papers) == 1 else "The studies behind this issue"
    return ('<section class="papers" aria-label="Source studies"><h2 class="papers-head">%s</h2>'
            '<ul class="paper-list">%s</ul>'
            '<p class="papers-note">Follow the links to read the original papers. '
            'Some journals charge for access; abstracts are usually free.</p></section>'
            % (heading, "".join(rows)))


# --------------------------------------------------------------------------
# Content loading
# --------------------------------------------------------------------------

def load_config():
    with open(os.path.join(ROOT, "site.json"), encoding="utf-8") as f:
        return json.load(f)


def load_glossary():
    path = os.path.join(CONTENT, "glossary.md")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        _, body = parse_frontmatter(f.read())
    entries = []
    for block in re.split(r"\n(?=##\s)", body):
        m = re.match(r"##\s+(.+)", block.strip())
        if not m:
            continue
        term = m.group(1).strip()
        definition = plain_text(block[m.end():])
        if not definition:
            warn("Glossary term '%s' has no definition under it." % term)
            continue
        entry = {"term": term, "definition": definition, "slug": slugify(term)}
        entries.append(entry)
        GLOSSARY[entry["slug"]] = entry
        # allow a plural form to resolve to the same entry
        if not term.endswith("s"):
            GLOSSARY.setdefault(slugify(term + "s"), entry)
    entries.sort(key=lambda e: e["term"].lower())
    return entries


def load_issues(cfg):
    items = []
    if not os.path.isdir(ISSUES_DIR):
        return items
    for name in sorted(os.listdir(ISSUES_DIR)):
        if not name.endswith(".md") or name.startswith("_"):
            continue
        path = os.path.join(ISSUES_DIR, name)
        with open(path, encoding="utf-8") as f:
            meta, body = parse_frontmatter(f.read())

        if str(meta.get("draft", "")).lower() in ("true", "yes", "1"):
            continue

        title = meta.get("title") or name[:-3].replace("-", " ").title()
        if not meta.get("title"):
            warn("%s has no 'title:' in its frontmatter." % name)

        d = parse_date(meta.get("date", name[:10]), name)
        slug = meta.get("slug") or re.sub(r"^\d{4}-\d{2}-\d{2}-", "", name[:-3])
        slug = slugify(slug)

        papers = []
        for p in as_list(meta.get("papers")):
            papers.append(p if isinstance(p, dict) else {"title": str(p)})

        summary = meta.get("summary") or plain_text(body, 200)
        if not meta.get("summary"):
            warn("%s has no 'summary:' -- one was generated from the first lines." % name)

        items.append({
            "file": name,
            "title": str(title),
            "date": d,
            "slug": slug,
            "url": "/issues/%s/" % slug,
            "topics": [str(t) for t in as_list(meta.get("topics"))],
            "papers": papers,
            "summary": str(summary),
            "body": body,
            "reading_time": reading_time(body),
            "number": meta.get("issue"),
            "meta": meta,
        })

    items.sort(key=lambda x: (x["date"], x["file"]))
    for idx, it in enumerate(items, start=1):
        if not it["number"]:
            it["number"] = idx
    items.sort(key=lambda x: (x["date"], x["number"]), reverse=True)

    seen = {}
    for it in items:
        if it["slug"] in seen:
            warn("Two issues share the slug '%s' (%s and %s). One will overwrite the other."
                 % (it["slug"], it["file"], seen[it["slug"]]))
        seen[it["slug"]] = it["file"]
    return items


def load_pages():
    pages = []
    if not os.path.isdir(PAGES_DIR):
        return pages
    for name in sorted(os.listdir(PAGES_DIR)):
        if not name.endswith(".md"):
            continue
        with open(os.path.join(PAGES_DIR, name), encoding="utf-8") as f:
            meta, body = parse_frontmatter(f.read())
        slug = meta.get("slug") or name[:-3]
        pages.append({
            "title": meta.get("title", slug.replace("-", " ").title()),
            "slug": slugify(slug),
            "description": meta.get("description", ""),
            "body": body,
            "meta": meta,
        })
    return pages


# --------------------------------------------------------------------------
# Page rendering
# --------------------------------------------------------------------------

def page_shell(cfg, content, title=None, description=None, path="/",
               og_type="website", body_class="", extra_head="", extra_body=""):
    nav_links = "".join(
        '<a class="nav-link%s" href="%s">%s</a>'
        % (" current" if item["href"] == path else "", item["href"], esc(item["label"]))
        for item in cfg.get("nav", []))
    footer_nav = "".join(
        '<a href="%s">%s</a>' % (item["href"], esc(item["label"]))
        for item in cfg.get("nav", []))
    links = list(cfg.get("footer_links", []))
    if cfg.get("feedback_form_url") and not any(l.get("href") == "/ask/" for l in links):
        links.insert(0, {"label": "Ask a question", "href": "/ask/"})
    footer_links = "".join(
        '<a href="%s">%s</a>' % (item["href"], esc(item["label"]))
        for item in links)
    full_title = cfg["title"] if title is None else "%s | %s" % (title, cfg["title"])
    desc = description or cfg["description"]
    return render(
        LAYOUT,
        lang=cfg.get("language", "en"),
        page_title=esc(full_title),
        og_title=esc(title or cfg["title"]),
        page_description=esc(plain_text(desc, 300)),
        canonical=cfg["url"].rstrip("/") + path,
        og_type=og_type,
        site_title=esc(cfg["title"]),
        site_description=esc(cfg["description"]),
        nav_links=nav_links,
        footer_nav=footer_nav,
        footer_links=footer_links,
        content=content,
        year=date.today().year,
        body_class=body_class,
        extra_head=extra_head,
        extra_body=extra_body,
        cachebust=CACHEBUST,
    )


def subscribe_block(cfg):
    if cfg.get("subscribe_url"):
        return ("""<section class="subscribe"><div class="wrap subscribe-inner">
        <h2>Get each issue by email</h2>
        <p>One short email a week. No cost, no advertising, unsubscribe whenever you like.</p>
        <a class="btn btn-primary" href="%s" target="_blank" rel="noopener">Subscribe</a>
        </div></section>""" % esc(cfg["subscribe_url"]))
    return """<section class="subscribe"><div class="wrap subscribe-inner">
      <h2>Follow along</h2>
      <p>New issues land every week. Subscribe with any RSS reader, or bookmark the archive.</p>
      <div class="subscribe-actions">
        <a class="btn btn-primary" href="/feed.xml">RSS feed</a>
        <a class="btn btn-quiet" href="/archive/">Browse the archive</a>
      </div>
    </div></section>"""


def build_home(cfg, issues):
    if not issues:
        body = ('<div class="wrap"><div class="empty"><h1>No issues yet</h1>'
                '<p>Add your first Markdown file to <code>content/issues/</code> and rebuild.</p></div></div>')
        return page_shell(cfg, body, path="/")

    latest = issues[0]
    rest = issues[1:7]
    topics_html = "".join('<a class="tag" href="/topics/%s/">%s</a>' % (slugify(t), esc(t))
                          for t in latest["topics"][:4])

    hero = """<section class="hero">
  <div class="wrap">
    <p class="eyebrow">Independent &middot; Weekly &middot; Free to read</p>
    <h1 class="hero-title">%s</h1>
    <p class="hero-tagline">%s</p>
    <p class="hero-note">%s</p>
  </div>
</section>

<section class="latest">
  <div class="wrap">
    <div class="section-head">
      <h2 class="section-title">This week's issue</h2>
      <a class="section-link" href="/archive/">All issues <span aria-hidden="true">&rarr;</span></a>
    </div>
    <article class="feature">
      <div class="card-meta">
        <span class="issue-no">Issue %s</span>
        <span class="dot" aria-hidden="true">&middot;</span>
        <time datetime="%s">%s</time>
        <span class="dot" aria-hidden="true">&middot;</span>
        <span class="read-time">%s min read</span>
      </div>
      <h3 class="feature-title"><a href="%s">%s</a></h3>
      <p class="feature-summary">%s</p>
      <div class="tags">%s</div>
      <a class="btn btn-primary" href="%s">Read this issue</a>
    </article>
  </div>
</section>""" % (esc(cfg["tagline"]), esc(cfg["description"]),
                 "%d issue%s published since %s." % (
                     len(issues), "" if len(issues) == 1 else "s",
                     issues[-1]["date"].strftime("%B %Y")),
                 latest["number"], latest["date"].isoformat(), pretty_date(latest["date"]),
                 latest["reading_time"], latest["url"], esc(latest["title"]),
                 esc(latest["summary"]), topics_html, latest["url"])

    what = """<section class="explainer">
  <div class="wrap">
    <div class="explainer-grid">
      <div class="explainer-item">
        <span class="explainer-num">1</span>
        <h3>We read the new research</h3>
        <p>Every week we go through newly published Parkinson's studies in the medical
        journals and pick one or two that genuinely move the field.</p>
      </div>
      <div class="explainer-item">
        <span class="explainer-num">2</span>
        <h3>We translate it</h3>
        <p>No jargon without an explanation. We say what the researchers did, what they
        found, and how confident anyone should be about it.</p>
      </div>
      <div class="explainer-item">
        <span class="explainer-num">3</span>
        <h3>The archive builds up</h3>
        <p>Each issue joins a growing record, so you can follow how an idea developed
        over months and years instead of seeing one headline in isolation.</p>
      </div>
    </div>
  </div>
</section>"""

    recent = ""
    if rest:
        recent = ("""<section class="recent"><div class="wrap">
    <div class="section-head"><h2 class="section-title">Earlier issues</h2></div>
    <div class="card-grid">%s</div>
    <div class="center"><a class="btn btn-quiet" href="/archive/">See the full archive</a></div>
    </div></section>""" % "".join(issue_card(it) for it in rest))

    return page_shell(cfg, hero + what + recent + subscribe_block(cfg), path="/")


def feedback_link(cfg):
    """The address of the questions page, if one has been set up."""
    return "/ask/" if cfg.get("feedback_form_url") else ""


def ask_invitation(cfg):
    """A short invitation shown at the end of each issue."""
    if not cfg.get("feedback_form_url"):
        return ""
    return ('<aside class="ask-invite">'
            '<h2 class="ask-invite-head">Something here unclear?</h2>'
            '<p>If a part of this issue did not make sense, or you want to know more about '
            'the study behind it, ask. Questions shape what gets covered and how it gets '
            'explained &mdash; and asking one helps the next reader too.</p>'
            '<a class="btn btn-primary" href="/ask/">Ask a question</a>'
            '</aside>')


def embeddable_form(url):
    """Turn a Google Form link into one that can be shown inside the page.

    Returns None when the address cannot be embedded, which is the case for
    forms.gle short links -- those only work as ordinary links.
    """
    u = str(url or "").strip()
    if "docs.google.com/forms" not in u:
        return None
    u = u.split("?")[0].rstrip("/")
    if u.endswith("/edit") or "/d/e/" not in u:
        return None
    if not u.endswith("/viewform"):
        u += "/viewform"
    return u + "?embedded=true"


def build_feedback_page(cfg):
    url = cfg.get("feedback_form_url", "")
    embed_url = embeddable_form(url) if cfg.get("feedback_embed", True) else None

    if cfg.get("feedback_embed", True) and not embed_url:
        warn("The feedback form cannot be shown inside the page, so it is linked instead. "
             "For an embedded form use the full docs.google.com/forms/d/e/.../viewform "
             "address rather than a forms.gle short link.")

    if embed_url:
        form_html = (
            '<div class="form-frame">'
            '<iframe src="%s" title="Questions and feedback form" '
            'width="100%%" height="900" frameborder="0" marginheight="0" marginwidth="0" '
            'loading="lazy">Loading the form&hellip;</iframe>'
            '</div>'
            '<p class="form-note">This form is hosted by Google, so opening this page '
            'contacts Google&rsquo;s servers. If you would rather not, you can '
            '<a href="%s" target="_blank" rel="noopener">open the form in a new tab</a> '
            'instead, or write to us another way.</p>' % (esc(embed_url), esc(url)))
    else:
        form_html = (
            '<div class="form-cta">'
            '<a class="btn btn-primary btn-big" href="%s" target="_blank" rel="noopener">'
            'Open the question form</a>'
            '<p class="form-note">The form opens in a new tab and is hosted by Google.</p>'
            '</div>' % esc(url))

    content = """<div class="page-head"><div class="wrap wrap-narrow">
      <h1>Ask a question</h1>
      <p class="page-lede">If something in an issue did not make sense, or you want to know
      more about a study, this is the place to say so. There is no such thing as a question
      that is too basic &mdash; if something was unclear to you, it was probably unclear to
      other readers too.</p>
    </div></div>

    <div class="wrap wrap-narrow ask-page">
      <section class="ask-what">
        <h2>What you can send</h2>
        <ul class="ask-list">
          <li><strong>A question about an issue.</strong> Which part lost you, and what you
          were trying to understand.</li>
          <li><strong>A study worth covering.</strong> A link or a title is enough.</li>
          <li><strong>A correction.</strong> If something here is wrong, we want to know.
          Corrections are published on the issue itself rather than quietly fixed.</li>
          <li><strong>A term for the glossary.</strong> Any word you had to look up
          elsewhere is a word that belongs in the glossary.</li>
        </ul>
      </section>

      %s

      <aside class="callout callout-caution">
        <p class="callout-label">Please do not send medical questions</p>
        <p>We cannot advise on anyone&rsquo;s treatment, symptoms, or medication, and we will
        not try. Those questions belong with your neurologist or doctor, who knows your
        history. What we can do is explain what a piece of research found.</p>
      </aside>
    </div>""" % form_html

    return page_shell(cfg, content, title="Ask a question",
                      description="Send a question, a correction, or a study worth covering "
                                  "to %s." % cfg["title"],
                      path="/ask/")


def build_issue(cfg, it, prev_issue, next_issue):
    body_html, headings = markdown(it["body"])

    toc = ""
    if len(headings) >= 3:
        links = "".join('<li class="toc-l%d"><a href="#%s">%s</a></li>'
                        % (h["level"], h["id"], esc(h["text"])) for h in headings)
        toc = ('<nav class="toc" aria-label="On this page"><p class="toc-head">On this page</p>'
               '<ul>%s</ul></nav>' % links)

    topics_html = "".join('<a class="tag" href="/topics/%s/">%s</a>' % (slugify(t), esc(t))
                          for t in it["topics"])

    nav_prev = ('<a class="pager-item pager-prev" href="%s"><span class="pager-label">'
                '&larr; Previous issue</span><span class="pager-title">%s</span></a>'
                % (prev_issue["url"], esc(prev_issue["title"]))) if prev_issue else "<span></span>"
    nav_next = ('<a class="pager-item pager-next" href="%s"><span class="pager-label">'
                'Next issue &rarr;</span><span class="pager-title">%s</span></a>'
                % (next_issue["url"], esc(next_issue["title"]))) if next_issue else "<span></span>"

    schema = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": it["title"],
        "description": plain_text(it["summary"], 300),
        "datePublished": it["date"].isoformat(),
        "author": {"@type": "Organization", "name": cfg["title"]},
        "publisher": {"@type": "Organization", "name": cfg["title"]},
        "mainEntityOfPage": cfg["url"].rstrip("/") + it["url"],
        "isAccessibleForFree": True,
    }
    if it["papers"]:
        schema["citation"] = [
            {"@type": "ScholarlyArticle", "name": p.get("title", ""),
             "identifier": ("https://doi.org/%s" % p["doi"]) if p.get("doi") else p.get("url", "")}
            for p in it["papers"]]
    extra_head = ('<script type="application/ld+json">%s</script>'
                  % json.dumps(schema, ensure_ascii=False))

    content = """<article class="issue">
  <header class="issue-header">
    <div class="wrap wrap-narrow">
      <div class="issue-crumbs"><a href="/archive/">Archive</a>
        <span aria-hidden="true">/</span> <span>Issue %s</span></div>
      <h1 class="issue-title">%s</h1>
      <p class="issue-summary">%s</p>
      <div class="issue-meta">
        <time datetime="%s">%s</time>
        <span class="dot" aria-hidden="true">&middot;</span>
        <span>%s min read</span>
      </div>
      <div class="tags">%s</div>
    </div>
  </header>

  <div class="wrap wrap-narrow issue-body">
    %s
    <div class="prose">
      %s
    </div>
    %s
  </div>

  <div class="wrap wrap-narrow">
    %s
    <nav class="pager" aria-label="Other issues">%s%s</nav>
  </div>
</article>""" % (it["number"], esc(it["title"]), esc(it["summary"]),
                 it["date"].isoformat(), pretty_date(it["date"]), it["reading_time"],
                 topics_html, toc, body_html, paper_block(it["papers"]),
                 ask_invitation(cfg), nav_prev, nav_next)

    return page_shell(cfg, content, title=it["title"], description=it["summary"],
                      path=it["url"], og_type="article", body_class="page-issue",
                      extra_head=extra_head)


def build_archive(cfg, issues):
    by_year = {}
    for it in issues:
        by_year.setdefault(it["date"].year, []).append(it)

    all_topics = sorted({t for it in issues for t in it["topics"]}, key=str.lower)
    filters = "".join('<button class="filter" data-topic="%s">%s</button>'
                      % (slugify(t), esc(t)) for t in all_topics)

    sections = []
    for year in sorted(by_year, reverse=True):
        rows = []
        for it in by_year[year]:
            topics_attr = " ".join(slugify(t) for t in it["topics"])
            tags = "".join('<span class="tag tag-static">%s</span>' % esc(t) for t in it["topics"][:3])
            rows.append("""<li class="arch-row" data-topics="%s">
  <a class="arch-link" href="%s">
    <span class="arch-no">%s</span>
    <span class="arch-main">
      <span class="arch-title">%s</span>
      <span class="arch-summary">%s</span>
      <span class="tags">%s</span>
    </span>
    <span class="arch-date"><time datetime="%s">%s</time></span>
  </a></li>""" % (topics_attr, it["url"], it["number"], esc(it["title"]),
                  esc(plain_text(it["summary"], 150)), tags,
                  it["date"].isoformat(), short_date(it["date"])))
        sections.append('<section class="arch-year"><h2 class="year-head">%d</h2>'
                        '<ul class="arch-list">%s</ul></section>' % (year, "".join(rows)))

    content = """<div class="page-head">
  <div class="wrap">
    <h1>Archive</h1>
    <p class="page-lede">Every issue of %s, newest first. %d issue%s so far, covering
    %d topic%s. Search or filter to find what you need.</p>
  </div>
</div>
<div class="wrap archive">
  <div class="archive-controls">
    <div class="search-wrap">
      <label class="sr-only" for="archive-search">Search issues</label>
      <input type="search" id="archive-search" placeholder="Search titles, summaries, topics&hellip;"
             autocomplete="off">
    </div>
    <div class="filters" role="group" aria-label="Filter by topic">
      <button class="filter is-active" data-topic="all">All</button>%s
    </div>
  </div>
  <p class="results-count" id="results-count" aria-live="polite"></p>
  %s
  <p class="no-results" id="no-results" hidden>No issues match that. Try a different word or clear the filter.</p>
</div>""" % (esc(cfg["title"]), len(issues), "" if len(issues) == 1 else "s",
             len(all_topics), "" if len(all_topics) == 1 else "s", filters, "".join(sections))

    return page_shell(cfg, content, title="Archive",
                      description="Every issue of %s -- weekly plain-language summaries of "
                                  "newly published Parkinson's disease research." % cfg["title"],
                      path="/archive/", body_class="page-archive")


def build_topics_index(cfg, issues):
    counts = {}
    for it in issues:
        for t in it["topics"]:
            counts.setdefault(t, []).append(it)
    if not counts:
        counts = {}

    cards = "".join("""<a class="topic-card" href="/topics/%s/">
      <h2 class="topic-name">%s</h2>
      <p class="topic-count">%d issue%s</p>
      <p class="topic-latest">Most recent: %s</p></a>"""
      % (slugify(t), esc(t), len(v), "" if len(v) == 1 else "s", short_date(v[0]["date"]))
      for t, v in sorted(counts.items(), key=lambda kv: (-len(kv[1]), kv[0].lower())))

    content = """<div class="page-head"><div class="wrap">
      <h1>Topics</h1>
      <p class="page-lede">Parkinson's research moves along several tracks at once. Follow a single
      thread to see how the thinking has developed issue by issue.</p>
    </div></div>
    <div class="wrap"><div class="topic-grid">%s</div></div>""" % (cards or
      '<p class="empty-note">Topics appear here once your issues have <code>topics:</code> set.</p>')

    return page_shell(cfg, content, title="Topics",
                      description="Browse Parkinson's disease research summaries by topic.",
                      path="/topics/")


def build_topic_page(cfg, topic, items):
    content = """<div class="page-head"><div class="wrap">
      <p class="eyebrow"><a href="/topics/">Topics</a></p>
      <h1>%s</h1>
      <p class="page-lede">%d issue%s on this topic, newest first.</p>
    </div></div>
    <div class="wrap"><div class="card-grid">%s</div></div>""" % (
        esc(topic), len(items), "" if len(items) == 1 else "s",
        "".join(issue_card(it) for it in items))
    return page_shell(cfg, content, title=topic,
                      description="Parkinson's research summaries about %s." % topic,
                      path="/topics/%s/" % slugify(topic))


def build_glossary(cfg, entries):
    if not entries:
        content = ('<div class="page-head"><div class="wrap"><h1>Glossary</h1>'
                   '<p class="page-lede">Add terms to <code>content/glossary.md</code>.</p></div></div>')
        return page_shell(cfg, content, title="Glossary", path="/glossary/")

    groups = {}
    for e in entries:
        groups.setdefault(e["term"][0].upper(), []).append(e)

    jump = "".join('<a href="#letter-%s">%s</a>' % (k, k) for k in sorted(groups))
    blocks = []
    for letter in sorted(groups):
        items = "".join('<div class="gl-entry" id="term-%s"><dt>%s</dt><dd>%s</dd></div>'
                        % (e["slug"], esc(e["term"]), inline(e["definition"]))
                        for e in groups[letter])
        blocks.append('<section class="gl-group"><h2 id="letter-%s" class="gl-letter">%s</h2>'
                      '<dl class="gl-list">%s</dl></section>' % (letter, letter, items))

    content = """<div class="page-head"><div class="wrap">
      <h1>Glossary</h1>
      <p class="page-lede">Plain-language definitions of the terms that come up in Parkinson's
      research. Any underlined word inside an issue can be tapped to see its meaning without
      leaving the page.</p>
    </div></div>
    <div class="wrap wrap-narrow">
      <nav class="gl-jump" aria-label="Jump to letter">%s</nav>
      <div class="search-wrap gl-search-wrap">
        <label class="sr-only" for="gloss-search">Search the glossary</label>
        <input type="search" id="gloss-search" placeholder="Search terms&hellip;" autocomplete="off">
      </div>
      %s
      <p class="no-results" id="gl-no-results" hidden>No terms match that.</p>
    </div>""" % (jump, "".join(blocks))

    return page_shell(cfg, content, title="Glossary",
                      description="Plain-language definitions of Parkinson's disease research terms.",
                      path="/glossary/", body_class="page-glossary")


def build_static_page(cfg, page):
    body_html, _ = markdown(page["body"])
    content = """<div class="page-head"><div class="wrap wrap-narrow">
      <h1>%s</h1></div></div>
      <div class="wrap wrap-narrow"><div class="prose">%s</div></div>""" % (
        esc(page["title"]), body_html)
    return page_shell(cfg, content, title=page["title"],
                      description=page["description"] or plain_text(page["body"], 200),
                      path="/%s/" % page["slug"])


def build_404(cfg, issues):
    recent = "".join(issue_card(it) for it in issues[:3])
    content = """<div class="wrap wrap-narrow notfound">
      <p class="eyebrow">404</p>
      <h1>That page isn't here</h1>
      <p class="page-lede">The link may be old, or the address may have a typo. The archive has
      every issue we have published.</p>
      <p><a class="btn btn-primary" href="/archive/">Go to the archive</a></p>
    </div>
    <div class="wrap"><div class="card-grid">%s</div></div>""" % recent
    return page_shell(cfg, content, title="Page not found", path="/404.html")


# --------------------------------------------------------------------------
# Feeds and machine-readable files
# --------------------------------------------------------------------------

def build_feed(cfg, issues):
    global PLAIN_GLOSS
    base = cfg["url"].rstrip("/")
    items = []
    PLAIN_GLOSS = True
    for it in issues[:25]:
        body_html, _ = markdown(it["body"])
        items.append("""  <item>
    <title>%s</title>
    <link>%s%s</link>
    <guid isPermaLink="true">%s%s</guid>
    <pubDate>%s</pubDate>
    <description>%s</description>
    <content:encoded><![CDATA[%s]]></content:encoded>
%s  </item>""" % (esc(it["title"]), base, it["url"], base, it["url"],
                  rfc822(it["date"]), esc(it["summary"]), body_html,
                  "".join("    <category>%s</category>\n" % esc(t) for t in it["topics"])))

    PLAIN_GLOSS = False
    last = rfc822(issues[0]["date"]) if issues else rfc822(date.today())
    return """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"
     xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel>
  <title>%s</title>
  <link>%s/</link>
  <atom:link href="%s/feed.xml" rel="self" type="application/rss+xml"/>
  <description>%s</description>
  <language>%s</language>
  <lastBuildDate>%s</lastBuildDate>
%s
</channel>
</rss>
""" % (esc(cfg["title"]), base, base, esc(cfg["description"]),
       cfg.get("language", "en"), last, "\n".join(items))


def build_sitemap(cfg, urls):
    base = cfg["url"].rstrip("/")
    entries = "".join(
        "  <url><loc>%s%s</loc>%s</url>\n"
        % (base, u["path"], ("<lastmod>%s</lastmod>" % u["lastmod"]) if u.get("lastmod") else "")
        for u in urls)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n%s</urlset>\n' % entries)


FAVICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
<rect width="32" height="32" rx="7" fill="#8a3324"/>
<g fill="none" stroke="#ffffff" stroke-width="2.2" stroke-linecap="round">
<path d="M7 24c0-8 4-12 9-12s9 4 9 12"/><circle cx="16" cy="7.5" r="2.8"/>
<path d="M11.5 24v-4.5M16 24v-7M20.5 24v-4.5"/></g></svg>
"""


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

CACHEBUST = datetime.now().strftime("%Y%m%d%H%M")




def clear_output():
    """Empty _site/ without deleting the directory itself, so a running
    preview server keeps its working directory valid across rebuilds."""
    os.makedirs(OUT, exist_ok=True)
    for name in os.listdir(OUT):
        path = os.path.join(OUT, name)
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        else:
            os.remove(path)


def generate(check_only=False, quiet=False):
    """Build the whole site. Returns the number of issues published."""
    global CACHEBUST
    CACHEBUST = datetime.now().strftime("%Y%m%d%H%M%S")
    del WARNINGS[:]
    GLOSSARY.clear()
    GLOSSARY_USED.clear()

    cfg = load_config()
    glossary_entries = load_glossary()
    issues = load_issues(cfg)
    pages = load_pages()

    if not check_only:
        clear_output()

    written = []

    def emit(path, content):
        written.append(path)
        if not check_only:
            write(path, content)

    # issues[] is newest first, so the "previous" issue sits at the next index.
    for idx, it in enumerate(issues):
        older = issues[idx + 1] if idx + 1 < len(issues) else None
        newer = issues[idx - 1] if idx > 0 else None
        emit("issues/%s/index.html" % it["slug"], build_issue(cfg, it, older, newer))

    emit("index.html", build_home(cfg, issues))
    emit("archive/index.html", build_archive(cfg, issues))
    emit("topics/index.html", build_topics_index(cfg, issues))

    topics = {}
    for it in issues:
        for t in it["topics"]:
            topics.setdefault(t, []).append(it)
    for topic, items in topics.items():
        emit("topics/%s/index.html" % slugify(topic), build_topic_page(cfg, topic, items))

    emit("glossary/index.html", build_glossary(cfg, glossary_entries))
    if cfg.get("feedback_form_url"):
        emit("ask/index.html", build_feedback_page(cfg))
    for page in pages:
        emit("%s/index.html" % page["slug"], build_static_page(cfg, page))

    emit("404.html", build_404(cfg, issues))
    emit("feed.xml", build_feed(cfg, issues))
    emit("favicon.svg", FAVICON)

    urls = [{"path": "/", "lastmod": issues[0]["date"].isoformat() if issues else None},
            {"path": "/archive/"}, {"path": "/topics/"}, {"path": "/glossary/"}]
    urls += [{"path": it["url"], "lastmod": it["date"].isoformat()} for it in issues]
    urls += [{"path": "/topics/%s/" % slugify(t)} for t in topics]
    urls += [{"path": "/%s/" % p["slug"]} for p in pages]
    if cfg.get("feedback_form_url"):
        urls.append({"path": "/ask/"})
    emit("sitemap.xml", build_sitemap(cfg, urls))
    emit("robots.txt", "User-agent: *\nAllow: /\n\nSitemap: %s/sitemap.xml\n" % cfg["url"].rstrip("/"))

    index = [{"t": it["title"], "u": it["url"], "s": plain_text(it["summary"], 180),
              "d": it["date"].isoformat(), "n": it["number"],
              "g": [slugify(x) for x in it["topics"]]} for it in issues]
    emit("search-index.json", json.dumps(index, ensure_ascii=False))

    if cfg.get("domain"):
        emit("CNAME", cfg["domain"] + "\n")
    emit(".nojekyll", "")

    if not check_only:
        if os.path.isdir(ASSETS):
            shutil.copytree(ASSETS, os.path.join(OUT, "assets"), dirs_exist_ok=True)
        static = os.path.join(ROOT, "static")
        if os.path.isdir(static):
            shutil.copytree(static, OUT, dirs_exist_ok=True)

    if not quiet:
        print("")
        print("  %s — build complete" % cfg["title"])
        print("  " + "-" * 46)
        print("  issues        %d" % len(issues))
        print("  topics        %d" % len(topics))
        print("  glossary      %d terms (%d used in issues)"
              % (len(glossary_entries), len(GLOSSARY_USED)))
        print("  pages         %d" % len(pages))
        print("  files written %d" % len(written))
        if issues:
            print("  latest        Issue %s — %s (%s)"
                  % (issues[0]["number"], issues[0]["title"], pretty_date(issues[0]["date"])))
        if WARNINGS:
            print("")
            print("  %d thing%s to look at:" % (len(WARNINGS), "" if len(WARNINGS) == 1 else "s"))
            for w in WARNINGS:
                print("    • %s" % w)
        else:
            print("\n  No problems found.")

    return len(issues)


def watched_files():
    """Every source file whose modification should trigger a rebuild."""
    paths = [os.path.join(ROOT, "site.json"), os.path.join(ROOT, "build.py"),
             os.path.join(ROOT, "admin.py")]
    for folder in (CONTENT, ASSETS):
        for dirpath, _dirs, names in os.walk(folder):
            for name in names:
                if not name.startswith("."):
                    paths.append(os.path.join(dirpath, name))
    return paths


def snapshot():
    stamps = {}
    for path in watched_files():
        try:
            stamps[path] = os.path.getmtime(path)
        except OSError:
            pass
    return stamps


def serve():
    import http.server
    import socketserver
    import threading
    import time

    # The writing desk is local-only: it is loaded here, never during a build,
    # and nothing it serves is written into _site/.
    try:
        import admin
    except Exception as exc:            # the site must still preview without it
        admin = None
        print("  (writing desk unavailable: %s)" % exc)

    port = 8000
    httpd = None
    while port < 8020:
        try:
            socketserver.TCPServer.allow_reuse_address = True

            class Handler(http.server.SimpleHTTPRequestHandler):
                def __init__(self, *a, **kw):
                    super().__init__(*a, directory=OUT, **kw)

                def log_message(self, fmt, *a):
                    pass

                def end_headers(self):
                    self.send_header("Cache-Control", "no-store")
                    super().end_headers()

                def do_POST(self):
                    path = self.path.split("?")[0]
                    if admin and admin.handle_post(self, path):
                        return
                    self.send_error(404, "Not found")

                def do_GET(self):
                    # Mirror GitHub Pages: clean URLs, and a real 404 page.
                    path = self.path.split("?")[0]
                    if admin and admin.handle_get(self, path):
                        return
                    target = os.path.join(OUT, path.lstrip("/"))
                    if (not os.path.exists(target) and not path.endswith("/")
                            and "." not in os.path.basename(path)):
                        self.send_response(301)
                        self.send_header("Location", path + "/")
                        self.end_headers()
                        return
                    if not os.path.exists(target) and not os.path.exists(target.rstrip("/") + "/index.html"):
                        page = os.path.join(OUT, "404.html")
                        if os.path.exists(page):
                            body = open(page, "rb").read()
                            self.send_response(404)
                            self.send_header("Content-Type", "text/html; charset=utf-8")
                            self.send_header("Content-Length", str(len(body)))
                            self.end_headers()
                            self.wfile.write(body)
                            return
                    return super().do_GET()

            httpd = socketserver.TCPServer(("", port), Handler)
            break
        except OSError:
            port += 1

    if httpd is None:
        print("  Could not find a free port between 8000 and 8019.")
        return 1

    self_path = os.path.abspath(__file__)
    self_stamp = os.path.getmtime(self_path)

    def watcher():
        last = snapshot()
        while True:
            time.sleep(1)
            # Editing the generator itself needs a fresh process, because the
            # old code is already loaded into memory. Restart in place.
            try:
                if os.path.getmtime(self_path) != self_stamp:
                    print("  build.py changed — restarting the preview…")
                    os.execv(sys.executable, [sys.executable] + sys.argv)
            except OSError:
                pass
            now = snapshot()
            if now != last:
                last = now
                try:
                    generate(quiet=True)
                    stamp = datetime.now().strftime("%H:%M:%S")
                    if WARNINGS:
                        print("  [%s] rebuilt — %d warning%s:"
                              % (stamp, len(WARNINGS), "" if len(WARNINGS) == 1 else "s"))
                        for w in WARNINGS:
                            print("           • %s" % w)
                    else:
                        print("  [%s] rebuilt — reload the page to see your changes." % stamp)
                except Exception as exc:   # keep the server alive through a bad edit
                    print("  Build failed: %s" % exc)

    threading.Thread(target=watcher, daemon=True).start()

    if "--open" in sys.argv:
        # The port is only known once the socket is bound, so open the browser here.
        def launch():
            time.sleep(0.6)
            try:
                import webbrowser
                webbrowser.open("http://localhost:%d/admin/" % port)
            except Exception:
                pass
        threading.Thread(target=launch, daemon=True).start()

    print("\n  Preview running at http://localhost:%d" % port)
    if admin:
        print("  Writing desk  at http://localhost:%d/admin/" % port)
    print("  Watching content/ and assets/ — edits rebuild automatically.")
    print("  Press Control-C to stop.\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Preview stopped.\n")
    return 0


def main():
    args = sys.argv[1:]
    check_only = "--check" in args

    if check_only:
        print("Checking content (nothing will be written)…")
        generate(check_only=True)
        print("\n  Check finished. Nothing was written.")
        return 1 if WARNINGS else 0

    generate()
    print("\n  Output: _site/")

    if "--serve" in args:
        return serve()
    return 0


if __name__ == "__main__":
    sys.exit(main())
