# PD Brief

The website for **pdbrief.org** — an independent weekly summary of newly published
Parkinson's disease research, written for people without a scientific background.

You write each issue as a Markdown file. A small Python script turns the whole
folder into a fast, accessible static website. No frameworks, no `npm install`,
no database, and nothing to keep patched.

---

## The weekly routine

Three commands, once a week.

**1. Start the issue**

```bash
python3 new-issue.py "Your headline goes here"
```

This creates `content/issues/2026-09-06-your-headline-goes-here.md`, dated to the
next Saturday, pre-filled with the standard structure and marked `draft: true`
so it stays off the live site while you work.

**2. Write it, watching the result**

```bash
python3 build.py --serve
```

Opens a preview at <http://localhost:8000>. Leave it running: every time you save
the Markdown file, the site rebuilds within a second. Refresh the browser to see it.
Editing `build.py` itself restarts the preview automatically.

When the issue is ready, delete the `draft: true` line from the file.

**3. Publish**

```bash
git add . && git commit -m "Issue 4: your headline" && git push
```

GitHub rebuilds and deploys the site automatically. The live version updates in
a minute or two.

---

## Writing an issue

Every issue is one Markdown file in `content/issues/`. The filename should be
`YYYY-MM-DD-short-slug.md`.

The top of the file, between the `---` lines, is the issue's metadata:

```yaml
---
title: "A diabetes drug that seemed to slow Parkinson's down"
date: 2026-08-23
slug: lixisenatide-diabetes-drug
summary: "Two or three sentences. Shown on the homepage, in the archive, in the
  RSS feed, and in Google results."
topics: [Clinical Trials, Drug Repurposing]
papers:
  - title: "Trial of Lixisenatide in Early Parkinson's Disease"
    authors: "Meissner WG, Remy P, Giordana C, et al."
    journal: "New England Journal of Medicine"
    year: 2024
    doi: "10.1056/NEJMoa2312323"
    access: "Free abstract"
---
```

| Field | Required | Notes |
| --- | --- | --- |
| `title` | yes | Plain language. This is the headline readers see. |
| `date` | yes | `YYYY-MM-DD`. Controls ordering and the issue number. |
| `slug` | no | The URL. Defaults to the filename with the date stripped off. |
| `summary` | yes | Two or three sentences. Generated from the opening if you omit it. |
| `topics` | no | Any words you like. Topic pages are created automatically. |
| `papers` | no | One entry per study. Builds the citation box at the bottom. |
| `issue` | no | Force an issue number. Otherwise numbered automatically by date. |
| `draft` | no | `draft: true` keeps an issue off the site while you write it. |

**Issue numbers are automatic.** The oldest issue is number 1 and each new one
increments. You never have to track it.

### Formatting available in the body

Standard Markdown — `**bold**`, `*italic*`, `[links](https://example.com)`,
`## headings`, bullet and numbered lists, `> quotes`, and pipe tables — plus two
things built specifically for this publication.

**Glossary terms.** Write `{{dopamine}}` and the word becomes tappable: readers
get a plain-language definition in a small pop-up without leaving the page. Use
`{{seed amplification assay|the test}}` when you want different words shown.
Terms are defined once in `content/glossary.md` and reused everywhere. If you
reference a term that isn't defined, the build tells you.

**Callout boxes.** Five kinds:

```
:::key
The single most important finding.
:::
```

`:::key` (key takeaway), `:::plain` (in plain terms), `:::caution` (a warning
against over-reading), `:::note`, and `:::context`. Close each one with `:::`.

### The house structure

The template follows the same shape every week, which is what makes an archive
readable years later:

1. Open with the finding, in plain terms
2. `## What the researchers were trying to find out`
3. `## What they did`
4. `## What they found`
5. `## Why it matters`
6. `## What this doesn't tell us` — never skip this one
7. `## What to watch next`

`content/issues/_TEMPLATE.md` has the full scaffold. Files starting with `_`
are ignored by the build.

---

## Everything else you can edit

| What | Where |
| --- | --- |
| Site name, tagline, description, navigation | `site.json` |
| Glossary terms | `content/glossary.md` — `## Term` then a paragraph |
| About page | `content/pages/about.md` |
| How we read a study | `content/pages/how-we-read-a-study.md` |
| A brand new standing page | Add any `.md` file to `content/pages/` |
| Colours, fonts, spacing | `assets/style.css` — the palette is at the very top |
| Interface behaviour | `assets/site.js` |

Adding a Markdown file to `content/pages/` publishes it at `/its-slug/`
automatically. Add it to the `nav` list in `site.json` if you want it in the menu.

### Newsletter signups

Set `subscribe_url` in `site.json` to a Buttondown, Substack, Mailchimp, or
similar signup page, and the homepage banner turns into a working Subscribe
button. Leave it empty and the banner points at the RSS feed instead.

---

## Commands

| Command | What it does |
| --- | --- |
| `python3 build.py` | Build the site into `_site/` |
| `python3 build.py --serve` | Build, preview at localhost:8000, rebuild on save |
| `python3 build.py --check` | Report problems without writing anything |
| `python3 new-issue.py "Title"` | Scaffold a new issue |

`--check` is worth running before you push. It flags missing titles, unreadable
dates, duplicate URLs, and glossary terms you used but never defined.

---

## What gets built

Every build regenerates `_site/` from scratch:

- The homepage, with the latest issue featured
- A page for every issue, at `/issues/<slug>/`
- `/archive/` — every issue, with live search and topic filters
- `/topics/` and a page per topic, so a reader can follow one thread over time
- `/glossary/` — every term, searchable
- An RSS feed at `/feed.xml`, with full article text
- `sitemap.xml` and `robots.txt` for search engines
- Structured data on each issue so Google understands what it is
- A `404.html` that suggests recent issues
- `CNAME`, so the custom domain survives every deploy

`_site/` is deliberately not committed to git — GitHub rebuilds it on every push.

---

## Publishing on GitHub

Do this once.

**1. Create the repository**

Go to <https://github.com/new>. Name it `pdbrief` (or anything). Public. Do not
add a README, `.gitignore`, or licence — this folder already has what it needs.

**2. Push this folder**

```bash
git init -b main
git add .
git commit -m "PD Brief: initial site"
git remote add origin https://github.com/YOUR-USERNAME/pdbrief.git
git push -u origin main
```

**3. Turn on Pages**

In the repository: **Settings → Pages → Build and deployment → Source**, and
choose **GitHub Actions**. Not "Deploy from a branch" — the workflow in
`.github/workflows/deploy.yml` handles it.

**4. Watch the first build**

The **Actions** tab shows the build running. When it goes green, the site is live
at `https://YOUR-USERNAME.github.io/pdbrief/` until the domain is connected.

From then on, every `git push` to `main` republishes the site. You can also add
or edit an issue directly on github.com — press `.` in the repository to open a
web editor — and it deploys the same way. That works from a phone.

---

## Connecting pdbrief.org from GoDaddy

Buy `pdbrief.org` at GoDaddy, then point it at GitHub.

**1. In GoDaddy → My Products → your domain → DNS → Manage Zones**

Delete the parked-page records GoDaddy adds by default (usually an `A` record on
`@` pointing at a GoDaddy IP, and a `CNAME` on `www`). Then add these five:

| Type | Name | Value | TTL |
| --- | --- | --- | --- |
| A | `@` | `185.199.108.153` | 1 hour |
| A | `@` | `185.199.109.153` | 1 hour |
| A | `@` | `185.199.110.153` | 1 hour |
| A | `@` | `185.199.111.153` | 1 hour |
| CNAME | `www` | `YOUR-USERNAME.github.io` | 1 hour |

The four A records are GitHub's Pages servers — all four, for redundancy. The
`CNAME` value must end in a dot in some interfaces (`YOUR-USERNAME.github.io.`);
GoDaddy usually adds it for you.

**2. In GitHub → Settings → Pages → Custom domain**

Enter `pdbrief.org` and save. GitHub checks the DNS, which can take anywhere from
a few minutes to a few hours.

**3. Tick "Enforce HTTPS"**

The checkbox stays greyed out until GitHub has issued the certificate — usually
under an hour after DNS resolves. Come back and tick it. Do not skip this.

**4. Check `site.json`**

It should already say:

```json
"domain": "pdbrief.org",
"url": "https://pdbrief.org"
```

`domain` is what writes the `CNAME` file into every build, which is what stops
GitHub forgetting the custom domain. `url` is used for the RSS feed, the sitemap,
and social preview links — it must be the real, final address.

### If the domain doesn't work

- **Give it time.** DNS changes are often quick but can take a few hours.
- **Check propagation** at <https://dnschecker.org> — enter `pdbrief.org`, choose
  `A`, and confirm the four GitHub addresses appear.
- **"Domain does not resolve to the GitHub Pages server"** means GoDaddy's
  original parked records are still there. Delete them.
- **The custom domain empties itself** if the `CNAME` file goes missing from a
  build. `site.json` prevents that, so make sure `domain` stays set.

---

## How it works, briefly

`build.py` is one dependency-free Python file, about 1,400 lines:

- reads `site.json`, `content/glossary.md`, `content/issues/*.md`, `content/pages/*.md`
- parses the `---` frontmatter with a small YAML subset parser
- renders Markdown with a purpose-built renderer that also handles callouts,
  pipe tables, and glossary terms
- writes complete HTML pages, a feed, a sitemap, and a search index into `_site/`

Because every page is real HTML written to disk, the site works without
JavaScript, loads fast on a poor connection, and is fully readable by search
engines and screen readers. JavaScript only adds the extras: text size, dark
mode, glossary pop-ups, archive search.

### Accessibility

The audience includes people with tremor, reduced dexterity, and changing vision,
so this is treated as a feature and not an afterthought:

- a reader-controlled text size, remembered between visits
- a light/dark toggle that also respects the system setting
- large touch targets and visible focus outlines throughout
- semantic HTML, a skip link, and labelled controls for screen readers
- honours `prefers-reduced-motion`
- a print stylesheet, so an issue can be printed and brought to an appointment

---

## A note on the three sample issues

`content/issues/` ships with three worked examples built around real, published
studies. They are there to show the format — including how the archive lets a
reader follow one thread across weeks, which is what issues 2 and 3 demonstrate.

**Verify every figure and citation against the original papers before you publish
them**, or delete the files and start with your own. The DOI on the exenatide
issue is deliberately left blank and marked in a comment.
