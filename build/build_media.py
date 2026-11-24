#!/usr/bin/env python3
"""Copy the replay clips, cut poster frames and render the system figure.

    python build/build_media.py --videos DIR --paper-root DIR

DIR is the folder that holds the ten side-by-side replay clips listed in the
paper's clip table. The clips are copied unchanged. For each clip the script
writes a poster frame and a small thumbnail with ffmpeg and records size and
duration in data/media.json, which the page uses for width, height and aspect
ratio. The system figure is rendered from the paper's PDF with pdftocairo.

Needs ffmpeg, ffprobe and pdftocairo on the PATH, and Pillow.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ASSETS, DATA, die, dump_json, load_json, paper_root  # noqa: E402

from PIL import Image  # noqa: E402

POSTER_AT = 0.36       # fraction of the clip at which the poster frame is taken
POSTER_WIDTH = 1280
THUMB_WIDTH = 400
FIGURE_PDF = "figures/figure2_method/figure2_evidence_draft.pdf"
FIGURE_WIDTH = 1760


def run(cmd: list[str]) -> str:
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        die("command failed: " + " ".join(cmd) + "\n" + res.stderr.strip())
    return res.stdout


def probe(path: Path) -> dict:
    out = run(["ffprobe", "-v", "error", "-show_entries",
               "stream=codec_type,codec_name,width,height,r_frame_rate:format=duration",
               "-of", "json", str(path)])
    import json
    info = json.loads(out)
    video = [s for s in info["streams"] if s["codec_type"] == "video"]
    audio = [s for s in info["streams"] if s["codec_type"] == "audio"]
    if len(video) != 1 or video[0]["codec_name"] != "h264":
        die(f"{path.name}: expected one H.264 video stream")
    if audio:
        die(f"{path.name}: expected no audio stream")
    num, den = video[0]["r_frame_rate"].split("/")
    return {"width": int(video[0]["width"]), "height": int(video[0]["height"]),
            "duration_s": round(float(info["format"]["duration"]), 2),
            "fps": round(int(num) / int(den), 2)}


def save_jpeg(src: Path, dst: Path, width: int, quality: int):
    im = Image.open(src).convert("RGB")
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    dst.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst, "JPEG", quality=quality, optimize=True, progressive=True)
    return im.size


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--videos", required=True, help="folder with the ten replay clips")
    ap.add_argument("--paper-root", default=None,
                    help="root of the paper sources (read-only); default: $SC_PAPER_ROOT")
    args = ap.parse_args()
    src_dir = Path(args.videos)
    root = paper_root(args.paper_root)
    if not src_dir.is_dir():
        die(f"video folder not found: {src_dir}")

    clips = load_json(DATA / "site_data.json")["clips"]
    media = {"clips": {}, "figures": {}}
    scratch = Path(tempfile.mkdtemp(prefix="sc_media_"))
    try:
        for cid, clip in clips.items():
            src = src_dir / clip["file"]
            if not src.is_file():
                die(f"clip listed in the paper but not found: {src}")
            dst = ASSETS / "video" / clip["file"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not dst.is_file() or dst.stat().st_size != src.stat().st_size:
                shutil.copyfile(src, dst)
            info = probe(dst)
            if len(clip["panels"]) < 2:
                die(f"{clip['file']}: fewer than two panels listed")
            frame = scratch / f"{cid}.png"
            run(["ffmpeg", "-v", "error", "-y", "-ss", f"{info['duration_s'] * POSTER_AT:.2f}",
                 "-i", str(dst), "-frames:v", "1", str(frame)])
            stem = clip["file"][:2]
            save_jpeg(frame, ASSETS / "img" / "posters" / f"{stem}.jpg", POSTER_WIDTH, 80)
            save_jpeg(frame, ASSETS / "img" / "thumbs" / f"{stem}.jpg", THUMB_WIDTH, 72)
            media["clips"][cid] = dict(info, bytes=dst.stat().st_size,
                                       poster=f"assets/img/posters/{stem}.jpg",
                                       thumb=f"assets/img/thumbs/{stem}.jpg",
                                       video=f"assets/video/{clip['file']}")
        extra = sorted(p.name for p in (ASSETS / "video").glob("*.mp4")
                       if p.name not in {c["file"] for c in clips.values()})
        if extra:
            die("assets/video holds clips that the paper does not list: " + ", ".join(extra))

        pdf = root / FIGURE_PDF
        if not pdf.is_file():
            die(f"system figure not found: {pdf}")
        run(["pdftocairo", "-png", "-r", "400", "-singlefile", str(pdf),
             str(scratch / "system")])
        im = Image.open(scratch / "system.png").convert("RGB")
        im = im.resize((FIGURE_WIDTH, round(im.height * FIGURE_WIDTH / im.width)), Image.LANCZOS)
        out = ASSETS / "img" / "resop_system.webp"
        im.save(out, "WEBP", quality=88, method=6)
        media["figures"]["resop_system"] = {"file": "assets/img/resop_system.webp",
                                            "width": im.width, "height": im.height,
                                            "source": FIGURE_PDF}
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    (DATA / "media.json").write_text(dump_json(media), encoding="utf-8")
    total = sum(c["bytes"] for c in media["clips"].values())
    print(f"build_media: {len(media['clips'])} clips ({total / 1e6:.1f} MB), posters, thumbnails "
          "and the system figure written; data/media.json updated")


if __name__ == "__main__":
    main()
