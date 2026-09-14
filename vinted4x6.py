#!/usr/bin/env python3
"""
vinted4x6 - crop a shipping label off an A4 sheet and emit a 4x6 PDF.

    pip install pymupdf pillow numpy

    python vinted4x6.py                 # GUI
    python vinted4x6.py label.pdf ...   # batch, auto-detect, no window

Carrier-agnostic: it finds the label by looking for the page block that
contains barcode-like vertical bars and sits closest to a 3:2 aspect ratio,
rather than using per-carrier crop templates. Click any other block in the
preview, or drag a box, to override.

Output is vector (show_pdf_page, not a raster re-encode), so barcodes stay
sharp at any printer resolution.
"""
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF
import numpy as np

PT_PER_MM = 72.0 / 25.4
LABEL_4X6 = (4 * 72.0, 6 * 72.0)  # 288 x 432 pt
DETECT_DPI = 100
CONFIG = Path(__file__).with_suffix(".json")

DEFAULTS = {
    "bleed_mm": 1.0,       # padding added around the detected block
    "margin_mm": 2.0,      # unprintable-edge inset on the 4x6 page
    "threshold": 200,      # grayscale value below which a pixel counts as ink
    "gap_mm": 6.0,         # whitespace run that separates two blocks
    "landscape_out": False,
    "suffix": "_4x6",
}


# --------------------------------------------------------------------------
# detection
# --------------------------------------------------------------------------

@dataclass
class Block:
    x0: float
    y0: float
    x1: float
    y1: float
    score: float = 0.0
    barcode: bool = False

    @property
    def w(self):
        return self.x1 - self.x0

    @property
    def h(self):
        return self.y1 - self.y0

    def rect(self):
        return fitz.Rect(self.x0, self.y0, self.x1, self.y1)

    def padded(self, pad_pt, bounds):
        return Block(max(bounds.x0, self.x0 - pad_pt),
                     max(bounds.y0, self.y0 - pad_pt),
                     min(bounds.x1, self.x1 + pad_pt),
                     min(bounds.y1, self.y1 + pad_pt))


def _runs(mask, min_gap):
    """Spans of True in a 1-D bool array, merging gaps shorter than min_gap."""
    idx = np.flatnonzero(mask)
    if idx.size == 0:
        return []
    cuts = np.flatnonzero(np.diff(idx) > min_gap)
    starts = np.concatenate(([idx[0]], idx[cuts + 1]))
    ends = np.concatenate((idx[cuts], [idx[-1]]))
    return list(zip(starts.tolist(), (ends + 1).tolist()))


def _looks_like_barcode(sub, px_per_mm, strip_mm=4.0):
    """True if some horizontal strip is spanned top-to-bottom by many narrow
    vertical bars. Address text fails this - glyphs don't fill a strip's full
    height - so it separates the label from instructions and footers."""
    bh, bw = sub.shape
    strip = max(3, int(strip_mm * px_per_mm))
    if bh < strip:
        return False
    for top in range(0, bh - strip, max(1, strip // 2)):
        full = sub[top:top + strip].mean(axis=0) > 0.9
        if full.sum() >= max(20, 0.20 * bw):
            if np.count_nonzero(np.diff(full.astype(np.int8))) >= 12:
                return True  # alternating bars, not one solid rule
    return False


def page_ink(page, dpi=DETECT_DPI, threshold=200):
    """Binary ink mask of the page, plus px-per-point scale factors."""
    pm = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY, alpha=False)
    a = np.frombuffer(pm.samples, dtype=np.uint8).reshape(pm.height, pm.width)
    return a < threshold


def find_blocks(page, cfg):
    ink = page_ink(page, threshold=cfg["threshold"])
    h_px, w_px = ink.shape
    if not ink.any():
        return []
    r = page.rect
    px_per_mm = w_px / (r.width / PT_PER_MM)
    gap_px = max(4, int(cfg["gap_mm"] * px_per_mm))
    sx, sy = r.width / w_px, r.height / h_px

    out = []
    for y0, y1 in _runs(ink.any(axis=1), gap_px):
        band = ink[y0:y1]
        for x0, x1 in _runs(band.any(axis=0), gap_px):
            sub = band[:, x0:x1]
            bh, bw = sub.shape
            if bw < 0.05 * w_px or bh < 0.05 * h_px:
                continue
            barcode = _looks_like_barcode(sub, px_per_mm)
            area = (bw * bh) / (w_px * h_px)
            aspect = max(bw, bh) / min(bw, bh)
            score = 2.0 * area + 1.5 / (1.0 + abs(aspect - 1.5)) + 2.0 * barcode
            out.append(Block(r.x0 + x0 * sx, r.y0 + y0 * sy,
                             r.x0 + x1 * sx, r.y0 + y1 * sy, score, barcode))
    out.sort(key=lambda b: -b.score)
    return out


def best_block(page, cfg):
    blocks = find_blocks(page, cfg)
    if blocks:
        return blocks[0]
    return Block(page.rect.x0, page.rect.y0, page.rect.x1, page.rect.y1)


# --------------------------------------------------------------------------
# conversion
# --------------------------------------------------------------------------

def make_4x6(src_path, out_path, crops, cfg):
    """crops: {page_number: Block in that page's point coords}."""
    src = fitz.open(src_path)
    out = fitz.open()
    w, h = LABEL_4X6
    if cfg["landscape_out"]:
        w, h = h, w
    margin = cfg["margin_mm"] * PT_PER_MM
    bleed = cfg["bleed_mm"] * PT_PER_MM

    for pno, block in sorted(crops.items()):
        clip = block.padded(bleed, src[pno].rect).rect()
        page = out.new_page(width=w, height=h)
        target = fitz.Rect(margin, margin, w - margin, h - margin)
        # rotate so the label's long edge runs along the label's long edge
        clip_portrait = clip.height >= clip.width
        target_portrait = target.height >= target.width
        rotate = 0 if clip_portrait == target_portrait else 90
        page.show_pdf_page(target, src, pno, clip=clip,
                           keep_proportion=True, rotate=rotate)

    out.save(out_path, garbage=4, deflate=True)
    out.close()
    src.close()
    return out_path


def default_out(src_path, cfg):
    p = Path(src_path)
    return str(p.with_name(p.stem + cfg["suffix"] + ".pdf"))


def print_pdf(path):
    """Print at true size. Scaling is the usual cause of unscannable barcodes,
    so prefer SumatraPDF's noscale over the shell's print verb."""
    for exe in (r"C:\Program Files\SumatraPDF\SumatraPDF.exe",
                r"C:\Users\%s\AppData\Local\SumatraPDF\SumatraPDF.exe"
                % os.environ.get("USERNAME", "")):
        if os.path.exists(exe):
            subprocess.Popen([exe, "-print-to-default",
                              "-print-settings", "noscale", path])
            return "sent to default printer (noscale)"
    if os.name == "nt":
        os.startfile(path, "print")  # noqa: S606
        return "sent via Windows print verb - check scaling is 'Actual size'"
    subprocess.Popen(["lp", "-o", "media=Custom.4x6in", "-o",
                      "fit-to-page=false", path])
    return "sent to lp"


def load_cfg():
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.loads(CONFIG.read_text()))
    except Exception:
        pass
    return cfg


def save_cfg(cfg):
    try:
        CONFIG.write_text(json.dumps(cfg, indent=2))
    except Exception:
        pass


# --------------------------------------------------------------------------
# GUI
# --------------------------------------------------------------------------

def run_gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from PIL import Image, ImageTk

    PREVIEW_W = 420

    class App(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title("Vinted label -> 4x6")
            self.cfg = load_cfg()
            self.doc = None
            self.path = None
            self.pno = 0
            self.blocks = []
            self.crop = None
            self.scale = 1.0
            self.photo = None
            self.drag = None
            self._build()

        # -- layout ---------------------------------------------------
        def _build(self):
            bar = ttk.Frame(self, padding=6)
            bar.pack(fill="x")
            ttk.Button(bar, text="Open PDF", command=self.open).pack(side="left")
            self.b_save = ttk.Button(bar, text="Save 4x6", command=self.save,
                                     state="disabled")
            self.b_save.pack(side="left", padx=4)
            self.b_print = ttk.Button(bar, text="Save + Print",
                                      command=self.save_print, state="disabled")
            self.b_print.pack(side="left")
            ttk.Button(bar, text="Auto", command=self.auto).pack(side="left",
                                                                 padx=(12, 0))
            self.landscape = tk.BooleanVar(value=self.cfg["landscape_out"])
            ttk.Checkbutton(bar, text="6x4", variable=self.landscape,
                            command=self.on_cfg).pack(side="left", padx=8)

            self.canvas = tk.Canvas(self, width=PREVIEW_W, height=int(PREVIEW_W * 1.414),
                                    bg="#888", highlightthickness=0)
            self.canvas.pack(padx=6)
            self.canvas.bind("<Button-1>", self.on_press)
            self.canvas.bind("<B1-Motion>", self.on_drag)
            self.canvas.bind("<ButtonRelease-1>", self.on_release)

            nav = ttk.Frame(self, padding=6)
            nav.pack(fill="x")
            self.b_prev = ttk.Button(nav, text="<", width=3, command=lambda: self.go(-1))
            self.b_next = ttk.Button(nav, text=">", width=3, command=lambda: self.go(1))
            ttk.Label(nav, text="bleed mm").pack(side="left")
            self.bleed = tk.DoubleVar(value=self.cfg["bleed_mm"])
            ttk.Spinbox(nav, from_=0, to=10, increment=0.5, width=5,
                        textvariable=self.bleed, command=self.on_cfg).pack(side="left", padx=4)
            ttk.Label(nav, text="gap mm").pack(side="left")
            self.gap = tk.DoubleVar(value=self.cfg["gap_mm"])
            ttk.Spinbox(nav, from_=2, to=20, increment=1, width=5,
                        textvariable=self.gap, command=self.auto).pack(side="left", padx=4)

            self.status = ttk.Label(self, text="Open a Vinted label PDF.",
                                    padding=(8, 2, 8, 8), foreground="#333")
            self.status.pack(fill="x")

        # -- actions --------------------------------------------------
        def open(self, path=None):
            path = path or filedialog.askopenfilename(
                title="Vinted label", filetypes=[("PDF", "*.pdf")])
            if not path:
                return
            if self.doc:
                self.doc.close()
            self.doc = fitz.open(path)
            self.path = path
            self.pno = 0
            self.crops = {}
            self.b_save.state(["!disabled"])
            self.b_print.state(["!disabled"])
            if self.doc.page_count > 1:
                self.b_prev.pack(side="left", padx=(12, 2))
                self.b_next.pack(side="left")
            self.auto()

        def on_cfg(self):
            self.cfg["bleed_mm"] = self.bleed.get()
            self.cfg["gap_mm"] = self.gap.get()
            self.cfg["landscape_out"] = self.landscape.get()
            save_cfg(self.cfg)
            self.render()

        def auto(self):
            if not self.doc:
                return
            self.on_cfg_quiet()
            page = self.doc[self.pno]
            self.blocks = find_blocks(page, self.cfg)
            self.crop = self.blocks[0] if self.blocks else Block(*page.rect)
            self.crops[self.pno] = self.crop
            self.render()

        def on_cfg_quiet(self):
            self.cfg["bleed_mm"] = self.bleed.get()
            self.cfg["gap_mm"] = self.gap.get()
            self.cfg["landscape_out"] = self.landscape.get()

        def go(self, d):
            self.pno = max(0, min(self.doc.page_count - 1, self.pno + d))
            self.auto()

        def save(self, then_print=False):
            out = default_out(self.path, self.cfg)
            try:
                make_4x6(self.path, out, {self.pno: self.crop}, self.cfg)
            except Exception as e:
                messagebox.showerror("Failed", str(e))
                return
            msg = f"Saved {Path(out).name}"
            if then_print:
                msg += " - " + print_pdf(out)
            self.status.config(text=msg)

        def save_print(self):
            self.save(then_print=True)

        # -- preview --------------------------------------------------
        def render(self):
            if not self.doc:
                return
            page = self.doc[self.pno]
            self.scale = PREVIEW_W / page.rect.width
            pm = page.get_pixmap(matrix=fitz.Matrix(self.scale, self.scale),
                                 alpha=False)
            img = Image.frombytes("RGB", (pm.width, pm.height), pm.samples)
            self.photo = ImageTk.PhotoImage(img)
            c = self.canvas
            c.config(width=pm.width, height=pm.height)
            c.delete("all")
            c.create_image(0, 0, anchor="nw", image=self.photo)

            for b in self.blocks:
                if b is not self.crop:
                    c.create_rectangle(*self._to_px(b), outline="#0af",
                                       dash=(3, 3), tags="alt")
            if self.crop:
                bl = self.crop.padded(self.cfg["bleed_mm"] * PT_PER_MM, page.rect)
                c.create_rectangle(*self._to_px(bl), outline="#e01", width=2)
                ratio = max(bl.w, bl.h) / max(1e-6, min(bl.w, bl.h))
                self.status.config(
                    text=f"page {self.pno + 1}/{self.doc.page_count}  "
                         f"crop {bl.w / PT_PER_MM:.0f}x{bl.h / PT_PER_MM:.0f} mm  "
                         f"aspect {ratio:.2f} (4x6 = 1.50)  "
                         f"{'barcode found' if self.crop.barcode else 'no barcode - check the box'}"
                         "   |  click a dashed box or drag your own")

        def _to_px(self, b):
            s = self.scale
            return (b.x0 * s, b.y0 * s, b.x1 * s, b.y1 * s)

        def _to_pt(self, x, y):
            return x / self.scale, y / self.scale

        def on_press(self, e):
            self.drag = (e.x, e.y)

        def on_drag(self, e):
            if not self.drag:
                return
            self.canvas.delete("sel")
            self.canvas.create_rectangle(self.drag[0], self.drag[1], e.x, e.y,
                                         outline="#e01", width=2, tags="sel")

        def on_release(self, e):
            if not self.drag or not self.doc:
                return
            x0, y0 = self.drag
            self.drag = None
            if abs(e.x - x0) < 8 and abs(e.y - y0) < 8:
                px, py = self._to_pt(e.x, e.y)          # treat as a click
                hits = [b for b in self.blocks
                        if b.x0 <= px <= b.x1 and b.y0 <= py <= b.y1]
                if hits:
                    self.crop = min(hits, key=lambda b: b.w * b.h)
            else:
                a = self._to_pt(min(x0, e.x), min(y0, e.y))
                b = self._to_pt(max(x0, e.x), max(y0, e.y))
                self.crop = Block(a[0], a[1], b[0], b[1])
            self.crops[self.pno] = self.crop
            self.render()

    app = App()
    if len(sys.argv) > 1:
        app.open(sys.argv[1])
    app.mainloop()


def run_cli(paths):
    cfg = load_cfg()
    for p in paths:
        doc = fitz.open(p)
        crops = {i: best_block(doc[i], cfg) for i in range(doc.page_count)}
        doc.close()
        out = make_4x6(p, default_out(p, cfg), crops, cfg)
        print(out)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if args and "--gui" not in sys.argv:
        run_cli(args)
    else:
        run_gui()
