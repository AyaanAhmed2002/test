"""
PDF reading and validation module.

Primary library: PyMuPDF (fitz)
Chosen because it is fast, fully offline, returns structured text with
positional data, and handles most malformed/encrypted PDFs without crashing.

Public API
----------
read_pdf(data: bytes) -> list[str]
    Returns a list of page text strings (one per page, up to MAX_PAGES).
    Raises PDFError subclasses for all known failure modes.
"""

from __future__ import annotations

import io
import logging
from typing import Final

import fitz  # PyMuPDF

from app.config import MAX_PAGES, MAX_UPLOAD_BYTES

logger = logging.getLogger(__name__)

# Magic bytes that identify a PDF file
_PDF_MAGIC: Final[bytes] = b"%PDF"


# ── custom exceptions ──────────────────────────────────────────────────────────

class PDFError(ValueError):
    """Base class for all PDF-related client errors."""


class FileTooLargeError(PDFError):
    """Upload exceeds the configured size limit."""


class NotAPDFError(PDFError):
    """File does not appear to be a PDF."""


class EncryptedPDFError(PDFError):
    """PDF is password-protected and cannot be read."""


class EmptyPDFError(PDFError):
    """PDF contains no pages or no extractable text."""


class MalformedPDFError(PDFError):
    """PyMuPDF could not parse the file structure."""


# ── public interface ───────────────────────────────────────────────────────────

def validate_upload(data: bytes, filename: str = "") -> None:
    """
    Run cheap, fast checks before attempting to open the PDF.

    Raises an appropriate PDFError subclass on failure.
    Note: filename is used only for logging; never as a filesystem path.
    """
    if len(data) == 0:
        raise EmptyPDFError("Uploaded file is empty.")

    if len(data) > MAX_UPLOAD_BYTES:
        limit_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
        raise FileTooLargeError(
            f"File exceeds the {limit_mb} MB upload limit "
            f"({len(data) / 1024 / 1024:.1f} MB received)."
        )

    if not data.startswith(_PDF_MAGIC):
        raise NotAPDFError(
            "The uploaded file does not appear to be a PDF "
            "(missing %PDF header). Only PDF files are accepted."
        )


def read_pdf(data: bytes) -> list[str]:
    """
    Open a PDF from raw bytes and return a list of page text strings.

    Parameters
    ----------
    data : bytes
        Raw PDF bytes (already validated by validate_upload).

    Returns
    -------
    list[str]
        One entry per page, up to MAX_PAGES.  Each entry is the plain-text
        content of that page with line breaks preserved.

    Raises
    ------
    EncryptedPDFError
        The PDF requires a password.
    EmptyPDFError
        The PDF has no pages, or none of the processed pages contain text.
    MalformedPDFError
        PyMuPDF could not parse the file at all.
    """
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except fitz.FileDataError as exc:
        raise MalformedPDFError(
            f"PDF could not be parsed: the file may be corrupted. ({exc})"
        ) from exc
    except Exception as exc:  # noqa: BLE001 – broad catch, re-raised as domain error
        raise MalformedPDFError(
            f"Unexpected error while opening PDF: {type(exc).__name__}."
        ) from exc

    if doc.is_encrypted:
        doc.close()
        raise EncryptedPDFError(
            "The PDF is password-protected.  "
            "Please provide an unencrypted copy."
        )

    page_count = doc.page_count
    if page_count == 0:
        doc.close()
        raise EmptyPDFError("The PDF contains no pages.")

    pages_to_read = min(page_count, MAX_PAGES)
    pages: list[str] = []

    try:
        for i in range(pages_to_read):
            page = doc[i]
            # "text" layout preserves reading order and line breaks
            text = page.get_text("text")  # type: ignore[arg-type]
            pages.append(text)
    finally:
        doc.close()

    # Log (but do not expose to user) if we hit the page limit
    if page_count > MAX_PAGES:
        logger.warning(
            "PDF has %d pages; only the first %d were processed.",
            page_count,
            MAX_PAGES,
        )

    non_empty = [p for p in pages if p.strip()]
    if not non_empty:
        raise EmptyPDFError(
            "No extractable text was found in the PDF. "
            "Scanned or image-only PDFs are not supported."
        )

    return pages


def concatenate_pages(pages: list[str]) -> str:
    """Join page texts with a form-feed sentinel to preserve page breaks."""
    return "\f".join(pages)
