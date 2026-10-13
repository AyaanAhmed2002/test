"""
Confidence scoring module.

Computes a deterministic, per-field confidence score between 0 and 1.

Scoring policy
--------------
0.95–1.00  Strong, direct, unambiguous evidence
0.80–0.94  Strong evidence with minor uncertainty
0.50–0.79  Plausible extraction with material ambiguity
0.01–0.49  Weak inference
0.00       Unavailable, invalid, or not extracted

Each score is computed from the evidence gathered during extraction,
not from random weights or arbitrary constants.
"""

from __future__ import annotations

from decimal import Decimal
from datetime import date
from typing import Optional


def confidence_vendor(
    match_confidence: float,
    is_unknown: bool,
) -> float:
    """
    Confidence for the vendor field.

    match_confidence comes from vendor_matcher.VendorMatch.confidence.
    """
    if is_unknown:
        return round(min(match_confidence, 0.30), 3)
    return round(min(match_confidence, 1.0), 3)


def confidence_invoice_number(
    value: str | None,
    extraction_conf: float,
) -> float:
    """Confidence for invoice number."""
    if value is None:
        return 0.0
    return round(min(extraction_conf, 1.0), 3)


def confidence_date(
    parsed_date: object,  # ParsedDate
    is_derived: bool = False,
) -> float:
    """
    Confidence for a date field.

    is_derived=True means the date was calculated from payment terms,
    not printed on the invoice.
    """
    # ParsedDate carries its own confidence
    base = getattr(parsed_date, "confidence", 0.0)
    if is_derived:
        base = min(base, 0.72)
    return round(base, 3)


def confidence_currency(
    currency_conf: float,
    is_inferred: bool,
) -> float:
    """Confidence for currency."""
    if is_inferred:
        return round(min(currency_conf, 0.55), 3)
    return round(min(currency_conf, 1.0), 3)


def confidence_amount(
    value: Decimal | None,
    extraction_conf: float,
    has_mismatch: bool = False,
) -> float:
    """Confidence for a monetary amount field."""
    if value is None:
        return 0.0
    base = extraction_conf
    if has_mismatch:
        base = min(base, 0.70)
    return round(min(base, 1.0), 3)
