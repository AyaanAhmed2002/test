"""
Document classification module.

Detects whether the PDF is:
  - INVOICE      (normal processing)
  - QUOTATION    (null all financial fields, return warning)
  - DELIVERY_NOTE
  - STATEMENT
  - UNKNOWN      (treat as invoice with low confidence warning)

Classification uses document-level heading evidence.  A single occurrence of
an ambiguous word is never sufficient – the classifier looks for the heading
near the top of the document or in a prominent position.

Returns a DocumentType and a confidence score for the classification.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class DocumentType(str, Enum):
    INVOICE = "INVOICE"
    QUOTATION = "QUOTATION"
    DELIVERY_NOTE = "DELIVERY_NOTE"
    STATEMENT = "STATEMENT"
    UNKNOWN = "UNKNOWN"


@dataclass
class ClassificationResult:
    doc_type: DocumentType
    confidence: float   # 0–1, confidence that the classification is correct
    evidence: str       # human-readable description of the evidence found


# ── Heading patterns ───────────────────────────────────────────────────────────
# Checked against the first 60 lines (top of document) where headings appear.

_INVOICE_PATTERNS = [
    re.compile(r"\b(TAX\s+)?INVOICE\b", re.IGNORECASE),
    re.compile(r"\bINVOICE\s+(NO|NUMBER|#|NUM)\b", re.IGNORECASE),
    re.compile(r"\bSALES\s+INVOICE\b", re.IGNORECASE),
    re.compile(r"\bPROFORMA\s+INVOICE\b", re.IGNORECASE),
]

_QUOTATION_PATTERNS = [
    re.compile(r"\b(QUOTATION|QUOTE)\b", re.IGNORECASE),
    re.compile(r"\bPROPOSAL\b", re.IGNORECASE),
    re.compile(r"\bESTIMATE\b", re.IGNORECASE),
    re.compile(r"\bPRICE\s+QUOTE\b", re.IGNORECASE),
]

_DELIVERY_PATTERNS = [
    re.compile(r"\bDELIVERY\s+(NOTE|ADVICE|ORDER|RECEIPT)\b", re.IGNORECASE),
    re.compile(r"\bPACKING\s+(LIST|SLIP)\b", re.IGNORECASE),
    re.compile(r"\bDESPATCH\s+NOTE\b", re.IGNORECASE),
    re.compile(r"\bSHIPMENT\s+ADVICE\b", re.IGNORECASE),
]

_STATEMENT_PATTERNS = [
    re.compile(r"\bSTATEMENT\s+OF\s+ACCOUNT\b", re.IGNORECASE),
    re.compile(r"\bACCOUNT\s+STATEMENT\b", re.IGNORECASE),
    # Plain "STATEMENT" only when it's a standalone heading (whole line / short)
    re.compile(r"^[\s]*STATEMENT[\s]*$", re.IGNORECASE | re.MULTILINE),
]


def _top_region(text: str, lines: int = 60) -> str:
    """Return the first `lines` lines of the document."""
    return "\n".join(text.splitlines()[:lines])


def classify_document(text: str) -> ClassificationResult:
    """
    Classify the document type from its extracted text.

    Parameters
    ----------
    text : str
        Full concatenated text of all PDF pages.

    Returns
    -------
    ClassificationResult
    """
    top = _top_region(text)

    # Check patterns in priority order.
    # Quotation, delivery note, statement each have stronger distinguishing
    # headings than invoice.  We check non-invoice types first so that a
    # document titled "QUOTATION" that also contains the word "invoice" in a
    # line item is still classified correctly.

    # If an explicit INVOICE heading is present at the top, check it first unless
    # a stronger standalone heading for Quotation/Statement/Delivery Note exists.
    # We inspect standalone line headings or check if INVOICE is prominent.
    invoice_match = None
    for pat in _INVOICE_PATTERNS:
        m = pat.search(top)
        if m:
            invoice_match = m
            break

    # If invoice matched early, check if a non-invoice keyword is actually the main title
    # (e.g. standalone title line) rather than just an inline reference (e.g. 'Re: Delivery Note').
    for pat in _QUOTATION_PATTERNS:
        m = pat.search(top)
        if m:
            # Treat as standalone if: no invoice_match, OR the QUOTATION keyword
            # appears before 'NOT AN INVOICE' negation, OR it IS on a standalone line.
            is_standalone_quot = bool(re.search(
                r"^[ \t]*(?:QUOTATION|QUOTE|PROPOSAL|ESTIMATE|PRICE\s+QUOTE)[ \t]*$",
                top, re.IGNORECASE | re.MULTILINE,
            ))
            has_negation = bool(re.search(
                r"\bQUOTATION\b.{0,30}NOT\s+AN?\s+INVOICE",
                top, re.IGNORECASE | re.DOTALL,
            ))
            if invoice_match and not is_standalone_quot and not has_negation:
                continue
            return ClassificationResult(
                doc_type=DocumentType.QUOTATION,
                confidence=0.92,
                evidence=f"Heading pattern matched: '{m.group(0)}'",
            )

    for pat in _DELIVERY_PATTERNS:
        m = pat.search(top)
        if m:
            # If both match and delivery note is just a reference line (e.g. preceded by Re:, Ref:, Delivery Note No),
            # prefer INVOICE
            if invoice_match:
                # Check if delivery note is a standalone heading line
                is_standalone = bool(re.search(r"^[ \t]*(?:DELIVERY\s+(?:NOTE|ADVICE|ORDER|RECEIPT)|PACKING\s+(?:LIST|SLIP)|DESPATCH\s+NOTE)[ \t]*$", top, re.IGNORECASE | re.MULTILINE))
                if not is_standalone:
                    continue
            return ClassificationResult(
                doc_type=DocumentType.DELIVERY_NOTE,
                confidence=0.92,
                evidence=f"Heading pattern matched: '{m.group(0)}'",
            )

    for pat in _STATEMENT_PATTERNS:
        m = pat.search(top)
        if m:
            if invoice_match and not re.search(r"^[ \t]*(?:STATEMENT\s+OF\s+ACCOUNT|ACCOUNT\s+STATEMENT|STATEMENT)[ \t]*$", top, re.IGNORECASE | re.MULTILINE):
                continue
            return ClassificationResult(
                doc_type=DocumentType.STATEMENT,
                confidence=0.88,
                evidence=f"Heading pattern matched: '{m.group(0)}'",
            )

    if invoice_match:
        return ClassificationResult(
            doc_type=DocumentType.INVOICE,
            confidence=0.97,
            evidence=f"Heading pattern matched: '{invoice_match.group(0)}'",
        )

    # No strong heading found – treat as invoice with a warning
    return ClassificationResult(
        doc_type=DocumentType.UNKNOWN,
        confidence=0.40,
        evidence="No clear document-type heading found near the top of the document.",
    )


def is_invoice(result: ClassificationResult) -> bool:
    """Return True if the document should be treated as an invoice."""
    return result.doc_type in (DocumentType.INVOICE, DocumentType.UNKNOWN)
