"""
Warning generation module.

Centralises all human-readable warning string construction.
Each function returns a list of strings (possibly empty).
Warnings are deduplicated by the caller pipeline.
"""

from __future__ import annotations

from decimal import Decimal
from datetime import date


def warn_unknown_vendor(vendor_name: str) -> list[str]:
    return [f"Vendor '{vendor_name}' was not found in the canonical registry; "
            "returned as 'unknown'."]


def warn_ambiguous_date_no_locale(field: str, raw: str) -> list[str]:
    return [f"{field}: date '{raw}' is ambiguous (DD/MM vs MM/DD) and vendor "
            "locale is unknown; value set to null."]


def warn_missing_invoice_number() -> list[str]:
    return ["Invoice number not found in the document."]


def warn_missing_invoice_date() -> list[str]:
    return ["Invoice date not found in the document."]


def warn_missing_due_date(has_terms: bool) -> list[str]:
    if has_terms:
        return []  # due date was derived; no 'missing' warning
    return ["Due date not found and no payment terms available."]


def warn_derived_due_date(days: int, iso: str) -> list[str]:
    return [f"Due date derived from payment terms ({days} days) → {iso}."]


def warn_inferred_currency(currency: str, reason: str) -> list[str]:
    return [f"Currency inferred as {currency} ({reason}); no explicit "
            "currency symbol or code found."]


def warn_missing_amount(field: str) -> list[str]:
    return [f"{field.capitalize()} not found in the document."]


def warn_non_invoice(doc_type: str) -> list[str]:
    return [f"Document appears to be a {doc_type.lower().replace('_', ' ')}, "
            "not an invoice; financial fields set to null."]


def warn_unknown_doc_type() -> list[str]:
    return ["Document type could not be confirmed as an invoice; "
            "results may be incomplete."]


def warn_low_confidence(field: str, score: float) -> list[str]:
    return [f"Low confidence for field '{field}' (score: {score:.2f}); "
            "manual review recommended."]


def warn_pdf_poor_extraction() -> list[str]:
    return ["Limited text extracted from the PDF; results may be incomplete."]


def deduplicate(warnings: list[str]) -> list[str]:
    """Remove duplicate warning strings while preserving order."""
    seen: set[str] = set()
    result: list[str] = []
    for w in warnings:
        if w not in seen:
            seen.add(w)
            result.append(w)
    return result
