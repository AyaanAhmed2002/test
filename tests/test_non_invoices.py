"""
Tests for non-invoice document handling:
- Quotation, Delivery Note, Statement → null financial fields
- Vendor identification still works
- Correct warnings generated
"""

import pytest
from app.pipeline import run_extraction_pipeline
from app.document_classifier import classify_document, DocumentType


class TestDocumentClassifier:
    def test_invoice_classified(self):
        text = "Northwind Traders\n\nINVOICE\nInvoice No: 1234\n"
        r = classify_document(text)
        assert r.doc_type == DocumentType.INVOICE
        assert r.confidence >= 0.90

    def test_quotation_classified(self):
        text = "Northwind Traders\n\nQUOTATION\nQuote No: Q-001\n"
        r = classify_document(text)
        assert r.doc_type == DocumentType.QUOTATION

    def test_delivery_note_classified(self):
        text = "Blue Harbour Logistics\n\nDELIVERY NOTE\nDN-12345\n"
        r = classify_document(text)
        assert r.doc_type == DocumentType.DELIVERY_NOTE

    def test_statement_classified(self):
        text = "Kestrel Components\n\nSTATEMENT OF ACCOUNT\n"
        r = classify_document(text)
        assert r.doc_type == DocumentType.STATEMENT

    def test_invoice_with_delivery_reference_not_misclassified(self):
        """An invoice that references a delivery note should still be INVOICE."""
        text = (
            "Northwind Traders\nINVOICE\n"
            "Invoice No: INV-123\n"
            "Re: Delivery Note DN-456\n"
            "Total Due: £100.00\n"
        )
        r = classify_document(text)
        assert r.doc_type == DocumentType.INVOICE


class TestNonInvoiceExtraction:
    def _make_quotation_text(self):
        return (
            "Northwind Traders Ltd\n12 King Street, London, UK\n\n"
            "QUOTATION\n"
            "Quote No: Q-2026-001\n"
            "Date: 3 September 2026\n\n"
            "Description                  Amount\n"
            "Consulting services         £361.60\n"
            "Hardware                    £100.00\n\n"
            "Subtotal: £461.60\n"
            "VAT: £92.32\n"
            "Total: £553.92\n"
        )

    def _make_delivery_text(self):
        return (
            "Blue Harbour Logistics Ltd\nDock Road, Liverpool, UK\n\n"
            "DELIVERY NOTE\n"
            "DN No: DN-2026-042\n"
            "Delivery Date: 5 October 2026\n\n"
            "Item 1: 20 units Widget A\n"
            "Item 2: 5 boxes Component B\n"
        )

    def test_quotation_financial_fields_null(self):
        result = run_extraction_pipeline(self._make_quotation_text())
        assert result.invoice_number is None
        assert result.invoice_date is None
        assert result.due_date is None
        assert result.subtotal is None
        assert result.tax is None
        assert result.total is None

    def test_quotation_vendor_identified(self):
        result = run_extraction_pipeline(self._make_quotation_text())
        assert result.vendor == "Northwind Traders"

    def test_quotation_warning_present(self):
        result = run_extraction_pipeline(self._make_quotation_text())
        assert any("quotation" in w.lower() for w in result.warnings)

    def test_quotation_confidence_zeros(self):
        result = run_extraction_pipeline(self._make_quotation_text())
        c = result.confidence
        assert c.invoice_number == 0.0
        assert c.invoice_date == 0.0
        assert c.due_date == 0.0
        assert c.subtotal == 0.0
        assert c.tax == 0.0
        assert c.total == 0.0

    def test_delivery_note_financial_null(self):
        result = run_extraction_pipeline(self._make_delivery_text())
        assert result.subtotal is None
        assert result.total is None

    def test_delivery_note_vendor_identified(self):
        result = run_extraction_pipeline(self._make_delivery_text())
        assert result.vendor == "Blue Harbour Logistics"
