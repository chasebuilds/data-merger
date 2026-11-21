"""SQLite export: row counts tie to the workbook, keys hold, values trace back."""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from openpyxl import load_workbook

from data_merger import merge_files, write_sqlite
from data_merger.cli import main
from data_merger.sqlite_export import value_column_names

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
SAMPLE_FILES = [SAMPLES / n for n in ("crm_export.csv", "billing_export.xlsx",
                                      "mailing_list.csv")]


@pytest.fixture(scope="module")
def sample_outputs(tmp_path_factory):
    out = tmp_path_factory.mktemp("sqlite")
    xlsx, db = out / "merged.xlsx", out / "merged.db"
    code = main(["merge", *map(str, SAMPLE_FILES), "-o", str(xlsx), "--sqlite", str(db)])
    assert code == 0
    return xlsx, db


def _sheet_rows(path, name):
    book = load_workbook(path, read_only=True)
    try:
        return list(book[name].iter_rows(values_only=True))[1:]
    finally:
        book.close()


def _count(db, table):
    with closing(sqlite3.connect(db)) as connection:
        return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


@pytest.mark.parametrize("sheet, table", [
    ("Merged", "records"), ("Crosswalk", "sources"), ("Lineage", "lineage"),
    ("Conflicts", "conflicts"), ("Review", "review_pairs"), ("Summary", "run_summary"),
])
def test_row_counts_tie_to_the_workbook(sample_outputs, sheet, table):
    xlsx, db = sample_outputs
    assert _count(db, table) == len(_sheet_rows(xlsx, sheet)) > 0


def test_sample_counts_match_the_readme(sample_outputs):
    _, db = sample_outputs
    with closing(sqlite3.connect(db)) as connection:
        one = connection.execute
        assert one("SELECT COUNT(*) FROM sources").fetchone()[0] == 61
        assert one("SELECT COUNT(*) FROM records").fetchone()[0] == 33
        assert one("SELECT COUNT(*) FROM records WHERE source_count >= 2").fetchone()[0] == 19
        assert one("SELECT COUNT(*) FROM records WHERE source_count = 1").fetchone()[0] == 14
        assert one("SELECT SUM(rows_read) FROM source_files").fetchone()[0] == 61


def test_foreign_keys_hold_and_are_enforced(sample_outputs):
    _, db = sample_outputs
    connection = sqlite3.connect(db)
    try:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        connection.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO sources VALUES (9999, 'crm_export.csv', 999, "
                               "'NO_SUCH_RECORD', 'fuzzy', 0.9, 'x')")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO sources VALUES (9999, 'crm_export.csv', 3, "
                               "'M0001', 'fuzzy', 0.9, 'duplicate file and row')")
    finally:
        connection.close()


def test_source_count_equals_rows_pointing_at_each_record(sample_outputs):
    _, db = sample_outputs
    with closing(sqlite3.connect(db)) as connection:
        mismatched = connection.execute("""
            SELECT r.record_id FROM records r
            LEFT JOIN sources s ON s.record_id = r.record_id
            GROUP BY r.record_id HAVING COUNT(s.source_id) != r.source_count
        """).fetchall()
    assert mismatched == []


def test_lineage_values_equal_the_record_values(sample_outputs):
    _, db = sample_outputs
    connection = sqlite3.connect(db)
    try:
        fields = [row[0] for row in connection.execute("SELECT DISTINCT field FROM lineage")]
        assert "email" in fields
        for field in fields:
            bad = connection.execute(f"""
                SELECT l.record_id FROM lineage l JOIN records r USING (record_id)
                WHERE l.field = ? AND r."{field}" IS NOT l.value
            """, (field,)).fetchall()
            assert bad == [], field
    finally:
        connection.close()


def test_conflict_losers_cover_every_lost_source(sample_outputs):
    xlsx, db = sample_outputs
    lost_refs = sum(len(str(row[5]).split("; ")) for row in _sheet_rows(xlsx, "Conflicts"))
    assert _count(db, "conflict_losers") == lost_refs


def test_readme_example_conflict_is_queryable(sample_outputs):
    _, db = sample_outputs
    with closing(sqlite3.connect(db)) as connection:
        row = connection.execute("""
            SELECT c.kept_value, c.lost_value, s.source_file || ':' || s.source_row, c.rule
            FROM conflicts c
            JOIN conflict_losers cl USING (conflict_id)
            JOIN sources s ON s.source_id = cl.source_id
            WHERE c.record_id = 'M0002' AND c.field = 'phone'
        """).fetchone()
    assert row == ("(957) 555-4056", "(262) 555-3016", "billing_export.xlsx:7", "most_recent")


def test_blank_values_are_null(sample_outputs):
    _, db = sample_outputs
    with closing(sqlite3.connect(db)) as connection:
        empty = connection.execute("SELECT COUNT(*) FROM records WHERE email = ''").fetchone()[0]
    assert empty == 0


def test_review_pairs_point_at_both_records(tmp_path, write_csv):
    a = write_csv("a.csv", ["Name", "Zip", "Email"], [["Ana Ruiz", "45402", "ana@example.com"]])
    b = write_csv("b.csv", ["Name", "Zip", "Email"], [["Ana Ruiz", "45402", "ar@example.org"]])
    db = write_sqlite(merge_files([a, b]), tmp_path / "out.db")
    with closing(sqlite3.connect(db)) as connection:
        rows = connection.execute("""
            SELECT sa.source_file, sb.source_file, p.record_a != p.record_b, p.decision
            FROM review_pairs p
            JOIN sources sa ON sa.source_id = p.source_a
            JOIN sources sb ON sb.source_id = p.source_b
        """).fetchall()
    assert rows == [("a.csv", "b.csv", 1, None)]


def test_no_lineage_leaves_the_table_empty(tmp_path):
    db = tmp_path / "out.db"
    main(["merge", *map(str, SAMPLE_FILES), "-o", str(tmp_path / "m.xlsx"),
          "--sqlite", str(db), "--no-lineage"])
    assert _count(db, "lineage") == 0
    assert _count(db, "records") == 33


def test_rerun_replaces_the_database(tmp_path, three_sources):
    db = tmp_path / "out.db"
    write_sqlite(merge_files(three_sources), db)
    write_sqlite(merge_files(three_sources), db)
    assert _count(db, "sources") == 5


def test_value_columns_that_clash_with_fixed_columns_are_renamed():
    names = value_column_names(["email", "match_score", "Record_ID", "match_score_value"])
    assert names == {"email": "email", "match_score": "match_score_value",
                     "Record_ID": "Record_ID_value", "match_score_value": "match_score_value_value"}
