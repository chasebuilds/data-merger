from pathlib import Path

import pytest
from openpyxl import load_workbook

from data_merger import Config, load_config, merge_files, write_workbook
from data_merger.cli import main


def _row(result, last_name):
    return next(m for m in result.merged if m.values.get("last_name") == last_name
                and len(m.members) > 1)


def test_one_customer_from_three_files_becomes_one_row(three_sources):
    result = merge_files(three_sources)
    hale = _row(result, "Hale")
    assert hale.source_files == "crm.csv; billing.csv; mailing.csv"
    assert hale.source_rows == "crm.csv:2; billing.csv:2; mailing.csv:2"
    assert hale.match_score >= 0.88
    # Dana Hale shares the phone and address but is a different person.
    assert len(result.merged) == 3
    assert sorted(len(m.members) for m in result.merged) == [1, 1, 3]


def test_values_are_harmonized_before_output(three_sources):
    result = merge_files(three_sources)
    hale = _row(result, "Hale")
    assert hale.values["email"] == "rhale@example.com"
    assert hale.values["balance"] == 1250.0
    assert hale.values["updated_at"] == "2026-06-15"
    quinn = next(m for m in result.merged if m.values["last_name"] == "Quinn")
    assert quinn.values["balance"] == -40.0
    assert quinn.values["phone"] == "(303) 555-0144"


def test_most_recent_wins_and_the_loser_is_kept(three_sources):
    result = merge_files(three_sources)
    hale = _row(result, "Hale")
    assert hale.values["phone"] == "(614) 555-0199"
    phone = [c for c in result.conflicts if c.merged_id == hale.merged_id and c.column == "phone"]
    assert len(phone) == 1
    assert phone[0].kept_source == "billing.csv:2"
    assert phone[0].lost_value == "(614) 555-0101"
    assert phone[0].lost_sources == "crm.csv:2"
    assert phone[0].rule == "most_recent"


def test_source_priority_rule_and_order(three_sources):
    config = Config(column_rules={"phone": "source_priority"})
    assert _row(merge_files(three_sources, config), "Hale").values["phone"] == "(614) 555-0101"
    config.source_priority = ["billing.csv"]
    assert _row(merge_files(three_sources, config), "Hale").values["phone"] == "(614) 555-0199"


def test_most_complete_and_most_common_rules(three_sources):
    by_votes = _row(merge_files(three_sources), "Hale")
    assert by_votes.values["first_name"] == "Robert"
    config = Config(column_rules={"first_name": "source_priority"}, source_priority=["mailing.csv"])
    assert _row(merge_files(three_sources, config), "Hale").values["first_name"] == "Rob"
    config = Config(column_rules={"first_name": "most_complete"})
    assert _row(merge_files(three_sources, config), "Hale").values["first_name"] == "Robert"


def test_address_parts_come_from_one_source(write_csv):
    old = write_csv("old.csv", ["Name", "Email", "Street", "City", "Zip", "Updated"],
                    [["Ana Ruiz", "ana@example.com", "5 Elm Rd", "Dayton", "45402", "2024-01-01"]])
    new = write_csv("new.csv", ["Name", "Email", "Street", "Updated"],
                    [["Ana Ruiz", "ana@example.com", "77 Lake Ave", "2026-01-01"]])
    values = merge_files([old, new]).merged[0].values
    assert values["street"] == "77 Lake Ave"
    # The new address has no city on file; the old city must not be glued onto it.
    assert values["city"] == ""
    assert values["postal_code"] == ""


def test_same_fact_written_two_ways_is_not_a_conflict(write_csv):
    a = write_csv("a.csv", ["Name", "Email", "Street", "Company"],
                  [["Ana Ruiz", "ana@example.com", "5 Elm Road", "Acme Supply Inc"]])
    b = write_csv("b.csv", ["Name", "Email", "Street", "Company"],
                  [["Ana Ruiz", "ANA@example.com", "5 ELM RD", "ACME SUPPLY"]])
    result = merge_files([a, b])
    assert len(result.merged) == 1
    assert result.conflicts == []


def test_lineage_names_the_exact_source_of_every_value(three_sources):
    result = merge_files(three_sources)
    hale = _row(result, "Hale")
    lineage = {i.column: i for i in result.lineage if i.merged_id == hale.merged_id}
    assert (lineage["balance"].source_file, lineage["balance"].source_row) == ("billing.csv", 2)
    assert lineage["email"].agreeing_rows == 3
    assert set(lineage) == {c for c in result.columns if hale.values[c] != ""}


def test_extra_columns_blank_rows_and_bad_values_are_reported(write_csv):
    a = write_csv("a.csv", ["Name", "Email", "Loyalty Tier", "Updated"], [
        ["Ana Ruiz", "ana@example.com", "Gold", "last spring"],
        ["", "", "", ""],
        ["Ben Cho", "ben(at)example.com", "", "2026-01-01"],
    ])
    b = write_csv("b.csv", ["Name", "Email"], [["Ana Ruiz", "ana@example.com"]])
    result = merge_files([a, b])
    assert "Loyalty Tier" in result.columns
    assert result.merged[0].values["Loyalty Tier"] == "Gold"
    summary = dict(result.summary)
    assert summary["Blank rows skipped"] == 1
    assert summary["Values that could not be parsed (kept as typed)"] == 2
    assert result.records[1].source_row == 4


def test_config_file_overrides_mapping_rules_and_thresholds(tmp_path, write_csv):
    a = write_csv("a.csv", ["Ref", "Email", "Phone"], [["Acme", "ana@example.com", "6145550101"]])
    b = write_csv("b.csv", ["Ref", "Email", "Phone"], [["Acme", "ana@example.com", "6145550102"]])
    config_path = tmp_path / "cfg.toml"
    config_path.write_text(
        '[thresholds]\nauto = 0.9\nreview = 0.6\n'
        '[rules]\ndefault = "source_priority"\nphone = "most_complete"\n'
        '[source_priority]\norder = ["b.csv", "a.csv"]\n'
        '[mapping."a.csv"]\nRef = "company"\n[mapping."b.csv"]\nRef = "ignore"\n',
        encoding="utf-8",
    )
    config = load_config(config_path)
    assert (config.auto_threshold, config.review_threshold) == (0.9, 0.6)
    result = merge_files([a, b], config)
    assert {(m.source_file, m.target, m.method) for m in result.mappings if m.header == "Ref"} == {
        ("a.csv", "company", "config"), ("b.csv", "ignore", "config")}
    assert result.merged[0].values["company"] == "Acme"
    assert result.merged[0].values["phone"] == "(614) 555-0102"


def test_example_config_in_the_repo_is_valid():
    config = load_config(Path(__file__).resolve().parent.parent / "merge_config.example.toml")
    assert config.rule_for("balance") == "source_priority"
    assert config.rule_for("email") == "most_recent"
    assert config.mapping["mailing_list.csv"] == {"subscribed_on": "ignore"}


def test_bad_config_is_rejected(tmp_path):
    path = tmp_path / "cfg.toml"
    path.write_text('[rules]\nemail = "newest"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="Unknown rule"):
        load_config(path)
    with pytest.raises(ValueError, match="Thresholds"):
        Config(auto_threshold=0.5, review_threshold=0.7).validate()


def test_duplicate_file_names_are_rejected(tmp_path, write_csv):
    a = write_csv("a.csv", ["Email"], [["x@example.com"]])
    other = tmp_path / "sub"
    other.mkdir()
    b = other / "a.csv"
    b.write_text("Email\ny@example.com\n", encoding="utf-8")
    with pytest.raises(ValueError, match="different file names"):
        merge_files([a, b])


def test_workbook_has_every_sheet_and_reads_xlsx_sources(tmp_path, three_sources):
    result = merge_files(three_sources)
    out = write_workbook(result, tmp_path / "out.xlsx")
    workbook = load_workbook(out)
    assert workbook.sheetnames == ["Read me", "Merged", "Review", "Conflicts", "Unmatched",
                                   "Crosswalk", "Mapping", "Lineage", "Summary"]
    merged = list(workbook["Merged"].iter_rows(values_only=True))
    assert merged[0][0] == "merged_id"
    assert {"source_files", "source_rows", "match_score"} <= set(merged[0])
    assert len(merged) == 1 + len(result.merged)
    assert workbook["Unmatched"].max_row == 1 + 2
    assert workbook["Mapping"].max_row == 1 + 15


def test_formula_like_values_are_written_as_text(tmp_path, write_csv):
    a = write_csv("a.csv", ["Name", "Email", "Notes"], [["Ana Ruiz", "a@example.com", "=1+1"]])
    b = write_csv("b.csv", ["Name", "Email"], [["Ana Ruiz", "a@example.com"]])
    out = write_workbook(merge_files([a, b]), tmp_path / "out.xlsx")
    row = list(load_workbook(out)["Merged"].iter_rows(values_only=True))[1]
    assert "'=1+1" in row


def test_review_sheet_shows_both_sides(tmp_path, write_csv):
    a = write_csv("a.csv", ["Name", "Zip", "Email"], [["Ana Ruiz", "45402", "ana@example.com"]])
    b = write_csv("b.csv", ["Name", "Zip", "Email"], [["Ana Ruiz", "45402", "ar@example.org"]])
    result = merge_files([a, b])
    assert len(result.merged) == 2
    assert len(result.review) == 1
    assert [reason for _, reason in result.unmatched] == ["possible match waiting in Review"] * 2
    out = write_workbook(result, tmp_path / "out.xlsx")
    header, row = list(load_workbook(out)["Review"].iter_rows(values_only=True))
    side = dict(zip(header, row, strict=True))
    assert side["email [A]"] == "ana@example.com"
    assert side["email [B]"] == "ar@example.org"
    assert (side["source [A]"], side["source [B]"]) == ("a.csv:2", "b.csv:2")
    assert 0.70 <= side["match_score"] < 0.88


def test_cli_end_to_end(tmp_path, three_sources, capsys):
    out = tmp_path / "merged.xlsx"
    code = main(["merge", *map(str, three_sources), "-o", str(out), "--no-lineage"])
    assert code == 0
    assert "Merged records: 3" in capsys.readouterr().out
    workbook = load_workbook(out)
    assert "Lineage" not in workbook.sheetnames
    assert dict(workbook["Summary"].iter_rows(values_only=True))["Lineage sheet"] == "turned off"


def test_cli_reports_missing_file_and_bad_thresholds(tmp_path, three_sources, capsys):
    assert main(["merge", str(tmp_path / "nope.csv"), str(three_sources[0])]) == 2
    assert "file not found" in capsys.readouterr().err
    assert main(["merge", *map(str, three_sources), "--auto", "0.5", "--review", "0.9",
                 "-o", str(tmp_path / "x.xlsx")]) == 2
    assert "Thresholds" in capsys.readouterr().err
