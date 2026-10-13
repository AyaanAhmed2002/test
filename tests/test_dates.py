"""
Tests for date parsing module.
"""

import pytest
from datetime import date
from app.date_parser import parse_date, extract_payment_term_days, derive_due_date


class TestISODates:
    def test_iso_hyphen(self):
        r = parse_date("2026-09-03")
        assert r.value == date(2026, 9, 3)
        assert r.iso == "2026-09-03"
        assert r.confidence >= 0.95

    def test_iso_dotted(self):
        r = parse_date("2026.09.03")
        assert r.value == date(2026, 9, 3)

    def test_iso_slash(self):
        r = parse_date("2026/09/03")
        assert r.value == date(2026, 9, 3)


class TestTextualDates:
    def test_dmy_long(self):
        r = parse_date("3 September 2026")
        assert r.value == date(2026, 9, 3)
        assert r.ambiguous is False

    def test_dmy_short(self):
        r = parse_date("3 Sep 2026")
        assert r.value == date(2026, 9, 3)

    def test_mdy_long(self):
        r = parse_date("September 3, 2026")
        assert r.value == date(2026, 9, 3)

    def test_mdy_abbreviated(self):
        r = parse_date("Sep 3, 2026")
        assert r.value == date(2026, 9, 3)

    def test_ordinal_day(self):
        r = parse_date("3rd September 2026")
        assert r.value == date(2026, 9, 3)

    def test_short_text_dash(self):
        r = parse_date("3-Sep-2026")
        assert r.value == date(2026, 9, 3)


class TestNumericAmbiguous:
    def test_uk_day_first(self):
        """03/09/2026 with day_first=True → 3 September."""
        r = parse_date("03/09/2026", day_first=True)
        assert r.value == date(2026, 9, 3)
        assert r.locale_resolved is True

    def test_us_month_first(self):
        """09/03/2026 with day_first=False → 3 September."""
        r = parse_date("09/03/2026", day_first=False)
        assert r.value == date(2026, 9, 3)
        assert r.locale_resolved is True

    def test_ambiguous_unknown_locale(self):
        """03/09/2026 with day_first=None → null and warning."""
        r = parse_date("03/09/2026", day_first=None)
        assert r.value is None
        assert r.ambiguous is True
        assert len(r.warnings) > 0

    def test_unambiguous_day_gt12(self):
        """15/09/2026 – day (15) > 12, unambiguous regardless of locale."""
        r = parse_date("15/09/2026", day_first=None)
        assert r.value == date(2026, 9, 15)
        assert r.ambiguous is False


class TestTwoDigitYears:
    def test_year_26_maps_to_2026(self):
        r = parse_date("03/09/26", day_first=True)
        assert r.value is not None
        assert r.value.year == 2026

    def test_year_30_maps_to_1930(self):
        r = parse_date("01/01/30", day_first=True)
        # 30 → 1930 per CENTURY_PIVOT
        assert r.value is not None
        assert r.value.year == 1930

    def test_year_29_maps_to_2029(self):
        r = parse_date("01/01/29", day_first=True)
        assert r.value is not None
        assert r.value.year == 2029


class TestInvalidDates:
    def test_invalid_day_31_feb(self):
        r = parse_date("31/02/2026", day_first=True)
        assert r.value is None

    def test_invalid_month_13(self):
        # 13/13/2026: both values > 12, cannot determine day vs month
        # _make_date will fail since month 13 doesn't exist
        r = parse_date("13/13/2026", day_first=False)
        assert r.value is None

    def test_valid_jan_13_us(self):
        # 01/13/2026 in MM/DD = January 13, 2026 (valid)
        r = parse_date("01/13/2026", day_first=False)
        assert r.value is not None
        assert r.value.month == 1
        assert r.value.day == 13

    def test_empty_string(self):
        r = parse_date("")
        assert r.value is None

    def test_garbage(self):
        r = parse_date("not-a-date")
        assert r.value is None


class TestPaymentTerms:
    def test_net30(self):
        assert extract_payment_term_days("Payment Terms: Net 30") == 30

    def test_net15(self):
        assert extract_payment_term_days("NET15") == 15

    def test_30_days(self):
        assert extract_payment_term_days("Payment due in 30 days") == 30

    def test_30_days_from_invoice(self):
        assert extract_payment_term_days("30 days from invoice") == 30

    def test_no_terms(self):
        assert extract_payment_term_days("Please pay promptly.") is None


class TestDeriveDueDate:
    def test_net30(self):
        inv = date(2026, 9, 3)
        due = derive_due_date(inv, 30)
        assert due == date(2026, 10, 3)

    def test_net15(self):
        inv = date(2026, 9, 3)
        due = derive_due_date(inv, 15)
        assert due == date(2026, 9, 18)
