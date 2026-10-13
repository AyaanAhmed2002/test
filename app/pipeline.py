"""
Extraction pipeline orchestrator.

Coordinates all extraction modules in a defined sequence and assembles the
final ExtractionResult.  This is the single function that ties together:
  vendor matching → document classification → field extraction →
  validation → confidence scoring → warning assembly.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from app.confidence import (
    confidence_amount,
    confidence_currency,
    confidence_date,
    confidence_invoice_number,
    confidence_vendor,
)
from app.document_classifier import ClassificationResult, DocumentType, classify_document, is_invoice
from app.field_extractor import (
    extract_currency,
    extract_due_date,
    extract_invoice_date,
    extract_invoice_number,
    extract_payment_terms,
    extract_subtotal,
    extract_tax,
    extract_total,
    extract_vendor_name_raw,
)
from app.amount_parser import decimal_to_float, round_amount
from app.schemas import ConfidenceScores, ExtractionResult
from app.text_normalizer import normalize_text
from app.validators import validate_dates, validate_due_date_vs_terms, validate_financials
from app.vendor_matcher import VendorMatch, get_day_first, get_vendor_currency, match_vendor
from app.warnings import (
    deduplicate,
    warn_derived_due_date,
    warn_inferred_currency,
    warn_low_confidence,
    warn_missing_amount,
    warn_missing_due_date,
    warn_missing_invoice_date,
    warn_missing_invoice_number,
    warn_non_invoice,
    warn_unknown_doc_type,
    warn_unknown_vendor,
)
from app.date_parser import derive_due_date

logger = logging.getLogger(__name__)

_LOW_CONF_THRESHOLD = 0.50


def run_extraction_pipeline(raw_text: str) -> ExtractionResult:
    """
    Run the full extraction pipeline on pre-extracted PDF text.

    Parameters
    ----------
    raw_text : str
        Concatenated text from all PDF pages (via concatenate_pages).

    Returns
    -------
    ExtractionResult
        Fully populated response schema.
    """
    warnings: list[str] = []

    # ── Step 1: Text normalisation ─────────────────────────────────────────────
    text = normalize_text(raw_text)

    # ── Step 2: Vendor identification ─────────────────────────────────────────
    vendor_match: VendorMatch = match_vendor(text)
    day_first = get_day_first(vendor_match)
    vendor_currency = get_vendor_currency(vendor_match)

    if vendor_match.record is not None:
        vendor_name = vendor_match.record.canonical
    else:
        vendor_name = extract_vendor_name_raw(text) or "unknown"
        warnings += warn_unknown_vendor(vendor_name)
        vendor_name = "unknown"

    conf_vendor = confidence_vendor(
        vendor_match.confidence,
        is_unknown=(vendor_match.record is None),
    )

    # ── Step 3: Document classification ───────────────────────────────────────
    doc_class: ClassificationResult = classify_document(text)

    if not is_invoice(doc_class):
        # Non-invoice: return null fields with warning
        warnings += warn_non_invoice(doc_class.doc_type.value)
        warnings = deduplicate(warnings)
        return _non_invoice_result(vendor_name, conf_vendor, doc_class, warnings)

    if doc_class.doc_type == DocumentType.UNKNOWN:
        warnings += warn_unknown_doc_type()

    # ── Step 4: Invoice number ─────────────────────────────────────────────────
    inv_num, inv_num_conf_raw = extract_invoice_number(text)
    conf_inv_num = confidence_invoice_number(inv_num, inv_num_conf_raw)
    if inv_num is None:
        warnings += warn_missing_invoice_number()

    # ── Step 5: Dates ──────────────────────────────────────────────────────────
    inv_date_parsed = extract_invoice_date(text, day_first)
    warnings += inv_date_parsed.warnings  # locale / ambiguity warnings

    if inv_date_parsed.value is None:
        warnings += warn_missing_invoice_date()

    due_date_parsed = extract_due_date(text, day_first)
    warnings += due_date_parsed.warnings

    # Payment terms and due-date derivation
    payment_days = extract_payment_terms(text)
    derived_due = None

    if due_date_parsed.value is not None:
        # Printed due date exists; check for conflict with payment terms
        if payment_days is not None and inv_date_parsed.value is not None:
            derived_due = derive_due_date(inv_date_parsed.value, payment_days)
            warnings += validate_due_date_vs_terms(
                due_date_parsed.value, derived_due, payment_days
            )
        conf_due = confidence_date(due_date_parsed, is_derived=False)
    else:
        # No printed due date; try to derive
        if payment_days is not None and inv_date_parsed.value is not None:
            derived_due = derive_due_date(inv_date_parsed.value, payment_days)
            due_date_parsed.value = derived_due
            due_date_parsed.iso = derived_due.isoformat()
            due_date_parsed.confidence = 0.72
            warnings += warn_derived_due_date(payment_days, derived_due.isoformat())
            conf_due = 0.72
        else:
            conf_due = 0.0
            warnings += warn_missing_due_date(has_terms=(payment_days is not None))

    # Date ordering validation
    warnings += validate_dates(inv_date_parsed.value, due_date_parsed.value)

    conf_inv_date = confidence_date(inv_date_parsed)

    # ── Step 6: Currency ───────────────────────────────────────────────────────
    currency, currency_conf = extract_currency(text, vendor_currency)
    is_inferred = currency_conf < 0.85
    if is_inferred:
        reason = (
            f"no explicit symbol/code; defaulting to vendor default ({vendor_currency})"
            if vendor_currency
            else "no explicit symbol/code and vendor is unknown"
        )
        warnings += warn_inferred_currency(currency, reason)
    conf_currency = confidence_currency(currency_conf, is_inferred)

    # ── Step 7: Monetary amounts ───────────────────────────────────────────────
    subtotal_dec, sub_conf_raw = extract_subtotal(text)
    tax_dec, tax_conf_raw = extract_tax(text)
    total_dec, total_conf_raw = extract_total(text)

    if subtotal_dec is None:
        warnings += warn_missing_amount("subtotal")
    if tax_dec is None:
        warnings += warn_missing_amount("tax")
    if total_dec is None:
        warnings += warn_missing_amount("total")

    # ── Step 8: Financial validation ───────────────────────────────────────────
    fin_warnings = validate_financials(subtotal_dec, tax_dec, total_dec)
    has_mismatch = bool(fin_warnings)
    warnings += fin_warnings

    # ── Step 9: Confidence scores ──────────────────────────────────────────────
    conf_subtotal = confidence_amount(subtotal_dec, sub_conf_raw, has_mismatch)
    conf_tax = confidence_amount(tax_dec, tax_conf_raw, has_mismatch)
    conf_total = confidence_amount(total_dec, total_conf_raw, has_mismatch)

    # Low-confidence warnings
    field_scores = {
        "vendor": conf_vendor,
        "invoice_number": conf_inv_num,
        "invoice_date": conf_inv_date,
        "due_date": conf_due,
        "currency": conf_currency,
        "subtotal": conf_subtotal,
        "tax": conf_tax,
        "total": conf_total,
    }
    for fname, fscore in field_scores.items():
        if 0.0 < fscore < _LOW_CONF_THRESHOLD:
            warnings += warn_low_confidence(fname, fscore)

    # ── Step 10: Assemble result ───────────────────────────────────────────────
    warnings = deduplicate(warnings)

    return ExtractionResult(
        vendor=vendor_name,
        invoice_number=inv_num,
        invoice_date=inv_date_parsed.iso,
        due_date=due_date_parsed.iso,
        currency=currency,
        subtotal=decimal_to_float(round_amount(subtotal_dec)) if subtotal_dec is not None else None,
        tax=decimal_to_float(round_amount(tax_dec)) if tax_dec is not None else None,
        total=decimal_to_float(round_amount(total_dec)) if total_dec is not None else None,
        confidence=ConfidenceScores(
            vendor=conf_vendor,
            invoice_number=conf_inv_num,
            invoice_date=conf_inv_date,
            due_date=conf_due,
            currency=conf_currency,
            subtotal=conf_subtotal,
            tax=conf_tax,
            total=conf_total,
        ),
        warnings=warnings,
    )


def _non_invoice_result(
    vendor_name: str,
    conf_vendor: float,
    doc_class: ClassificationResult,
    warnings: list[str],
) -> ExtractionResult:
    """Return a result with all financial fields null for non-invoice documents."""
    return ExtractionResult(
        vendor=vendor_name,
        invoice_number=None,
        invoice_date=None,
        due_date=None,
        currency="unknown",
        subtotal=None,
        tax=None,
        total=None,
        confidence=ConfidenceScores(
            vendor=conf_vendor,
            invoice_number=0.0,
            invoice_date=0.0,
            due_date=0.0,
            currency=0.0,
            subtotal=0.0,
            tax=0.0,
            total=0.0,
        ),
        warnings=warnings,
    )
