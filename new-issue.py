#!/usr/bin/env python3
"""
Start a new issue of PD Brief.

    python3 new-issue.py "A diabetes drug that seemed to slow Parkinson's down"
    python3 new-issue.py "Some headline" --date 2026-09-13

Creates content/issues/YYYY-MM-DD-slug.md from the template, pre-filled with
the title and date, and marked as a draft so it stays off the site until you
are ready. Remove the `draft: true` line to publish it.
"""

import os
import re
import sys
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.abspath(__file__))
ISSUES = os.path.join(ROOT, "content", "issues")


def slugify(s):
    s = s.lower().strip()
    s = re.sub(r"['’]", "", s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")[:60] or "untitled"


def next_saturday():
    today = date.today()
    return today + timedelta(days=(5 - today.weekday()) % 7)


TEMPLATE = '''---
title: "{title}"
date: {date}
slug: {slug}
summary: "Two or three sentences a reader could take away on their own. This appears on the homepage, in the archive, in the RSS feed, and in search results."
topics: [Clinical Trials]
papers:
  - title: "Exact title of the paper"
    authors: "Lastname A, Lastname B, et al."
    journal: "Journal name"
    year: {year}
    doi: "10.xxxx/xxxxx"
    access: "Free abstract"
# Delete the next line when this issue is ready to publish.
draft: true
---

Open with the finding in plain terms. Assume the reader knows nothing about the
topic and has no obligation to keep reading.

:::key
The single most important thing to take away, in two or three sentences.
:::

## What the researchers were trying to find out

## What they did

## What they found

## Why it matters

## What this doesn't tell us

## What to watch next

:::plain
A closing paragraph a reader could repeat to someone else.
:::
'''


def main():
    args = [a for a in sys.argv[1:]]
    when = next_saturday()
    if "--date" in args:
        i = args.index("--date")
        try:
            y, m, d = (int(x) for x in args[i + 1].split("-"))
            when = date(y, m, d)
        except (IndexError, ValueError):
            print("Could not read --date. Use the form --date 2026-09-13.")
            return 1
        del args[i:i + 2]

    if not args:
        print(__doc__.strip())
        return 1

    title = " ".join(args).strip()
    slug = slugify(title)
    name = "%s-%s.md" % (when.isoformat(), slug)
    path = os.path.join(ISSUES, name)

    if os.path.exists(path):
        print("That file already exists:\n  content/issues/%s" % name)
        return 1

    os.makedirs(ISSUES, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(TEMPLATE.format(title=title.replace('"', "'"), date=when.isoformat(),
                                slug=slug, year=when.year))

    print("")
    print("  Created content/issues/%s" % name)
    print("")
    print("  Next:")
    print("    1. Write the issue in that file.")
    print("    2. Delete the 'draft: true' line when it is ready.")
    print("    3. Run:  python3 build.py --serve   to preview it.")
    print("")
    return 0


if __name__ == "__main__":
    sys.exit(main())
