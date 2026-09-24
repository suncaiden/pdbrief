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
import shutil
import subprocess
import threading
import time
from datetime import date, datetime

import build

ADMIN_DIR = os.path.join(build.ROOT, "admin")

# Deleted and replaced issues are moved here rather than destroyed, so the
# desk can offer Undo. The folder is ignored by git and by the build.
TRASH_DIR = os.path.join(build.ROOT, ".trash")

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
    field is folded into a space. Quotes and backslashes are escaped, and the
    reader in build.py undoes that.
    """
    s = re.sub(r"\s+", " ", str(value)).strip()
    return '"%s"' % s.replace("\\", "\\\\").replace('"', '\\"')


def _topic(value):
    """A topic inside [a, b]: quoted only when it would otherwise be misread,
    such as one containing a comma or one that looks like yes, no or a number."""
    t = re.sub(r"\s+", " ", str(value)).strip()
    if (re.search(r"[,\[\]\"'#:]", t) or t.lower() in ("yes", "no", "true", "false", "null", "~")
            or re.fullmatch(r"-?\d+(\.\d+)?", t)):
        return _quote(t)
    return t


KNOWN_KEYS = {"title", "date", "slug", "summary", "topics", "papers", "draft"}


def preserved_lines(path):
    """Frontmatter the editor does not manage, returned as raw lines.

    Anything the writer added by hand -- a forced `issue:` number, a
    `corrections:` list -- would otherwise be dropped the next time the issue
    was saved from the editor.
    """
    if not path or not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        text = f.read().replace("\r\n", "\n")
    if not text.startswith("---"):
        return []
    end = text.find("\n---", 3)
    if end == -1:
        return []

    out, keeping = [], False
    for line in text[3:end].split("\n"):
        if line.strip().startswith("#") or not line.strip():
            keeping = False
            continue
        if line[:1] not in (" ", "\t"):          # a new top-level key
            key = line.split(":", 1)[0].strip()
            keeping = key not in KNOWN_KEYS
        if keeping:
            out.append(line.rstrip())
    return out


def existing_comments(path):
    """Comment lines a writer put in the frontmatter, so saving never eats them."""
    if not path or not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        text = f.read().replace("\r\n", "\n")
    if not text.startswith("---"):
        return []
    end = text.find("\n---", 3)
    if end == -1:
        return []
    return [ln for ln in text[3:end].split("\n") if ln.strip().startswith("#")]


def to_frontmatter(meta, comments=None, preserved=None):
    lines = ["---"]
    for line in (comments or []):
        lines.append(line.rstrip())
    for key in ("title", "date", "slug", "summary"):
        if meta.get(key) not in (None, ""):
            lines.append("%s: %s" % (key, _quote(meta[key])))

    topics = [t for t in meta.get("topics", []) if str(t).strip()]
    if topics:
        lines.append("topics: [%s]" % ", ".join(_topic(t) for t in topics))

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

    for line in (preserved or []):
        lines.append(line)

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


_status_cache = {"at": 0, "value": None}


def publish_status():
    """How much work is sitting on this Mac and not yet on pdbrief.org.

    Counted from git: files changed since the last commit, plus commits that
    have not been pushed. Cached for a few seconds so typing stays quick.
    """
    if time.time() - _status_cache["at"] < 5 and _status_cache["value"]:
        return _status_cache["value"]

    def git(*args):
        return subprocess.run(("git", "-C", build.ROOT) + args, capture_output=True,
                              text=True, timeout=5)

    out = {"ok": True, "changed": 0, "unpushed": 0, "repo": ""}
    try:
        r = git("status", "--porcelain", "--", "content", "assets", "site.json")
        out["changed"] = len([l for l in r.stdout.splitlines() if l.strip()])
        r = git("rev-list", "--count", "@{u}..HEAD")
        out["unpushed"] = int(r.stdout.strip() or 0) if r.returncode == 0 else 0
        r = git("remote", "get-url", "origin")
        url = r.stdout.strip()
        if url.startswith("git@github.com:"):
            url = "https://github.com/" + url.split(":", 1)[1]
        out["repo"] = url[:-4] if url.endswith(".git") else url
    except Exception as exc:                       # git missing, no remote, etc.
        out = {"ok": False, "error": str(exc)[:120], "changed": 0, "unpushed": 0, "repo": ""}

    _status_cache.update(at=time.time(), value=out)
    return out


def glossary_terms():
    with RENDER_LOCK:
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

# The preview and the glossary list share the renderer's module-level state,
# and requests now arrive on separate threads, so they take turns.
RENDER_LOCK = threading.Lock()


def render_preview(payload):
    with RENDER_LOCK:
        return _render_preview(payload)


def _render_preview(payload):
    body = payload.get("body", "") or ""
    del build.WARNINGS[:]
    build.GLOSSARY.clear()
    build.load_glossary()
    html, headings = build.markdown(body)

    meta = payload.get("meta") or {}
    papers = [p for p in (meta.get("papers") or [])
              if str(p.get("title", "")).strip()]

    words = len(re.findall(r"[A-Za-z0-9'-]+", body))
    heads = [h["text"].lower().replace("\u2019", "'") for h in headings]
    expected = ["what they did", "what they found", "why it matters",
                "what this doesn't tell us", "what to watch next"]

    # Things a reader would miss, checked on the form fields as well as the text.
    warnings = list(build.WARNINGS)
    summary = str(meta.get("summary") or "").strip()
    if not summary:
        warnings.append("Add a summary. It is what shows on the homepage, in the archive "
                        "and in Google.")
    elif len(summary) > 300:
        warnings.append("The summary is %d characters. Under 300 reads best on the homepage."
                        % len(summary))
    if not [t for t in (meta.get("topics") or []) if str(t).strip()]:
        warnings.append("Add at least one topic, so the issue appears on a topic page.")
    if not papers:
        warnings.append("Fill in the study behind this issue, so readers can find the "
                        "original paper.")
    when = str(meta.get("date") or "")[:10]
    if when and not meta.get("draft"):
        try:
            if build.parse_date(when, "editor") > date.today():
                warnings.append("The date is in the future. The issue still goes live as "
                                "soon as you push.")
        except Exception:
            pass
    elif not all(str(p.get("doi") or p.get("url") or "").strip() for p in papers):
        warnings.append("A study has no DOI, so readers cannot follow a link to it.")

    return {
        "html": html,
        "papers_html": build.paper_block(papers),
        "words": words,
        "minutes": max(1, round(words / 200.0)),
        "warnings": warnings,
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

    # Two published issues sharing a web address means one quietly disappears
    # from the site. A draft may share it, though: that is how a rewrite is
    # written while the original stays live. Publishing the draft then offers
    # to replace the original, which is moved to the trash.
    wanted_slug = build.slugify(meta["slug"])
    is_draft = bool(meta.get("draft"))
    replace = os.path.basename(str(payload.get("replace") or ""))
    replacing = None
    for other in list_issues():
        if other["template"]:
            continue
        if old_path and other["file"] == os.path.basename(old_path):
            continue
        data = read_issue(other["file"])
        if not data:
            continue
        if issue_slug(data, other["file"]) != wanted_slug:
            continue
        if is_draft != other["draft"]:
            continue    # one is a draft, so only one of them is ever on the site
        if not is_draft:
            if replace == other["file"]:
                replacing = other["file"]
                continue
            return {"ok": False, "conflict": other["file"], "conflict_title": data["title"],
                    "error": "\u201c%s\u201d is already published at /issues/%s/."
                             % (data["title"], wanted_slug)}
        return {"ok": False, "error":
                "\u201c%s\u201d already uses the web address /issues/%s/. Change the "
                "web address so the two do not collide." % (data["title"], wanted_slug)}

    # A rewrite given the original's date would share its file name, so the
    # draft gets a suffix on disk. The web address comes from the slug, not
    # the file name, so readers never see it.
    if (is_draft and os.path.exists(path) and path != old_path
            and issue_slug(read_issue(name) or {}, name) == wanted_slug
            and not (read_issue(name) or {}).get("draft")):
        name = name[:-3] + "-rewrite.md"
        path = safe_issue_path(name)
        renamed = bool(old_path and os.path.exists(old_path)
                       and os.path.basename(old_path) != name)

    # Refuse to silently overwrite a different existing issue.
    if (os.path.exists(path) and (not old_path or os.path.basename(old_path) != name)
            and replacing != name):
        if not payload.get("overwrite"):
            return {"ok": False, "error":
                    "An issue file named %s already exists. Change the headline, the "
                    "date, or the web address." % name}

    source = old_path if (old_path and os.path.exists(old_path)) else path
    keep = existing_comments(source)
    extra = preserved_lines(source)
    text = to_frontmatter(meta, keep, extra) + "\n\n" + body.strip() + "\n"

    # The version being replaced goes to the trash first, so it can be restored.
    trashed = move_to_trash(replacing) if replacing else None

    with open(path, "w", encoding="utf-8") as f:
        f.write(text)

    if renamed:
        try:
            os.remove(old_path)
        except OSError:
            pass

    return {"ok": True, "file": name, "renamed": renamed, "replaced": replacing,
            "trashed": trashed,
            "slug": build.slugify(meta["slug"]),
            "url": "/issues/%s/" % build.slugify(meta["slug"]),
            "saved_at": datetime.now().strftime("%H:%M:%S")}


def issue_slug(data, filename):
    """The web address the build will give an issue: its slug, or failing that
    its filename without the date, exactly as build.load_issues() decides."""
    return build.slugify(data.get("slug") or re.sub(r"^\d{4}-\d{2}-\d{2}-", "", filename[:-3]))


def move_to_trash(filename):
    """Move an issue file into .trash/ and return the name it was given there."""
    path = safe_issue_path(filename)
    if not path or not os.path.exists(path):
        return None
    os.makedirs(TRASH_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    trashed, n = "%s--%s" % (stamp, os.path.basename(path)), 2
    while os.path.exists(os.path.join(TRASH_DIR, trashed)):     # never overwrite
        trashed, n = "%s-%d--%s" % (stamp, n, os.path.basename(path)), n + 1
    shutil.move(path, os.path.join(TRASH_DIR, trashed))
    return trashed


def delete_issue(filename):
    trashed = move_to_trash(filename)
    if not trashed:
        return {"ok": False, "error": "No such issue."}
    return {"ok": True, "trashed": trashed}


def restore_issue(trashed):
    """Put a trashed issue back where it was, unless something has taken its place."""
    name = os.path.basename(str(trashed or ""))
    src = os.path.join(TRASH_DIR, name)
    if "--" not in name or not os.path.exists(src):
        return {"ok": False, "error": "That issue is no longer in the trash."}
    original = name.split("--", 1)[1]
    dest = safe_issue_path(original)
    if not dest:
        return {"ok": False, "error": "That file name is not usable."}
    if os.path.exists(dest):
        return {"ok": False, "error": "Another issue now uses the file name %s." % original}
    shutil.move(src, dest)
    return {"ok": True, "file": original}


def add_glossary_term(payload):
    """Append a new entry to content/glossary.md from the desk."""
    term = re.sub(r"\s+", " ", str(payload.get("term", ""))).strip()
    # A leading # would turn the definition into a heading in glossary.md.
    definition = re.sub(r"\s+", " ", str(payload.get("definition", ""))).strip().lstrip("#").strip()
    if not term or not definition:
        return {"ok": False, "error": "Give the word and a definition."}
    if len(term) > 80 or term.startswith("#"):
        return {"ok": False, "error": "That word is too long or starts with a symbol."}
    with RENDER_LOCK:
        build.GLOSSARY.clear()
        existing = {e["slug"] for e in build.load_glossary()}
    if build.slugify(term) in existing:
        return {"ok": False, "error": "\u201c%s\u201d is already in the glossary." % term}
    path = os.path.join(build.CONTENT, "glossary.md")
    with open(path, encoding="utf-8") as f:
        current = f.read()
    with open(path, "w", encoding="utf-8") as f:
        f.write(current.rstrip("\n") + "\n\n## %s\n\n%s\n" % (term, definition))
    return {"ok": True, "term": term, "terms": glossary_terms()}


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


def _local_request(handler):
    """True only for requests from this computer's own browser.

    The server already listens on 127.0.0.1 alone. Checking the Host header as
    well stops a web page from reaching it by pointing its own domain name at
    this machine, and checking Origin stops any other site open in the browser
    from sending the desk a save or delete.
    """
    host = (handler.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
    if host not in ("localhost", "127.0.0.1", "::1"):
        return False
    origin = handler.headers.get("Origin")
    if origin and not re.match(r"^http://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$", origin):
        return False
    return True


def _refuse(handler):
    _send(handler, {"ok": False, "error": "The writing desk only answers this computer."}, 403)
    return True


def handle_get(handler, path):
    if (path in STATIC or path.startswith("/api/")) and not _local_request(handler):
        return _refuse(handler)
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

    if path == "/api/status":
        _send(handler, publish_status())
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
    if not _local_request(handler):
        return _refuse(handler)
    # The editor always sends JSON. Requiring it means another site cannot
    # slip a request through as a plain form post.
    if not (handler.headers.get("Content-Type") or "").startswith("application/json"):
        _send(handler, {"ok": False, "error": "Expected JSON."}, 415)
        return True
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
    if path == "/api/restore":
        _send(handler, restore_issue(payload.get("trashed")))
        return True
    if path == "/api/glossary/add":
        _send(handler, add_glossary_term(payload))
        return True

    _send(handler, {"ok": False, "error": "Unknown endpoint."}, 404)
    return True
