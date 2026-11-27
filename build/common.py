"""Shared helpers for the page build scripts: paths, number formatting, data lookup."""
from __future__ import annotations

import json
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent
DATA = SITE / "data"
ASSETS = SITE / "assets"

MINUS = "−"      # true minus sign
NDASH = "–"
NBSP = " "
TIMES = "×"


def die(msg: str) -> "None":
    sys.stderr.write("ERROR: " + msg + "\n")
    raise SystemExit(1)


def paper_root(option: str | None) -> Path:
    """The paper source tree: --paper-root, else the environment variable SC_PAPER_ROOT."""
    import os
    value = option or os.environ.get("SC_PAPER_ROOT", "")
    if not value:
        die("the paper root is not set: pass --paper-root DIR or set SC_PAPER_ROOT")
    root = Path(value).expanduser()
    if not root.is_dir():
        die("paper root not found: " + value)
    return root


def additions_source(option: str | None) -> Path:
    """Public additions bundle (.zip or extracted dir): --additions, else SC_ADDITIONS_PATH."""
    import os
    value = option or os.environ.get("SC_ADDITIONS_PATH", "")
    if not value:
        die("the additions bundle is not set: pass --additions PATH or set SC_ADDITIONS_PATH")
    path = Path(value).expanduser()
    if not path.exists():
        die("additions bundle not found: " + value)
    return path


def load_json(path: Path):
    if not path.is_file():
        die(f"missing file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(obj) -> str:
    """Deterministic JSON text (insertion order kept, fixed separators, trailing newline)."""
    return json.dumps(obj, indent=1, ensure_ascii=False, sort_keys=False) + "\n"


def lookup(data: dict, key: str):
    """Resolve a dotted key in the nested data; fail loudly when it is missing."""
    node = data
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            die(f"data key not found: {key!r} (at {part!r})")
        node = node[part]
    return node


def _round(value, places: int) -> Decimal:
    """Round half up to the displayed precision, as the paper does."""
    q = Decimal(1).scaleb(-places)
    return Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP)


def fmt(value, spec: str = "1") -> str:
    """Format a data value for display.

    spec: "0".."4"  fixed decimals, half up, true minus sign
          "+0".."+4" the same with an explicit sign
          "a0".."a4" absolute value
          "int"      integer with thousands separators
          "raw"      the stored value as is
    Strings pass through unchanged.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, bool) or value is None:
        die(f"cannot format value {value!r}")
    if spec == "raw":
        return str(value)
    if spec == "int":
        return f"{int(_round(value, 0)):,}"
    signed = spec.startswith("+")
    absolute = spec.startswith("a")
    places = int(spec.lstrip("+a"))
    d = _round(value, places)
    if absolute:
        d = abs(d)
    body = f"{abs(d):.{places}f}"
    if d < 0:
        return MINUS + body
    if signed and d > 0:
        return "+" + body
    return body


def esc(text) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))
