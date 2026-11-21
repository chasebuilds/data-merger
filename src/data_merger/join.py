"""Key join: match list A to list B on an ID column, with the checks a VLOOKUP skips.

A hand-rolled lookup goes wrong quietly in four ways: keys that differ only by leading
zeros or spacing, blank keys matching each other, duplicate keys multiplying rows, and
unmatched rows vanishing. Each one gets its own sheet here.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from openpyxl import Workbook

from . import __version__
from .normalize import squash
from .records import read_table
from .workbook import _sheet, safe_cell

CONTRACTS = ("one-to-one", "many-to-one", "one-to-many", "many-to-many")


@dataclass
class JoinResult:
    headers: list[str]
    joined: list[list[object]]
    left_only: list[list[object]]
    right_only: list[list[object]]
    duplicates: list[tuple[str, str, int, int, int]]  # key, side(s), left n, right n, rows made
    blank_keys: list[tuple[str, int]]
    near_keys: list[tuple[str, int, str, int, str]]
    summary: list[tuple[str, object]] = field(default_factory=list)
    violations: int = 0
    left_headers: list[str] = field(default_factory=list)
    right_headers: list[str] = field(default_factory=list)


def _key_column(headers: list[str], name: str, file_name: str) -> int:
    wanted = squash(name)
    hits = [i for i, h in enumerate(headers) if squash(h) == wanted]
    if len(hits) != 1:
        problem = "not found" if not hits else "found more than once"
        raise ValueError(f"Key column '{name}' {problem} in {file_name}. "
                         f"Headers: {', '.join(headers)}")
    return hits[0]


def _loose(key: str) -> str:
    """What a key would be if case, spaces and leading zeros did not matter."""
    return squash(key).replace(" ", "").lstrip("0")


def join_files(left_path: str | Path, right_path: str | Path, on: str,
               right_on: str | None = None, expect: str = "one-to-one") -> JoinResult:
    if expect not in CONTRACTS:
        raise ValueError(f"--expect must be one of: {', '.join(CONTRACTS)}")
    left_path, right_path = Path(left_path), Path(right_path)
    left, right = read_table(left_path), read_table(right_path)
    lk = _key_column(left.headers, on, left_path.name)
    rk = _key_column(right.headers, right_on or on, right_path.name)
    width_l, width_r = len(left.headers), len(right.headers)

    def index(rows, key_col, width, file_name):
        by_key: dict[str, list[tuple[int, list[str]]]] = defaultdict(list)
        blanks = []
        for offset, row in enumerate(rows):
            if not any(row):
                continue
            row = (row + [""] * width)[:width]
            # Keys are compared as text, exactly as typed apart from outer spaces.
            key = row[key_col].strip()
            if key:
                by_key[key].append((offset + 2, row))
            else:
                # Two blank keys are two unknowns, not a match.
                blanks.append((file_name, offset + 2))
        return by_key, blanks

    left_by, left_blank = index(left.rows, lk, width_l, left_path.name)
    right_by, right_blank = index(right.rows, rk, width_r, right_path.name)

    taken = {squash(h) for h in left.headers}
    right_names = [f"{h} ({right_path.stem})" if squash(h) in taken else h
                   for i, h in enumerate(right.headers) if i != rk]
    headers = ["left_row", "right_row", "rows_for_this_key", *left.headers, *right_names]

    left_many, right_many = expect.split("-to-")
    joined, duplicates, violations = [], [], 0
    for key, lrows in left_by.items():
        rrows = right_by.get(key)
        if not rrows:
            continue
        made = len(lrows) * len(rrows)
        broke = (len(lrows) > 1 and left_many == "one") or (len(rrows) > 1 and right_many == "one")
        if len(lrows) > 1 or len(rrows) > 1:
            duplicates.append((key, "breaks the contract" if broke else "allowed",
                               len(lrows), len(rrows), made))
        violations += broke
        for lrow_number, lrow in lrows:
            for rrow_number, rrow in rrows:
                joined.append([lrow_number, rrow_number, made, *lrow,
                               *[c for i, c in enumerate(rrow) if i != rk]])
    for by_key, other, many, side in ((left_by, right_by, left_many, "left"),
                                      (right_by, left_by, right_many, "right")):
        for key, rows in by_key.items():
            if len(rows) > 1 and key not in other:
                broke = many == "one"
                duplicates.append((key, f"{side} file only, "
                                   + ("breaks the contract" if broke else "allowed"),
                                   len(rows) if side == "left" else 0,
                                   len(rows) if side == "right" else 0, 0))
                violations += broke

    left_only = [[n, *row] for key, rows in left_by.items() if key not in right_by
                 for n, row in rows]
    right_only = [[n, *row] for key, rows in right_by.items() if key not in left_by
                  for n, row in rows]

    loose_right: dict[str, list[str]] = defaultdict(list)
    for key in right_by:
        if key not in left_by:
            loose_right[_loose(key)].append(key)
    near = []
    for key, rows in left_by.items():
        if key in right_by:
            continue
        for other in loose_right.get(_loose(key), []):
            reason = ("leading zeros" if key.lstrip("0") == other.lstrip("0")
                      else "letter case, spaces or punctuation")
            near.append((key, rows[0][0], other, right_by[other][0][0], reason))

    rows_left = sum(len(v) for v in left_by.values())
    rows_right = sum(len(v) for v in right_by.values())
    matched_left = rows_left - len(left_only)
    matched_right = rows_right - len(right_only)
    summary = [
        ("data-merger version", __version__),
        ("Left file", left_path.name), ("Left file read as", left.read_as),
        ("Left file SHA-256", left.sha256), ("Left key column", left.headers[lk]),
        ("Right file", right_path.name), ("Right file read as", right.read_as),
        ("Right file SHA-256", right.sha256), ("Right key column", right.headers[rk]),
        ("Contract expected", expect),
        ("Contract result", "held" if not violations else
         f"BROKEN by {violations} key(s), see Duplicate keys"),
        ("Left rows with a key", rows_left),
        ("Left rows matched", matched_left),
        ("Left rows with no match (Left only)", len(left_only)),
        ("Left rows with a blank key (never matched)", len(left_blank)),
        ("Check: left rows = matched + left only",
         "balanced" if rows_left == matched_left + len(left_only) else "NOT BALANCED"),
        ("Right rows with a key", rows_right),
        ("Right rows matched", matched_right),
        ("Right rows with no match (Right only)", len(right_only)),
        ("Right rows with a blank key (never matched)", len(right_blank)),
        ("Check: right rows = matched + right only",
         "balanced" if rows_right == matched_right + len(right_only) else "NOT BALANCED"),
        ("Rows in Joined", len(joined)),
        ("Rows in Joined beyond one per matched key",
         len(joined) - sum(key in right_by for key in left_by)),
        ("Keys that almost match (Near keys)", len(near)),
        ("Keys compared as", "text, exactly as typed apart from outer spaces"),
    ]
    return JoinResult(headers, joined, left_only, right_only, duplicates,
                      left_blank + right_blank, near, summary, violations,
                      left.headers, right.headers)


def write_join_workbook(result: JoinResult, path: str | Path) -> Path:
    path = Path(path)
    workbook = Workbook(write_only=True)

    def fill(title: str, headers: list[str], rows: list) -> None:
        sheet = _sheet(workbook, title, headers)
        for row in rows:
            sheet.append([safe_cell(c) for c in row])

    fill("Joined", result.headers, result.joined)
    fill("Left only", ["left_row", *result.left_headers], result.left_only)
    fill("Right only", ["right_row", *result.right_headers], result.right_only)
    fill("Duplicate keys", ["key", "status", "left_rows", "right_rows", "joined_rows_made"],
         result.duplicates)
    fill("Blank keys", ["file", "row"], result.blank_keys)
    fill("Near keys", ["left_key", "left_row", "right_key", "right_row", "differs_by"],
         result.near_keys)
    sheet = _sheet(workbook, "Summary", ["metric", "value"], [50, 70])
    for metric, value in result.summary:
        sheet.append([metric, value])
    workbook.save(path)
    return path
