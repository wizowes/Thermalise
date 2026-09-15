"""
Redact personal/address info from the test label PDF so it's safe to keep in the repo.
Uses PyMuPDF redaction annotations — removes text from the PDF content stream.
Run once: python blank_test_label.py
"""
import pymupdf as fitz
from pathlib import Path

INPUT = Path(__file__).parent / "Vinted-Label-21815073485.pdf"
OUTPUT = Path(__file__).parent / "test-label-blank.pdf"

# Text snippets that identify address/personal blocks to redact.
# PyMuPDF search is case-insensitive by default.
REDACT_TERMS = [
    # Generic patterns that appear in Vinted UK labels
    "From:", "To:", "Sender", "Recipient",
    # Add any name/address fragments you saw on the label here
]


def redact_page(page):
    # Search and redact each term
    for term in REDACT_TERMS:
        for inst in page.search_for(term):
            page.add_redact_annot(inst, fill=(1, 1, 1))

    # Also find all text blocks and redact those that look like addresses
    # (short lines of mixed words/numbers typical of name+address blocks)
    blocks = page.get_text("blocks")  # list of (x0,y0,x1,y1, text, block_no, block_type)
    for b in blocks:
        x0, y0, x1, y1, text, *_ = b
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        # Heuristic: 2-6 lines, at least one looks like a postcode or number
        if 2 <= len(lines) <= 8:
            has_postcode = any(
                any(c.isdigit() for c in l) for l in lines
            )
            if has_postcode:
                rect = fitz.Rect(x0, y0, x1, y1)
                page.add_redact_annot(rect, fill=(1, 1, 1))

    page.apply_redactions()


def main():
    doc = fitz.open(INPUT)
    for page in doc:
        redact_page(page)
    doc.save(OUTPUT, garbage=4, deflate=True)
    doc.close()
    print(f"Saved: {OUTPUT}")


if __name__ == "__main__":
    main()
