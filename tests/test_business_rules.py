"""
Tests for business rules:
- Financial validation
- Date ordering
- Due date vs payment terms conflict
- Payment term derivation priority
- Non-invoice document null behaviour
"""

import pytest
from decimal import Decimal
from datetime import date

from app.validators import validate_financials, validate_dates, validate_due_date_vs_terms
from app.pipeline import run_extraction_pipeline
from app.document_classifier import classify_document, DocumentType


class TestFinancialValidation:
    def test_correct_arithmetic(self):
        warnings = validate_financials(
            Decimal("361.60"), Decimal("72.32"), Decimal("433.92")
        )
        assert warnings == []

    def test_mismatch_detected(self):
        warnings = validate_financials(
            Decimal("500.00"), Decimal("100.00"), Decimal("650.00")
        )
        assert len(warnings) == 1
        assert "mismatch" in warnings[0].lower()

    def test_missing_field_skips_validation(self):
        """When subtotal is None, we can't validate, so no warning."""
        warnings = validate_financials(None, Decimal("100.00"), Decimal("650.00"))
        assert warnings == []

    def test_tolerance_accepted(self):
        """Difference of 0.005 should not trigger a warning (within 0.01 tolerance)."""
        warnings = validate_financials(
            Decimal("100.00"), Decimal("20.005"), Decimal("120.00")
        )
        # 100.00 + 20.005 = 120.005, diff from 120.00 = 0.005 ≤ 0.01 → ok
        assert warnings == []

    def test_tolerance_exceeded(self):
        warnings = validate_financials(
            Decimal("100.00"), Decimal("20.02"), Decimal("120.00")
        )
        # 100 + 20.02 = 120.02, diff = 0.02 > 0.01 → mismatch
        assert len(warnings) == 1


class TestDateValidation:
    def test_valid_dates(self):
        warnings = validate_dates(date(2026, 9, 3), date(2026, 10, 3))
        assert warnings == []

    def test_due_before_invoice(self):
        warnings = validate_dates(date(2026, 9, 3), date(2026, 8, 1))
        assert len(warnings) == 1

    def test_same_dates(self):
        warnings = validate_dates(date(2026, 9, 3), date(2026, 9, 3))
        assert warnings == []

    def test_none_dates_no_crash(self):
        assert validate_dates(None, None) == []
        assert validate_dates(date(2026, 9, 3), None) == []


class TestDueDateConflict:
    def test_conflict_detected(self):
        printed = date(2026, 10, 10)
        derived = date(2026, 10, 3)
        warnings = validate_due_date_vs_terms(printed, derived, 30)
        assert len(warnings) == 1
        assert "differs" in warnings[0].lower()

    def test_no_conflict(self):
        printed = date(2026, 10, 3)
        derived = date(2026, 10, 3)
        warnings = validate_due_date_vs_terms(printed, derived, 30)
        assert warnings == []

    def test_missing_printed_no_conflict(self):
        warnings = validate_due_date_vs_terms(None, date(2026, 10, 3), 30)
        assert warnings == []


class TestPipelineBusinessRules:
    def test_printed_due_date_preferred(self):
        """Printed due date must take precedence over calculated one."""
        text = (
            "Northwind Traders\n12 King Street, London, UK\n\n"
            "INVOICE\n"
            "Invoice No: NW-1042\n"
            "Invoice Date: 3 September 2026\n"
            "Due Date: 10 October 2026\n"
            "Payment Terms: Net 30\n\n"
            "Subtotal: £361.60\nVAT: £72.32\nTotal Due: £433.92\n"
        )
        result = run_extraction_pipeline(text)
        # Printed due date (Oct 10) should be returned, not derived (Oct 3)
        assert result.due_date == "2026-10-10"
        # Conflict warning should be present
        assert any("differs" in w.lower() or "conflict" in w.lower()
                   or "printed" in w.lower() for w in result.warnings)

    def test_derived_due_date_from_terms(self):
        """When no printed due date exists, derive from payment terms."""
        text = (
            "Northwind Traders\n12 King Street, London, UK\n\n"
            "INVOICE\n"
            "Invoice No: NW-1042\n"
            "Invoice Date: 3 September 2026\n"
            "Payment Terms: Net 30\n\n"
            "Subtotal: £361.60\nVAT: £72.32\nTotal Due: £433.92\n"
        )
        result = run_extraction_pipeline(text)
        assert result.due_date == "2026-10-03"
        # Should have a derived-due-date warning
        assert any("derived" in w.lower() or "payment terms" in w.lower()
                   for w in result.warnings)

    def test_no_due_date_no_terms_null(self):
        """If no due date and no terms, due_date must be null."""
        text = (
            "Northwind Traders\n12 King Street, London, UK\n\n"
            "INVOICE\n"
            "Invoice No: NW-100\n"
            "Invoice Date: 3 September 2026\n\n"
            "Total Due: £100.00\n"
        )
        result = run_extraction_pipeline(text)
        assert result.due_date is None

    def test_arithmetic_mismatch_values_preserved(self):
        """Extracted values must not be silently corrected."""
        text = (
            "Northwind Traders\nLondon, UK\nINVOICE\n"
            "Invoice No: NW-999\n"
            "Invoice Date: 3 September 2026\n"
            "Subtotal: £500.00\nVAT: £100.00\nTotal Due: £650.00\n"
        )
        result = run_extraction_pipeline(text)
        assert result.subtotal == 500.00
        assert result.tax == 100.00
        assert result.total == 650.00
        assert any("mismatch" in w.lower() for w in result.warnings)
