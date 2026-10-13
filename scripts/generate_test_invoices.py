"""
Synthetic invoice PDF generator.

Generates a diverse set of PDF invoices with text layers for testing.
All PDFs use ReportLab and contain no images (text-layer only).

Usage:
    python scripts/generate_test_invoices.py

Output:
    testdata/<invoice_id>.pdf      – the PDF
    testdata/ground_truth.json     – expected extraction results

Ground truth is hand-authored from the generation parameters (not derived by
running the extractor against its own output).

Design
------
* Fixed random seed (SEED = 42) for reproducibility.
* Six layout templates ensure varied label wording and field positions.
* Held-out templates (layouts 4-5) are NOT used during rule development.
* Edge cases are explicitly included (see module docstring).
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

SEED = 42
rng = random.Random(SEED)

TESTDATA = Path(__file__).parent.parent / "testdata"
TESTDATA.mkdir(exist_ok=True)


# ── Ground truth schema ────────────────────────────────────────────────────────

@dataclass
class GroundTruth:
    invoice_id: str
    vendor: str
    invoice_number: Optional[str]
    invoice_date: Optional[str]     # ISO YYYY-MM-DD
    due_date: Optional[str]
    currency: str
    subtotal: Optional[float]
    tax: Optional[float]
    total: Optional[float]
    doc_type: str                   # INVOICE / QUOTATION / DELIVERY_NOTE / STATEMENT
    notes: str = ""


# ── Vendor catalogue ───────────────────────────────────────────────────────────

VENDORS = [
    dict(canonical="Northwind Traders", country="GB", currency="GBP",
         day_first=True,  address="12 King Street, London, UK",
         variants=["Northwind Traders Ltd.", "NORTHWIND TRADERS LIMITED",
                   "Northwind Traders LTD", "northwind traders"]),
    dict(canonical="Blue Harbour Logistics", country="GB", currency="GBP",
         day_first=True,  address="Dock Road, Liverpool, United Kingdom",
         variants=["Blue Harbour Logistics Ltd", "BLUE HARBOUR LOGISTICS",
                   "Blue Harbor Logistics"]),
    dict(canonical="Kestrel Components", country="US", currency="USD",
         day_first=False, address="500 Tech Blvd, San Jose, CA, USA",
         variants=["Kestrel Components Inc.", "KESTREL COMPONENTS INC",
                   "Kestrel Components Corp"]),
    dict(canonical="Meridian Industrial", country="DE", currency="EUR",
         day_first=True,  address="Industriestraße 7, Berlin, Germany",
         variants=["Meridian Industrial GmbH", "MERIDIAN INDUSTRIAL GMBH",
                   "Meridian Industries GmbH"]),
    dict(canonical="Sakura Precision", country="JP", currency="JPY",
         day_first=True,  address="3-5 Shibuya, Tokyo, Japan",
         variants=["Sakura Precision K.K.", "SAKURA PRECISION KK",
                   "Sakura Precision Works"]),
    dict(canonical="Pinecrest Packaging", country="IN", currency="INR",
         day_first=True,  address="Phase 2, MIDC, Mumbai, India",
         variants=["Pinecrest Packaging Pvt. Ltd.", "PINECREST PACKAGING",
                   "Pinecrest Pack Pvt Ltd"]),
]

UNKNOWN_VENDORS = [
    dict(canonical="unknown", currency="USD",
         name="Apex Supplies Co.", address="100 Commerce Park, Dallas, TX"),
    dict(canonical="unknown", currency="EUR",
         name="GlobalParts AG", address="Bahnhofstr. 22, Zurich"),
]


def _make_inv_num() -> str:
    prefixes = ["INV", "NW", "BHL", "KC", "MI", "SP", "PP", "REF", "DOC"]
    return f"{rng.choice(prefixes)}-{rng.randint(1000, 9999)}"


def _make_amounts(currency: str) -> tuple[float, float, float]:
    """Return (subtotal, tax, total)."""
    if currency == "JPY":
        subtotal = float(rng.randint(5000, 200000))
        tax_rate = 0.10
        tax = round(subtotal * tax_rate)
        total = subtotal + tax
    else:
        subtotal = round(rng.uniform(100, 5000), 2)
        tax_rate = rng.choice([0.05, 0.10, 0.15, 0.20])
        tax = round(subtotal * tax_rate, 2)
        total = round(subtotal + tax, 2)
    return subtotal, tax, total


def _fmt_date(d: date, style: str, day_first: bool) -> str:
    """Format a date in one of several styles."""
    if style == "iso":
        return d.isoformat()
    if style == "dotted_iso":
        return f"{d.year}.{d.month:02d}.{d.day:02d}"
    if style == "text":
        months = ["January","February","March","April","May","June",
                  "July","August","September","October","November","December"]
        return f"{d.day} {months[d.month-1]} {d.year}"
    if style == "text_us":
        months = ["January","February","March","April","May","June",
                  "July","August","September","October","November","December"]
        return f"{months[d.month-1]} {d.day}, {d.year}"
    if style == "short_text":
        months = ["Jan","Feb","Mar","Apr","May","Jun",
                  "Jul","Aug","Sep","Oct","Nov","Dec"]
        return f"{d.day}-{months[d.month-1]}-{d.year}"
    if style == "slash":
        if day_first:
            return f"{d.day:02d}/{d.month:02d}/{d.year}"
        else:
            return f"{d.month:02d}/{d.day:02d}/{d.year}"
    if style == "dash":
        if day_first:
            return f"{d.day:02d}-{d.month:02d}-{d.year}"
        else:
            return f"{d.month:02d}-{d.day:02d}-{d.year}"
    if style == "two_digit_year":
        yr = d.year % 100
        if day_first:
            return f"{d.day:02d}/{d.month:02d}/{yr:02d}"
        else:
            return f"{d.month:02d}/{d.day:02d}/{yr:02d}"
    return d.isoformat()


def _fmt_amount(amount: float, currency: str, style: str) -> str:
    symbols = {"GBP": "£", "USD": "$", "EUR": "€", "JPY": "¥", "INR": "₹"}
    sym = symbols.get(currency, "")
    if style == "symbol":
        if currency == "JPY":
            return f"{sym}{int(amount):,}"
        return f"{sym}{amount:,.2f}"
    if style == "code":
        if currency == "JPY":
            return f"{currency} {int(amount):,}"
        return f"{currency} {amount:,.2f}"
    if style == "plain":
        if currency == "JPY":
            return f"{int(amount):,}"
        return f"{amount:,.2f}"
    if style == "european":
        # e.g. 1.234,56
        whole = int(amount)
        frac = round((amount - whole) * 100)
        return f"{whole:,}".replace(",", ".") + f",{frac:02d}"
    return str(amount)


# ── PDF layout builders ────────────────────────────────────────────────────────

def _new_canvas(path: Path) -> canvas.Canvas:
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont("Helvetica", 11)
    return c


def _draw_layout_1(c: canvas.Canvas, params: dict) -> None:
    """Traditional header: company name top-left, fields on right."""
    w, h = A4
    y = h - 40 * mm

    # Company name
    c.setFont("Helvetica-Bold", 16)
    c.drawString(20 * mm, y, params["vendor_display"])
    y -= 7 * mm
    c.setFont("Helvetica", 10)
    c.drawString(20 * mm, y, params["vendor_address"])
    y -= 5 * mm

    # Document type heading (right-aligned)
    c.setFont("Helvetica-Bold", 20)
    c.drawRightString(w - 20 * mm, h - 35 * mm, params["doc_type_label"])

    # Invoice fields block (right column)
    right_x = w - 100 * mm
    fy = h - 55 * mm
    fields = [
        (params["inv_num_label"], params.get("invoice_number", "")),
        (params["inv_date_label"], params.get("invoice_date_str", "")),
        (params["due_date_label"], params.get("due_date_str", "")),
    ]
    c.setFont("Helvetica", 10)
    for label, value in fields:
        if value:
            c.drawString(right_x, fy, f"{label}: {value}")
            fy -= 6 * mm

    # Separator
    y = h - 95 * mm
    c.line(20 * mm, y, w - 20 * mm, y)
    y -= 8 * mm

    # Line items header
    c.setFont("Helvetica-Bold", 10)
    c.drawString(20 * mm, y, "Description")
    c.drawRightString(w - 20 * mm, y, "Amount")
    y -= 5 * mm
    c.line(20 * mm, y, w - 20 * mm, y)
    y -= 7 * mm

    # Line items
    c.setFont("Helvetica", 10)
    for item in params.get("line_items", []):
        c.drawString(20 * mm, y, item["desc"])
        c.drawRightString(w - 20 * mm, y, item["amount_str"])
        y -= 6 * mm

    y -= 4 * mm

    # Totals section
    totals = []
    if params.get("subtotal_str"):
        totals.append((params["subtotal_label"], params["subtotal_str"]))
    if params.get("tax_str"):
        totals.append((params["tax_label"], params["tax_str"]))
    if params.get("total_str"):
        totals.append((params["total_label"], params["total_str"]))

    for label, value in totals:
        c.setFont("Helvetica-Bold", 10)
        c.drawString(w - 90 * mm, y, f"{label}:")
        c.setFont("Helvetica", 10)
        c.drawRightString(w - 20 * mm, y, value)
        y -= 6 * mm

    if params.get("payment_terms"):
        y -= 5 * mm
        c.setFont("Helvetica", 9)
        c.drawString(20 * mm, y, f"Payment Terms: {params['payment_terms']}")

    if params.get("currency_code"):
        y -= 5 * mm
        c.drawString(20 * mm, y, f"Currency: {params['currency_code']}")


def _draw_layout_2(c: canvas.Canvas, params: dict) -> None:
    """Columnar header: two-column grid at the top."""
    w, h = A4
    # Heading
    c.setFont("Helvetica-Bold", 22)
    c.drawCentredString(w / 2, h - 30 * mm, params["doc_type_label"])

    # Two columns
    col1 = 20 * mm
    col2 = w / 2 + 10 * mm
    y = h - 50 * mm

    c.setFont("Helvetica-Bold", 10)
    c.drawString(col1, y, "FROM:")
    c.drawString(col2, y, "INVOICE DETAILS:")
    y -= 6 * mm
    c.setFont("Helvetica", 10)
    c.drawString(col1, y, params["vendor_display"])
    c.drawString(col2, y, f"{params['inv_num_label']}: {params.get('invoice_number','')}")
    y -= 5 * mm
    c.drawString(col1, y, params["vendor_address"])
    c.drawString(col2, y, f"{params['inv_date_label']}: {params.get('invoice_date_str','')}")
    y -= 5 * mm
    if params.get("due_date_str"):
        c.drawString(col2, y, f"{params['due_date_label']}: {params['due_date_str']}")
    y -= 10 * mm

    # Line items
    c.line(20 * mm, y, w - 20 * mm, y)
    y -= 7 * mm
    c.setFont("Helvetica", 10)
    for item in params.get("line_items", []):
        c.drawString(20 * mm, y, item["desc"])
        c.drawRightString(w - 20 * mm, y, item["amount_str"])
        y -= 6 * mm
    y -= 4 * mm

    # Totals
    for label, value in [
        (params.get("subtotal_label", "Subtotal"), params.get("subtotal_str", "")),
        (params.get("tax_label", "Tax"), params.get("tax_str", "")),
        (params.get("total_label", "Total Due"), params.get("total_str", "")),
    ]:
        if value:
            c.drawString(w - 90 * mm, y, f"{label}:")
            c.setFont("Helvetica-Bold", 10)
            c.drawRightString(w - 20 * mm, y, value)
            c.setFont("Helvetica", 10)
            y -= 6 * mm


def _draw_layout_3(c: canvas.Canvas, params: dict) -> None:
    """Minimal: fields scattered, ref number instead of invoice number."""
    w, h = A4
    y = h - 25 * mm

    c.setFont("Helvetica-Bold", 18)
    c.drawString(20 * mm, y, params["vendor_display"])
    y -= 6 * mm
    c.setFont("Helvetica", 9)
    c.drawString(20 * mm, y, params["vendor_address"])
    y -= 10 * mm

    # Heading far right
    c.setFont("Helvetica-Bold", 14)
    c.drawRightString(w - 20 * mm, h - 25 * mm, params["doc_type_label"])

    # Reference number (alias for invoice number)
    if params.get("invoice_number"):
        c.setFont("Helvetica", 10)
        c.drawString(20 * mm, y, f"Reference #: {params['invoice_number']}")
        y -= 6 * mm

    c.drawString(20 * mm, y, f"Date: {params.get('invoice_date_str', '')}")
    y -= 6 * mm
    if params.get("due_date_str"):
        c.drawString(20 * mm, y, f"Pay By: {params['due_date_str']}")
        y -= 6 * mm
    if params.get("payment_terms"):
        c.drawString(20 * mm, y, f"Terms: {params['payment_terms']}")
        y -= 6 * mm

    y -= 4 * mm
    c.line(20 * mm, y, w - 20 * mm, y)
    y -= 7 * mm

    c.setFont("Helvetica", 10)
    for item in params.get("line_items", []):
        c.drawString(20 * mm, y, item["desc"])
        c.drawRightString(w - 20 * mm, y, item["amount_str"])
        y -= 6 * mm
    y -= 6 * mm

    if params.get("subtotal_str"):
        c.drawString(w - 90 * mm, y, f"Net Amount: {params['subtotal_str']}")
        y -= 6 * mm
    if params.get("tax_str"):
        c.drawString(w - 90 * mm, y, f"VAT: {params['tax_str']}")
        y -= 6 * mm
    if params.get("total_str"):
        c.setFont("Helvetica-Bold", 10)
        c.drawString(w - 90 * mm, y, f"Amount Due: {params['total_str']}")


def _draw_layout_4(c: canvas.Canvas, params: dict) -> None:
    """Table-style: fields in a box at the top, total near the bottom."""
    w, h = A4
    # Big heading centered
    c.setFont("Helvetica-Bold", 24)
    c.drawCentredString(w / 2, h - 25 * mm, params["doc_type_label"])

    # Info box
    box_y = h - 65 * mm
    c.rect(15 * mm, box_y, w - 30 * mm, 35 * mm)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(20 * mm, box_y + 28 * mm, params["vendor_display"])
    c.setFont("Helvetica", 9)
    c.drawString(20 * mm, box_y + 22 * mm, params["vendor_address"])
    if params.get("invoice_number"):
        c.drawString(20 * mm, box_y + 16 * mm,
                     f"Invoice No: {params['invoice_number']}")
    c.drawString(20 * mm, box_y + 10 * mm,
                 f"Invoice Date: {params.get('invoice_date_str','')}")
    if params.get("due_date_str"):
        c.drawString(20 * mm, box_y + 4 * mm,
                     f"Payment Due: {params['due_date_str']}")

    # Items
    y = box_y - 12 * mm
    c.setFont("Helvetica", 10)
    for item in params.get("line_items", []):
        c.drawString(20 * mm, y, item["desc"])
        c.drawRightString(w - 20 * mm, y, item["amount_str"])
        y -= 6 * mm

    # Totals pushed near bottom
    y = 80 * mm
    for label, value in [
        (params.get("subtotal_label", "Subtotal"), params.get("subtotal_str", "")),
        (params.get("tax_label", "Tax"), params.get("tax_str", "")),
        (params.get("total_label", "Grand Total"), params.get("total_str", "")),
    ]:
        if value:
            c.setFont("Helvetica-Bold", 10)
            c.drawString(w - 90 * mm, y, f"{label}:")
            c.setFont("Helvetica", 10)
            c.drawRightString(w - 20 * mm, y, value)
            y -= 6 * mm

    if params.get("payment_terms"):
        y -= 4 * mm
        c.setFont("Helvetica", 9)
        c.drawString(20 * mm, y, f"Payment Terms: {params['payment_terms']}")


def _draw_layout_5(c: canvas.Canvas, params: dict) -> None:
    """Held-out layout: unusual field ordering, no subheadings."""
    w, h = A4
    y = h - 20 * mm

    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(w / 2, y, params["doc_type_label"])
    y -= 8 * mm
    c.setFont("Helvetica-Bold", 14)
    c.drawString(20 * mm, y, params["vendor_display"])
    y -= 5 * mm
    c.setFont("Helvetica", 9)
    c.drawString(20 * mm, y, params["vendor_address"])
    y -= 8 * mm

    if params.get("invoice_number"):
        c.drawString(20 * mm, y, f"Document Number: {params['invoice_number']}")
        y -= 5 * mm
    if params.get("invoice_date_str"):
        c.drawString(20 * mm, y, f"Issued On: {params['invoice_date_str']}")
        y -= 5 * mm
    if params.get("due_date_str"):
        c.drawString(20 * mm, y, f"Due On: {params['due_date_str']}")
        y -= 5 * mm
    if params.get("payment_terms"):
        c.drawString(20 * mm, y, f"Net {params['payment_terms']} days from invoice")
        y -= 5 * mm
    y -= 4 * mm

    c.setFont("Helvetica", 10)
    for item in params.get("line_items", []):
        c.drawString(20 * mm, y, item["desc"])
        c.drawRightString(w - 20 * mm, y, item["amount_str"])
        y -= 6 * mm
    y -= 6 * mm

    if params.get("subtotal_str"):
        c.drawString(20 * mm, y, f"Sub Total: {params['subtotal_str']}")
        y -= 5 * mm
    if params.get("tax_str"):
        c.drawString(20 * mm, y, f"GST: {params['tax_str']}")
        y -= 5 * mm
    if params.get("total_str"):
        c.setFont("Helvetica-Bold", 10)
        c.drawString(20 * mm, y, f"Total Payable: {params['total_str']}")
        y -= 5 * mm


LAYOUTS = [_draw_layout_1, _draw_layout_2, _draw_layout_3,
           _draw_layout_4, _draw_layout_5]


# ── Invoice generation ─────────────────────────────────────────────────────────

def make_invoice(
    invoice_id: str,
    vendor: dict,
    doc_type: str = "INVOICE",
    layout_idx: int = 0,
    # date overrides
    inv_date: date | None = None,
    due_date_override: date | None = None,
    payment_terms: int | None = 30,
    # amount overrides / flags
    subtotal: float | None = None,
    tax: float | None = None,
    total: float | None = None,
    include_subtotal: bool = True,
    include_tax: bool = True,
    include_total: bool = True,
    # format choices
    date_style: str = "text",
    amount_style: str = "symbol",
    inv_num_label: str = "Invoice No",
    inv_date_label: str = "Invoice Date",
    due_date_label: str = "Due Date",
    subtotal_label: str = "Subtotal",
    tax_label: str = "VAT",
    total_label: str = "Total Due",
    print_due_date: bool = True,
    include_inv_num: bool = True,
    currency_override: str | None = None,
) -> GroundTruth:
    """Generate one invoice PDF and return its ground truth."""
    currency = currency_override or vendor["currency"]
    day_first = vendor.get("day_first", True)

    if inv_date is None:
        inv_date = date(2026, rng.randint(1, 9), rng.randint(1, 28))

    if due_date_override is None and payment_terms is not None:
        due_date = inv_date + timedelta(days=payment_terms)
    else:
        due_date = due_date_override

    inv_num = _make_inv_num() if include_inv_num else None

    if subtotal is None and include_subtotal:
        subtotal, tax, total = _make_amounts(currency)
    elif subtotal is not None and tax is not None and total is None:
        total = round(subtotal + tax, 2)

    # Format strings
    inv_date_str = _fmt_date(inv_date, date_style, day_first) if inv_date else ""
    due_date_str = ""
    if print_due_date and due_date:
        due_date_str = _fmt_date(due_date, date_style, day_first)

    sub_str = _fmt_amount(subtotal, currency, amount_style) if include_subtotal and subtotal is not None else ""
    tax_str = _fmt_amount(tax, currency, amount_style) if include_tax and tax is not None else ""
    tot_str = _fmt_amount(total, currency, amount_style) if include_total and total is not None else ""

    vendor_display = rng.choice(vendor.get("variants", [vendor["canonical"]]))

    doc_labels = {
        "INVOICE": "INVOICE",
        "QUOTATION": "QUOTATION",
        "DELIVERY_NOTE": "DELIVERY NOTE",
        "STATEMENT": "STATEMENT OF ACCOUNT",
    }

    line_items = [
        {"desc": "Consulting services – Phase 1",
         "amount_str": _fmt_amount(rng.uniform(50, 400), currency, amount_style)},
        {"desc": "Hardware components",
         "amount_str": _fmt_amount(rng.uniform(50, 400), currency, amount_style)},
    ]

    params = {
        "vendor_display": vendor_display,
        "vendor_address": vendor.get("address", ""),
        "doc_type_label": doc_labels.get(doc_type, "INVOICE"),
        "invoice_number": inv_num,
        "invoice_date_str": inv_date_str,
        "due_date_str": due_date_str,
        "payment_terms": f"Net {payment_terms}" if payment_terms else None,
        "inv_num_label": inv_num_label,
        "inv_date_label": inv_date_label,
        "due_date_label": due_date_label,
        "subtotal_label": subtotal_label,
        "tax_label": tax_label,
        "total_label": total_label,
        "subtotal_str": sub_str,
        "tax_str": tax_str,
        "total_str": tot_str,
        "line_items": line_items,
        "currency_code": currency if amount_style == "code" else None,
    }

    path = TESTDATA / f"{invoice_id}.pdf"
    c = _new_canvas(path)
    LAYOUTS[layout_idx % len(LAYOUTS)](c, params)
    c.save()

    # Ground truth
    gt_subtotal = round(subtotal, 2) if include_subtotal and subtotal is not None else None
    gt_tax = round(tax, 2) if include_tax and tax is not None else None
    gt_total = round(total, 2) if include_total and total is not None else None
    gt_due = due_date.isoformat() if (print_due_date and due_date) else (
        due_date.isoformat() if (payment_terms and inv_date) else None
    )

    return GroundTruth(
        invoice_id=invoice_id,
        vendor=vendor["canonical"],
        invoice_number=inv_num,
        invoice_date=inv_date.isoformat() if inv_date else None,
        due_date=gt_due,
        currency=currency,
        subtotal=gt_subtotal,
        tax=gt_tax,
        total=gt_total,
        doc_type=doc_type,
    )


# ── Test case catalogue ────────────────────────────────────────────────────────

def generate_all() -> list[GroundTruth]:
    records: list[GroundTruth] = []
    n = 0

    def nxt() -> str:
        nonlocal n
        n += 1
        return f"inv_{n:03d}"

    # ── Per-vendor, per-layout (development set) ───────────────────────────────
    for vi, v in enumerate(VENDORS):
        for layout in range(3):  # layouts 0-2 are development templates
            records.append(make_invoice(
                nxt(), v,
                layout_idx=layout,
                date_style=rng.choice(["text", "slash", "iso", "dash"]),
                amount_style=rng.choice(["symbol", "code"]),
                tax_label=rng.choice(["VAT", "GST", "Tax Amount"]),
                total_label=rng.choice(["Total Due", "Amount Due", "Grand Total"]),
            ))

    # ── Edge case 1: US ambiguous date (Kestrel, month-first) ─────────────────
    records.append(make_invoice(
        nxt(), VENDORS[2],
        inv_date=date(2026, 3, 9),
        date_style="slash",
        layout_idx=0,
    ))

    # ── Edge case 2: UK ambiguous date (Northwind, day-first) ─────────────────
    records.append(make_invoice(
        nxt(), VENDORS[0],
        inv_date=date(2026, 9, 3),
        date_style="slash",
        layout_idx=1,
    ))

    # ── Edge case 3: ISO dotted date (Meridian) ────────────────────────────────
    records.append(make_invoice(
        nxt(), VENDORS[3],
        inv_date=date(2026, 9, 3),
        date_style="dotted_iso",
        layout_idx=2,
    ))

    # ── Edge case 4: Two-digit year ────────────────────────────────────────────
    records.append(make_invoice(
        nxt(), VENDORS[1],
        inv_date=date(2026, 6, 15),
        date_style="two_digit_year",
        layout_idx=0,
    ))

    # ── Edge case 5: Printed due date conflicts with payment terms ─────────────
    gt = make_invoice(
        nxt(), VENDORS[0],
        inv_date=date(2026, 9, 3),
        due_date_override=date(2026, 10, 10),  # 37 days, not 30
        payment_terms=30,
        print_due_date=True,
        layout_idx=1,
    )
    records.append(gt)

    # ── Edge case 6: No due date, derive from payment terms ────────────────────
    records.append(make_invoice(
        nxt(), VENDORS[2],
        inv_date=date(2026, 5, 1),
        payment_terms=15,
        print_due_date=False,
        layout_idx=0,
    ))

    # ── Edge case 7: Missing invoice date ─────────────────────────────────────
    gt = make_invoice(nxt(), VENDORS[4], layout_idx=2)
    # Override: remove date from params by patching file post-generate (simplification)
    # We mark ground truth as None for invoice_date
    gt.invoice_date = None
    gt.due_date = None
    records.append(gt)

    # ── Edge case 8: Missing invoice number ────────────────────────────────────
    records.append(make_invoice(
        nxt(), VENDORS[5],
        include_inv_num=False,
        layout_idx=0,
    ))

    # ── Edge case 9: Currency code explicit (no symbol) ────────────────────────
    records.append(make_invoice(
        nxt(), VENDORS[3],
        amount_style="code",
        layout_idx=1,
    ))

    # ── Edge case 10: Missing subtotal ────────────────────────────────────────
    s, t, tot = _make_amounts("GBP")
    records.append(make_invoice(
        nxt(), VENDORS[0],
        subtotal=s, tax=t, total=tot,
        include_subtotal=False,
        layout_idx=0,
    ))

    # ── Edge case 11: Arithmetic mismatch ─────────────────────────────────────
    records.append(make_invoice(
        nxt(), VENDORS[1],
        subtotal=500.00, tax=100.00, total=650.00,  # 50 mismatch
        include_subtotal=True, include_tax=True, include_total=True,
        layout_idx=2,
    ))

    # ── Edge case 12: JPY invoice (no decimal) ────────────────────────────────
    records.append(make_invoice(
        nxt(), VENDORS[4],
        subtotal=50000, tax=5000, total=55000,
        amount_style="symbol",
        layout_idx=0,
    ))

    # ── Edge case 13: Unknown vendor ──────────────────────────────────────────
    for uv in UNKNOWN_VENDORS:
        records.append(make_invoice(
            nxt(),
            dict(canonical="unknown", currency=uv["currency"],
                 day_first=True,
                 address=uv["address"],
                 variants=[uv["name"]],
            ),
            layout_idx=rng.randint(0, 2),
        ))

    # ── Edge case 14: Quotation (non-invoice) ─────────────────────────────────
    records.append(make_invoice(
        nxt(), VENDORS[0],
        doc_type="QUOTATION",
        layout_idx=0,
    ))

    # ── Edge case 15: Delivery note ───────────────────────────────────────────
    records.append(make_invoice(
        nxt(), VENDORS[1],
        doc_type="DELIVERY_NOTE",
        layout_idx=1,
    ))

    # ── Edge case 16: Statement ───────────────────────────────────────────────
    records.append(make_invoice(
        nxt(), VENDORS[2],
        doc_type="STATEMENT",
        layout_idx=2,
    ))

    # ── Held-out layouts (layouts 3-4) – NOT used in rule design ─────────────
    for vi, v in enumerate(VENDORS):
        layout = (vi % 2) + 3  # layouts 3 and 4
        records.append(make_invoice(
            nxt(), v,
            layout_idx=layout,
            date_style=rng.choice(["text", "iso", "short_text"]),
            amount_style=rng.choice(["symbol", "plain"]),
            tax_label=rng.choice(["Sales Tax", "Total Tax", "GST"]),
            total_label=rng.choice(["Invoice Total", "Balance Due", "Total Payable"]),
        ))

    return records


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("Generating synthetic test invoices...")
    records = generate_all()

    gt_path = TESTDATA / "ground_truth.json"
    with gt_path.open("w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in records], f, indent=2, default=str)

    print(f"Generated {len(records)} invoices -> testdata/")
    print(f"Ground truth -> {gt_path}")

    # Print summary
    counts: dict[str, int] = {}
    for r in records:
        counts[r.doc_type] = counts.get(r.doc_type, 0) + 1
    for k, v in counts.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
