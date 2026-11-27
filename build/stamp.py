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
  <!--gen:NAME ARGS-->...<!--/gen-->    a generated block; ARGS are words or
        "quoted text". Blocks: title, authors, links, teaser, loop, clip ID,
        clips GROUP ID "label" ID "label" ..., gallery, matters, guide,
        recipekey, bibtex, sysfig, defs

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
LOGO_HEIGHT = 30          # px; default height for institution wordmarks
WIDE_PANELS = 3           # clips with at least this many panels scroll sideways on phones

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

LINK_META = (
    ("paper", "Paper",
     '<svg class="ico" viewBox="0 0 16 16" width="15" height="15" aria-hidden="true" focusable="false">'
     '<path d="M4 1.75h5.2L12.75 5.3v8.95a.75.75 0 0 1-.75.75H4a.75.75 0 0 1-.75-.75V2.5a.75.75 0 0 1 .75-.75Z" fill="none" stroke="currentColor" stroke-width="1.35" stroke-linejoin="round"/>'
     '<path d="M9 1.9v3.6h3.6M5.5 8.5h5M5.5 11.2h3.5" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>'),
    ("arxiv", "arXiv",
     '<svg class="ico" viewBox="0 0 16 16" width="15" height="15" aria-hidden="true" focusable="false">'
     '<path d="M3 12.5 8 3.2l5 9.3M5 9.2h6" fill="none" stroke="currentColor" stroke-width="1.35" stroke-linecap="round" stroke-linejoin="round"/></svg>'),
    ("videos", "Replays",
     '<svg class="ico" viewBox="0 0 16 16" width="15" height="15" aria-hidden="true" focusable="false">'
     '<rect x="1.75" y="3.25" width="12.5" height="9.5" rx="2" fill="none" stroke="currentColor" stroke-width="1.35"/>'
     '<polygon points="6.6,5.8 10.6,8 6.6,10.2" fill="currentColor"/></svg>'),
    ("bibtex", "BibTeX",
     '<svg class="ico" viewBox="0 0 16 16" width="15" height="15" aria-hidden="true" focusable="false">'
     '<path d="M5.5 4.2 2.2 8l3.3 3.8M10.5 4.2 13.8 8l-3.3 3.8M9 3.2 7 12.8" fill="none" stroke="currentColor" stroke-width="1.35" stroke-linecap="round" stroke-linejoin="round"/></svg>'),
)


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
        lh = int(x.get("logo_height") or LOGO_HEIGHT)
        style = f' style="--lh:{lh}px"' if lh != LOGO_HEIGHT else ""
        logos.append(f'<li><img src="{esc(rel)}" alt="{esc(alt)}" height="{lh}" '
                     f'width="{round(w * lh / h)}"{style}></li>')
    if logos:
        out += f'<ul class="logos" aria-label="Institutions">{"".join(logos)}</ul>'
    notes = [str(x).strip() for x in site.get("author_notes", []) if str(x).strip()]
    if notes:
        out += '<p class="author-note">' + "".join(f"<span>{esc(x)}</span>" for x in notes) + "</p>"
    return out


def gen_links(ctx, args):
    links = ctx["site"].get("links", {})
    items = []
    has_primary = False
    for key, label, icon in LINK_META:
        url = str(links.get(key, "")).strip()
        if not url:
            continue
        if url.lower() == "soon":
            items.append(
                f'<span class="btn btn-soon" aria-disabled="true" title="{esc(label)} coming soon">'
                f'{icon}<span>{label}</span><small>soon</small></span>'
            )
            continue
        cls = "btn btn-primary" if not has_primary else "btn"
        has_primary = True
        items.append(f'<a class="{cls}" href="{esc(url)}">{icon}<span>{label}</span></a>')
    if not items:
        return ""
    return f'<nav class="links" aria-label="Paper links">{"".join(items)}</nav>'


def gen_teaser(ctx, args):
    fig = ctx["media"]["figures"]["teaser"]
    if not (SITE / fig["file"]).is_file():
        die(f"figure missing: {fig['file']} (run build/build_media.py)")
    return (f'<img src="{esc(fig["file"])}" width="{fig["width"]}" height="{fig["height"]}" '
            'fetchpriority="high" decoding="async" '
            'alt="Overview of Sharing Corrections across Tasks. (a) One shared editor trained on '
            '112 source tasks raises mean success on 18 editor-held-out tasks from 23.3% to '
            '50.0–57.6% across three recipes without updates on those tasks. (b) Rescue grows and '
            'harm falls as source tasks increase from 2 to 16 to 112. (c, d) Broad source '
            'experience lowers nearest-source visual distance and ten source directions capture '
            '85.3% of the bounded editor’s held-out correction variance. (e) Example rollout where '
            'the base stalls and the editor completes the task. (f) Soft-penalty recipes harm '
            'fewer episodes than output bounds, and halving the bounded correction lowers harm.">')


def clip_caption(clip: dict) -> str:
    where = "LIBERO held-out task" if clip["benchmark"] == "LIBERO" else f"{clip['benchmark']} task"
    note = f", {clip['note']}" if clip["note"] else ""
    return (f"<b>{esc(clip['task'])}</b> ({esc(where)}{esc(note)}). {esc(clip['shows'])}. "
            '<span class="chip">1× replay</span>')


def clip_figure(ctx, cid: str, panel_id: str = "") -> str:
    """One replay clip: video (with baked panel headers) and concise caption."""
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
    attrs = f' id="{panel_id}" data-panel' if panel_id else ""
    hint = '<p class="scroll-hint">Scroll sideways to view all panels.</p>' if wide else ""
    return (
        f'<figure class="clip{" wide" if wide else ""}" data-clip="{cid}"{attrs} '
        f'style="--ar:{m["width"] / m["height"]:.4f}">{hint}'
        f'<div class="clip-scroll"><div class="clip-inner">'
        f'<div class="clip-frame" style="aspect-ratio:{m["width"]}/{m["height"]}">'
        f'<video muted playsinline loop controls preload="none" data-lazy '
        f'width="{m["width"]}" height="{m["height"]}" poster="{esc(m["poster"])}" '
        f'aria-label="{esc(label)}">'
        f'<source src="{esc(m["video"])}" type="video/mp4"></video></div>'
        f'</div></div>'
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
        rows.append(
            f'<tr><th scope="row">{esc(row["factor"])}</th>'
            f'<td>{esc(row["finding"])}</td>'
            f'<td class="m-ref"><a href="{href}">{esc(label)}</a></td></tr>')
    return (
        '<div class="table-wrap"><table class="matters-table">'
        '<thead><tr><th scope="col">Factor</th><th scope="col">Finding</th>'
        '<th scope="col" class="m-ref">Evidence</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div>')


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
        lines.append(f"  year   = {{{year}}},")
    arxiv_url = str(ctx["site"].get("links", {}).get("arxiv", "")).strip()
    m_arxiv = re.search(r"(\d{4}\.\d{4,5}(?:v\d+)?)", arxiv_url)
    if m_arxiv:
        lines.append(f"  eprint = {{{m_arxiv.group(1)}}},")
        lines.append("  archivePrefix = {arXiv},")
        lines.append("  primaryClass  = {cs.RO},")
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


def gen_loop(ctx, args):
    """Structured four-step closed control loop with live-context bypass and return arc."""
    n_tasks = fmt(lookup(ctx["data"], "setup.n_tasks"), "int")
    ico_obs = (
        '<svg class="node-ico" viewBox="0 0 18 18" width="16" height="16" aria-hidden="true" focusable="false">'
        '<path d="M2 6.2a1.5 1.5 0 0 1 1.5-1.5h2l1.1-1.6h4.8l1.1 1.6h2A1.5 1.5 0 0 1 16 6.2v7.1a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 2 13.3Z" '
        'fill="none" stroke="currentColor" stroke-width="1.35" stroke-linejoin="round"/>'
        '<circle cx="9" cy="9.6" r="2.5" fill="none" stroke="currentColor" stroke-width="1.35"/></svg>'
    )
    ico_frozen = (
        '<svg class="node-ico" viewBox="0 0 18 18" width="16" height="16" aria-hidden="true" focusable="false">'
        '<path d="M9 2v14M2.9 5.5l12.2 7M15.1 5.5l-12.2 7M7.1 3.4 9 5.1l1.9-1.7M7.1 14.6 9 12.9l1.9 1.7" '
        'fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>'
    )
    ico_editor = (
        '<svg class="node-ico" viewBox="0 0 18 18" width="16" height="16" aria-hidden="true" focusable="false">'
        '<path d="M3 5h12M3 9h12M3 13h12" fill="none" stroke="currentColor" stroke-width="1.35" stroke-linecap="round"/>'
        '<circle cx="6.5" cy="5" r="1.6" fill="#f3f7fb" stroke="currentColor" stroke-width="1.35"/>'
        '<circle cx="11.8" cy="9" r="1.6" fill="#f3f7fb" stroke="currentColor" stroke-width="1.35"/>'
        '<circle cx="7.5" cy="13" r="1.6" fill="#f3f7fb" stroke="currentColor" stroke-width="1.35"/></svg>'
    )
    ico_robot = (
        '<svg class="node-ico" viewBox="0 0 18 18" width="16" height="16" aria-hidden="true" focusable="false">'
        '<path d="M3 14.8h7.5M5.8 14.8v-3.4l3.8-6h3.8v2.4M11.6 7.8h3.6M11.6 7.8v3M15.2 7.8v3" '
        'fill="none" stroke="currentColor" stroke-width="1.35" stroke-linecap="round" stroke-linejoin="round"/>'
        '<circle cx="5.8" cy="11.4" r="1.3" fill="currentColor"/>'
        '<circle cx="9.6" cy="5.4" r="1.3" fill="currentColor"/></svg>'
    )

    def arrow(label: str, accent: bool = False) -> str:
        cls = "loop-conn is-accent" if accent else "loop-conn"
        return (
            f'<div class="{cls}" aria-hidden="true">'
            f'<span class="conn-label">{label}</span>'
            '<svg class="conn-h" viewBox="0 0 64 14" width="64" height="14" focusable="false">'
            '<line x1="2" y1="7" x2="55" y2="7" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>'
            '<polygon points="54,3.5 62,7 54,10.5" fill="currentColor"/></svg>'
            '<svg class="conn-v" viewBox="0 0 14 26" width="14" height="26" focusable="false">'
            '<line x1="7" y1="2" x2="7" y2="18" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>'
            '<polygon points="3.5,17 7,24.5 10.5,17" fill="currentColor"/></svg>'
            '</div>'
        )

    # Grid proportions: 196fr 76fr 196fr 76fr 196fr 76fr 196fr (sum = 1012).
    # Exact column centres in viewBox 0..1012: 98, 370, 642, 914.
    top_arc = (
        '<svg class="loop-arc loop-arc-top" viewBox="0 0 1012 42" width="1012" height="42" '
        'aria-hidden="true" focusable="false">'
        '<path d="M98 41 V22 Q98 14 106 14 H634 Q642 14 642 22 V35" '
        'fill="none" stroke="#15466e" stroke-opacity="0.52" stroke-width="1.35" stroke-dasharray="4 3"/>'
        '<polygon points="638.5,33 642,41 645.5,33" fill="#15466e" fill-opacity="0.72"/>'
        '<rect x="296" y="4" width="148" height="20" rx="10" fill="#ffffff"/>'
        '<text x="370" y="17.5" text-anchor="middle" class="arc-lbl arc-accent">live obs (z, q)</text>'
        '</svg>'
    )
    bot_arc = (
        '<svg class="loop-arc loop-arc-bot" viewBox="0 0 1012 38" width="1012" height="38" '
        'aria-hidden="true" focusable="false">'
        '<path d="M914 1 V18 Q914 26 906 26 H106 Q98 26 98 18 V7" '
        'fill="none" stroke="#94a3b8" stroke-width="1.35" stroke-dasharray="4 3"/>'
        '<polygon points="94.5,9 98,1 101.5,9" fill="#94a3b8"/>'
        '<rect x="389.5" y="16" width="233" height="20" rx="10" fill="#ffffff"/>'
        '<text x="506" y="29.5" text-anchor="middle" class="arc-lbl">closed loop · every five actions</text>'
        '</svg>'
    )

    nodes = (
        '<div class="loop-grid" role="list" aria-label="Control loop">'
        '<div class="loop-node node-obs" role="listitem">'
        f'<div class="node-head"><span class="node-num">01</span>{ico_obs}</div>'
        '<b>Observation</b>'
        '<p>Camera images, robot state, and task instruction.</p>'
        '</div>'
        + arrow("o, q, ℓ")
        + '<div class="loop-node node-base" role="listitem">'
        f'<div class="node-head"><span class="node-num">02</span><span class="node-state">Frozen</span>{ico_frozen}</div>'
        '<b>Frozen base policy</b>'
        f'<p>Fine-tuned on all {n_tasks} LIBERO tasks and kept fixed. Proposes action chunk <i>B</i>.</p>'
        '</div>'
        + arrow("proposal B")
        + '<div class="loop-node node-editor" role="listitem">'
        f'<div class="node-head"><span class="node-num">03</span><span class="node-state">Learned</span>{ico_editor}</div>'
        '<b>Shared editor</b>'
        '<p>One small policy across tasks. Reads live context and <i>B</i>; outputs edited chunk <i>A</i>.</p>'
        '</div>'
        + arrow("chunk A", accent=True)
        + '<div class="loop-node node-robot" role="listitem">'
        f'<div class="node-head"><span class="node-num">04</span>{ico_robot}</div>'
        '<b>Robot execution</b>'
        '<p>Executes five physical actions, then repeats from a fresh observation.</p>'
        '</div>'
        '</div>'
    )
    mobile_note = '<p class="loop-mobile-note">Closed loop: the shared editor receives live observation directly alongside <i>B</i>, and the cycle repeats every five actions.</p>'
    return f'<div class="loop-diagram">{top_arc}{nodes}{bot_arc}{mobile_note}</div>'


def gen_spark(ctx, args):
    """Data-driven miniature SVG sparklines for the four key-finding tiles."""
    if len(args) != 1 or args[0] not in ("f1", "f2", "f3", "f4"):
        die(f"gen:spark expects one of f1..f4, got {args!r}")
    which = args[0]
    d = ctx["data"]
    w, h = 136, 52

    def pt(x, y):
        return f"{x:.1f},{y:.1f}"

    parts: list[str] = []
    if which == "f1":
        # Crossing rescue (teal, rising) and harm (rust, falling) across 2, 16, 112 sources.
        xs = (16.0, 68.0, 120.0)
        keys = ("n2", "n16", "n112")
        rs = [d["breadth"][k]["r"] for k in keys]
        hs = [d["breadth"][k]["h"] for k in keys]
        lbls = [str(d["breadth"][k]["sources"]) for k in keys]
        ymax = max(max(rs), max(hs), 40.0)
        sy = lambda v: 36.0 - (v / ymax) * 29.0
        parts.append('<line x1="6" y1="36" x2="130" y2="36" fill="none" class="sp-base"/>')
        rpts = " ".join(pt(x, sy(v)) for x, v in zip(xs, rs))
        hpts = " ".join(pt(x, sy(v)) for x, v in zip(xs, hs))
        area = f"{xs[0]:.1f},36.0 {rpts} {xs[-1]:.1f},36.0"
        parts.append(f'<polygon points="{area}" class="sp-area sp-rescue"/>')
        parts.append(f'<polyline points="{hpts}" fill="none" class="sp-ln sp-harm"/>')
        parts.append(f'<polyline points="{rpts}" fill="none" class="sp-ln sp-rescue"/>')
        for x, v in zip(xs, hs):
            parts.append(f'<circle cx="{x:.1f}" cy="{sy(v):.1f}" r="2.6" class="sp-dot sp-harm"/>')
        for x, v in zip(xs, rs):
            parts.append(f'<circle cx="{x:.1f}" cy="{sy(v):.1f}" r="2.9" class="sp-dot sp-rescue"/>')
        for x, lbl in zip(xs, lbls):
            parts.append(f'<text x="{x:.1f}" y="49" text-anchor="middle" class="sp-lbl">{lbl}</text>')
    elif which == "f2":
        # Grouped gain bars across base-SR bins (low, mid, high) for L1, L2, L3.
        groups = ("low", "mid", "high")
        recs = ("L1", "L2", "L3")
        vals = [d["base_groups"][g][r]["gain"] for g in groups for r in recs]
        vmax = max(max(vals), 45.0)
        vmin = min(min(vals), -6.0)
        sy = lambda v: 6.0 + (vmax - v) / (vmax - vmin) * 30.0
        y0 = sy(0.0)
        parts.append(f'<line x1="6" y1="{y0:.1f}" x2="130" y2="{y0:.1f}" fill="none" class="sp-base"/>')
        gx0 = (12.0, 54.0, 96.0)
        bw, gap = 8.0, 2.5
        for gx, g in zip(gx0, groups):
            for i, r in enumerate(recs):
                v = d["base_groups"][g][r]["gain"]
                yv = sy(v)
                top, bh = (yv, y0 - yv) if v >= 0 else (y0, yv - y0)
                parts.append(
                    f'<rect x="{gx + i * (bw + gap):.1f}" y="{top:.1f}" width="{bw:.1f}" '
                    f'height="{max(bh, 1.6):.1f}" rx="1.3" class="b-{r}"/>'
                )
            cx = gx + bw + gap + bw / 2.0
            parts.append(f'<text x="{cx:.1f}" y="49" text-anchor="middle" class="sp-lbl">{g}</text>')
    elif which == "f3":
        # Harm sloping down across inference scales 1.00, 0.75, 0.50, 0.25 for L1, L2, L3.
        xs = (14.0, 50.0, 86.0, 122.0)
        scales = ("a100", "a075", "a050", "a025")
        recs = ("L3", "L1", "L2")
        all_h = [d["dose"][r][s]["mean"]["h"] for r in recs for s in scales]
        ymax = max(max(all_h), 12.0)
        sy = lambda v: 36.0 - (v / ymax) * 29.0
        parts.append('<line x1="6" y1="36" x2="130" y2="36" fill="none" class="sp-base"/>')
        parts.append(f'<line x1="{xs[2]:.1f}" y1="6" x2="{xs[2]:.1f}" y2="36" fill="none" class="sp-guide"/>')
        for r in recs:
            ys = [sy(d["dose"][r][s]["mean"]["h"]) for s in scales]
            pts = " ".join(pt(x, y) for x, y in zip(xs, ys))
            parts.append(f'<polyline points="{pts}" fill="none" class="sp-ln sp-{r}"/>')
            for idx in (0, 2):
                parts.append(f'<circle cx="{xs[idx]:.1f}" cy="{ys[idx]:.1f}" r="2.6" class="sp-dot sp-{r}"/>')
        parts.append(f'<text x="{xs[0]:.1f}" y="49" text-anchor="middle" class="sp-lbl">1×</text>')
        parts.append(f'<text x="{xs[2]:.1f}" y="49" text-anchor="middle" class="sp-lbl sp-lbl-hi">0.5×</text>')
    elif which == "f4":
        # Dumbbell contrast: own source-mean (open) vs. live editor (filled) for L1, L2, L3.
        recs = ("L1", "L2", "L3")
        ys = (8.0, 19.0, 30.0)
        lo, hi = 35.0, 62.0
        sx = lambda v: 10.0 + (v - lo) / (hi - lo) * 116.0
        for r, y in zip(recs, ys):
            xm = sx(d["controls"][r]["mean"]["mean"])
            xl = sx(d["controls"][r]["live"]["mean"])
            parts.append(f'<line x1="8" y1="{y:.1f}" x2="128" y2="{y:.1f}" fill="none" class="sp-track"/>')
            parts.append(f'<line x1="{xm:.1f}" y1="{y:.1f}" x2="{xl:.1f}" y2="{y:.1f}" fill="none" class="sp-ln sp-{r}"/>')
            parts.append(f'<circle cx="{xm:.1f}" cy="{y:.1f}" r="3.1" class="sp-open sp-{r}"/>')
            parts.append(f'<circle cx="{xl:.1f}" cy="{y:.1f}" r="3.3" class="sp-dot sp-{r}"/>')
        parts.append('<circle cx="24" cy="46.2" r="2.3" class="sp-open sp-L1"/>')
        parts.append('<text x="30" y="49" class="sp-lbl">mean</text>')
        parts.append('<circle cx="88" cy="46.2" r="2.4" class="sp-dot sp-L1"/>')
        parts.append('<text x="94" y="49" class="sp-lbl">live</text>')

    return (
        f'<svg class="spark" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
        f'aria-hidden="true" focusable="false">{"".join(parts)}</svg>'
    )


def gen_syscosts(ctx, args):
    """What a training run costs at three scales, for #system.

    One row per scale, largest first: the reader sees the same system go from
    112 tasks on a four-GPU node to one task on one consumer GPU. Rates, the
    added seed and the per-GPU split of the adaptation runs stay in the paper.
    """
    d = ctx["data"]
    s = d["system"]
    n_src = d["setup"]["n_source"]
    u112 = d["setup"]["updates_112_k"]
    u16 = d["setup"]["updates_16_k"]
    lo, hi = s["adapt_6000"]["lo"], s["adapt_4090"]["hi"]
    rows = [
        (f"One editor for {n_src} tasks",
         f"shared actor, {s['critic_heads']:,} per-task critic heads",
         "4× A100", f"{u112:.2f}k",
         f"{s['full']['gpu_hours']:.2f}", f"{s['per_task_gpu_hours']:.2f} per task"),
        ("One editor for 16 tasks",
         f"{s['s16']['n_runs']} runs",
         "2× A100, RTX 6000D or RTX 4090", f"{u16}k",
         f"{s['s16']['gpuh_lo']:.2f}–{s['s16']['gpuh_hi']:.2f}", ""),
        ("Adaptation to one task",
         f"{s['adapt_runs']} runs, from the {n_src}-task editor or from scratch",
         "1× RTX 4090 or RTX 6000D", "25k",
         f"{lo:.2f}–{hi:.2f}", f"{s['peak_gib']:.1f} GiB peak memory"),
    ]
    trs = "".join(
        f'<tr><th scope="row">{esc(w)}<span class="sub">{esc(sub)}</span></th>'
        f'<td>{esc(hw)}</td><td class="num">{esc(u)}</td>'
        f'<td class="num"><b>{esc(gh)}</b>'
        + (f'<span class="sub">{esc(note)}</span>' if note else '')
        + '</td></tr>'
        for w, sub, hw, u, gh, note in rows
    )
    return (
        '<div class="syscost-wrap"><table class="syscost-table">'
        '<caption>Recorded cost of a training run at three scales (allocated GPUs × process time).</caption>'
        '<thead><tr><th scope="col">What is trained</th><th scope="col">Hardware</th>'
        '<th scope="col" class="num">Actor updates</th><th scope="col" class="num">GPU-hours</th></tr></thead>'
        f'<tbody>{trs}</tbody></table></div>'
    )


GENERATORS = {"title": gen_title, "authors": gen_authors, "links": gen_links, "teaser": gen_teaser,
              "loop": gen_loop, "clip": gen_clip, "clips": gen_clips, "gallery": gen_gallery,
              "matters": gen_matters, "guide": gen_guide, "recipekey": gen_recipekey,
              "defs": gen_defs, "bibtex": gen_bibtex, "sysfig": gen_sysfig, "spark": gen_spark,
              "syscosts": gen_syscosts}


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


# -------------------------------------------------------------------- stamp

SLOT = re.compile(r'<span data-v="([^"]+)"(?: data-f="([^"]+)")?>[^<]*</span>')
CHART = re.compile(r"<!--chart:([\w-]+)-->.*?<!--/chart-->", re.S)
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
        if name not in charts:
            die(f"unknown chart {name}")
        used["charts"].add(name)
        return f"<!--chart:{name}-->" + chart_block(charts[name]) + "<!--/chart-->"

    def do_slot(m):
        used["values"] += 1
        key, spec = m.group(1), m.group(2)
        f = f' data-f="{spec}"' if spec else ""
        return f'<span data-v="{key}"{f}>{value(data, key, spec)}</span>'

    html = GEN.sub(do_gen, html)
    html = CHART.sub(do_chart, html)
    protected = re.compile(r"(<!--(?:gen|chart):.*?<!--/(?:gen|chart)-->)", re.S)
    parts = protected.split(html)
    for i in range(0, len(parts), 2):
        parts[i] = SLOT.sub(do_slot, parts[i])
        if parts[i].count("data-v=") != len(SLOT.findall(parts[i])):
            bad = re.search(r'.{0,60}data-v="[^"]*"[^>]*>(?![^<]*</span>).{0,40}', parts[i], re.S)
            die("malformed value slot near: " + (bad.group(0) if bad else "?").replace("\n", " "))
    html = "".join(parts)
    for marker, rx in (("<!--gen:", GEN), ("<!--chart:", CHART)):
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
