#!/usr/bin/env python3
"""Extract every number shown on the page from the paper sources.

Reads the TeX sections, the generated tables and macros, and the JSON result
files of the paper tree (read-only) and writes

    data/site_data.json   nested values used by the page and the charts
    data/ledger.json      "values": for each value the source file, line and
                          matched text (or, for a derived value, the formula and
                          its inputs); "sources": sha256 of every file read

Every pattern must match exactly once. A missing or ambiguous pattern stops the
build with an error, so a change in the paper cannot silently leave a stale
number on the page.

Usage:  python build/build_data.py --paper-root DIR [--check]

The paper root is the directory that holds preamble.tex, sections/ and
research/. It is taken from --paper-root or from the environment variable
SC_PAPER_ROOT; there is no built-in default.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
import zipfile
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA, additions_source, die, dump_json, paper_root  # noqa: E402

EXP = "sections/experiments.tex"
APP_LIBERO = "sections/appendix_libero.tex"
APP_EXP = "sections/appendix_experiments.tex"
VIDEOS_TEX = "sections/supp_videos.tex"
PUB = "research/results/publication/"
SW = PUB + "suppweek/"
RECIPES = ("L1", "L2", "L3")

NUM = r"[-+]?\d[\d,]*(?:\.\d+)?"


# ----------------------------------------------------------------- helpers

def ws(pattern: str) -> str:
    """Let every literal space in a pattern match any TeX whitespace."""
    return re.sub(r" +", r"\\s+", pattern)


def collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def clean(cell: str) -> str:
    """Strip TeX markup from a table cell, keeping its text."""
    s = cell
    for _ in range(3):
        s = re.sub(r"\\(?:best|second|textbf|emph|texttt|hd)\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"\\swatch\{[^{}]*\}", "", s)
    s = re.sub(r"\\(?:hlrow|sumrow)\b", "", s)
    s = re.sub(r"\$\^\{?\\?(?:dagger|circ|star|\*)\}?\$", "", s)
    s = s.replace("$-$", "-").replace("$\\le$", "\u2264").replace("$\\ge$", "\u2265")
    s = s.replace("$\\le ", "\u2264 ").replace("$\\ge ", "\u2265 ")
    s = s.replace("\\%", "%").replace("\\,", "").replace("\\_", "_").replace("~", " ")
    s = s.replace("\\ ", " ").replace("$", "")
    return collapse(s)


def to_num(text: str, where: str):
    s = clean(text).replace(",", "").replace("%", "").strip()
    if s.startswith("+"):
        s = s[1:]
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", s):
        die(f"not a number: {text!r} ({where})")
    return float(s) if "." in s else int(s)


def half_up(value, places: int = 2):
    q = Decimal(1).scaleb(-places)
    return float(Decimal(repr(value)).quantize(q, rounding=ROUND_HALF_UP))


class Builder:
    def __init__(self, root: Path, additions: Path):
        self.root = root
        self.additions = additions
        self._zip = zipfile.ZipFile(additions) if additions.is_file() else None
        self._text: dict[str, str] = {}
        self._json: dict[str, object] = {}
        self.files: dict[str, str] = {}      # source file -> sha256 of the bytes read
        self.data: dict = {}
        self.ledger: dict = {}

    def close(self):
        if self._zip is not None:
            self._zip.close()
            self._zip = None

    # ---- sources
    def text(self, rel: str) -> str:
        if rel not in self._text:
            path = self.root / rel
            if not path.is_file():
                die(f"paper source missing: {rel}")
            raw = path.read_bytes()
            self.files[rel] = hashlib.sha256(raw).hexdigest()
            self._text[rel] = raw.decode("utf-8")
        return self._text[rel]

    def add_text(self, rel: str) -> str:
        key = "additions:" + rel
        if key not in self._text:
            if self._zip is not None:
                try:
                    raw = self._zip.read(rel)
                except KeyError:
                    die(f"additions source missing: {rel}")
            else:
                path = self.additions / rel
                if not path.is_file():
                    die(f"additions source missing: {rel}")
                raw = path.read_bytes()
            self.files[key] = hashlib.sha256(raw).hexdigest()
            self._text[key] = raw.decode("utf-8")
        return self._text[key]

    def add_json(self, rel: str):
        key = "additions:" + rel
        if key not in self._json:
            self._json[key] = json.loads(self.add_text(rel))
        return self._json[key]

    def add_csv_rows(self, rel: str) -> list[dict[str, str]]:
        return list(csv.DictReader(io.StringIO(self.add_text(rel))))

    def json(self, rel: str):
        if rel not in self._json:
            self._json[rel] = json.loads(self.text(rel))
        return self._json[rel]

    # ---- writing
    def set(self, key: str, value, **entry):
        if key in self.ledger:
            die(f"duplicate data key: {key}")
        node = self.data
        parts = key.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
            if not isinstance(node, dict):
                die(f"data key collides with a value: {key}")
        if parts[-1] in node:
            die(f"data key collides with a group: {key}")
        node[parts[-1]] = value
        self.ledger[key] = {"value": value, **entry}

    def derive(self, key: str, value, formula: str, inputs: list[str]):
        for k in inputs:
            if k not in self.ledger:
                die(f"derived value {key} uses unknown input {k}")
        self.set(key, value, derived=formula, inputs=inputs)

    def get(self, key: str):
        if key not in self.ledger:
            die(f"value not set yet: {key}")
        return self.ledger[key]["value"]

    # ---- prose and macros
    def grab(self, rel: str, pattern: str, flags: int = 0):
        """Exactly one regex match in a source file; returns (match, ledger source)."""
        txt = self.text(rel)
        found = list(re.finditer(ws(pattern), txt, flags))
        if len(found) != 1:
            die(f"{rel}: pattern matched {len(found)} times, need exactly 1:\n    {pattern}")
        m = found[0]
        src = {"source": rel, "line": txt.count("\n", 0, m.start()) + 1,
               "match": collapse(m.group(0))}
        return m, src

    def prose(self, rel: str, pattern: str, keys: list[str | None], flags: int = 0):
        """Match a sentence and store one number per capture group (None skips a group)."""
        m, src = self.grab(rel, pattern, flags)
        if len(keys) != len(m.groups()):
            die(f"{rel}: {len(m.groups())} groups but {len(keys)} keys for:\n    {pattern}")
        for key, group in zip(keys, m.groups()):
            if key is not None:
                self.set(key, to_num(group, f"{rel}: {pattern}"), **src)

    def macro_raw(self, rel: str, name: str):
        m, src = self.grab(rel, r"^\\newcommand\{\\%s\}\{(.*)\}[ \t]*$" % re.escape(name),
                           re.M)
        return m.group(1), src

    def macro(self, key: str, rel: str, name: str):
        raw, src = self.macro_raw(rel, name)
        self.set(key, to_num(raw, f"{rel}: \\{name}"), **src)

    def macro_range(self, key: str, rel: str, name: str):
        raw, src = self.macro_raw(rel, name)
        m = re.fullmatch(r"(%s)--(%s)" % (NUM, NUM), clean(raw))
        if not m:
            die(f"{rel}: \\{name} is not a range: {raw!r}")
        self.set(key + ".lo", to_num(m.group(1), name), **src)
        self.set(key + ".hi", to_num(m.group(2), name), **src)

    def macro_ci(self, key: str, rel: str, name: str):
        """A macro of the form [lo, hi]."""
        raw, src = self.macro_raw(rel, name)
        m = re.fullmatch(r"\[(%s), (%s)\]" % (NUM, NUM), clean(raw))
        if not m:
            die(f"{rel}: \\{name} is not an interval: {raw!r}")
        self.set(key + ".lo", to_num(m.group(1), name), **src)
        self.set(key + ".hi", to_num(m.group(2), name), **src)

    # ---- tables
    def rows(self, rel: str, label: str | None = None):
        """Table rows as (line number, raw row, cells) for a whole file or one labelled table."""
        txt = self.text(rel)
        start, end = 0, len(txt)
        if label is not None:
            tag = "\\label{%s}" % label
            if txt.count(tag) != 1:
                die(f"{rel}: label {label} found {txt.count(tag)} times")
            at = txt.index(tag)
            start = txt.rfind("\\begin{table", 0, at)
            end = txt.find("\\end{table", at)
            if start < 0 or end < 0:
                die(f"{rel}: no table around label {label}")
        out = []
        offset = start
        for line in txt[start:end].split("\n"):
            lineno = txt.count("\n", 0, offset) + 1
            offset += len(line) + 1
            body = line.strip()
            if "&" not in body or not body.endswith("\\\\"):
                continue
            body = body[:-2]
            out.append((lineno, collapse(line), [c.strip() for c in body.split("&")]))
        if not out:
            die(f"{rel}: no table rows found" + (f" for {label}" if label else ""))
        return out

    def one_row(self, rows, first_cell: str, rel: str):
        """The single row whose cleaned first cell matches a regex."""
        hits = [r for r in rows if re.fullmatch(first_cell, clean(r[2][0]))]
        if len(hits) != 1:
            die(f"{rel}: {len(hits)} rows match first cell /{first_cell}/, need exactly 1")
        return hits[0]

    def cells(self, prefix: str, rel: str, row, spec: dict[str, int]):
        """Store named numeric cells of one table row."""
        lineno, raw, cells = row
        for name, idx in spec.items():
            if idx >= len(cells):
                die(f"{rel}:{lineno}: row has no cell {idx}: {raw}")
            self.set(f"{prefix}.{name}", to_num(cells[idx], f"{rel}:{lineno}"),
                     source=rel, line=lineno, match=raw)

    def cell_ci(self, prefix: str, rel: str, row, idx: int, names=("d", "lo", "hi")):
        """Store a cell of the form  value [lo, hi]."""
        lineno, raw, cells = row
        m = re.fullmatch(r"(%s) \[(%s), (%s)\]" % (NUM, NUM, NUM), clean(cells[idx]))
        if not m:
            die(f"{rel}:{lineno}: cell {idx} is not 'value [lo, hi]': {cells[idx]!r}")
        for name, group in zip(names, m.groups()):
            self.set(f"{prefix}.{name}", to_num(group, f"{rel}:{lineno}"),
                     source=rel, line=lineno, match=raw)

    def cell_range(self, prefix: str, rel: str, row, idx: int):
        lineno, raw, cells = row
        m = re.fullmatch(r"(%s)--(%s)" % (NUM, NUM), clean(cells[idx]))
        if not m:
            die(f"{rel}:{lineno}: cell {idx} is not a range: {cells[idx]!r}")
        self.set(f"{prefix}.lo", to_num(m.group(1), rel), source=rel, line=lineno, match=raw)
        self.set(f"{prefix}.hi", to_num(m.group(2), rel), source=rel, line=lineno, match=raw)

    def cell_text(self, key: str, rel: str, row, idx: int):
        lineno, raw, cells = row
        self.set(key, clean(cells[idx]), source=rel, line=lineno, match=raw)

    # ---- JSON
    def jnum(self, key: str, rel: str, path: list, places: int | None = None):
        node = self.json(rel)
        for part in path:
            try:
                node = node[part]
            except (KeyError, IndexError, TypeError):
                die(f"{rel}: JSON path not found: {path}")
        if isinstance(node, bool) or not isinstance(node, (int, float)):
            die(f"{rel}: JSON value at {path} is not a number: {node!r}")
        value = node
        entry = {"source": rel, "match": "%s = %s" % (".".join(str(p) for p in path),
                                                    json.dumps(node))}
        if places is not None and isinstance(node, float):
            value = half_up(node, places)
            if value != node:
                entry["note"] = f"rounded half up to {places} decimals"
        self.set(key, value, **entry)

    def jtext(self, key: str, rel: str, path: list):
        node = self.json(rel)
        for part in path:
            try:
                node = node[part]
            except (KeyError, IndexError, TypeError):
                die(f"{rel}: JSON path not found: {path}")
        if not isinstance(node, str):
            die(f"{rel}: JSON value at {path} is not text: {node!r}")
        self.set(key, node, source=rel,
                 match="%s = %s" % (".".join(str(p) for p in path), json.dumps(node)))


# ------------------------------------------------------------------ sections
#
# Preference order for a value: generated table, macro or JSON file first; a
# short number-centred pattern in the TeX prose only where no generated source
# states the value. Ranges and differences that the paper states in prose are
# recomputed here from the table values and recorded as derived.

def dnum(value) -> Decimal:
    return Decimal(str(value))


def plain(d: Decimal):
    """Decimal to int when integral, else float."""
    return int(d) if d == d.to_integral_value() else float(d)


def span(b: Builder, key: str, inputs: list[str], what: str):
    vals = [b.get(k) for k in inputs]
    b.derive(key + ".lo", min(vals), f"lowest {what}", inputs)
    b.derive(key + ".hi", max(vals), f"highest {what}", inputs)


def paper_and_setup(b: Builder):
    m, src = b.grab("preamble.tex", r"^\\newcommand\{\\PaperTitle\}\{(.+)\}[ \t]*$", re.M)
    b.set("paper.title", m.group(1), **src)

    # Colour roles, as defined for the paper's figures.
    for name in ("rescuecol", "harmcol", "keptcol", "failcol"):
        m, src = b.grab("preamble.tex",
                        r"^\\definecolor\{%s\}\{HTML\}\{([0-9A-Fa-f]{6})\}" % name, re.M)
        b.set(f"colors.{name}", "#" + m.group(1).upper(), **src)
    for name in ("recfull", "recadd", "recbnd"):
        m, src = b.grab("preamble.tex",
                        r"^\\definecolor\{%s\}\{rgb\}\{([\d.]+),([\d.]+),([\d.]+)\}" % name, re.M)
        rgb = [int(Decimal(g) * 255 + Decimal("0.5")) for g in m.groups()]
        b.set(f"colors.{name}", "#%02X%02X%02X" % tuple(rgb), **src,
              note="rgb triple converted to hex, rounded half up")

    b.prose(APP_EXP, r"The editor split contains (\d+) source and (\d+) editor-held-out tasks\.",
            ["setup.n_source", "setup.n_heldout"])
    b.prose(APP_EXP, r"supervised training covers (\d+) tasks", ["setup.n_tasks"])
    b.prose(EXP, r"under (\d+) states\$\\times\$(\d+) passes", ["setup.states", "setup.passes"])
    b.prose(EXP, r"(\d+)\\% CIs use", ["setup.ci_level"])
    rows = b.rows(APP_LIBERO, "tab:libero-training-resources")
    b.cells("setup", APP_LIBERO, b.one_row(rows, r"Online actor updates", APP_LIBERO),
            {"updates_112": 3})
    b.prose(EXP, r"\\emph\{16 source tasks; (\d+)k online actor updates\}",
            ["setup.updates_16_k"])
    b.prose(EXP, r"\\emph\{112 source tasks; ([\d.]+)k online actor updates\}",
            ["setup.updates_112_k"])
    b.prose(EXP, r"Source/held-out base SR is ([\d.]+)/([\d.]+)\\% for 16-task runs and "
                 r"([\d.]+)/([\d.]+)\\% for 112-task runs",
            ["base.s16.source", "base.s16.heldout", "base.s112.source", "base.s112.heldout"])
    b.prose(EXP, r"\((\d+)/(\d+) and (\d+)/(\d+) tasks\)",
            ["setup.scenes.s16.covered", "setup.scenes.s16.uncovered",
             "setup.scenes.s112.covered", "setup.scenes.s112.uncovered"])


def recipe_table(b: Builder):
    """Main recipe comparison: six 16-task recipes, three 112-task recipes, repeated base."""
    rows = b.rows(EXP, "tab:learner-classes")
    spec = {"src.sr": 2, "src.r": 3, "src.k": 4, "src.h": 5, "src.f": 6,
            "ho.sr": 7, "ho.r": 8, "ho.k": 9, "ho.h": 10, "ho.f": 11,
            "cov.r": 12, "cov.h": 13, "unc.r": 14, "unc.h": 15}
    lines = b.text(EXP).split("\n")
    seen = {"s16": [], "s112": []}
    for row in rows:
        lineno, raw, cells = row
        # The scale of a row is given by the nearest block heading above it.
        scale = None
        for back in range(lineno - 1, 0, -1):
            head = lines[back - 1]
            if "\\emph{16 source tasks;" in head:
                scale = "s16"
                break
            if "\\emph{112 source tasks;" in head:
                scale = "s112"
                break
            if "\\emph{Actor routing" in head or "\\toprule" in head:
                break
        first = clean(cells[0])
        if scale in ("s16", "s112") and re.fullmatch(r"[RL][123]", first):
            b.cells(f"recipes.{scale}.{first}", EXP, row, spec)
            seen[scale].append(first)
            if scale == "s112":
                b.cell_text(f"recipe_names.{first}", EXP, row, 1)
        elif scale == "s112" and clean(cells[1]) == "Base, repeated run":
            b.cells("recipes.s112.base_repeat", EXP, row,
                    {k: v for k, v in spec.items() if not k.startswith("src.")})
            seen["s112"].append("base_repeat")
    if seen["s16"] != ["R1", "R2", "R3", "L1", "L2", "L3"]:
        die(f"{EXP}: unexpected 16-task rows {seen['s16']}")
    if seen["s112"] != ["L1", "L2", "L3", "base_repeat"]:
        die(f"{EXP}: unexpected 112-task rows {seen['s112']}")
    for scale, ids in (("s16", seen["s16"]), ("s112", RECIPES)):
        for rid in ids:
            for cohort in ("src", "ho"):
                keys = [f"recipes.{scale}.{rid}.{cohort}.{x}" for x in "rkhf"]
                total = sum(dnum(b.get(k)) for k in keys)
                if abs(total - 100) > Decimal("0.25"):
                    die(f"outcome shares of {scale} {rid} {cohort} sum to {total}")

    # Paired gains over the base and pairwise recipe differences on the 18 held-out tasks.
    rel = PUB + "transfer_revision.json"
    paired = ["terminal", "paired_e50x2"]
    for r in ("L1", "L2"):
        b.jnum(f"heldout.gain.{r}.d", rel, paired + [f"{r}_minus_base", "diff_pp"])
        b.jnum(f"heldout.gain.{r}.lo", rel, paired + [f"{r}_minus_base", "ci_low_pp"])
        b.jnum(f"heldout.gain.{r}.hi", rel, paired + [f"{r}_minus_base", "ci_high_pp"])
    b.macro("heldout.gain.L3.d", PUB + "libero_uncertainty_macros.tex", "LiberoHeldoutGain")
    for a, c in (("L1", "L3"), ("L2", "L3"), ("L1", "L2")):
        for stat, name in (("d", "diff_pp"), ("lo", "ci_low_pp"), ("hi", "ci_high_pp")):
            b.jnum(f"heldout.diff.{a}_{c}.{stat}", rel, paired + [f"{a}_minus_{c}", name])

    ho = lambda stat: [f"recipes.s112.{r}.ho.{stat}" for r in RECIPES]  # noqa: E731
    span(b, "heldout.sr_span", ho("sr"), "held-out SR of the three 112-task recipes")
    span(b, "heldout.rescue_span", ho("r"), "rescue share of the three 112-task recipes")
    span(b, "heldout.harm_span", ho("h"), "harm share of the three 112-task recipes")
    span(b, "heldout.soft_harm_span", ho("h")[:2], "harm share of the two soft-penalty recipes")
    srcs = [f"recipes.s112.{r}.src.sr" for r in RECIPES]
    span(b, "heldout.source_sr_span", srcs, "source SR of the three 112-task recipes")
    b.derive("heldout.source_spread",
             plain(max(dnum(b.get(k)) for k in srcs) - min(dnum(b.get(k)) for k in srcs)),
             "highest minus lowest source SR of the three 112-task recipes", srcs)
    b.derive("heldout.heldout_spread",
             plain(max(dnum(b.get(k)) for k in ho("sr")) - min(dnum(b.get(k)) for k in ho("sr"))),
             "highest minus lowest held-out SR of the three 112-task recipes", ho("sr"))
    for r in RECIPES:
        keys = [f"recipes.s112.{r}.ho.r", f"recipes.s112.{r}.ho.h"]
        b.derive(f"recipes.s112.{r}.ho.editor_sr_from_shares",
                 plain(dnum(b.get(f"recipes.s112.{r}.ho.r")) + dnum(b.get(f"recipes.s112.{r}.ho.k"))),
                 "rescued + kept (consistency check against the SR column)",
                 [f"recipes.s112.{r}.ho.r", f"recipes.s112.{r}.ho.k"])
        del keys

    six = seen["s16"]
    span(b, "s16.source_span", [f"recipes.s16.{r}.src.sr" for r in six],
         "source SR of the six 16-task recipes")
    span(b, "s16.heldout_five", [f"recipes.s16.{r}.ho.sr" for r in six if r != "L3"],
         "held-out SR of the five 16-task recipes other than L3")
    span(b, "s16.rescue_cov", [f"recipes.s16.{r}.cov.r" for r in six],
         "rescue share in source-covered scenes, six 16-task recipes")
    span(b, "s16.rescue_unc", [f"recipes.s16.{r}.unc.r" for r in six],
         "rescue share in uncovered scenes, six 16-task recipes")


def breadth(b: Builder):
    """Source breadth for the bounded recipe: 2, 16 and 112 source tasks."""
    rows = b.rows(APP_EXP, "tab:outcome-shares-rates")
    for n in ("2", "16", "112"):
        row = b.one_row(rows, rf"L3, {n} sources", APP_EXP)
        b.set(f"breadth.n{n}.sources", int(n), source=APP_EXP, line=row[0], match=row[1])
        b.cells(f"breadth.n{n}", APP_EXP, row, {"pairs": 1, "base": 2, "r": 3, "h": 4})
    b.derive("setup.pairs_heldout", b.get("breadth.n112.pairs"),
             "paired held-out episodes of a two-pass evaluation", ["breadth.n112.pairs"])
    # Source and held-out SR: two-task editor from its summary table, the others from the
    # recipe comparison.
    rel = PUB + "libero_reference_summary.tex"
    lines = b.text(rel).split("\n")

    def two_task_row(first):
        hits = [r for r in b.rows(rel) if clean(r[2][0]) == first
                and any("\\textit{2 tasks;" in ln for ln in lines[max(0, r[0] - 3):r[0]])]
        if len(hits) != 1:
            die(f"{rel}: row {first!r} of the two-task block not found exactly once")
        return hits[0]

    b.cells("breadth.n2", rel, two_task_row("Source (2)"), {"src_base": 1, "src_sr": 2})
    b.cells("breadth.n2", rel, two_task_row("Editor-held-out (18)"), {"ho_sr": 2, "gain": 3})
    for n, scale in (("16", "s16"), ("112", "s112")):
        for stat, col in (("src_sr", "src.sr"), ("ho_sr", "ho.sr")):
            key = f"recipes.{scale}.L3.{col}"
            b.derive(f"breadth.n{n}.{stat}", b.get(key), "copied from the recipe comparison", [key])
        for stat in ("r", "h"):
            if b.get(f"breadth.n{n}.{stat}") != b.get(f"recipes.{scale}.L3.ho.{stat}"):
                die(f"breadth: {stat} of the {n}-task editor differs between the two tables")
    b.prose(EXP, r"from ([\d.]+) to ([\d.]+) at matched early",
            ["breadth.distance.n2", "breadth.distance.n112"])
    # Two-source soft-penalty recipes (C1: L1 and L2).
    rel_c1 = SW + "completions_twosource.tex"
    b.prose(rel_c1, r"held-out base SR ([\d.]+)\\% for L1, ([\d.]+)\\% for L2 and ([\d.]+)\\% for L3",
            ["breadth.c1.base.L1", "breadth.c1.base.L2", None])
    rec_c1 = None
    seen_c1 = []
    for row in b.rows(rel_c1):
        lineno, raw, cells = row
        if clean(cells[0]) in RECIPES:
            rec_c1 = clean(cells[0])
        if rec_c1 in ("L1", "L2") and clean(cells[1]) == "2":
            b.cells(f"breadth.c1.{rec_c1}", rel_c1, row,
                    {"src_sr": 2, "ho_sr": 3, "r": 4, "h": 5})
            b.cell_ci(f"breadth.c1.{rec_c1}.gain", rel_c1, row, 6)
            seen_c1.append(rec_c1)
    if seen_c1 != ["L1", "L2"]:
        die(f"{rel_c1}: expected two-source L1 and L2 rows, found {seen_c1}")


def what_matters(b: Builder):
    """The paper's summary table: factor, finding (the section column is mapped on the page)."""
    n = 0
    for lineno, raw, cells in b.rows(EXP, "tab:what-matters"):
        if len(cells) != 3 or clean(cells[0]) == "Factor":
            continue
        n += 1
        src = {"source": EXP, "line": lineno, "match": raw}
        m = re.fullmatch(r"\\ref\{(sec:[\w:-]+)\}", cells[2])
        if not m:
            die(f"{EXP}:{lineno}: unexpected section cell {cells[2]!r}")
        b.set(f"what_matters.r{n:02d}.factor", clean(cells[0]), **src)
        b.set(f"what_matters.r{n:02d}.finding", clean(cells[1]), **src)
        b.set(f"what_matters.r{n:02d}.paper_section", m.group(1), **src)
    if n < 6:
        die(f"{EXP}: only {n} rows in the summary table")


def per_task(b: Builder):
    """Per-task held-out success of the base and the three 112-task editors."""
    rows = b.rows(APP_LIBERO, "tab:libero112-per-task")
    ids = []
    for row in rows:
        lineno, raw, cells = row
        m = re.fullmatch(r"(\d+) \((Cov|Unc)\.\)", clean(cells[0]))
        if not m:
            continue
        tid = "t" + m.group(1)
        src = {"source": APP_LIBERO, "line": lineno, "match": raw}
        b.set(f"tasks.{tid}.id", int(m.group(1)), **src)
        b.set(f"tasks.{tid}.scene", "covered" if m.group(2) == "Cov" else "uncovered", **src)
        b.set(f"tasks.{tid}.name", clean(cells[1]), **src)
        b.cells(f"tasks.{tid}", APP_LIBERO, row, {"base": 2, "L1": 3, "L2": 4, "L3": 5})
        for r in RECIPES:
            b.derive(f"tasks.{tid}.gain_{r}",
                     b.get(f"tasks.{tid}.{r}") - b.get(f"tasks.{tid}.base"),
                     "editor SR minus base SR on this task, in points",
                     [f"tasks.{tid}.{r}", f"tasks.{tid}.base"])
        ids.append(tid)
    if len(ids) != b.get("setup.n_heldout"):
        die(f"{APP_LIBERO}: {len(ids)} per-task rows, expected {b.get('setup.n_heldout')}")
    for r in RECIPES:
        keys = [f"tasks.{t}.gain_{r}" for t in ids]
        b.derive(f"heldout.tasks_up.{r}", sum(1 for k in keys if b.get(k) > 0),
                 "number of held-out tasks on which the editor's SR is above the base's", keys)
        b.derive(f"heldout.tasks_down.{r}", sum(1 for k in keys if b.get(k) < 0),
                 "number of held-out tasks on which the editor's SR is below the base's", keys)

    # Grouping of the 18 tasks by base success.
    rows = b.rows(APP_LIBERO, "tab:outcome-by-base")
    groups = [("low", r"\u2264 7% \(.*\)", "\u2264 7%"), ("mid", r"21--34% \(.*\)", "21\u201334%"),
              ("high", r"\u2265 50% \(.*\)", "\u2265 50%")]
    for gid, first, label in groups:
        row = b.one_row(rows, first, APP_LIBERO)
        lineno, raw, cells = row
        src = {"source": APP_LIBERO, "line": lineno, "match": raw}
        listed = re.search(r"\(([\d, ]+)\)", clean(cells[0])).group(1)
        b.set(f"base_groups.{gid}.label", label, **src)
        b.set(f"base_groups.{gid}.n_tasks", len(listed.split(",")), **src,
              note="number of task IDs listed in the row")
        b.cells(f"base_groups.{gid}", APP_LIBERO, row,
                {"pairs": 1, "base": 2, "L1.r": 3, "L1.h": 4, "L1.sr": 5,
                 "L2.r": 6, "L2.h": 7, "L2.sr": 8, "L3.r": 9, "L3.h": 10, "L3.sr": 11})
        for r in RECIPES:
            keys = [f"base_groups.{gid}.{r}.r", f"base_groups.{gid}.{r}.h"]
            b.derive(f"base_groups.{gid}.{r}.gain",
                     plain(dnum(b.get(keys[0])) - dnum(b.get(keys[1]))),
                     "rescue share minus harm share of the group, in points", keys)
        span(b, f"base_groups.{gid}.gain_span",
             [f"base_groups.{gid}.{r}.gain" for r in RECIPES], "gain of the three recipes")
        span(b, f"base_groups.{gid}.harm_span",
             [f"base_groups.{gid}.{r}.h" for r in RECIPES], "harm share of the three recipes")
    b.prose(APP_LIBERO, r"At least one recipe harms (\d+) pairs \(([\d.]+)\\%\), but all three "
                        r"harm only (\d+) \(([\d.]+)\\%\)",
            ["overlap.harm_any.n", "overlap.harm_any.share",
             "overlap.harm_all.n", "overlap.harm_all.share"])


def structure(b: Builder):
    """Correction structure and the first-pass controls (finding 4)."""
    rel = SW + "corrsize_subspace.tex"
    rows = b.rows(rel)
    for r in RECIPES:
        b.cells(f"directions.{r}", rel, b.one_row(rows, r, rel), {"m10": 2, "m_for_85": 5})
    b.prose(rel, r"captures (\d+)\\% of held-out correction variance", ["directions.threshold"])
    b.prose("figures/figure1_evidence/caption.tex",
            r"capture ([\d.]+)\\% of the bounded editor's", ["directions.L3_sampled"])
    b.prose(EXP, r"([\d.]+)\\% of its recorded gripper commands are clipped",
            ["corr_size.gripper_clipped"])

    # Source-mean and frozen-frame controls: difference to the live editor, with intervals.
    rows = b.rows(APP_LIBERO, "tab:libero112-p0-controls")
    b.cells("controls.base_first_pass", APP_LIBERO, b.one_row(rows, r"Base \(5-action\)",
                                                              APP_LIBERO), {"sr": 1})
    for r in ("L1", "L2"):
        b.cells(f"controls.{r}.live_table", APP_LIBERO,
                b.one_row(rows, rf"112-task {r} \(live\)", APP_LIBERO), {"sr": 1, "r": 4, "h": 5})
        row = b.one_row(rows, rf"{r} source-mean .*", APP_LIBERO)
        b.cells(f"controls.{r}.mean_table", APP_LIBERO, row, {"sr": 1, "r": 4, "h": 5})
        b.cell_ci(f"controls.{r}.mean_delta", APP_LIBERO, row, 6)
        row = b.one_row(rows, rf"{r} frozen editor frames", APP_LIBERO)
        b.cells(f"controls.{r}.frozen_table", APP_LIBERO, row, {"sr": 1, "r": 4, "h": 5})
        b.cell_ci(f"controls.{r}.frozen_delta", APP_LIBERO, row, 6)
    rows = b.rows(APP_LIBERO, "tab:libero-controls-summary")

    def summary_row(name):
        hits = [r for r in rows if clean(r[2][0]) == name and clean(r[2][1]).startswith("All 18")]
        if len(hits) != 1:
            die(f"{APP_LIBERO}: control contrast {name!r} (All 18) not found exactly once")
        return hits[0]

    b.cell_ci("controls.L3.live_minus_mean", APP_LIBERO, summary_row("112-L3 - Source-mean"), 3)
    for stat, other in (("d", "d"), ("lo", "hi"), ("hi", "lo")):
        key = f"controls.L3.live_minus_mean.{other}"
        b.derive(f"controls.L3.mean_delta.{stat}", plain(-dnum(b.get(key))),
                 "sign reversed: source-mean minus live", [key])
    b.cell_ci("controls.L3.frozen_delta", APP_LIBERO,
              summary_row("Editor first-frame - 112-L3"), 3)
    b.prose(APP_LIBERO, r"\(18 editor-held-out tasks, (\d+) paired states per condition",
            ["controls.pairs"])
    span(b, "controls.soft_mean_drop", ["controls.L1.mean_delta.d", "controls.L2.mean_delta.d"],
         "difference to live under the source-mean correction, L1 and L2")
    span(b, "controls.frozen_drop", [f"controls.{r}.frozen_delta.d" for r in RECIPES],
         "difference to live under frozen editor frames, three recipes")

    # Success and pointwise 95% intervals of every condition, as plotted in the paper.
    rel = PUB + "transfer_revision.json"
    for name, key in (("base5", "controls.base"), ("base8", "controls.base_native")):
        for stat in ("mean", "low", "high"):
            b.jnum(f"{key}.{stat}", rel, ["controls", name, stat], places=2)
    for r in RECIPES:
        for cond, name in (("live", "live"), ("source_mean", "mean"), ("visual_frozen", "frozen")):
            for stat in ("mean", "low", "high"):
                b.jnum(f"controls.{r}.{name}.{stat}", rel,
                       ["controls", f"{r}_{cond}", stat], places=2)
        b.jnum(f"controls.{r}.above_native", rel,
               ["terminal", "pass0_vs_controls", "editors", r, "vs_base_k8_all18", "diff_pp"])
    span(b, "controls.above_native_span", [f"controls.{r}.above_native" for r in RECIPES],
         "difference to the base's native eight-action execution, three recipes")

    # Replacing the editor's instruction.
    rel = SW + "completions_instruction.tex"
    rows = b.rows(rel)
    for r in RECIPES:
        b.cell_ci(f"controls.{r}.instruction_delta", rel, b.one_row(rows, r, rel), 3)
    keys = [f"controls.{r}.instruction_delta.d" for r in RECIPES]
    b.derive("controls.instruction_max", max(abs(b.get(k)) for k in keys),
             "largest absolute SR change when the editor's instruction is replaced", keys)


def correction_size(b: Builder):
    """Correction scaling at inference (finding 3)."""
    # The separate bounded-recipe batch. Main-text Table 3 (rows generated into table3_scaling_body.tex)
    # carries its SR and harm share in the last two columns; the rescue share, the number of pairs and the
    # base SR are in the appendix table of shares and rates; the paired SR differences are in the result file.
    body = SW + "table3_scaling_body.tex"
    rows3 = b.rows(body)
    shares = b.rows(APP_EXP, "tab:outcome-shares-rates")
    ref = PUB + "followup_4090.json"
    for key, scale, name, cohort in (("original", r"1", "Original", None),
                                     ("half", r"0\.5", "Half scale", "l2_half"),
                                     ("quarter", r"0\.25", "Quarter scale", "l2_quarter"),
                                     ("no_gripper", r"1, no grip\.", "No gripper correction", "l2_zero_gripper")):
        b.cells(f"scaling.{key}", body, b.one_row(rows3, scale, body), {"sr": 7, "h": 8})
        b.cells(f"scaling.{key}", APP_EXP, b.one_row(shares, name, APP_EXP), {"r": 3})
        if cohort:
            b.jnum(f"scaling.{key}.d_sr", ref,
                   ["l2_interventions", "cohorts", "all18", cohort, "vs_samehost_orig_l3_pp", "diff_pp"], places=2)
    b.cells("scaling", APP_EXP, b.one_row(shares, "Original", APP_EXP), {"pairs": 1, "base": 2})

    rel = SW + "corrsize_dose.tex"
    recipe = None
    n = 0
    for row in b.rows(rel):
        lineno, raw, cells = row
        first = clean(cells[0])
        m = re.match(r"(L[123]) ", first)
        if m:
            recipe = m.group(1)
        elif first != "":
            continue
        if recipe is None or len(cells) != 12:
            continue
        alpha = clean(cells[1])
        if not re.fullmatch(r"[01]\.\d\d", alpha):
            die(f"{rel}:{lineno}: unexpected scale {alpha!r}")
        prefix = f"dose.{recipe}.a{alpha.replace('.', '')}"
        b.set(prefix + ".alpha", float(alpha), source=rel, line=lineno, match=raw)
        b.cells(prefix, rel, row, {"b1.sr": 2, "b1.r": 3, "b1.h": 4, "b1.gain": 5,
                                   "b2.sr": 7, "b2.r": 8, "b2.h": 9, "b2.gain": 10})
        for stat in ("sr", "h", "r"):
            keys = [f"{prefix}.b1.{stat}", f"{prefix}.b2.{stat}"]
            b.derive(f"{prefix}.mean.{stat}",
                     float((dnum(b.get(keys[0])) + dnum(b.get(keys[1]))) / 2),
                     "mean of the two batches (marker position; not printed as a result)", keys)
        n += 1
    if n != 12:
        die(f"{rel}: expected 12 dose rows, found {n}")
    num = SW + "corrsize_numbers.tex"
    b.macro("dose.base.b1", num, "SWcsBaseOne")
    b.macro("dose.base.b2", num, "SWcsBaseTwo")
    b.prose(rel, r"first pass, (\d+) pairs per cell", ["dose.pairs"])
    for r, name in zip(RECIPES, ("Lone", "Ltwo", "Lthree")):
        b.macro(f"dose.{r}.half_pooled.d", num, f"SWcsHalfPooled{name}")
        b.macro_ci(f"dose.{r}.half_pooled", num, f"SWcsHalfPooledCI{name}")
        b.macro(f"dose.{r}.harm_drop", num, f"SWcsHarmDrop{name}")
        b.macro(f"dose.{r}.rescue_change", num, f"SWcsRescueChange{name}")
        b.macro(f"dose.{r}.arm_norm", num, f"SWcsArmNorm{name}")

    rel = SW + "armgrip_table.tex"
    rows = b.rows(rel)
    for key, first in (("full", "Full scale"), ("both", "Both halved"),
                       ("arm", "Arm halved"), ("gripper", "Gripper halved")):
        b.cells(f"armgrip.{key}", rel, b.one_row(rows, first, rel), {"sr": 3})
    b.cell_ci("armgrip.arm.diff", rel, b.one_row(rows, r"Arm halved - full", rel), 1)
    b.cell_ci("armgrip.gripper.diff", rel, b.one_row(rows, r"Gripper halved - full", rel), 1)
    b.cell_ci("armgrip.both.diff", rel, b.one_row(rows, r"Both halved - full", rel), 1)
    b.prose(rel, r"the first (\d+) initial states of each task, one pass: (\d+) episodes per "
                 r"condition", ["armgrip.states", "armgrip.episodes"])


def robustness(b: Builder):
    mac = SW + "robustness_macros.tex"
    rel = SW + "robustness_repeat.tex"
    rows = b.rows(rel)
    for key, first in (("base12", "Base, runs 1 and 2"), ("base13", "Base, runs 1 and 3"),
                       ("base23", "Base, runs 2 and 3")):
        row = b.one_row(rows, first, rel)
        b.cells(f"repeat.{key}", rel, row,
                {"first": 1, "second": 2, "r": 4, "h": 5, "differs": 6,
                 "differs_cov": 7, "differs_unc": 8})
        b.cell_ci(f"repeat.{key}.delta", rel, row, 3)
    for r in RECIPES:
        row = b.one_row(rows, rf"{r}, runs 1 and 2", rel)
        b.cells(f"repeat.{r}", rel, row,
                {"first": 1, "second": 2, "r": 4, "h": 5, "differs": 6})
        b.cell_ci(f"repeat.{r}.delta", rel, row, 3)
        b.cell_range(f"repeat.{r}.gain6", rel, row, 9)
        b.cell_range(f"repeat.{r}.rescue6", rel, row, 10)
        b.cell_range(f"repeat.{r}.harm6", rel, row, 11)
    b.macro_range("repeat.base_harm", mac, "swrBaseNullHarm")
    b.macro_range("repeat.base_rescue", mac, "swrBaseNullRescue")
    b.macro("repeat.min_recipe_gap", mac, "swrMinRecipeGap")
    b.macro("repeat.max_base_delta", mac, "swrMaxBaseDelta")
    b.macro("repeat.paper_repro_max", mac, "swrPaperReproMax")
    b.macro_range("repeat.len_differs", mac, "swrBaseLenDiffer")
    b.macro("repeat.other_tasks", mac, "swrOtherTasks")
    raw, src = b.macro_raw(mac, "swrHotShare")
    m = re.fullmatch(r"(\d+) of the (\d+)", raw)
    if not m:
        die(f"{mac}: swrHotShare has an unexpected form: {raw!r}")
    b.set("repeat.hot.n", int(m.group(1)), **src)
    b.set("repeat.hot.of", int(m.group(2)), **src)
    b.prose(rel, r"\(([\d,]+) pairs per comparison", ["repeat.pairs"])

    # Three training seeds at 16 source tasks.
    rel = SW + "robustness_seeds16.tex"
    recipe = None
    seen = []
    for row in b.rows(rel):
        lineno, raw, cells = row
        if clean(cells[0]) in RECIPES:
            recipe = clean(cells[0])
        tag = clean(cells[1])
        if recipe is None or tag not in ("0", "1", "2", "Mean", "SD"):
            continue
        name = {"Mean": "mean", "SD": "sd"}.get(tag, "seed" + tag)
        b.cells(f"seeds16.{recipe}.{name}", rel, row,
                {"src_sr": 2, "ho_sr": 3, "r": 4, "h": 5, "cov_sr": 6, "unc_sr": 7})
        seen.append(f"{recipe}.{name}")
    if len(seen) != 15:
        die(f"{rel}: expected 15 rows, found {len(seen)}")
    b.prose(rel, r"Held-out base SR is ([\d.]+)\\% for seed 0 and ([\d.]+)\\% for seeds 1 and 2",
            ["seeds16.base.seed0", "seeds16.base.seed12"])
    b.macro_range("seeds16.bounded_sr", mac, "swrSxBoundSr")
    b.macro_range("seeds16.soft_sr", mac, "swrSxSoftSr")
    b.macro_range("seeds16.bounded_harm", mac, "swrSxBoundHarm")
    b.macro_range("seeds16.soft_harm", mac, "swrSxSoftHarm")
    b.macro("seeds16.l2_minus_l1.mean", mac, "swrSxLtwoMinusLone")
    b.macro("seeds16.l2_minus_l1.lo", mac, "swrSxLtwoMinusLoneLo")
    b.macro("seeds16.l2_minus_l1.hi", mac, "swrSxLtwoMinusLoneHi")

    # Three training seeds at 112 source tasks (121.25k matched batch).
    rel = SW + "robustness_seeds112.tex"
    recipe = None
    n = 0
    for row in b.rows(rel):
        lineno, raw, cells = row
        if clean(cells[0]) in RECIPES:
            recipe = clean(cells[0])
        if recipe is None or clean(cells[1]) not in ("0", "1", "2"):
            continue
        seed = clean(cells[1])
        upd = clean(cells[2])
        if not re.fullmatch(r"[\d.]+k", upd):
            die(f"{rel}:{lineno}: unexpected update count {upd!r}")
        prefix = f"seeds112.{recipe}.seed{seed}.u{upd[:-1].replace('.', '_')}"
        b.set(prefix + ".updates_k", float(upd[:-1]), source=rel, line=lineno, match=raw)
        b.cells(prefix, rel, row, {"sr": 3, "r": 4, "h": 5, "cov_sr": 7, "unc_sr": 8})
        b.cell_ci(prefix + ".gain", rel, row, 6)
        if seed == "2":
            b.cells(prefix, rel, row, {"src_sr": 9})
        if seed in ("1", "2"):
            b.cell_ci(f"seeds112.{recipe}.seed{seed}_diff", rel, row, 10)
        n += 1
    if n != 9:
        die(f"{rel}: expected 9 rows, found {n}")
    b.prose(rel, r"1,800 pairs per row, base SR ([\d.]+)\\% \(([\d.]+)\\% on the 10 "
                 r"tasks in source-covered scenes, ([\d.]+)\\% on the 8 in uncovered scenes\)",
            ["seeds112.base.sr", "seeds112.base.cov", "seeds112.base.unc"])
    b.macro("seeds112.l3_abs_diff", mac, "swrHxSeedAbsThree")
    b.macro("seeds112.three.l3_s1_abs_diff", mac, "swrThreeAbsLthreeOne")
    b.macro("seeds112.three.l3_s2_diff", mac, "swrThreeDiffLthreeTwo")
    span(b, "seeds112.three.l2_sr",
         ["seeds112.L2.seed0.u121_54.sr", "seeds112.L2.seed1.u121_25.sr", "seeds112.L2.seed2.u121_25.sr"],
         "held-out SR of L2 across three training seeds at 121k updates")
    for seed, tag in (("seed0", "Zero"), ("seed1", "One")):
        b.macro(f"seeds112.l2_minus_l3.{seed}.d", mac, f"swrHxTwoMinusThree{tag}")
        b.macro_ci(f"seeds112.l2_minus_l3.{seed}", mac, f"swrHxTwoMinusThree{tag}Ci")
        b.macro(f"seeds112.l2_minus_l1.{seed}.d", mac, f"swrHxTwoMinusOne{tag}")
        b.macro_ci(f"seeds112.l2_minus_l1.{seed}", mac, f"swrHxTwoMinusOne{tag}Ci")
    for seed, tag in (("seed0", "Zero"), ("seed1", "One"), ("seed2", "Two")):
        b.macro(f"seeds112.three.l2_minus_l3.{seed}.d", mac, f"swrThreeTwoMinusThree{tag}")
        b.macro_ci(f"seeds112.three.l2_minus_l3.{seed}", mac, f"swrThreeTwoMinusThree{tag}Ci")
        b.macro(f"seeds112.three.l1_minus_l3.{seed}.d", mac, f"swrThreeOneMinusThree{tag}")
        b.macro_ci(f"seeds112.three.l1_minus_l3.{seed}", mac, f"swrThreeOneMinusThree{tag}Ci")
        b.macro(f"seeds112.three.l2_minus_l1.{seed}.d", mac, f"swrThreeTwoMinusOne{tag}")
        b.macro_ci(f"seeds112.three.l2_minus_l1.{seed}", mac, f"swrThreeTwoMinusOne{tag}Ci")


def evolution(b: Builder):
    """Held-out success across training for the three 112-task recipes (three seeds)."""
    rel = SW + "completions_evolution.tex"
    m, src = b.grab(rel, r"\(L1: ([\d.]+)k, ([\d.]+)k, ([\d.]+)k; L2: ([\d.]+)k, ([\d.]+)k, "
                         r"([\d.]+)k\)")
    nearest = {"L1": dict(zip(("121", "241", "352"), m.groups()[:3])),
               "L2": dict(zip(("121", "241", "352"), m.groups()[3:]))}
    m2, src2 = b.grab(rel, r"two further runs per recipe to ([\d.]+)k updates")
    txt = b.text(rel)
    if txt.count("\\emph{Second training seed}") != 1 or txt.count("\\emph{Third training seed}") != 1:
        die(f"{rel}: second/third-seed block headings not found exactly once")
    split1 = txt.count("\n", 0, txt.index("\\emph{Second training seed}")) + 1
    split2 = txt.count("\n", 0, txt.index("\\emph{Third training seed}")) + 1
    n = 0
    for row in b.rows(rel):
        lineno, raw, cells = row
        label = clean(cells[0])
        if not re.fullmatch(r"[\d.]+", label) or len(cells) != 9:
            continue
        seed = "seed0" if lineno < split1 else ("seed1" if lineno < split2 else "seed2")
        for r, off in (("L1", 1), ("L2", 5)):
            prefix = f"evolution.{r}.{seed}.p{label.replace('.', '_')}"
            if seed in ("seed1", "seed2") and label == "121":
                b.set(prefix + ".updates_k", float(m2.group(1)),
                      **dict(src2, note=f"row 121 of {seed}: the run stops here"))
            elif label in nearest[r]:
                b.set(prefix + ".updates_k", float(nearest[r][label]),
                      **dict(src, note=f"row {label}: nearest saved snapshot of {r}"))
            else:
                b.set(prefix + ".updates_k", float(label), source=rel, line=lineno, match=raw)
            spec = {"sr": off, "r": off + 1, "h": off + 2}
            if clean(cells[off + 3]) not in ("--", ""):
                spec["src_sr"] = off + 3
            b.cells(prefix, rel, row, spec)
        n += 1
    if n != 12:
        die(f"{rel}: expected 12 snapshot rows, found {n}")
    b.prose(rel, r"1,800 pairs per snapshot, base SR ([\d.]+)\\%", ["evolution.base"])
    rel = PUB + "libero_evolution_checkpoints.tex"
    n = 0
    for row in b.rows(rel):
        lineno, raw, cells = row
        label = clean(cells[0])
        if not re.fullmatch(r"[\d.]+", label):
            continue
        prefix = f"evolution.L3.seed0.p{label.replace('.', '_')}"
        b.set(prefix + ".updates_k", float(label), source=rel, line=lineno, match=raw)
        b.cell_ci(prefix, rel, row, 2, names=("sr", "lo", "hi"))
        n += 1
    if n != 6:
        die(f"{rel}: expected 6 checkpoint rows, found {n}")
    # Second seed of the bounded recipe, from the completions ledger (A2b evolution).
    c_led = SW + "completions_ledger.json"
    c_map = {x["key"]: x["value"] for x in b.json(c_led)["numbers"]}
    for upd, tag in ((1.25, "1250"), (51.25, "51250"), (121.25, "121250")):
        k = f"evolution_L3_seed1_{tag}_heldout_sr"
        if k not in c_map:
            die(f"{c_led}: missing {k}")
        p = f"evolution.L3.seed1.p{str(upd).replace('.', '_')}"
        src_l = {"source": c_led, "match": f"{k}={c_map[k]}"}
        b.set(p + ".updates_k", upd, **src_l)
        b.set(p + ".sr", to_num(str(c_map[k]), f"{c_led}:{k}"), **src_l)
    # Third seed of the bounded recipe, from heldout_evolution.json (A2b' evolution).
    h_evo = SW + "heldout_evolution.json"
    s2_l3 = b.json(h_evo)["seed2_snapshots"]["L3"]
    if len(s2_l3) != 3:
        die(f"{h_evo}: expected 3 seed2_snapshots.L3 points, found {len(s2_l3)}")
    for pt in s2_l3:
        upd = round(pt["updates"] / 1000.0, 2)
        p = f"evolution.L3.seed2.p{str(upd).replace('.', '_')}"
        src_h = {"source": h_evo, "match": f"seed2_snapshots.L3[{pt['updates']}]"}
        b.set(p + ".updates_k", upd, **src_h)
        b.set(p + ".sr", half_up(100 * pt["sr"], 2), **src_h)


def unseen96(b: Builder):
    num = SW + "unseen96_numbers.tex"
    rel = SW + "unseen96_cohorts.tex"
    txt = b.text(rel)
    if txt.count("\\emph{18 held-out tasks, separate batch") != 1:
        die(f"{rel}: 18-task block heading not found exactly once")
    split_at = txt.count("\n", 0, txt.index("\\emph{18 held-out tasks, separate batch")) + 1
    n = 0
    for row in b.rows(rel):
        lineno, raw, cells = row
        r = clean(cells[0])
        if r not in RECIPES:
            continue
        cohort = "t96" if lineno < split_at else "t18"
        b.cells(f"unseen96.{cohort}.{r}", rel, row, {"sr": 1, "r": 2, "k": 3, "h": 4, "f": 5})
        b.cell_ci(f"unseen96.{cohort}.{r}.gain", rel, row, 6)
        n += 1
    if n != 6:
        die(f"{rel}: expected 6 rows, found {n}")
    b.macro("unseen96.t96.base", num, "UnsBase")
    b.macro("unseen96.t18.base", num, "UnsHeldBase")
    b.macro("unseen96.t96.pairs", num, "UnsPairs")
    rel = SW + "unseen96_breakdown.tex"
    rows = b.rows(rel)
    groups = [("all", r"All 96 tasks", "All 96 tasks"),
              ("covered", r"Source-covered scenes", "Source-covered scenes"),
              ("uncovered", r"Uncovered scenes", "Uncovered scenes"),
              ("low", r"Base SR \u226410%", "\u2264 10%"),
              ("mid", r"Base SR 10--50%", "10\u201350%"),
              ("high", r"Base SR \u226550%", "\u2265 50%"),
              ("libero90", r"LIBERO-90", "LIBERO-90"),
              ("libero10", r"LIBERO-10 \(long horizon\)", "LIBERO-10 (long horizon)"),
              ("spatial", r"LIBERO-Spatial", "LIBERO-Spatial"),
              ("object", r"LIBERO-Object", "LIBERO-Object"),
              ("goal", r"LIBERO-Goal", "LIBERO-Goal")]
    for gid, first, label in groups:
        row = b.one_row(rows, first, rel)
        b.set(f"unseen96.groups.{gid}.label", label, source=rel, line=row[0], match=row[1])
        b.cells(f"unseen96.groups.{gid}", rel, row,
                {"n_tasks": 1, "base": 2,
                 "L1.sr": 3, "L1.r": 4, "L1.h": 5, "L1.gain": 6,
                 "L2.sr": 7, "L2.r": 8, "L2.h": 9, "L2.gain": 10,
                 "L3.sr": 11, "L3.r": 12, "L3.h": 13, "L3.gain": 14})
    for r, s in zip(RECIPES, ("La", "Lb", "Lc")):
        b.macro(f"unseen96.rho.{r}.d", num, f"UnsRho{s}")
        b.macro_ci(f"unseen96.rho.{r}", num, f"UnsRhoCI{s}")
        b.macro(f"unseen96.near.{r}", num, f"UnsNear{s}")
        b.macro(f"unseen96.far.{r}", num, f"UnsFar{s}")
        b.macro(f"unseen96.tasks_down.{r}", num, f"UnsNeg{s}")
    keys = []
    gaps = []
    for r in RECIPES:
        pair = [f"unseen96.groups.covered.{r}.r", f"unseen96.groups.uncovered.{r}.r"]
        keys += pair
        gaps.append(abs(dnum(b.get(pair[0])) - dnum(b.get(pair[1]))))
    b.derive("unseen96.scene_gap_max", plain(max(gaps)),
             "largest absolute difference between rescue in source-covered and uncovered "
             "scenes, three recipes", keys)


def adaptation(b: Builder):
    rel = SW + "fig5_numbers.json"
    rel2 = PUB + "libero_adaptation_three_recipes.json"
    for r in RECIPES:
        base = ["three_seeds", r]
        for init in ("pretrained", "fresh"):
            b.jnum(f"adaptation.{r}.auc.{init}", rel,
                   base + ["auc_pct", "mean_over_targets", init])
            b.jnum(f"adaptation.{r}.critic_loss.{init}", rel,
                   base + ["critic_loss", "mean_over_targets", f"{init}_e-4"])
            for step in ("0", "5000", "10000", "25000"):
                b.jnum(f"adaptation.{r}.target.{init}.u{step}", rel2,
                       [r, "target_sr_pct", init, step], places=2)
        b.jnum(f"adaptation.{r}.auc.diff", rel,
               base + ["auc_pct", "mean_over_targets", "difference"])
        b.jnum(f"adaptation.{r}.critic_loss.reduction", rel,
               base + ["critic_loss", "mean_over_targets", "relative_reduction_pct"])
        b.jtext(f"adaptation.{r}.critic_loss.pairs_lower", rel,
                base + ["critic_loss", "seed_matched_pairs_pretrained_lower"])
        for when in ("before", "after"):
            for stat in ("mean", "min", "max"):
                b.jnum(f"adaptation.{r}.source.{when}.{stat}", rel,
                       base + ["source_sr_pct_pretrained", when, stat])
        b.jnum(f"adaptation.{r}.source.ratio_to_L3", rel,
               base + ["source_sr_pct_pretrained", "ratio_of_after_mean_to_L3"])
    across = ["three_seeds", "across_recipes"]
    b.jnum("adaptation.critic_reduction.lo", rel,
           across + ["critic_loss_reduction_pct_range_by_recipe", 0])
    b.jnum("adaptation.critic_reduction.hi", rel,
           across + ["critic_loss_reduction_pct_range_by_recipe", 1])
    b.jtext("adaptation.critic_pairs_lower", rel, across + ["seed_matched_pairs_pretrained_lower"])
    b.jtext("adaptation.soft_runs_90_at_5k", rel, across + ["runs_at_or_above_90_at_5k_L1_L2"])
    span(b, "adaptation.soft_auc_diff", ["adaptation.L1.auc.diff", "adaptation.L2.auc.diff"],
         "AUC difference (pretrained minus fresh), L1 and L2")
    span(b, "adaptation.soft_source_after",
         ["adaptation.L1.source.after.mean", "adaptation.L2.source.after.mean"],
         "source SR after adaptation, L1 and L2")
    span(b, "adaptation.soft_ratio",
         ["adaptation.L1.source.ratio_to_L3", "adaptation.L2.source.ratio_to_L3"],
         "ratio of retained source SR to that of L3, L1 and L2")
    span(b, "adaptation.source_before",
         [f"adaptation.{r}.source.before.mean" for r in RECIPES],
         "mean source SR before adaptation, three recipes")
    b.prose(SW + "adaptation_seeds.tex", r"equal-task mean over (\d+) source tasks",
            ["adaptation.source_tasks"])
    b.prose(SW + "adaptation_seeds.tex", r"at 0, 5k, 10k and (\d+)k online actor updates",
            ["adaptation.updates_k"])
    b.prose("sections/supp_adaptation.tex",
            r"At (\d+)k updates, (\d+) of the (\d+) runs are at (\d+)\\% target SR or above",
            ["adaptation.soft_fast.updates_k", "adaptation.soft_fast.n",
             "adaptation.soft_fast.of", "adaptation.soft_fast.sr"])
    seeds = b.json(rel)["three_seeds"]["L1"]["seeds"]
    b.set("adaptation.seeds", len(seeds), source=rel,
          match="three_seeds.L1.seeds = %s" % json.dumps(seeds), note="number of seeds listed")
    # Third target (Task 39) completed for L1 and L2 (three seeds) alongside L3.
    rel_t39 = SW + "adaptation_target39.tex"
    rec_t39 = None
    seen_t39 = 0
    for row in b.rows(rel_t39):
        lineno, raw, cells = row
        if clean(cells[0]) in RECIPES:
            rec_t39 = clean(cells[0])
        init = clean(cells[1]).lower()
        if rec_t39 is None or init not in ("pretrained", "fresh"):
            continue
        b.cells(f"adaptation.t39.{rec_t39}.{init}", rel_t39, row,
                {"auc4": 6, "critic_loss": 8})
        seen_t39 += 1
    if seen_t39 != 6:
        die(f"{rel_t39}: expected 6 rows, found {seen_t39}")
    for r in ("L1", "L2", "L3"):
        pre_k = f"adaptation.t39.{r}.pretrained.critic_loss"
        fr_k = f"adaptation.t39.{r}.fresh.critic_loss"
        red = half_up(100 * (b.get(fr_k) - b.get(pre_k)) / b.get(fr_k), 1)
        b.derive(f"adaptation.t39.{r}.critic_loss.reduction", red,
                 "100 * (fresh - pretrained) / fresh, percent", [fr_k, pre_k])
    span(b, "adaptation.t39.critic_reduction",
         [f"adaptation.t39.{r}.critic_loss.reduction" for r in RECIPES],
         "relative online critic-loss reduction across three recipes on the third target")


def robotwin(b: Builder):
    rel = PUB + "transfer_revision.json"
    rows = b.rows(APP_EXP, "tab:outcome-shares-rates")
    b.cells("robotwin.source", APP_EXP, b.one_row(rows, r"S4 editor, four source tasks", APP_EXP),
            {"pairs": 1, "base": 2, "r": 3, "h": 4})
    b.cells("robotwin.other", APP_EXP, b.one_row(rows, r"S4 editor, 12 other tasks", APP_EXP),
            {"pairs": 1, "base": 2, "r": 3, "h": 4})
    pol = ["robotwin", "expanded", "policies", "task_id_b_1490000"]
    b.jnum("robotwin.source.editor", rel, pol + ["macro_sr_pct"])
    b.jnum("robotwin.source.gain.d", rel, pol + ["vs_matched_base", "diff_pp"])
    b.jnum("robotwin.source.gain.lo", rel, pol + ["vs_matched_base", "ci_low_pp"])
    b.jnum("robotwin.source.gain.hi", rel, pol + ["vs_matched_base", "ci_high_pp"])
    held = ["robotwin", "heldout"]
    b.jnum("robotwin.other.n_tasks", rel, held + ["tasks_count"])
    b.jnum("robotwin.other.editor", rel, held + ["editor_sr_pct"])
    b.jnum("robotwin.other.gain.d", rel, held + ["diff_pp"])
    b.jnum("robotwin.other.gain.lo", rel, held + ["ci_low_pp"])
    b.jnum("robotwin.other.gain.hi", rel, held + ["ci_high_pp"])
    # Kept and still-failed shares from the pair counts.
    b.jnum("robotwin.source.counts.pairs", rel,
           ["robotwin", "expanded", "policies", "matched_base", "cases"])
    b.jnum("robotwin.source.counts.base_ok", rel,
           ["robotwin", "expanded", "policies", "matched_base", "successes"])
    b.jnum("robotwin.source.counts.rescued", rel, pol + ["vs_matched_base", "rescues"])
    b.jnum("robotwin.source.counts.harmed", rel, pol + ["vs_matched_base", "harms"])
    b.jnum("robotwin.other.counts.pairs", rel, held + ["episodes_per_policy"])
    b.jnum("robotwin.other.counts.base_ok", rel, held + ["base_successes"])
    b.jnum("robotwin.other.counts.rescued", rel, held + ["rescues"])
    b.jnum("robotwin.other.counts.harmed", rel, held + ["harms"])
    for cohort in ("source", "other"):
        c = {k: b.get(f"robotwin.{cohort}.counts.{k}")
             for k in ("pairs", "base_ok", "rescued", "harmed")}
        keys = [f"robotwin.{cohort}.counts.{k}" for k in c]
        if c["pairs"] != b.get(f"robotwin.{cohort}.pairs"):
            die(f"RoboTwin {cohort}: pair counts disagree between the table and the JSON file")
        kept = c["base_ok"] - c["harmed"]
        failed = c["pairs"] - c["base_ok"] - c["rescued"]
        b.derive(f"robotwin.{cohort}.k", half_up(100 * kept / c["pairs"], 1),
                 "(base successes - harmed) / pairs, in percent, rounded half up", keys)
        b.derive(f"robotwin.{cohort}.f", half_up(100 * failed / c["pairs"], 1),
                 "(pairs - base successes - rescued) / pairs, in percent, rounded half up", keys)
        total = sum(dnum(b.get(f"robotwin.{cohort}.{x}")) for x in "rkhf")
        if abs(total - 100) > Decimal("0.25"):
            die(f"RoboTwin {cohort} outcome shares sum to {total}, not 100")
    # Routing interventions on the source tasks: success from the table, intervals from the
    # figure data (the two must agree).
    rows = b.rows(APP_EXP, "tab:s4-routing-interventions")
    header = [r for r in rows if clean(r[2][0]) == "Model"]
    want = ["Unmodified top-two", "Task mean", "Swapped mean", "Uniform"]
    got = [collapse(re.sub(r"\\shortstack\{([^{}]*)\}", r"\1", c).replace("\\\\", " "))
           for c in header[0][2][1:]] if len(header) == 1 else []
    if got != want:
        die(f"{APP_EXP}: routing table columns are {got}, expected {want}")
    conds = (("original", "original", 1), ("task_mean", "RI-a", 2), ("swapped", "RI-b", 3),
             ("uniform", "RI-c", 4))
    for key, row_name, json_name in (("unsup", r"MoE baseline", "none"),
                                     ("sup", r"MoE \+ TC", "task_id_b")):
        row = b.one_row(rows, row_name, APP_EXP)
        for cond, json_cond, idx in conds:
            prefix = f"robotwin.routing.{key}.{cond}"
            b.cells(prefix, APP_EXP, row, {"sr": idx})
            b.jnum(prefix + ".lo", rel, ["robotwin", "routing", json_name, json_cond, "low"], places=2)
            b.jnum(prefix + ".hi", rel, ["robotwin", "routing", json_name, json_cond, "high"], places=2)
            mean = b.json(rel)["robotwin"]["routing"][json_name][json_cond]["mean"]
            if half_up(mean, 2) != b.get(prefix + ".sr"):
                die(f"routing {key} {cond}: table value {b.get(prefix + '.sr')} and figure data "
                    f"{mean} disagree")
    b.prose(APP_EXP, r"\(4 tasks \$\\times\$ (\d+) scenarios = (\d+) paired episodes per model\)",
            ["robotwin.routing.scenarios", "robotwin.routing.pairs"])
    b.prose(APP_EXP, r"RoboTwin S4 routing interventions at ([\d.]+)M critic updates",
            ["robotwin.routing.updates_m"])
    # Per-task success: four source tasks and the other tasks.
    rows = b.rows(APP_EXP, "tab:s4-ra-200")
    base = b.one_row(rows, r"Matched base", APP_EXP)
    editor = b.one_row(rows, r"MoE \+ TC \(1\.49M\)", APP_EXP)
    header = [r for r in rows if clean(r[2][0]) == "Policy (updates)"]
    if len(header) != 1 or [clean(c) for c in header[0][2][1:5]] != ["H", "M", "P", "S"]:
        die(f"{APP_EXP}: task columns of the 200-scene table are not H, M, P, S")
    for key, label, idx in (("hammer", "Beat block hammer", 1), ("mug", "Hanging mug", 2),
                            ("card", "Move playing card away", 3), ("switch", "Turn switch", 4)):
        b.set(f"robotwin.tasks.source.{key}.name", label, source=APP_EXP, line=base[0],
              match=base[1], note="task name written out from the column key of the table")
        b.cells(f"robotwin.tasks.source.{key}", APP_EXP, base, {"base": idx})
        b.cells(f"robotwin.tasks.source.{key}", APP_EXP, editor, {"editor": idx})
    n = 0
    for row in b.rows(APP_EXP, "tab:s4-re-transfer"):
        lineno, raw, cells = row
        m = re.fullmatch(r"\\texttt\{([a-z_\\]+)\}", cells[0])
        if not m:
            continue
        name = m.group(1).replace("\\_", "_")
        label = name.replace("_", " ").capitalize()
        b.set(f"robotwin.tasks.other.{name}.name", label, source=APP_EXP, line=lineno, match=raw)
        b.cells(f"robotwin.tasks.other.{name}", APP_EXP, row,
                {"base": 1, "editor": 2, "rescued": 3, "harmed": 4})
        n += 1
    if n != b.get("robotwin.other.n_tasks"):
        die(f"{APP_EXP}: {n} other RoboTwin tasks, expected {b.get('robotwin.other.n_tasks')}")
    # Source-task gain against base success (the two tasks the base solves least often, and
    # the one it solves most often).
    src_keys = ("hammer", "mug", "card", "switch")
    for key in src_keys:
        pre = f"robotwin.tasks.source.{key}"
        b.derive(pre + ".gain", plain(dnum(b.get(pre + ".editor")) - dnum(b.get(pre + ".base"))),
                 "editor success - base success, in points", [pre + ".editor", pre + ".base"])
    by_base = sorted(src_keys, key=lambda k: b.get(f"robotwin.tasks.source.{k}.base"))
    if by_base[:2] != ["mug", "switch"] or by_base[-1] != "card":
        die(f"RoboTwin source tasks ordered by base success are {by_base}; the page text names "
            "Hanging mug and Turn switch as the two lowest and Move playing card away as the highest")
    low = [f"robotwin.tasks.source.{k}" for k in by_base[:2]]
    span(b, "robotwin.by_base.low.gain", [k + ".gain" for k in low],
         "gain of the two source tasks with the lowest base success")
    span(b, "robotwin.by_base.low.base", [k + ".base" for k in low],
         "base success of the two source tasks with the lowest base success")
    # Harm outside the source tasks: three press and click tasks against the nine others.
    scenes_key = "robotwin.other.scenes"
    b.prose(APP_EXP, r"(\d+) scenes per task \(4 tasks", ["robotwin.source.scenes"])
    b.prose(APP_EXP, r"\((\d+) matched scenes per task, (\d+) pairs\)",
            ["robotwin.other.scenes", None])
    press = ["click_alarmclock", "click_bell", "press_stapler"]
    others = sorted(b.data["robotwin"]["tasks"]["other"])
    if not set(press) <= set(others):
        die(f"{APP_EXP}: press and click tasks {press} are not all among the other tasks")
    per_scene = dnum(b.get(scenes_key))
    for name in others:
        pre = f"robotwin.tasks.other.{name}"
        b.derive(pre + ".harm_pct", plain(dnum(b.get(pre + ".harmed")) * 100 / per_scene),
                 "harmed pairs / scenes per task, in percent", [pre + ".harmed", scenes_key])
    rest = [n for n in others if n not in press]
    span(b, "robotwin.other_harm.press", [f"robotwin.tasks.other.{n}.harm_pct" for n in press],
         "harm share among the three press and click tasks")
    span(b, "robotwin.other_harm.rest", [f"robotwin.tasks.other.{n}.harm_pct" for n in rest],
         "harm share among the other tasks outside the source set")
    if b.get("robotwin.other_harm.press.hi") >= b.get("robotwin.other_harm.rest.lo"):
        die("RoboTwin: harm on the press and click tasks is no longer below harm on the other tasks")
    b.derive("robotwin.other_harm.press.n_tasks", len(press), "number of press and click tasks",
             [f"robotwin.tasks.other.{n}.harmed" for n in press])
    b.derive("robotwin.other_harm.rest.n_tasks", len(rest), "number of the remaining other tasks",
             [f"robotwin.tasks.other.{n}.harmed" for n in rest])
    # The two S4 editors on the same 600 scenes (paired outcome transitions).
    rel_tr = SW + "transitions_macros.tex"
    for key, name in (("scenes", "SWtrGScenes"), ("both_harm", "SWtrGBothHarm"),
                      ("both_harm_share", "SWtrGBothHarmShare"), ("harm_tc", "SWtrGHarmTC"),
                      ("harm_moe", "SWtrGHarmMoE"), ("overlap_tc", "SWtrGOverlapTC"),
                      ("overlap_moe", "SWtrGOverlapMoE")):
        b.macro("robotwin.same_scenes." + key, rel_tr, name)
    # Unsupervised MoE baseline on the same 600 matched scenes (G6 RoboTwin).
    rel_g6 = SW + "robotwin_b4_g6_overall.tex"
    rows_g6 = b.rows(rel_g6)
    row_none = b.one_row(rows_g6, r"MoE baseline, full \(α=1\.0\)|MoE baseline, full \(\\alpha=1\.0\)", rel_g6)
    b.cells("robotwin.g6.none", rel_g6, row_none, {"sr": 1})
    b.cell_ci("robotwin.g6.none.gain", rel_g6, row_none, 2)
    for stat, idx in (("r", 3), ("k", 4), ("h", 5), ("f", 6)):
        m_sh = re.match(r"([\d.]+)%\s*\((\d+)\)", clean(row_none[2][idx]))
        if not m_sh:
            die(f"{rel_g6}:{row_none[0]}: unexpected share cell {row_none[2][idx]!r}")
        src_g6 = {"source": rel_g6, "line": row_none[0], "match": row_none[1]}
        b.set(f"robotwin.g6.none.{stat}", to_num(m_sh.group(1), rel_g6), **src_g6)
        b.set(f"robotwin.g6.none.{stat}_count", int(m_sh.group(2)), **src_g6)
    b.prose(rel_g6, r"MoE\+TC minus MoE is (\$-\$" + r"|[-+])([\d.]+) \[(\$-\$" + r"|[-+])([\d.]+), (\$-\$" + r"|[-+])([\d.]+)\] points",
            [None, None, None, None, None, None])
    m_c, src_c = b.grab(rel_g6, r"MoE\+TC minus MoE is ([^ ]+) \[([^,]+), ([^\]]+)\] points")
    b.set("robotwin.g6.contrast.d", to_num(m_c.group(1), rel_g6), **src_c)
    b.set("robotwin.g6.contrast.lo", to_num(m_c.group(2), rel_g6), **src_c)
    b.set("robotwin.g6.contrast.hi", to_num(m_c.group(3), rel_g6), **src_c)


def system(b: Builder):
    rel = PUB + "systems_evidence.json"
    alloc = ["libero112", "allocation"]
    b.jnum("system.interaction_ratio", rel,
           alloc + ["episode_length_steps_per_task_max_min_ratio"], places=2)
    b.jnum("system.sampling_ratio", rel,
           alloc + ["retained_cutoff_replay_sample_rows_per_task_max_min_ratio"], places=2)
    b.jnum("system.actions_min", rel, alloc + ["episode_length_steps_per_task_min_median_max", 0])
    b.jnum("system.actions_max", rel, alloc + ["episode_length_steps_per_task_min_median_max", 2])
    b.prose("sections/supp_system.tex",
            r"([\d,]+) critic heads for 112 tasks; ([\d.]+)\\,MB inference snapshot",
            ["system.critic_heads", "system.snapshot_mb"])
    b.prose(APP_EXP, r"(\d+)\\% fewer render calls; ([\d.]+) to ([\d.]+) actions/s",
            ["system.render_reduction", "system.speed_before", "system.speed_after"])
    mac = SW + "runcost_macros.tex"
    b.macro("system.hours", mac, "SWrcFullHours")
    b.macro("system.gpu_hours", mac, "SWrcFullGpuh")
    b.macro("system.actions_m", mac, "SWrcFullActions")
    b.macro("system.first_range_gpu_hours", mac, "SWrcFirstGpuh")
    b.macro("system.second_seed_gpu_hours", mac, "SWrcSecondLthreeGpuh")
    rows = b.rows(SW + "runcost_table.tex")
    row = b.one_row(rows, r"L3, second seed", SW + "runcost_table.tex")
    b.cell_text("system.second_seed_updates", SW + "runcost_table.tex", row, 1)
    row3 = b.one_row(rows, r"L3, third seed", SW + "runcost_table.tex")
    b.cells("system.third_seed", SW + "runcost_table.tex", row3, {"hours": 2, "gpu_hours": 3, "rate": 4})


def videos(b: Builder):
    mac = SW + "videos_macros.tex"
    b.macro("videos.recorded", mac, "swVideoClips")
    b.macro("videos.same_outcome", mac, "swVideoSame")
    b.macro("videos.same_length", mac, "swVideoSameLen")
    b.macro("videos.n_files", mac, "swVideoFiles")
    b.prose(VIDEOS_TEX, r"recorded (\d+) frames per second", ["videos.fps"])
    rel = SW + "videos_table.tex"
    # The paper's table numbers the clips; the file of each number comes from the clip manifest.
    manifest = SW + "videos_manifest.csv"
    files = {}
    for mrow in csv.DictReader(io.StringIO(b.text(manifest))):
        name = mrow["output_file"].rsplit("/", 1)[-1]
        if not re.fullmatch(r"\d\d_[a-z0-9_]+\.mp4", name):
            die(f"{manifest}: unexpected clip file name {name!r}")
        if files.setdefault(int(name[:2]), name) != name:
            die(f"{manifest}: two files share the clip number {int(name[:2])}")
    n = 0
    for row in b.rows(rel):
        lineno, raw, cells = row
        m = re.fullmatch(r"\d+", cells[0])
        if not m:
            continue
        if int(cells[0]) not in files:
            die(f"{rel}:{lineno}: clip {cells[0]} is not in {manifest}")
        fname = files[int(cells[0])]
        cid = "c" + fname[:2]
        src = {"source": rel, "line": lineno, "match": raw}
        task = clean(cells[1])
        scene = ""
        ms = re.fullmatch(r"(.+?) \((.+)\)", task)
        if ms:
            task, scene = ms.group(1), ms.group(2)
        b.set(f"clips.{cid}.file", fname, **src)
        b.set(f"clips.{cid}.benchmark", "RoboTwin" if "robotwin" in fname else "LIBERO", **src,
              note="from the file name")
        b.set(f"clips.{cid}.task", task, **src)
        b.set(f"clips.{cid}.note", scene, **src)
        panels = []
        for part in clean(cells[2]).split(";"):
            policy, _, outcome = part.strip().rpartition(":")
            outcome = outcome.strip()
            if not policy or outcome not in ("success", "failure"):
                die(f"{rel}:{lineno}: cannot read panel {part!r}")
            panels.append({"policy": policy.strip(), "result": outcome})
        b.set(f"clips.{cid}.panels", panels, **src)
        b.set(f"clips.{cid}.shows", clean(cells[3]), **src)
        n += 1
    if n != b.get("videos.n_files"):
        die(f"{rel}: {n} clips listed, expected {b.get('videos.n_files')}")


def guide_questions(b: Builder):
    """The one-line answers of the appendix overview, with their number macros filled in."""
    rel = SW + "guide_questions_body.tex"
    macros: dict[str, str] = {}
    for mfile in ("robustness_macros.tex", "unseen96_numbers.tex", "corrsize_numbers.tex",
                  "armgrip_macros.tex"):
        for m in re.finditer(r"^\\newcommand\{\\(\w+)\}\{(.*)\}[ \t]*$", b.text(SW + mfile), re.M):
            macros[m.group(1)] = m.group(2)

    def fill(text: str, lineno: int) -> str:
        def repl(m):
            if m.group(1) not in macros:
                die(f"{rel}:{lineno}: unknown macro \\{m.group(1)}")
            return macros[m.group(1)]
        out = re.sub(r"\\((?:swr|Uns|SWcs|SWag)\w+)(?:\{\})?", repl, text)
        out = out.replace("$-$", "\u2212").replace("\\%", "%").replace("--", "\u2013").replace("~", " ")
        if "\\" in out or "$" in out or "{" in out:
            die(f"{rel}:{lineno}: TeX left in guide answer: {out!r}")
        return collapse(out)

    n = 0
    for lineno, raw, cells in b.rows(rel):
        if len(cells) != 3:
            die(f"{rel}:{lineno}: expected 3 cells")
        n += 1
        src = {"source": rel, "line": lineno, "match": raw,
               "note": "number macros replaced by their generated values"}
        b.set(f"guide.q{n:02d}.question", fill(cells[0], lineno), **src)
        b.set(f"guide.q{n:02d}.answer", fill(cells[1], lineno), **src)
    if n < 8:
        die(f"{rel}: only {n} guide questions found")


def public_additions(b: Builder):
    """Camera-matched 16-task comparison (all nine rows in paper + G4 CI) and RoboTwin half-scale (B4)."""
    # 1. Paper camera-matched comparison across R1--R3 and L1--L3 (dual and main-only).
    rel = SW + "completions_cameras.tex"
    rows = b.rows(rel)
    b.prose(rel,
            r"Source / held-out base SR is ([\d.]+) / ([\d.]+)\\% for the unshaded rows, "
            r"([\d.]+) / ([\d.]+)\\% for main-camera L1, ([\d.]+) / ([\d.]+)\\% for main-camera L2 and "
            r"([\d.]+) / ([\d.]+)\\% for main-camera L3",
            ["cameras.base.shared.src", "cameras.base.shared.ho",
             "cameras.base.L1_main.src", "cameras.base.L1_main.ho",
             "cameras.base.L2_main.src", "cameras.base.L2_main.ho",
             "cameras.base.L3_main.src", "cameras.base.L3_main.ho"])
    cam_spec = {"src_sr": 1, "ho_sr": 2, "r": 3, "h": 4, "gain": 5, "cov": 6, "unc": 7}
    for key, first in (("R1_main", r"R1, main"), ("L1_dual", r"L1, main \+ wrist"),
                       ("L1_main", r"L1, main"), ("R2_main", r"R2, main"),
                       ("L2_dual", r"L2, main \+ wrist"), ("L2_main", r"L2, main"),
                       ("R3_main", r"R3, main"), ("L3_dual", r"L3, main \+ wrist"),
                       ("L3_main", r"L3, main")):
        b.cells(f"cameras.{key}", rel, b.one_row(rows, first, rel), cam_spec)

    # 2. G4 main-camera L3 intervals & extra shares from the additions bundle (cross-checked against paper table).
    g4_rel = "figures/G4/inputs/summary.csv"
    g4_rows = {(r["task_group"], r["view"]): r for r in b.add_csv_rows(g4_rel)}
    src16 = g4_rows.get(("source16", "both_rounds"))
    ho18 = g4_rows.get(("heldout18", "both_rounds"))
    if not src16 or not ho18:
        die(f"additions:{g4_rel}: missing source16 or heldout18 both_rounds row")
    s_src = {"source": "additions:" + g4_rel, "match": "source16,both_rounds"}
    s_ho = {"source": "additions:" + g4_rel, "match": "heldout18,both_rounds"}
    for k, csv_v, places in (("src_sr", float(src16["editor_sr"]), 2),
                             ("ho_sr", float(ho18["editor_sr"]), 2),
                             ("r", float(ho18["r"]), 1),
                             ("h", float(ho18["h"]), 1),
                             ("gain", float(ho18["gain"]), 2)):
        if half_up(100 * csv_v, places) != b.get(f"cameras.L3_main.{k}"):
            die(f"cameras.L3_main.{k}: paper table {b.get(f'cameras.L3_main.{k}')} != G4 {half_up(100 * csv_v, places)}")
    b.set("cameras.L3_main.src_pairs", int(src16["episodes"]), **s_src)
    b.set("cameras.L3_main.src_gain.d", half_up(100 * float(src16["gain"]), 2), **s_src)
    b.set("cameras.L3_main.src_gain.lo", half_up(100 * float(src16["gain_ci_low"]), 2), **s_src)
    b.set("cameras.L3_main.src_gain.hi", half_up(100 * float(src16["gain_ci_high"]), 2), **s_src)
    b.set("cameras.L3_main.ho_pairs", int(ho18["episodes"]), **s_ho)
    b.set("cameras.L3_main.k", half_up(100 * float(ho18["k"]), 1), **s_ho)
    b.set("cameras.L3_main.f", half_up(100 * float(ho18["f"]), 1), **s_ho)
    b.set("cameras.L3_main.gain_lo", half_up(100 * float(ho18["gain_ci_low"]), 2), **s_ho)
    b.set("cameras.L3_main.gain_hi", half_up(100 * float(ho18["gain_ci_high"]), 2), **s_ho)
    g4_total = sum(dnum(b.get(f"cameras.L3_main.{x}")) for x in "rkhf")
    if abs(g4_total - 100) > Decimal("0.25"):
        die(f"G4 L3_main held-out shares sum to {g4_total}")

    # 3. B4 RoboTwin amplitude scaling (12 other tasks, 600 matched triplets: base, alpha=1, alpha=0.5).
    b4_rel = "figures/B4/inputs/summary.json"
    b4 = b.add_json(b4_rel)
    b4_src = {"source": "additions:" + b4_rel, "match": "ALL_12_TASKS_EQUAL_WEIGHT"}
    b.set("robotwin.b4.pairs", int(b4["paired_states"]), source="additions:" + b4_rel, match="paired_states")
    b.set("robotwin.b4.episodes", int(b4["episodes"]), source="additions:" + b4_rel, match="episodes")
    overall = {r["condition"]: r for r in b4["summary"] if r["scope"] == "ALL_12_TASKS_EQUAL_WEIGHT"}
    if set(overall) != {"s4_alpha_1", "s4_alpha_0p5"}:
        die(f"additions:{b4_rel}: unexpected overall conditions {sorted(overall)}")
    b.set("robotwin.b4.tasks_count", int(overall["s4_alpha_1"]["task_count"]), **b4_src)
    b.set("robotwin.b4.base.sr", half_up(100 * overall["s4_alpha_1"]["base_sr"], 2), **b4_src)
    b.set("robotwin.b4.base.lo", half_up(100 * overall["s4_alpha_1"]["base_sr_ci_low"], 2), **b4_src)
    b.set("robotwin.b4.base.hi", half_up(100 * overall["s4_alpha_1"]["base_sr_ci_high"], 2), **b4_src)
    b.set("robotwin.b4.base.ok", int(overall["s4_alpha_1"]["base_successful_n"]), **b4_src)
    for cname, cond in (("full", "s4_alpha_1"), ("half", "s4_alpha_0p5")):
        row = overall[cond]
        m = {"source": "additions:" + b4_rel, "match": f"ALL_12_TASKS_EQUAL_WEIGHT:{cond}"}
        b.set(f"robotwin.b4.{cname}.sr", half_up(100 * row["editor_sr"], 2), **m)
        b.set(f"robotwin.b4.{cname}.lo", half_up(100 * row["editor_sr_ci_low"], 2), **m)
        b.set(f"robotwin.b4.{cname}.hi", half_up(100 * row["editor_sr_ci_high"], 2), **m)
        b.set(f"robotwin.b4.{cname}.ok", int(row["editor_successful_n"]), **m)
        for s in "rkhf":
            b.set(f"robotwin.b4.{cname}.{s}", half_up(100 * row[s], 1), **m)
            b.set(f"robotwin.b4.{cname}.{s}_count", int(row[f"{s}_count"]), **m)
        b.set(f"robotwin.b4.{cname}.gain.d", half_up(100 * row["gain"], 2), **m)
        b.set(f"robotwin.b4.{cname}.gain.lo", half_up(100 * row["gain_ci_low"], 2), **m)
        b.set(f"robotwin.b4.{cname}.gain.hi", half_up(100 * row["gain_ci_high"], 2), **m)
        total = sum(dnum(b.get(f"robotwin.b4.{cname}.{x}")) for x in "rkhf")
        if abs(total - 100) > Decimal("0.25"):
            die(f"B4 {cname} shares sum to {total}")
    b.derive("robotwin.b4.half_minus_full.sr",
             plain(dnum(b.get("robotwin.b4.half.sr")) - dnum(b.get("robotwin.b4.full.sr"))),
             "half-scale SR minus full-scale SR in the matched B4 panel, points",
             ["robotwin.b4.half.sr", "robotwin.b4.full.sr"])
    b.derive("robotwin.b4.half_minus_full.harm_drop",
             plain(dnum(b.get("robotwin.b4.full.h")) - dnum(b.get("robotwin.b4.half.h"))),
             "full-scale harm share minus half-scale harm share, percentage points",
             ["robotwin.b4.full.h", "robotwin.b4.half.h"])
    b.derive("robotwin.b4.half_minus_full.fewer_harmed",
             b.get("robotwin.b4.full.h_count") - b.get("robotwin.b4.half.h_count"),
             "fewer harmed pairs out of 600 at half scale",
             ["robotwin.b4.full.h_count", "robotwin.b4.half.h_count"])

    # Per-task B4 rows for all 12 tasks.
    by_task: dict[str, dict[str, dict]] = {}
    for row in b4["summary"]:
        sc = row["scope"]
        if sc == "ALL_12_TASKS_EQUAL_WEIGHT":
            continue
        by_task.setdefault(sc, {})[row["condition"]] = row
    if len(by_task) != b.get("robotwin.b4.tasks_count"):
        die(f"additions:{b4_rel}: found {len(by_task)} tasks, expected {b.get('robotwin.b4.tasks_count')}")
    for slug in sorted(by_task):
        pair = by_task[slug]
        r1, r05 = pair["s4_alpha_1"], pair["s4_alpha_0p5"]
        m = {"source": "additions:" + b4_rel, "match": f"scope={slug}"}
        b.set(f"robotwin.b4.tasks.{slug}.name", slug.replace("_", " ").capitalize(), **m)
        b.set(f"robotwin.b4.tasks.{slug}.base", half_up(100 * r1["base_sr"], 1), **m)
        b.set(f"robotwin.b4.tasks.{slug}.full", half_up(100 * r1["editor_sr"], 1), **m)
        b.set(f"robotwin.b4.tasks.{slug}.half", half_up(100 * r05["editor_sr"], 1), **m)
        b.set(f"robotwin.b4.tasks.{slug}.harm_full", half_up(100 * r1["h"], 1), **m)
        b.set(f"robotwin.b4.tasks.{slug}.harm_half", half_up(100 * r05["h"], 1), **m)
        b.set(f"robotwin.b4.tasks.{slug}.gain_full", half_up(100 * r1["gain"], 1), **m)
        b.set(f"robotwin.b4.tasks.{slug}.gain_half", half_up(100 * r05["gain"], 1), **m)


# ---------------------------------------------------------------------- main

def build(root: Path, additions: Path) -> Builder:
    b = Builder(root, additions)
    try:
        paper_and_setup(b)
        recipe_table(b)
        breadth(b)
        what_matters(b)
        per_task(b)
        structure(b)
        correction_size(b)
        robustness(b)
        evolution(b)
        unseen96(b)
        adaptation(b)
        robotwin(b)
        system(b)
        videos(b)
        guide_questions(b)
        public_additions(b)
    finally:
        b.close()
    return b


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--paper-root", default=None,
                    help="root of the paper sources (read-only); default: $SC_PAPER_ROOT")
    ap.add_argument("--additions", default=None,
                    help="public-additions ZIP or extracted directory (read-only); default: $SC_ADDITIONS_PATH")
    ap.add_argument("--check", action="store_true",
                    help="do not write; fail if data/site_data.json differs from a fresh "
                         "build, and report whether data/ledger.json is current")
    args = ap.parse_args()
    b = build(paper_root(args.paper_root), additions_source(args.additions))
    ledger = {"sources": dict(sorted(b.files.items())), "values": b.ledger}
    outputs = {DATA / "site_data.json": dump_json(b.data),
               DATA / "ledger.json": dump_json(ledger)}
    if args.check:
        data_path, ledger_path = DATA / "site_data.json", DATA / "ledger.json"
        if not data_path.is_file() or data_path.read_text(encoding="utf-8") != outputs[data_path]:
            die("data/site_data.json differs from a fresh build: the paper sources or the "
                "patterns changed; run build/build_data.py and build/stamp.py")
        print(f"build_data: {len(b.ledger)} values reproduce data/site_data.json byte for byte")
        if not ledger_path.is_file() or ledger_path.read_text(encoding="utf-8") != outputs[ledger_path]:
            stored = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.is_file() else {}
            changed = sorted(f for f, h in ledger["sources"].items()
                             if stored.get("sources", {}).get(f) != h)
            print("build_data: the values are unchanged, but data/ledger.json is older than the "
                  "paper sources (changed files: " + (", ".join(changed) or "none; line numbers "
                  "or matched text moved") + "); run build/build_data.py to refresh it")
        else:
            print("build_data: data/ledger.json reproduces byte for byte")
        return
    DATA.mkdir(exist_ok=True)
    for path, text in outputs.items():
        path.write_text(text, encoding="utf-8")
    print(f"build_data: wrote {len(b.ledger)} values from {len(b.files)} source files "
          "to data/site_data.json and data/ledger.json")


if __name__ == "__main__":
    main()
