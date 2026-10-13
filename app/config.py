"""
Application configuration constants.

Upload / processing limits and default behaviours are centralised here so
they can be adjusted without touching business logic.
"""

# Maximum allowed upload size in bytes (10 MB)
MAX_UPLOAD_BYTES: int = 10 * 1024 * 1024

# Maximum number of PDF pages to process (avoids runaway parsing on huge docs)
MAX_PAGES: int = 20

# Two-digit year: years 00-29 → 2000-2029, 30-99 → 1930-1999
CENTURY_PIVOT: int = 30

# Supported ISO 4217 currency codes
SUPPORTED_CURRENCIES: list[str] = ["GBP", "USD", "EUR", "JPY", "INR"]

# Financial mismatch tolerance (Decimal-comparable string)
AMOUNT_TOLERANCE: str = "0.01"

# Minimum fuzzy-match ratio (0–100) to accept as a vendor alias match
VENDOR_FUZZY_THRESHOLD: int = 85
