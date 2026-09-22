# PD Brief

The website for **pdbrief.org** — an independent weekly summary of newly published
Parkinson's disease research, written for people without a scientific background.

You write each issue as a Markdown file. A small Python script turns the whole
folder into a fast, accessible static website. No frameworks, no `npm install`,
no database, and nothing to keep patched.

---

## The weekly routine

**1. Open the writing desk**

Double-click **Write PD Brief** on your Desktop.

A small black window appears and your browser opens the writing desk. Leave that
window open while you write; close it when you are done. That is the whole
startup routine — there is nothing to type. If the desk is already running,
double-clicking again just opens it in your browser rather than starting a
second copy.

If you would rather use a terminal:

```bash
cd ~/pdbrief && python3 build.py --serve
```

Either way the writing desk is at **<http://localhost:8000/admin/>** and the site
itself is at **<http://localhost:8000>**. Both live only on your Mac. Nobody else
can reach them, and neither exists when the window is closed.

The desk is a proper editor for PD Brief. You never open a text file or type any
Markdown.

It gives you:

- **Real fields** for the headline, date, summary, topics, and each study's
  citation — no raw frontmatter
- **A visual writing surface.** Headings look like headings, callouts look like
  callouts, tables are real tables you type into. You never see `##`, `:::`,
  or any other markup.
- **A style menu** — Body text, Section heading, Smaller heading, Bulleted list,
  Numbered list, Quotation
- **An Insert menu** for the Key takeaway, In plain terms and Important caution
  boxes, comparison tables, and the six standard section headings
- **Explain a word** — select a word, pick a glossary entry, and readers get a
  tap-to-see definition. Click an explained word again to change or remove it.
  If the word is not in the glossary yet, open **Add a new word to the glossary**
  at the bottom of the same window: it is added and used in one step.
- **A live preview** on the right, rendered by the real site, so what you see is
  exactly what readers get
- **A checks panel** that flags missing house sections, undefined glossary terms,
  a missing summary, topic or study link, and whether the length is in range
- **A draft switch** — an issue stays off the public site until you flip it
- **Rewrite from scratch** — on a published issue, starts a fresh draft with the
  same study, topics and web address, while the original stays live. When you
  switch the draft off and save, the desk offers to publish it in place of the
  original, which is set aside rather than destroyed.
- **Undo** — deleting an issue shows an Undo button for a few seconds. Deleted
  and replaced issues are kept in a hidden `.trash` folder in the project, which
  is never published or committed.

Under the hood it still reads and writes ordinary Markdown files, so nothing is
locked in. Opening an issue and saving it again leaves the file semantically
identical, and anything the editor does not recognise is preserved untouched.

Press **⌘S** or click Save. The file is written for you and the site rebuilds
in about a second. Drafts also save themselves every 30 seconds; a published
issue is only written when you press Save, so a half-finished edit to it can
never go out with your next push. The desk reopens whichever issue you last had
open, and **View this issue** in the header opens it as a full page.

**Seeing a draft as a real page.** The writing desk shows a live preview, but
to read a draft as a full page, click **Drafts** in the desk header or visit
<http://localhost:8000/drafts/>. These pages carry a warning banner and exist
only on your machine: a real build leaves them out of the site, the feed, the
sitemap and the search index entirely.

**2. Publish**

Open **GitHub Desktop**. Your changes are listed on the left. Type a short note
in the Summary box — "Issue 4" is fine — click **Commit to main**, then
**Push origin**.

GitHub rebuilds and deploys the site automatically. The live version updates in
a minute or two. Saving in the writing desk only changes the copy on your Mac;
nothing reaches pdbrief.org until you push.

GitHub also rebuilds the site once a day on its own, so date-dependent wording
("This week's issue" becoming "The latest issue") stays accurate in a week when
you do not push anything.

From a terminal instead: `git add . && git commit -m "Issue 4" && git push`

> The writing desk runs only on your own machine, from the preview server. It is
> never copied into the built site, so it cannot be reached from the public web
> and needs no password. The preview server also refuses connections from other
> devices on the same Wi-Fi, and requests from other websites open in your
> browser, so nobody else can edit or delete an issue through it.
>
> Once an issue has been saved, its web address stays fixed even if you later
> change the headline, so links people have shared keep working. To move it
> deliberately, edit the **Web address** field.

### If you prefer plain files

The desk just reads and writes ordinary Markdown, so nothing stops you editing
the files directly. `python3 new-issue.py "Your headline"` scaffolds one, and the
preview rebuilds on every save. The two approaches can be mixed freely.

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
| `corrections` | no | A dated list, published at the foot of the issue. See below. |

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

### Correcting a published issue

Your editorial policy promises that corrections are published on the issue
rather than edited away. Add them to the issue's frontmatter:

```yaml
corrections:
  - date: 2026-10-01
    note: "Corrected the participant count from 190 to 194."
```

They appear in a marked block at the foot of that issue. The writing desk does
not manage this field, but it will not disturb it either: anything you add to
the frontmatter by hand is preserved when you save from the editor.

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
| Your name on the byline (`editor_name`) | `site.json` — leave it empty to publish without a byline |
| Glossary terms | `content/glossary.md` — `## Term` then a paragraph |
| About page | `content/pages/about.md` |
| How we read a study | `content/pages/how-we-read-a-study.md` |
| A brand new standing page | Add any `.md` file to `content/pages/` |
| Colours, fonts, spacing | `assets/style.css` — the palette is at the very top |
| Interface behaviour | `assets/site.js` |
| The writing desk | `admin.py` and `admin/` — local only, never published |

Adding a Markdown file to `content/pages/` publishes it at `/its-slug/`
automatically. Add it to the `nav` list in `site.json` if you want it in the menu.

### Questions and feedback from readers

Set `feedback_form_url` in `site.json` to your Google Form address and three
things switch on automatically:

- a **/ask/** page explaining what readers can send, with the form on it
- an **Ask a question** link in the footer
- a short **invitation at the end of every issue**

Leave it empty and all three disappear, with no broken links left behind.

Use the long `docs.google.com/forms/d/e/.../viewform` address if you want the
form shown inside the page. A `forms.gle` short link cannot be embedded, so it
is shown as a button that opens the form in a new tab instead — the build tells
you when it makes that choice. Set `feedback_embed` to `false` to always use the
button, which avoids loading anything from Google onto your page.

The page carries a standing note asking readers not to send medical questions,
since answering those is outside what this publication can responsibly do.

### Newsletter signups

Set `subscribe_url` in `site.json` to a Buttondown, Substack, Mailchimp, or
similar signup page, and the closing note at the foot of the homepage gains a
"Get it by email" link. Leave it empty and the note points readers at the
archive instead.

---

## Commands

| Command | What it does |
| --- | --- |
| Double-click `Write PD Brief.command` | **The one you want.** Starts everything and opens the writing desk |
| `python3 build.py --serve` | The same thing, from a terminal |
| `python3 build.py --serve --open` | As above, and opens the browser for you |
| `python3 build.py` | Build the site into `_site/` once |
| `python3 build.py --check` | Report problems without writing anything |
| `python3 new-issue.py "Title"` | Scaffold an issue file, if you'd rather not use the desk |

`--check` is worth running before you push. It flags missing titles, unreadable
dates, duplicate URLs, and glossary terms you used but never defined.

---

## What gets built

Every build regenerates `_site/` from scratch:

- The homepage, with the latest issue featured
- A page for every issue, at `/issues/<slug>/`
- `/archive/` — every issue, with topic filters and search that looks inside
  the full text of each issue, not just titles and summaries
- `/topics/` and a page per topic, so a reader can follow one thread over time
- `/sources/` — every study you have covered, grouped by issue, with authors,
  journal, year and a DOI link. Built automatically from the `papers` field, so
  it stays correct without any upkeep.
- `/glossary/` — every term, searchable
- An RSS feed at `/feed.xml`, with full article text
- `sitemap.xml` and `robots.txt` for search engines
- Structured data on each issue so Google understands what it is
- A `404.html` that suggests recent issues
- `CNAME`, which only matters if you ever switch to deploying from a branch

`_site/` is deliberately not committed to git — GitHub rebuilds it on every push.

---

## Publishing on GitHub

Do this once.

**1. Make a GitHub account** at <https://github.com/signup> if you don't have one.

**2. Install GitHub Desktop** from <https://desktop.github.com> and sign in with
that account. It handles your login and your git identity for you, so there is
no terminal setup and no access token to create.

**3. Add this folder.** File → Add Local Repository → choose the `pdbrief` folder
in your home folder.

**4. Publish it.** Click **Publish repository**. Name it `pdbrief`, and
**untick "Keep this code private"** — GitHub Pages is free only for public
repositories. Click Publish.

**5. Turn on Pages.** On github.com, open the repository → **Settings → Pages →
Build and deployment → Source**, and choose **GitHub Actions**. Not "Deploy from
a branch".

**6. Re-run the first build.** The **Actions** tab will show a red failed run.
That is expected: it ran the moment you published, before Pages was switched on.
Open it and click **Re-run all jobs**. When it goes green, the site is deployed.

Don't judge it at `https://YOUR-USERNAME.github.io/pdbrief/`. The site is built
to sit at the root of its own domain, so at that temporary address it appears
unstyled with broken links. That is expected and goes away once pdbrief.org is
connected.

From then on, every push to `main` republishes the site. You can also edit an
issue directly on github.com — press `.` in the repository for a web editor — and
it deploys the same way. If you do, click **Fetch origin** in GitHub Desktop before
you next write on your Mac, so the two stay in step.

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

`url` is used for the RSS feed, the sitemap, and social preview links — it must
be the real, final address. The custom domain itself is stored in the repository's
Pages settings, not in any file: because this site deploys through GitHub Actions,
GitHub ignores the `CNAME` file the build writes.

### If the domain doesn't work

- **Give it time.** DNS changes are often quick but can take a few hours.
- **Check propagation** at <https://dnschecker.org> — enter `pdbrief.org`, choose
  `A`, and confirm the four GitHub addresses appear.
- **"Domain does not resolve to the GitHub Pages server"** means GoDaddy's
  original parked records are still there. Delete them.
- **The custom domain field is empty again.** Re-enter `pdbrief.org` under
  Settings → Pages. With Actions deploys the setting lives there, not in a file.

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
engines and screen readers. JavaScript only adds the extras: dark mode,
glossary pop-ups, archive search.

### Accessibility

The audience includes people with tremor, reduced dexterity, and changing vision,
so this is treated as a feature and not an afterthought:

- a light/dark toggle, remembered between visits (light is the default)
- browser zoom works everywhere, since nothing is sized in fixed pixels
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
