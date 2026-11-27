#!/usr/bin/env python3
"""Checks of the page that need no browser.

    python build/check_site.py

  1. index.html is up to date with the data (same test as stamp.py --check).
  2. Every local link, image, poster, video, script and stylesheet exists, and
     every #anchor points at an id; ids are unique.
  3. Nothing is loaded from another host: resources are relative paths, the
     stylesheet has no remote url() or @import, the scripts open no connection.
     Outgoing links are allowed only for URLs entered in data/site.json.
  4. No quantity is typed by hand: outside the value slots, charts and
     generated blocks, the page text holds digits only in names such as L1,
     R3, LIBERO-130 or "Finding 2".
  5. Logos: every logo named in data/site.json exists, is listed in
     assets/img/logos/SOURCES.md with the SHA-256 of the stored file, and an
     SVG logo holds no script, event attribute or external reference.
  6. Release hygiene: no text file holds an absolute path into a home, media
     or user directory.

Exits with status 1 and a list of problems if any check fails.
"""
from __future__ import annotations

import hashlib
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA, SITE, load_json  # noqa: E402
import build_charts  # noqa: E402
import stamp  # noqa: E402

# Names and fixed labels that contain digits (not quantities).
NAME_PATTERNS = [
    r"\b[RL][123]\b",                 # recipe names
    r"\bLIBERO-130\b",                # benchmark name
    r"\b[Ff]inding [1-4]\b",          # finding labels
    r"\bF[1-4]\b",                    # finding labels in the section rail
    r"\bFigure [12]\b",               # paper figure references
    r"\b2×2\b",                       # paired outcome table shape
    r"\bsum to 100%",                 # definition of the four outcome shares
]
TEXT_SUFFIXES = {".html", ".css", ".js", ".json", ".md", ".py", ".svg", ".txt", ""}
# Directory names that start an absolute path on a personal machine; written so that
# this file does not contain such a path itself.
PRIVATE_ROOTS = ["/" + name + "/" for name in ("home", "media", "Users", "mnt", "root")]


class Collector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids: list[str] = []
        self.refs: list[tuple[str, str, str]] = []     # (tag, attribute, value)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            self.ids.append(a["id"])
        for name in ("href", "src", "poster"):
            if a.get(name) is not None:
                self.refs.append((tag, name, a[name]))


def allowed_external(site: dict) -> set[str]:
    urls = {str(v).strip() for v in site.get("links", {}).values()}
    urls |= {str(a.get("url", "")).strip() for a in site.get("authors", [])}
    return {u for u in urls if u and not u.startswith("#")}


def check_logos(site: dict, problems: list[str]) -> int:
    logo_dir = SITE / "assets/img/logos"
    record = logo_dir / "SOURCES.md"
    listed = record.read_text(encoding="utf-8") if record.is_file() else ""
    n = 0
    for aff in site.get("affiliations", []):
        rel = str(aff.get("logo", "")).strip()
        if not rel:
            continue
        n += 1
        path = SITE / rel
        if not path.is_file():
            problems.append(f"logo file missing: {rel}")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if path.name not in listed or digest not in listed:
            problems.append(f"logo {path.name} is not listed in SOURCES.md with its SHA-256 {digest}")
        if not str(aff.get("logo_alt", "")).strip() and not str(aff.get("name", "")).strip():
            problems.append(f"logo {path.name} has no alt text")
        if path.suffix == ".svg":
            svg = path.read_text(encoding="utf-8", errors="replace")
            if re.search(r"<script|<foreignObject|<image\b|<use\b|<style|\son\w+\s*=|<!ENTITY|"
                         r"(?:href|src)\s*=|url\(\s*['\"]?(?!#)", svg, re.I):
                problems.append(f"logo {path.name}: SVG holds a script, a link or an external reference")
    if logo_dir.is_dir():
        for extra in sorted(p.name for p in logo_dir.iterdir()
                            if p.is_file() and p.name != "SOURCES.md" and p.name not in listed):
            problems.append(f"file in assets/img/logos is not listed in SOURCES.md: {extra}")
    return n


def check_private_paths(problems: list[str]) -> int:
    n = 0
    for path in sorted(SITE.rglob("*")):
        if not path.is_file() or ".git" in path.relative_to(SITE).parts:
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        n += 1
        text = path.read_text(encoding="utf-8", errors="replace")
        for root in PRIVATE_ROOTS:
            if root in text:
                problems.append(f"{path.relative_to(SITE)} holds an absolute path ({root}...)")
                break
    return n


def main():
    problems: list[str] = []
    html = (SITE / "index.html").read_text(encoding="utf-8")
    site = load_json(DATA / "site.json")

    # 1. up to date
    data = load_json(DATA / "site_data.json")
    ctx = {"data": data, "media": load_json(DATA / "media.json"), "site": site,
           "charts": build_charts.render_all(data)}
    fresh, used = stamp.stamp(html, ctx)
    if fresh != html:
        problems.append("index.html is not up to date with the data: run build/stamp.py")

    # 2. and 3. links and resources
    c = Collector()
    c.feed(html)
    dupes = sorted({i for i in c.ids if c.ids.count(i) > 1})
    if dupes:
        problems.append("duplicate ids: " + ", ".join(dupes))
    ids = set(c.ids)
    external_ok = allowed_external(site)
    n_local = 0
    for tag, attr, val in c.refs:
        if val.startswith("data:"):
            continue
        if val.startswith("#"):
            if val[1:] not in ids:
                problems.append(f"anchor without target: {val}")
            continue
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", val) or val.startswith("//"):
            if tag == "a" and attr == "href" and val in external_ok:
                continue
            problems.append(f"external reference in <{tag} {attr}>: {val}")
            continue
        path = SITE / val.split("#")[0].split("?")[0]
        n_local += 1
        if not path.is_file():
            problems.append(f"missing file: {val}")
    blob = load_json(DATA / "media.json")
    for clip in blob["clips"].values():
        for key in ("video", "poster", "thumb"):
            if not (SITE / clip[key]).is_file():
                problems.append(f"missing media file: {clip[key]}")
    for fig in blob.get("figures", {}).values():
        if not (SITE / fig["file"]).is_file():
            problems.append(f"missing figure file: {fig['file']}")
    css_path = SITE / "assets/css/site.css"
    css = css_path.read_text(encoding="utf-8")
    if re.search(r"@import|url\(\s*['\"]?(?:https?:)?//", css):
        problems.append("stylesheet refers to another host")
    for rel_url in re.findall(r"url\(\s*['\"]?([^)'\"]+)['\"]?\s*\)", css):
        if rel_url.startswith(("#", "data:")):
            continue
        asset = (css_path.parent / rel_url).resolve()
        if not asset.is_file():
            problems.append(f"missing CSS asset: {rel_url}")
    scripts = (SITE / "assets/js/site.js").read_text(encoding="utf-8")
    scripts += " ".join(re.findall(r"<script\b[^>]*>(.*?)</script>", html, re.S))
    if re.search(r"\bfetch\s*\(|XMLHttpRequest|WebSocket|sendBeacon|https?://|importScripts", scripts):
        problems.append("a script may open a network connection")
    if re.search(r'<meta[^>]+property="og:image"', html):
        if not re.search(r'<meta[^>]+property="og:image"[^>]+content="https://', html):
            problems.append("og:image must be an absolute https URL (see README)")

    # 4. digits outside slots
    text = re.sub(r"<!--(?:gen|chart|mini):.*?<!--/(?:gen|chart|mini)-->", " ", html, flags=re.S)
    text = re.sub(r"<span data-v=[^>]*>[^<]*</span>", " ", text)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", text, flags=re.S)
    text = re.sub(r"<head\b.*?</head>", " ", text, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    for pat in NAME_PATTERNS:
        text = re.sub(pat, " ", text)
    stray = sorted(set(re.findall(r"[^\s]*\d[^\s]*", text)))
    if stray:
        problems.append("digits typed outside the data slots: " + ", ".join(stray))

    # 5. and 6.
    n_logos = check_logos(site, problems)
    n_text = check_private_paths(problems)

    if problems:
        print("check_site: FAILED")
        for p in problems:
            print("  - " + p)
        raise SystemExit(1)
    print(f"check_site: ok ({used['values']} values, {len(used['charts'])} charts, "
          f"{n_local} local references, {len(ids)} ids, {n_logos} logos, "
          f"{n_text} text files without private paths)")


if __name__ == "__main__":
    main()
