#!/usr/bin/env python3
"""
vinted4x6_cli - batch convert Vinted A4 label PDFs to 4x6.

    python vinted4x6_cli.py label.pdf [label2.pdf ...]
    python vinted4x6_cli.py --sheet label.pdf label2.pdf   # combine onto A4
    python vinted4x6_cli.py --landscape label.pdf          # 6x4 output

Each PDF's label block is auto-detected. Output is written next to the input.
"""
import sys
from pathlib import Path

from vinted4x6_core import (
    best_block, default_out, default_sheet_out,
    load_cfg, make_4x6, make_a4_sheet,
)

import pymupdf as fitz


def main():
    args = sys.argv[1:]
    if not args or "--help" in args or "-h" in args:
        print(__doc__)
        sys.exit(0)

    sheet_mode = "--sheet" in args
    landscape = "--landscape" in args
    paths = [a for a in args if not a.startswith("--")]

    if not paths:
        print("No PDF paths given.", file=sys.stderr)
        sys.exit(1)

    cfg = load_cfg()
    if landscape:
        cfg["landscape_out"] = True

    if sheet_mode:
        entries = []
        for p in paths:
            doc = fitz.open(p)
            block = best_block(doc[0], cfg)
            doc.close()
            entries.append((p, 0, block))
        out = default_sheet_out(paths[0], cfg)
        make_a4_sheet(entries, out, cfg)
        print(out)
    else:
        for p in paths:
            doc = fitz.open(p)
            crops = {i: best_block(doc[i], cfg) for i in range(doc.page_count)}
            doc.close()
            out = make_4x6(p, default_out(p, cfg), crops, cfg)
            print(out)


if __name__ == "__main__":
    main()
