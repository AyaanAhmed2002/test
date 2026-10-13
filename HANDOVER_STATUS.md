# Bruviti Invoice Field Extraction — Handover & Current Status

> **Target Audience**: Claude / Senior Backend Engineer taking over the project.  
> **Repository Path**: `d:\Bruviti_Assignment`  
> **Status**: **Core Pipeline Complete, 265/265 Tests Passing (100%)**, Ready for Documentation & Containerization.

---

## 1. Project Background & Objective

This repository contains the implementation for **Bruviti Campus Drive 2026 — Use Case 3: Invoice Field Extraction**.

### Core Requirements
The system accepts digital supplier invoice PDFs, extracts **8 header fields**, normalizes them into a fixed JSON schema, computes a confidence score for each field `[0.0, 1.0]`, and outputs actionable warning messages for ambiguous, inconsistent, or non-invoice documents.

### The 8 Required Header Fields
1. `vendor`: Canonical supplier name from the 6 known vendors, or normalized name / `"unknown"` for unseen suppliers.
2. `invoice_number`: Extracted invoice identifier or reference code.
3. `invoice_date`: Normalized to ISO `YYYY-MM-DD` (or `null` if missing).
4. `due_date`: Normalized to ISO `YYYY-MM-DD` (printed due date preferred, or derived from payment terms e.g. "Net 30").
5. `currency`: Standard 3-letter currency code (`USD`, `EUR`, `GBP`, `JPY`, `INR`).
6. `subtotal`: Monetary amount pre-tax (`float` or `null`).
7. `tax`: Monetary tax amount (`float` or `null`).
8. `total`: Total payable amount (`float` or `null`).

### Mandatory Non-Invoice Document Behavior
If the document is a **Quotation**, **Delivery Note**, or **Statement of Account**:
- Identify vendor if present.
- Set all financial fields (`subtotal`, `tax`, `total`, `invoice_number`, etc.) to `null`.
- Set corresponding confidence scores to `0.0`.
- Return clear warning messages explaining the document type.

---

## 2. Workspace & Architecture Overview

```
Bruviti_Assignment/
├── app/
│   ├── __init__.py
│   ├── config.py                 # Configuration settings (thresholds, upload limits)
│   ├── schemas.py                # Pydantic v2 data models (ExtractionResult, ConfidenceScores)
│   ├── pdf_reader.py             # PyMuPDF-based text & metadata extraction with safety guards
│   ├── text_normalizer.py        # Text cleaning, unicode normalization, spatial formatting
│   ├── vendor_matcher.py         # Known vendor registry (6 vendors), aliases, fuzzy matcher
│   ├── date_parser.py            # Multi-format date extractor, ambiguity resolver, payment terms
│   ├── amount_parser.py          # US/EU/UK number format parsing, currency detection
│   ├── document_classifier.py    # Document type detection (Invoice, Quotation, Delivery Note, etc.)
│   ├── field_extractor.py        # Regex & proximity extractors for invoice number, dates, amounts
│   ├── validators.py             # Business rule validation (subtotal+tax≈total, date logic)
│   ├── confidence.py             # Deterministic confidence score calculation engine
│   ├── warnings.py               # Warning generation system
│   ├── pipeline.py               # End-to-end extraction orchestrator
│   └── main.py                   # FastAPI application (serves UI + REST API)
├── templates/
│   └── index.html                # Jinja2 template for interactive web upload UI
├── static/
│   └── styles.css                # Polished modern CSS for web UI
├── scripts/
│   └── generate_test_invoices.py # ReportLab generator for 41 synthetic test invoices + ground truth
├── testdata/
│   ├── ground_truth.json         # 41 ground truth evaluation entries
│   └── *.pdf                     # 41 synthetic invoice PDFs (inv_001.pdf to inv_041.pdf)
├── tests/
│   ├── __init__.py
│   ├── test_amounts.py           # Unit tests for currency and monetary parsing
│   ├── test_dates.py             # Unit tests for date formats, ambiguity, and payment terms
│   ├── test_vendor_matching.py   # Unit tests for vendor matching, aliases, and unknown vendors
│   ├── test_business_rules.py    # Unit tests for financial checks and date ordering
│   ├── test_non_invoices.py      # Unit tests for quotations, delivery notes, and statements
│   ├── test_api.py               # FastAPI integration tests using httpx AsyncClient
│   └── test_generated_invoices.py# Parametrized tests evaluating all 41 synthetic PDFs
├── requirements.txt              # Production and test dependencies
└── HANDOVER_STATUS.md            # This handover document
```

---

## 3. What Has Been Done Up Until Now

### A. Environment & Setup
- Virtual environment created at `.venv/`.
- All required packages installed:
  - `fastapi==0.115.5`, `uvicorn[standard]==0.32.1`, `python-multipart==0.0.12`
  - `pymupdf==1.25.1` (high performance digital PDF text extraction)
  - `python-dateutil==2.9.0.post0`
  - `jinja2==3.1.4`, `reportlab==4.2.5`
  - `pytest==8.3.3`, `pytest-asyncio==0.24.0`, `httpx==0.27.2`

### B. Core Extraction Pipeline (`app/`)
1. **`pdf_reader.py`**:
   - Uses PyMuPDF (`fitz`) for fast deterministic digital text extraction.
   - Enforces upload security checks: 15MB file size limit, empty file check, encrypted PDF detection, and corrupted PDF handling.
2. **`vendor_matcher.py`**:
   - Registered 6 canonical suppliers:
     - `Northwind Traders` (UK, GBP, DD/MM)
     - `Blue Harbour Logistics` (UK, GBP, DD/MM)
     - `Kestrel Components` (US, USD, MM/DD)
     - `Meridian Industrial` (DE, EUR, DD/MM)
     - `Sakura Precision` (JP, JPY, DD/MM)
     - `Pinecrest Packaging` (IN, INR, DD/MM)
   - Handles legal suffix stripping (`Ltd`, `Inc`, `GmbH`, `K.K.`, `Pvt Ltd`).
   - 3-tier matching: exact canonical -> exact alias -> fuzzy similarity (threshold = 80).
   - Strict unknown vendor safeguard: unknown vendors are returned as `"unknown"` without false positive force-fitting.
3. **`date_parser.py`**:
   - Supports ISO (`2026-09-03`, `2026.09.03`, `2026/09/03`), textual (`3 September 2026`, `September 3, 2026`, `3-Sep-2026`), and numeric (`03/09/2026` vs `09/03/2026`).
   - Uses vendor locale hint to disambiguate DD/MM vs MM/DD when both parts are $\le 12$. If ambiguous without locale hint, defaults to DD/MM and issues a warning.
   - Two-digit year handling with sliding window pivot.
   - Payment terms parsing: extracts `"Net 30"`, `"30 days"`, etc., and computes `due_date = invoice_date + days`.
4. **`amount_parser.py`**:
   - Disambiguates US/UK punctuation (`1,234.56`) from European comma decimals (`1.234,56`).
   - Multi-source currency detection: explicit 3-letter codes (`USD`, `EUR`, `GBP`), symbols (`$`, `£`, `€`, `¥`, `₹`), and vendor registry default fallback.
5. **`document_classifier.py`**:
   - Classifies `INVOICE`, `QUOTATION`, `DELIVERY_NOTE`, `STATEMENT`.
   - Distinguishes header titles from inline references (e.g. an invoice referencing `Re: Delivery Note DN-123` is recognized as an `INVOICE`).
6. **`field_extractor.py`**:
   - Targeted label extraction for invoice numbers, dates, subtotal, tax, and total.
7. **`validators.py` & `warnings.py`**:
   - Validates `subtotal + tax == total` with tolerance $\pm 0.05$. Generates warning on arithmetic mismatch while preserving original values.
   - Validates `invoice_date <= due_date`. Generates warning if due date precedes invoice date.
   - Detects conflicts between printed due date and payment-term derived due date.
8. **`confidence.py`**:
   - Calculates field confidence scores based on matching method, label strength, and arithmetic/date cross-validation.
9. **`main.py`**:
   - FastAPI server with `GET /` (upload UI), `POST /extract` (PDF extraction API), and `GET /health`.

### C. Synthetic Dataset Generation (`scripts/generate_test_invoices.py`)
- Generates 41 diverse, realistic test PDFs using ReportLab covering:
  - 6 canonical vendors across UK, US, Germany, Japan, India.
  - Diverse date formats (ISO, textual, numeric, two-digit years).
  - Clean and ambiguous numeric amounts.
  - Edge cases: missing fields, arithmetic mismatches, unknown vendors, and non-invoice documents.
  - Automatically exports `testdata/ground_truth.json`.

### D. Automated Test Suite (`tests/`)
- **Unit & Integration Tests**:
  - `test_dates.py`: 21 tests covering ISO, textual, ambiguous, 2-digit years, and payment terms.
  - `test_amounts.py`: 18 tests covering currencies and formatting.
  - `test_vendor_matching.py`: 19 tests covering matching, aliases, legal suffixes, and unknown vendors.
  - `test_business_rules.py`: 16 tests covering arithmetic validation and date rules.
  - `test_non_invoices.py`: 11 tests covering document classification and nulling behaviour.
  - `test_api.py`: 11 tests covering endpoint status codes, schema validation, and error cases.
  - `test_generated_invoices.py`: 169 parametrized evaluation tests across all 41 synthetic invoices.
- **Current Test Run Result**:
  ```
  265 passed, 6 warnings in 2.56s (100% pass rate)
  ```

---

## 4. Key Bugs Identified & Resolved

1. **Verbose Regex `#` Issue (`app/field_extractor.py`)**:
   - `re.VERBOSE` treated literal `#` inside regex character classes as inline comment markers.
   - *Fix*: Removed `re.VERBOSE` from label regexes and escaped `#`.
2. **Short Dash Textual Dates (`app/date_parser.py`)**:
   - Dates formatted as `3-Sep-2026` failed to match textual date pattern.
   - *Fix*: Added hyphen support in `_TEXT_DMY_RE`.
3. **Document Classifier False Positives (`app/document_classifier.py`)**:
   - Invoices containing text like `"Re: Delivery Note DN-456"` were prematurely flagged as `DELIVERY_NOTE`.
   - *Fix*: Implemented priority checking where `INVOICE` takes precedence unless non-invoice keywords form a standalone heading line.
4. **Windows Encoding Issue in Data Generator (`scripts/generate_test_invoices.py`)**:
   - Unicode `\u2192` crashed Windows `cp1252` console print.
   - *Fix*: Replaced `→` with standard ASCII `->`.
5. **False Positive Vendor Attribution (`app/vendor_matcher.py`)**:
   - Unknown vendors from the US with `$` or Texas addresses were fallback-matched to `Kestrel Components` solely based on country hints.
   - *Fix*: Removed country-hint-only assignment; country hints now only corroborate name matches, ensuring unknown vendors return `"unknown"`.

---

## 5. What Needs To Be Done (Immediate Next Steps)

Here is the exact punch list for Claude or any developer resuming this project:

### 1. Create Comprehensive `README.md`
Provide a complete, standalone documentation file covering:
- **Project Overview & Objectives**: Purpose, assignment brief summary, technology stack.
- **Architecture & Pipeline Flow**: Text extraction -> normalization -> classification -> vendor matching -> field extraction -> business rules & validation -> confidence scoring.
- **Setup & Execution Instructions**:
  ```bash
  python -m venv .venv
  .venv\Scripts\activate   # or source .venv/bin/activate on Linux/macOS
  pip install -r requirements.txt
  python scripts/generate_test_invoices.py
  uvicorn app.main:app --reload --port 8000
  ```
- **Testing**:
  ```bash
  pytest tests/ -v
  ```
- **API Specification**: Sample curl commands and input/output JSON schemas for `POST /extract`.
- **Benchmark / Test Coverage**: Table showing 265 passed tests and extraction accuracy across the 41 synthetic ground-truth invoices.
- **Design Decisions & Trade-offs**: Why PyMuPDF over heavy OCR/Tesseract for digital PDFs, deterministic regex + heuristics over LLM hallucination risk and latency, deterministic confidence scoring.

### 2. Add Dockerfile & Containerization
Create a production-ready `Dockerfile` and `.dockerignore` for one-command deployment:
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN python scripts/generate_test_invoices.py
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 3. Add Latency Benchmark Script (Optional but Impressive)
Create a quick benchmark script `scripts/benchmark_latency.py` that measures extraction latency per invoice across all 41 test files:
- Demonstrates digital PDF extraction typically executes in < 50ms per invoice, well below standard SLA limits.

### 4. Git Commit & Clean Up
- Ensure temporary cache files (`.pytest_cache`, `__pycache__`) are ignored via a clean `.gitignore`.
- Commit all code, tests, scripts, and documentation to the git repository.

---

## 6. Verification Commands to Run

To verify the repository state at any moment:
```bash
# Run the entire test suite
.venv\Scripts\python -m pytest tests/ -v

# Run the test data generator
.venv\Scripts\python scripts/generate_test_invoices.py

# Start the application server
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```
Then visit `http://127.0.0.1:8000` to interact with the web UI or test PDF uploads.
