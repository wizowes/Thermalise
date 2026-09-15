"""
vinted4x6_email - background watchers for auto-printing Vinted labels.

EmailWatcher  — polls a Gmail inbox via IMAP.
FolderWatcher — polls a local folder for new PDFs.

Both share the same on_status / on_printed callbacks and cfg dict.
"""
import email
import imaplib
import logging
import shutil
import tempfile
import threading
from email.header import decode_header
from pathlib import Path

import pymupdf as fitz

from vinted4x6_core import Block, default_out, find_blocks, make_4x6, print_pdf

log = logging.getLogger(__name__)

GMAIL_IMAP = "imap.gmail.com"
GMAIL_PORT = 993


# ---------------------------------------------------------------------------
# shared base
# ---------------------------------------------------------------------------

class _BaseWatcher:
    def __init__(self, on_status=None, on_printed=None):
        self._stop = threading.Event()
        self._thread = None
        self.on_status = on_status or (lambda msg: None)
        self.on_printed = on_printed or (lambda path: None)

    def start(self, cfg):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, args=(cfg,), daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def check_now(self, cfg):
        threading.Thread(target=self._poll, args=(cfg,), daemon=True).start()

    def _loop(self, cfg):
        while not self._stop.is_set():
            self._poll(cfg)
            self._stop.wait(cfg.get("poll_interval_minutes", 5) * 60)

    def _poll(self, cfg):
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Gmail IMAP watcher
# ---------------------------------------------------------------------------

class EmailWatcher(_BaseWatcher):
    """Polls a Gmail inbox for unread emails with PDF attachments."""

    def _poll(self, cfg):
        addr = cfg.get("email_address", "").strip()
        pw = cfg.get("email_app_password", "")
        if not addr or not pw:
            self.on_status("Gmail: not configured")
            return
        folder = cfg.get("email_folder", "INBOX")
        done_folder = cfg.get("email_processed_folder", "thermalise-done")
        try:
            self.on_status("Gmail: checking…")
            count = _process_inbox(addr, pw, folder, done_folder, cfg,
                                   self.on_status, self.on_printed)
            self.on_status(f"Gmail: printed {count} label(s)" if count
                           else "Gmail: no new labels")
        except Exception as exc:
            log.exception("Gmail poll failed")
            self.on_status(f"Gmail error: {exc}")


def _process_inbox(addr, pw, folder, done_folder, cfg, on_status, on_printed):
    printed = 0
    with imaplib.IMAP4_SSL(GMAIL_IMAP, GMAIL_PORT) as imap:
        imap.login(addr, pw)
        imap.select(folder)
        _, data = imap.search(None, "UNSEEN")
        uids = data[0].split()
        if not uids:
            return 0
        try:
            imap.create(done_folder)
        except Exception:
            pass
        for uid in uids:
            _, msg_data = imap.fetch(uid, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])
            pdfs = _extract_pdfs(msg)
            if not pdfs:
                imap.store(uid, "+FLAGS", "\\Seen")
                continue
            for fname, pdf_bytes in pdfs:
                on_status(f"Gmail: processing {fname}…")
                try:
                    out = _convert_and_print(fname, pdf_bytes, cfg)
                    on_printed(out)
                    printed += 1
                except Exception as exc:
                    log.exception("Failed %s", fname)
                    on_status(f"Gmail failed {fname}: {exc}")
            imap.copy(uid, done_folder)
            imap.store(uid, "+FLAGS", "\\Deleted")
        imap.expunge()
    return printed


def _extract_pdfs(msg):
    results = []
    for part in msg.walk():
        if part.get_content_type() == "application/pdf":
            raw_name = part.get_filename() or "label.pdf"
            chunks = decode_header(raw_name)
            fname = "".join(
                c.decode(enc or "utf-8") if isinstance(c, bytes) else c
                for c, enc in chunks
            )
            results.append((fname, part.get_payload(decode=True)))
    return results


# ---------------------------------------------------------------------------
# local folder watcher
# ---------------------------------------------------------------------------

class FolderWatcher(_BaseWatcher):
    """Watches a local folder for new PDFs and auto-prints them."""

    def _poll(self, cfg):
        folder_str = cfg.get("watch_folder", "").strip()
        if not folder_str:
            self.on_status("Folder: not configured")
            return
        folder = Path(folder_str)
        if not folder.is_dir():
            self.on_status(f"Folder: not found ({folder})")
            return
        done_dir = folder / "processed"
        done_dir.mkdir(exist_ok=True)
        pdfs = [f for f in folder.glob("*.pdf") if f.is_file()]
        if not pdfs:
            self.on_status("Folder: no new labels")
            return
        printed = 0
        for pdf in pdfs:
            self.on_status(f"Folder: processing {pdf.name}…")
            try:
                out = _convert_and_print(pdf.name, pdf.read_bytes(), cfg)
                self.on_printed(out)
                shutil.move(str(pdf), str(done_dir / pdf.name))
                printed += 1
            except Exception as exc:
                log.exception("Failed %s", pdf.name)
                self.on_status(f"Folder failed {pdf.name}: {exc}")
        self.on_status(f"Folder: printed {printed} label(s)" if printed
                       else "Folder: no new labels")


# ---------------------------------------------------------------------------
# shared conversion helper
# ---------------------------------------------------------------------------

def _convert_and_print(fname, pdf_bytes, cfg):
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / fname
        src.write_bytes(pdf_bytes)
        out = default_out(str(src), cfg)
        doc = fitz.open(str(src))
        blocks = find_blocks(doc[0], cfg)
        block = blocks[0] if blocks else Block(*doc[0].rect)
        doc.close()
        make_4x6(str(src), out, {0: block}, cfg)
        result = print_pdf(out, cfg)
        log.info("Printed %s: %s", fname, result)
        return out
