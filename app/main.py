"""
FastAPI application entry point.

Endpoints
---------
GET  /          → HTML upload interface
POST /extract   → Invoice field extraction (multipart PDF upload)
GET  /health    → Service readiness check

The same process serves both the API and the HTML page (no separate frontend).
"""

from __future__ import annotations

import io
import logging
import time
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import MAX_UPLOAD_BYTES
from app.pdf_reader import (
    EmptyPDFError,
    EncryptedPDFError,
    FileTooLargeError,
    MalformedPDFError,
    NotAPDFError,
    PDFError,
    read_pdf,
    validate_upload,
    concatenate_pages,
)
from app.pipeline import run_extraction_pipeline
from app.schemas import ExtractionResult, HealthResponse

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── App setup ──────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Invoice Field Extractor",
    description="Extracts structured header fields from supplier invoice PDFs.",
    version="1.0.0",
)

BASE_DIR = Path(__file__).parent.parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ── Error status mapping ───────────────────────────────────────────────────────

_PDF_ERROR_STATUS: dict[type, int] = {
    FileTooLargeError: 413,
    NotAPDFError: 415,
    EncryptedPDFError: 422,
    EmptyPDFError: 422,
    MalformedPDFError: 422,
}


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index(request: Request) -> HTMLResponse:
    """Serve the upload interface."""
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Service readiness check."""
    return HealthResponse(status="ok")


@app.post("/extract", response_model=ExtractionResult)
async def extract(file: UploadFile = File(...)) -> ExtractionResult:
    """
    Extract invoice header fields from an uploaded PDF.

    Accepts: multipart/form-data with field `file` containing a PDF.
    Returns: JSON with eight business fields, confidence scores, and warnings.
    """
    t_start = time.perf_counter()

    # ── Read upload ────────────────────────────────────────────────────────────
    try:
        data = await file.read()
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to read upload: %s", type(exc).__name__)
        raise HTTPException(status_code=400, detail="Failed to read uploaded file.")

    # ── Validate ───────────────────────────────────────────────────────────────
    try:
        validate_upload(data, filename=file.filename or "")
    except PDFError as exc:
        status = _PDF_ERROR_STATUS.get(type(exc), 422)
        raise HTTPException(status_code=status, detail=str(exc))

    # ── Extract text ───────────────────────────────────────────────────────────
    try:
        pages = read_pdf(data)
    except PDFError as exc:
        status = _PDF_ERROR_STATUS.get(type(exc), 422)
        raise HTTPException(status_code=status, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error during PDF reading")
        raise HTTPException(status_code=500, detail="Internal error processing PDF.")

    full_text = concatenate_pages(pages)

    # ── Run extraction pipeline ────────────────────────────────────────────────
    try:
        result = run_extraction_pipeline(full_text)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error during field extraction")
        raise HTTPException(status_code=500, detail="Internal error during field extraction.")

    elapsed_ms = (time.perf_counter() - t_start) * 1000
    logger.info(
        "Extraction complete in %.1f ms | vendor=%s | doc_type=%s",
        elapsed_ms,
        result.vendor,
        "invoice",
    )

    return result
