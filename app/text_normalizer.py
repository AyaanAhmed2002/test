"""
Text normalisation utilities.

Provides lightweight, reversible transformations that make downstream regex
matching more reliable without destroying positional structure.
"""

from __future__ import annotations

import re
import unicodedata


# ── public helpers ─────────────────────────────────────────────────────────────

def normalize_whitespace(text: str) -> str:
    """Collapse multiple spaces/tabs to a single space; keep newlines."""
    # Collapse horizontal whitespace only – preserve line structure
    text = re.sub(r"[^\S\n]+", " ", text)
    # Collapse 3+ consecutive newlines to 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_unicode(text: str) -> str:
    """
    Decompose and recompose unicode; replace exotic whitespace with ASCII.
    Preserves currency symbols and special characters that carry meaning.
    """
    # Normalize to NFC so accented chars behave consistently
    text = unicodedata.normalize("NFC", text)
    # Replace non-breaking spaces and similar with regular space
    text = re.sub(r"[\u00a0\u202f\u2009\u2007\u2008\u200b]", " ", text)
    return text


def normalize_text(text: str) -> str:
    """Apply all normalisation steps in the correct order."""
    text = normalize_unicode(text)
    text = normalize_whitespace(text)
    return text


def strip_legal_suffixes(name: str) -> str:
    """
    Remove common legal-entity suffixes for vendor name comparison.

    Handles: LTD, LIMITED, INC, INCORPORATED, LLC, LLP, CORP, CORPORATION,
    GMBH, AG, NV, BV, KK, PTE, PTY, SA, SAS, SRL, OY, AB, AS
    """
    suffixes = (
        r"\bLIMITED\b",
        r"\bLTD\.?\b",
        r"\bINCORPORATED\b",
        r"\bINC\.?\b",
        r"\bCORPORATION\b",
        r"\bCORP\.?\b",
        r"\bLLC\.?\b",
        r"\bLLP\.?\b",
        r"\bGMBH\.?\b",
        r"\bAG\.?\b",
        r"\bNV\.?\b",
        r"\bBV\.?\b",
        r"\bKK\.?\b",
        r"\bPTE\.?\b",
        r"\bPTY\.?\b",
        r"\bSA\.?\b",
        r"\bSAS\.?\b",
        r"\bSRL\.?\b",
        r"\bOY\.?\b",
        r"\bAB\.?\b",
        r"\bAS\.?\b",
        r"\bCO\.?\b",
        r"\bPLC\.?\b",
    )
    pattern = "|".join(suffixes)
    cleaned = re.sub(pattern, "", name.upper(), flags=re.IGNORECASE)
    # Remove leftover punctuation and extra spaces
    cleaned = re.sub(r"[,.\-&]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def normalize_vendor_name(name: str) -> str:
    """Case-fold and strip suffixes for comparison purposes."""
    return strip_legal_suffixes(name.upper())
