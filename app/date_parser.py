"""
Date parsing module.

Two-digit year policy
---------------------
  Years 00–29 → 2000–2029
  Years 30–99 → 1930–1999  (CENTURY_PIVOT = 30)

Ambiguity resolution
---------------------
  When the day and month values are both ≤ 12 (e.g. 03/09/2026), the date
  is ambiguous for numeric formats (DD/MM vs MM/DD).
  Resolution priority:
    1. Use the vendor's country convention (day_first parameter).
    2. If vendor is unknown (day_first=None) and the date is ambiguous,
       return None and add a warning.
    3. Textual months (e.g. "3 September 2026") are always unambiguous.
    4. ISO-format dates (YYYY-MM-DD, YYYY.MM.DD) are always unambiguous.

Public API
----------
parse_date(raw: str, day_first: bool | None) -> ParsedDate
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.config import CENTURY_PIVOT


@dataclass
class ParsedDate:
    value: date | None          # None when parsing fails or date is ambiguous
    iso: str | None             # ISO YYYY-MM-DD string, or None
    ambiguous: bool = False     # True when numeric format was ambiguous
    locale_resolved: bool = False  # True when vendor locale broke the ambiguity
    warnings: list[str] = field(default_factory=list)
    confidence: float = 0.0


# ── Month name tables ──────────────────────────────────────────────────────────

_MONTH_NAMES = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}

_MONTH_RE = (
    r"(?:january|february|march|april|may|june|july|august|september|"
    r"october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)"
)

# ── Date patterns (ordered by specificity) ────────────────────────────────────

# ISO:  2026-09-03  or  2026.09.03
_ISO_RE = re.compile(
    r"\b(\d{4})[-./](\d{1,2})[-./](\d{1,2})\b",
    re.IGNORECASE,
)

# Textual: 3 September 2026  /  September 3, 2026  /  3rd Sep 2026  /  3-Sep-2026
_TEXT_DMY_RE = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\-]+(" + _MONTH_RE + r")[\s\-]+(\d{2,4})\b",
    re.IGNORECASE,
)
_TEXT_MDY_RE = re.compile(
    r"\b(" + _MONTH_RE + r")[\s\-]+(\d{1,2})(?:st|nd|rd|th)?,?[\s\-]+(\d{2,4})\b",
    re.IGNORECASE,
)

# Numeric ambiguous:  03/09/2026  or  3-9-26  or  03.09.2026
_NUMERIC_RE = re.compile(
    r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})\b",
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _expand_year(y: int) -> int:
    """Expand a two-digit year using the CENTURY_PIVOT policy."""
    if y < 100:
        return (2000 + y) if y < CENTURY_PIVOT else (1900 + y)
    return y


def _make_date(year: int, month: int, day: int) -> date | None:
    """Return a date or None if the combination is invalid."""
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _confidence_for_date(d: date | None, ambiguous: bool, locale_resolved: bool) -> float:
    if d is None:
        return 0.0
    if ambiguous and not locale_resolved:
        return 0.50
    if locale_resolved:
        return 0.82
    return 0.95


# ── Core parsing ───────────────────────────────────────────────────────────────

def _try_iso(raw: str) -> ParsedDate | None:
    """Match ISO-style dates (YYYY-MM-DD, YYYY.MM.DD).  Always unambiguous."""
    m = _ISO_RE.match(raw.strip())
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    dt = _make_date(y, mo, d)
    if dt is None:
        return ParsedDate(
            value=None, iso=None, confidence=0.0,
            warnings=[f"Invalid ISO date: {raw.strip()!r}"],
        )
    return ParsedDate(value=dt, iso=dt.isoformat(), confidence=0.97)


def _try_textual(raw: str) -> ParsedDate | None:
    """Match dates that contain a written month name.  Always unambiguous."""
    # D Month YYYY
    m = _TEXT_DMY_RE.match(raw.strip())
    if m:
        d = int(m.group(1))
        mo = _MONTH_NAMES[m.group(2).lower()]
        y = _expand_year(int(m.group(3)))
        dt = _make_date(y, mo, d)
        if dt is None:
            return ParsedDate(
                value=None, iso=None, confidence=0.0,
                warnings=[f"Invalid date: {raw.strip()!r}"],
            )
        return ParsedDate(value=dt, iso=dt.isoformat(), confidence=0.97)

    # Month D, YYYY
    m = _TEXT_MDY_RE.match(raw.strip())
    if m:
        mo = _MONTH_NAMES[m.group(1).lower()]
        d = int(m.group(2))
        y = _expand_year(int(m.group(3)))
        dt = _make_date(y, mo, d)
        if dt is None:
            return ParsedDate(
                value=None, iso=None, confidence=0.0,
                warnings=[f"Invalid date: {raw.strip()!r}"],
            )
        return ParsedDate(value=dt, iso=dt.isoformat(), confidence=0.97)

    return None


def _try_numeric(raw: str, day_first: bool | None) -> ParsedDate:
    """
    Match purely numeric dates.  May be ambiguous.

    day_first=True  → DD/MM/YYYY
    day_first=False → MM/DD/YYYY
    day_first=None  → unknown convention; ambiguous dates return None
    """
    m = _NUMERIC_RE.match(raw.strip())
    if not m:
        return ParsedDate(
            value=None, iso=None, confidence=0.0,
            warnings=[f"Could not parse date: {raw.strip()!r}"],
        )

    a, b, c = int(m.group(1)), int(m.group(2)), int(m.group(3))
    y = _expand_year(c)

    # Determine if ambiguous (both a and b could be day or month)
    ambiguous = (1 <= a <= 12) and (1 <= b <= 12) and (a != b)

    if not ambiguous:
        # One value must be the day (> 12 means it's the day)
        if a > 12:
            # a is definitely the day
            dt = _make_date(y, b, a)
        elif b > 12:
            # b is definitely the day; a is month
            # But validate that a is a valid month
            if a > 12:
                return ParsedDate(
                    value=None, iso=None, confidence=0.0,
                    warnings=[f"Invalid month value in date: {raw.strip()!r}"],
                )
            dt = _make_date(y, a, b)
        else:
            # a == b, either interpretation gives same date
            dt = _make_date(y, a, b)
        if dt is None:
            return ParsedDate(
                value=None, iso=None, confidence=0.0,
                warnings=[f"Invalid date values: {raw.strip()!r}"],
            )
        return ParsedDate(value=dt, iso=dt.isoformat(), confidence=0.92)

    # Ambiguous – need locale
    if day_first is None:
        return ParsedDate(
            value=None, iso=None,
            ambiguous=True, locale_resolved=False,
            confidence=0.0,
            warnings=[
                f"Date {raw.strip()!r} is ambiguous (DD/MM vs MM/DD) and vendor "
                "locale is unknown; returning null."
            ],
        )

    if day_first:
        dt = _make_date(y, b, a)   # DD/MM: a=day, b=month
    else:
        dt = _make_date(y, a, b)   # MM/DD: a=month, b=day

    if dt is None:
        return ParsedDate(
            value=None, iso=None, confidence=0.0,
            warnings=[f"Invalid date after locale resolution: {raw.strip()!r}"],
        )

    locale_warning = (
        f"Date {raw.strip()!r} was ambiguous; interpreted as "
        f"{'DD/MM' if day_first else 'MM/DD'} per vendor locale → {dt.isoformat()}."
    )
    return ParsedDate(
        value=dt, iso=dt.isoformat(),
        ambiguous=True, locale_resolved=True,
        confidence=_confidence_for_date(dt, True, True),
        warnings=[locale_warning],
    )


# ── Public parse_date ──────────────────────────────────────────────────────────

def parse_date(raw: str, day_first: bool | None = None) -> ParsedDate:
    """
    Parse a date string into a ParsedDate.

    Parameters
    ----------
    raw : str
        A single date candidate string (no surrounding text).
    day_first : bool | None
        True → DD/MM convention; False → MM/DD; None → unknown.

    Returns
    -------
    ParsedDate
        Always returned; value=None indicates failure or ambiguity.
    """
    raw = raw.strip()
    if not raw:
        return ParsedDate(value=None, iso=None, confidence=0.0,
                          warnings=["Empty date string."])

    # Try ISO first (unambiguous)
    result = _try_iso(raw)
    if result is not None:
        return result

    # Try textual (unambiguous)
    result = _try_textual(raw)
    if result is not None:
        return result

    # Try numeric (potentially ambiguous)
    return _try_numeric(raw, day_first)


# ── Payment term derivation ────────────────────────────────────────────────────

_PAYMENT_TERM_RE = re.compile(
    r"""
    (?:
        net\s*(\d+)               # "Net 30", "NET30"
      | (\d+)\s*days?(?:\s+from\s+(?:invoice|date))?  # "30 days", "30 days from invoice"
      | due\s+in\s+(\d+)\s*days? # "Due in 30 days"
      | payable\s+in\s+(\d+)\s*days?  # "Payable in 30 days"
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def extract_payment_term_days(text: str) -> int | None:
    """
    Return the number of days in the payment term, or None if not found.

    Searches the whole text for the first matching payment-term pattern.
    """
    m = _PAYMENT_TERM_RE.search(text)
    if not m:
        return None
    # Return whichever group matched
    for g in m.groups():
        if g is not None:
            return int(g)
    return None


def derive_due_date(invoice_date: date, days: int) -> date:
    """Add `days` to `invoice_date` and return the resulting date."""
    return invoice_date + timedelta(days=days)
