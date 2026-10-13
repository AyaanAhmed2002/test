# Invoice Field Extractor

> **Bruviti Campus Drive 2026 — Use Case 3: Invoice Field Extraction**

A production-quality FastAPI service that accepts digital supplier invoice PDFs, extracts eight structured header fields, assigns deterministic confidence scores to each field, and returns actionable warnings for ambiguous or non-invoice documents.

**No Docker required.** The project runs from a Python virtual environment with a single documented startup command. Docker is provided as an optional convenience only.

---

## Table of Contents

1. [Quick Start (Fresh Clone)](#quick-start-fresh-clone)
2. [Features](#features)
3. [Architecture & Pipeline](#architecture--pipeline)
4. [Project Structure](#project-structure)
5. [Setup — Step by Step](#setup--step-by-step)
6. [Running the Service](#running-the-service)
7. [API Reference](#api-reference)
8. [Web UI](#web-ui)
9. [Running Tests](#running-tests)
10. [Synthetic Test Data](#synthetic-test-data)
11. [Known Vendors](#known-vendors)
12. [Design Decisions & Trade-offs](#design-decisions--trade-offs)
13. [Docker (Optional)](#docker-optional)

---

## Quick Start (Fresh Clone)

**Prerequisites**: Python 3.11 or later installed and on your `PATH`.

### Windows
```bat
git clone <repo-url>
cd Bruviti_Assignment
setup.bat
```

### Linux / macOS
```bash
git clone <repo-url>
cd Bruviti_Assignment
chmod +x setup.sh && ./setup.sh
```

Both scripts create the virtual environment, install all pinned dependencies, generate the synthetic test dataset, and run the full test suite. When they finish you will see:

```
265 passed, 6 warnings in ~2.5s
```

### Start the server
```bat
REM Windows
.venv\Scripts\uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
```bash
# Linux / macOS
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Open `http://127.0.0.1:8000` to use the web UI.

---

## Features

| Capability | Detail |
|---|---|
| **8 header fields** | vendor, invoice_number, invoice_date, due_date, currency, subtotal, tax, total |
| **Per-field confidence** | Deterministic score `[0.0, 1.0]` based on extraction method strength |
| **Date formats** | ISO (`2026-09-03`), textual (`3 Sep 2026`, `September 3rd, 2026`), numeric (`03/09/2026`) |
| **Locale-aware dates** | DD/MM vs MM/DD resolved from vendor registry; warns on genuine ambiguity |
| **Currency detection** | Explicit codes (`USD`, `EUR`), symbols (`$`, `£`, `€`, `¥`, `₹`), vendor-default fallback |
| **Amount formats** | US `1,234.56`, European `1.234,56`, Japanese `¥55,000` |
| **Non-invoice handling** | Quotations, Delivery Notes, Statements → null financial fields + warnings |
| **Business validation** | Arithmetic check (`subtotal + tax ≈ total`), date ordering, due-date / payment-term conflict |
| **Security guards** | 15 MB upload limit, non-PDF rejection (HTTP 415), encrypted PDF (422), empty/corrupted PDF (422) |
| **Fast extraction** | Digital PDF text extraction via PyMuPDF; typically < 50 ms per invoice |

---

## Architecture & Pipeline

```
PDF Upload (multipart/form-data)
        │
        ▼
┌───────────────────┐
│  pdf_reader.py    │  PyMuPDF text extraction + safety validation
└────────┬──────────┘
         │  raw page text
         ▼
┌───────────────────┐
│ text_normalizer   │  Unicode normalization, whitespace cleanup
└────────┬──────────┘
         │  clean text
         ▼
┌───────────────────┐         ┌────────────────────────┐
│  vendor_matcher   │──────►  │  document_classifier   │
│  (6 known vendors)│         │  INVOICE / QUOTATION   │
└────────┬──────────┘         │  DELIVERY_NOTE, etc.   │
         │ vendor + locale    └────────────┬───────────┘
         │                                │ non-invoice → null fields + warning
         ▼                                │ invoice ↓
┌───────────────────┐                     │
│  field_extractor  │ ◄───────────────────┘
│  invoice_number   │  label-proximity regex extraction
│  invoice_date     │
│  due_date         │
│  payment_terms    │
│  currency         │
│  subtotal/tax/tot │
└────────┬──────────┘
         │ raw parsed values
         ▼
┌───────────────────┐
│   validators.py   │  subtotal+tax≈total, date ordering, due-date vs terms conflict
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│   confidence.py   │  Deterministic per-field confidence scores
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│   warnings.py     │  Human-readable warning messages
└────────┬──────────┘
         │
         ▼
     JSON Response  (ExtractionResult schema)
```

---

## Project Structure

```
Bruviti_Assignment/
├── app/
│   ├── __init__.py
│   ├── config.py               # Upload limits, fuzzy thresholds, tolerances
│   ├── schemas.py              # Pydantic v2 models: ExtractionResult, ConfidenceScores
│   ├── pdf_reader.py           # PyMuPDF text extraction + upload safety guards
│   ├── text_normalizer.py      # Unicode & whitespace normalization
│   ├── vendor_matcher.py       # 6-vendor registry with alias & fuzzy matching
│   ├── date_parser.py          # Multi-format date parser, payment terms, due-date derivation
│   ├── amount_parser.py        # US/EU/UK number format parser, currency detector
│   ├── document_classifier.py  # INVOICE / QUOTATION / DELIVERY_NOTE / STATEMENT
│   ├── field_extractor.py      # Label-proximity field extraction for all 8 fields
│   ├── validators.py           # Business rule validation (arithmetic, date ordering)
│   ├── confidence.py           # Confidence score engine
│   ├── warnings.py             # Warning message generator
│   ├── pipeline.py             # End-to-end extraction orchestrator
│   └── main.py                 # FastAPI application (UI + REST API)
├── templates/
│   └── index.html              # Jinja2 interactive upload UI
├── static/
│   └── styles.css              # Modern web UI stylesheet
├── scripts/
│   ├── generate_test_invoices.py  # ReportLab PDF generator (41 synthetic invoices)
│   └── benchmark_latency.py       # Per-invoice latency benchmarking
├── testdata/                      # Created by generate_test_invoices.py
│   ├── ground_truth.json
│   └── *.pdf
├── tests/
│   ├── test_amounts.py
│   ├── test_dates.py
│   ├── test_vendor_matching.py
│   ├── test_business_rules.py
│   ├── test_non_invoices.py
│   ├── test_api.py
│   └── test_generated_invoices.py
├── requirements.txt            # All direct dependencies, fully pinned
├── setup.bat                   # Windows one-command fresh-clone bootstrap
├── setup.sh                    # Linux / macOS one-command bootstrap
├── Dockerfile                  # Optional — not required to run the project
├── .dockerignore
├── .gitignore
└── README.md
```

---

## Setup — Step by Step

If you prefer to run each step manually instead of the setup scripts:

### 1. Create a virtual environment
```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install all dependencies
```bash
pip install -r requirements.txt
```

All packages are pinned — this is a deterministic, reproducible install.

### 3. Generate the synthetic test dataset
```bash
python scripts/generate_test_invoices.py
```

Creates `testdata/ground_truth.json` and 41 synthetic invoice PDFs.  
Only needed once (or after a clean checkout).

### 4. Verify with the test suite
```bash
python -m pytest tests/ -v
```

Expected result: **265 passed, 6 warnings**.

### 5. Start the server
```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

---

## Running the Service

Once the server is running, the following endpoints are available:

| Endpoint | Method | Description |
|---|---|---|
| `/` | `GET` | Interactive HTML upload UI |
| `/extract` | `POST` | Invoice field extraction API |
| `/health` | `GET` | Service readiness check |
| `/docs` | `GET` | Swagger UI (auto-generated) |
| `/redoc` | `GET` | ReDoc API documentation |

---

## API Reference

### `POST /extract`

Extract invoice fields from a PDF file.

**Request**: `multipart/form-data`

| Field | Type | Description |
|---|---|---|
| `file` | `File` | PDF file, max 15 MB, digital text-based |

**Example — curl**
```bash
curl -X POST http://127.0.0.1:8000/extract \
  -F "file=@invoice.pdf" \
  | python -m json.tool
```

**Success Response — `200 OK`**
```json
{
  "vendor": "Northwind Traders",
  "invoice_number": "INV-4821",
  "invoice_date": "2026-09-03",
  "due_date": "2026-10-03",
  "currency": "GBP",
  "subtotal": 850.00,
  "tax": 170.00,
  "total": 1020.00,
  "confidence": {
    "vendor": 0.98,
    "invoice_number": 0.95,
    "invoice_date": 0.97,
    "due_date": 0.72,
    "currency": 0.99,
    "subtotal": 0.88,
    "tax": 0.88,
    "total": 0.91
  },
  "warnings": [
    "Due date derived from payment terms: Net 30 -> 2026-10-03"
  ]
}
```

**Non-Invoice Response — `200 OK`**
```json
{
  "vendor": "Northwind Traders",
  "invoice_number": null,
  "invoice_date": null,
  "due_date": null,
  "currency": "unknown",
  "subtotal": null,
  "tax": null,
  "total": null,
  "confidence": {
    "vendor": 0.98,
    "invoice_number": 0.0,
    "invoice_date": 0.0,
    "due_date": 0.0,
    "currency": 0.0,
    "subtotal": 0.0,
    "tax": 0.0,
    "total": 0.0
  },
  "warnings": [
    "Document classified as QUOTATION — financial fields are not extracted."
  ]
}
```

**Error Responses**

| HTTP Code | Condition |
|---|---|
| `400` | Could not read the uploaded file |
| `413` | File exceeds the 15 MB limit |
| `415` | File is not a PDF |
| `422` | Encrypted, empty, or corrupted PDF |
| `500` | Unexpected internal server error |

---

## Web UI

Visit `http://127.0.0.1:8000` for the interactive upload interface.

- Drag-and-drop or browse to select a PDF.
- All 8 extracted fields, their colour-coded confidence scores, and all warnings are displayed inline.

---

## Running Tests

```bash
# Full test suite (recommended)
python -m pytest tests/ -v

# Individual test modules
python -m pytest tests/test_dates.py -v
python -m pytest tests/test_amounts.py -v
python -m pytest tests/test_vendor_matching.py -v
python -m pytest tests/test_business_rules.py -v
python -m pytest tests/test_non_invoices.py -v
python -m pytest tests/test_api.py -v

# Evaluation against all 41 synthetic invoices
# (requires: python scripts/generate_test_invoices.py)
python -m pytest tests/test_generated_invoices.py -v
```

### Test Coverage

| Module | Tests | What Is Verified |
|---|---|---|
| `test_dates.py` | 21 | ISO, textual, numeric, ambiguous, 2-digit year, payment terms |
| `test_amounts.py` | 18 | US/EU/UK number formats, currency symbols and codes |
| `test_vendor_matching.py` | 19 | Exact, alias, fuzzy matching; legal suffix stripping; unknown vendors |
| `test_business_rules.py` | 16 | Financial arithmetic, date ordering, due-date vs payment-term conflict |
| `test_non_invoices.py` | 11 | Quotation, delivery note, statement — null fields, warnings, classification |
| `test_api.py` | 11 | HTTP status codes, schema validation, error edge cases |
| `test_generated_invoices.py` | 169 | 41 synthetic PDFs × vendor / date / currency / confidence assertions |
| **Total** | **265** | **265 passed, 100% pass rate** |

---

## Synthetic Test Data

| Category | Count | Details |
|---|---|---|
| Standard invoices | 30 | All 6 vendors, 3 layout variants, multiple date formats |
| Date format edge cases | 4 | ISO slash, dotted ISO, two-digit year, `3-Sep-2026` dash textual |
| Amount edge cases | 5 | European comma decimal, explicit currency code, missing subtotal, arithmetic mismatch, JPY no-decimal |
| Missing field cases | 2 | Missing invoice date, missing invoice number |
| Unknown vendors | 2 | `Apex Supplies Co.` (USD), `GlobalParts AG` (EUR) |
| Non-invoice documents | 3 | Quotation, Delivery Note, Statement of Account |
| **Total** | **41** | |

---

## Known Vendors

| Canonical Name | Country | Currency | Date Convention |
|---|---|---|---|
| Northwind Traders | UK | GBP | DD/MM/YYYY |
| Blue Harbour Logistics | UK | GBP | DD/MM/YYYY |
| Kestrel Components | US | USD | MM/DD/YYYY |
| Meridian Industrial | Germany | EUR | DD/MM/YYYY |
| Sakura Precision | Japan | JPY | DD/MM/YYYY |
| Pinecrest Packaging | India | INR | DD/MM/YYYY |

Unknown vendors return `"vendor": "unknown"` with an informational warning.

---

## Design Decisions & Trade-offs

### Why PyMuPDF instead of OCR?
Digital invoice PDFs embed text natively. PyMuPDF extracts it in microseconds with 100% character fidelity and no system dependencies. OCR (Tesseract / cloud vision) would add hundreds of milliseconds of latency and require an external binary install — unnecessarily expensive for digital PDFs.

**Trade-off**: Rasterized / scanned PDFs would need an OCR step. This project is scoped to digital supplier invoices.

### Why deterministic regex/heuristics instead of an LLM?

| Factor | LLM approach | This approach |
|---|---|---|
| Latency | 500 ms – 5 s (network round trip) | < 50 ms (local, no network) |
| Cost | Per-request API fee | Zero marginal cost |
| Reproducibility | Non-deterministic | 100% reproducible across runs |
| Auditability | Opaque | Every decision is traceable |
| Data privacy | Invoice data leaves the system | All processing is local |

**Trade-off**: LLMs generalize better to radically unseen layouts. Deterministic heuristics excel on the structured, predictable layouts of known supplier invoices.

### Why does the printed due date take priority over the derived one?
The printed due date is the legally binding payment deadline. Payment terms (e.g., `Net 30`) may be the contract template default, not the agreed-upon term for a specific invoice. A warning is raised when both are present and conflict.

### Why are confidence scores deterministic?
They are calculated from the strength of extraction signals (exact label match > fuzzy match > heuristic inference), cross-validation results (arithmetic consistency, date ordering), and locale corroboration. This makes them auditable, reproducible, and free of probabilistic ML overhead.

---

## Docker (Optional)

Docker is **not required** to run or test this project. If you want to containerize it:

```bash
docker build -t invoice-extractor .
docker run -p 8000:8000 invoice-extractor
```

The `Dockerfile` in the repository generates the test data at build time and starts the server on port 8000. The application is fully functional without Docker.
