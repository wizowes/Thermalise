#!/usr/bin/env python3
"""
vinted4x6_gui - simple GUI for converting Vinted labels to 4x6 or A4 sheet.

    python vinted4x6_gui.py [label.pdf ...]

Features:
- Add multiple label PDFs; auto-detects the crop in each
- Preview the detected label crop for any file in the list
- Save each as an individual 4x6 (or 6x4) PDF
- Combine all labels onto a single A4 sheet (2 per page)
- Send directly to the default printer
"""
import sys
from dataclasses import dataclass
from pathlib import Path

import pymupdf as fitz
from PIL import Image, ImageTk

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from vinted4x6_core import (
    Block, PT_PER_MM,
    find_blocks, best_block,
    make_4x6, make_a4_sheet,
    default_out, default_sheet_out,
    print_pdf, list_printers, load_cfg, save_cfg,
)

PREVIEW_W = 400
LIST_W = 220


@dataclass
class LabelEntry:
    path: str
    pno: int
    block: Block
    blocks: list       # all detected blocks for this page
    doc: object        # fitz.Document, kept open while in list


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Vinted Label Tool")
        self.resizable(True, True)
        self.cfg = load_cfg()
        self.entries: list[LabelEntry] = []
        self.selected_idx: int | None = None
        self._photo = None
        self._drag = None
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # -----------------------------------------------------------------------
    # layout
    # -----------------------------------------------------------------------

    def _build(self):
        # Top toolbar
        top = ttk.Frame(self, padding=(6, 6, 6, 2))
        top.pack(fill="x")
        ttk.Button(top, text="Add Labels…", command=self._add_labels).pack(side="left")
        ttk.Button(top, text="Remove", command=self._remove_selected).pack(side="left", padx=4)
        self.landscape = tk.BooleanVar(value=self.cfg.get("landscape_out", False))
        ttk.Checkbutton(top, text="6×4 landscape", variable=self.landscape,
                        command=self._on_cfg).pack(side="right")

        # Main area: file list left, preview right
        main = ttk.Frame(self, padding=(6, 0))
        main.pack(fill="both", expand=True)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(0, weight=1)

        list_frame = ttk.LabelFrame(main, text="Labels", padding=4)
        list_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self.listbox = tk.Listbox(list_frame, selectmode="single",
                                  width=28, activestyle="none",
                                  font=("Segoe UI", 9))
        self.listbox.pack(fill="both", expand=True)
        self.listbox.bind("<<ListboxSelect>>", self._on_list_select)

        preview_frame = ttk.LabelFrame(main, text="Preview", padding=4)
        preview_frame.grid(row=0, column=1, sticky="nsew")
        self.canvas = tk.Canvas(preview_frame, width=PREVIEW_W,
                                height=int(PREVIEW_W * 1.414),
                                bg="#666", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

        # Output mode
        mode_frame = ttk.LabelFrame(self, text="Output", padding=(8, 4))
        mode_frame.pack(fill="x", padx=6, pady=(4, 2))
        self.output_mode = tk.StringVar(value="individual")
        ttk.Radiobutton(mode_frame, text="Individual 4×6 files",
                        variable=self.output_mode, value="individual").pack(side="left")
        ttk.Radiobutton(mode_frame, text="Combine all onto A4 sheet",
                        variable=self.output_mode, value="sheet").pack(side="left", padx=20)

        # Fine-tune spinboxes (tucked into a small row)
        tune = ttk.Frame(self, padding=(6, 0))
        tune.pack(fill="x")
        ttk.Label(tune, text="Bleed mm").pack(side="left")
        self.bleed_var = tk.DoubleVar(value=self.cfg["bleed_mm"])
        ttk.Spinbox(tune, from_=0, to=10, increment=0.5, width=5,
                    textvariable=self.bleed_var, command=self._on_cfg).pack(side="left", padx=(2, 10))
        ttk.Label(tune, text="Gap mm").pack(side="left")
        self.gap_var = tk.DoubleVar(value=self.cfg["gap_mm"])
        ttk.Spinbox(tune, from_=2, to=20, increment=1, width=5,
                    textvariable=self.gap_var, command=self._redetect_selected).pack(side="left", padx=2)

        # Action buttons
        actions = ttk.Frame(self, padding=(6, 4))
        actions.pack(fill="x")
        self.b_save = ttk.Button(actions, text="Save", command=self._save,
                                 state="disabled")
        self.b_save.pack(side="left")
        self.b_print = ttk.Button(actions, text="Save + Print", command=self._save_print,
                                  state="disabled")
        self.b_print.pack(side="left", padx=6)

        # Status bar
        self.status = ttk.Label(self, text="Add Vinted label PDFs to get started.",
                                padding=(8, 2, 8, 6), foreground="#444")
        self.status.pack(fill="x")

    # -----------------------------------------------------------------------
    # file management
    # -----------------------------------------------------------------------

    def _add_labels(self):
        paths = filedialog.askopenfilenames(
            title="Select Vinted label PDFs",
            filetypes=[("PDF files", "*.pdf")],
        )
        for path in paths:
            self._load_entry(path)
        if self.entries and self.selected_idx is None:
            self._select(0)
        self._refresh_buttons()

    def _load_entry(self, path):
        try:
            doc = fitz.open(path)
            cfg = self._current_cfg()
            blocks = find_blocks(doc[0], cfg)
            block = blocks[0] if blocks else Block(*doc[0].rect)
            entry = LabelEntry(path=path, pno=0, block=block,
                               blocks=blocks, doc=doc)
            self.entries.append(entry)
            name = Path(path).name
            self.listbox.insert("end", f"  {name}")
            self._set_status(f"Loaded {name}")
        except Exception as e:
            messagebox.showerror("Load error", str(e))

    def _remove_selected(self):
        if self.selected_idx is None:
            return
        idx = self.selected_idx
        self.entries[idx].doc.close()
        self.entries.pop(idx)
        self.listbox.delete(idx)
        self.selected_idx = None
        self.canvas.delete("all")
        if self.entries:
            self._select(min(idx, len(self.entries) - 1))
        self._refresh_buttons()

    def _select(self, idx):
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(idx)
        self.listbox.activate(idx)
        self.selected_idx = idx
        self._render()

    def _on_list_select(self, _event=None):
        sel = self.listbox.curselection()
        if sel:
            self.selected_idx = sel[0]
            self._render()

    def _refresh_buttons(self):
        state = "normal" if self.entries else "disabled"
        self.b_save.config(state=state)
        self.b_print.config(state=state)

    # -----------------------------------------------------------------------
    # config
    # -----------------------------------------------------------------------

    def _current_cfg(self):
        cfg = dict(self.cfg)
        cfg["bleed_mm"] = self.bleed_var.get()
        cfg["gap_mm"] = self.gap_var.get()
        cfg["landscape_out"] = self.landscape.get()
        return cfg

    def _on_cfg(self):
        cfg = self._current_cfg()
        self.cfg.update(cfg)
        save_cfg(self.cfg)
        self._render()

    def _redetect_selected(self):
        if self.selected_idx is None:
            return
        entry = self.entries[self.selected_idx]
        cfg = self._current_cfg()
        entry.blocks = find_blocks(entry.doc[entry.pno], cfg)
        entry.block = entry.blocks[0] if entry.blocks else Block(*entry.doc[entry.pno].rect)
        self.cfg.update(cfg)
        save_cfg(self.cfg)
        self._render()

    # -----------------------------------------------------------------------
    # preview
    # -----------------------------------------------------------------------

    def _render(self):
        if self.selected_idx is None or not self.entries:
            return
        entry = self.entries[self.selected_idx]
        page = entry.doc[entry.pno]

        canvas_w = max(self.canvas.winfo_width(), PREVIEW_W)
        scale = canvas_w / page.rect.width
        pm = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        img = Image.frombytes("RGB", (pm.width, pm.height), pm.samples)
        self._photo = ImageTk.PhotoImage(img)
        self._scale = scale

        c = self.canvas
        c.config(width=pm.width, height=pm.height)
        c.delete("all")
        c.create_image(0, 0, anchor="nw", image=self._photo)

        for b in entry.blocks:
            if b is not entry.block:
                c.create_rectangle(*self._to_px(b), outline="#0af",
                                   dash=(3, 3), tags="alt")

        cfg = self._current_cfg()
        bleed_pt = cfg["bleed_mm"] * PT_PER_MM
        bl = entry.block.padded(bleed_pt, page.rect)
        c.create_rectangle(*self._to_px(bl), outline="#e01", width=2, tags="crop")

        ratio = max(bl.w, bl.h) / max(1e-6, min(bl.w, bl.h))
        bc = "barcode found" if entry.block.barcode else "no barcode — check the box"
        self._set_status(
            f"{Path(entry.path).name}  |  "
            f"crop {bl.w / PT_PER_MM:.0f}×{bl.h / PT_PER_MM:.0f} mm  "
            f"aspect {ratio:.2f}  {bc}   (click a dashed box or drag to override)"
        )

    def _to_px(self, b):
        s = self._scale if hasattr(self, "_scale") else 1.0
        return b.x0 * s, b.y0 * s, b.x1 * s, b.y1 * s

    def _to_pt(self, x, y):
        s = self._scale if hasattr(self, "_scale") else 1.0
        return x / s, y / s

    # -----------------------------------------------------------------------
    # canvas interaction (click / drag to override crop)
    # -----------------------------------------------------------------------

    def _on_press(self, e):
        self._drag = (e.x, e.y)

    def _on_drag(self, e):
        if not self._drag:
            return
        self.canvas.delete("sel")
        self.canvas.create_rectangle(self._drag[0], self._drag[1], e.x, e.y,
                                     outline="#e01", width=2, tags="sel")

    def _on_release(self, e):
        if not self._drag or self.selected_idx is None:
            return
        x0, y0 = self._drag
        self._drag = None
        entry = self.entries[self.selected_idx]

        if abs(e.x - x0) < 8 and abs(e.y - y0) < 8:
            # click → select alternate block
            px, py = self._to_pt(e.x, e.y)
            hits = [b for b in entry.blocks
                    if b.x0 <= px <= b.x1 and b.y0 <= py <= b.y1]
            if hits:
                entry.block = min(hits, key=lambda b: b.w * b.h)
        else:
            # drag → custom crop
            a = self._to_pt(min(x0, e.x), min(y0, e.y))
            b = self._to_pt(max(x0, e.x), max(y0, e.y))
            entry.block = Block(a[0], a[1], b[0], b[1])

        self._render()

    # -----------------------------------------------------------------------
    # save / print
    # -----------------------------------------------------------------------

    def _save(self, then_print=False):
        if not self.entries:
            return
        cfg = self._current_cfg()
        try:
            if self.output_mode.get() == "sheet":
                entries_data = [(e.path, e.pno, e.block) for e in self.entries]
                out = default_sheet_out(self.entries[0].path, cfg)
                make_a4_sheet(entries_data, out, cfg)
                msg = f"Saved {Path(out).name}"
            else:
                outs = []
                for entry in self.entries:
                    out = make_4x6(entry.path, default_out(entry.path, cfg),
                                   {entry.pno: entry.block}, cfg)
                    outs.append(Path(out).name)
                msg = "Saved: " + ", ".join(outs)
                out = default_out(self.entries[-1].path, cfg)  # last file for print

            if then_print:
                msg += "  —  " + print_pdf(out, cfg)
            self._set_status(msg)
        except Exception as e:
            messagebox.showerror("Save failed", str(e))

    def _save_print(self):
        self._save(then_print=True)

    # -----------------------------------------------------------------------
    # helpers
    # -----------------------------------------------------------------------

    def _set_status(self, text):
        self.status.config(text=text)

    def _on_close(self):
        for entry in self.entries:
            try:
                entry.doc.close()
            except Exception:
                pass
        self.destroy()


def main():
    app = App()
    for path in sys.argv[1:]:
        app._load_entry(path)
    if app.entries:
        app._select(0)
        app._refresh_buttons()
    app.mainloop()


if __name__ == "__main__":
    main()
