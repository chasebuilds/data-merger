"""Every example query in docs/queries.sql runs against the sample output."""

import re
import sqlite3
from pathlib import Path

import pytest

from data_merger import merge_files, write_sqlite

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_FILES = [ROOT / "samples" / n for n in ("crm_export.csv", "billing_export.xlsx",
                                                "mailing_list.csv")]


def load_queries() -> dict[str, str]:
    text = (ROOT / "docs" / "queries.sql").read_text(encoding="utf-8")
    parts = re.split(r"^-- name: (\S+)\s*$", text, flags=re.MULTILINE)
    return {name: sql.strip() for name, sql in zip(parts[1::2], parts[2::2], strict=True)}


QUERIES = load_queries()


@pytest.fixture(scope="module")
def sample_db(tmp_path_factory):
    path = tmp_path_factory.mktemp("queries") / "merged.db"
    write_sqlite(merge_files(SAMPLE_FILES), path)
    connection = sqlite3.connect(path)
    yield connection
    connection.close()


def test_there_are_5_to_8_queries():
    assert 5 <= len(QUERIES) <= 8


@pytest.mark.parametrize("name", sorted(QUERIES))
def test_query_runs(sample_db, name):
    sql = QUERIES[name]
    assert sqlite3.complete_statement(sql), name
    sample_db.execute(sql).fetchall()


def test_query_results_on_the_sample(sample_db):
    def run(name):
        return sample_db.execute(QUERIES[name]).fetchall()

    big = run("records_built_from_3_or_more_rows")
    assert big and all(row[2] >= 3 for row in big)
    assert "M0002" in {row[0] for row in big}

    by_file = {row[0]: row[2] for row in run("unmatched_rows_by_source_file")}
    assert sum(by_file.values()) == 14

    conflicts = run("fields_with_conflicts")
    assert sum(row[2] for row in conflicts) == 20

    detail = run("conflict_detail_with_rows")
    assert ("M0002", "phone", "(957) 555-4056", "crm_export.csv:3", "(262) 555-3016",
            "billing_export.xlsx:7", "most_recent") in detail

    assert len(run("review_queue")) == 1
