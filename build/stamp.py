#!/usr/bin/env python3
"""Fill the slots of index.html in place from the data files.

    python build/stamp.py            rewrite index.html
    python build/stamp.py --check    fail if index.html is not up to date

index.html is the hand-written page. It holds three kinds of slots, and this
script only ever replaces what is inside them:

  <span data-v="KEY" data-f="SPEC">...</span>
        one value of data/site_data.json, formatted (see common.fmt; SPEC
        "word" / "Word" spells a small whole number)
  <!--chart:NAME-->...<!--/chart-->     a chart with legend and value table
  <!--mini:NAME-->...<!--/mini-->       a small chart without table
  <!--gen:NAME ARGS-->...<!--/gen-->    a generated block; ARGS are words or
        "quoted text". Blocks: title, authors, links, clip ID, clips GROUP ID
        "label" ID "label" ..., gallery, matters, guide, recipekey, bibtex,
        sysfig, defs

The <title> element and the og:title meta tag are set to the paper title.
A slot that names an unknown key, chart or block stops the script.
"""
from __future__ import annotations

import argparse
import re
import shlex
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA, SITE, die, esc, fmt, load_json, lookup  # noqa: E402
import build_charts  # noqa: E402

INDEX = SITE / "index.html"
WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
         "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
         "eighteen", "nineteen", "twenty"]
LOGO_HEIGHT = 30          # px; every institution logo is shown at this height
WIDE_PANELS = 3           # clips with at least this many panels scroll sideways on phones

# Where each row of the paper's summary table is taken up on this page.
MATTERS_LINKS = {
    "Source breadth": ("#finding-1", "Finding 1"),
    "Source-task success": ("#finding-1", "Finding 1"),
    "Base competence": ("#finding-2", "Finding 2"),
    "Correction size": ("#finding-3", "Finding 3"),
    "Penalty or bounds": ("#finding-3", "Finding 3"),
    "Fixed offset": ("#finding-4", "Finding 4"),
    "Live vision": ("#finding-4", "Finding 4"),
    "Instruction": ("#finding-4", "Finding 4"),
    "Pretraining": ("#adaptation", "Adaptation"),
    "Expert routing": ("#more-answers", "Appendix answers"),
}
LINK_LABELS = (("paper", "Paper"), ("arxiv", "arXiv"), ("videos", "Videos"))


def value(data: dict, key: str, spec: str | None) -> str:
    v = lookup(data, key)
    if spec in ("word", "Word"):
        if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v < len(WORDS):
            die(f"{key}: cannot spell {v!r}")
        w = WORDS[v]
        return w.capitalize() if spec == "Word" else w
    if isinstance(v, str):
        return esc(v)
    if spec is None:
        if isinstance(v, int) and not isinstance(v, bool):
            return fmt(v, "int")
        die(f"{key}: a format (data-f) is required for the value {v!r}")
    return esc(fmt(v, spec))


def image_size(path: Path) -> tuple[float, float]:
    """Intrinsic width and height of a PNG, JPEG or SVG file (standard library only)."""
    raw = path.read_bytes()
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", raw[16:24])
    if raw[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(raw):
            if raw[i] != 0xFF:
                i += 1
                continue
            marker = raw[i + 1]
            if marker in (0xC0, 0xC1, 0xC2):
                h, w = struct.unpack(">HH", raw[i + 5:i + 9])
                return w, h
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            i += 2 + struct.unpack(">H", raw[i + 2:i + 4])[0]
        die(f"{path.name}: JPEG size not found")
    text = raw.decode("utf-8", "replace")
    m = re.search(r'<svg\b[^>]*\bviewBox="\s*[-\d.]+[\s,]+[-\d.]+[\s,]+([\d.]+)[\s,]+([\d.]+)', text)
    if m:
        return float(m.group(1)), float(m.group(2))
    die(f"{path.name}: unsupported image type")


# ------------------------------------------------------------ generated blocks

def gen_title(ctx, args):
    title = ctx["data"]["paper"]["title"]
    main, sep, sub = title.partition(": ")
    out = f"<h1>{esc(main)}</h1>"
    if sep:
        out += f'<p class="subtitle">{esc(sub)}</p>'
    return out


def gen_authors(ctx, args):
    site = ctx["site"]
    authors = [a for a in site.get("authors", []) if str(a.get("name", "")).strip()]
    if not authors:
        return ""
    items = []
    for a in authors:
        name = esc(a["name"].strip())
        if str(a.get("url", "")).strip():
            name = f'<a href="{esc(a["url"].strip())}">{name}</a>'
        marks = ",".join(str(x) for x in list(a.get("affiliations", [])) + list(a.get("marks", [])))
        sup = f"<sup>{esc(marks)}</sup>" if marks else ""
        items.append(f'<li role="listitem">{name}{sup}</li>')
    # Two balanced rows on wide screens (first row one longer when the count is odd); the rows
    # merge into one wrapping list on narrow screens.
    cut = (len(items) + 1) // 2
    rows = [items[:cut], items[cut:]] if len(items) > 5 else [items]
    out = ('<div class="authors" role="list" aria-label="Authors">'
           + "".join(f'<ul class="author-row" role="presentation">{"".join(r)}</ul>' for r in rows if r)
           + "</div>")
    affs = [x for x in site.get("affiliations", []) if str(x.get("name", "")).strip()]
    if affs:
        lis = "".join(f'<li><sup>{esc(x.get("id", ""))}</sup>{esc(x["name"].strip())}</li>'
                      for x in affs)
        out += f'<ul class="affiliations" aria-label="Affiliations">{lis}</ul>'
    logos = []
    for x in affs:
        rel = str(x.get("logo", "")).strip()
        if not rel:
            continue
        path = SITE / rel
        if not path.is_file():
            die(f"logo file missing: {rel}")
        w, h = image_size(path)
        alt = str(x.get("logo_alt", "")).strip() or x["name"].strip()
        logos.append(f'<li><img src="{esc(rel)}" alt="{esc(alt)}" height="{LOGO_HEIGHT}" '
                     f'width="{round(w * LOGO_HEIGHT / h)}"></li>')
    if logos:
        out += f'<ul class="logos" aria-label="Institutions">{"".join(logos)}</ul>'
    notes = [str(x).strip() for x in site.get("author_notes", []) if str(x).strip()]
    if notes:
        out += '<p class="author-note">' + "".join(f"<span>{esc(x)}</span>" for x in notes) + "</p>"
    return out


def gen_links(ctx, args):
    links = ctx["site"].get("links", {})
    items = []
    for key, label in LINK_LABELS:
        url = str(links.get(key, "")).strip()
        if url:
            cls = "btn btn-primary" if not items else "btn"
            items.append(f'<a class="{cls}" href="{esc(url)}">{label}</a>')
    if not items:
        return ""
    return f'<nav class="links" aria-label="Paper links">{"".join(items)}</nav>'


def clip_caption(clip: dict) -> str:
    where = "LIBERO held-out task" if clip["benchmark"] == "LIBERO" else f"{clip['benchmark']} task"
    note = f", {clip['note']}" if clip["note"] else ""
    return (f"<b>{esc(clip['task'])}</b> ({esc(where)}{esc(note)}). {esc(clip['shows'])}. "
            '<span class="chip">1× replay</span>')


def clip_figure(ctx, cid: str, panel_id: str = "") -> str:
    """One replay clip: video, panel labels that sit under their panels, caption."""
    clips, media = ctx["data"]["clips"], ctx["media"]["clips"]
    if cid not in clips or cid not in media:
        die(f"unknown clip {cid}")
    clip, m = clips[cid], media[cid]
    for rel in (m["video"], m["poster"], m["thumb"]):
        if not (SITE / rel).is_file():
            die(f"media file missing: {rel} (run build/build_media.py)")
    wide = len(clip["panels"]) >= WIDE_PANELS
    label = f"Replay: {clip['task']}. " + "; ".join(
        f"{p['policy']}: {p['result']}" for p in clip["panels"]) + "."
    lis = "".join(
        f'<li class="{"ok" if p["result"] == "success" else "no"}"><span class="pol">'
        f'{esc(p["policy"])}</span><span class="out">{esc(p["result"])}</span></li>'
        for p in clip["panels"])
    attrs = f' id="{panel_id}" data-panel' if panel_id else ""
    hint = '<p class="scroll-hint">Scroll sideways to see every panel.</p>' if wide else ""
    return (
        f'<figure class="clip{" wide" if wide else ""}" data-clip="{cid}"{attrs} '
        f'style="--ar:{m["width"] / m["height"]:.4f}">{hint}'
        f'<div class="clip-scroll"><div class="clip-inner">'
        f'<div class="clip-frame" style="aspect-ratio:{m["width"]}/{m["height"]}">'
        f'<video muted playsinline loop controls preload="none" data-lazy '
        f'width="{m["width"]}" height="{m["height"]}" poster="{esc(m["poster"])}" '
        f'aria-label="{esc(label)}">'
        f'<source src="{esc(m["video"])}" type="video/mp4"></video></div>'
        f'<ol class="panels" style="--n:{len(clip["panels"])}">{lis}</ol></div></div>'
        f"<figcaption>{clip_caption(clip)}</figcaption></figure>")


def gen_clip(ctx, args):
    if len(args) != 1:
        die("gen:clip takes one clip id")
    return clip_figure(ctx, args[0])


def gen_clips(ctx, args):
    """Several clips behind one switch: gen:clips GROUP ID "label" ID "label" ..."""
    if len(args) < 5 or len(args) % 2 == 0:
        die('gen:clips takes a group name and at least two pairs of clip id and "label"')
    group, pairs = args[0], list(zip(args[1::2], args[2::2]))
    tabs = "".join(f'<a href="#clip-{group}-{cid}" data-tab>{esc(label)}</a>' for cid, label in pairs)
    figures = "".join(clip_figure(ctx, cid, f"clip-{group}-{cid}") for cid, _ in pairs)
    return (f'<div class="clipgroup" data-tabs><div class="switch" data-tablist '
            f'aria-label="Choose a replay">{tabs}</div>{figures}</div>')


def gen_gallery(ctx, args):
    clips, media = ctx["data"]["clips"], ctx["media"]["clips"]
    picks = "".join(
        f'<a class="pick" href="#clip-g-{cid}" data-tab>'
        f'<img src="{esc(media[cid]["thumb"])}" alt="" loading="lazy" width="84" height="48">'
        f'<span><b>{esc(clip["shows"])}</b>{esc(clip["benchmark"])} · {esc(clip["task"])}'
        f"</span></a>" for cid, clip in clips.items())
    figures = "".join(clip_figure(ctx, cid, f"clip-g-{cid}") for cid in clips)
    return (f'<div class="gallery" data-tabs>{figures}<div class="picker" data-tablist '
            f'aria-label="Choose a replay">{picks}</div></div>')


def gen_matters(ctx, args):
    rows = []
    for row in ctx["data"]["what_matters"].values():
        if row["factor"] not in MATTERS_LINKS:
            die(f"summary table: no page section mapped for factor {row['factor']!r}")
        href, label = MATTERS_LINKS[row["factor"]]
        rows.append(f'<li><b>{esc(row["factor"])}</b><span>{esc(row["finding"])}</span>'
                    f'<a href="{href}">{esc(label)}</a></li>')
    return f'<ul class="matters-list">{"".join(rows)}</ul>'


def gen_guide(ctx, args):
    out = []
    for qa in ctx["data"]["guide"].values():
        out.append(f"<dt>{esc(qa['question'])}</dt><dd>{esc(qa['answer'])}</dd>")
    return "<dl>" + "".join(out) + "</dl>"


def gen_recipekey(ctx, args):
    return build_charts.recipe_key()


def gen_defs(ctx, args):
    return build_charts.defs_block()


def gen_bibtex(ctx, args):
    bib = ctx["site"].get("bibtex", {})
    key = str(bib.get("key", "")).strip() or "sharingcorrections"
    year = str(bib.get("year", "")).strip()
    authors = str(bib.get("authors", "")).strip()
    if not authors:
        names = [a["name"].strip() for a in ctx["site"].get("authors", [])
                 if str(a.get("name", "")).strip()]
        authors = " and ".join(names)
    lines = [f"@misc{{{key},", f"  title  = {{{ctx['data']['paper']['title']}}},",
             f"  author = {{{authors}}},"]
    if year:
        lines.append(f"  year   = {{{year}}}")
    else:
        lines[-1] = lines[-1].rstrip(",")
    lines.append("}")
    return esc("\n".join(lines))


def gen_sysfig(ctx, args):
    fig = ctx["media"]["figures"]["resop_system"]
    if not (SITE / fig["file"]).is_file():
        die(f"figure missing: {fig['file']} (run build/build_media.py)")
    return (f'<img src="{esc(fig["file"])}" width="{fig["width"]}" height="{fig["height"]}" '
            'loading="lazy" alt="Diagram of the training system. Collectors run the simulators: '
            'a frozen base proposes an action chunk, the shared editor turns context and proposal '
            'into the edited chunk that is executed, and task-labelled transitions go to a '
            'task-indexed replay. The learner draws task-balanced batches, trains one critic '
            'ensemble per task and a shared actor, and publishes the actor and representation '
            'back to the collectors.">')


GENERATORS = {"title": gen_title, "authors": gen_authors, "links": gen_links, "clip": gen_clip,
              "clips": gen_clips, "gallery": gen_gallery, "matters": gen_matters,
              "guide": gen_guide, "recipekey": gen_recipekey, "defs": gen_defs,
              "bibtex": gen_bibtex, "sysfig": gen_sysfig}


# ------------------------------------------------------------------- charts

def chart_block(c: dict) -> str:
    top = ""
    if c["legend"] or c["toggle"]:
        toggle = ""
        if c["toggle"]:
            buttons = "".join(
                f'<button type="button" data-recipe="{r}" aria-pressed="{"true" if r == "all" else "false"}">'
                f'{"All" if r == "all" else r}</button>' for r in ("all", "L1", "L2", "L3"))
            toggle = f'<div class="rtoggle" role="group" aria-label="Highlight a recipe">{buttons}</div>'
        top = f'<div class="chart-top">{c["legend"]}{toggle}</div>'
    svg = build_charts.svg_open(c, inline=True) + c["body"] + "</svg>"
    table = (f'<details class="values"><summary>Values as a table</summary>'
             f'<div class="table-wrap">{c["table"]}</div></details>') if c["table"] else ""
    return top + svg + table


def mini_block(c: dict) -> str:
    return build_charts.svg_open(c, inline=True) + c["body"] + "</svg>"


# -------------------------------------------------------------------- stamp

SLOT = re.compile(r'<span data-v="([^"]+)"(?: data-f="([^"]+)")?>[^<]*</span>')
CHART = re.compile(r"<!--chart:([\w-]+)-->.*?<!--/chart-->", re.S)
MINI = re.compile(r"<!--mini:([\w-]+)-->.*?<!--/mini-->", re.S)
GEN = re.compile(r'<!--gen:([\w-]+)((?: (?:[\w.-]+|"[^"<>]*"))*)-->.*?<!--/gen-->', re.S)
OG_TITLE = re.compile(r'<meta property="og:title" content="[^"]*">')


def stamp(html: str, ctx: dict) -> tuple[str, dict]:
    data, charts = ctx["data"], ctx["charts"]
    used = {"values": 0, "charts": set(), "gens": 0}

    def do_gen(m):
        name, args = m.group(1), shlex.split(m.group(2))
        if name not in GENERATORS:
            die(f"unknown generated block gen:{name}")
        used["gens"] += 1
        return f"<!--gen:{name}{m.group(2)}-->" + GENERATORS[name](ctx, args) + "<!--/gen-->"

    def do_chart(m):
        name = m.group(1)
        if name not in charts or name.startswith("mini_"):
            die(f"unknown chart {name}")
        used["charts"].add(name)
        return f"<!--chart:{name}-->" + chart_block(charts[name]) + "<!--/chart-->"

    def do_mini(m):
        name = m.group(1)
        if name not in charts or not name.startswith("mini_"):
            die(f"unknown small chart {name}")
        used["charts"].add(name)
        return f"<!--mini:{name}-->" + mini_block(charts[name]) + "<!--/mini-->"

    def do_slot(m):
        used["values"] += 1
        key, spec = m.group(1), m.group(2)
        f = f' data-f="{spec}"' if spec else ""
        return f'<span data-v="{key}"{f}>{value(data, key, spec)}</span>'

    html = GEN.sub(do_gen, html)
    html = CHART.sub(do_chart, html)
    html = MINI.sub(do_mini, html)
    # Value slots outside the generated blocks and charts only.
    protected = re.compile(r"(<!--(?:gen|chart|mini):.*?<!--/(?:gen|chart|mini)-->)", re.S)
    parts = protected.split(html)
    for i in range(0, len(parts), 2):
        parts[i] = SLOT.sub(do_slot, parts[i])
        if parts[i].count("data-v=") != len(SLOT.findall(parts[i])):
            bad = re.search(r'.{0,60}data-v="[^"]*"[^>]*>(?![^<]*</span>).{0,40}', parts[i], re.S)
            die("malformed value slot near: " + (bad.group(0) if bad else "?").replace("\n", " "))
    html = "".join(parts)
    for marker, rx in (("<!--gen:", GEN), ("<!--chart:", CHART), ("<!--mini:", MINI)):
        if html.count(marker) != len(rx.findall(html)):
            die(f"malformed or unclosed {marker} block in index.html")
    title = esc(data["paper"]["title"])
    if len(re.findall(r"<title>[^<]*</title>", html)) != 1:
        die("index.html needs exactly one <title> element")
    html = re.sub(r"<title>[^<]*</title>", lambda m: f"<title>{title}</title>", html)
    if len(OG_TITLE.findall(html)) != 1:
        die('index.html needs exactly one <meta property="og:title" content="...">')
    html = OG_TITLE.sub(lambda m: f'<meta property="og:title" content="{title}">', html)
    return html, used


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true",
                    help="do not write; fail if index.html would change")
    args = ap.parse_args()
    data = load_json(DATA / "site_data.json")
    ctx = {"data": data, "media": load_json(DATA / "media.json"),
           "site": load_json(DATA / "site.json"), "charts": build_charts.render_all(data)}
    if not INDEX.is_file():
        die("index.html not found")
    html = INDEX.read_text(encoding="utf-8")
    out, used = stamp(html, ctx)
    again, _ = stamp(out, ctx)
    if again != out:
        die("stamping is not stable: a second pass changes the page")
    unused = sorted(set(ctx["charts"]) - used["charts"])
    if unused:
        print("stamp: charts not placed on the page: " + ", ".join(unused), file=sys.stderr)
    if args.check:
        if out != html:
            die("index.html is not up to date with the data; run build/stamp.py")
        print(f"stamp: index.html is up to date ({used['values']} values, "
              f"{len(used['charts'])} charts, {used['gens']} generated blocks)")
        return
    if out != html:
        INDEX.write_text(out, encoding="utf-8")
    print(f"stamp: {used['values']} values, {len(used['charts'])} charts, "
          f"{used['gens']} generated blocks" + ("" if out != html else " (no change)"))


if __name__ == "__main__":
    main()
