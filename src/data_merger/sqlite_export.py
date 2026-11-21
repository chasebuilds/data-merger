"""Write a merge result to a SQLite database with keys, so it can be queried with SQL.

Tables (see docs/queries.sql for examples):
  source_files   one row per input file
  sources        one row per source row, and the record it went to (the Crosswalk sheet)
  records        one row per merged record (the Merged sheet)
  lineage        for each record and field, the value and the source row it was taken from
  conflicts      values that lost to another; conflict_losers links each to its source rows
  review_pairs   pairs a person should check (the Review sheet), with a decision column
  run_summary    the Summary sheet as metric / value
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .pipeline import MergeResult

SCHEMA = """
CREATE TABLE source_files (
    file_name   TEXT PRIMARY KEY,
    rows_read   INTEGER NOT NULL,
    sha256      TEXT,
    read_as     TEXT
);

CREATE TABLE records (
    record_id    TEXT PRIMARY KEY,
    source_count INTEGER NOT NULL CHECK (source_count >= 1),
    match_score  REAL,
    match_basis  TEXT NOT NULL
    {value_columns}
);

CREATE TABLE sources (
    source_id   INTEGER PRIMARY KEY,
    source_file TEXT NOT NULL REFERENCES source_files (file_name),
    source_row  INTEGER NOT NULL,
    record_id   TEXT NOT NULL REFERENCES records (record_id),
    match_tier  TEXT NOT NULL,
    match_score REAL,
    match_basis TEXT NOT NULL,
    UNIQUE (source_file, source_row)
);
CREATE INDEX sources_record ON sources (record_id);

CREATE TABLE lineage (
    record_id     TEXT NOT NULL REFERENCES records (record_id),
    field         TEXT NOT NULL,
    value,
    source_id     INTEGER NOT NULL REFERENCES sources (source_id),
    agreeing_rows INTEGER NOT NULL,
    PRIMARY KEY (record_id, field)
);
CREATE INDEX lineage_source ON lineage (source_id);

CREATE TABLE conflicts (
    conflict_id    INTEGER PRIMARY KEY,
    record_id      TEXT NOT NULL REFERENCES records (record_id),
    field          TEXT NOT NULL,
    kept_value,
    kept_source_id INTEGER NOT NULL REFERENCES sources (source_id),
    lost_value,
    rule           TEXT NOT NULL
);
CREATE INDEX conflicts_record ON conflicts (record_id, field);

CREATE TABLE conflict_losers (
    conflict_id INTEGER NOT NULL REFERENCES conflicts (conflict_id),
    source_id   INTEGER NOT NULL REFERENCES sources (source_id),
    PRIMARY KEY (conflict_id, source_id)
);

CREATE TABLE review_pairs (
    pair_id     INTEGER PRIMARY KEY,
    source_a    INTEGER NOT NULL REFERENCES sources (source_id),
    source_b    INTEGER NOT NULL REFERENCES sources (source_id),
    record_a    TEXT NOT NULL REFERENCES records (record_id),
    record_b    TEXT NOT NULL REFERENCES records (record_id),
    match_score REAL NOT NULL,
    why         TEXT NOT NULL,
    decision    TEXT CHECK (decision IN ('same', 'different'))
);
CREATE INDEX review_record_a ON review_pairs (record_a);
CREATE INDEX review_record_b ON review_pairs (record_b);

CREATE TABLE run_summary (
    metric TEXT NOT NULL,
    value
);
"""

_FIXED = {"record_id", "source_count", "match_score", "match_basis"}


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def value_column_names(columns: list[str]) -> dict[str, str]:
    """Map each merged column to its SQL column name, renaming any that clash."""
    names: dict[str, str] = {}
    taken = set(_FIXED)
    for column in columns:
        name = column
        while name.lower() in {t.lower() for t in taken}:
            name += "_value"
        names[column] = name
        taken.add(name)
    return names


def _cell(value: object) -> object:
    """Blank text becomes NULL so SQL can test for missing values with IS NULL."""
    if value is None or value == "":
        return None
    if isinstance(value, int | float | str):
        return value
    return str(value)


def write_sqlite(result: MergeResult, path: str | Path) -> Path:
    path = Path(path)
    path.unlink(missing_ok=True)
    names = value_column_names(result.columns)
    value_sql = "".join(f",\n    {_quote(n)}" for n in names.values())
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            connection.executescript(SCHEMA.format(value_columns=value_sql))

            tables = result.load.tables if result.load else {}
            rows_per_file = result.load.rows_per_file if result.load else {}
            files = dict.fromkeys(r.source_file for r in result.records)
            connection.executemany(
                "INSERT INTO source_files VALUES (?, ?, ?, ?)",
                [(name, rows_per_file.get(name, 0),
                  tables[name].sha256 if name in tables else None,
                  tables[name].read_as if name in tables else None) for name in files],
            )

            placeholders = ", ".join("?" * (4 + len(names)))
            connection.executemany(
                f"INSERT INTO records VALUES ({placeholders})",
                [(m.merged_id, len(m.members), m.match_score, m.match_basis,
                  *[_cell(m.values.get(c)) for c in names]) for m in result.merged],
            )

            source_id = {(c.source_file, c.source_row): n
                         for n, c in enumerate(result.crosswalk, start=1)}
            id_of_ref = {f"{f}:{r}": n for (f, r), n in source_id.items()}
            connection.executemany(
                "INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(n, c.source_file, c.source_row, c.merged_id, c.tier, c.score, c.basis)
                 for n, c in enumerate(result.crosswalk, start=1)],
            )

            connection.executemany(
                "INSERT INTO lineage VALUES (?, ?, ?, ?, ?)",
                [(item.merged_id, item.column, _cell(item.value),
                  source_id[item.source_file, item.source_row], item.agreeing_rows)
                 for item in result.lineage],
            )

            losers = []
            for n, c in enumerate(result.conflicts, start=1):
                connection.execute(
                    "INSERT INTO conflicts VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (n, c.merged_id, c.column, _cell(c.kept_value), id_of_ref[c.kept_source],
                     _cell(c.lost_value), c.rule),
                )
                losers.extend((n, id_of_ref[ref]) for ref in c.lost_sources.split("; "))
            connection.executemany("INSERT INTO conflict_losers VALUES (?, ?)", losers)

            rows_of = {r.idx: r for r in result.records}
            review = []
            for n, pair in enumerate(result.review, start=1):
                a, b = rows_of[pair.a], rows_of[pair.b]
                review.append((n, source_id[a.source_file, a.source_row],
                               source_id[b.source_file, b.source_row],
                               result.merged_id_of[a.idx], result.merged_id_of[b.idx],
                               pair.score, pair.basis, None))
            connection.executemany("INSERT INTO review_pairs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                   review)

            connection.executemany("INSERT INTO run_summary VALUES (?, ?)",
                                   [(k, _cell(v)) for k, v in result.summary])
        problems = connection.execute("PRAGMA foreign_key_check").fetchall()
        if problems:
            raise ValueError(f"SQLite export broke {len(problems)} foreign key(s)")
    finally:
        connection.close()
    return path
