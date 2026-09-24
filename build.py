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
        inner = s[1:-1]
        if s[0] == '"':
            # \" and \\ are the only escapes a writer is likely to type.
            return re.sub(r'\\(["\\])', r"\1", inner)
        return inner.replace("''", "'")
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
            if re.match(r"[A-Za-z_][\w-]*:(\s|$)", rest.strip()):
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
GLOSSARY_USES = {}    # slug -> [issues that explain the word], for the glossary page
RENDERING = None      # the issue currently being rendered, if any
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

    # Emphasis, defined here so link labels can use it too.
    def emphasis(t):
        t = re.sub(r"\*\*\*(.+?)\*\*\*", r"<strong><em>\1</em></strong>", t)
        t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
        t = re.sub(r"(^|[^\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1<em>\2</em>", t)
        return t

    # Links. The address may contain balanced brackets, which DOIs often do:
    # 10.1016/S0140-6736(24)02808-3 would otherwise be cut at the first one.
    def link_sub(m):
        label, href = m.group(1), m.group(2)
        ext = href.startswith("http")
        attrs = ' target="_blank" rel="noopener"' if ext else ""
        cls = ' class="ext"' if ext else ""
        return stash('<a href="%s"%s%s>%s</a>' % (href, cls, attrs, emphasis(label)))
    text = re.sub(r"\[([^\]]+)\]\(((?:[^()\s]|\([^()\s]*\))+)\)", link_sub, text)

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
        if RENDERING is not None:
            seen = GLOSSARY_USES.setdefault(entry["slug"], [])
            if RENDERING not in seen:
                seen.append(RENDERING)
        return stash(
            '<button type="button" class="gloss" data-term="%s" data-def="%s" '
            'data-slug="%s" aria-expanded="false" aria-controls="gloss-pop">%s</button>'
            % (esc(entry["term"]), esc(entry["definition"]), esc(entry["slug"]), shown))
    text = re.sub(r"\{\{([^}]+)\}\}", gloss_sub, text)

    text = emphasis(text)

    # Typography
    text = text.replace("--", "—")

    for idx, val in enumerate(placeholders):
        text = text.replace("\x00%d\x00" % idx, val)
    return text


def _is_block_start(line):
    ls = line.lstrip()
    return (re.match(r"#{1,6}\s", ls) or ls.startswith("> ") or ls.startswith("- ")
            or ls.startswith("* ") or ls.startswith(":::") or ls.startswith("|")
            or re.match(r"^\d+\.\s", ls) or re.match(r"^-{3,}$", ls.strip()))


# Ids the page layout already uses, so a heading can never collide with them.
RESERVED_IDS = {"main", "site-nav", "theme-btn", "gloss-pop", "gloss-pop-term",
                "gloss-pop-def", "gloss-close", "archive-search", "gloss-search",
                "results-count", "no-results", "gl-no-results", "corrections-head",
                "ask-invite-head"}


def markdown(src, _ids=None):
    lines = src.replace("\r\n", "\n").split("\n")
    out = []
    headings = []
    # One set per document, shared with nested blocks, so an issue covering two
    # studies can repeat "What they found" without two headings sharing an id.
    ids = set(RESERVED_IDS) if _ids is None else _ids
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
            if i >= n:
                warn("A '%s' box is never closed, so it runs to the end of the text. "
                     "Put ::: on its own line where the box should end." % label)
            i += 1  # consume closing :::
            inner, _ = markdown("\n".join(body), ids)
            out.append(
                '<div class="callout callout-%s" role="note"><p class="callout-label">%s</p>%s</div>'
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
                hid = slugify(plain_inline(text))
            base, k = hid, 2
            while hid in ids:
                hid = "%s-%d" % (base, k)
                k += 1
            ids.add(hid)
            if level in (2, 3):
                headings.append({"level": level, "text": plain_inline(text), "id": hid})
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
            inner, _ = markdown("\n".join(body), ids)
            out.append("<blockquote>%s</blockquote>" % inner)
            continue

        # Unordered list
        if re.match(r"^[-*]\s+", stripped):
            items, i = collect_list(lines, i, r"^[-*]\s+")
            out.append("<ul>%s</ul>" % "".join("<li>%s</li>" % it for it in items))
            continue

        # Ordered list
        if re.match(r"^\d+\.\s+", stripped):
            first = int(re.match(r"\d+", stripped).group(0))
            items, i = collect_list(lines, i, r"^\d+\.\s+")
            start = (' start="%d"' % first) if first != 1 else ""
            out.append("<ol%s>%s</ol>" % (start, "".join("<li>%s</li>" % it for it in items)))
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

    head_html = "".join(("<th scope='col'>%s</th>" % inline(c)) if c else "<td></td>"
                        for c in header)
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
    t = str(md_src)
    t = re.sub(r"(?m)^:::[\w-]*\s*$", "", t)                  # callout fences
    t = re.sub(r"(?m)^\s*(?:-{3,}|\*{3,})\s*$", "", t)        # horizontal rules
    t = re.sub(r"(?m)^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$", "", t)  # table divider rows
    t = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", t)                # heading marks
    t = re.sub(r"(?m)^\s*>\s?", "", t)                         # quotation marks
    t = re.sub(r"(?m)^\s*(?:[-*+]|\d+\.)\s+", "", t)          # list markers
    t = re.sub(r"\s*\{#[A-Za-z0-9_-]+\}\s*$", "", t, flags=re.M)  # heading anchors
    t = plain_inline(t)
    if limit and len(t) > limit:
        cut = t[:limit].rsplit(" ", 1)[0]
        return cut.rstrip(",.;:") + "…"
    return t


def plain_inline(t):
    """Strip inline markup (links, glossary terms, emphasis) from one run of text."""
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", t)
    t = re.sub(r"\[([^\]]+)\]\(((?:[^()\s]|\([^()\s]*\))+)\)", r"\1", t)
    # {{term|words shown}} reads as the words shown, just as it does on the page.
    t = re.sub(r"\{\{([^}|]+)\|([^}]*)\}\}",
               lambda m: m.group(2).strip() or m.group(1).strip(), t)
    t = re.sub(r"\{\{([^}]+)\}\}", r"\1", t)
    t = re.sub(r"\*+", "", t)
    t = re.sub(r"(?<![\w])_+|_+(?![\w])", "", t)             # _emphasis_, not snake_case
    t = t.replace("|", " ").replace("--", "\u2014")
    return re.sub(r"\s+", " ", t).strip()


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
{{author_meta}}
<link rel="canonical" href="{{canonical}}">
<meta property="og:type" content="{{og_type}}">
<meta property="og:site_name" content="{{site_title}}">
<meta property="og:title" content="{{og_title}}">
<meta property="og:description" content="{{page_description}}">
<meta property="og:url" content="{{canonical}}">
<meta name="twitter:card" content="summary_large_image">
<meta property="og:image" content="{{social_image}}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="{{site_title}}: {{site_tagline}}">
<meta name="twitter:image" content="{{social_image}}">
<meta name="theme-color" content="#fcfaf5" id="theme-color">
<link rel="alternate" type="application/rss+xml" title="{{site_title}} weekly issues" href="/feed.xml">
<link rel="icon" href="/assets/favicon-32.png" sizes="32x32" type="image/png">
<link rel="icon" href="/assets/favicon-96.png" sizes="96x96" type="image/png">
<link rel="apple-touch-icon" href="/assets/apple-touch-icon.png">
{{verification}}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&display=swap">
<link rel="stylesheet" href="/assets/style.css?v={{cachebust}}">
<script>
/* Applied before paint so the page never flashes the wrong theme. */
(function(){try{
var d=document.documentElement;
var t=localStorage.getItem('pdb-theme'); if(t){d.setAttribute('data-theme',t);}
if(t==='dark'){var m=document.getElementById('theme-color');if(m)m.setAttribute('content','#17150f');}
}catch(e){}})();
</script>
{{extra_head}}
</head>
<body class="{{body_class}}">
<a class="skip" href="#main">Skip to content</a>

<header class="site-header">
  <div class="wrap header-inner">
    <a class="brand" href="/">
      <span class="brand-mark" aria-hidden="true"></span>
      <span class="brand-name">{{site_title}}</span>
    </a>

    <button type="button" class="nav-toggle" aria-expanded="false" aria-controls="site-nav">
      <span class="nav-toggle-bars" aria-hidden="true"><span></span><span></span><span></span></span>
      <span class="nav-toggle-label">Menu</span>
    </button>

    <nav id="site-nav" class="site-nav" aria-label="Main">
      {{nav_links}}
      <div class="nav-tools">
        <button type="button" class="tool-btn theme-btn" id="theme-btn" title="Switch between light and dark">
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
    <p class="disclaimer"><strong>This is not medical advice.</strong> {{site_title}} explains published
    research. It can&rsquo;t tell you what is right for your own care, so talk to your neurologist or doctor
    before changing anything about your treatment.</p>
    <p class="copyright">&copy; {{year}} {{site_title}}{{editor_credit}}. Not affiliated with any journal,
    university, drug company or patient group. The findings belong to the researchers who published them.</p>
  </div>
</footer>

<div class="gloss-pop" id="gloss-pop" role="dialog" aria-labelledby="gloss-pop-term" aria-live="polite" hidden>
  <p class="gloss-term" id="gloss-pop-term"></p>
  <p class="gloss-def" id="gloss-pop-def"></p>
  <p class="gloss-more"><a id="gloss-pop-link" href="/glossary/">See it in the glossary</a></p>
  <button type="button" class="gloss-close" id="gloss-close" aria-label="Close definition">&times;</button>
</div>

<script src="/assets/site.js?v={{cachebust}}"></script>
{{extra_body}}
</body>
</html>
"""


def byline(cfg):
    """'By <name>', linked to the editor's note on the About page."""
    name = cfg.get("editor_name", "").strip()
    if not name:
        return ""
    return 'By <a href="/about/#editor">%s</a>' % esc(name)


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
            '<p class="papers-note">The links go to the original papers. Some journals '
            'charge to read the full text, but the abstract is usually free. Every study '
            'covered so far is also on the <a href="/sources/">sources page</a>.</p></section>'
            % (heading, "".join(rows)))


# --------------------------------------------------------------------------
# Content loading
# --------------------------------------------------------------------------

def load_config():
    path = os.path.join(ROOT, "site.json")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    try:
        return json.loads(text)
    except ValueError as exc:
        line = getattr(exc, "lineno", "?")
        raise SystemExit(
            "\n  site.json has a mistake on line %s: %s\n"
            "  Usually a missing comma between two lines, or a missing quote mark.\n"
            % (line, getattr(exc, "msg", exc)))


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
        if any(e["slug"] == entry["slug"] for e in entries):
            warn("The glossary defines '%s' twice. Only the first definition is used." % term)
            continue
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
        if d > date.today():
            warn("%s is dated %s, which has not happened yet. It still goes live as soon "
                 "as it is pushed." % (name, pretty_date(d)))
        if not as_list(meta.get("papers")):
            warn("%s lists no study, so it will be missing from the sources page." % name)

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

    numbers = {}
    for it in items:
        numbers.setdefault(str(it["number"]), []).append(it["file"])
    for num, files in numbers.items():
        if len(files) > 1:
            warn("Issues %s are all numbered %s. Remove the 'issue:' line from all but "
                 "one of them." % (" and ".join(files), num))

    seen = {}
    for it in items:
        if it["slug"] in seen:
            warn("Two issues share the slug '%s' (%s and %s). One will overwrite the other."
                 % (it["slug"], it["file"], seen[it["slug"]]))
        seen[it["slug"]] = it["file"]
    return items


def unify_topics(issues):
    """Make every spelling of a topic ("clinical trials", "Clinical Trials")
    use one name, so it gets one topic page instead of two fighting over the
    same address. The spelling used most often wins; ties go to the earliest."""
    counts, first_seen = {}, {}
    for it in sorted(issues, key=lambda x: x["date"]):
        for t in it["topics"]:
            key = slugify(t)
            counts.setdefault(key, {})
            counts[key][t] = counts[key].get(t, 0) + 1
            first_seen.setdefault((key, t), len(first_seen))
    canonical = {key: sorted(names, key=lambda n: (-names[n], first_seen[(key, n)]))[0]
                 for key, names in counts.items()}
    for key, names in counts.items():
        if len(names) > 1:
            others = [n for n in names if n != canonical[key]]
            warn("The topic '%s' is also written as %s. They are shown together as '%s'; "
                 "use one spelling to keep things tidy."
                 % (canonical[key], ", ".join("'%s'" % o for o in others), canonical[key]))
    for it in issues:
        seen, topics = set(), []
        for t in it["topics"]:
            key = slugify(t)
            if key not in seen:
                seen.add(key)
                topics.append(canonical[key])
        it["topics"] = topics
    return issues


def load_drafts(cfg):
    """The issues load_issues() skips, for local preview only."""
    drafts = []
    if not os.path.isdir(ISSUES_DIR):
        return drafts
    for name in sorted(os.listdir(ISSUES_DIR), reverse=True):
        if not name.endswith(".md") or name.startswith("_"):
            continue
        with open(os.path.join(ISSUES_DIR, name), encoding="utf-8") as f:
            meta, body = parse_frontmatter(f.read())
        if str(meta.get("draft", "")).lower() not in ("true", "yes", "1"):
            continue
        slug = slugify(meta.get("slug") or re.sub(r"^\d{4}-\d{2}-\d{2}-", "", name[:-3]))
        papers = [p if isinstance(p, dict) else {"title": str(p)}
                  for p in as_list(meta.get("papers"))]
        drafts.append({
            "file": name,
            "title": str(meta.get("title") or name),
            "date": parse_date(meta.get("date", name[:10]), name),
            "slug": slug,
            "url": "/drafts/%s/" % slug,
            "topics": [str(t) for t in as_list(meta.get("topics"))],
            "papers": papers,
            "summary": str(meta.get("summary") or plain_text(body, 200)),
            "body": body,
            "reading_time": reading_time(body),
            "number": meta.get("issue") or "draft",
            "meta": meta,
        })
    return drafts


def build_draft_index(cfg, drafts):
    if drafts:
        rows = "".join(
            '<article class="card"><div class="card-meta"><span class="issue-no">Draft</span>'
            '<span class="dot" aria-hidden="true">&middot;</span><time datetime="%s">%s</time>'
            '<span class="dot" aria-hidden="true">&middot;</span><span>%s min read</span></div>'
            '<h3 class="card-title"><a href="%s">%s</a></h3>'
            '<p class="card-summary">%s</p></article>'
            % (d["date"].isoformat(), short_date(d["date"]), d["reading_time"],
               d["url"], esc(d["title"]), esc(plain_text(d["summary"], 160)))
            for d in drafts)
        body = '<div class="card-grid">%s</div>' % rows
    else:
        body = '<p class="empty-note">Nothing in progress. Start an issue in the writing desk.</p>'

    content = """<div class="page-head"><div class="wrap">
      <h1>Drafts</h1>
      <p class="page-lede">Unfinished issues, visible only on your own machine. These are never
      built into the published site.</p>
    </div></div>
    <div class="wrap"><div class="archive">%s</div></div>""" % body
    return page_shell(cfg, content, title="Drafts",
                      description="Unfinished issues of %s, visible only on the editor's own "
                                  "machine and never built into the published site." % cfg["title"],
                      path="/drafts/",
                      extra_head='<meta name="robots" content="noindex, nofollow">')


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
        '<a class="nav-link%s" href="%s"%s>%s</a>'
        % (" current" if item["href"] == path else "", item["href"],
           ' aria-current="page"' if item["href"] == path else "", esc(item["label"]))
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
    if title is None:
        # The homepage carries the tagline too, so search results say what this is.
        full_title = ("%s: %s" % (cfg["title"], cfg["tagline"].rstrip(".")) if path == "/"
                      and cfg.get("tagline") else cfg["title"])
    elif len(title) > 52:
        full_title = title          # adding the site name would overflow the result
    else:
        full_title = "%s | %s" % (title, cfg["title"])
    desc = description or cfg["description"]
    return render(
        LAYOUT,
        lang=cfg.get("language", "en"),
        page_title=esc(full_title),
        og_title=esc(title or cfg["title"]),
        page_description=esc(plain_text(desc, 155)),
        canonical=cfg["url"].rstrip("/") + path,
        og_type=og_type,
        site_title=esc(cfg["title"]),
        site_description=esc(cfg["description"]),
        site_tagline=esc(cfg.get("tagline", "").rstrip(".")),
        editor_credit=(", by %s" % esc(cfg["editor_name"].strip())
                       if cfg.get("editor_name", "").strip() else ""),
        nav_links=nav_links,
        footer_nav=footer_nav,
        footer_links=footer_links,
        content=content,
        year=date.today().year,
        body_class=body_class,
        extra_head=extra_head,
        extra_body=extra_body,
        cachebust=CACHEBUST,
        social_image=cfg["url"].rstrip("/") + "/assets/social-card.png?v=" + SOCIAL_VERSION,
        author_meta=('<meta name="author" content="%s">' % esc(cfg["editor_name"].strip())
                     if cfg.get("editor_name", "").strip() else ""),
        verification=(
            '<meta name="google-site-verification" content="%s">'
            % esc(cfg["google_site_verification"])
            if cfg.get("google_site_verification") else ""),
    )


def subscribe_block(cfg):
    """A closing invitation. Readers are sent to the questions page, never to
    the raw feed file, which looks broken to anyone without a reader app."""
    ask = '<a href="/ask/">send a question or a suggestion</a>' if cfg.get("feedback_form_url") else ""
    if cfg.get("subscribe_url"):
        lead = ('A new issue comes out every week. <a href="%s" target="_blank" rel="noopener">Get '
                'it by email</a>, or catch up in the <a href="/archive/">archive</a>.'
                % esc(cfg["subscribe_url"]))
    else:
        lead = ('A new issue comes out every week, and everything so far is in the '
                '<a href="/archive/">archive</a>.')
    tail = (" If you&rsquo;ve seen a study worth covering, or something here didn&rsquo;t make "
            "sense, %s." % ask) if ask else ""
    return ("""<section class="subscribe" aria-label="Keeping up with PD Brief"><div class="wrap wrap-narrow subscribe-inner">
      <p>%s%s</p>
    </div></section>""" % (lead, tail))


def build_home(cfg, issues):
    if not issues:
        body = ('<div class="wrap"><div class="empty"><h1>No issues yet</h1>'
                '<p>Open the writing desk and click <strong>Start a new issue</strong>. '
                'It will appear here as soon as you save it.</p></div></div>')
        return page_shell(cfg, body, path="/")

    latest = issues[0]
    rest = issues[1:7]
    # "This week's issue" is only true while it is; otherwise it reads as stale.
    age = (date.today() - latest["date"]).days
    latest_label = "This week's issue" if age <= 7 else "The latest issue"
    topics_html = "".join('<a class="tag" href="/topics/%s/">%s</a>' % (slugify(t), esc(t))
                          for t in latest["topics"][:4])

    hero = """<section class="hero">
  <div class="wrap">
    <p class="eyebrow">Free to read, new every week</p>
    <h1 class="hero-title">%s</h1>
    <p class="hero-tagline">%s</p>
    <p class="hero-note">%s</p>
  </div>
</section>

<section class="latest">
  <div class="wrap">
    <div class="section-head">
      <h2 class="section-title">%s</h2>
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
      <p class="feature-more"><a href="%s">Read this issue</a></p>
    </article>
  </div>
</section>""" % (esc(cfg["tagline"]), esc(cfg["description"]),
                 (byline(cfg) + ". " if byline(cfg) else "") +
                 "%d issue%s published since %s." % (
                     len(issues), "" if len(issues) == 1 else "s",
                     issues[-1]["date"].strftime("%B %Y")),
                 latest_label,
                 latest["number"], latest["date"].isoformat(), pretty_date(latest["date"]),
                 latest["reading_time"], latest["url"], esc(latest["title"]),
                 esc(latest["summary"]), topics_html, latest["url"])

    recent = ""
    if rest:
        recent = ("""<section class="recent"><div class="wrap">
    <div class="section-head"><h2 class="section-title">Earlier issues</h2></div>
    <div class="card-grid">%s</div>
    <div class="center"><a class="btn btn-quiet" href="/archive/">See the full archive</a></div>
    </div></section>""" % "".join(issue_card(it) for it in rest))

    site_schema = {"@context": "https://schema.org", "@type": "WebSite",
                   "name": cfg["title"], "url": cfg["url"].rstrip("/") + "/",
                   "description": cfg["description"], "inLanguage": cfg.get("language", "en")}
    return page_shell(cfg, hero + recent + subscribe_block(cfg), path="/",
                      extra_head='<script type="application/ld+json">%s</script>'
                      % json.dumps(site_schema, ensure_ascii=False).replace("</", "<\\/"))


def corrections_block(it):
    """Corrections are published on the issue itself, as the editorial policy
    promises, rather than edited away silently."""
    entries = as_list(it["meta"].get("corrections"))
    if not entries:
        return ""
    rows = []
    for c in entries:
        if isinstance(c, dict):
            when = c.get("date", "")
            note = c.get("note", "")
        else:
            when, note = "", str(c)
        d = ""
        if when:
            try:
                d = '<span class="corr-date">%s</span> ' % esc(pretty_date(parse_date(when, it["file"])))
            except Exception:
                d = '<span class="corr-date">%s</span> ' % esc(when)
        rows.append("<li>%s%s</li>" % (d, inline(str(note))))
    return ('<section class="corrections" aria-labelledby="corrections-head">'
            '<h2 class="corr-head" id="corrections-head">Corrections</h2>'
            '<ul class="corr-list">%s</ul></section>' % "".join(rows))


def last_changed(it):
    """The issue's date, or its latest correction if that is later."""
    latest = it["date"]
    for c in as_list(it["meta"].get("corrections")):
        if isinstance(c, dict) and c.get("date"):
            try:
                latest = max(latest, parse_date(c["date"], it["file"]))
            except Exception:
                pass
    return latest


def feedback_link(cfg):
    """The address of the questions page, if one has been set up."""
    return "/ask/" if cfg.get("feedback_form_url") else ""


def ask_invitation(cfg):
    """A short invitation shown at the end of each issue."""
    if not cfg.get("feedback_form_url"):
        return ""
    return ('<section class="ask-invite" aria-labelledby="ask-invite-head">'
            '<h2 class="ask-invite-head" id="ask-invite-head">Something here unclear?</h2>'
            '<p>If part of this issue didn&rsquo;t make sense, or you want to know more about '
            'the study behind it, ask. Your question might end up shaping a future issue.</p>'
            '<a class="btn btn-primary" href="/ask/">Ask a question</a>'
            '</section>')


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
            'height="900" loading="lazy"></iframe>'
            '</div>'
            '<p class="form-note">The form is run by Google. If it doesn&rsquo;t load, '
            '<a href="%s" target="_blank" rel="noopener">open it in a new tab</a>.</p>'
            % (esc(embed_url), esc(url)))
    else:
        form_html = (
            '<div class="form-cta">'
            '<a class="btn btn-primary btn-big" href="%s" target="_blank" rel="noopener">'
            'Open the question form</a>'
            '<p class="form-note">The form opens in a new tab and is hosted by Google.</p>'
            '</div>' % esc(url))

    content = """<div class="page-head"><div class="wrap wrap-narrow">
      <h1>Ask a question</h1>
      <p class="page-lede">If something in an issue didn&rsquo;t make sense, or you want to know
      more about a study, this is the place to ask. No question is too basic. If it confused
      you, it probably confused other readers too.</p>
    </div></div>

    <div class="wrap wrap-narrow ask-page">
      <section class="ask-what">
        <h2>What you can send</h2>
        <ul class="ask-list">
          <li><strong>A question about an issue.</strong> Say which part lost you and what
          you were trying to understand.</li>
          <li><strong>A study we should cover.</strong> A link or a title is enough.</li>
          <li><strong>A correction.</strong> If something here is wrong, please tell us. The
          fix gets noted at the bottom of the issue.</li>
          <li><strong>A word for the glossary.</strong> If you had to look something up,
          other readers probably did too.</li>
        </ul>
      </section>

      %s

      <div class="callout callout-caution" role="note">
        <p class="callout-label">Please don&rsquo;t send medical questions</p>
        <p>We can&rsquo;t give advice about anyone&rsquo;s treatment, symptoms or medication.
        Your neurologist or doctor knows your history and is the right person to ask. PD Brief
        can only explain what the research found.</p>
      </div>
    </div>""" % form_html

    return page_shell(cfg, content, title="Ask a question",
                      description="Send a question, a correction, or a study we should cover "
                                  "to %s." % cfg["title"],
                      path="/ask/")


def build_issue(cfg, it, prev_issue, next_issue):
    global RENDERING
    # Remember which issues explain a word, so the glossary can link back.
    RENDERING = None if it.get("is_draft") else it
    try:
        body_html, headings = markdown(it["body"])
    finally:
        RENDERING = None

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
        "dateModified": last_changed(it).isoformat(),
        "image": cfg["url"].rstrip("/") + "/assets/social-card.png",
        "author": ({"@type": "Person", "name": cfg["editor_name"].strip(),
                    "url": cfg["url"].rstrip("/") + "/about/#editor"}
                   if cfg.get("editor_name", "").strip()
                   else {"@type": "Organization", "name": cfg["title"]}),
        "publisher": {"@type": "Organization", "name": cfg["title"]},
        "mainEntityOfPage": cfg["url"].rstrip("/") + it["url"],
        "isAccessibleForFree": True,
    }
    if it["papers"]:
        schema["citation"] = [
            {"@type": "ScholarlyArticle", "name": p.get("title", ""),
             "identifier": ("https://doi.org/%s" % p["doi"]) if p.get("doi") else p.get("url", "")}
            for p in it["papers"]]
    extra_head = ('<meta property="article:published_time" content="%s">'
                  '<script type="application/ld+json">%s</script>'
                  % (it["date"].isoformat(),
                     json.dumps(schema, ensure_ascii=False).replace("</", "<\\/")))
    if it.get("is_draft"):
        extra_head = '<meta name="robots" content="noindex, nofollow">' + extra_head

    banner = ("" if not it.get("is_draft") else
              '<div class="draft-banner"><div class="wrap wrap-narrow">'
              '<strong>Draft.</strong> Only you can see this. It is not part of the '
              'published site and will not appear until you switch the draft setting off.'
              '</div></div>')

    content = """<article class="issue">
  %s
  <header class="issue-header">
    <div class="wrap wrap-narrow">
      <div class="issue-crumbs"><a href="/archive/">Archive</a>
        <span aria-hidden="true">/</span> <span>Issue %s</span></div>
      <h1 class="issue-title">%s</h1>
      <p class="issue-summary">%s</p>
      <div class="issue-meta">
        %s<time datetime="%s">%s</time>
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
    %s
    <nav class="pager" aria-label="Other issues">%s%s</nav>
  </div>
</article>""" % (banner, it["number"], esc(it["title"]), esc(it["summary"]),
                 ('<span class="byline">%s</span><span class="dot" aria-hidden="true">'
                  '&middot;</span>' % byline(cfg)) if byline(cfg) else "",
                 it["date"].isoformat(), pretty_date(it["date"]), it["reading_time"],
                 topics_html, toc, body_html, paper_block(it["papers"]),
                 corrections_block(it), ask_invitation(cfg), nav_prev, nav_next)

    return page_shell(cfg, content, title=it["title"], description=it["summary"],
                      path=it["url"], og_type="article", body_class="page-issue",
                      extra_head=extra_head)


def build_archive(cfg, issues):
    by_year = {}
    for it in issues:
        by_year.setdefault(it["date"].year, []).append(it)

    all_topics = sorted({t for it in issues for t in it["topics"]}, key=str.lower)
    filters = "".join('<button type="button" class="filter" data-topic="%s">%s</button>'
                      % (slugify(t), esc(t)) for t in all_topics)

    sections = []
    for year in sorted(by_year, reverse=True):
        rows = []
        for it in by_year[year]:
            topics_attr = " ".join(slugify(t) for t in it["topics"])
            tags = "".join('<span class="tag tag-static">%s</span>' % esc(t) for t in it["topics"][:3])
            if as_list(it["meta"].get("corrections")):
                tags += '<span class="tag tag-corrected">Corrected</span>' 
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
    <p class="page-lede">%s Search for a word or pick a topic to narrow the list.</p>
  </div>
</div>
<div class="wrap archive">
  <div class="archive-controls">
    <div class="search-wrap">
      <label class="sr-only" for="archive-search">Search issues</label>
      <input type="search" id="archive-search" placeholder="Search every issue&hellip;"
             autocomplete="off">
    </div>
    <div class="filters" role="group" aria-label="Filter by topic">
      <button type="button" class="filter is-active" data-topic="all">All</button>%s
    </div>
  </div>
  <p class="results-count" id="results-count" aria-live="polite"></p>
  %s
  <p class="no-results" id="no-results" hidden>No issues match that. Try a different word or clear the filter.</p>
</div>""" % ("No issues yet." if not issues else
             "The first issue is below." if len(issues) == 1 else
             "All %d issues so far, newest first." % len(issues),
             filters, "".join(sections))

    return page_shell(cfg, content, title="Archive",
                      description="Every issue of %s, newest first: newly published "
                                  "Parkinson's research explained in everyday language."
                                  % cfg["title"],
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
      <p class="page-lede">Parkinson's research can be conducted along a variety of tracks.
      Follow one of these threads to take a deeper look at a specific one.</p>
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
    <div class="wrap">
      <div class="section-head"><h2 class="section-title">Issues on this topic</h2></div>
      <div class="card-grid">%s</div>
    </div>""" % (
        esc(topic), len(items), "" if len(items) == 1 else "s",
        "".join(issue_card(it) for it in items))
    return page_shell(cfg, content, title=topic,
                      description="%s issues about %s, newest first. Newly published "
                                  "Parkinson's research explained in everyday language."
                                  % (cfg["title"], topic),
                      path="/topics/%s/" % slugify(topic))


def build_sources_page(cfg, issues):
    """Every paper covered, grouped by the issue that covered it."""
    covered = [it for it in issues if it["papers"]]

    blocks = []
    for it in covered:
        rows = []
        for paper in it["papers"]:
            title = esc(str(paper.get("title", "Untitled study")))
            link = paper.get("url") or (("https://doi.org/%s" % paper["doi"]) if paper.get("doi") else "")
            title_html = ('<a href="%s" target="_blank" rel="noopener">%s</a>' % (esc(link), title)
                          if link else title)
            bits = []
            if paper.get("authors"):
                bits.append(esc(str(paper["authors"])))
            if paper.get("journal"):
                bits.append("<em>%s</em>" % esc(str(paper["journal"])))
            if paper.get("year"):
                bits.append(esc(str(paper["year"])))
            access = ""
            if paper.get("access"):
                label = str(paper["access"])
                cls = "open" if ("open" in label.lower() or "free" in label.lower()) else "closed"
                access = ' <span class="access access-%s">%s</span>' % (cls, esc(label))
            doi = ""
            if paper.get("doi"):
                doi = ('<p class="paper-doi">DOI: <a href="https://doi.org/%s" target="_blank" '
                       'rel="noopener">%s</a></p>' % (esc(str(paper["doi"])), esc(str(paper["doi"]))))
            rows.append('<li class="paper"><p class="paper-title">%s%s</p>'
                        '<p class="paper-meta">%s</p>%s</li>'
                        % (title_html, access, ", ".join(bits), doi))

        blocks.append(
            '<section class="src-issue">'
            '<div class="src-head"><p class="src-no">Issue %s &middot; %s</p>'
            '<h2 class="src-title"><a href="%s">%s</a></h2></div>'
            '<ul class="paper-list">%s</ul></section>'
            % (it["number"], short_date(it["date"]), it["url"], esc(it["title"]), "".join(rows)))

    lede = ("Information and links to the original studies that %s has covered so far."
            % esc(cfg["title"]))

    content = """<div class="page-head"><div class="wrap">
      <h1>Sources</h1>
      <p class="page-lede">%s</p>
    </div></div>
    <div class="wrap wrap-narrow sources">%s
      <p class="src-note">Some journals charge for the full paper, but the abstract is almost
      always free. DOI links keep working even if a journal moves its website.</p>
    </div>""" % (lede, "".join(blocks) or
                 '<p class="empty-note">No studies recorded yet.</p>')

    return page_shell(cfg, content, title="Sources",
                      description="Every study covered by %s, with authors, journal and DOI, "
                                  "grouped by the issue that summarised it." % cfg["title"],
                      path="/sources/")


def gl_uses(entry):
    """'Explained in Issue 2, Issue 3' under a glossary definition."""
    uses = GLOSSARY_USES.get(entry["slug"], [])
    if not uses:
        return ""
    links = ", ".join('<a href="%s">Issue %s</a>' % (it["url"], esc(it["number"]))
                      for it in sorted(uses, key=lambda i: i["date"]))
    return '<p class="gl-uses">Explained in %s</p>' % links


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
        items = "".join('<div class="gl-entry" id="term-%s"><dt>%s</dt><dd>%s%s</dd></div>'
                        % (e["slug"], esc(e["term"]), inline(e["definition"]), gl_uses(e))
                        for e in groups[letter])
        blocks.append('<section class="gl-group"><h2 id="letter-%s" class="gl-letter">%s</h2>'
                      '<dl class="gl-list">%s</dl></section>' % (letter, letter, items))

    content = """<div class="page-head"><div class="wrap">
      <h1>Glossary</h1>
      <p class="page-lede">Definitions for the terms that keep coming up in Parkinson&rsquo;s
      research. Inside an issue, tap any word with a dotted underline to see its meaning
      without leaving the page.</p>
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
      <p class="page-lede">The link might be old, or there could be a typo in the address.
      Every issue is listed in the archive.</p>
      <p><a class="btn btn-primary" href="/archive/">Go to the archive</a></p>
    </div>
    <div class="wrap">
      <div class="section-head"><h2 class="section-title">Recent issues</h2></div>
      <div class="card-grid">%s</div>
    </div>""" % recent
    return page_shell(cfg, content, title="Page not found",
                      extra_head='<meta name="robots" content="noindex">',
                      description="That page could not be found. Browse the %s archive of "
                                  "plain-language Parkinson's research summaries instead."
                                  % cfg["title"],
                      path="/404.html")


# --------------------------------------------------------------------------
# Feeds and machine-readable files
# --------------------------------------------------------------------------

def build_feed(cfg, issues):
    global PLAIN_GLOSS
    base = cfg["url"].rstrip("/")
    items = []
    PLAIN_GLOSS = True
    try:
        rendered = [markdown(it["body"])[0] for it in issues[:25]]
    finally:
        PLAIN_GLOSS = False
    for it, body_html in zip(issues[:25], rendered):
        # Feed readers show the article away from the site, so links must be absolute.
        body_html = re.sub(r'(href|src)="/(?!/)', r'\1="%s/' % base, body_html)
        body_html = body_html.replace("]]>", "]]]]><![CDATA[>")
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
  <image>
    <url>%s/assets/favicon-96.png</url>
    <title>%s</title>
    <link>%s/</link>
  </image>
  <lastBuildDate>%s</lastBuildDate>
%s
</channel>
</rss>
""" % (esc(cfg["title"]), base, base, esc(cfg["description"]),
       cfg.get("language", "en"), base, esc(cfg["title"]), base, last, "\n".join(items))


def build_sitemap(cfg, urls):
    base = cfg["url"].rstrip("/")
    entries = "".join(
        "  <url><loc>%s%s</loc>%s</url>\n"
        % (base, u["path"], ("<lastmod>%s</lastmod>" % u["lastmod"]) if u.get("lastmod") else "")
        for u in urls)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n%s</urlset>\n' % entries)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

CACHEBUST = datetime.now().strftime("%Y%m%d%H%M")


def _file_version(path):
    """A short fingerprint of a file, so a changed image gets a new address and
    sites that cache link previews (iMessage, Slack, Facebook) fetch it again."""
    import hashlib
    try:
        with open(path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()[:8]
    except OSError:
        return "1"


SOCIAL_VERSION = _file_version(os.path.join(ASSETS, "social-card.png"))

# Drafts are built only by the local preview server, never by a real build,
# so an unfinished issue can be read as a full page without any risk of it
# reaching the published site.
INCLUDE_DRAFTS = False




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
    global CACHEBUST, SOCIAL_VERSION
    # A fingerprint of the stylesheet and script: readers' browsers fetch them
    # again only when they have actually changed, not on every daily rebuild.
    CACHEBUST = _file_version(os.path.join(ASSETS, "style.css")) + \
        _file_version(os.path.join(ASSETS, "site.js"))[:4]
    SOCIAL_VERSION = _file_version(os.path.join(ASSETS, "social-card.png"))
    del WARNINGS[:]
    GLOSSARY.clear()
    GLOSSARY_USED.clear()
    GLOSSARY_USES.clear()

    cfg = load_config()
    glossary_entries = load_glossary()
    issues = unify_topics(load_issues(cfg))
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

    if INCLUDE_DRAFTS:
        drafts = load_drafts(cfg)
        for d in drafts:
            d["is_draft"] = True
            emit("drafts/%s/index.html" % d["slug"], build_issue(cfg, d, None, None))
        emit("drafts/index.html", build_draft_index(cfg, drafts))

    emit("sources/index.html", build_sources_page(cfg, issues))
    emit("glossary/index.html", build_glossary(cfg, glossary_entries))
    if cfg.get("feedback_form_url"):
        emit("ask/index.html", build_feedback_page(cfg))
    for page in pages:
        emit("%s/index.html" % page["slug"], build_static_page(cfg, page))

    emit("404.html", build_404(cfg, issues))
    emit("feed.xml", build_feed(cfg, issues))

    urls = [{"path": "/", "lastmod": issues[0]["date"].isoformat() if issues else None},
            {"path": "/archive/"}, {"path": "/topics/"}, {"path": "/glossary/"},
            {"path": "/sources/"}]
    urls += [{"path": it["url"], "lastmod": last_changed(it).isoformat()} for it in issues]
    urls += [{"path": "/topics/%s/" % slugify(t)} for t in topics]
    urls += [{"path": "/%s/" % p["slug"]} for p in pages]
    if cfg.get("feedback_form_url"):
        urls.append({"path": "/ask/"})
    emit("sitemap.xml", build_sitemap(cfg, urls))
    emit("robots.txt", "User-agent: *\nAllow: /\n\nSitemap: %s/sitemap.xml\n" % cfg["url"].rstrip("/"))

    # "b" carries the whole issue as plain text so the archive can search
    # inside articles, not just their titles and summaries. It is fetched only
    # when a reader actually types, so it costs nothing on page load.
    index = [{"t": it["title"], "u": it["url"], "s": plain_text(it["summary"], 180),
              "d": it["date"].isoformat(), "n": it["number"],
              "g": [slugify(x) for x in it["topics"]],
              "c": len(as_list(it["meta"].get("corrections"))),
              "b": plain_text(it["body"]).lower()} for it in issues]
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


def running_preview():
    """The port of a PD Brief preview already running on this Mac, or None.

    Double-clicking the launcher twice used to start a second copy on the next
    port along; now the second click simply opens the one that is running."""
    import urllib.request
    for port in range(8000, 8020):
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/api/issues" % port, timeout=0.4) as r:
                if "issues" in json.loads(r.read().decode("utf-8")):
                    return port
        except Exception:
            continue
    return None


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

    already = running_preview()
    if already:
        url = "http://localhost:%d/admin/" % already
        print("\n  PD Brief is already running at http://localhost:%d" % already)
        if "--open" in sys.argv:
            import webbrowser
            webbrowser.open(url)
            print("  Opened the writing desk in your browser. You can close this window.\n")
        else:
            print("  Writing desk at %s\n" % url)
        return 0

    port = 8000
    httpd = None

    class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
        # Threads, so one stalled browser connection cannot freeze the preview.
        daemon_threads = True
        allow_reuse_address = True

    while port < 8020:
        try:

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
                    path = "/" + self.path.split("?")[0].split("#")[0].lstrip("/")
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
                            with open(page, "rb") as fh:
                                body = fh.read()
                            self.send_response(404)
                            self.send_header("Content-Type", "text/html; charset=utf-8")
                            self.send_header("Content-Length", str(len(body)))
                            self.end_headers()
                            self.wfile.write(body)
                            return
                    return super().do_GET()

            # 127.0.0.1 only: the writing desk can change files, so nothing else on
            # the same Wi-Fi network may reach it.
            httpd = Server(("127.0.0.1", port), Handler)
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
    global INCLUDE_DRAFTS
    args = sys.argv[1:]
    check_only = "--check" in args
    INCLUDE_DRAFTS = "--serve" in args

    if check_only:
        print("Checking content (nothing will be written)…")
        generate(check_only=True)
        print("\n  Check finished. Nothing was written.")
        return 1 if WARNINGS else 0

    if "--serve" in args and running_preview():
        return serve()      # only opens the copy that is already running

    generate()
    print("\n  Output: _site/")

    if "--serve" in args:
        return serve()
    return 0


if __name__ == "__main__":
    sys.exit(main())
