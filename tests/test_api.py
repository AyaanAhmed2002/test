"""
FastAPI endpoint tests (test_api.py).

Uses httpx AsyncClient with FastAPI's ASGI transport.
Tests:
- GET /health
- GET /
- POST /extract with valid PDF
- POST /extract error cases (empty, non-PDF, too large, etc.)
"""

from __future__ import annotations

import io
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app


# Minimal valid PDF (2-page text invoice for Northwind Traders)
def _make_minimal_pdf() -> bytes:
    """Build a minimal PDF using PyMuPDF to avoid dependency on reportlab in tests."""
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(
        (50, 50),
        (
            "Northwind Traders\n"
            "12 King Street, London, UK\n\n"
            "INVOICE\n"
            "Invoice No: NW-1042\n"
            "Invoice Date: 3 September 2026\n"
            "Due Date: 3 October 2026\n\n"
            "Description                   Amount\n"
            "Consulting services           £361.60\n\n"
            "Subtotal: £361.60\n"
            "VAT: £72.32\n"
            "Total Due: £433.92\n"
        ),
        fontsize=11,
    )
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


VALID_PDF = _make_minimal_pdf()


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.asyncio
class TestHealthEndpoint:
    async def test_health_returns_200(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


@pytest.mark.asyncio
class TestIndexEndpoint:
    async def test_index_returns_html(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "InvoiceExtractor" in r.text or "invoice" in r.text.lower()


@pytest.mark.asyncio
class TestExtractEndpoint:
    async def test_valid_invoice_200(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(
                "/extract",
                files={"file": ("invoice.pdf", VALID_PDF, "application/pdf")},
            )
        assert r.status_code == 200
        data = r.json()

        # Required fields present
        assert "vendor" in data
        assert "invoice_number" in data
        assert "invoice_date" in data
        assert "due_date" in data
        assert "currency" in data
        assert "subtotal" in data
        assert "tax" in data
        assert "total" in data
        assert "confidence" in data
        assert "warnings" in data

    async def test_vendor_identified(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(
                "/extract",
                files={"file": ("invoice.pdf", VALID_PDF, "application/pdf")},
            )
        data = r.json()
        assert data["vendor"] == "Northwind Traders"

    async def test_currency_extracted(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(
                "/extract",
                files={"file": ("invoice.pdf", VALID_PDF, "application/pdf")},
            )
        data = r.json()
        assert data["currency"] == "GBP"

    async def test_confidence_scores_in_range(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(
                "/extract",
                files={"file": ("invoice.pdf", VALID_PDF, "application/pdf")},
            )
        conf = r.json()["confidence"]
        for field_name, score in conf.items():
            assert 0.0 <= score <= 1.0, f"{field_name} confidence out of range: {score}"

    async def test_confidence_has_all_eight_keys(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(
                "/extract",
                files={"file": ("invoice.pdf", VALID_PDF, "application/pdf")},
            )
        conf = r.json()["confidence"]
        expected = {"vendor", "invoice_number", "invoice_date", "due_date",
                    "currency", "subtotal", "tax", "total"}
        assert set(conf.keys()) == expected

    async def test_warnings_is_list(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(
                "/extract",
                files={"file": ("invoice.pdf", VALID_PDF, "application/pdf")},
            )
        assert isinstance(r.json()["warnings"], list)

    async def test_empty_file_422(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(
                "/extract",
                files={"file": ("empty.pdf", b"", "application/pdf")},
            )
        assert r.status_code in (422, 400)

    async def test_non_pdf_415(self):
        fake_content = b"This is not a PDF"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(
                "/extract",
                files={"file": ("text.txt", fake_content, "text/plain")},
            )
        assert r.status_code in (415, 422)

    async def test_oversized_file_413(self):
        oversized = b"%PDF" + b"X" * (11 * 1024 * 1024)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(
                "/extract",
                files={"file": ("big.pdf", oversized, "application/pdf")},
            )
        assert r.status_code == 413

    async def test_monetary_values_two_decimal(self):
        """Monetary amounts in response must be valid JSON numbers (not strings)."""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(
                "/extract",
                files={"file": ("invoice.pdf", VALID_PDF, "application/pdf")},
            )
        data = r.json()
        for field_name in ("subtotal", "tax", "total"):
            v = data[field_name]
            if v is not None:
                assert isinstance(v, (int, float))
