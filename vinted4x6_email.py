"""
vinted4x6_email - IMAP polling for auto-printing Vinted labels.

Polls a Gmail inbox for unread emails with PDF attachments, converts each
to 4x6, and prints. Processed emails are moved to a 'thermalise-done' folder
(created automatically) and deleted from the inbox.
"""
import email
import imaplib
import logging
import tempfile
import threading
from email.header import decode_header
from pathlib import Path

import pymupdf as fitz

from vinted4x6_core import Block, default_out, find_blocks, load_cfg, make_4x6, print_pdf

log = logging.getLogger(__name__)

GMAIL_IMAP = "imap.gmail.com"
GMAIL_PORT = 993


class EmailWatcher:
    """Background IMAP poller. Thread-safe; safe to stop/restart."""

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
        """Trigger an immediate poll without waiting for the interval."""
        threading.Thread(target=self._poll, args=(cfg,), daemon=True).start()

    # ------------------------------------------------------------------

    def _loop(self, cfg):
        while not self._stop.is_set():
            self._poll(cfg)
            interval_s = cfg.get("poll_interval_minutes", 5) * 60
            self._stop.wait(interval_s)

    def _poll(self, cfg):
        addr = cfg.get("email_address", "").strip()
        pw = cfg.get("email_app_password", "")
        if not addr or not pw:
            self.on_status("Email: not configured")
            return
        folder = cfg.get("email_folder", "INBOX")
        done_folder = cfg.get("email_processed_folder", "thermalise-done")
        try:
            self.on_status("Email: checking…")
            count = _process_inbox(addr, pw, folder, done_folder, cfg,
                                   self.on_status, self.on_printed)
            if count:
                self.on_status(f"Email: printed {count} label(s)")
            else:
                self.on_status("Email: no new labels")
        except Exception as exc:
            log.exception("Email poll failed")
            self.on_status(f"Email error: {exc}")


# ------------------------------------------------------------------
# internals
# ------------------------------------------------------------------

def _process_inbox(addr, pw, folder, done_folder, cfg, on_status, on_printed):
    printed = 0
    with imaplib.IMAP4_SSL(GMAIL_IMAP, GMAIL_PORT) as imap:
        imap.login(addr, pw)
        imap.select(folder)

        _, data = imap.search(None, "UNSEEN")
        uids = data[0].split()
        if not uids:
            return 0

        # Create processed folder if it doesn't exist (IMAP CREATE is idempotent-ish)
        try:
            imap.create(done_folder)
        except Exception:
            pass

        for uid in uids:
            _, msg_data = imap.fetch(uid, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])
            pdfs = _extract_pdfs(msg)
            if not pdfs:
                # No PDF attachment — mark read and leave it alone
                imap.store(uid, "+FLAGS", "\\Seen")
                continue
            for fname, pdf_bytes in pdfs:
                on_status(f"Email: processing {fname}…")
                try:
                    out = _convert_and_print(fname, pdf_bytes, cfg)
                    on_printed(out)
                    printed += 1
                except Exception as exc:
                    log.exception("Failed to process %s", fname)
                    on_status(f"Failed {fname}: {exc}")
            # Move to processed folder
            imap.copy(uid, done_folder)
            imap.store(uid, "+FLAGS", "\\Deleted")

        imap.expunge()
    return printed


def _extract_pdfs(msg):
    """Return list of (filename, bytes) for all PDF attachments in the message."""
    results = []
    for part in msg.walk():
        if part.get_content_type() == "application/pdf":
            raw_name = part.get_filename() or "label.pdf"
            # Decode RFC 2047 encoded words
            chunks = decode_header(raw_name)
            fname = "".join(
                chunk.decode(enc or "utf-8") if isinstance(chunk, bytes) else chunk
                for chunk, enc in chunks
            )
            results.append((fname, part.get_payload(decode=True)))
    return results


def _convert_and_print(fname, pdf_bytes, cfg):
    """Write PDF to a temp file, convert to 4x6, print, return output path."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / fname
        src.write_bytes(pdf_bytes)
        out = default_out(str(src), cfg)

        doc = fitz.open(str(src))
        blocks = find_blocks(doc[0], cfg)
        block = blocks[0] if blocks else Block(*doc[0].rect)
        doc.close()

        make_4x6(str(src), out, {0: block}, cfg)
        result = print_pdf(out)
        log.info("Printed %s: %s", fname, result)
        return out
