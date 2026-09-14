# vinted4x6 — handoff

Convert Vinted A4 shipping-label PDFs into 4×6 PDFs for a thermal label printer.
Written blind (no PyMuPDF, no GUI, no real label PDFs in the authoring
environment). **Nothing below has been run end-to-end.** Your job is to run it on
a real machine against real labels and fix what breaks.

## Files

| File | Status |
|---|---|
| `vinted4x6.py` | Complete single-file app. Syntax-checked only. |
| `make_test_sheets.py` | Generates 3 synthetic A4 sheets. Runs clean. |

## Context

| | |
|---|---|
| User | Wesley — Python dev, comfortable with low-level detail, prefers concise answers and tables over prose |
| Actual user of the tool | His wife, non-technical. GUI must be obvious with no options she has to understand. |
| Volume | One label at a time, ad hoc. Not a batch pipeline. |
| Carriers | Mixed — Evri, Yodel, InPost, Royal Mail, whatever Vinted UK issues |
| Printer | 4×6 thermal, not yet purchased |

Mixed carriers is why there are no per-carrier crop templates. Layouts change
without notice, so detection is heuristic.

## How it works

| Stage | Implementation | Function |
|---|---|---|
| Rasterise | `page.get_pixmap(dpi=100, colorspace=csGRAY)` → numpy, ink = `< 200` | `page_ink` |
| Segment | Project ink on Y, split on whitespace runs > 6mm → bands. Project each band on X, split again → blocks. Blocks under 5% of page width or height are dropped. | `_runs`, `find_blocks` |
| Score | `2·area_frac + 1.5/(1+|aspect−1.5|) + 2·has_barcode` | `find_blocks` |
| Barcode test | Slide a 4mm strip down the block. Pass if ≥20 columns (or ≥20% of block width) are ink through the strip's **full height**, with ≥12 alternations. Text fails: glyphs don't span a strip vertically. Solid rules fail the alternation check. | `_looks_like_barcode` |
| Crop + place | New 288×432pt page, `show_pdf_page(target, src, pno, clip=…, keep_proportion=True, rotate=…)`. Vector passthrough — no raster re-encode. | `make_4x6` |
| Rotate | 90° iff crop orientation ≠ output page orientation | `make_4x6` |
| Print | SumatraPDF `-print-to-default -print-settings noscale` if found, else `os.startfile(path,"print")`, else `lp` | `print_pdf` |

Config persists to `vinted4x6.json` next to the script.

## What was actually verified

The scoring and barcode heuristic were run against the three synthetic sheets
from `make_test_sheets.py`, using poppler for rasterisation instead of PyMuPDF:

| Sheet | Top-ranked block | Barcode | Correct? |
|---|---|---|---|
| Label top-left, instructions below | 105×155 mm | yes | yes — instructions scored 0.68 vs 3.99 |
| Label centred, header above | 100×150 mm | yes | yes |
| Landscape label | 150×100 mm | yes | yes |

Everything else — PyMuPDF calls, the tkinter GUI, rotation, printing — is
unexercised.

## Test plan

1. `pip install pymupdf pillow numpy`
2. `python make_test_sheets.py` then `python vinted4x6.py mock_topleft.pdf` — CLI path, should write `mock_topleft_4x6.pdf` at exactly 288×432pt with the label filling it.
3. `python vinted4x6.py` — GUI. Open each mock, confirm the red box lands on the label and dashed boxes are clickable, drag a custom box, save.
4. Real labels, one per carrier. This is the part that matters.
5. Print one and scan the barcode with a phone app before trusting the printer.

Verify output geometry directly:

```python
import fitz; d = fitz.open("out.pdf"); print(d[0].rect)   # expect 0,0,288,432
```

## Known risks, in likelihood order

| Risk | Symptom | Fix direction |
|---|---|---|
| Full-page background rectangle or border | Whole A4 detected as one block | Detect blocks whose area > ~85% of page and re-run segmentation on their interior with the border rows/cols stripped |
| Dark carrier header with white text | Inverted ink; band may split oddly | Ink test is `< 200` only — consider `abs(v-128) > 60` or detect and invert dark regions |
| QR-only label (InPost lockers) | `has_barcode=False`, label may lose to another block | Add a 2-D detector: high edge density + roughly square block, or drop the barcode weight and lean on aspect |
| Label with a bleed line right at the sheet edge | Crop includes page furniture | Clamp to `page.rect` already done; may need an erosion pass |
| Multi-page PDF where page 2 is instructions | Page 2 converted too in CLI mode | CLI converts every page. Add a rule: skip pages whose best block has `barcode=False` |
| `show_pdf_page` + `rotate=90` aspect handling | Label squashed or rotated wrong way | If `keep_proportion` misbehaves with rotate, compute the fit matrix manually |
| Windows print verb rescales | Barcode too small to scan | Install SumatraPDF; the noscale path is the reliable one |

## Tuning knobs

| Key | Default | Raise it when |
|---|---|---|
| `threshold` | 200 | Light grey backgrounds are being read as ink |
| `gap_mm` | 6.0 | The label is being split into several blocks (raise); the label is merging with nearby text (lower) |
| `bleed_mm` | 1.0 | Edges of the label are clipped |
| `margin_mm` | 2.0 | Printer has a larger unprintable border |

`gap_mm` is exposed in the GUI and re-runs detection on change. The other three
are config-file only.

## Definition of done

- Real labels from at least three carriers convert correctly with no manual override
- Output page is exactly 288×432pt, label fills it with only the margin inset
- Printed barcode scans first time
- Wife can go PDF → printed label in two clicks without reading anything

## Deliberately out of scope

Batch folder watching, carrier auto-naming, tracking-number extraction,
right-click shell integration. Only add these if the core conversion is solid
and she asks.
