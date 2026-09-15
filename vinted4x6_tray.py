"""
vinted4x6_tray - system tray entry point for Thermalise.

Runs silently on startup. Right-click the tray icon to open the label tool,
trigger an immediate email check, open settings, or quit.

    python vinted4x6_tray.py
"""
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import pystray
from PIL import Image, ImageDraw

from vinted4x6_core import load_cfg, save_cfg
from vinted4x6_email import EmailWatcher


# ---------------------------------------------------------------------------
# tray icon — simple thermal printer silhouette, 64×64 RGBA
# ---------------------------------------------------------------------------

def _make_icon(colour="#ffffff"):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = colour
    d.rectangle([8, 22, 56, 46], fill=c)       # printer body
    d.rectangle([18, 10, 46, 26], fill=c)       # paper feed (top)
    d.rectangle([22, 42, 42, 58], fill=c)       # paper out (bottom)
    d.rectangle([12, 37, 52, 41], fill="#444")  # output slot shadow
    return img


# ---------------------------------------------------------------------------
# settings window
# ---------------------------------------------------------------------------

class SettingsWindow(tk.Toplevel):
    def __init__(self, master, cfg, on_save):
        super().__init__(master)
        self.title("Thermalise — Settings")
        self.resizable(False, False)
        self.lift()
        self.focus_force()
        self._cfg = dict(cfg)
        self._on_save = on_save
        self._build()

    def _build(self):
        p = dict(padx=8, pady=3)
        f = ttk.Frame(self, padding=14)
        f.pack(fill="both", expand=True)

        ttk.Label(f, text="Email watcher", font=("Segoe UI", 9, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))

        self._enabled = tk.BooleanVar(value=self._cfg.get("email_enabled", False))
        ttk.Checkbutton(f, text="Enable automatic email checking",
                        variable=self._enabled).grid(row=1, column=0, columnspan=2, sticky="w", **p)

        fields = [
            ("Gmail address",      "email_address",          False, 34),
            ("App password",       "email_app_password",     True,  34),
            ("Inbox folder",       "email_folder",           False, 20),
            ("Processed folder",   "email_processed_folder", False, 20),
        ]
        self._vars = {}
        for row, (label, key, secret, width) in enumerate(fields, start=2):
            ttk.Label(f, text=label).grid(row=row, column=0, sticky="e", **p)
            var = tk.StringVar(value=self._cfg.get(key, ""))
            kw = dict(show="*") if secret else {}
            ttk.Entry(f, textvariable=var, width=width, **kw).grid(
                row=row, column=1, sticky="w", **p)
            self._vars[key] = var

        ttk.Label(f, text="Poll interval (min)").grid(
            row=6, column=0, sticky="e", **p)
        self._interval = tk.IntVar(value=self._cfg.get("poll_interval_minutes", 5))
        ttk.Spinbox(f, from_=1, to=60, textvariable=self._interval,
                    width=6).grid(row=6, column=1, sticky="w", **p)

        ttk.Separator(f).grid(row=7, column=0, columnspan=2, sticky="ew", pady=10)

        note = ("Use a Gmail App Password — not your main password.\n"
                "Google Account → Security → 2-Step Verification → App passwords.")
        ttk.Label(f, text=note, foreground="#666", justify="left",
                  wraplength=340).grid(row=8, column=0, columnspan=2, sticky="w", padx=8)

        btn = ttk.Frame(f)
        btn.grid(row=9, column=0, columnspan=2, pady=(12, 0))
        ttk.Button(btn, text="Save", command=self._save).pack(side="left")
        ttk.Button(btn, text="Cancel", command=self.destroy).pack(side="left", padx=8)

    def _save(self):
        self._cfg.update({
            "email_enabled":            self._enabled.get(),
            "email_address":            self._vars["email_address"].get().strip(),
            "email_app_password":       self._vars["email_app_password"].get(),
            "email_folder":             self._vars["email_folder"].get().strip() or "INBOX",
            "email_processed_folder":   self._vars["email_processed_folder"].get().strip() or "thermalise-done",
            "poll_interval_minutes":    self._interval.get(),
        })
        self._on_save(self._cfg)
        self.destroy()


# ---------------------------------------------------------------------------
# tray app
# ---------------------------------------------------------------------------

class TrayApp:
    def __init__(self):
        self.cfg = load_cfg()
        self._status = "Idle"
        self._watcher = EmailWatcher(
            on_status=self._set_status,
            on_printed=lambda p: self._set_status(f"Printed: {Path(p).name}"),
        )

        # Hidden root keeps tkinter's mainloop alive without showing a window
        self._root = tk.Tk()
        self._root.withdraw()
        self._root.title("Thermalise")
        self._icon = None

    def run(self):
        menu = pystray.Menu(
            pystray.MenuItem("Open Label Tool", self._open_gui, default=True),
            pystray.MenuItem("Check email now", self._check_now),
            pystray.MenuItem(lambda _: f"  {self._status}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Settings…", self._open_settings),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._quit),
        )
        self._icon = pystray.Icon("thermalise", _make_icon(), "Thermalise", menu)

        if self.cfg.get("email_enabled"):
            self._watcher.start(self.cfg)

        # pystray blocks its thread; tkinter mainloop must run on the main thread
        threading.Thread(target=self._icon.run, daemon=True).start()
        self._root.mainloop()

    # ------------------------------------------------------------------

    def _set_status(self, msg):
        self._status = msg
        if self._icon:
            self._icon.title = f"Thermalise — {msg}"

    def _open_gui(self, *_):
        if getattr(sys, "frozen", False):
            # Running as a PyInstaller bundle — relaunch self with --gui
            subprocess.Popen([sys.executable, "--gui"])
        else:
            gui = Path(__file__).parent / "vinted4x6_gui.py"
            subprocess.Popen([sys.executable, str(gui)])

    def _check_now(self, *_):
        if not self.cfg.get("email_enabled"):
            self._set_status("Email watcher not enabled — see Settings")
            return
        self._watcher.check_now(self.cfg)

    def _open_settings(self, *_):
        # Settings must open on the tkinter main thread
        self._root.after(0, self._show_settings)

    def _show_settings(self):
        self._root.deiconify()

        def on_save(new_cfg):
            self.cfg.update(new_cfg)
            save_cfg(self.cfg)
            self._watcher.stop()
            if self.cfg.get("email_enabled"):
                self._watcher.start(self.cfg)

        win = SettingsWindow(self._root, self.cfg, on_save)
        win.protocol("WM_DELETE_WINDOW", lambda: (win.destroy(), self._root.withdraw()))
        win.grab_set()
        self._root.wait_window(win)
        self._root.withdraw()

    def _quit(self, *_):
        self._watcher.stop()
        self._icon.stop()
        self._root.quit()


def main():
    if "--gui" in sys.argv:
        from vinted4x6_gui import main as gui_main
        gui_main()
    else:
        TrayApp().run()


if __name__ == "__main__":
    main()
