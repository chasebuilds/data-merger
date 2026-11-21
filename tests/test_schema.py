import pytest

from data_merger.schema import map_headers


def _targets(headers, overrides=None):
    return {m.header: m for m in map_headers("f.csv", headers, overrides)}


@pytest.mark.parametrize("header", [
    "E-mail", "email_address", "Contact Email", "EMAIL", "Email Addr", "e_mail",
])
def test_email_synonyms(header):
    assert _targets([header])[header].target == "email"


@pytest.mark.parametrize(("header", "target"), [
    ("First Name", "first_name"), ("lname", "last_name"), ("Customer Name", "full_name"),
    ("Tel", "phone"), ("mobile", "phone"), ("Organization", "company"), ("ZIP", "postal_code"),
    ("ST", "state"), ("Balance Due", "balance"), ("Last Modified", "updated_at"),
    ("Shipping Address", "full_address"), ("Billing Address", "street"),
])
def test_common_headers(header, target):
    mapping = _targets([header])[header]
    assert (mapping.target, mapping.method) == (target, "synonym")


@pytest.mark.parametrize(("header", "target"), [
    ("Emial Address", "email"), ("Phone Numbr", "phone"), ("Compny Name", "company"),
    ("Postal-Codes", "postal_code"),
])
def test_fuzzy_headers_are_mapped_and_labelled(header, target):
    mapping = _targets([header])[header]
    assert (mapping.target, mapping.method) == (target, "fuzzy")
    assert 86 <= mapping.score < 100


def test_unknown_header_is_carried_as_extra():
    mapping = _targets(["Loyalty Tier"])["Loyalty Tier"]
    assert mapping.target == "extra:Loyalty Tier"
    assert mapping.method == "unmapped"
    assert "carried through" in mapping.note


def test_two_headers_for_one_column_keeps_the_best():
    got = _targets(["Email", "Emial Address"])
    assert got["Email"].target == "email"
    assert got["Emial Address"].target == "extra:Emial Address"
    assert "'Email' won" in got["Emial Address"].note


def test_config_override_wins_and_can_ignore():
    got = _targets(["Ref", "Email", "Notes"], {"Ref": "company", "notes": "ignore"})
    assert (got["Ref"].target, got["Ref"].method) == ("company", "config")
    assert got["Notes"].target == "ignore"


def test_config_override_to_unknown_column_fails_loudly():
    with pytest.raises(ValueError, match="unknown column"):
        map_headers("f.csv", ["Ref"], {"Ref": "customer_ref"})
