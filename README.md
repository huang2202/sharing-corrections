# Sharing Corrections across Tasks: project page

A static page for the paper *Sharing Corrections across Tasks: A Study of
Generalizable Action Editing for Pretrained Robot Policies*. No framework, no
bundler, no external requests. Open `index.html` in a browser (it works when
opened as a local file), or serve the folder with any static server, for
example `python3 -m http.server` in this directory.

## Layout

```
index.html              the page, written by hand; values and charts sit in slots
assets/css/site.css     one light-theme stylesheet, no external requests
assets/fonts/           self-hosted OFL fonts (Inter Variable, IBM Plex Mono) and SOURCES.md
assets/js/site.js       enhancements only (clips, tabs, tooltips, recipe highlight, copy)
assets/charts/*.svg     the charts as stand-alone files
assets/img/             paper teaser, system figure, poster frames, thumbnails
assets/img/logos/       institution logos and SOURCES.md (origin and hash of each)
assets/video/           the ten replay clips, copied unchanged
data/site.json          authors, affiliations, logos, links, BibTeX key: edit by hand
data/site_data.json     every number and label shown on the page (generated)
data/ledger.json        for each value: source file, line, matched text (generated)
data/media.json         size and duration of each clip, figure sizes (generated)
build/                  the scripts below
```

## Where the numbers come from

No result number is typed into `index.html`, the charts or the scripts.

1. `build/build_data.py` reads the paper sources (TeX sections, generated
   tables and macros, JSON result files) and one archive of result files
   (RoboTwin correction scaling and the main-camera run of the bounded
   recipe), then writes
   `data/site_data.json` and `data/ledger.json`. Every pattern must match
   exactly once; a pattern that no longer matches stops the script with the
   file and the pattern, so a change in the paper cannot leave a stale number
   on the page. Values that the paper states as a range or a difference are
   recomputed from the table values and recorded in the ledger as derived,
   with their inputs.
2. `build/build_charts.py` draws every chart from `data/site_data.json`.
3. `build/stamp.py` fills the slots of `index.html` in place.

`data/ledger.json` has two parts: `sources` (path inside the paper tree or
`additions:` archive and sha256 of every file that was read) and `values`
(one entry per value).

## Rebuilding after the paper changes

The scripts read the paper from `--paper-root DIR` (`SC_PAPER_ROOT`) and the
public-additions ZIP or directory from `--additions PATH` (`SC_ADDITIONS_PATH`).
There are no built-in defaults, and local paths are never written into any
generated file.

```
export SC_PAPER_ROOT=path/to/the/paper/tree
export SC_ADDITIONS_PATH=path/to/gae_public_additions_20261125.zip
python build/build_data.py
python build/build_media.py --videos path/to/the/clips   # only when clips or paper figures change
python build/build_charts.py
python build/stamp.py
python build/check_site.py
```

`python build/build_data.py --check` rebuilds in memory, fails if
`data/site_data.json` would change, and reports whether `data/ledger.json` is
current. The scripts need Python 3.10 or later; `build_media.py` also needs
Pillow, `ffmpeg`, `ffprobe` and `pdftocairo`.

If `build_data.py` stops, read the message: it names the source file and the
pattern. Either the paper changed its wording (update the pattern in the
script) or a table changed shape (update the row or column it reads). Do not
work around a failure by typing the value.

## Editing the page

Edit `index.html` directly, then run `python build/stamp.py`. The script only
replaces the content of slots:

- `<span data-v="KEY" data-f="SPEC"></span>`: one value. `KEY` is a dotted
  path in `data/site_data.json`. `SPEC` is the number of decimals (`0` to
  `4`), with `+` for an explicit sign (`+2`) or `a` for the absolute value
  (`a2`); `int` adds thousands separators; `word` spells a small whole
  number. Text values need no `SPEC`.
- `<!--chart:NAME--><!--/chart-->`: a chart with its legend and value table.
- `<!--gen:NAME ARGS--><!--/gen-->`: a generated block. Names: `title`,
  `authors` (author line, affiliations, logos, notes), `links`, `teaser`
  (paper Figure 1), `loop` (closed-loop setup diagram), `clip ID`
  (for example `clip c07`), `clips GROUP ID "label" ID "label"` (several clips
  behind one switch), `gallery`, `matters` (the paper's summary table),
  `guide` (one-line answers of the appendix overview), `recipekey`, `bibtex`,
  `sysfig`, `defs`.

Tabs, clip switches and the gallery are one component: a row of links marked
`data-tab` that point at elements marked `data-panel` inside a `data-tabs`
container. Without scripting every panel is visible. A link to a panel's id
(for example `#training-seeds`) opens that panel.

`python build/check_site.py` verifies that the page is up to date, that every
local file and anchor exists, that nothing is loaded from another host, that
no digits were typed outside the slots (names such as L1, R3 or LIBERO-130 are
allowed), that every logo is recorded with its hash, and that no text file
holds an absolute path of a personal machine.

## Filling `data/site.json`

```
{
 "authors": [
  {"name": "Full Name", "affiliations": [1, 2], "url": "", "marks": ["*"]}
 ],
 "affiliations": [
  {"id": 1, "name": "Institution", "logo": "assets/img/logos/file.svg", "logo_alt": "Institution"}
 ],
 "author_notes": ["*Equal contribution"],
 "links": {"paper": "", "arxiv": "", "videos": "#gallery"},
 "bibtex": {"key": "huang2026sharing", "year": "2026", "authors": ""}
}
```

- An empty value renders nothing: an author without `url` is plain text, a
  link slot without a URL has no button, an affiliation without `logo` has no
  logo, an empty `authors` list removes the author block.
- `marks` are printed after the affiliation numbers of an author; explain
  each mark in `author_notes`.
- `links`: a button appears for each slot that holds a URL, in the order
  Paper, arXiv, Videos; the first one is filled, the others outlined.
  `videos` points at the gallery on the page.
- `bibtex.authors` overrides the author field of the entry; when it is empty
  the names of `authors` are joined with `and`.

Run `python build/stamp.py` after editing the file.

## Logos

`assets/img/logos/SOURCES.md` lists, for every logo, the address it was
retrieved from, the date and the SHA-256 of the stored file. Use official
artwork only, store it unchanged, and add a row for it; `check_site.py`
fails when a logo is not listed with its hash or when an SVG logo holds a
script or an external reference. Logos are shown at one height through
`<img>`, on a light chip in the dark theme.

## Clips and figure

`python build/build_media.py --videos DIR` copies the ten clips named in the
paper's clip table from `DIR` to `assets/video/` without re-encoding, cuts a
poster frame and a thumbnail for each with `ffmpeg`, renders the system figure
from the paper's PDF, and writes `data/media.json`. It stops if a listed clip
is missing or if `assets/video/` holds a clip that the paper does not list.

## Reading path

The sticky rail lists the sections without numbers; the four findings have
their own links (F1 to F4) beside `Findings`, and the supporting sections
(system, replays) follow a divider. `#takeaways` holds one card per finding
and per follow-up question (robustness, adaptation, beyond LIBERO); every
card states the claim, one line of evidence from the data slots, and links to
its section. The robustness tabs carry their one-line answer under the topic.
Section titles are questions and each is followed by its answer, as in the
paper.

`index.html` loads the stylesheet and the script with a version parameter
(`?v=...`). Change it whenever `site.css` or `site.js` changes, so that a
cached copy is not combined with newer markup.

## Before the page goes public

- `index.html` carries `<meta name="robots" content="noindex">`. Remove that
  line when the page is released.
- Fill the `paper` and `arxiv` slots of `data/site.json`.
- Link preview. The page has `og:title`, `og:description` and
  `twitter:card` (`summary`). A preview image needs an absolute address, so
  none is set. Once the public address is known, add to the `<head>`:

  ```
  <meta property="og:url" content="https://HOST/PATH/">
  <meta property="og:image" content="https://HOST/PATH/assets/img/preview.png">
  <meta property="og:image:alt" content="One sentence that describes the image">
  ```

  and change `twitter:card` to `summary_large_image`. A suitable image is
  1200 by 630 pixels, for example a poster frame of the first clip with the
  title; save it as `assets/img/preview.png`. `check_site.py` rejects an
  `og:image` that is not an absolute `https` address.
- The wording follows the paper: paired outcomes are shares of all paired
  episodes, differences are in points, causal verbs are kept for results of
  interventions (correction scaling, source-mean replacement, frozen editor
  vision, routing replacement), and the four finding statements are used
  verbatim.
