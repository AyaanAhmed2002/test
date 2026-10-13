"""
Financial and business-rule validation module.

Validates extracted fields for:
1. Arithmetic consistency: subtotal + tax ≈ total
2. Date ordering: invoice_date ≤ due_date
3. Missing required fields
4. Derived due date vs printed due date conflicts

All comparisons use Decimal arithmetic.
Returns a list of warning strings and a dict of confidence adjustments.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.config import AMOUNT_TOLERANCE


def validate_financials(
    subtotal: Decimal | None,
    tax: Decimal | None,
    total: Decimal | None,
) -> list[str]:
    """
    Check subtotal + tax ≈ total.

    Returns a list of warning strings (empty when no issues).
    Does NOT modify the values.
    """
    warnings: list[str] = []

    if subtotal is None or tax is None or total is None:
        # Cannot validate incomplete data; other warnings handle missing fields
        return warnings

    calculated = subtotal + tax
    tolerance = Decimal(AMOUNT_TOLERANCE)
    diff = abs(calculated - total)

    if diff > tolerance:
        warnings.append(
            f"Financial mismatch: subtotal ({subtotal}) + tax ({tax}) = "
            f"{calculated}, but total is {total} "
            f"(difference: {diff}). Printed values preserved."
        )

    return warnings


def validate_dates(
    invoice_date: date | None,
    due_date: date | None,
) -> list[str]:
    """
    Check that due_date is not before invoice_date.
    """
    warnings: list[str] = []
    if invoice_date and due_date and due_date < invoice_date:
        warnings.append(
            f"Due date ({due_date.isoformat()}) is before invoice date "
            f"({invoice_date.isoformat()}). Please verify."
        )
    return warnings


def validate_due_date_vs_terms(
    printed_due: date | None,
    derived_due: date | None,
    payment_days: int | None,
) -> list[str]:
    """
    If both a printed due date and a payment-term-derived date exist and
    they differ by more than 1 day, add a warning.
    """
    warnings: list[str] = []
    if printed_due is None or derived_due is None or payment_days is None:
        return warnings

    diff = abs((printed_due - derived_due).days)
    if diff > 1:
        warnings.append(
            f"Printed due date ({printed_due.isoformat()}) differs from the "
            f"date derived from payment terms ({payment_days} days → "
            f"{derived_due.isoformat()}) by {diff} days. "
            "Printed due date is preserved."
        )

    return warnings
