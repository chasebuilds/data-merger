"""Review decisions on rerun, the audit sample, and the key-join command."""

import pytest
from openpyxl import load_workbook

from data_merger import join_files, merge_files, write_join_workbook, write_workbook
from data_merger.audit import audit_report, read_audit, wilson
from data_merger.cli import main


@pytest.fixture
def unsure_pair(write_csv):
    """Same name and ZIP, different email: lands in Review."""
    a = write_csv("a.csv", ["Name", "Zip", "Email"], [
        ["Ana Ruiz", "45402", "ana@example.com"], ["Cy Dunn", "10001", "cy@example.com"]])
    b = write_csv("b.csv", ["Name", "Zip", "Email"], [
        ["Ana Ruiz", "45402", "ar@example.org"], ["Cy Dunn", "10001", "cyd@example.org"]])
    return [a, b]


def _answer(path, sheet_name, header, answers):
    book = load_workbook(path)
    sheet = book[sheet_name]
    column = [c.value for c in sheet[1]].index(header) + 1
    for row, answer in enumerate(answers, start=2):
        sheet.cell(row=row, column=column, value=answer)
    book.save(path)


def test_review_decisions_are_applied_on_rerun(tmp_path, unsure_pair):
    first = merge_files(unsure_pair)
    assert (len(first.merged), len(first.review)) == (4, 2)
    out = write_workbook(first, tmp_path / "round1.xlsx")
    _answer(out, "Review", "decision (same / different)", ["Same", "different"])

    second = merge_files(unsure_pair, decisions_from=out)
    assert len(second.merged) == 3
    assert second.review == []
    human = next(m for m in second.merged if len(m.members) == 2)
    assert (human.match_score, human.match_basis) == (1.0, "human decision: same")
    assert {c.tier for c in second.crosswalk} == {"human", "unmatched"}
    summary = dict(second.summary)
    assert summary["Review decisions read: same"] == 1
    assert summary["Review decisions read: different"] == 1
    assert summary["Merge links by reason: human decision: same"] == 1


def test_unclear_and_stale_decisions_are_counted_not_applied(tmp_path, unsure_pair, write_csv):
    out = write_workbook(merge_files(unsure_pair), tmp_path / "round1.xlsx")
    _answer(out, "Review", "decision (same / different)", ["maybe?", "same"])
    # The second file lost a row since the review, so one answer points at nothing.
    shorter = write_csv("b.csv", ["Name", "Zip", "Email"],
                        [["Ana Ruiz", "45402", "ar@example.org"]])
    result = merge_files([unsure_pair[0], shorter], decisions_from=out)
    summary = dict(result.summary)
    assert summary["Review decisions read: not understood"] == 1
    assert summary["Review decisions read: row not found"] == 1
    assert summary["Review decisions read: same"] == 0
    assert len(result.merged) == 3


def test_decisions_need_a_review_sheet(tmp_path, unsure_pair, capsys):
    joined = write_join_workbook(join_files(*unsure_pair, on="Email"), tmp_path / "j.xlsx")
    code = main(["merge", *map(str, unsure_pair), "--decisions", str(joined),
                 "-o", str(tmp_path / "o.xlsx")])
    assert code == 2
    assert "no Review sheet" in capsys.readouterr().err


def test_wilson_interval():
    low, high = wilson(10, 10)
    assert high == 1.0
    assert 0.70 < low < 0.73
    low, high = wilson(45, 50)
    assert 0.78 < low < 0.79 and 0.95 < high < 0.96


def test_audit_sample_is_seeded_stratified_and_scored(tmp_path, three_sources, unsure_pair,
                                                      capsys):
    result = merge_files(three_sources, audit_sample=5, audit_seed=3)
    again = merge_files(three_sources, audit_sample=5, audit_seed=3)
    assert [(a.stratum, a.pair.a, a.pair.b) for a in result.audit] == [
        (a.stratum, a.pair.a, a.pair.b) for a in again.audit]
    # Two merge links, plus the household member who shares a phone: a near miss.
    assert [(a.stratum, a.stratum_size) for a in result.audit] == [
        ("merged: same email, names agree", 2), ("merged: same email, names agree", 2),
        ("not merged: near miss, just under the review band", 1)]

    out = write_workbook(result, tmp_path / "out.xlsx")
    assert main(["audit", str(out)]) == 0
    assert "not labeled yet" in capsys.readouterr().out

    _answer(out, "Audit", "label (same / different)", ["same", "different"])
    strata = read_audit(out)
    assert (strata[0].labeled, strata[0].same, strata[0].size) == (2, 1, 2)
    assert (strata[1].sampled, strata[1].labeled) == (1, 0)
    report = audit_report(strata)
    assert "correct merges: 1 of 2 (50.0%" in report
    assert "Estimated share of all 2 merge links that are correct: 50.0%" in report

    plain = write_workbook(merge_files(unsure_pair), tmp_path / "plain.xlsx")
    assert "Audit" not in load_workbook(plain).sheetnames
    assert main(["audit", str(plain)]) == 2


@pytest.fixture
def id_lists(write_csv):
    left = write_csv("orders.csv", ["Customer ID", "Order", "Amount"], [
        ["00123", "A-1", "10"], ["00123", "A-2", "15"], ["777", "A-3", "20"],
        ["", "A-4", "5"], ["abc-9", "A-5", "7"], ["555", "A-6", "1"],
    ])
    right = write_csv("customers.csv", ["customer_id", "Name", "Amount"], [
        ["00123", "Ana Ruiz", "x"], ["123", "Other Person", "y"], ["0777", "Ben Cho", "z"],
        ["", "No Key", ""], ["ABC 9", "Cy Dunn", ""], ["900", "Di Egan", ""],
    ])
    return left, right


def test_join_reports_every_way_a_lookup_goes_wrong(tmp_path, id_lists):
    result = join_files(*id_lists, on="customer id", expect="many-to-one")
    assert result.violations == 0
    assert len(result.joined) == 2
    assert result.headers == ["left_row", "right_row", "rows_for_this_key", "Customer ID",
                              "Order", "Amount", "Name", "Amount (customers)"]
    assert result.joined[0] == [2, 2, 2, "00123", "A-1", "10", "Ana Ruiz", "x"]
    # "00123" must not match "123": a key is text, and those are two customers.
    assert all(row[6] != "Other Person" for row in result.joined)
    assert [row[1] for row in result.left_only] == ["777", "abc-9", "555"]
    assert [row[1] for row in result.right_only] == ["123", "0777", "ABC 9", "900"]
    assert result.blank_keys == [("orders.csv", 5), ("customers.csv", 5)]
    assert ("777", 4, "0777", 4, "leading zeros") in result.near_keys
    assert ("abc-9", 6, "ABC 9", 6, "letter case, spaces or punctuation") in result.near_keys
    assert ("00123", "allowed", 2, 1, 2) in result.duplicates
    summary = dict(result.summary)
    assert summary["Check: left rows = matched + left only"] == "balanced"
    assert summary["Check: right rows = matched + right only"] == "balanced"
    assert summary["Contract result"] == "held"

    book = load_workbook(write_join_workbook(result, tmp_path / "joined.xlsx"))
    assert book.sheetnames == ["Joined", "Left only", "Right only", "Duplicate keys",
                               "Blank keys", "Near keys", "Summary"]
    assert book["Joined"].max_row == 3


def test_join_contract_violation_is_an_error(tmp_path, id_lists, capsys):
    out = tmp_path / "joined.xlsx"
    code = main(["join", *map(str, id_lists), "--on", "Customer ID", "-o", str(out)])
    assert code == 1
    assert "break the one-to-one contract" in capsys.readouterr().err
    assert dict(load_workbook(out)["Summary"].iter_rows(values_only=True))[
        "Contract result"].startswith("BROKEN by 1 key")


def test_join_rejects_a_missing_key_column(id_lists, capsys):
    with pytest.raises(ValueError, match="not found in customers.csv"):
        join_files(*id_lists, on="Order")
    assert main(["join", *map(str, id_lists), "--on", "nope"]) == 2
    assert "Key column 'nope' not found" in capsys.readouterr().err
