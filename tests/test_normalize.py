from datetime import date, datetime

import pytest

from data_merger import normalize as nz


@pytest.mark.parametrize("raw", [
    "(614) 555-0101", "614-555-0101", "614.555.0101", "6145550101", "+1 614 555 0101",
    "1-614-555-0101",
])
def test_phone_formats_become_one(raw):
    assert nz.norm_phone(raw) == "(614) 555-0101"
    assert nz.phone_digits(raw) == "6145550101"


def test_phone_keeps_extension_and_odd_numbers():
    assert nz.norm_phone("614-555-0101 ext. 22") == "(614) 555-0101 x22"
    assert nz.norm_phone("555-0101") == "555-0101"


@pytest.mark.parametrize("raw", [
    "2026-03-05", "03/05/2026", "3/5/26", "Mar 05, 2026", "March 5, 2026", "05-Mar-2026",
    "2026-03-05T00:00:00",
])
def test_dates_become_iso(raw):
    assert nz.norm_date(raw) == "2026-03-05"


def test_dayfirst_and_unparseable_dates():
    assert nz.norm_date("05/03/2026", dayfirst=True) == "2026-03-05"
    assert nz.norm_date("sometime in spring") == "sometime in spring"
    assert nz.normalize_value("date", "sometime in spring") == ("sometime in spring", False)


@pytest.mark.parametrize(("raw", "expected"), [
    ("$1,250.00", 1250.0), ("1250", 1250.0), ("(40.00)", -40.0), ("-12.5", -12.5),
    ("USD 3,000", 3000.0), ("n/a", None),
])
def test_money(raw, expected):
    assert nz.parse_money(raw) == expected


def test_name_casing_fixes_caps_but_keeps_mixed_case():
    assert nz.norm_name("MCDONALD") == "McDonald"
    assert nz.norm_name("o'brien") == "O'Brien"
    assert nz.norm_name("smith-jones") == "Smith-Jones"
    assert nz.norm_name("DeShawn") == "DeShawn"


@pytest.mark.parametrize(("raw", "expected"), [
    ("Hale, Robert", ("Robert", "Hale")),
    ("Robert Hale", ("Robert", "Hale")),
    ("Dr. Robert Hale Jr", ("Robert", "Hale")),
    ("Mary Ann Van Dyke", ("Mary Ann", "Van Dyke")),
    ("Cher", ("Cher", "")),
])
def test_split_full_name(raw, expected):
    assert nz.split_full_name(raw) == expected


def test_address_parts():
    assert nz.split_full_address("12 Oak St, Apt 4, Dayton, OH 45402") == {
        "street": "12 Oak St, Apt 4", "city": "Dayton", "state": "OH", "postal_code": "45402",
    }
    assert nz.split_full_address("12 Oak St Dayton") == {"street": "12 Oak St Dayton"}
    assert nz.street_key("12 Oak Street, Apartment 4") == nz.street_key("12 OAK ST APT 4")
    assert nz.norm_street("12 OAK ST NE") == "12 Oak St NE"


def test_state_zip_company_email():
    assert nz.norm_state("ohio") == "OH"
    assert nz.norm_state("oh") == "OH"
    assert nz.norm_postal("2134") == "02134"
    assert nz.norm_postal("432011234") == "43201-1234"
    assert nz.company_key("The Acme Supply Co., Inc.") == nz.company_key("ACME SUPPLY")
    assert nz.norm_email(" RHale@Example.COM ") == "rhale@example.com"
    assert nz.normalize_value("email", "not an email") == ("not an email", False)


def test_nicknames_share_a_key():
    assert nz.first_name_key("Bob") == nz.first_name_key("Robert") == nz.first_name_key("ROB")


def test_excel_cells_become_clean_strings():
    assert nz.cell_to_str(2134.0) == "2134"
    assert nz.cell_to_str(datetime(2026, 3, 5)) == "2026-03-05"
    assert nz.cell_to_str(date(2026, 3, 5)) == "2026-03-05"
    assert nz.cell_to_str(None) == ""
    assert nz.cell_to_str("  two   spaces ") == "two spaces"
