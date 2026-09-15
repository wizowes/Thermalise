"""
vinted4x6_tray - system tray entry point for Thermalise.

    Thermalise.exe          -> tray app (email/folder watcher + auto-print)
    Thermalise.exe --gui    -> manual label tool

Single-instance enforced via a named Windows mutex.
"""
import ctypes
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import pystray
from PIL import Image, ImageDraw

from vinted4x6_core import list_printers, load_cfg, save_cfg
from vinted4x6_email import EmailWatcher, FolderWatcher


# ---------------------------------------------------------------------------
# single instance
# ---------------------------------------------------------------------------

def _ensure_single_instance():
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, "Global\\ThermaliseApp")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        sys.exit(0)
    return handle  # keep reference alive for process lifetime


# ---------------------------------------------------------------------------
# startup registration (Task Scheduler)
# ---------------------------------------------------------------------------

def _startup_registered():
    r = subprocess.run(["schtasks", "/Query", "/TN", "Thermalise"],
                       capture_output=True)
    return r.returncode == 0


def _set_startup(enable):
    if enable:
        if getattr(sys, "frozen", False):
            tr = f'"{sys.executable}"'
        else:
            script = Path(__file__).parent / "vinted4x6_tray.py"
            tr = f'"{sys.executable}" "{script}"'
        subprocess.run(["schtasks", "/Create", "/F",
                        "/TN", "Thermalise", "/TR", tr,
                        "/SC", "ONLOGON", "/DELAY", "0001:00"],
                       capture_output=True)
    else:
        subprocess.run(["schtasks", "/Delete", "/F", "/TN", "Thermalise"],
                       capture_output=True)


# ---------------------------------------------------------------------------
# toast notification (best-effort, no extra deps)
# ---------------------------------------------------------------------------

def _toast(title, message):
    try:
        ctypes.windll.shell32.ShellExecuteW(
            None, "open",
            "powershell",
            f'-WindowStyle Hidden -Command "'
            f'[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null;'
            f'$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);'
            f'$t.GetElementsByTagName(\'text\')[0].AppendChild($t.CreateTextNode(\'{title}\')) | Out-Null;'
            f'$t.GetElementsByTagName(\'text\')[1].AppendChild($t.CreateTextNode(\'{message}\')) | Out-Null;'
            f'$n=[Windows.UI.Notifications.ToastNotification]::new($t);'
            f'[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier(\'Thermalise\').Show($n)"',
            None, 1,  # SW_SHOWNORMAL
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# splash screen
# ---------------------------------------------------------------------------

class SplashScreen(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.overrideredirect(True)       # no title bar / borders
        self.attributes("-topmost", True)
        self.configure(bg="#1c1c2e")

        w, h = 320, 110
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

        tk.Label(self, text="Thermalise", font=("Segoe UI", 22, "bold"),
                 bg="#1c1c2e", fg="white").pack(pady=(18, 4))
        tk.Label(self, text="Label printer — starting…", font=("Segoe UI", 10),
                 bg="#1c1c2e", fg="#888").pack()

        # thin accent bar at bottom
        tk.Frame(self, height=4, bg="#5b6af0").pack(fill="x", side="bottom")

    def close(self):
        self.destroy()


# ---------------------------------------------------------------------------
# tray icon image
# ---------------------------------------------------------------------------

def _make_icon():
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([8, 22, 56, 46], fill="white")
    d.rectangle([18, 10, 46, 26], fill="white")
    d.rectangle([22, 42, 42, 58], fill="white")
    d.rectangle([12, 37, 52, 41], fill="#444")
    return img


# ---------------------------------------------------------------------------
# settings window (tabbed)
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
        nb = ttk.Notebook(self, padding=6)
        nb.pack(fill="both", expand=True, padx=8, pady=(8, 0))

        self._build_general(nb)
        self._build_gmail(nb)
        self._build_folder(nb)

        btn = ttk.Frame(self, padding=(8, 6))
        btn.pack(fill="x")
        ttk.Button(btn, text="Save", command=self._save).pack(side="left")
        ttk.Button(btn, text="Cancel", command=self.destroy).pack(side="left", padx=8)

    # -- General tab --

    def _build_general(self, nb):
        f = ttk.Frame(nb, padding=12)
        nb.add(f, text="General")
        p = dict(padx=8, pady=3)

        self._startup = tk.BooleanVar(value=_startup_registered())
        ttk.Checkbutton(f, text="Start with Windows",
                        variable=self._startup).grid(row=0, column=0, columnspan=2,
                                                     sticky="w", **p)

        ttk.Label(f, text="Poll interval (min)").grid(row=1, column=0, sticky="e", **p)
        self._interval = tk.IntVar(value=self._cfg.get("poll_interval_minutes", 5))
        ttk.Spinbox(f, from_=1, to=60, textvariable=self._interval,
                    width=6).grid(row=1, column=1, sticky="w", **p)

        ttk.Label(f, text="Printer").grid(row=2, column=0, sticky="e", **p)
        printers = ["(default)"] + list_printers()
        self._printer = tk.StringVar(
            value=self._cfg.get("printer", "") or "(default)")
        ttk.Combobox(f, textvariable=self._printer, values=printers,
                     state="readonly", width=30).grid(row=2, column=1, sticky="w", **p)

    # -- Gmail tab --

    def _build_gmail(self, nb):
        f = ttk.Frame(nb, padding=12)
        nb.add(f, text="Gmail")
        p = dict(padx=8, pady=3)

        self._gmail_enabled = tk.BooleanVar(value=self._cfg.get("email_enabled", False))
        ttk.Checkbutton(f, text="Enable Gmail watcher",
                        variable=self._gmail_enabled).grid(row=0, column=0,
                                                           columnspan=2, sticky="w", **p)

        fields = [
            ("Gmail address",    "email_address",          False, 32),
            ("App password",     "email_app_password",     True,  32),
            ("Inbox folder",     "email_folder",           False, 18),
            ("Processed folder", "email_processed_folder", False, 18),
        ]
        self._gmail_vars = {}
        for row, (label, key, secret, width) in enumerate(fields, start=1):
            ttk.Label(f, text=label).grid(row=row, column=0, sticky="e", **p)
            var = tk.StringVar(value=self._cfg.get(key, ""))
            kw = dict(show="*") if secret else {}
            ttk.Entry(f, textvariable=var, width=width, **kw).grid(
                row=row, column=1, sticky="w", **p)
            self._gmail_vars[key] = var

        note = "Use a Gmail App Password (Google Account → Security → App passwords)."
        ttk.Label(f, text=note, foreground="#666",
                  wraplength=340, justify="left").grid(
            row=5, column=0, columnspan=2, sticky="w", padx=8, pady=(8, 0))

    # -- Folder tab --

    def _build_folder(self, nb):
        f = ttk.Frame(nb, padding=12)
        nb.add(f, text="Watch Folder")
        p = dict(padx=8, pady=3)

        self._folder_enabled = tk.BooleanVar(value=self._cfg.get("folder_enabled", False))
        ttk.Checkbutton(f, text="Enable folder watcher",
                        variable=self._folder_enabled).grid(row=0, column=0,
                                                            columnspan=3, sticky="w", **p)

        ttk.Label(f, text="Watch folder").grid(row=1, column=0, sticky="e", **p)
        self._watch_folder = tk.StringVar(value=self._cfg.get("watch_folder", ""))
        ttk.Entry(f, textvariable=self._watch_folder, width=28).grid(
            row=1, column=1, sticky="w", **p)
        ttk.Button(f, text="Browse…", command=self._browse_folder).grid(
            row=1, column=2, padx=(0, 8))

        note = ("Drop PDFs into this folder and they will be auto-printed.\n"
                "Processed files are moved to a 'processed' subfolder.")
        ttk.Label(f, text=note, foreground="#666",
                  wraplength=340, justify="left").grid(
            row=2, column=0, columnspan=3, sticky="w", padx=8, pady=(8, 0))

    def _browse_folder(self):
        d = filedialog.askdirectory(title="Select watch folder")
        if d:
            self._watch_folder.set(d)

    # -- save --

    def _save(self):
        printer_val = self._printer.get()
        self._cfg.update({
            "poll_interval_minutes":    self._interval.get(),
            "printer":                  "" if printer_val == "(default)" else printer_val,
            "email_enabled":            self._gmail_enabled.get(),
            "email_address":            self._gmail_vars["email_address"].get().strip(),
            "email_app_password":       self._gmail_vars["email_app_password"].get(),
            "email_folder":             self._gmail_vars["email_folder"].get().strip() or "INBOX",
            "email_processed_folder":   self._gmail_vars["email_processed_folder"].get().strip() or "thermalise-done",
            "folder_enabled":           self._folder_enabled.get(),
            "watch_folder":             self._watch_folder.get().strip(),
        })
        _set_startup(self._startup.get())
        self._on_save(self._cfg)
        self.destroy()


# ---------------------------------------------------------------------------
# tray app
# ---------------------------------------------------------------------------

class TrayApp:
    def __init__(self):
        self.cfg = load_cfg()
        self._status = "Idle"
        self._paused = False
        self._gui_proc = None

        cb = dict(on_status=self._set_status, on_printed=self._on_printed)
        self._email_watcher = EmailWatcher(**cb)
        self._folder_watcher = FolderWatcher(**cb)

        self._root = tk.Tk()
        self._root.withdraw()
        self._root.title("Thermalise")
        self._icon = None

    def run(self):
        splash = SplashScreen(self._root)
        self._root.update()

        self._icon = pystray.Icon(
            "thermalise", _make_icon(), "Thermalise",
            menu=pystray.Menu(
                pystray.MenuItem("Open Label Tool", self._open_gui, default=True),
                pystray.MenuItem("Check now", self._check_now),
                pystray.MenuItem(lambda _: "Pause watcher" if not self._paused
                                 else "Resume watcher", self._toggle_pause),
                pystray.MenuItem(lambda _: f"  {self._status}", None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Settings…", self._open_settings),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", self._quit),
            ),
        )
        self._start_watchers()

        def _run_icon():
            self._icon.run()

        t = threading.Thread(target=_run_icon, daemon=True)
        t.start()

        # dismiss splash after a short delay once the icon thread is running
        self._root.after(1500, splash.close)
        self._root.mainloop()

    # ------------------------------------------------------------------

    def _start_watchers(self):
        if self._paused:
            return
        if self.cfg.get("email_enabled"):
            self._email_watcher.start(self.cfg)
        if self.cfg.get("folder_enabled"):
            self._folder_watcher.start(self.cfg)

    def _stop_watchers(self):
        self._email_watcher.stop()
        self._folder_watcher.stop()

    def _set_status(self, msg):
        self._status = msg
        if self._icon:
            self._icon.title = f"Thermalise — {msg}"

    def _on_printed(self, path):
        name = Path(path).name
        self._set_status(f"Printed: {name}")
        _toast("Thermalise", f"Printed: {name}")

    def _open_gui(self, *_):
        # If GUI window already exists and is alive, bring it to focus
        hwnd = ctypes.windll.user32.FindWindowW(None, "Vinted Label Tool")
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            return
        if getattr(sys, "frozen", False):
            subprocess.Popen([sys.executable, "--gui"])
        else:
            gui = Path(__file__).parent / "vinted4x6_gui.py"
            subprocess.Popen([sys.executable, str(gui)])

    def _check_now(self, *_):
        if self._paused:
            self._set_status("Watcher paused — resume first")
            return
        if self.cfg.get("email_enabled"):
            self._email_watcher.check_now(self.cfg)
        if self.cfg.get("folder_enabled"):
            self._folder_watcher.check_now(self.cfg)
        if not self.cfg.get("email_enabled") and not self.cfg.get("folder_enabled"):
            self._set_status("No watcher enabled — check Settings")

    def _toggle_pause(self, *_):
        self._paused = not self._paused
        if self._paused:
            self._stop_watchers()
            self._set_status("Paused")
        else:
            self._start_watchers()
            self._set_status("Resumed")

    def _open_settings(self, *_):
        self._root.after(0, self._show_settings)

    def _show_settings(self):
        self._root.deiconify()

        def on_save(new_cfg):
            self.cfg.update(new_cfg)
            save_cfg(self.cfg)
            self._stop_watchers()
            self._start_watchers()

        win = SettingsWindow(self._root, self.cfg, on_save)
        win.protocol("WM_DELETE_WINDOW", lambda: (win.destroy(), self._root.withdraw()))
        win.grab_set()
        self._root.wait_window(win)
        self._root.withdraw()

    def _quit(self, *_):
        # pystray callbacks run on a non-tkinter thread; schedule on main thread
        self._root.after(0, self._confirm_quit)

    def _confirm_quit(self):
        self._root.deiconify()
        if messagebox.askyesno(
            "Quit Thermalise",
            "Stop the watcher and quit?\n\nLabels will not be auto-printed while Thermalise is closed.",
            parent=self._root,
        ):
            self._stop_watchers()
            self._icon.stop()
            self._root.quit()
        else:
            self._root.withdraw()


def main():
    if "--gui" in sys.argv:
        sys.argv.remove("--gui")   # strip flag so GUI doesn't try to open it as a file
        from vinted4x6_gui import main as gui_main
        gui_main()
    else:
        _mutex = _ensure_single_instance()  # noqa: F841 — keep alive
        TrayApp().run()


if __name__ == "__main__":
    main()
