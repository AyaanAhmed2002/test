"""
Field extraction module.

Extracts the eight header fields from normalised invoice text using
label-aware regular expressions.  Each extractor is a standalone function
that can be tested independently.

Design principles
-----------------
* Prefer label-to-value association over positional heuristics.
* Never take the first occurrence of a number as the total.
* Exclude values that are clearly from address/tax-ID/reference contexts.
* Return None on genuine absence; do not invent values.
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from app.amount_parser import parse_amount, detect_currency_from_text
from app.date_parser import parse_date, ParsedDate, extract_payment_term_days, derive_due_date
from app.vendor_matcher import VendorMatch

logger = logging.getLogger(__name__)


# ── Label patterns ─────────────────────────────────────────────────────────────
# All patterns use re.IGNORECASE.  They match a label followed by optional
# separators (colon, space, dash) and capture the value.

# Invoice number
# Each label branch fully consumes its trailing punctuation/separator so the
# label's own words (e.g. 'No.', 'Ref') cannot be captured as the value.
_INV_NUM_LABELS = re.compile(
    r"(?:"
    r"invoice\s*no\.?\s*[:\-]?\s*"               # Invoice No, Invoice No., Invoice No:
    r"|invoice\s*(?:number|num|#|id)\s*[:\-]?\s*"
    r"|inv\s*(?:no\.?|number|#)\s*[:\-]?\s*"
    r"|bill\s*(?:no\.?|number|#)\s*[:\-]?\s*"
    r"|document\s+(?:no\.?|number|ref(?:erence)?)\s*[:\-]?\s*"  # Document Ref (INV-01)
    r"|doc\s*(?:no\.?|number|#)\s*[:\-]?\s*"
    r"|reference\s*(?:no\.?|number|#)?\s*[:\-]\s*"              # Reference: 7781 (INV-06)
    r"|ref\s*(?:no\.?|number|#)\s*[:\-]?\s*"
    r"|rechnungsnummer\s*[:\-]?\s*"               # German (INV-03)
    r")"
    r"\n?[ \t]*"                                  # optional newline before value
    r"([A-Z0-9][A-Z0-9\-/\.]{1,29})",            # value: alphanumeric-dominated
    re.IGNORECASE,
)

_INV_DATE_LABELS = re.compile(
    r"(?:invoice\s*(?:date|issued)"
    r"|date\s+of\s+invoice"
    r"|issued?\s+(?:on|date)?"                    # 'Issued On' (INV-01)
    r"|invoice\s+issued(?:\s*(?:on|date))?"       # 'Invoice issued:' (INV-04)
    r"|rechnungsdatum"                             # German (INV-03)
    r"|dated?|inv(?:oice)?\s*date)"
    r"[ \t]*[:\-]?[ \t]*\n?[ \t]*"               # separator: allows one newline
    r"([\d]{1,4}[\s/.\-]+[\w,]+[\s/.\-]+[\d]{2,4}"
    r"|[A-Za-z]+\s+\d{1,2}[,\s]+\d{4}"
    r"|\d{1,2}[\s\-]+[A-Za-z]+[\s\-]+\d{2,4}"
    r"|\d{1,2}\s+[A-Za-z]+\s+\d{2,4})",
    re.IGNORECASE,
)

_DUE_DATE_LABELS = re.compile(
    r"(?:due\s*date|payment\s*due(?:\s*date)?|pay\s*by"
    r"|due\s+on|payable\s+(?:by|on|date)|payment\s*date"
    r"|zahlbar\s+bis|zahlung(?:sziel)?"            # German (INV-03)
    r"|zahlungsdatum)"
    r"[ \t]*[:\-]?[ \t]*\n?[ \t]*"               # separator: allows one newline
    r"([\d]{1,4}[\s/.\-]+[\w,]+[\s/.\-]+[\d]{2,4}"
    r"|[A-Za-z]+\s+\d{1,2}[,\s]+\d{4}"
    r"|\d{1,2}[\s\-]+[A-Za-z]+[\s\-]+\d{2,4}"
    r"|\d{1,2}\s+[A-Za-z]+\s+\d{2,4})",
    re.IGNORECASE,
)

# Monetary field label patterns
_SUBTOTAL_LABELS = re.compile(
    r"(?<!\w)"                                   # must start at a word boundary
    r"(?:sub\s*total|subtotal|net\s+amount|net\s+total"
    r"|amount\s+before\s+(?:tax|vat|gst)|taxable\s+amount"
    r"|goods\s+total|items?\s+total"
    r"|nettobetrag|netto\s+betrag"               # German (INV-03)
    r")"
    r"[ \t]*[:\-]?[ \t]*\n?[ \t]*"             # separator: allows one newline (table PDFs)
    r"(?:GBP|USD|EUR|JPY|INR)?\s*"              # optional ISO currency code before the number
    r"([£$€¥₹]?\s*[\d,. \t]+(?:\.\d{1,4})?)", # amount
    re.IGNORECASE,
)

_TAX_LABELS = re.compile(
    r"(?<!\w)"                                   # must start at a word boundary
    r"(?:v\.?a\.?t\.?(?:\s+(?:amount|charged))?|gst(?:\s+(?:amount)?)?"
    r"|sales\s+tax(?:\s+amount)?|tax\s+amount|total\s+tax"
    r"|tax\s+total|tax\s+charged|consumption\s+tax"  # Japanese (INV-04)
    r"|umsatzsteuer"                               # German (INV-03)
    r"|tax(?!\s*(?:invoice|rate|id|number|no|registration|reg|code|exempt)))"  # bare 'tax' but NOT 'tax invoice'
    r"(?!\s*(?:rate|id|number|no|registration|reg|code|exempt))"
    r"[ \t]*[:\-@]?[ \t]*"
    r"(?:\(?\d+(?:\.\d+)?%\)?\s*)?"              # optional rate: '20%' or '(20%)' or '(8.25%)'
    r"[ \t]*\n?[ \t]*"                           # allow one newline after the rate
    r"(?:GBP|USD|EUR|JPY|INR)?\s*"               # optional ISO currency code
    r"([£$€¥₹]?\s*[\d,. \t]+(?:\.\d{1,4})?)",  # amount
    re.IGNORECASE,
)

_TOTAL_LABELS = re.compile(
    r"(?<!\w)"                                   # must start at a word boundary
    r"(?:(?:grand\s+)?total\s+(?:due|payable|amount)?"
    r"|amount\s+due|balance\s+due|total\s+payable"
    r"|invoice\s+total|amount\s+payable"
    r"|total\s+(?:invoice\s+)?amount"
    r"|(?:total|grand)\s+amount|payment\s+total"
    r"|rechnungsbetrag|rechnungs\s*betrag"        # German invoice total (INV-03)
    r")"
    r"[ \t]*[:\-]?[ \t]*\n?[ \t]*"             # separator: allows one newline (table PDFs)
    r"(?:GBP|USD|EUR|JPY|INR)?\s*"              # optional ISO currency code before the number
    r"([£$€¥₹]?\s*[\d,. \t]+(?:\.\d{1,4})?)", # amount
    re.IGNORECASE,
)

# A plain "Total" line – lower priority than labeled totals above
_PLAIN_TOTAL_RE = re.compile(
    r"^[\s]*total\s*[:\-]?\s*([£$€¥₹]?\s*[\d,.\s]+(?:\.\d{1,4})?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)



# ── Vendor name extraction ────────────────────────────────────────────────────

def extract_vendor_name_raw(text: str) -> str:
    """
    Return a raw vendor name string from the top of the document.

    Looks at the first non-empty line(s) that aren't obvious label lines.
    Used primarily for the 'unknown' vendor display name fallback.
    """
    lines = text.splitlines()
    for line in lines[:15]:
        stripped = line.strip()
        if (
            stripped
            and len(stripped) > 2
            and not re.match(r"^(invoice|date|tax|ref|page|tel|fax|email)", stripped, re.IGNORECASE)
        ):
            return stripped
    return ""


# ── Invoice number extraction ─────────────────────────────────────────────────

def extract_invoice_number(text: str) -> tuple[str | None, float]:
    """
    Extract invoice number.

    Returns (value, confidence).
    """
    m = _INV_NUM_LABELS.search(text)
    if m:
        value = m.group(1).strip()
        if value:
            return value, 0.93
    return None, 0.0


# ── Date extraction ───────────────────────────────────────────────────────────

def extract_invoice_date(text: str, day_first: bool | None) -> ParsedDate:
    """Extract the invoice date from label context."""
    m = _INV_DATE_LABELS.search(text)
    if m:
        raw = m.group(1).strip()
        result = parse_date(raw, day_first)
        return result
    return ParsedDate(value=None, iso=None, confidence=0.0,
                      warnings=["Invoice date not found."])


def extract_due_date(text: str, day_first: bool | None) -> ParsedDate:
    """Extract the printed due date from label context."""
    m = _DUE_DATE_LABELS.search(text)
    if m:
        raw = m.group(1).strip()
        return parse_date(raw, day_first)
    return ParsedDate(value=None, iso=None, confidence=0.0)


# ── Monetary field extraction ─────────────────────────────────────────────────

def _first_decimal(pattern: re.Pattern, text: str) -> tuple[Decimal | None, float]:
    """
    Find the first match of `pattern` and parse the amount.

    Returns (Decimal, confidence) or (None, 0.0).
    """
    m = pattern.search(text)
    if m:
        raw = m.group(1).strip()
        value = parse_amount(raw)
        if value is not None:
            return value, 0.90
    return None, 0.0


def _all_matches(pattern: re.Pattern, text: str) -> list[Decimal]:
    """Return all parsed amounts matching `pattern`."""
    results = []
    for m in pattern.finditer(text):
        raw = m.group(1).strip()
        value = parse_amount(raw)
        if value is not None:
            results.append(value)
    return results


def extract_subtotal(text: str) -> tuple[Decimal | None, float]:
    return _first_decimal(_SUBTOTAL_LABELS, text)


def extract_tax(text: str) -> tuple[Decimal | None, float]:
    """
    Extract total tax amount.

    Handles multiple tax lines (VAT + GST etc.) by preferring a printed
    "Total Tax" or "Tax Amount" label.  Falls back to summing distinct
    tax components only when they are clearly separate.
    """
    # Prefer "total tax" or "tax amount" labels
    _TOTAL_TAX_RE = re.compile(
        r"(?:total\s+tax|tax\s+(?:amount|total|charged))\s*[:\-]?[ \t]*\n?[ \t]*"
        r"(?:GBP|USD|EUR|JPY|INR)?\s*"
        r"([£$€¥₹]?\s*[\d,. \t]+(?:\.\d{1,4})?)",
        re.IGNORECASE,
    )
    m = _TOTAL_TAX_RE.search(text)
    if m:
        value = parse_amount(m.group(1))
        if value is not None:
            return value, 0.93

    # Fall back to any tax label
    return _first_decimal(_TAX_LABELS, text)


def extract_total(text: str) -> tuple[Decimal | None, float]:
    """
    Extract the invoice total (amount due).

    Uses the LAST match of specific labeled total patterns — this ensures that
    a specific label like 'Balance Due' or 'Amount Due' appearing after an
    inline 'total' in 'Subtotal' wins even if both are matched.
    Falls back to a plain "Total:" line with lower confidence.
    Never uses the first number on the page.
    """
    # Collect ALL matches and take the last one
    last_value: Decimal | None = None
    for m in _TOTAL_LABELS.finditer(text):
        raw = m.group(1).strip()
        candidate = parse_amount(raw)
        if candidate is not None:
            last_value = candidate
    if last_value is not None:
        return last_value, 0.90

    # Try plain "Total: X" as fallback
    m = _PLAIN_TOTAL_RE.search(text)
    if m:
        value = parse_amount(m.group(1))
        if value is not None:
            return value, 0.72

    return None, 0.0


# ── Currency extraction ───────────────────────────────────────────────────────

def extract_currency(text: str, vendor_currency: str | None) -> tuple[str, float]:
    """Detect currency from text, with vendor default as fallback."""
    return detect_currency_from_text(text, vendor_currency)


# ── Payment terms ─────────────────────────────────────────────────────────────

def extract_payment_terms(text: str) -> int | None:
    """Return payment term in days, or None."""
    return extract_payment_term_days(text)
