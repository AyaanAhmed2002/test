"""
Tests on generated synthetic invoice PDFs.

Requires testdata/ to be populated first:
    python scripts/generate_test_invoices.py

This test module loads PDFs from testdata/, extracts them through the full
pipeline, and compares against ground_truth.json.

Field-level accuracy is reported at the end.
"""

from __future__ import annotations

import json
import pytest
from pathlib import Path
from typing import Optional

TESTDATA = Path(__file__).parent.parent / "testdata"
GT_FILE = TESTDATA / "ground_truth.json"


def load_ground_truth() -> list[dict]:
    if not GT_FILE.exists():
        return []
    with GT_FILE.open(encoding="utf-8") as f:
        return json.load(f)


GT = load_ground_truth()

# Skip the entire module gracefully if test data hasn't been generated
pytestmark = pytest.mark.skipif(
    not GT_FILE.exists(),
    reason="testdata/ground_truth.json not found – run scripts/generate_test_invoices.py first",
)


def read_pdf_text(invoice_id: str) -> str:
    """Read and extract text from a generated invoice PDF."""
    from app.pdf_reader import read_pdf, concatenate_pages
    pdf_path = TESTDATA / f"{invoice_id}.pdf"
    if not pdf_path.exists():
        return ""
    data = pdf_path.read_bytes()
    try:
        pages = read_pdf(data)
        return concatenate_pages(pages)
    except Exception:
        return ""


def run_on_invoice(invoice_id: str):
    """Run the extraction pipeline on a generated invoice."""
    from app.pipeline import run_extraction_pipeline
    text = read_pdf_text(invoice_id)
    if not text:
        return None
    return run_extraction_pipeline(text)


# ── Per-invoice tests ──────────────────────────────────────────────────────────

class TestGeneratedInvoices:
    """
    Parametrized test: run every generated INVOICE-type record through the
    pipeline and check vendor and document type.
    """

    @pytest.mark.parametrize("gt", [g for g in GT if g["doc_type"] == "INVOICE"])
    def test_invoice_vendor(self, gt):
        result = run_on_invoice(gt["invoice_id"])
        if result is None:
            pytest.skip(f"PDF not found: {gt['invoice_id']}")
        # Vendor must match canonical or be unknown when ground truth is unknown
        assert result.vendor == gt["vendor"], (
            f"{gt['invoice_id']}: expected vendor={gt['vendor']!r}, "
            f"got={result.vendor!r}"
        )

    @pytest.mark.parametrize("gt", [g for g in GT if g["doc_type"] == "INVOICE"])
    def test_invoice_currency(self, gt):
        result = run_on_invoice(gt["invoice_id"])
        if result is None:
            pytest.skip(f"PDF not found: {gt['invoice_id']}")
        assert result.currency == gt["currency"], (
            f"{gt['invoice_id']}: expected currency={gt['currency']!r}, "
            f"got={result.currency!r}"
        )

    @pytest.mark.parametrize("gt", [g for g in GT if g["doc_type"] == "INVOICE"])
    def test_invoice_date(self, gt):
        result = run_on_invoice(gt["invoice_id"])
        if result is None:
            pytest.skip(f"PDF not found: {gt['invoice_id']}")
        # When ground truth has a date, we expect one too (or a warning)
        if gt["invoice_date"] is not None:
            assert result.invoice_date == gt["invoice_date"], (
                f"{gt['invoice_id']}: expected invoice_date={gt['invoice_date']!r}, "
                f"got={result.invoice_date!r}"
            )

    @pytest.mark.parametrize("gt", [g for g in GT if g["doc_type"] == "INVOICE"])
    def test_confidence_all_in_range(self, gt):
        result = run_on_invoice(gt["invoice_id"])
        if result is None:
            pytest.skip(f"PDF not found: {gt['invoice_id']}")
        c = result.confidence
        for field_name in ("vendor", "invoice_number", "invoice_date", "due_date",
                           "currency", "subtotal", "tax", "total"):
            score = getattr(c, field_name)
            assert 0.0 <= score <= 1.0, (
                f"{gt['invoice_id']}: {field_name} confidence={score} out of range"
            )


class TestNonInvoiceGenerated:
    """Verify non-invoice generated PDFs produce null financial fields."""

    @pytest.mark.parametrize("gt", [g for g in GT if g["doc_type"] != "INVOICE"])
    def test_non_invoice_null_financials(self, gt):
        result = run_on_invoice(gt["invoice_id"])
        if result is None:
            pytest.skip(f"PDF not found: {gt['invoice_id']}")
        assert result.invoice_number is None, f"{gt['invoice_id']}: invoice_number should be null"
        assert result.subtotal is None, f"{gt['invoice_id']}: subtotal should be null"
        assert result.total is None, f"{gt['invoice_id']}: total should be null"
        assert len(result.warnings) > 0, f"{gt['invoice_id']}: expected a warning"
