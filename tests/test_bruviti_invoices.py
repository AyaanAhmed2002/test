"""
Regression tests for the 10 bruviti_test_invoices PDFs.

Each test asserts manually-verified expected values derived from reading the
PDF source text directly — NOT from treating the extractor's previous output
as ground truth.

Coverage includes:
  - Label variant handling (Document Ref, Rechnungsnummer, Reference:, Invoice No.)
  - Date locale logic (UK DD/MM, US MM/DD, ISO YYYY.MM.DD)
  - German number format (EUR 1.148,95 → 1148.95)
  - JPY integers without decimals
  - Indian number grouping
  - Unknown vendor returns 'unknown' with warning
  - Non-invoice (quotation) yields null financial fields + warning
  - Conflicting dates/totals generate expected warnings
  - Missing fields generate expected warnings (not exceptions)
  - Ambiguous dates for unknown vendor return null (not a guess)

All tests are offline and deterministic (no server, no HTTP).
"""

from __future__ import annotations

import pathlib
import pytest

from app.pdf_reader import read_pdf, concatenate_pages
from app.pipeline import run_extraction_pipeline
from app.schemas import ExtractionResult

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

INVOICE_DIR = pathlib.Path("bruviti_test_invoices")


def _extract(filename: str) -> ExtractionResult:
    """Read a PDF from bruviti_test_invoices/ and run the full pipeline."""
    data = (INVOICE_DIR / filename).read_bytes()
    pages = read_pdf(data)
    text = concatenate_pages(pages)
    return run_extraction_pipeline(text)


def _conf(result: ExtractionResult) -> dict:
    return result.confidence.model_dump()


# ---------------------------------------------------------------------------
# INV-01: Blue Harbour — label variants (Document Ref, Net Amount, VAT Amount (20%))
# ---------------------------------------------------------------------------

class TestInv01BlueHarbourLabelVariants:
    """
    PDF layout: 'Document Ref' for invoice number, 'Net Amount' for subtotal,
    'VAT Amount (20%)' for tax (with parenthesised percentage), 'Total Payable'
    for total.  All monetary values on the next line with 'GBP' prefix.
    Due date derived from 'Net 14' payment terms (no explicit due date label).
    """

    @pytest.fixture(scope="class")
    def result(self):
        return _extract("01_blue_harbour_label_variants.pdf")

    def test_vendor(self, result):
        assert result.vendor == "Blue Harbour Logistics"
        assert _conf(result)["vendor"] == 1.0

    def test_invoice_number(self, result):
        # Label 'Document Ref' with value on next line
        assert result.invoice_number == "BH-2026-0088"
        assert _conf(result)["invoice_number"] == pytest.approx(0.93)

    def test_invoice_date(self, result):
        # 'Issued On\n14/10/2026' — 14 > 12 so unambiguous DD/MM
        assert result.invoice_date == "2026-10-14"
        assert _conf(result)["invoice_date"] >= 0.90

    def test_due_date_derived(self, result):
        # No explicit due date; derived from 'Net 14' → 14 Oct + 14 days = 28 Oct
        assert result.due_date == "2026-10-28"
        assert any("derived from payment terms" in w for w in result.warnings)

    def test_currency(self, result):
        assert result.currency == "GBP"

    def test_subtotal(self, result):
        # 'Net Amount\nGBP 944.00'
        assert result.subtotal == pytest.approx(944.0)

    def test_tax(self, result):
        # 'VAT Amount (20%)\nGBP 188.80' — parenthesised % in label
        assert result.tax == pytest.approx(188.8)

    def test_total(self, result):
        # 'Total Payable\nGBP 1,132.80'
        assert result.total == pytest.approx(1132.8)

    def test_no_unexpected_warnings(self, result):
        # The only expected warning is the derived due date
        unexpected = [w for w in result.warnings if "derived" not in w]
        assert unexpected == [], f"Unexpected warnings: {unexpected}"


# ---------------------------------------------------------------------------
# INV-02: Kestrel — US date format, Sales Tax (8.25%), Grand Total
# ---------------------------------------------------------------------------

class TestInv02KestrelUSDateAndCurrency:
    """
    Kestrel is a US vendor (MM/DD locale).
    '11/04/2026' → ambiguous → MM/DD → 2026-11-04.
    'Sales Tax (8.25%)' with $ values.
    'Grand Total' for total.
    Due date derived from 'Due in 30 days'.
    """

    @pytest.fixture(scope="class")
    def result(self):
        return _extract("02_kestrel_us_date_and_currency.pdf")

    def test_vendor(self, result):
        assert result.vendor == "Kestrel Components"

    def test_invoice_number(self, result):
        assert result.invoice_number == "KC-7782"

    def test_invoice_date_mm_dd(self, result):
        # 11/04/2026 → MM/DD → November 4, 2026 (Kestrel is US)
        assert result.invoice_date == "2026-11-04"
        assert any("MM/DD" in w for w in result.warnings), \
            "Expected ambiguous-date warning for MM/DD interpretation"

    def test_due_date_derived(self, result):
        # 'Due in 30 days' from 2026-11-04 → 2026-12-04
        assert result.due_date == "2026-12-04"
        assert any("derived from payment terms" in w for w in result.warnings)

    def test_currency(self, result):
        assert result.currency == "USD"

    def test_subtotal(self, result):
        assert result.subtotal == pytest.approx(2190.0)

    def test_tax(self, result):
        # 'Sales Tax (8.25%)\n$180.68'
        assert result.tax == pytest.approx(180.68)

    def test_total(self, result):
        # 'Grand Total\n$2,370.68'
        assert result.total == pytest.approx(2370.68)


# ---------------------------------------------------------------------------
# INV-03: Meridian German — Rechnungsnummer, Rechnungsdatum, Zahlbar bis,
#         Nettobetrag, Umsatzsteuer, Rechnungsbetrag, European number format
# ---------------------------------------------------------------------------

class TestInv03MeridianGermanFormat:
    """
    All labels are German.  Numbers use European format: 1.234,56 (period=thousands, comma=decimal).
    'EUR 1.148,95' → 1148.95.
    """

    @pytest.fixture(scope="class")
    def result(self):
        return _extract("03_meridian_german_format.pdf")

    def test_vendor(self, result):
        assert result.vendor == "Meridian Industrial"

    def test_invoice_number(self, result):
        # Rechnungsnummer: MI-2026-441
        assert result.invoice_number == "MI-2026-441"

    def test_invoice_date(self, result):
        # Rechnungsdatum: 2026.10.02 — ISO-style, unambiguous
        assert result.invoice_date == "2026-10-02"
        assert _conf(result)["invoice_date"] >= 0.95

    def test_due_date(self, result):
        # Zahlbar bis: 16.10.2026 — DD.MM.YYYY, 16 > 12 so unambiguous
        assert result.due_date == "2026-10-16"

    def test_currency(self, result):
        assert result.currency == "EUR"

    def test_subtotal_european_format(self, result):
        # Nettobetrag\nEUR 965,50 — comma is decimal in European format
        assert result.subtotal == pytest.approx(965.5)

    def test_tax_german_label(self, result):
        # Umsatzsteuer 19%\nEUR 183,45
        assert result.tax == pytest.approx(183.45)

    def test_total_german_label(self, result):
        # Rechnungsbetrag\nEUR 1.148,95 — period=thousands, comma=decimal
        assert result.total == pytest.approx(1148.95)

    def test_no_warnings(self, result):
        # German format, all labels matched, no ambiguous dates
        assert result.warnings == []


# ---------------------------------------------------------------------------
# INV-04: Sakura — ISO dates, JPY integers, Consumption tax
# ---------------------------------------------------------------------------

class TestInv04SakuraJPYNoDecimals:
    """
    JPY amounts are integers (no decimal places).
    Dates use YYYY.MM.DD ISO format — unambiguous.
    'Invoice issued:' for invoice date, 'Payment due:' for due date.
    'Consumption tax' label (Japanese tax terminology).
    """

    @pytest.fixture(scope="class")
    def result(self):
        return _extract("04_sakura_jpy_no_decimals.pdf")

    def test_vendor(self, result):
        assert result.vendor == "Sakura Precision"

    def test_invoice_number(self, result):
        # 'Invoice No. SP-90017'
        assert result.invoice_number == "SP-90017"

    def test_invoice_date_iso(self, result):
        # 'Invoice issued: 2026.10.05' — ISO-style, unambiguous
        assert result.invoice_date == "2026-10-05"
        assert _conf(result)["invoice_date"] >= 0.95

    def test_due_date_iso(self, result):
        # 'Payment due: 2026.11.04'
        assert result.due_date == "2026-11-04"

    def test_currency(self, result):
        assert result.currency == "JPY"

    def test_subtotal_jpy_integer(self, result):
        # JPY 155,000 — no decimal places
        assert result.subtotal == pytest.approx(155000.0)

    def test_tax_consumption(self, result):
        # 'Consumption tax\n¥ 15500'
        assert result.tax == pytest.approx(15500.0)

    def test_total_jpy_integer(self, result):
        assert result.total == pytest.approx(170500.0)

    def test_no_warnings(self, result):
        assert result.warnings == []


# ---------------------------------------------------------------------------
# INV-05: Pinecrest — Indian number grouping, GST, Balance Due
# ---------------------------------------------------------------------------

class TestInv05PinecrestIndianGrouping:
    """
    Indian number format: 21,250.00 (comma at thousands).
    Currency symbol ₹ may be garbled by PDF extractor — currency inferred
    from vendor default (INR).
    'Balance Due' is the total label.
    '12-10-2026' → DD/MM (Pinecrest is Indian vendor) → 2026-10-12.
    """

    @pytest.fixture(scope="class")
    def result(self):
        return _extract("05_pinecrest_indian_grouping.pdf")

    def test_vendor(self, result):
        assert result.vendor == "Pinecrest Packaging"

    def test_invoice_number(self, result):
        assert result.invoice_number == "PP/26-27/019"

    def test_invoice_date_dd_mm(self, result):
        # '12-10-2026' → DD/MM (Pinecrest INR locale) → 2026-10-12
        assert result.invoice_date == "2026-10-12"

    def test_due_date(self, result):
        # 'Pay By: 11-11-2026' → 11 > 12 is not > 12... but same digit → 2026-11-11
        assert result.due_date == "2026-11-11"

    def test_currency_inferred(self, result):
        # ₹ symbol garbled; currency inferred from vendor default
        assert result.currency == "INR"
        assert any("Currency inferred" in w or "inferred" in w.lower() for w in result.warnings)

    def test_subtotal(self, result):
        assert result.subtotal == pytest.approx(21250.0)

    def test_tax_gst(self, result):
        assert result.tax == pytest.approx(3825.0)

    def test_total_balance_due(self, result):
        # 'Balance Due\n25,075.00' — must not match 'Net Total' (21,250)
        assert result.total == pytest.approx(25075.0)


# ---------------------------------------------------------------------------
# INV-06: Unknown vendor — 'Reference:' label, payable-on-receipt, INR
# ---------------------------------------------------------------------------

class TestInv06UnknownVendor:
    """
    'Eastern Industrial Supplies' is not in the vendor registry.
    Invoice number uses bare 'Reference:' label.
    'Payable upon receipt' → no numeric term → due date null (expected).
    Date '21 August 2026' is textual — unambiguous.
    """

    @pytest.fixture(scope="class")
    def result(self):
        return _extract("06_unknown_vendor.pdf")

    def test_vendor_unknown(self, result):
        assert result.vendor == "unknown"
        assert _conf(result)["vendor"] == 0.0
        assert any("not found in the canonical registry" in w for w in result.warnings)

    def test_invoice_number_reference_label(self, result):
        # 'Reference: 7781'
        assert result.invoice_number == "7781"

    def test_invoice_date_textual(self, result):
        # '21 August 2026' — textual, unambiguous
        assert result.invoice_date == "2026-08-21"
        assert _conf(result)["invoice_date"] >= 0.95

    def test_due_date_null_payable_on_receipt(self, result):
        # 'payable upon receipt' → no numeric day count → no derived date
        assert result.due_date is None
        assert any("Due date not found" in w for w in result.warnings)

    def test_currency(self, result):
        assert result.currency == "INR"

    def test_subtotal(self, result):
        assert result.subtotal == pytest.approx(12500.0)

    def test_tax(self, result):
        assert result.tax == pytest.approx(2250.0)

    def test_total(self, result):
        assert result.total == pytest.approx(14750.0)


# ---------------------------------------------------------------------------
# INV-07: Non-invoice quotation — all financial fields must be null
# ---------------------------------------------------------------------------

class TestInv07NonInvoiceQuotation:
    """
    Document heading: 'QUOTATION — NOT AN INVOICE'.
    The classifier must recognise this as QUOTATION despite the word 'INVOICE'
    appearing in the heading negation.
    All financial fields must be null per the Bruviti spec.
    """

    @pytest.fixture(scope="class")
    def result(self):
        return _extract("07_non_invoice_quotation.pdf")

    def test_vendor_still_extracted(self, result):
        # Vendor identification works even for non-invoices
        assert result.vendor == "Northwind Traders"

    def test_financial_fields_null(self, result):
        assert result.subtotal is None, "subtotal must be null for non-invoice"
        assert result.tax is None, "tax must be null for non-invoice"
        assert result.total is None, "total must be null for non-invoice"

    def test_financial_confidences_zero(self, result):
        conf = _conf(result)
        assert conf["subtotal"] == 0.0
        assert conf["tax"] == 0.0
        assert conf["total"] == 0.0

    def test_dates_null(self, result):
        assert result.invoice_date is None
        assert result.due_date is None

    def test_quotation_warning_present(self, result):
        assert any("quotation" in w.lower() for w in result.warnings), \
            f"Expected quotation warning, got: {result.warnings}"

    def test_no_invoice_number(self, result):
        # 'Quote Reference' is not an invoice number label
        assert result.invoice_number is None


# ---------------------------------------------------------------------------
# INV-08: Conflicting dates and arithmetic mismatch
# ---------------------------------------------------------------------------

class TestInv08ConflictingDatesAndTotals:
    """
    Printed due date (15/10) differs from terms-derived date (Net 30 from 01/10 = 31/10).
    Printed due date takes priority; a date-conflict warning is generated.
    Subtotal (1000) + VAT (200) = 1200, but Total Due = 1250 → arithmetic mismatch warning.
    Extracted values are preserved as-printed; no auto-correction.
    """

    @pytest.fixture(scope="class")
    def result(self):
        return _extract("08_conflicting_dates_and_totals.pdf")

    def test_vendor(self, result):
        assert result.vendor == "Blue Harbour Logistics"

    def test_invoice_number(self, result):
        assert result.invoice_number == "BH-9917"

    def test_invoice_date(self, result):
        # 01/10/2026 → DD/MM (Blue Harbour UK) → 2026-10-01
        assert result.invoice_date == "2026-10-01"

    def test_due_date_printed_wins(self, result):
        # Printed: 15/10/2026 → DD/MM → 2026-10-15
        # Net 30 from 2026-10-01 would give 2026-10-31 — 16-day conflict
        assert result.due_date == "2026-10-15"

    def test_date_conflict_warning(self, result):
        assert any("differs from" in w or "conflict" in w.lower() for w in result.warnings), \
            f"Expected date-conflict warning, got: {result.warnings}"

    def test_subtotal(self, result):
        assert result.subtotal == pytest.approx(1000.0)

    def test_tax(self, result):
        assert result.tax == pytest.approx(200.0)

    def test_total_printed_preserved(self, result):
        # Total is 1250 (not 1200); printed value preserved despite arithmetic mismatch
        assert result.total == pytest.approx(1250.0)

    def test_arithmetic_mismatch_warning(self, result):
        assert any("mismatch" in w.lower() for w in result.warnings), \
            f"Expected arithmetic mismatch warning, got: {result.warnings}"


# ---------------------------------------------------------------------------
# INV-09: Missing fields — no invoice number, no tax, currency by inference
# ---------------------------------------------------------------------------

class TestInv09MissingFieldsAndCurrencyInference:
    """
    Invoice has no invoice number, no tax line, no currency symbol.
    Currency inferred from Meridian's vendor default (EUR).
    Date '07.10.2026' is DD.MM.YYYY → 2026-10-07 (Meridian is EU vendor, day_first=True).
    Due date derived from 'Payment terms: 14 days'.
    Subtotal = Total (no VAT line means zero-tax invoice, not a bug).
    """

    @pytest.fixture(scope="class")
    def result(self):
        return _extract("09_missing_fields_and_currency_inference.pdf")

    def test_vendor(self, result):
        assert result.vendor == "Meridian Industrial"

    def test_invoice_number_null(self, result):
        assert result.invoice_number is None
        assert any("Invoice number not found" in w for w in result.warnings)

    def test_invoice_date(self, result):
        assert result.invoice_date == "2026-10-07"

    def test_due_date_derived(self, result):
        # 14 days from 2026-10-07 = 2026-10-21
        assert result.due_date == "2026-10-21"

    def test_currency_inferred(self, result):
        assert result.currency == "EUR"
        assert any("inferred" in w.lower() for w in result.warnings)

    def test_subtotal(self, result):
        # 'Net Amount\n570,00' — EU comma decimal → 570.00
        assert result.subtotal == pytest.approx(570.0)

    def test_tax_null(self, result):
        # No tax line in document — expected absence
        assert result.tax is None
        assert any("Tax not found" in w for w in result.warnings)

    def test_total(self, result):
        # 'Amount Due\n570,00' — same as subtotal (zero-tax invoice)
        assert result.total == pytest.approx(570.0)


# ---------------------------------------------------------------------------
# INV-10: Unknown vendor — ambiguous date returns null
# ---------------------------------------------------------------------------

class TestInv10UnknownVendorAmbiguousDate:
    """
    'Alpha Mechanical Services' is not in the vendor registry → vendor='unknown'.
    Dates '03/04/2026' and '03/05/2026' are ambiguous (both day and month ≤ 12)
    and vendor locale is unknown → per spec, return null with warning.
    Currency label 'Currency: USD' is explicit → USD extracted reliably.
    """

    @pytest.fixture(scope="class")
    def result(self):
        return _extract("10_unknown_vendor_ambiguous_date.pdf")

    def test_vendor_unknown(self, result):
        assert result.vendor == "unknown"

    def test_invoice_number(self, result):
        assert result.invoice_number == "AMS-556"

    def test_invoice_date_null_ambiguous(self, result):
        # '03/04/2026' is ambiguous; vendor unknown → null per spec
        assert result.invoice_date is None
        assert any("ambiguous" in w.lower() for w in result.warnings)

    def test_due_date_null_ambiguous(self, result):
        # '03/05/2026' same situation
        assert result.due_date is None

    def test_currency_explicit(self, result):
        # 'Currency: USD' explicit label → high-confidence USD
        assert result.currency == "USD"
        assert _conf(result)["currency"] >= 0.90

    def test_subtotal(self, result):
        assert result.subtotal == pytest.approx(450.0)

    def test_tax(self, result):
        assert result.tax == pytest.approx(36.0)

    def test_total(self, result):
        assert result.total == pytest.approx(486.0)

    def test_arithmetic_consistent(self, result):
        # 450 + 36 = 486 — no mismatch warning expected
        assert not any("mismatch" in w.lower() for w in result.warnings)
