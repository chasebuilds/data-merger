"""Write the result workbook. Sheet order is the order a client should read them in."""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from .pipeline import DECISION_HEADER, MergeResult

# Excel's hard row limit; Lineage is the only sheet that can realistically reach it.
EXCEL_MAX_ROWS = 1_048_576
AUDIT_LABEL_HEADER = "label (same / different)"
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_HEADER_FILL = PatternFill("solid", fgColor="1F4E78")

SHEET_GUIDE = [
    ("Merged", "The result. One row per real-world record. source_rows shows which file rows "
               "were combined, match_score and match_basis show why."),
    ("Review", "Pairs the tool was not sure about, side by side. Type same or different in the "
               "decision column; a rerun with --decisions applies your answers."),
    ("Conflicts", "Every value that lost to another when merged rows disagreed, where it came "
                  "from, and which rule decided."),
    ("Placeholders", "Filler contacts such as none@none.com or 000-000-0000 that were blanked "
                     "in Merged, with the file and row each came from."),
    ("Unmatched", "Records found in only one row of one file."),
    ("Crosswalk", "One row per source row: which merged record it went to and how."),
    ("Mapping", "How each source column header was understood. Check this first."),
    ("Audit", "Only if requested. A random sample of merges to label, so match quality on "
              "this job can be measured instead of assumed."),
    ("Lineage", "For every value in Merged: the exact file and row it was taken from."),
    ("Summary", "Counts, balance checks, settings, file fingerprints, and anything skipped."),
]


def _sheet(workbook: Workbook, title: str, headers: list[str], widths: list[int] | None = None):
    sheet = workbook.create_sheet(title)
    for index, header in enumerate(headers, start=1):
        width = widths[index - 1] if widths else max(12, min(len(header) + 4, 40))
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.freeze_panes = "A2"
    cells = []
    for header in headers:
        cell = WriteOnlyCell(sheet, value=header)
        cell.font, cell.fill = _HEADER_FONT, _HEADER_FILL
        cells.append(cell)
    sheet.append(cells)
    return sheet


def safe_cell(value: object) -> object:
    """Stop a text value from running as a formula when the client opens the file."""
    if not isinstance(value, str) or len(value) < 2:
        return value
    first = value[0]
    # A leading minus is only dangerous in front of text; "-12.50" and "-5" stay as typed.
    risky = first in "=+@\t\r" or (first == "-" and not value[1:].replace(".", "").isdigit())
    return "'" + value if risky else value


def write_workbook(result: MergeResult, path: str | Path) -> Path:
    path = Path(path)
    workbook = Workbook(write_only=True)
    columns = result.columns
    rows_of = {r.idx: r for r in result.records}

    sheet = _sheet(workbook, "Read me", ["What this workbook is", ""], [22, 110])
    sheet.append(["", "Several source files merged into one list. Nothing was deleted: every "
                      "source row is accounted for on the Crosswalk sheet."])
    sheet.append([])
    sheet.append(["How it was done", ""])
    for line in result.method:
        sheet.append(["", line])
    sheet.append([])
    sheet.append(["Sheet", "What is in it"])
    for name, text in SHEET_GUIDE:
        sheet.append([name, text])

    lineage_cols = ["source_count", "source_files", "source_rows", "match_score", "match_basis"]
    headers = ["merged_id", *columns, *lineage_cols]
    rows = [
        [
            row.merged_id, *[safe_cell(row.values.get(c, "")) for c in columns],
            len(row.members), row.source_files, row.source_rows, row.match_score, row.match_basis,
        ]
        for row in result.merged
    ]
    # size to the content so emails and phones are not cut off when the client opens it
    widths = [
        max(12, min(40, 2 + max([len(h)] + [len(str(r[i])) for r in rows[:2000]])))
        for i, h in enumerate(headers)
    ]
    sheet = _sheet(workbook, "Merged", headers, widths)
    for row in rows:
        sheet.append(row)

    side = [f"{c} [A]" for c in columns] + [f"{c} [B]" for c in columns]
    sheet = _sheet(workbook, "Review", [
        "pair", "match_score", "why", DECISION_HEADER,
        "merged_id [A]", "source [A]", "merged_id [B]", "source [B]", *side,
    ])
    for number, pair in enumerate(result.review, start=1):
        a, b = rows_of[pair.a], rows_of[pair.b]
        sheet.append([
            number, pair.score, pair.basis, "", result.merged_id_of[a.idx], a.ref,
            result.merged_id_of[b.idx], b.ref,
            *[safe_cell(a.values.get(c, "")) for c in columns],
            *[safe_cell(b.values.get(c, "")) for c in columns],
        ])

    sheet = _sheet(workbook, "Conflicts", [
        "merged_id", "column", "kept_value", "kept_from", "lost_value", "lost_from", "rule",
    ], [12, 16, 30, 28, 30, 40, 18])
    for c in result.conflicts:
        sheet.append([c.merged_id, c.column, safe_cell(c.kept_value), c.kept_source,
                      safe_cell(c.lost_value), c.lost_sources, c.rule])

    sheet = _sheet(workbook, "Placeholders", [
        "merged_id", "source_file", "source_row", "column", "value_removed", "reason",
    ], [12, 26, 12, 12, 30, 50])
    if result.load:
        ids = {(r.source_file, r.source_row): result.merged_id_of[r.idx] for r in result.records}
        for file, row, column, value in result.load.blanked:
            sheet.append([ids[file, row], file, row, column, safe_cell(value),
                          "filler value, identifies nobody; blanked in Merged"])

    sheet = _sheet(workbook, "Unmatched", ["merged_id", "source_file", "source_row", "reason",
                                           *columns])
    for row, reason in result.unmatched:
        member = row.members[0]
        sheet.append([row.merged_id, member.source_file, member.source_row, reason,
                      *[safe_cell(row.values.get(c, "")) for c in columns]])

    sheet = _sheet(workbook, "Crosswalk", [
        "source_file", "source_row", "merged_id", "match_tier", "match_score", "match_basis",
    ], [26, 12, 12, 14, 12, 60])
    for item in result.crosswalk:
        sheet.append([item.source_file, item.source_row, item.merged_id, item.tier, item.score,
                      item.basis])

    sheet = _sheet(workbook, "Mapping", [
        "source_file", "source_header", "mapped_to", "method", "score", "note",
    ], [24, 26, 26, 12, 8, 60])
    for m in result.mappings:
        sheet.append([m.source_file, m.header, m.target, m.method, m.score, m.note])

    if result.audit:
        sheet = _sheet(workbook, "Audit", [
            "sample", "stratum", "stratum_size", "match_score", AUDIT_LABEL_HEADER,
            "source [A]", "source [B]", *side,
        ])
        for number, item in enumerate(result.audit, start=1):
            a, b = rows_of[item.pair.a], rows_of[item.pair.b]
            sheet.append([
                number, item.stratum, item.stratum_size, item.pair.score, "", a.ref, b.ref,
                *[safe_cell(a.values.get(c, "")) for c in columns],
                *[safe_cell(b.values.get(c, "")) for c in columns],
            ])

    summary = list(result.summary)
    if not result.lineage:
        summary.append(("Lineage sheet", "turned off"))
    elif len(result.lineage) >= EXCEL_MAX_ROWS:
        summary.append(("Lineage sheet", "left out: more rows than one Excel sheet can hold"))
    else:
        sheet = _sheet(workbook, "Lineage", [
            "merged_id", "column", "value", "taken_from_file", "taken_from_row",
            "source_rows_agreeing",
        ], [12, 16, 34, 26, 16, 22])
        for item in result.lineage:
            sheet.append([item.merged_id, item.column, safe_cell(item.value), item.source_file,
                          item.source_row, item.agreeing_rows])

    sheet = _sheet(workbook, "Summary", ["metric", "value"], [58, 70])
    for metric, value in summary:
        sheet.append([metric, value])

    workbook.save(path)
    return path
