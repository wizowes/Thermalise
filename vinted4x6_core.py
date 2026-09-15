"""
vinted4x6_core - shared detection, conversion, and config used by both
the CLI and GUI entry points.

    pip install pymupdf pillow numpy
"""
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pymupdf as fitz
import numpy as np

PT_PER_MM = 72.0 / 25.4
LABEL_W, LABEL_H = 4 * 72.0, 6 * 72.0   # 288 x 432 pt (portrait 4x6)
DETECT_DPI = 100

def _config_path():
    # In a PyInstaller bundle __file__ resolves to the temp extraction dir,
    # which is deleted on exit. Use AppData so settings persist.
    appdata = os.environ.get("APPDATA")
    if appdata:
        d = Path(appdata) / "Thermalise"
        d.mkdir(exist_ok=True)
        return d / "vinted4x6.json"
    return Path(__file__).parent / "vinted4x6.json"

CONFIG = _config_path()

DEFAULTS = {
    "bleed_mm": 1.0,
    "margin_mm": 2.0,
    "threshold": 200,
    "gap_mm": 6.0,
    "landscape_out": False,
    "suffix": "_4x6",
}


# ---------------------------------------------------------------------------
# detection
# ---------------------------------------------------------------------------

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
        return Block(
            max(bounds.x0, self.x0 - pad_pt),
            max(bounds.y0, self.y0 - pad_pt),
            min(bounds.x1, self.x1 + pad_pt),
            min(bounds.y1, self.y1 + pad_pt),
        )


def _runs(mask, min_gap):
    idx = np.flatnonzero(mask)
    if idx.size == 0:
        return []
    cuts = np.flatnonzero(np.diff(idx) > min_gap)
    starts = np.concatenate(([idx[0]], idx[cuts + 1]))
    ends = np.concatenate((idx[cuts], [idx[-1]]))
    return list(zip(starts.tolist(), (ends + 1).tolist()))


def _looks_like_barcode(sub, px_per_mm, strip_mm=4.0):
    bh, bw = sub.shape
    strip = max(3, int(strip_mm * px_per_mm))
    if bh < strip:
        return False
    for top in range(0, bh - strip, max(1, strip // 2)):
        full = sub[top:top + strip].mean(axis=0) > 0.9
        if full.sum() >= max(20, 0.20 * bw):
            if np.count_nonzero(np.diff(full.astype(np.int8))) >= 12:
                return True
    return False


def page_ink(page, dpi=DETECT_DPI, threshold=200):
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
            out.append(Block(
                r.x0 + x0 * sx, r.y0 + y0 * sy,
                r.x0 + x1 * sx, r.y0 + y1 * sy,
                score, barcode,
            ))
    out.sort(key=lambda b: -b.score)
    return out


def best_block(page, cfg):
    blocks = find_blocks(page, cfg)
    return blocks[0] if blocks else Block(page.rect.x0, page.rect.y0,
                                          page.rect.x1, page.rect.y1)


# ---------------------------------------------------------------------------
# conversion
# ---------------------------------------------------------------------------

def _rotate_for_cell(clip, target):
    """Return 90 if clip and target have mismatched orientations, else 0."""
    clip_portrait = clip.height >= clip.width
    target_portrait = target.height >= target.width
    return 0 if clip_portrait == target_portrait else 90


def make_4x6(src_path, out_path, crops, cfg):
    """
    crops: {page_number: Block}  (all from src_path)
    Each crop becomes one 4x6 (or 6x4) page in the output.
    """
    src = fitz.open(src_path)
    out = fitz.open()
    w = LABEL_H if cfg["landscape_out"] else LABEL_W
    h = LABEL_W if cfg["landscape_out"] else LABEL_H
    margin = cfg["margin_mm"] * PT_PER_MM
    bleed = cfg["bleed_mm"] * PT_PER_MM

    for pno, block in sorted(crops.items()):
        clip = block.padded(bleed, src[pno].rect).rect()
        page = out.new_page(width=w, height=h)
        target = fitz.Rect(margin, margin, w - margin, h - margin)
        page.show_pdf_page(target, src, pno, clip=clip,
                           keep_proportion=True,
                           rotate=_rotate_for_cell(clip, target))

    out.save(out_path, garbage=4, deflate=True)
    out.close()
    src.close()
    return out_path


def make_a4_sheet(entries, out_path, cfg):
    """
    entries: list of (src_path, page_no, Block)
    Lays labels out 2-per-page on A4 pages, vector passthrough.
    """
    A4_W, A4_H = 595.0, 842.0
    PER_PAGE = 2
    margin = 14.0
    gap = 10.0
    bleed = cfg["bleed_mm"] * PT_PER_MM

    srcs = {}
    for path, _, _ in entries:
        if path not in srcs:
            srcs[path] = fitz.open(path)

    out = fitz.open()
    try:
        for page_start in range(0, len(entries), PER_PAGE):
            chunk = entries[page_start:page_start + PER_PAGE]
            n = len(chunk)
            page = out.new_page(width=A4_W, height=A4_H)
            cell_w = (A4_W - 2 * margin - (n - 1) * gap) / n
            cell_h = A4_H - 2 * margin

            for i, (src_path, pno, block) in enumerate(chunk):
                src = srcs[src_path]
                clip = block.padded(bleed, src[pno].rect).rect()
                x0 = margin + i * (cell_w + gap)
                target = fitz.Rect(x0, margin, x0 + cell_w, margin + cell_h)
                page.show_pdf_page(target, src, pno, clip=clip,
                                   keep_proportion=True,
                                   rotate=_rotate_for_cell(clip, target))

        out.save(out_path, garbage=4, deflate=True)
    finally:
        out.close()
        for s in srcs.values():
            s.close()

    return out_path


def default_out(src_path, cfg):
    p = Path(src_path)
    return str(p.with_name(p.stem + cfg["suffix"] + ".pdf"))


def default_sheet_out(first_path, cfg):
    p = Path(first_path)
    return str(p.parent / ("labels_sheet" + cfg["suffix"] + ".pdf"))


# ---------------------------------------------------------------------------
# printing
# ---------------------------------------------------------------------------

def print_pdf(path, cfg=None):
    """Send path to the printer.  cfg['printer'] names a specific printer;
    omit or leave blank to use the system default."""
    printer = (cfg or {}).get("printer", "").strip()
    for exe in (
        r"C:\Program Files\SumatraPDF\SumatraPDF.exe",
        r"C:\Users\%s\AppData\Local\SumatraPDF\SumatraPDF.exe"
        % os.environ.get("USERNAME", ""),
    ):
        if os.path.exists(exe):
            if printer:
                args = [exe, "-print-to", printer, "-print-settings", "noscale", path]
            else:
                args = [exe, "-print-to-default", "-print-settings", "noscale", path]
            subprocess.Popen(args)
            dest = printer or "default printer"
            return f"sent to {dest} (noscale)"
    if os.name == "nt":
        os.startfile(path, "print")  # noqa: S606
        return "sent via Windows print verb — check scaling is 'Actual size'"
    lp_args = ["lp", "-o", "media=Custom.4x6in", "-o", "fit-to-page=false"]
    if printer:
        lp_args += ["-d", printer]
    lp_args.append(path)
    subprocess.Popen(lp_args)
    return "sent to lp"


def list_printers():
    """Return list of printer names available on this system (Windows only)."""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r"SYSTEM\CurrentControlSet\Control\Print\Printers")
        printers = []
        i = 0
        while True:
            try:
                printers.append(winreg.EnumKey(key, i))
                i += 1
            except OSError:
                break
        return printers
    except Exception:
        return []


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

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
