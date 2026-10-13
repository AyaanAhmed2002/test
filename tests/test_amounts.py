"""
Tests for monetary amount parsing and currency detection.
"""

import pytest
from decimal import Decimal
from app.amount_parser import parse_amount, detect_currency_from_text, round_amount


class TestAmountParsing:
    def test_us_format(self):
        assert parse_amount("1,234.56") == Decimal("1234.56")

    def test_eu_format(self):
        assert parse_amount("1.234,56") == Decimal("1234.56")

    def test_space_thousands(self):
        assert parse_amount("1 234,56") == Decimal("1234.56")

    def test_symbol_prefix_gbp(self):
        assert parse_amount("£433.92") == Decimal("433.92")

    def test_symbol_prefix_eur(self):
        assert parse_amount("€1.234,56") == Decimal("1234.56")

    def test_code_prefix(self):
        assert parse_amount("USD 242.17") == Decimal("242.17")

    def test_jpy_no_decimal(self):
        result = parse_amount("¥12000")
        assert result == Decimal("12000")

    def test_plain_integer(self):
        assert parse_amount("5000") == Decimal("5000")

    def test_plain_float(self):
        assert parse_amount("361.60") == Decimal("361.60")

    def test_negative_parenthesized(self):
        result = parse_amount("(100.00)")
        assert result == Decimal("-100.00")

    def test_inr_symbol(self):
        assert parse_amount("₹50,000.00") == Decimal("50000.00")

    def test_invalid_returns_none(self):
        assert parse_amount("not-a-number") is None

    def test_empty_returns_none(self):
        assert parse_amount("") is None


class TestRounding:
    def test_round_half_up(self):
        v = Decimal("1.005")
        assert round_amount(v) == Decimal("1.01")

    def test_jpy_integer(self):
        v = Decimal("55000")
        assert round_amount(v) == Decimal("55000.00")


class TestCurrencyDetection:
    def test_gbp_code(self):
        code, conf = detect_currency_from_text("Invoice amount: GBP 433.92")
        assert code == "GBP"
        assert conf >= 0.90

    def test_usd_code(self):
        code, conf = detect_currency_from_text("Total: USD 242.17")
        assert code == "USD"
        assert conf >= 0.90

    def test_eur_code(self):
        code, conf = detect_currency_from_text("EUR 1.234,56")
        assert code == "EUR"

    def test_jpy_code(self):
        code, conf = detect_currency_from_text("JPY 55000")
        assert code == "JPY"

    def test_inr_code(self):
        code, conf = detect_currency_from_text("INR 5000")
        assert code == "INR"

    def test_pound_symbol(self):
        code, conf = detect_currency_from_text("Total: £433.92")
        assert code == "GBP"
        assert conf >= 0.90

    def test_euro_symbol(self):
        code, conf = detect_currency_from_text("Total: €500")
        assert code == "EUR"

    def test_rupee_symbol(self):
        code, conf = detect_currency_from_text("Total: ₹50,000")
        assert code == "INR"

    def test_dollar_with_vendor_hint(self):
        code, conf = detect_currency_from_text("Total: $242.17", vendor_currency="USD")
        assert code == "USD"
        assert conf >= 0.85

    def test_vendor_default_fallback(self):
        code, conf = detect_currency_from_text("Total: 433.92", vendor_currency="GBP")
        assert code == "GBP"
        assert conf < 0.85  # inferred

    def test_no_evidence(self):
        code, conf = detect_currency_from_text("Total: 433.92")
        assert conf < 0.50  # very low confidence
