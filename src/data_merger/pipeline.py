"""The whole run: load, align, normalize, match, resolve. Returns everything the workbook shows."""

from __future__ import annotations

import random
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from openpyxl import load_workbook

from . import __version__
from .config import Config
from .match import HUMAN_SAME, MatchResult, PairScore, match_records
from .records import LoadResult, Record, load_sources
from .resolve import Conflict, Lineage, resolve_cluster
from .schema import ColumnMapping

DECISION_HEADER = "decision (same / different)"
_SAME = {"same", "s", "yes", "y", "merge", "match"}
_DIFFERENT = {"different", "d", "diff", "no", "n", "not same", "separate"}


@dataclass
class MergedRow:
    merged_id: str
    values: dict[str, object]
    members: list[Record]
    match_score: float | None
    match_basis: str

    @property
    def source_files(self) -> str:
        return "; ".join(dict.fromkeys(r.source_file for r in self.members))

    @property
    def source_rows(self) -> str:
        return "; ".join(r.ref for r in self.members)


@dataclass
class CrosswalkRow:
    source_file: str
    source_row: int
    merged_id: str
    tier: str  # exact key | fuzzy | human | unmatched
    score: float | None
    basis: str


@dataclass
class AuditRow:
    stratum: str
    stratum_size: int
    pair: PairScore


@dataclass
class MergeResult:
    columns: list[str]
    records: list[Record]
    merged: list[MergedRow]
    review: list[PairScore]
    conflicts: list[Conflict]
    lineage: list[Lineage]
    unmatched: list[tuple[MergedRow, str]]
    mappings: list[ColumnMapping]
    summary: list[tuple[str, object]]
    merged_id_of: dict[int, str] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)
    match: MatchResult | None = None
    load: LoadResult | None = None
    crosswalk: list[CrosswalkRow] = field(default_factory=list)
    audit: list[AuditRow] = field(default_factory=list)
    method: list[str] = field(default_factory=list)


def tier_of(basis: str) -> str:
    if basis.startswith("human"):
        return "human"
    return "exact key" if basis.startswith("same ") else "fuzzy"


def read_decisions(
    path: Path, records: list[Record]
) -> tuple[dict[tuple[int, int], str], dict[str, int]]:
    """Read same/different answers from the Review sheet of an earlier output workbook."""
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        if "Review" not in workbook.sheetnames:
            raise ValueError(f"{path.name} has no Review sheet to read decisions from")
        rows = list(workbook["Review"].iter_rows(values_only=True))
    finally:
        workbook.close()
    header = [str(h or "") for h in rows[0]] if rows else []
    try:
        col = [header.index(h) for h in (DECISION_HEADER, "source [A]", "source [B]")]
    except ValueError as error:
        raise ValueError(f"{path.name}: Review sheet is missing a column ({error})") from error
    by_ref = {r.ref: r.idx for r in records}
    decisions: dict[tuple[int, int], str] = {}
    counts = {"same": 0, "different": 0, "blank": 0, "not understood": 0, "row not found": 0}
    for row in rows[1:]:
        answer = str(row[col[0]] or "").strip().lower()
        if not answer:
            counts["blank"] += 1
            continue
        verdict = "same" if answer in _SAME else "different" if answer in _DIFFERENT else ""
        a, b = by_ref.get(str(row[col[1]])), by_ref.get(str(row[col[2]]))
        if not verdict:
            counts["not understood"] += 1
        elif a is None or b is None:
            # The source files changed since the review; a stale answer is never applied.
            counts["row not found"] += 1
        else:
            decisions[(a, b)] = verdict
            counts[verdict] += 1
    return decisions, counts


def draw_audit_sample(match: MatchResult, per_stratum: int, seed: int) -> list[AuditRow]:
    """Seeded random sample of merge links per match basis, plus near misses, for labeling."""
    rng = random.Random(seed)
    strata: dict[str, list[PairScore]] = {}
    for link in match.links:
        if link.basis != HUMAN_SAME:
            strata.setdefault(f"merged: {link.basis}", []).append(link)
    if match.near_misses:
        strata["not merged: near miss, just under the review band"] = match.near_misses
    sample: list[AuditRow] = []
    for name in sorted(strata):
        pool = strata[name]
        picked = rng.sample(pool, min(per_stratum, len(pool)))
        sample.extend(AuditRow(name, len(pool), p) for p in sorted(picked, key=lambda p: p.a))
    return sample


def merge_files(
    paths: list[str | Path], config: Config | None = None, *,
    decisions_from: str | Path | None = None, audit_sample: int = 0, audit_seed: int = 0,
) -> MergeResult:
    config = config or Config()
    config.validate()
    files = [Path(p) for p in paths]
    started = time.perf_counter()
    load = load_sources(files, config)
    loaded = time.perf_counter()
    decisions: dict[tuple[int, int], str] = {}
    decision_counts: dict[str, int] = {}
    if decisions_from is not None:
        decisions, decision_counts = read_decisions(Path(decisions_from), load.records)
    match = match_records(load.records, config, decisions)
    matched = time.perf_counter()

    order = config.source_priority + [f.name for f in files if f.name not in config.source_priority]
    priority = {name: rank for rank, name in enumerate(order)}
    width = max(4, len(str(len(match.clusters))))
    merged: list[MergedRow] = []
    conflicts: list[Conflict] = []
    lineage: list[Lineage] = []
    merged_id_of: dict[int, str] = {}
    for number, cluster in enumerate(match.clusters, start=1):
        merged_id = f"M{number:0{width}d}"
        members = [load.records[i] for i in cluster]
        values, row_conflicts, row_lineage = resolve_cluster(
            merged_id, members, load.columns, config, priority
        )
        merged.append(MergedRow(merged_id, values, members, match.cluster_scores[number - 1],
                                match.cluster_basis[number - 1]))
        conflicts.extend(row_conflicts)
        lineage.extend(row_lineage)
        for i in cluster:
            merged_id_of[i] = merged_id

    in_review = {merged_id_of[i] for pair in match.review for i in (pair.a, pair.b)}
    unmatched = [
        (row, "possible match waiting in Review" if row.merged_id in in_review
         else "no other record scored above the review threshold")
        for row in merged if len(row.members) == 1
    ]

    # Each row's own strongest link says how it got into its merged record.
    strongest: dict[int, PairScore] = {}
    for link in match.links:
        for i in (link.a, link.b):
            if i not in strongest or link.score > strongest[i].score:
                strongest[i] = link
    crosswalk = [
        CrosswalkRow(r.source_file, r.source_row, merged_id_of[r.idx],
                     tier_of(strongest[r.idx].basis) if r.idx in strongest else "unmatched",
                     strongest[r.idx].score if r.idx in strongest else None,
                     strongest[r.idx].basis if r.idx in strongest else "")
        for r in load.records
    ]
    audit = draw_audit_sample(match, audit_sample, audit_seed) if audit_sample > 0 else []
    resolved = time.perf_counter()

    rows_read = len(load.records)
    absorbed = rows_read - len(merged)
    sizes = Counter(len(m.members) for m in merged)
    link_basis = Counter(link.basis for link in match.links)
    fields = [c for c in ("email", "phone", "first_name", "last_name", "street", "postal_code",
                          "company") if c in load.columns]
    method = [
        f"{len(files)} files with {rows_read} rows were read. Each header was mapped to a "
        "standard column (Mapping sheet) and values were put in one format.",
        f"Rows were compared on: {', '.join(fields)}. Only rows sharing a cheap key (same "
        "email, same phone, similar surname and first initial, same ZIP and house number, same "
        f"company and first initial) were compared: {match.candidate_pairs} pairs.",
        f"A pair scoring {config.auto_threshold} or more was merged, {config.review_threshold} "
        "or more was sent to the Review sheet, anything lower was left apart. A merge was held "
        "for review if it would join clashing first names, join groups with different contact "
        f"details, or make a record of more than {config.max_cluster_size} rows.",
        f"Where merged rows disagreed, the value was chosen by rule ({config.default_rule} "
        "unless a column says otherwise) and the losing value was written to Conflicts.",
        f"Result: {len(merged)} records from {rows_read} rows. Pairs waiting for a decision: "
        f"{len(match.review)}. Conflicts logged: {len(conflicts)}.",
        "These are rule-based matches, not certainties. Check the Review sheet, and label the "
        "Audit sheet if one was requested, before relying on the merged list.",
    ]

    summary: list[tuple[str, object]] = [
        ("data-merger version", __version__),
        ("Source files", len(files)),
        *[(f"Rows read: {name}", count) for name, count in load.rows_per_file.items()],
        ("Rows read, total", rows_read),
        ("Blank rows skipped", load.blank_rows),
        ("Merged records (one per real-world record)", len(merged)),
        ("Merged records built from 2+ rows", sum(len(m.members) > 1 for m in merged)),
        ("Rows absorbed by auto-merge", absorbed),
        ("Check: rows read = merged records + rows absorbed",
         f"{rows_read} = {len(merged)} + {absorbed}: "
         + ("balanced" if rows_read == len(merged) + absorbed else "NOT BALANCED")),
        ("Check: rows read = Crosswalk rows",
         f"{rows_read} = {len(crosswalk)}: "
         + ("balanced" if rows_read == len(crosswalk) else "NOT BALANCED")),
        ("Review pairs (need a human decision)", len(match.review)),
        ("Conflicts logged (losing values kept)", len(conflicts)),
        ("Unmatched records (single source row)", len(unmatched)),
        *[(f"Merge links by reason: {basis}", count) for basis, count in link_basis.most_common()],
        *[(f"Merges held for review: {reason}", count)
          for reason, count in sorted(match.held_back.items())],
        *[(f"Merged records made of {size} row{'s' if size > 1 else ''}", count)
          for size, count in sorted(sizes.items())],
        *[(f"Review decisions read: {kind}", count) for kind, count in decision_counts.items()],
        ("Values that could not be parsed (kept as typed)", len(load.unparsed)),
        *[(f"Not parsed: {f} row {r}, {c}", v) for f, r, c, v in load.unparsed[:25]],
        ("Placeholder emails and phones not used for matching",
         sum(load.placeholders.values())),
        ("Placeholder emails and phones in the output",
         f"blanked: {len(load.blanked)} cells, each on the Placeholders sheet"
         if config.placeholders == "blank" else "kept as typed (options.placeholders = keep)"),
        *[(f"Placeholder {column}: {value}", f"{count} rows")
          for (column, value), count in load.placeholders.most_common(25)],
        ("Candidate pairs compared (after blocking)", match.candidate_pairs),
        ("All possible pairs (no blocking)", rows_read * (rows_read - 1) // 2),
        ("Oversized blocks skipped", len(match.skipped_blocks)),
        *[(f"Skipped block: {key}", f"{size} rows share this key")
          for key, size in match.skipped_blocks[:25]],
        ("Auto-merge threshold", config.auto_threshold),
        ("Review threshold", config.review_threshold),
        ("Largest merged record allowed (rows)", config.max_cluster_size),
        ("One row per file in a merged record", "yes" if config.one_per_source else "no"),
        ("Default conflict rule", config.default_rule),
        *[(f"Conflict rule: {col}", rule) for col, rule in sorted(config.column_rules.items())],
        ("Source priority (first wins ties)", ", ".join(order)),
        ("Phone numbers read as", "10-digit US and Canada numbers; others kept as typed"),
        ("Dates read as", "day first" if config.dayfirst else "month first"),
    ]
    for name, table in load.tables.items():
        summary.append((f"File read as: {name}", table.read_as))
        summary.append((f"File SHA-256: {name}", table.sha256))
        if table.skipped_sheets:
            summary.append((f"Sheets NOT read: {name}", ", ".join(table.skipped_sheets)))
        if table.suspect_cells:
            summary.append((f"Cells with garbled characters: {name}", table.suspect_cells))
        for label, value in load.profile.get(name, {}).items():
            summary.append((f"Identifiers, {label}: {name}", value))
    timings = {"load": loaded - started, "match": matched - loaded, "resolve": resolved - matched}
    return MergeResult(load.columns, load.records, merged, match.review, conflicts, lineage,
                       unmatched, load.mappings, summary, merged_id_of, timings, match, load,
                       crosswalk, audit, method)
