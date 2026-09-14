"""Synthetic A4 label sheets for testing vinted4x6 detection without real customer data."""
import random
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

W, H = A4


def barcode(c, x, y, w, h):
    random.seed(7)
    cx = x
    while cx < x + w - 2:
        bw = random.choice([0.8, 0.8, 1.6, 2.4])
        if random.random() < 0.62:
            c.rect(cx, y, bw, h, stroke=0, fill=1)
        cx += bw + random.choice([0.8, 1.6])


def label_block(c, x, y, w, h, carrier):
    c.setLineWidth(0.8)
    c.rect(x, y, w, h)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(x + 6 * mm, y + h - 12 * mm, carrier)
    c.setFont("Helvetica", 9)
    for i, line in enumerate(["Jane Smith", "12 Example Road", "Flat 4",
                              "Manchester", "M1 2AB"]):
        c.drawString(x + 6 * mm, y + h - 22 * mm - i * 4.5 * mm, line)
    barcode(c, x + 6 * mm, y + 22 * mm, w - 12 * mm, 20 * mm)
    c.setFont("Helvetica", 7)
    c.drawString(x + 6 * mm, y + 16 * mm, "JD0002284993847 2038 4772")


def sheet_top_left(path):
    """Label top-left, Vinted instructions underneath."""
    c = canvas.Canvas(path, pagesize=A4)
    lw, lh = 105 * mm, 155 * mm
    label_block(c, 15 * mm, H - 15 * mm - lh, lw, lh, "EVRI")
    c.setFont("Helvetica-Bold", 11)
    c.drawString(15 * mm, 55 * mm, "How to send your parcel")
    c.setFont("Helvetica", 8)
    for i, t in enumerate(["1. Print this label and attach it to your parcel.",
                           "2. Drop it off at your nearest ParcelShop.",
                           "3. Keep your receipt until delivery is confirmed."]):
        c.drawString(15 * mm, 48 * mm - i * 5 * mm, t)
    c.save()


def sheet_centred(path):
    """Label centred with a Vinted header line above."""
    c = canvas.Canvas(path, pagesize=A4)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(20 * mm, H - 18 * mm, "vinted  |  Shipping label")
    lw, lh = 100 * mm, 150 * mm
    label_block(c, (W - lw) / 2, (H - lh) / 2 - 10 * mm, lw, lh, "InPost")
    c.setFont("Helvetica", 7)
    c.drawCentredString(W / 2, 15 * mm, "Do not fold. Place in a clear pouch.")
    c.save()


def sheet_landscape_label(path):
    """Label rotated 90 deg on the sheet (some carriers do this)."""
    c = canvas.Canvas(path, pagesize=A4)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(20 * mm, H - 15 * mm, "Royal Mail  Tracked 48")
    label_block(c, 20 * mm, 120 * mm, 150 * mm, 100 * mm, "ROYAL MAIL")
    c.save()


if __name__ == "__main__":
    sheet_top_left("mock_topleft.pdf")
    sheet_centred("mock_centred.pdf")
    sheet_landscape_label("mock_landscape.pdf")
    print("wrote 3 mock sheets")
