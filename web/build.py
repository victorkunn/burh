"""Inline the engine into the tool page.

The page and the node cross-validator share ONE engine file. Publishing a
copy-pasted engine would let the shipped page drift from the one that was
validated, so the inlining happens here, at build time, from the same source.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MARKER = "/*__ENGINE__*/"


def build(out: Path) -> Path:
    engine = (HERE / "engine.js").read_text()
    # Drop the CommonJS/global export tail; the page inlines the IIFE directly.
    engine = engine.split('if (typeof module !== "undefined"')[0].rstrip()
    html = (HERE / "tool.html").read_text()
    if MARKER not in html:
        raise SystemExit(f"{MARKER} not found in tool.html")
    page = html.replace(MARKER, engine)
    if MARKER in page:
        raise SystemExit("engine was not substituted")
    out.write_text(page)
    return out


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "footing-check.html"
    p = build(target)
    print(f"{p}  ({p.stat().st_size / 1024:.0f} KB)")
