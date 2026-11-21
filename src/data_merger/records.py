"""Read source files into normalized records that remember where they came from."""

from __future__ import annotations

import csv
import hashlib
import io
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from openpyxl import load_workbook

from . import normalize as nz
from .config import Config
from .schema import CANONICAL, IGNORE, ColumnMapping, map_headers

DELIMITERS = {",": "comma", ";": "semicolon", "\t": "tab", "|": "pipe"}
# Character pairs that show UTF-8 text was decoded with the wrong code page at some point.
_MOJIBAKE = re.compile(
    f"{chr(0xC3)}[{chr(0x80)}-{chr(0xBF)}]|{chr(0xE2)}{chr(0x20AC)}|{chr(0xFFFD)}"
)
_PLACEHOLDER_LOCALS = {
    "none", "no", "na", "noemail", "nomail", "unknown", "null", "test", "noreply",
    "donotreply", "nobody", "noaddress", "x", "xx", "xxx", "email",
}
_PLACEHOLDER_PHONES = {"1234567890", "0123456789", "9876543210"}


@dataclass
class Record:
    idx: int
    source_file: str
    source_row: int  # row number as shown in the file; the header is row 1
    values: dict[str, object] = field(default_factory=dict)
    email: str = ""
    phone: str = ""
    first: str = ""
    last: str = ""
    street: str = ""
    house: str = ""
    zip5: str = ""
    city: str = ""
    company: str = ""
    updated: date | None = None

    @property
    def ref(self) -> str:
        return f"{self.source_file}:{self.source_row}"


@dataclass
class Table:
    headers: list[str]
    rows: list[list[str]]
    read_as: str  # what was assumed about the file, in plain words
    sha256: str
    skipped_sheets: list[str] = field(default_factory=list)
    suspect_cells: int = 0


@dataclass
class LoadResult:
    records: list[Record]
    mappings: list[ColumnMapping]
    columns: list[str]  # canonical columns in use, then extras, in output order
    rows_per_file: dict[str, int]
    blank_rows: int
    unparsed: list[tuple[str, int, str, str]]  # file, row, column, raw value
    tables: dict[str, Table] = field(default_factory=dict)
    placeholders: Counter = field(default_factory=Counter)  # (column, value) -> rows
    profile: dict[str, dict[str, str]] = field(default_factory=dict)


def sniff_delimiter(first_line: str) -> str:
    """Pick the separator that splits the header line into the most cells."""
    counts = {d: len(next(csv.reader([first_line], delimiter=d))) for d in DELIMITERS}
    best = max(counts, key=lambda d: counts[d])
    return best if counts[best] > 1 else ","


def read_table(path: Path) -> Table:
    """Read one file as strings. The first row of the first sheet is the header."""
    suffix = path.suffix.lower()
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    skipped: list[str] = []
    if suffix in (".xlsx", ".xlsm"):
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        try:
            sheet = workbook.worksheets[0]
            raw = [[nz.cell_to_str(c) for c in row] for row in sheet.iter_rows(values_only=True)]
            skipped = [s.title for s in workbook.worksheets[1:]]
            read_as = f"Excel, sheet '{sheet.title}', formulas read as their last saved value"
        finally:
            workbook.close()
    elif suffix in (".csv", ".txt", ".tsv"):
        # An encoding cannot be detected for certain. UTF-8 fails loudly on other
        # encodings, so it is tried first; Windows-1252 accepts any bytes and is the guess.
        try:
            text, encoding = data.decode("utf-8-sig"), "UTF-8"
        except UnicodeDecodeError:
            text, encoding = data.decode("cp1252", errors="replace"), "Windows-1252 (a guess)"
        delimiter = "\t" if suffix == ".tsv" else sniff_delimiter(text.split("\n", 1)[0])
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
        raw = [[nz.cell_to_str(c) for c in row] for row in reader]
        read_as = f"text, {encoding}, {DELIMITERS[delimiter]}-separated"
    else:
        raise ValueError(f"Unsupported file type: {path.name} (use .csv, .tsv or .xlsx)")
    suspect = sum(bool(_MOJIBAKE.search(cell)) for row in raw for cell in row)
    headers, rows = (raw[0], raw[1:]) if raw else ([], [])
    return Table(headers, rows, read_as, digest, skipped, suspect)


def is_placeholder(column: str, key: str) -> bool:
    """A filler value typed to get past a required field. It identifies nobody."""
    if column == "email":
        return re.sub(r"[^a-z0-9]", "", key.partition("@")[0]) in _PLACEHOLDER_LOCALS
    return len(set(key)) == 1 or key in _PLACEHOLDER_PHONES or key[3:] == "0000000"


def _set_keys(record: Record) -> list[tuple[str, str]]:
    """Fill the match keys. Returns placeholder values that were kept out of matching."""
    values = record.values
    record.email = str(values.get("email", ""))
    record.phone = nz.phone_digits(str(values.get("phone", "")))
    if len(record.phone) < 7:
        record.phone = ""
    ignored = []
    for column in ("email", "phone"):
        key = getattr(record, column)
        if key and is_placeholder(column, key):
            ignored.append((column, str(values[column])))
            setattr(record, column, "")
    record.first = nz.first_name_key(str(values.get("first_name", "")))
    record.last = nz.last_name_key(str(values.get("last_name", "")))
    street = str(values.get("street", ""))
    record.street = nz.street_key(street)
    record.house = nz.house_number(street)
    record.zip5 = str(values.get("postal_code", ""))[:5]
    record.city = nz.squash(str(values.get("city", "")))
    record.company = nz.company_key(str(values.get("company", "")))
    record.updated = nz.parse_date(str(values.get("updated_at", "")))
    return ignored


def _profile(records: list[Record]) -> dict[str, str]:
    """Fill rate and most repeated value for the identifiers matching leans on."""
    out: dict[str, str] = {}
    fills = []
    for column in ("email", "phone", "street"):
        present = [str(r.values[column]) for r in records if r.values.get(column)]
        fills.append(f"{column} {100 * len(present) / len(records):.0f}%")
        if present:
            value, count = Counter(present).most_common(1)[0]
            if count >= 3:
                out[f"most repeated {column}"] = f"{value} ({count} rows)"
    return {"filled in": ", ".join(fills), **out}


def load_sources(paths: list[Path], config: Config) -> LoadResult:
    names = [p.name for p in paths]
    if len(set(names)) != len(names):
        raise ValueError("Source files must have different file names (lineage uses the name).")
    result = LoadResult([], [], [], {}, 0, [])
    records = result.records
    extras: list[str] = []
    used: set[str] = set()

    for path in paths:
        table = read_table(path)
        result.tables[path.name] = table
        file_map = map_headers(path.name, table.headers, config.mapping.get(path.name))
        result.mappings.extend(file_map)
        start = len(records)
        for offset, row in enumerate(table.rows):
            if not any(row):
                result.blank_rows += 1
                continue
            row_number = offset + 2
            values: dict[str, object] = {}
            for mapping, cell in zip(file_map, row, strict=False):
                if mapping.target == IGNORE or not cell:
                    continue
                if mapping.target == "full_name":
                    parts = dict(zip(("first_name", "last_name"), nz.split_full_name(cell),
                                     strict=True))
                elif mapping.target == "full_address":
                    parts = nz.split_full_address(cell)
                elif mapping.target.startswith("extra:"):
                    name = mapping.target.removeprefix("extra:")
                    parts = {f"{name} (extra)" if name in CANONICAL else name: cell}
                else:
                    parts = {mapping.target: cell}
                for column, raw in parts.items():
                    if not raw:
                        continue
                    value, ok = nz.normalize_value(
                        CANONICAL.get(column, "text"), raw, config.dayfirst
                    )
                    if not ok:
                        result.unparsed.append((path.name, row_number, column, raw))
                    # A composite column never overwrites a dedicated one in the same row.
                    values.setdefault(column, value)
                    if column in CANONICAL:
                        used.add(column)
                    elif column not in extras:
                        extras.append(column)
            record = Record(len(records), path.name, row_number, values)
            result.placeholders.update(_set_keys(record))
            records.append(record)
        result.rows_per_file[path.name] = len(records) - start
        if len(records) > start:
            result.profile[path.name] = _profile(records[start:])

    result.columns = [c for c in CANONICAL if c in used] + extras
    return result
