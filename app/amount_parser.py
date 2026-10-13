"""
Monetary amount parser module.

Uses Python's Decimal throughout to avoid floating-point errors.
Converts to float only when constructing the final JSON-compatible response.

Number format support
---------------------
  1,234.56   – UK/US: comma = thousands separator, period = decimal
  1.234,56   – European: period = thousands separator, comma = decimal
  1 234,56   – Space as thousands separator with comma decimal
  £433.92    – Currency symbol prefix
  USD 242.17 – Currency code prefix
  12000      – Plain integer (e.g. JPY)
  (100.00)   – Parenthesized negative

The format is inferred from the surrounding vendor locale and number structure.
"""

from __future__ import annotations

import re
import logging
from decimal import Decimal, InvalidOperation
from typing import Optional

from app.config import SUPPORTED_CURRENCIES

logger = logging.getLogger(__name__)

# ── Currency symbol / code maps ────────────────────────────────────────────────

SYMBOL_TO_CODE: dict[str, str] = {
    "£": "GBP",
    "$": "USD",
    "€": "EUR",
    "¥": "JPY",
    "₹": "INR",
}

CODE_RE = re.compile(
    r"\b(GBP|USD|EUR|JPY|INR)\b",
    re.IGNORECASE,
)

SYMBOL_RE = re.compile(r"[£$€¥₹]")

# A raw number possibly preceded by a currency symbol/code
_AMOUNT_RE = re.compile(
    r"""
    (?:[£$€¥₹]|GBP|USD|EUR|JPY|INR)?\s*    # optional currency prefix
    (                                         # capture the numeric part
        \(?\s*                                # optional opening paren (negative)
        \d{1,3}                               # leading digits
        (?:[,.\s]\d{3})*                      # optional thousands groups
        (?:[.,]\d{1,4})?                      # optional decimal portion
        \s*\)?                                # optional closing paren
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


# ── Number parsing ─────────────────────────────────────────────────────────────

def _infer_format_and_parse(raw: str) -> Decimal | None:
    """
    Convert a raw number string to Decimal.

    Heuristics for format detection:
    - If the string has both ',' and '.':
        - Last separator is the decimal separator.
        - Other separator is thousands separator.
    - If only one separator:
        - If exactly 3 digits follow it → likely thousands separator (no decimals).
        - Otherwise → decimal separator.
    - Parenthesised numbers are treated as negative.
    """
    raw = raw.strip()
    negative = raw.startswith("(") and raw.endswith(")")
    raw = raw.strip("() ")

    # Remove space-based thousands separator
    # e.g. "1 234,56" → "1234,56"
    raw_no_space = re.sub(r"(\d)\s(\d)", r"\1\2", raw)

    has_comma = "," in raw_no_space
    has_period = "." in raw_no_space

    if has_comma and has_period:
        # Last one is decimal separator
        last_comma = raw_no_space.rfind(",")
        last_period = raw_no_space.rfind(".")
        if last_period > last_comma:
            # European false alarm: "1.234,56" style → remove commas
            # Actually: period is thousands, comma is decimal
            # → No: last_period > last_comma means period comes after comma
            # So the decimal separator is period → EU style with period at end?
            # e.g. "1,234.56" → comma=thousands, period=decimal ✓
            normalized = raw_no_space.replace(",", "")
        else:
            # last_comma > last_period → comma is decimal separator
            # e.g. "1.234,56" → period=thousands, comma=decimal
            normalized = raw_no_space.replace(".", "").replace(",", ".")
    elif has_comma:
        # Only comma: is it thousands or decimal?
        parts = raw_no_space.split(",")
        if len(parts) == 2 and len(parts[1]) == 3 and parts[0].isdigit():
            # e.g. "1,234" → thousands separator (integer)
            normalized = raw_no_space.replace(",", "")
        else:
            # e.g. "1,56" or "1234,56" → decimal separator
            normalized = raw_no_space.replace(",", ".")
    elif has_period:
        parts = raw_no_space.split(".")
        if len(parts) == 2 and len(parts[1]) == 3 and parts[0].isdigit():
            # e.g. "1.234" → ambiguous; treat as thousands separator
            # (plain integers more common than 3-decimal amounts)
            normalized = raw_no_space.replace(".", "")
        else:
            # e.g. "433.92" → decimal separator
            normalized = raw_no_space
    else:
        normalized = raw_no_space

    try:
        value = Decimal(normalized)
        return -value if negative else value
    except InvalidOperation:
        logger.debug("Could not parse number: %r (normalized: %r)", raw, normalized)
        return None


def parse_amount(raw: str) -> Optional[Decimal]:
    """
    Parse a raw amount string (which may include a currency symbol) to Decimal.
    Returns None if parsing fails.
    """
    # Strip currency symbols and codes from the front/back
    cleaned = re.sub(r"^[£$€¥₹\s]+", "", raw.strip())
    cleaned = re.sub(r"^(GBP|USD|EUR|JPY|INR)\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip()

    if not cleaned:
        return None

    return _infer_format_and_parse(cleaned)


def round_amount(value: Decimal) -> Decimal:
    """Round to 2 decimal places using ROUND_HALF_UP."""
    from decimal import ROUND_HALF_UP
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def decimal_to_float(value: Decimal) -> float:
    """Convert Decimal to float for JSON serialisation."""
    return float(round_amount(value))


# ── Currency detection ─────────────────────────────────────────────────────────

def detect_currency_from_text(
    text: str,
    vendor_currency: str | None = None,
) -> tuple[str, float]:
    """
    Detect the invoice currency.

    Priority:
    1. Explicit ISO currency code (GBP, USD, EUR, JPY, INR).
    2. Unambiguous symbol (£ → GBP, € → EUR, ₹ → INR).
    3. $ symbol with vendor evidence (USD) or fallback.
    4. ¥ symbol (JPY).
    5. Vendor default currency.
    6. Fallback with warning.

    Returns
    -------
    (currency_code, confidence)
    """
    text_upper = text.upper()

    # 1. Explicit ISO codes
    for code in SUPPORTED_CURRENCIES:
        if re.search(r"\b" + code + r"\b", text_upper):
            return code, 0.97

    # 2. Unambiguous symbols
    if "£" in text:
        return "GBP", 0.95
    if "€" in text:
        return "EUR", 0.95
    if "₹" in text:
        return "INR", 0.95

    # 3. $ – could be USD or other dollar
    if "$" in text:
        # Vendor evidence helps
        if vendor_currency == "USD":
            return "USD", 0.90
        # No vendor evidence; still likely USD for our corpus
        return "USD", 0.65

    # 4. ¥ – could be JPY or CNY; our registry only has JPY
    if "¥" in text:
        if vendor_currency == "JPY":
            return "JPY", 0.90
        return "JPY", 0.65

    # 5. Vendor default
    if vendor_currency is not None:
        return vendor_currency, 0.55

    # 6. No evidence at all
    return "USD", 0.10  # worst-case fallback; will trigger warning
