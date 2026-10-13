"""
Vendor registry and matching module.

Design decisions
----------------
* Matching is performed on *normalised* text (upper-case, no legal suffixes,
  no extra punctuation) so "Northwind Traders Ltd." equals "Northwind Traders".
* Exact and alias matching always wins over fuzzy matching.
* Fuzzy matching uses SequenceMatcher from the standard library – no extra
  dependencies, fully offline, and deterministic.
* A minimum ratio of VENDOR_FUZZY_THRESHOLD / 100 is required for a fuzzy hit.
  The default threshold (85) is deliberately conservative to avoid mapping an
  unrelated vendor that happens to share a word.
* Only the vendor section of the PDF (first ~30 lines) is searched by default
  to avoid matching vendor names against customer / bill-to blocks.
* Country hints (country names, locale markers) provide supplementary evidence
  when the vendor name alone is ambiguous.

Registry schema
---------------
Each entry contains:
  canonical   – the exact string to return in the API response
  country     – ISO 3166-1 alpha-2 country code
  currency    – default ISO 4217 currency code
  day_first   – True if DD/MM ambiguous date convention applies
  aliases     – normalised alternative names (after strip_legal_suffixes)
  country_hints – lowercase substrings that appear near the vendor name and
                  confirm country (e.g. address lines, phone prefixes)
"""

from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from dataclasses import dataclass, field

from app.config import VENDOR_FUZZY_THRESHOLD
from app.text_normalizer import normalize_vendor_name

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VendorRecord:
    canonical: str
    country: str          # ISO 3166-1 alpha-2
    currency: str         # ISO 4217
    day_first: bool       # True → DD/MM/YYYY interpretation for ambiguous dates
    aliases: tuple[str, ...]
    country_hints: tuple[str, ...]  # lowercase substrings found near the vendor


# ── Canonical registry ─────────────────────────────────────────────────────────
#
# Aliases are stored pre-normalised (output of normalize_vendor_name).
# Country hints are lowercase substrings that may appear in the address block.

REGISTRY: list[VendorRecord] = [
    VendorRecord(
        canonical="Northwind Traders",
        country="GB",
        currency="GBP",
        day_first=True,
        aliases=(
            "NORTHWIND TRADERS",
            "NORTHWIND TRADING",
            "NORTH WIND TRADERS",
            "NORTHWINDTRADERS",
        ),
        country_hints=("united kingdom", "u.k.", "uk", "england", "london",
                       "manchester", "birmingham", "£"),
    ),
    VendorRecord(
        canonical="Blue Harbour Logistics",
        country="GB",
        currency="GBP",
        day_first=True,
        aliases=(
            "BLUE HARBOUR LOGISTICS",
            "BLUE HARBOR LOGISTICS",
            "BLUE HARBOUR LOG",
            "BLUEHARBOUR LOGISTICS",
            "BLUE HARBOUR",
        ),
        country_hints=("united kingdom", "u.k.", "uk", "england", "london",
                       "liverpool", "bristol", "£"),
    ),
    VendorRecord(
        canonical="Kestrel Components",
        country="US",
        currency="USD",
        day_first=False,  # Month-first for US dates
        aliases=(
            "KESTREL COMPONENTS",
            "KESTREL COMPONENT",
            "KESTREL COMP",
        ),
        country_hints=("united states", "u.s.a.", "usa", "u.s.", "california",
                       "new york", "texas", "chicago", "$"),
    ),
    VendorRecord(
        canonical="Meridian Industrial",
        country="DE",
        currency="EUR",
        day_first=True,
        aliases=(
            "MERIDIAN INDUSTRIAL",
            "MERIDIAN INDUSTRIES",
            "MERIDIAN INDUSTRIE",
            "MERIDIANINDUSTRIAL",
        ),
        country_hints=("germany", "deutschland", "german", "berlin",
                       "munich", "münchen", "hamburg", "€"),
    ),
    VendorRecord(
        canonical="Sakura Precision",
        country="JP",
        currency="JPY",
        day_first=True,
        aliases=(
            "SAKURA PRECISION",
            "SAKURA PREC",
            "SAKURA PRECISION WORKS",
            "SAKURA PRECISION MFG",
        ),
        country_hints=("japan", "japanese", "tokyo", "osaka", "kyoto",
                       "¥", "yen"),
    ),
    VendorRecord(
        canonical="Pinecrest Packaging",
        country="IN",
        currency="INR",
        day_first=True,
        aliases=(
            "PINECREST PACKAGING",
            "PINECREST PACK",
            "PINE CREST PACKAGING",
            "PINECREST PACKAG",
        ),
        country_hints=("india", "indian", "mumbai", "delhi", "bangalore",
                       "chennai", "hyderabad", "₹", "inr"),
    ),
]


# ── Match result ───────────────────────────────────────────────────────────────

@dataclass
class VendorMatch:
    record: VendorRecord | None   # None when vendor is unknown
    confidence: float             # 0.0–1.0
    method: str                   # "exact", "alias", "fuzzy", "hint", "unknown"


# ── Internal helpers ───────────────────────────────────────────────────────────

def _fuzzy_ratio(a: str, b: str) -> float:
    """SequenceMatcher ratio between two strings (0–1)."""
    return SequenceMatcher(None, a, b).ratio()


def _extract_vendor_region(text: str, max_lines: int = 40) -> str:
    """
    Return the first `max_lines` lines of the document.

    The vendor name almost always appears at the top of an invoice (logo /
    company name block).  Limiting to the top of the document prevents false
    matches against the customer name or line-item descriptions.
    """
    lines = text.splitlines()[:max_lines]
    return "\n".join(lines)


def _score_country_hints(record: VendorRecord, text_lower: str) -> float:
    """Return a small bonus (0–0.10) for each country hint found in text."""
    hits = sum(1 for h in record.country_hints if h in text_lower)
    return min(hits * 0.03, 0.10)


# ── Public interface ───────────────────────────────────────────────────────────

def match_vendor(full_text: str) -> VendorMatch:
    """
    Identify the canonical vendor from extracted PDF text.

    Strategy (in priority order):
    1. Exact match against canonical name (normalised).
    2. Exact match against any registered alias.
    3. Fuzzy match against canonical and aliases with ratio ≥ threshold.
    4. Country-hint-only match (very low confidence).
    5. Unknown vendor.

    Parameters
    ----------
    full_text : str
        The complete extracted text of the PDF.

    Returns
    -------
    VendorMatch
        Contains the matched VendorRecord (or None), confidence score,
        and method used.
    """
    vendor_region = _extract_vendor_region(full_text)
    vendor_region_norm = normalize_vendor_name(vendor_region)
    text_lower = full_text.lower()

    best_record: VendorRecord | None = None
    best_ratio: float = 0.0
    best_method: str = "unknown"

    for record in REGISTRY:
        # 1. Exact canonical match
        canon_norm = normalize_vendor_name(record.canonical)
        if canon_norm in vendor_region_norm:
            logger.debug("Exact canonical match: %s", record.canonical)
            hint_bonus = _score_country_hints(record, text_lower)
            return VendorMatch(
                record=record,
                confidence=min(0.98 + hint_bonus, 1.0),
                method="exact",
            )

        # 2. Exact alias match
        for alias in record.aliases:
            alias_norm = normalize_vendor_name(alias)
            if alias_norm in vendor_region_norm:
                logger.debug("Alias match: %s → %s", alias, record.canonical)
                hint_bonus = _score_country_hints(record, text_lower)
                return VendorMatch(
                    record=record,
                    confidence=min(0.93 + hint_bonus, 1.0),
                    method="alias",
                )

        # 3. Fuzzy match – compare each line against canonical + aliases
        threshold = VENDOR_FUZZY_THRESHOLD / 100.0
        for line in vendor_region.splitlines():
            line_norm = normalize_vendor_name(line)
            if len(line_norm) < 4:
                continue
            candidates = [normalize_vendor_name(record.canonical)] + [
                normalize_vendor_name(a) for a in record.aliases
            ]
            for cand in candidates:
                ratio = _fuzzy_ratio(line_norm, cand)
                if ratio >= threshold and ratio > best_ratio:
                    best_ratio = ratio
                    best_record = record
                    best_method = "fuzzy"

    if best_record is not None:
        hint_bonus = _score_country_hints(best_record, text_lower)
        # Scale fuzzy confidence: threshold → 0.72, 1.0 → 0.96
        conf = 0.72 + (best_ratio - threshold) / (1.0 - threshold) * 0.24
        conf = min(conf + hint_bonus, 1.0)
        return VendorMatch(record=best_record, confidence=round(conf, 3), method=best_method)

    # 4. Unknown - do not force-fit based on country hints alone
    return VendorMatch(record=None, confidence=0.0, method="unknown")


def get_vendor_currency(match: VendorMatch) -> str | None:
    """Return the default currency for a matched vendor, or None if unknown."""
    if match.record is not None:
        return match.record.currency
    return None


def get_day_first(match: VendorMatch) -> bool | None:
    """
    Return True if the vendor uses DD/MM date convention,
    False if MM/DD, or None if unknown.
    """
    if match.record is not None:
        return match.record.day_first
    return None
