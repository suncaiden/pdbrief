"""
PD Brief writing desk — the local editor behind `python3 build.py --serve`.

This module is only ever loaded by the preview server on your own machine.
Nothing in here is copied into _site/, so it is never published to the web.

It gives the browser a small JSON API for listing, reading, writing and
previewing issues, using the same Markdown renderer the real site uses — so
what you see while writing is what readers will get.
"""

import json
import os
import re
from datetime import date, datetime

import build

ADMIN_DIR = os.path.join(build.ROOT, "admin")

# Files the editor is allowed to serve, so a stray request cannot read the disk.
STATIC = {
    "/admin": "editor.html",
    "/admin/": "editor.html",
    "/admin/editor.html": "editor.html",
    "/admin/editor.css": "editor.css",
    "/admin/editor.js": "editor.js",
}

TYPES = {".html": "text/html; charset=utf-8",
         ".css": "text/css; charset=utf-8",
         ".js": "text/javascript; charset=utf-8"}


# --------------------------------------------------------------------------
# Turning form fields back into a Markdown file
# --------------------------------------------------------------------------

def _quote(value):
    """Emit a YAML scalar our own parser will read back correctly.

    Frontmatter is one line per field, so any newline the writer types into a
    field is folded into a space. Inner double quotes survive: the reader only
    strips one matching pair from the ends.
    """
    s = re.sub(r"\s+", " ", str(value)).strip()
    return '"%s"' % s


def to_frontmatter(meta):
    lines = ["---"]
    for key in ("title", "date", "slug", "summary"):
        if meta.get(key) not in (None, ""):
            lines.append("%s: %s" % (key, _quote(meta[key])))

    topics = [t for t in meta.get("topics", []) if str(t).strip()]
    if topics:
        lines.append("topics: [%s]" % ", ".join(str(t).strip() for t in topics))

    papers = [p for p in meta.get("papers", []) if str(p.get("title", "")).strip()]
    if papers:
        lines.append("papers:")
        for p in papers:
            first = True
            for key in ("title", "authors", "journal", "year", "doi", "url", "access"):
                val = str(p.get(key, "")).strip()
                if not val:
                    continue
                prefix = "  - " if first else "    "
                if key == "year" and re.fullmatch(r"\d{4}", val):
                    lines.append("%s%s: %s" % (prefix, key, val))
                else:
                    lines.append("%s%s: %s" % (prefix, key, _quote(val)))
                first = False

    if meta.get("draft"):
        lines.append("draft: true")

    lines.append("---")
    return "\n".join(lines)


def filename_for(meta):
    d = build.parse_date(meta.get("date") or date.today().isoformat(), "editor")
    slug = build.slugify(meta.get("slug") or meta.get("title") or "untitled")
    return "%s-%s.md" % (d.isoformat(), slug)


def safe_issue_path(filename):
    """Resolve a filename inside content/issues/ and nowhere else."""
    name = os.path.basename(str(filename or ""))
    if not name.endswith(".md"):
        return None
    path = os.path.abspath(os.path.join(build.ISSUES_DIR, name))
    if os.path.dirname(path) != os.path.abspath(build.ISSUES_DIR):
        return None
    return path


# --------------------------------------------------------------------------
# Reading what is already there
# --------------------------------------------------------------------------

def list_issues():
    out = []
    if not os.path.isdir(build.ISSUES_DIR):
        return out
    for name in sorted(os.listdir(build.ISSUES_DIR), reverse=True):
        if not name.endswith(".md"):
            continue
        with open(os.path.join(build.ISSUES_DIR, name), encoding="utf-8") as f:
            meta, body = build.parse_frontmatter(f.read())
        if not isinstance(meta, dict):
            meta = {}
        out.append({
            "file": name,
            "title": meta.get("title") or name,
            "date": str(meta.get("date", ""))[:10],
            "draft": str(meta.get("draft", "")).lower() in ("true", "yes", "1"),
            "template": name.startswith("_"),
            "words": len(re.findall(r"[A-Za-z0-9'-]+", body)),
            "topics": build.as_list(meta.get("topics")),
        })
    return out


def read_issue(filename):
    path = safe_issue_path(filename)
    if not path or not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        meta, body = build.parse_frontmatter(f.read())
    if not isinstance(meta, dict):
        meta = {}

    papers = []
    for p in build.as_list(meta.get("papers")):
        papers.append(p if isinstance(p, dict) else {"title": str(p)})

    return {
        "file": os.path.basename(path),
        "title": meta.get("title", ""),
        "date": str(meta.get("date", ""))[:10],
        "slug": meta.get("slug", ""),
        "summary": meta.get("summary", ""),
        "topics": [str(t) for t in build.as_list(meta.get("topics"))],
        "papers": papers,
        "draft": str(meta.get("draft", "")).lower() in ("true", "yes", "1"),
        "body": body,
    }


def glossary_terms():
    build.GLOSSARY.clear()
    entries = build.load_glossary()
    return [{"term": e["term"], "slug": e["slug"], "definition": e["definition"]}
            for e in entries]


def all_topics():
    seen = {}
    for it in list_issues():
        for t in it["topics"]:
            seen[str(t)] = seen.get(str(t), 0) + 1
    return [t for t, _n in sorted(seen.items(), key=lambda kv: (-kv[1], kv[0].lower()))]


# --------------------------------------------------------------------------
# Live preview, rendered with the real site pipeline
# --------------------------------------------------------------------------

def render_preview(payload):
    body = payload.get("body", "") or ""
    del build.WARNINGS[:]
    build.GLOSSARY.clear()
    build.load_glossary()
    html, headings = build.markdown(body)

    meta = payload.get("meta") or {}
    papers = [p for p in (meta.get("papers") or [])
              if str(p.get("title", "")).strip()]

    words = len(re.findall(r"[A-Za-z0-9'-]+", body))
    heads = [h["text"].lower() for h in headings]
    expected = ["what they did", "what they found", "why it matters",
                "what this doesn't tell us", "what to watch next"]

    return {
        "html": html,
        "papers_html": build.paper_block(papers),
        "words": words,
        "minutes": max(1, round(words / 200.0)),
        "warnings": list(build.WARNINGS),
        "headings": [{"text": h["text"], "level": h["level"]} for h in headings],
        "checklist": [{"section": e, "present": any(e in h for h in heads)} for e in expected],
    }


def save_issue(payload):
    meta = payload.get("meta") or {}
    body = payload.get("body", "") or ""
    original = payload.get("original_file") or ""

    if not str(meta.get("title", "")).strip():
        return {"ok": False, "error": "An issue needs a title before it can be saved."}
    if not str(meta.get("date", "")).strip():
        return {"ok": False, "error": "An issue needs a date before it can be saved."}

    if not str(meta.get("slug", "")).strip():
        meta["slug"] = build.slugify(meta["title"])

    name = filename_for(meta)
    path = safe_issue_path(name)
    if not path:
        return {"ok": False, "error": "That title produces an unusable filename."}

    old_path = safe_issue_path(original) if original else None
    renamed = bool(old_path and os.path.exists(old_path)
                   and os.path.basename(old_path) != name)

    # Refuse to silently overwrite a different existing issue.
    if os.path.exists(path) and (not old_path or os.path.basename(old_path) != name):
        if not payload.get("overwrite"):
            return {"ok": False, "error":
                    "An issue file named %s already exists. Change the title, the date, "
                    "or the URL slug." % name}

    text = to_frontmatter(meta) + "\n\n" + body.strip() + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)

    if renamed:
        try:
            os.remove(old_path)
        except OSError:
            pass

    return {"ok": True, "file": name, "renamed": renamed,
            "url": "/issues/%s/" % build.slugify(meta["slug"]),
            "saved_at": datetime.now().strftime("%H:%M:%S")}


def delete_issue(filename):
    path = safe_issue_path(filename)
    if not path or not os.path.exists(path):
        return {"ok": False, "error": "No such issue."}
    os.remove(path)
    return {"ok": True}


# --------------------------------------------------------------------------
# Request handling, called from build.serve()
# --------------------------------------------------------------------------

def _send(handler, obj, status=200):
    payload = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(payload)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(payload)


def _send_file(handler, name):
    path = os.path.join(ADMIN_DIR, name)
    if not os.path.exists(path):
        handler.send_error(404, "Editor file missing: %s" % name)
        return
    with open(path, "rb") as f:
        data = f.read()
    handler.send_response(200)
    handler.send_header("Content-Type", TYPES.get(os.path.splitext(name)[1], "text/plain"))
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(data)


def handle_get(handler, path):
    if path in STATIC:
        if path == "/admin":
            handler.send_response(301)
            handler.send_header("Location", "/admin/")
            handler.end_headers()
            return True
        _send_file(handler, STATIC[path])
        return True

    if path == "/api/issues":
        _send(handler, {"issues": list_issues(), "topics": all_topics()})
        return True

    if path == "/api/glossary":
        _send(handler, {"terms": glossary_terms()})
        return True

    if path.startswith("/api/issue/"):
        data = read_issue(path[len("/api/issue/"):])
        if data is None:
            _send(handler, {"error": "Not found"}, 404)
        else:
            _send(handler, data)
        return True

    if path == "/api/new":
        today = date.today()
        nxt = today.toordinal() + ((5 - today.weekday()) % 7)
        _send(handler, {"date": date.fromordinal(nxt).isoformat()})
        return True

    return False


def handle_post(handler, path):
    if not path.startswith("/api/"):
        return False
    try:
        length = int(handler.headers.get("Content-Length") or 0)
        payload = json.loads(handler.rfile.read(length).decode("utf-8")) if length else {}
    except (ValueError, UnicodeDecodeError):
        _send(handler, {"ok": False, "error": "Could not read the request."}, 400)
        return True

    if path == "/api/preview":
        _send(handler, render_preview(payload))
        return True
    if path == "/api/save":
        _send(handler, save_issue(payload))
        return True
    if path == "/api/delete":
        _send(handler, delete_issue(payload.get("file")))
        return True

    _send(handler, {"ok": False, "error": "Unknown endpoint."}, 404)
    return True
