"""Reader hardening, guards against wrong merges, and the audit trail sheets."""

import hashlib

from openpyxl import Workbook, load_workbook

from data_merger import Config, merge_files, write_workbook
from data_merger.match import match_records
from data_merger.records import Record, _set_keys, is_placeholder, read_table, sniff_delimiter
from data_merger.workbook import safe_cell


def rec(idx, file="f.csv", **values) -> Record:
    record = Record(idx, file, idx + 2, dict(values))
    _set_keys(record)
    return record


def test_windows_1252_file_is_read_and_the_guess_is_stated(tmp_path):
    path = tmp_path / "legacy.csv"
    path.write_bytes("Name,Email\nRenée Dubé,renee@example.com\n".encode("cp1252"))
    table = read_table(path)
    assert table.rows[0][0] == "Renée Dubé"
    assert "Windows-1252 (a guess)" in table.read_as
    assert table.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


def test_utf8_with_bom_and_semicolons(tmp_path):
    path = tmp_path / "export.csv"
    path.write_bytes("﻿Name;Email;Notes\nAna Ruiz;ana@example.com;a, b\n".encode())
    table = read_table(path)
    assert table.headers == ["Name", "Email", "Notes"]
    assert table.rows[0] == ["Ana Ruiz", "ana@example.com", "a, b"]
    assert table.read_as == "text, UTF-8, semicolon-separated"


def test_delimiter_sniffing():
    assert sniff_delimiter("a|b|c") == "|"
    assert sniff_delimiter("a\tb") == "\t"
    assert sniff_delimiter('"Last, First";Email') == ";"
    assert sniff_delimiter("OnlyOneColumn") == ","


def test_garbled_text_is_counted(tmp_path):
    path = tmp_path / "bad.csv"
    garbled = "Renée".encode().decode("cp1252")
    path.write_text(f"Name,Email\n{garbled},r@example.com\nAna,a@example.com\n", encoding="utf-8")
    assert read_table(path).suspect_cells == 1


def test_extra_excel_sheets_are_named_not_silently_dropped(tmp_path, write_csv):
    path = tmp_path / "book.xlsx"
    workbook = Workbook()
    workbook.active.title = "Customers"
    workbook.active.append(["Name", "Email", "Zip"])
    workbook.active.append(["Ana Ruiz", "ana@example.com", 2134])
    workbook.create_sheet("Archive 2019").append(["Name"])
    workbook.save(path)
    other = write_csv("b.csv", ["Name", "Email"], [["Ana Ruiz", "ana@example.com"]])
    result = merge_files([path, other])
    summary = dict(result.summary)
    assert summary["Sheets NOT read: book.xlsx"] == "Archive 2019"
    assert "sheet 'Customers'" in summary["File read as: book.xlsx"]
    assert len(summary["File SHA-256: b.csv"]) == 64
    assert result.merged[0].values["postal_code"] == "02134"
    assert len(result.merged) == 1


def test_placeholder_values_are_not_evidence(write_csv):
    assert is_placeholder("email", "none@none.com")
    assert is_placeholder("email", "no-email@example.com")
    assert is_placeholder("phone", "0000000000")
    assert is_placeholder("phone", "6140000000")
    assert not is_placeholder("email", "nora@example.com")
    assert not is_placeholder("phone", "6145550101")

    a = write_csv("a.csv", ["Name", "Email", "Phone"], [
        ["Ana Ruiz", "none@none.com", "000-000-0000"],
        ["Ana Ruiz", "none@none.com", "000-000-0000"],
    ])
    b = write_csv("b.csv", ["Name", "Email"], [["Ben Cho", "none@none.com"]])
    result = merge_files([a, b])
    assert len(result.merged) == 3
    summary = dict(result.summary)
    assert summary["Placeholder emails and phones not used for matching"] == 5
    assert summary["Placeholder email: none@none.com"] == "3 rows"
    # The value is still delivered; it is only ignored as a reason to merge.
    assert result.merged[0].values["email"] == "none@none.com"


def test_identifier_profile_per_file(write_csv):
    a = write_csv("a.csv", ["Name", "Email", "Phone"], [
        ["Ana Ruiz", "front@example.com", "6145550101"],
        ["Ben Cho", "front@example.com", ""],
        ["Cy Dunn", "front@example.com", ""],
        ["Di Egan", "", ""],
    ])
    b = write_csv("b.csv", ["Name", "Email"], [["Flo Gray", "flo@example.com"]])
    summary = dict(merge_files([a, b]).summary)
    assert summary["Identifiers, filled in: a.csv"] == "email 75%, phone 25%, street 0%"
    assert summary["Identifiers, most repeated email: a.csv"] == "front@example.com (3 rows)"


def test_formula_guard_covers_every_trigger_but_keeps_negative_numbers():
    for risky in ("=1+1", "+1+1", "@SUM(A1)", "\t=1", "\r=1", "-2+3", "-cmd|x"):
        assert safe_cell(risky) == "'" + risky
    for fine in ("-12.50", "-5", "Ana", "a=b", "-", -4.0, None):
        assert safe_cell(fine) == fine


def test_groups_with_different_contact_details_are_not_joined_by_name_and_company():
    """The false merge found by the benchmark: two people, one name, one employer."""
    first = dict(first_name="Brenda", last_name="Abernathy")
    records = [
        rec(0, **first, phone="5345557918", company="Ironwood Bakery"),
        rec(1, **first, phone="5345557918", email="babernathy@example.net"),
        rec(2, **first, phone="6065555407", email="brenda.a@mail.example"),
        rec(3, **first, email="brenda.a@mail.example", company="Ironwood Bakery"),
    ]
    guarded = match_records(records, Config())
    assert guarded.clusters == [[0, 1], [2, 3]]
    assert guarded.held_back == {"the two groups hold different contact details": 1}
    assert "held back" in guarded.review[0].basis
    # The same rows with the guard off reproduce the wrong merge.
    assert match_records(records, Config(strong_key_guard=False)).clusters == [[0, 1, 2, 3]]


def test_name_and_address_survives_one_changed_contact_detail():
    base = dict(first_name="Ana", last_name="Ruiz", street="5 Elm Rd", postal_code="45402")
    records = [
        rec(0, **base, email="ana@example.com", phone="6145550101"),
        rec(1, **base, email="ana.new@example.org", phone="6145550101"),
        rec(2, **base, email="ana.old@example.net"),
    ]
    assert match_records(records, Config()).clusters == [[0, 1, 2]]


def test_cluster_size_cap_sends_the_overflow_to_review():
    records = [rec(i, first_name="Ana", last_name="Ruiz", email="ana@example.com")
               for i in range(5)]
    result = match_records(records, Config(max_cluster_size=3))
    assert sorted(len(c) for c in result.clusters) == [2, 3]
    assert any("more than 3 rows" in pair.basis for pair in result.review)


def test_one_per_source_option():
    records = [
        rec(0, "a.csv", first_name="Ana", last_name="Ruiz", email="ana@example.com"),
        rec(1, "a.csv", first_name="Ana", last_name="Ruiz", email="ana@example.com"),
        rec(2, "b.csv", first_name="Ana", last_name="Ruiz", email="ana@example.com"),
    ]
    assert match_records(records, Config()).clusters == [[0, 1, 2]]
    strict = match_records(records, Config(one_per_source=True))
    assert sorted(len(c) for c in strict.clusters) == [1, 2]
    assert "two rows from one file" in strict.review[0].basis


def test_crosswalk_accounts_for_every_source_row(tmp_path, three_sources):
    result = merge_files(three_sources)
    assert len(result.crosswalk) == len(result.records) == 5
    tiers = {(c.source_file, c.source_row): c.tier for c in result.crosswalk}
    assert tiers[("crm.csv", 2)] == "exact key"
    assert tiers[("crm.csv", 3)] == "unmatched"
    summary = dict(result.summary)
    assert summary["Check: rows read = Crosswalk rows"] == "5 = 5: balanced"
    assert summary["Check: rows read = merged records + rows absorbed"] == "5 = 3 + 2: balanced"
    assert summary["Merged records made of 3 rows"] == 1
    assert summary["Merged records made of 1 row"] == 2
    assert summary["Merge links by reason: same email, names agree"] == 2
    assert "US and Canada" in summary["Phone numbers read as"]

    book = load_workbook(write_workbook(result, tmp_path / "out.xlsx"))
    assert book["Crosswalk"].max_row == 1 + 5
    read_me = [row[1] for row in book["Read me"].iter_rows(values_only=True) if row[1]]
    assert any("3 files with 5 rows" in line for line in read_me)
    assert any("not certainties" in line for line in read_me)
