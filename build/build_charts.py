#!/usr/bin/env python3
"""Draw every chart of the page as SVG from data/site_data.json.

    python build/build_charts.py      writes assets/charts/<name>.svg

Each chart function returns the SVG body, an HTML legend and an HTML table with
the same values. build/stamp.py imports render_all() and places the three parts
inline in index.html; the files written here are the same drawings as
stand-alone SVG.

No number is typed in this file: every label, tooltip and table cell is read
from the data through V(), which stops the build when a key is missing.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ASSETS, DATA, MINUS, NDASH, die, esc, fmt, load_json, lookup  # noqa: E402

RECIPES = ("L1", "L2", "L3")
SHAPE = {"L1": "circle", "L2": "triangle", "L3": "square"}
W = 480          # standard two-up chart width in SVG units
WW = 640         # wide single-column chart width in SVG units
AW = 320         # compact three-up adaptation chart width

DATA_CACHE: dict = {}


def V(key: str):
    return lookup(DATA_CACHE, key)


def F(key: str, spec: str = "1") -> str:
    return fmt(V(key), spec)


def NS() -> str:
    return F("setup.n_source", "int")


def NH() -> str:
    return F("setup.n_heldout", "int")


def N16() -> str:
    return F("breadth.n16.sources", "int")


def N96() -> str:
    return F("unseen96.groups.all.n_tasks", "int")


def CI() -> str:
    return F("setup.ci_level", "int") + "%"


# ------------------------------------------------------------- SVG helpers

def n(x: float) -> str:
    """Coordinate with at most two decimals."""
    s = f"{x:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def text(x, y, s, cls="t", anchor="start", extra="") -> str:
    a = "" if anchor == "start" else f' text-anchor="{anchor}"'
    return f'<text x="{n(x)}" y="{n(y)}" class="{cls}"{a}{extra}>{esc(s)}</text>'


def line(x1, y1, x2, y2, cls="grid") -> str:
    return f'<line x1="{n(x1)}" y1="{n(y1)}" x2="{n(x2)}" y2="{n(y2)}" class="{cls}"/>'


def rect(x, y, w, h, cls, rx=0) -> str:
    r = f' rx="{n(rx)}"' if rx else ""
    return f'<rect x="{n(x)}" y="{n(y)}" width="{n(max(w, 0))}" height="{n(h)}"{r} class="{cls}"/>'


def hbar(x0, x1, y, h, cls, r=3) -> str:
    """Horizontal bar from baseline x0 to x1, rounded at the data end only."""
    if abs(x1 - x0) < 0.01:
        return ""
    r = min(r, abs(x1 - x0), h / 2)
    s = 1 if x1 > x0 else -1
    d = (f"M{n(x0)} {n(y)}H{n(x1 - s * r)}Q{n(x1)} {n(y)} {n(x1)} {n(y + r)}"
         f"V{n(y + h - r)}Q{n(x1)} {n(y + h)} {n(x1 - s * r)} {n(y + h)}H{n(x0)}Z")
    return f'<path d="{d}" class="{cls}"/>'


def vbar(x, w, y0, y1, cls, r=3) -> str:
    """Column from baseline y0 to y1, rounded at the data end only."""
    if abs(y1 - y0) < 0.01:
        return ""
    r = min(r, abs(y1 - y0), w / 2)
    s = 1 if y1 > y0 else -1
    d = (f"M{n(x)} {n(y0)}V{n(y1 - s * r)}Q{n(x)} {n(y1)} {n(x + r)} {n(y1)}"
         f"H{n(x + w - r)}Q{n(x + w)} {n(y1)} {n(x + w)} {n(y1 - s * r)}V{n(y0)}Z")
    return f'<path d="{d}" class="{cls}"/>'


def shape(kind, x, y, cls, size=4.6) -> str:
    """Marker with a white halo. kind: circle, triangle, square, diamond."""
    if kind == "circle":
        return f'<circle cx="{n(x)}" cy="{n(y)}" r="{n(size)}" class="pt {cls}"/>'
    if kind == "square":
        s = size * 0.9
        return (f'<rect x="{n(x - s)}" y="{n(y - s)}" width="{n(2 * s)}" height="{n(2 * s)}" '
                f'rx="1" class="pt {cls}"/>')
    if kind == "triangle":
        s = size * 1.25
        pts = f"{n(x)},{n(y - s)} {n(x + s)},{n(y + s * 0.8)} {n(x - s)},{n(y + s * 0.8)}"
        return f'<polygon points="{pts}" class="pt {cls}"/>'
    if kind == "diamond":
        s = size * 1.25
        pts = f"{n(x)},{n(y - s)} {n(x + s)},{n(y)} {n(x)},{n(y + s)} {n(x - s)},{n(y)}"
        return f'<polygon points="{pts}" class="pt {cls}"/>'
    die(f"unknown marker shape {kind}")


def mark(tip: list[str], inner: str, x=None, y=None, cls="", hit: str = "") -> str:
    """Wrap a mark with its tooltip text (value | label | detail) and hit target."""
    c = ("mark " + cls).strip()
    if hit == "" and x is not None:
        hit = f'<circle cx="{n(x)}" cy="{n(y)}" r="12" class="hit"/>'
    return f'<g class="{c}" data-tip="{esc("|".join(tip))}">{inner}{hit}</g>'


def scale(d0, d1, r0, r1):
    def f(v):
        return r0 + (v - d0) * (r1 - r0) / (d1 - d0)
    return f


def y_axis(ys, ticks, x0, x1, suffix="", spec="0") -> str:
    out = []
    for t in ticks:
        y = ys(t)
        out.append(line(x0, y, x1, y, "grid zero" if t == 0 else "grid"))
        out.append(text(x0 - 8, y + 4, fmt(t, spec) + suffix, "t", "end"))
    return "".join(out)


def x_axis(xs, ticks, y0, y1, suffix="", spec="0", grid=True) -> str:
    out = []
    for t in ticks:
        x = xs(t)
        if grid:
            out.append(line(x, y0, x, y1, "grid zero" if t == 0 else "grid"))
        out.append(text(x, y1 + 16, fmt(t, spec) + suffix, "t", "middle"))
    return "".join(out)


def swatch(kind: str, cls: str) -> str:
    """Legend key: a small inline SVG that mirrors the mark."""
    w = 14
    if kind == "bar":
        body = f'<rect x="1" y="3" width="12" height="8" rx="2" class="{cls}"/>'
    elif kind == "line":
        body = f'<line x1="1" y1="7" x2="13" y2="7" class="ln {cls}"/>'
    elif kind == "thin":
        body = f'<line x1="1" y1="7" x2="13" y2="7" class="ln thin {cls}"/>'
    elif kind == "band":
        body = f'<rect x="1" y="2" width="12" height="10" class="{cls}"/>'
    elif kind.startswith("lp:"):
        w = 26
        body = (f'<line x1="1" y1="7" x2="25" y2="7" class="ln s-{cls}"/>'
                + shape(kind[3:], 13, 7, f"c-{cls}", 3.6))
    else:
        body = shape(kind, 7, 7, cls, 4.0)
    return (f'<svg class="sw" viewBox="0 0 {w} 14" width="{w}" height="14" aria-hidden="true" '
            f'focusable="false">{body}</svg>')


def legend(items: list[tuple[str, str, str]]) -> str:
    lis = "".join(f"<li>{swatch(k, c)}<span>{esc(lbl)}</span></li>" for k, c, lbl in items)
    return f'<ul class="legend">{lis}</ul>'


def recipe_legend(mode: str = "marker") -> list[tuple[str, str, str]]:
    """The three recipes, keyed as the chart draws them. L3 carries a second encoding."""
    if mode == "bar":
        return [("bar", f"b-{r}", r) for r in RECIPES]
    if mode == "line":
        return [(f"lp:{SHAPE[r]}", r, r) for r in RECIPES]
    return [(SHAPE[r], f"c-{r}", r) for r in RECIPES]


def short_name(r: str) -> str:
    name = V("recipe_names." + r).replace(" action", "").replace(" penalty", "").replace("output ", "")
    if len(name) > 20 or "+" not in name:
        die(f"unexpected recipe name for {r}: {V('recipe_names.' + r)!r}")
    return name


def recipe_key() -> str:
    items = "".join(
        f'<li>{swatch("bar", "b-" + r)}{swatch(SHAPE[r], "c-" + r)}<span><b>{r}</b> '
        f'{esc(V("recipe_names." + r).lower())}</span></li>' for r in RECIPES)
    return f'<ul class="recipe-key" aria-label="Recipes">{items}</ul>'


HATCH = ('<pattern id="hatch-L3" patternUnits="userSpaceOnUse" width="5" height="5" '
         'patternTransform="rotate(45)"><rect width="5" height="5" class="hatch-bg"/>'
         '<rect width="2.4" height="5" class="hatch-fg"/></pattern>')


def defs_block() -> str:
    return ('<svg class="defs" width="0" height="0" aria-hidden="true" focusable="false">'
            f"<defs>{HATCH}</defs></svg>")


def table(caption: str, head: list[str], rows: list[list[str]]) -> str:
    th = "".join(f'<th scope="col">{esc(h)}</th>' for h in head)
    body = []
    for row in rows:
        cells = [f'<th scope="row">{esc(row[0])}</th>'] + [f"<td>{esc(c)}</td>" for c in row[1:]]
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (f'<table class="data"><caption>{esc(caption)}</caption><thead><tr>{th}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table>')


def chart(name, w, h, label, body, leg="", tab="", toggle=False) -> dict:
    return {"name": name, "w": w, "h": h, "label": label, "body": "".join(body),
            "legend": leg, "table": tab, "toggle": toggle}


def pts(value, spec="+2") -> str:
    return fmt(value, spec) + " points"


# ------------------------------------------------------------------ charts

def outcome_rows(name, rows, label, caption, with_base=None, h_row=44, above=False, width=W,
                 right_head="Editor SR"):
    """Segmented bars: rescued | kept | harmed | still failed, as shares of all pairs."""
    x0 = 2 if above else 48
    x1 = width - 68
    xs = scale(0, 100, x0, x1)
    top = 48 if above else 32
    body = [text(x0, 16, "Share of paired episodes (%)", "tl"),
            text(width - 2, 16, right_head, "tl", "end")]
    trows = []
    seg_names = (("r", "rescue", "Rescued"), ("k", "kept", "Kept"),
                 ("h", "harm", "Harmed"), ("f", "fail", "Still failed"))
    y = top
    for row in rows:
        vals = {s: V(f"{row['key']}.{s}") for s, _, _ in seg_names}
        total = sum(vals.values())
        pos = 0.0
        if above:
            body.append(text(x0, y - 7, row["label"], "dl"))
        else:
            body.append(text(x0 - 10, y + 16, row["label"], "dl", "end"))
        for s, cls, lbl in seg_names:
            v = vals[s]
            a, b = xs(pos * 100 / total), xs((pos + v) * 100 / total)
            pos += v
            wseg = b - a - 2
            tip = [fmt(v, "1") + "%", f"{lbl} · {row['label']}", row["tip"]]
            inner = rect(a, y, wseg, 24, f"c-{cls}", 3)
            if wseg >= 34:
                inner += text(a + 7, y + 16, fmt(v, "1"), f"in on-{cls}")
            elif s == "h" and not above:
                inner += text((a + b) / 2 - 1, y - 4, fmt(v, "1"), "dl2", "middle")
            elif above and wseg >= 10:
                inner += text((a + b) / 2 - 1, y + 38, fmt(v, "1"), "dl2", "middle")
            body.append(mark(tip, inner, hit=rect(a, y - 3, b - a, 30, "hit")))
        body.append(text(width - 2, y + 16, fmt(V(row["sr"]), "1") + "%", "dl", "end"))
        trows.append([row["long"]] + [fmt(vals[s], "1") for s, _, _ in seg_names]
                     + [fmt(V(row["sr"]), "2"), fmt(V(row["base"]), "2")])
        y += h_row
    if with_base:
        b = V(with_base["key"])
        blabel = with_base.get("label", "Base")
        if above:
            body.append(text(x0, y - 7, blabel, "dl"))
        else:
            body.append(text(x0 - 10, y + 16, blabel, "dl", "end"))
        a1 = xs(b)
        tip = [fmt(b, "1") + "%", "Base succeeds", with_base["tip"]]
        body.append(mark(tip, rect(x0, y, a1 - x0 - 2, 24, "c-kept", 3)
                         + text(x0 + 7, y + 16, fmt(b, "1"), "in on-kept"),
                         hit=rect(x0, y - 3, a1 - x0, 30, "hit")))
        tip = [fmt(100 - b, "1") + "%", "Base fails", with_base["tip"]]
        body.append(mark(tip, rect(a1, y, x1 - a1 - 2, 24, "c-fail", 3)
                         + text(a1 + 7, y + 16, fmt(100 - b, "1"), "in on-fail"),
                         hit=rect(a1, y - 3, x1 - a1, 30, "hit")))
        body.append(text(width - 2, y + 16, fmt(b, "1") + "%", "dl", "end"))
        y += h_row
    leg = legend([("bar", f"c-{cls}", lbl) for _, cls, lbl in seg_names])
    tab = table(caption, ["Policy", "Rescued", "Kept", "Harmed", "Still failed",
                          "Editor SR", "Base SR"], trows)
    return chart(name, width, y - h_row + (46 if above else 34), label, body, leg, tab)


def c_outcomes_112():
    rows = [{"key": f"recipes.s112.{r}.ho", "label": r,
             "long": f"{r} ({V('recipe_names.' + r)})",
             "sr": f"recipes.s112.{r}.ho.sr", "base": "base.s112.heldout",
             "tip": f"{F('setup.pairs_heldout', 'int')} paired held-out episodes"}
            for r in RECIPES]
    return outcome_rows(
        "outcomes_112", rows,
        f"Paired outcomes of the three {NS()}-task editors on {NH()} held-out tasks: rescued, "
        "kept, harmed and still failed shares of all paired episodes.",
        f"Paired outcomes on {NH()} held-out tasks, {NS()}-task editors (shares of "
        f"{F('setup.pairs_heldout', 'int')} paired episodes, %; SR in %).",
        with_base={"key": "base.s112.heldout", "tip": "frozen base, same tasks and initial states"},
        h_row=46, width=WW)


def c_rt_outcomes():
    rows = [{"key": "robotwin.source", "label": "Four source tasks", "long": "Four source tasks",
             "sr": "robotwin.source.editor", "base": "robotwin.source.base",
             "tip": f"{F('robotwin.source.pairs', 'int')} paired scenes, four source tasks"},
            {"key": "robotwin.other",
             "label": f"{F('robotwin.other.n_tasks', 'int')} other tasks, no editor update",
             "long": "Other tasks, no editor update",
             "sr": "robotwin.other.editor", "base": "robotwin.other.base",
             "tip": f"{F('robotwin.other.pairs', 'int')} paired scenes, twelve other tasks"}]
    return outcome_rows(
        "rt_outcomes", rows,
        "Paired outcomes of the four-task RoboTwin editor on its four source tasks and on "
        "twelve other tasks.",
        "RoboTwin: paired outcomes of the four-task editor (shares of paired scenes, %; SR in %).",
        h_row=62, above=True, width=W)


def c_rt_b4_amp():
    """RoboTwin B4 matched half-scale panel on 12 other tasks (600 matched triplets)."""
    rows = [{"key": "robotwin.b4.full",
             "label": "Full correction (α = 1.0)",
             "long": "Full correction (α = 1.0)",
             "sr": "robotwin.b4.full.sr", "base": "robotwin.b4.base.sr",
             "tip": f"{F('robotwin.b4.pairs', 'int')} matched triplets, twelve other tasks"},
            {"key": "robotwin.b4.half",
             "label": "Half correction (α = 0.5)",
             "long": "Half correction (α = 0.5)",
             "sr": "robotwin.b4.half.sr", "base": "robotwin.b4.base.sr",
             "tip": f"{F('robotwin.b4.pairs', 'int')} matched triplets, twelve other tasks"}]
    c = outcome_rows(
        "rt_b4_amp", rows,
        "Matched RoboTwin correction-amplitude panel on twelve other tasks: full correction, "
        "half correction, and the matched frozen base across 600 paired triplets.",
        f"RoboTwin amplitude scaling on {F('robotwin.b4.tasks_count', 'int')} other tasks "
        f"({F('robotwin.b4.pairs', 'int')} matched triplets, {F('robotwin.b4.episodes', 'int')} "
        f"episodes; shares in %, SR in %).",
        with_base={"key": "robotwin.b4.base.sr", "label": "Matched base (same triplets)",
                   "tip": f"{F('robotwin.b4.pairs', 'int')} matched scenes, twelve other tasks"},
        h_row=62, above=True, width=W, right_head="SR")
    return c


def c_f1_breadth():
    h = 248
    x0, x1, y0, y1 = 46, 404, 30, 194
    cols = ["n2", "n16", "n112"]
    xp = {c: x0 + 48 + i * (x1 - x0 - 96) / 2 for i, c in enumerate(cols)}
    ys = scale(0, 40, y1, y0)
    body = [text(x0 - 32, 16, "Share of paired held-out episodes (%)", "tl"),
            y_axis(ys, [0, 10, 20, 30, 40], x0, x1)]
    for c in cols:
        body.append(text(xp[c], y1 + 18, F(f"breadth.{c}.sources", "int"), "t", "middle"))
    body.append(text((x0 + x1) / 2, y1 + 38, "Source tasks (bounded recipe, L3)", "tl", "middle"))
    trows = []
    for stat, cls, name, kind, dy in (("r", "rescue", "Rescue", "circle", -12),
                                      ("h", "harm", "Harm", "square", -12)):
        ptsxy = [(xp[c], ys(V(f"breadth.{c}.{stat}"))) for c in cols]
        body.append('<polyline points="' + " ".join(f"{n(x)},{n(y)}" for x, y in ptsxy)
                    + f'" class="ln s-{cls}"/>')
        for c, (x, y) in zip(cols, ptsxy):
            v = V(f"breadth.{c}.{stat}")
            tip = [fmt(v, "1") + "%", f"{name} · {F(f'breadth.{c}.sources', 'int')} source tasks",
                   f"base SR {F(f'breadth.{c}.base', '2')}%, held-out SR {F(f'breadth.{c}.ho_sr', '2')}%"]
            off = dy
            if c == "n16":
                off = 22 if stat == "r" else -12
            if c == "n2" and stat == "r":
                off = -11
            body.append(mark(tip, shape(kind, x, y, f"c-{cls}")
                             + text(x, y + off, fmt(v, "1"), "dl", "middle"), x, y))
        xe, ye = ptsxy[-1]
        body.append(text(xe + 14, ye + 4, name, "dl"))
    for c in cols:
        trows.append([F(f"breadth.{c}.sources", "int"), F(f"breadth.{c}.src_sr", "2"),
                      F(f"breadth.{c}.ho_sr", "2"), F(f"breadth.{c}.base", "2"),
                      F(f"breadth.{c}.r", "1"), F(f"breadth.{c}.h", "1")])
    leg = legend([("circle", "c-rescue", "Rescue"), ("square", "c-harm", "Harm")])
    tab = table("Source breadth under the bounded recipe (L3): success rates (%) and shares of "
                f"{F('setup.pairs_heldout', 'int')} paired held-out episodes (%).",
                ["Source tasks", "Source SR", "Held-out SR", "Held-out base SR", "Rescue", "Harm"],
                trows)
    return chart("f1_breadth", W, h,
                 f"Rescue and harm shares on {NH()} held-out tasks for bounded editors trained on "
                 "increasing numbers of source tasks.", body, leg, tab)


def c_f1_source_vs_heldout():
    h = 266
    x0, x1, y0, y1 = 46, 460, 24, 210
    xs, ys = scale(50, 100, x0, x1), scale(15, 50, y1, y0)
    body = [text(x0 - 32, 14, "Held-out SR (%)", "tl"),
            y_axis(ys, [20, 30, 40, 50], x0, x1), x_axis(xs, [50, 60, 70, 80, 90, 100], y0, y1),
            text((x0 + x1) / 2, y1 + 38, f"Source SR (%), {N16()} source tasks", "tl", "middle")]
    yb = ys(V("base.s16.heldout"))
    body.append(line(x0, yb, x1, yb, "ref"))
    body.append(text(x0 + 6, yb + 15, f"Matched base {F('base.s16.heldout', '1')}%", "dl2"))
    place = {"R1": (0, -12, "middle"), "R2": (0, -12, "middle"), "R3": (-2, 21, "middle"),
             "L1": (4, 21, "middle"), "L2": (0, -12, "middle"), "L3": (0, -12, "middle")}
    names = {"1": "L1", "2": "L2", "3": "L3"}
    trows = []
    for rid in ("R1", "R2", "R3", "L1", "L2", "L3"):
        sx, sy = V(f"recipes.s16.{rid}.src.sr"), V(f"recipes.s16.{rid}.ho.sr")
        x, y = xs(sx), ys(sy)
        choice = V("recipe_names." + names[rid[1]])
        rep = "RL-token readout" if rid[0] == "R" else "online-learned encoder"
        kind = "diamond" if rid[0] == "R" else "circle"
        tip = [f"{fmt(sy, '2')}% held-out", f"{rid} · {choice}, {rep}",
               f"source SR {fmt(sx, '2')}%"]
        dx, dy, anchor = place[rid]
        body.append(mark(tip, shape(kind, x, y, f"c-{names[rid[1]]}", 5.2)
                         + text(x + dx, y + dy, rid, "dl", anchor), x, y))
        trows.append([f"{rid} ({choice}; {rep})", fmt(sx, "2"), fmt(sy, "2"),
                      F(f"recipes.s16.{rid}.ho.r", "1"), F(f"recipes.s16.{rid}.ho.h", "1")])
    leg = legend([("circle", "c-ink", "L: online encoder"), ("diamond", "c-ink", "R: RL-token readout")]
                 + [("bar", f"c-{r}", f"{r[1]}: {short_name(r).lower()}") for r in RECIPES])
    tab = table(f"Six recipes after {F('setup.updates_16_k', 'int')}k online actor updates on "
                f"{N16()} source tasks (SR in %; rescue and harm as shares of "
                f"{F('setup.pairs_heldout', 'int')} paired held-out episodes, %). Held-out base "
                f"SR {F('base.s16.heldout', '2')}%.",
                ["Recipe", "Source SR", "Held-out SR", "Rescue", "Harm"], trows)
    return chart("f1_source_vs_heldout", W, h,
                 f"Source success rate against held-out success rate for the six {N16()}-task "
                 "recipes.", body, leg, tab)


def task_ids() -> list[str]:
    return list(V("tasks").keys())


def c_f2_scatter():
    h = 294
    x0, x1, y0, y1 = 48, 460, 24, 238
    xs, ys = scale(0, 80, x0, x1), scale(-40, 100, y1, y0)
    body = [text(x0 - 34, 14, "Gain over the base (points)", "tl")]
    poly = [(xs(0), ys(0)), (xs(0), ys(100)), (xs(80), ys(20)), (xs(80), ys(-40)),
            (xs(40), ys(-40))]
    body.append('<polygon points="' + " ".join(f"{n(x)},{n(y)}" for x, y in poly)
                + '" class="region"/>')
    body.append(y_axis(ys, [-40, -20, 0, 20, 40, 60, 80, 100], x0, x1, spec="+0"))
    body.append(x_axis(xs, [0, 20, 40, 60, 80], y0, y1))
    body.append(text((x0 + x1) / 2, y1 + 38, "Base SR on the task (%)", "tl", "middle"))
    slope = math.degrees(math.atan2(ys(0) - ys(1), xs(1) - xs(0)))
    for label, bx, by, dy in (("all failures rescued", 42, 58, -9), ("all successes lost", 5, -5, 16)):
        px, py = xs(bx), ys(by) + dy
        body.append(text(px, py, label, "dl2",
                         extra=f' transform="rotate({n(slope)} {n(px)} {n(py)})"'))
    trows = []
    for tid in task_ids():
        base = V(f"tasks.{tid}.base")
        name = V(f"tasks.{tid}.name")
        for r in RECIPES:
            g = V(f"tasks.{tid}.gain_{r}")
            x, y = xs(base), ys(g)
            tip = [pts(g, "+0"), f"{r} · {name}",
                   f"base {fmt(base, '0')}% → editor {F(f'tasks.{tid}.{r}', '0')}%"]
            body.append(mark(tip, shape(SHAPE[r], x, y, f"c-{r}", 4.1), x, y, cls=f"rk rk-{r}"))
        scene = "source-covered" if V(f"tasks.{tid}.scene") == "covered" else "uncovered"
        trows.append([name, scene, fmt(base, "0")]
                     + [f"{F(f'tasks.{tid}.{r}', '0')} ({fmt(V(f'tasks.{tid}.gain_{r}'), '+0')})"
                        for r in RECIPES])
    tab = table(f"Success rate (%) on each of the {NH()} held-out tasks, with the gain over the "
                f"base in points (two passes over {F('setup.states', 'int')} initial states per "
                f"task, {NS()}-task editors).",
                ["Task", "Scene", "Base", "L1", "L2", "L3"], trows)
    leg = legend(recipe_legend("marker"))
    return chart("f2_scatter", W, h,
                 "Gain over the base against base success rate, one point per held-out task and "
                 "recipe.", body, leg, tab, toggle=True)


def grouped_columns(name, groups, key_fn, ylab, yticks, label, caption, head0, note_fn, spec,
                    h=258, width=W):
    x0, x1, y0, y1 = 48, width - 20, 28, h - 58
    ys = scale(yticks[0], yticks[-1], y1, y0)
    body = [text(x0 - 34, 14, ylab, "tl"), y_axis(ys, yticks, x0, x1, spec="+0")]
    gw = (x1 - x0) / len(groups)
    bw = 26 if width >= 540 else 24
    trows = []
    for gi, (gid, glabel, sub) in enumerate(groups):
        cx = x0 + gw * (gi + 0.5)
        row = [f"{glabel} ({sub})"]
        for ri, r in enumerate(RECIPES):
            v = V(key_fn(gid, r))
            x = cx + (ri - 1) * (bw + 5) - bw / 2
            yv = ys(v)
            tip = [pts(v, spec), f"{r} · base SR {glabel}", note_fn(gid, r)]
            lab_y = yv - 6 if v >= 0 else yv + 14
            inner = vbar(x, bw, ys(0), yv, f"b-{r}") + text(x + bw / 2, lab_y, fmt(v, "+0"),
                                                             "dl2", "middle")
            body.append(mark(tip, inner, cls=f"rk rk-{r}",
                             hit=rect(x - 2, min(yv, ys(0)) - 14, bw + 4,
                                      abs(yv - ys(0)) + 20, "hit")))
            row.append(fmt(v, spec))
        body.append(text(cx, y1 + 17, glabel, "t", "middle"))
        body.append(text(cx, y1 + 31, sub, "t", "middle"))
        trows.append(row)
    body.append(line(x0, ys(0), x1, ys(0), "axis"))
    body.append(text((x0 + x1) / 2, y1 + 50, "Base SR of the task group", "tl", "middle"))
    tab = table(caption, [head0, "L1", "L2", "L3"], trows)
    return chart(name, width, h, label, body, legend(recipe_legend("bar")), tab, toggle=True)


def c_f2_groups():
    groups = [(g, V(f"base_groups.{g}.label"), f"{F(f'base_groups.{g}.n_tasks', 'int')} tasks")
              for g in ("low", "mid", "high")]
    return grouped_columns(
        "f2_groups", groups, lambda g, r: f"base_groups.{g}.{r}.gain",
        "Gain over the base (points)", [-20, 0, 20, 40, 60],
        f"Gain over the base for the three {NS()}-task recipes on held-out tasks grouped by "
        "base success rate.",
        f"Gain (rescue share minus harm share, points) of the {NS()}-task editors on the {NH()} "
        "held-out tasks grouped by two-pass base SR; groups formed after evaluation.",
        "Base SR group",
        lambda g, r: (f"rescue {F(f'base_groups.{g}.{r}.r', '1')}%, "
                      f"harm {F(f'base_groups.{g}.{r}.h', '1')}%"), "+1", h=294, width=W)


def c_h_unseen96():
    groups = [(g, V(f"unseen96.groups.{g}.label"),
               f"{F(f'unseen96.groups.{g}.n_tasks', 'int')} tasks") for g in ("low", "mid", "high")]
    return grouped_columns(
        "h_unseen96", groups, lambda g, r: f"unseen96.groups.{g}.{r}.gain",
        "Gain over the base (points)", [-30, -20, -10, 0, 10, 20, 30],
        f"Gain over the base for the three {N16()}-task editors on {N96()} further unseen tasks "
        "grouped by base success rate.",
        f"Gain (points) of the {N16()}-task editors on {N96()} further unseen tasks grouped by base SR in "
        f"the same batch ({F('unseen96.t96.pairs', 'int')} pairs per recipe; base SR "
        f"{F('unseen96.t96.base', '2')}%).",
        "Base SR group",
        lambda g, r: (f"rescue {F(f'unseen96.groups.{g}.{r}.r', '1')}%, "
                      f"harm {F(f'unseen96.groups.{g}.{r}.h', '1')}%"), "+2", h=264, width=WW)


def c_f3_harm():
    h = 264
    x0, x1 = 152, 444
    xs = scale(0, 12, x0, x1)
    lo, hi = V("repeat.base_harm.lo"), V("repeat.base_harm.hi")
    y_top, y_bot = 38, 220
    body = [text(x0, 14, "Harm: share of paired held-out episodes (%)", "tl"),
            rect(xs(lo), y_top - 8, xs(hi) - xs(lo), y_bot - y_top + 8, "band"),
            x_axis(xs, [0, 2, 4, 6, 8, 10, 12], y_top - 8, y_bot)]
    body.append(text(xs(hi) + 6, y_top + 2, "base run twice:", "dl2"))
    body.append(text(xs(hi) + 6, y_top + 15, f"{fmt(lo, '1')}{NDASH}{fmt(hi, '1')}%", "dl2"))
    rows = [("head", f"{NS()}-task recipes"),
            ("L2", "recipes.s112.L2.ho.h", "L2", "setup.pairs_heldout", "base.s112.heldout"),
            ("L1", "recipes.s112.L1.ho.h", "L1", "setup.pairs_heldout", "base.s112.heldout"),
            ("L3", "recipes.s112.L3.ho.h", "L3", "setup.pairs_heldout", "base.s112.heldout"),
            ("head", "L3, separate batch"),
            ("L3", "scaling.original.h", "Full correction", "scaling.pairs", "scaling.base"),
            ("L3", "scaling.half.h", "Half correction", "scaling.pairs", "scaling.base")]
    y = y_top + 22
    trows = []
    for row in rows:
        if row[0] == "head":
            body.append(text(2, y + 3, row[1], "tl"))
            y += 14
            continue
        r, key, lbl, pairs, base = row
        v = V(key)
        tip = [fmt(v, "1") + "%", f"Harm · {lbl}" + ("" if lbl == r else f" ({r})"),
               f"{F(pairs, 'int')} pairs, base SR {F(base, '2')}%"]
        inner = (text(x0 - 10, y + 12, lbl, "dl", "end") + hbar(x0, xs(v), y, 16, f"b-{r}")
                 + text(xs(v) + 7, y + 12, fmt(v, "1"), "dl"))
        body.append(mark(tip, inner, cls=f"rk rk-{r}", hit=rect(x0, y - 4, x1 - x0 + 30, 24, "hit")))
        trows.append([lbl if lbl == r else f"L3, {lbl.lower()}", fmt(v, "1"), F(pairs, "int"),
                      F(base, "2")])
        y += 26
    body.append(line(x0, y_top - 8, x0, y_bot, "axis"))
    trows.append(["Base, second run against first", f"{fmt(lo, '1')}{NDASH}{fmt(hi, '1')}",
                  F("repeat.pairs", "int"), f"{F('repeat.base12.first', '2')}{NDASH}"
                  f"{F('repeat.base12.second', '2')}"])
    leg = legend(recipe_legend("bar") + [("band", "band", "Base run twice")])
    tab = table(f"Harm share on the {NH()} held-out tasks (%), with the number of paired episodes and "
                "the base SR (%) of each batch.", ["Policy", "Harm", "Pairs", "Base SR"], trows)
    return chart("f3_harm", W, h,
                 f"Harm share by recipe on {NH()} held-out tasks, with the level measured when the base "
                 "alone is run twice, and for the bounded editor at full and half correction.",
                 body, leg, tab, toggle=True)


ALPHAS = ("a100", "a075", "a050", "a025")


def dose_chart(name, stat, ylab, yticks, label, caption, unit, spec):
    h = 264
    x0, x1, y0, y1 = 46, 460, 28, 206
    ys = scale(yticks[0], yticks[-1], y1, y0)
    xp = {a: x0 + 68 + i * (x1 - x0 - 104) / 3 for i, a in enumerate(ALPHAS)}
    body = [text(x0 - 32, 14, ylab, "tl"), y_axis(ys, yticks, x0, x1)]
    for a in ALPHAS:
        body.append(text(xp[a], y1 + 18, F(f"dose.L1.{a}.alpha", "2"), "t", "middle"))
    body.append(text((x0 + x1) / 2, y1 + 40,
                     f"Correction scale α at inference ({F('dose.L1.a100.alpha', '0')} = "
                     "unmodified editor)", "tl", "middle"))
    trows = []
    for r in RECIPES:
        means = [(xp[a], ys(V(f"dose.{r}.{a}.mean.{stat}"))) for a in ALPHAS]
        g = ['<polyline points="' + " ".join(f"{n(x)},{n(y)}" for x, y in means)
             + f'" class="ln s-{r}"/>']
        for a, (x, y) in zip(ALPHAS, means):
            b1, b2 = V(f"dose.{r}.{a}.b1.{stat}"), V(f"dose.{r}.{a}.b2.{stat}")
            g.append(line(x, ys(b1), x, ys(b2), f"whisk s-{r}"))
            tip = [f"{fmt(b1, spec)}{unit} and {fmt(b2, spec)}{unit}",
                   f"{r} · α = {F(f'dose.{r}.{a}.alpha', '2')}",
                   f"two batches of {F('dose.pairs', 'int')} pairs"]
            g.append(mark(tip, shape(SHAPE[r], x, y, f"c-{r}"), x, y))
            trows.append([f"{r}, α = {F(f'dose.{r}.{a}.alpha', '2')}",
                          fmt(b1, spec), fmt(b2, spec)])
        x, y = means[0]
        g.append(text(x - 13, y + 4, r, "dl", "end"))
        body.append(f'<g class="rk rk-{r}">' + "".join(g) + "</g>")
    tab = table(caption, ["Recipe and scale", "First batch", "Second batch"], trows)
    return chart(name, W, h, label, body, legend(recipe_legend("line")), tab, toggle=True)


def c_f3_dose_harm():
    return dose_chart(
        "f3_dose_harm", "h", "Harm: share of paired episodes (%)", [0, 3, 6, 9, 12],
        f"Harm share against the correction scale applied at inference, three {NS()}-task editors.",
        f"Harm share (%) on the {NH()} held-out tasks when the correction is scaled at inference; two "
        f"separately run batches of {F('dose.pairs', 'int')} pairs (base SR "
        f"{F('dose.base.b1', '2')}% and {F('dose.base.b2', '2')}%).", "%", "1")


def c_f3_dose_sr():
    return dose_chart(
        "f3_dose_sr", "sr", "Held-out SR (%)", [45, 50, 55, 60, 65],
        f"Held-out success rate against the correction scale applied at inference, three {NS()}-task "
        "editors.",
        "Held-out SR (%) when the correction is scaled at inference; two separately run batches "
        f"of {F('dose.pairs', 'int')} pairs (base SR {F('dose.base.b1', '2')}% and "
        f"{F('dose.base.b2', '2')}%).", "%", "2")


def c_f3_armgrip():
    h = 192
    x0, x1 = 148, 520
    xs = scale(0, 60, x0, x1)
    rows = [("full", "Full correction", None), ("arm", "Arm halved", "armgrip.arm.diff"),
            ("gripper", "Gripper halved", "armgrip.gripper.diff"),
            ("both", "Both halved", "armgrip.both.diff")]
    y_top = 32
    body = [text(x0, 14, "Held-out SR (%), bounded editor L3", "tl"),
            x_axis(xs, [0, 20, 40, 60], y_top - 6, y_top + 4 * 30)]
    trows = []
    y = y_top
    for key, lbl, diff in rows:
        v = V(f"armgrip.{key}.sr")
        tail = ""
        ci = ""
        if diff:
            tail = f"  ({fmt(V(diff + '.d'), '+2')})"
            ci = f"{fmt(V(diff + '.d'), '+2')} [{fmt(V(diff + '.lo'), '+2')}, {fmt(V(diff + '.hi'), '+2')}]"
        tip = [fmt(v, "2") + "%", lbl,
               (f"difference to full correction {ci} points" if diff
                else f"{F('armgrip.episodes', 'int')} episodes per condition")]
        inner = (text(x0 - 10, y + 13, lbl, "dl", "end") + hbar(x0, xs(v), y, 18, "b-L3")
                 + text(xs(v) + 8, y + 13, fmt(v, "1") + tail, "dl"))
        body.append(mark(tip, inner, hit=rect(x0, y - 4, WW - x0, 26, "hit")))
        trows.append([lbl, fmt(v, "2"), ci or NDASH])
        y += 30
    body.append(line(x0, y_top - 6, x0, y_top + 120, "axis"))
    tab = table(f"Arm and gripper correction of the {NS()}-task bounded editor scaled separately "
                f"({NH()} held-out tasks, first {F('armgrip.states', 'int')} initial states, "
                f"{F('armgrip.episodes', 'int')} episodes per condition; no base run in this batch).",
                ["Condition", "SR (%)", f"Difference to full correction, points [{CI()} CI]"], trows)
    return chart("f3_armgrip", WW, h,
                 "Held-out success rate of the bounded editor with the arm correction, the "
                 "gripper correction or both halved.", body, "", tab)


def c_f4_controls():
    """First-pass controls: tightened top spacing so row 1 sits cleanly under the axis labels."""
    x0, x1 = 42, 470
    xs = scale(20, 65, x0, x1)
    y_grid_top = 46
    row_h = 46
    y_bot = y_grid_top + 3 * row_h - 2
    h = y_bot + 26
    col_mean, col_frozen = 556, 636
    body = [text(x0, 14, "Held-out SR (%), first pass", "tl"),
            text(col_frozen, 14, "Difference to live (pts)", "t", "end"),
            text(col_mean, 32, "Fixed", "tl", "end"), text(col_frozen, 32, "Frozen", "tl", "end"),
            x_axis(xs, [20, 30, 40, 50, 60], y_grid_top, y_bot)]
    xb, xn = xs(V("controls.base.mean")), xs(V("controls.base_native.mean"))
    body.append(line(xb, y_grid_top, xb, y_bot, "ref"))
    body.append(text(xb, y_grid_top - 7, f"Base {F('controls.base.mean', '1')}", "dl2", "middle"))
    body.append(line(xn, y_grid_top, xn, y_bot, "ref"))
    body.append(text(xn + 5, y_grid_top - 7, f"Native chunk {F('controls.base_native.mean', '1')}",
                     "dl2"))
    conds = (("live", "circle", "Live editor", None, None),
             ("mean", "diamond", "Own source-mean correction", "mean_delta", col_mean),
             ("frozen", "square", "Editor frames frozen at step 0", "frozen_delta", col_frozen))
    trows = []
    for i, r in enumerate(RECIPES):
        yc = y_grid_top + 19 + row_h * i
        g = [text(x0 - 10, yc + 4, r, "dl", "end"), line(x0, yc, x1, yc, "grid")]
        for cond, kind, lbl, delta, col in conds:
            m, lo, hi = (V(f"controls.{r}.{cond}.{s}") for s in ("mean", "low", "high"))
            x = xs(m)
            g.append(line(xs(lo), yc, xs(hi), yc, f"whisk s-{r}"))
            cls = f"c-{r}" if cond == "live" else f"o-{r}"
            tip = [fmt(m, "2") + "%", f"{r} · {lbl}",
                   f"{CI()} interval {fmt(lo, '2')}{NDASH}{fmt(hi, '2')}"]
            row = [f"{r}, {lbl.lower()}", fmt(m, "2"), f"{fmt(lo, '2')}{NDASH}{fmt(hi, '2')}"]
            lab = ""
            if delta:
                d, dl, dh = (V(f"controls.{r}.{delta}.{s}") for s in ("d", "lo", "hi"))
                tip[2] = f"{fmt(d, '+2')} points to live [{fmt(dl, '+2')}, {fmt(dh, '+2')}]"
                g.append(text(col, yc + 4, fmt(d, "+2"), "dl", "end"))
                row.append(f"{fmt(d, '+2')} [{fmt(dl, '+2')}, {fmt(dh, '+2')}]")
            else:
                lab = text(x, yc - 10, fmt(m, "1"), "dl", "middle")
                row.append(NDASH)
            g.append(mark(tip, shape(kind, x, yc, cls, 5.2) + lab, x, yc))
            trows.append(row)
        body.append(f'<g class="rk rk-{r}">' + "".join(g) + "</g>")
    leg = legend([("circle", "c-ink", "Live editor"),
                  ("diamond", "o-ink", "Fixed: own source-mean correction"),
                  ("square", "o-ink", "Frozen: editor camera frames held at step 0")])
    tab = table(f"First-pass controls on the {NH()} held-out tasks "
                f"({F('controls.pairs', 'int')} pairs per condition; base SR "
                f"{F('controls.base.mean', '2')}%, native eight-action base "
                f"{F('controls.base_native.mean', '2')}%).",
                ["Condition", "SR (%)", f"{CI()} interval",
                 f"Difference to live, points [{CI()} CI]"], trows)
    return chart("f4_controls", WW, h,
                 f"Held-out success rate of each {NS()}-task editor when live, when replaced by its "
                 "own source-mean correction, and with frozen editor camera frames.",
                 body, leg, tab, toggle=True)


def c_f4_directions():
    h = 152
    x0, x1 = 48, 578
    xs = scale(0, 100, x0, x1)
    y_top = 30
    body = [text(x0, 14, "Held-out correction variance captured by ten source directions (%)", "tl"),
            x_axis(xs, [0, 25, 50, 75, 100], y_top - 6, y_top + 3 * 28)]
    trows = []
    y = y_top
    for r in ("L3", "L2", "L1"):
        v = V(f"directions.{r}.m10")
        need = F(f"directions.{r}.m_for_85", "int")
        tip = [fmt(v, "1") + "%", f"{r} · first ten source directions",
               f"{need} directions capture {F('directions.threshold', 'int')}%"]
        inner = (text(x0 - 10, y + 13, r, "dl", "end") + hbar(x0, xs(v), y, 18, f"b-{r}")
                 + text(xs(v) + 8, y + 13, fmt(v, "1") + "%", "dl"))
        body.append(mark(tip, inner, cls=f"rk rk-{r}", hit=rect(x0, y - 4, WW - x0, 26, "hit")))
        trows.append([r, fmt(v, "1"), need])
        y += 28
    body.append(line(x0, y_top - 6, x0, y_top + 84, "axis"))
    tab = table("Share (%) of held-out correction variance captured by the first ten principal "
                f"directions of each {NS()}-task editor's source-task corrections, and the number "
                f"of directions needed to capture {F('directions.threshold', 'int')}%.",
                ["Recipe", "Ten directions (%)", f"Directions for {F('directions.threshold', 'int')}%"],
                trows)
    return chart("f4_directions", WW, h,
                 "Share of held-out correction variance captured by ten source correction "
                 "directions, by recipe.", body, "", tab, toggle=True)


def c_h_repeat():
    h = 196
    x0, x1 = 158, 558
    xs = scale(0, 12, x0, x1)
    y_top = 32
    rows = [("base", "Base vs. base", "three pairings", "repeat.base_harm", "c-ink3"),
            ("L2", "L2 vs. base", "six pairings", "repeat.L2.harm6", "b-L2"),
            ("L1", "L1 vs. base", "six pairings", "repeat.L1.harm6", "b-L1"),
            ("L3", "L3 vs. base", "six pairings", "repeat.L3.harm6", "b-L3")]
    body = [text(x0, 14, "Success turned into failure: share of pairs (%)", "tl"),
            x_axis(xs, [0, 2, 4, 6, 8, 10, 12], y_top - 6, y_top + 4 * 32)]
    trows = []
    y = y_top
    for rid, lbl, sub, key, cls in rows:
        lo, hi = V(key + ".lo"), V(key + ".hi")
        tip = [f"{fmt(lo, '1')}{NDASH}{fmt(hi, '1')}%", f"{lbl}, {sub}",
               f"{F('repeat.pairs', 'int')} pairs per comparison"]
        a, b = xs(lo), xs(hi)
        inner = (text(x0 - 10, y + 11, lbl, "dl", "end") + text(x0 - 10, y + 24, sub, "t", "end")
                 + rect(a - 4, y + 5, b - a + 8, 11, cls, 5)
                 + text(b + 10, y + 14, f"{fmt(lo, '1')}{NDASH}{fmt(hi, '1')}%", "dl"))
        body.append(mark(tip, inner, cls=("" if rid == "base" else f"rk rk-{rid}"),
                         hit=rect(x0, y - 2, WW - x0, 30, "hit")))
        trows.append([f"{lbl} ({sub})", f"{fmt(lo, '1')}{NDASH}{fmt(hi, '1')}"])
        y += 32
    body.append(line(x0, y_top - 6, x0, y_top + 128, "axis"))
    tab = table("Share of paired held-out episodes (%) that succeed in the reference run and "
                f"fail in the compared run ({F('repeat.pairs', 'int')} pairs per comparison; "
                "one batch).", ["Comparison", "Range over pairings (%)"], trows)
    return chart("h_repeat", WW, h,
                 "Share of pairs that turn from success to failure between two runs of the base, "
                 "and between the base and each editor.", body, "", tab, toggle=True)


def evo_points(r, seed):
    node = V(f"evolution.{r}.{seed}")
    return sorted(((p["updates_k"], p["sr"]) for p in node.values()), key=lambda t: t[0])


def c_h_seeds112():
    h = 276
    x0, x1, y0, y1 = 46, 412, 24, 218
    xs, ys = scale(0, 481.25, x0 + 6, x1), scale(0, 70, y1, y0)
    body = [text(x0 - 32, 14, "Held-out SR (%)", "tl"),
            y_axis(ys, [0, 10, 20, 30, 40, 50, 60, 70], x0, x1),
            x_axis(xs, [0, 100, 200, 300, 400], y0, y1, grid=False),
            text((x0 + x1) / 2, y1 + 38, "Online actor updates (thousands)", "tl", "middle")]
    yb = ys(V("evolution.base"))
    body.append(line(x0, yb, x1, yb, "ref"))
    body.append(text(x1 - 4, yb + 15, f"Base {F('evolution.base', '1')}", "dl2", "end"))
    trows = []
    end_dy = {"L1": 1, "L2": 5, "L3": 9}
    for r in RECIPES:
        g = []
        for seed, lcls, pcls, sname in (("seed0", f"ln s-{r}", f"c-{r}", "first seed"),
                                        ("seed1", f"ln thin s-{r}", f"o-{r}", "second seed"),
                                        ("seed2", f"ln thin dot s-{r}", f"t-{r}", "third seed")):
            data = evo_points(r, seed)
            xy = [(xs(u), ys(v)) for u, v in data]
            g.append('<polyline points="' + " ".join(f"{n(x)},{n(y)}" for x, y in xy)
                     + f'" class="{lcls}"/>')
            for (u, v), (x, y) in zip(data, xy):
                tip = [fmt(v, "2") + "%", f"{r} · {sname}",
                       f"{fmt(u, '2')}k online actor updates"]
                g.append(mark(tip, shape(SHAPE[r], x, y, pcls, 4.0), x, y))
                trows.append([f"{r}, {sname}", fmt(u, "2"), fmt(v, "2")])
        u, v = evo_points(r, "seed0")[-1]
        g.append(text(xs(u) + 10, ys(v) + end_dy[r] - 1, f"{r} {fmt(v, '1')}", "dl"))
        body.append(f'<g class="rk rk-{r}">' + "".join(g) + "</g>")
    leg = legend(recipe_legend("line") + [("circle", "c-ink", "First seed"),
                                          ("circle", "o-ink", "Second seed (shorter)"),
                                          ("circle", "t-ink", "Third seed (shorter)")])
    tab = table(f"Held-out SR (%) on {NH()} tasks across training for the three {NS()}-task recipes. "
                "Snapshots and endpoints come from separate evaluation batches, each paired with "
                "its own base run.", ["Recipe and seed", "Updates (thousands)", "Held-out SR"],
                trows)
    return chart("h_seeds112", W, h,
                 f"Held-out success rate across training for the three {NS()}-task recipes, first, "
                 "second and third training seed.", body, leg, tab, toggle=True)


def c_h_seeds16():
    h = 204
    x0, x1 = 46, 460
    xs = scale(15, 50, x0, x1)
    y_top, row_h = 32, 40
    y_bot = y_top + 3 * row_h
    b0, b1 = V("seeds16.base.seed12"), V("seeds16.base.seed0")
    body = [text(x0, 14, f"Held-out SR (%), {N16()} source tasks, three training seeds", "tl"),
            rect(xs(b0), y_top - 6, max(xs(b1) - xs(b0), 2.0), y_bot - y_top + 6, "band"),
            x_axis(xs, [20, 30, 40, 50], y_top - 6, y_bot),
            text(xs(b1) + 6, y_top + 6, f"Base {fmt(b0, '1')}{NDASH}{fmt(b1, '1')}", "dl2")]
    trows = []
    for i, r in enumerate(RECIPES):
        yc = y_top + row_h * i + row_h / 2
        g = [text(x0 - 10, yc + 4, r, "dl", "end"), line(x0, yc, x1, yc, "grid")]
        vals = [V(f"seeds16.{r}.seed{s}.ho_sr") for s in (0, 1, 2)]
        mean = V(f"seeds16.{r}.mean.ho_sr")
        g.append(line(xs(min(vals)), yc, xs(max(vals)), yc, f"whisk s-{r}"))
        g.append(line(xs(mean), yc - 9, xs(mean), yc + 9, f"tick s-{r}"))
        for s, v in zip((0, 1, 2), vals):
            tip = [fmt(v, "2") + "%", f"{r} · seed {s}",
                   f"harm {F(f'seeds16.{r}.seed{s}.h', '1')}%, source SR "
                   f"{F(f'seeds16.{r}.seed{s}.src_sr', '2')}%"]
            g.append(mark(tip, shape(SHAPE[r], xs(v), yc, f"c-{r}", 4.5), xs(v), yc))
            trows.append([f"{r}, seed {s}", fmt(v, "2"), F(f"seeds16.{r}.seed{s}.r", "1"),
                          F(f"seeds16.{r}.seed{s}.h", "1"), F(f"seeds16.{r}.seed{s}.src_sr", "2")])
        g.append(text(xs(mean), yc - 13, f"mean {fmt(mean, '1')}", "dl2", "middle"))
        body.append(f'<g class="rk rk-{r}">' + "".join(g) + "</g>")
    tab = table(f"Three training seeds at {N16()} source tasks ({F('setup.updates_16_k', 'int')}k "
                "updates): held-out SR (%), rescue and harm as shares of held-out pairs (%), "
                "source SR (%).", ["Recipe and seed", "Held-out SR", "Rescue", "Harm", "Source SR"],
                trows)
    return chart("h_seeds16", W, h,
                 f"Held-out success rate of three training seeds for each recipe at {N16()} "
                 "source tasks.", body, legend(recipe_legend("marker")), tab, toggle=True)


def c_h_cameras():
    """Camera-matched 16-task comparison across all three recipes (incl. new G4 main-camera L3)."""
    x0, x1 = 152, 534
    col_src = 636
    xs = scale(-5, 25, x0, x1)
    y_top = 34
    row_h = 24
    groups = [
        ("L1", "Full action + soft penalty", [
            ("R1_main", "R1 · main camera", "o-L1", "cameras.base.shared.ho"),
            ("L1_dual", "L1 · main + wrist", "b-L1", "cameras.base.shared.ho"),
            ("L1_main", "L1 · main camera only", "t-L1", "cameras.base.L1_main.ho"),
        ]),
        ("L2", "Additive + soft penalty", [
            ("R2_main", "R2 · main camera", "o-L2", "cameras.base.shared.ho"),
            ("L2_dual", "L2 · main + wrist", "b-L2", "cameras.base.shared.ho"),
            ("L2_main", "L2 · main camera only", "t-L2", "cameras.base.L2_main.ho"),
        ]),
        ("L3", "Additive + output bounds", [
            ("R3_main", "R3 · main camera", "o-L3", "cameras.base.shared.ho"),
            ("L3_dual", "L3 · main + wrist", "b-L3", "cameras.base.shared.ho"),
            ("L3_main", "L3 · main camera only", "t-L3", "cameras.base.L3_main.ho"),
        ]),
    ]
    total_h = y_top + len(groups) * (18 + 3 * row_h + 10) + 28
    body = [text(x0, 14, "Held-out gain over matched base (points)", "tl"),
            text(col_src, 14, "Source SR", "tl", "end")]
    marks = []
    trows = []
    y = y_top
    for gi, (r, gtitle, items) in enumerate(groups):
        if gi:
            y += 10
        marks.append(text(2, y + 12, gtitle, "tl"))
        y += 18
        g_el = []
        for ckey, lbl, cls, base_key in items:
            gain = V(f"cameras.{ckey}.gain")
            ho = V(f"cameras.{ckey}.ho_sr")
            src = V(f"cameras.{ckey}.src_sr")
            base_ho = V(base_key)
            yc = y + row_h / 2
            tip = [pts(gain, "+2"), lbl,
                   f"held-out {fmt(ho, '2')}% (base {fmt(base_ho, '2')}%); source SR {fmt(src, '2')}%"]
            x_end = xs(gain)
            lab_x = x_end + 7 if gain >= 0 else x_end - 7
            lab_anchor = "start" if gain >= 0 else "end"
            inner = (text(x0 - 10, yc + 4, lbl, "t ink", "end")
                     + hbar(xs(0), x_end, y + 4, 15, cls)
                     + text(lab_x, yc + 4, fmt(gain, "+1"), "dl", lab_anchor)
                     + text(col_src, yc + 4, fmt(src, "1") + "%", "dl2", "end"))
            g_el.append(mark(tip, inner, hit=rect(0, y, WW, row_h, "hit")))
            trows.append([lbl, fmt(src, "2"), fmt(ho, "2"), fmt(base_ho, "2"), fmt(gain, "+2")])
            y += row_h
        marks.append(f'<g class="rk rk-{r}">' + "".join(g_el) + "</g>")
    body.append(x_axis(xs, [-5, 0, 5, 10, 15, 20, 25], y_top, y, spec="+0"))
    body.append(line(xs(0), y_top, xs(0), y, "axis"))
    body += marks
    leg = legend([("bar", "o-ink", "Readout R (main camera)"),
                  ("bar", "c-ink", "Encoder L (main + wrist)"),
                  ("bar", "t-ink", "Encoder L (main camera only)")])
    tab = table(f"Camera-matched comparison at {N16()} source tasks ({F('setup.updates_16_k', 'int')}k "
                "updates, one training run per row). Each held-out gain is paired with its own "
                "evaluation batch base.",
                ["Recipe and cameras", "Source SR (%)", "Held-out SR (%)", "Base SR (%)", "Gain (pts)"],
                trows)
    return chart("h_cameras", WW, total_h,
                 f"Held-out gain over the matched base for readout, dual-camera encoder, and "
                 f"main-camera-only encoder recipes at {N16()} source tasks.",
                 body, leg, tab, toggle=True)


def c_adapt_critic():
    h = 232
    x0, x1, y0, y1 = 38, AW - 8, 28, 180
    ys = scale(0, 6, y1, y0)
    body = [text(4, 14, "Mean online critic loss (×10⁻⁴)", "tl"),
            y_axis(ys, [0, 2, 4, 6], x0, x1)]
    gw = (x1 - x0) / 3
    trows = []
    for i, r in enumerate(RECIPES):
        cx = x0 + gw * (i + 0.5)
        pre, fresh = V(f"adaptation.{r}.critic_loss.pretrained"), V(f"adaptation.{r}.critic_loss.fresh")
        red = V(f"adaptation.{r}.critic_loss.reduction")
        for v, dx, cls, lbl in ((fresh, -25, f"o-{r}", "fresh"), (pre, 3, f"b-{r}", "pretrained")):
            tip = [f"{fmt(v, '2')} × 10⁻⁴", f"{r} · {lbl} editor",
                   f"pretrained is {fmt(red, '1')}% lower"]
            body.append(mark(tip, vbar(cx + dx, 22, ys(0), ys(v), cls)
                             + text(cx + dx + 11, ys(v) - 5, fmt(v, "2"), "dl2", "middle"),
                             hit=rect(cx + dx - 1, ys(v) - 14, 24, ys(0) - ys(v) + 14, "hit")))
        body.append(text(cx, y1 + 17, r, "dl", "middle"))
        body.append(text(cx, y1 + 32, f"{MINUS}{fmt(red, '1')}%", "t", "middle"))
        trows.append([r, fmt(fresh, "3"), fmt(pre, "3"), f"{MINUS}{fmt(red, '1')}%"])
    body.append(line(x0, ys(0), x1, ys(0), "axis"))
    leg = legend([("bar", "o-ink", "Fresh editor"), ("bar", "c-ink", f"Pretrained {NS()}-task")])
    tab = table("Mean online critic loss (×10⁻⁴) during single-task adaptation; mean "
                f"over two targets and {F('adaptation.seeds', 'int')} seeds.",
                ["Recipe", "Fresh", "Pretrained", "Change"], trows)
    return chart("adapt_critic", AW, h,
                 "Mean online critic loss of fresh and pretrained editors during single-task "
                 "adaptation, by recipe.", body, leg, tab)


def dumbbell_rows(name, w, rows, xs, ticks, title, label, caption, head, leg, h=None,
                  x_label=None):
    y_top, row_h = 34, 42
    h = h or (y_top + row_h * len(rows) + 36 + (16 if x_label else 0))
    x0, x1 = xs(ticks[0]), xs(ticks[-1])
    y_bot = y_top + row_h * len(rows)
    body = [text(4, 14, title, "tl"), x_axis(xs, ticks, y_top - 6, y_bot)]
    trows = []
    for i, (lbl, a, b, col, tip_a, tip_b, end, trow) in enumerate(rows):
        yc = y_top + row_h * i + row_h / 2
        g = [text(x0 - 8, yc + 4, lbl, "dl", "end"),
             line(xs(a), yc, xs(b), yc, f"ln s-{col}")]
        g.append(mark(tip_a, shape("circle", xs(a), yc, f"o-{col}", 4.6), xs(a), yc))
        g.append(mark(tip_b, shape("circle", xs(b), yc, f"c-{col}", 4.6), xs(b), yc))
        right = max(xs(a), xs(b))
        if end:
            g.append(text(right + 10, yc + 4, end, "dl2"))
        body.append("".join(g))
        trows.append(trow)
    if x_label:
        body.append(text((x0 + x1) / 2, y_bot + 34, x_label, "tl", "middle"))
    return chart(name, w, h, label, body, leg, table(caption, head, trows))


def c_adapt_auc():
    xs = scale(80, 92, 38, 250)
    rows = []
    for r in RECIPES:
        pre, fresh = V(f"adaptation.{r}.auc.pretrained"), V(f"adaptation.{r}.auc.fresh")
        d = V(f"adaptation.{r}.auc.diff")
        rows.append((r, fresh, pre, r,
                     [fmt(fresh, "2"), f"{r} · fresh editor", "normalized AUC of target SR"],
                     [fmt(pre, "2"), f"{r} · pretrained editor", f"{fmt(d, '+2')} points to fresh"],
                     fmt(d, "+2"), [r, fmt(fresh, "2"), fmt(pre, "2"), fmt(d, "+2")]))
    leg = legend([("circle", "o-ink", "Fresh editor"), ("circle", "c-ink", "Pretrained editor")])
    return dumbbell_rows(
        "adapt_auc", AW, rows, xs, [80, 84, 88, 92], "AUC of target SR (%)",
        "Normalized area under the target success curve for fresh and pretrained editors, by "
        "recipe.",
        "Normalized area under target SR over the four evaluation checkpoints up to "
        f"{F('adaptation.updates_k', 'int')}k updates (%); mean over two targets and "
        f"{F('adaptation.seeds', 'int')} seeds.",
        ["Recipe", "Fresh", "Pretrained", "Difference (points)"], leg)


def c_adapt_source():
    xs = scale(0, 100, 38, 286)
    rows = []
    for r in RECIPES:
        b, a = V(f"adaptation.{r}.source.before.mean"), V(f"adaptation.{r}.source.after.mean")
        rows.append((r, b, a, r,
                     [fmt(b, "2") + "%", f"{r} · before adaptation",
                      f"range over runs {F(f'adaptation.{r}.source.before.min', '2')}{NDASH}"
                      f"{F(f'adaptation.{r}.source.before.max', '2')}"],
                     [fmt(a, "2") + "%", f"{r} · after {F('adaptation.updates_k', 'int')}k updates",
                      f"range over runs {F(f'adaptation.{r}.source.after.min', '2')}{NDASH}"
                      f"{F(f'adaptation.{r}.source.after.max', '2')}"],
                     "", [r, fmt(b, "2"), fmt(a, "2"),
                          F(f"adaptation.replay.{r}.source.after.mean", "2") if r != "L1" else "not run"]))
    leg = legend([("circle", "o-ink", "Before adaptation"),
                  ("circle", "c-ink", f"After {F('adaptation.updates_k', 'int')}k, no replay"),
                  ("diamond", "c-ink", "With source replay")])
    c = dumbbell_rows(
        "adapt_source", AW, rows, xs, [0, 25, 50, 75, 100],
        f"SR on {F('adaptation.source_tasks', 'int')} source tasks (%)",
        "Source-task success rate of pretrained editors before and after single-task adaptation, "
        "without source replay and (L2, L3) with it, by recipe.",
        f"SR (%) on {F('adaptation.source_tasks', 'int')} source tasks of the pretrained editors "
        "before and after adaptation, without source replay and with half of every batch replayed "
        f"from those tasks; mean over two targets and {F('adaptation.seeds', 'int')} seeds.",
        ["Recipe", "Before", "After, no replay", "After, with replay"], leg)
    extra = []
    for i, r in enumerate(RECIPES):
        if r == "L1":
            continue
        yc = 34 + 42 * i + 21
        v = V(f"adaptation.replay.{r}.source.after.mean")
        tip = [fmt(v, "2") + "%", f"{r} · after {F('adaptation.updates_k', 'int')}k updates with source replay",
               f"range over runs {F(f'adaptation.replay.{r}.source.after.min', '2')}{NDASH}"
               f"{F(f'adaptation.replay.{r}.source.after.max', '2')}"]
        extra.append(mark(tip, shape("diamond", xs(v), yc, f"c-{r}", 4.6), xs(v), yc))
        extra.append(text(xs(v), yc + 20, fmt(v, "1"), "dl", "middle"))
    for i, r in enumerate(RECIPES):
        yc = 34 + 42 * i + 21
        a = V(f"adaptation.{r}.source.after.mean")
        extra.append(text(xs(a), yc - 10, fmt(a, "1"), "dl", "middle"))
        b = V(f"adaptation.{r}.source.before.mean")
        extra.append(text(xs(b), yc - 10, fmt(b, "1"), "dl2", "middle"))
    c["body"] += "".join(extra)
    return c


def c_rt_tasks():
    x0, x1 = 172, 608
    xs = scale(0, 100, x0, x1)
    row_h = 20
    src = V("robotwin.tasks.source")
    oth = V("robotwin.tasks.other")
    order_src = sorted(src, key=lambda k: src[k]["base"] - src[k]["editor"])
    order_oth = sorted(oth, key=lambda k: oth[k]["base"] - oth[k]["editor"])
    blocks = [("Four source tasks", "source", order_src),
              (f"{F('robotwin.other.n_tasks', 'int')} other tasks, no editor update", "other",
               order_oth)]
    total_rows = len(order_src) + len(order_oth)
    y_top = 30
    h = y_top + total_rows * row_h + 2 * 22 + 12 + 44
    body = [text(x0, 14, "SR (%): base → editor", "tl")]
    grid_top = y_top
    y = y_top
    marks = []
    trows = []
    for bi, (title, kind, order) in enumerate(blocks):
        y += 12 if bi else 0
        marks.append(text(2, y + 13, title, "tl"))
        y += 22
        for k in order:
            t = V(f"robotwin.tasks.{kind}.{k}")
            yc = y + row_h / 2
            b, e = t["base"], t["editor"]
            d = e - b
            detail = (f"{fmt(t['rescued'], 'int')} rescued, {fmt(t['harmed'], 'int')} harmed of "
                      f"{F('robotwin.other.scenes', 'int')} pairs" if kind == "other"
                      else f"{F('robotwin.source.scenes', 'int')} paired scenes")
            tip = [pts(d, "+1"), t["name"], f"base {fmt(b, '1')}% → editor {fmt(e, '1')}%; "
                   + detail]
            inner = (text(x0 - 10, yc + 4, t["name"], "t ink", "end")
                     + line(xs(b), yc, xs(e), yc, "ln s-L1")
                     + shape("circle", xs(b), yc, "o-ink", 4.2)
                     + shape("circle", xs(e), yc, "c-L1", 4.2))
            marks.append(mark(tip, inner, hit=rect(0, y, WW, row_h, "hit")))
            trows.append([t["name"] + (" (source)" if kind == "source" else ""),
                          fmt(b, "1"), fmt(e, "1"), fmt(d, "+1")])
            y += row_h
    body.append(x_axis(xs, [0, 25, 50, 75, 100], grid_top, y))
    body += marks
    body.append(text((x0 + x1) / 2, y + 36, "Success rate (%)", "tl", "middle"))
    leg = legend([("circle", "o-ink", "Frozen base"), ("circle", "c-L1", "Four-task editor")])
    tab = table("RoboTwin: SR (%) of the frozen base and the four-task editor per task "
                f"({F('robotwin.source.scenes', 'int')} paired scenes per source task, "
                f"{F('robotwin.other.scenes', 'int')} per other task).",
                ["Task", "Base", "Editor", "Change (points)"], trows)
    return chart("rt_tasks", WW, h,
                 "Success rate of the frozen base and of the four-task RoboTwin editor on each of "
                 "its four source tasks and twelve other tasks.", body, leg, tab)


def c_rt_routing():
    x0, x1 = 158, 578
    xs = scale(0, 100, x0, x1)
    row_h = 22
    models = (("sup", "With task-contrastive routing supervision"),
              ("unsup", "Baseline run without routing supervision"))
    conds = (("original", "Dynamic routing", "c-L1"), ("task_mean", "Fixed task mean", "t-L1"),
             ("swapped", "Swapped task mean", "t-L1"), ("uniform", "Uniform mixture", "t-L1"))
    y_top = 30
    h = y_top + len(models) * (22 + len(conds) * row_h) + 12 + 44
    body = [text(x0, 14, "SR (%) on the four source tasks", "tl")]
    marks, trows = [], []
    y = y_top
    for mi, (mk, mname) in enumerate(models):
        y += 12 if mi else 0
        marks.append(text(2, y + 13, mname, "tl"))
        y += 22
        marks.append(line(x0, y, x0, y + len(conds) * row_h, "axis"))
        for ck, cname, cls in conds:
            v, lo, hi = (V(f"robotwin.routing.{mk}.{ck}.{st}") for st in ("sr", "lo", "hi"))
            yc = y + row_h / 2
            tip = [fmt(v, "2") + "%", f"{cname} · {mname.lower()}",
                   f"{CI()} interval {fmt(lo, '2')}{NDASH}{fmt(hi, '2')}; "
                   f"{F('robotwin.routing.pairs', 'int')} paired episodes"]
            inner = (text(x0 - 10, yc + 4, cname, "t ink", "end") + hbar(x0, xs(v), y + 3, 16, cls)
                     + line(xs(lo), yc, xs(hi), yc, "err-bg") + line(xs(lo), yc, xs(hi), yc, "err")
                     + text(xs(hi) + 8, yc + 4, fmt(v, "1") + "%", "dl"))
            marks.append(mark(tip, inner, hit=rect(0, y, WW, row_h, "hit")))
            trows.append([f"{mname}: {cname.lower()}", fmt(v, "2"),
                          f"{fmt(lo, '2')}{NDASH}{fmt(hi, '2')}"])
            y += row_h
    body.append(x_axis(xs, [0, 25, 50, 75, 100], y_top, y))
    body += marks
    body.append(text((x0 + x1) / 2, y + 36, "Success rate (%)", "tl", "middle"))
    leg = legend([("bar", "c-L1", "Unmodified editor"), ("bar", "t-L1", "Routing replaced"),
                  ("line", "err-key", f"{CI()} interval")])
    tab = table("RoboTwin routing interventions: SR (%) on the four source tasks when the editor's "
                "state-dependent routing is replaced by a fixed mixture "
                f"({F('robotwin.routing.scenarios', 'int')} scenarios per task, "
                f"{F('robotwin.routing.pairs', 'int')} paired episodes per model, each with a newly "
                "recorded unmodified control).", ["Model and routing", "SR (%)", f"{CI()} interval"],
                trows)
    return chart("rt_routing", WW, h,
                 "Success rate on the four RoboTwin source tasks with the editor's dynamic routing "
                 "and with three fixed replacements, for two models.", body, leg, tab)


CHARTS = [c_outcomes_112, c_f1_breadth, c_f1_source_vs_heldout, c_f2_scatter, c_f2_groups,
          c_f3_harm, c_f3_dose_harm, c_f3_dose_sr, c_f3_armgrip, c_f4_controls, c_f4_directions,
          c_h_repeat, c_h_seeds112, c_h_seeds16, c_h_unseen96, c_h_cameras,
          c_adapt_critic, c_adapt_auc, c_adapt_source,
          c_rt_outcomes, c_rt_b4_amp, c_rt_tasks, c_rt_routing]


def render_all(data: dict) -> dict:
    DATA_CACHE.clear()
    DATA_CACHE.update(data)
    out = {}
    for fn in CHARTS:
        c = fn()
        if c["name"] in out:
            die(f"duplicate chart name {c['name']}")
        out[c["name"]] = c
    return out


def svg_open(c: dict, inline: bool) -> str:
    attrs = [f'viewBox="0 0 {c["w"]} {c["h"]}"', f'width="{c["w"]}"', f'height="{c["h"]}"']
    if not inline:
        attrs.insert(0, 'xmlns="http://www.w3.org/2000/svg"')
    attrs += ['class="chart"', 'role="img"', f'aria-label="{esc(c["label"])}"',
              f'data-chart="{c["name"]}"']
    if inline:
        attrs.append('tabindex="0"')
    return "<svg " + " ".join(attrs) + ">"


def standalone_style(colors: dict) -> str:
    """Light-theme values for the stand-alone files; the page supplies its own."""
    c = colors
    rec = {"L1": c["recfull"], "L2": c["recadd"], "L3": c["recbnd"]}
    per = "".join(
        f".c-{r}{{fill:{v}}}.s-{r}{{stroke:{v}}}.t-{r}{{fill:{v};fill-opacity:.38}}"
        f".o-{r}{{fill:#fff;stroke:{v};stroke-width:2}}" for r, v in rec.items())
    return ("<style>"
            "text{font-family:'Inter Variable',Inter,system-ui,-apple-system,sans-serif;font-size:12px;fill:#6b7280}"
            ".tl{fill:#4b5563}.dl{fill:#111827;font-weight:600}.dl2{fill:#4b5563;font-size:11.5px}"
            ".ink{fill:#111827}.in{font-size:11.5px;font-weight:600}"
            ".on-rescue,.on-harm,.on-kept{fill:#fff}.on-fail{fill:#111827}"
            ".grid{stroke:#eceef1;stroke-width:1}.grid.zero,.axis{stroke:#c7cdd4;stroke-width:1}"
            ".ref{stroke:#8c939a;stroke-width:1;stroke-dasharray:3 3}"
            ".band{fill:#8c939a;fill-opacity:.22}.region{fill:#8c939a;fill-opacity:.09}.hit{fill:transparent}"
            ".ln{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}"
            ".ln.thin{stroke-width:1.25}.ln.dot{stroke-dasharray:2 3}.ln.s-L3{stroke-dasharray:6 3}.tick{stroke-width:2}"
            ".whisk{stroke-width:1.5;stroke-opacity:.55}.err{stroke:#111827;stroke-width:1.3}"
            ".err-bg{stroke:#fff;stroke-width:3.6;stroke-linecap:round}"
            ".pt{stroke:#fff;stroke-width:1.6;paint-order:stroke}"
            f".c-rescue{{fill:{c['rescuecol']}}}.c-harm{{fill:{c['harmcol']}}}"
            f".c-kept{{fill:{c['keptcol']}}}.c-fail{{fill:{c['failcol']}}}"
            f".s-rescue{{stroke:{c['rescuecol']}}}.s-harm{{stroke:{c['harmcol']}}}"
            + per +
            f".b-L1{{fill:{rec['L1']}}}.b-L2{{fill:{rec['L2']}}}.b-L3{{fill:url(#hatch-L3) {rec['L3']}}}"
            f".hatch-bg{{fill:{rec['L3']};fill-opacity:.3}}.hatch-fg{{fill:{rec['L3']}}}"
            ".c-ink{fill:#111827}.c-ink3{fill:#6b7280}.s-ink{stroke:#111827}"
            ".t-ink{fill:#111827;fill-opacity:.28}"
            ".o-ink{fill:#fff;stroke:#111827;stroke-width:2}"
            "</style>")


def main():
    data = load_json(DATA / "site_data.json")
    charts = render_all(data)
    out_dir = ASSETS / "charts"
    out_dir.mkdir(parents=True, exist_ok=True)
    style = standalone_style(data["colors"])
    keep = set()
    for name, c in charts.items():
        svg = (svg_open(c, inline=False) + f"<title>{esc(c['label'])}</title>" + style
               + f"<defs>{HATCH}</defs>"
               + f'<rect width="{c["w"]}" height="{c["h"]}" fill="#fff"/>' + c["body"] + "</svg>\n")
        (out_dir / f"{name}.svg").write_text(svg, encoding="utf-8")
        keep.add(f"{name}.svg")
    for old in out_dir.glob("*.svg"):
        if old.name not in keep:
            old.unlink()
    print(f"build_charts: wrote {len(charts)} charts to assets/charts/")


if __name__ == "__main__":
    main()
