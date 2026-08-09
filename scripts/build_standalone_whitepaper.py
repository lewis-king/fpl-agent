"""Bundle the visual GW1 whitepaper and its local assets into one HTML file."""

from __future__ import annotations

import base64
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
SOURCE = REPORTS / "gw1-picker-whitepaper.html"
OUTPUT = REPORTS / "gw1-picker-whitepaper-standalone.html"


ASSETS = {
    "./assets/manrope-400.ttf": ("font/ttf", REPORTS / "assets/manrope-400.ttf"),
    "./assets/manrope-500.ttf": ("font/ttf", REPORTS / "assets/manrope-500.ttf"),
    "./assets/manrope-600.ttf": ("font/ttf", REPORTS / "assets/manrope-600.ttf"),
    "./assets/manrope-700.ttf": ("font/ttf", REPORTS / "assets/manrope-700.ttf"),
    "./assets/newsreader-400.ttf": ("font/ttf", REPORTS / "assets/newsreader-400.ttf"),
    "./assets/newsreader-500.ttf": ("font/ttf", REPORTS / "assets/newsreader-500.ttf"),
    "./assets/newsreader-600.ttf": ("font/ttf", REPORTS / "assets/newsreader-600.ttf"),
    "./assets/gw1-picker-cover.webp": ("image/webp", REPORTS / "assets/gw1-picker-cover.webp"),
}


def data_uri(mime_type: str, path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def main() -> None:
    html = SOURCE.read_text(encoding="utf-8")
    for reference, (mime_type, path) in ASSETS.items():
        if reference not in html:
            raise RuntimeError(f"Expected asset reference is absent: {reference}")
        html = html.replace(reference, data_uri(mime_type, path))

    html = html.replace(
        '<a class="nav-action" href="./gw1-picker-technical-report.md">',
        '<a class="nav-action" href="#appendix">',
    )
    html = html.replace(
        '<a href="./gw1-picker-technical-report.md">full technical report</a>',
        '<a href="#appendix">embedded technical methods annex</a>',
    )
    html = html.replace(
        "<!doctype html>",
        "<!doctype html>\n<!-- Standalone build: fonts, cover and methods are embedded below. -->",
        1,
    )
    OUTPUT.write_text(html, encoding="utf-8")
    print(f"Built {OUTPUT.relative_to(ROOT)} ({OUTPUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
