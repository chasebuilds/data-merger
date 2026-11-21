"""Command line.

data-merger merge a.csv b.xlsx c.csv -o merged.xlsx    fuzzy merge of overlapping lists
data-merger audit merged.xlsx                          precision from a labeled Audit sheet
data-merger join a.csv b.csv --on customer_id          exact join on an ID column
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .audit import audit_report, read_audit
from .config import load_config
from .join import CONTRACTS, join_files, write_join_workbook
from .pipeline import merge_files
from .workbook import write_workbook


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="data-merger",
        description="Merge overlapping CSV/XLSX record lists into one traceable workbook.",
    )
    parser.add_argument("--version", action="version", version=f"data-merger {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    merge = commands.add_parser("merge", help="merge source files into one workbook")
    merge.add_argument("sources", nargs="+", type=Path, help="CSV or XLSX files, 2 or more")
    merge.add_argument("-o", "--output", type=Path, default=Path("merged.xlsx"))
    merge.add_argument("-c", "--config", type=Path,
                       help="TOML config (see merge_config.example.toml)")
    merge.add_argument("--auto", type=float, help="auto-merge threshold, default 0.88")
    merge.add_argument("--review", type=float, help="review threshold, default 0.70")
    merge.add_argument("--decisions", type=Path, metavar="WORKBOOK",
                       help="earlier output whose Review sheet has same/different answers")
    merge.add_argument("--audit-sample", type=int, default=0, metavar="N",
                       help="add an Audit sheet with N random merges per match reason to label")
    merge.add_argument("--audit-seed", type=int, default=0, help="seed for the audit sample")
    merge.add_argument("--one-per-source", action="store_true",
                       help="never merge two rows from the same file (files have no duplicates)")
    merge.add_argument("--no-lineage", action="store_true", help="skip the per-value Lineage sheet")
    merge.add_argument("--keep-placeholders", action="store_true",
                       help="leave filler contacts (none@none.com, 000-000-0000) in the output "
                            "instead of blanking them")

    audit = commands.add_parser("audit", help="report match quality from a labeled Audit sheet")
    audit.add_argument("workbook", type=Path)

    join = commands.add_parser("join", help="exact join of two files on an ID column")
    join.add_argument("left", type=Path)
    join.add_argument("right", type=Path)
    join.add_argument("--on", required=True, help="key column header in the left file")
    join.add_argument("--right-on", help="key column header in the right file, if different")
    join.add_argument("--expect", choices=CONTRACTS, default="one-to-one",
                      help="how many rows may share a key on each side (left-to-right)")
    join.add_argument("-o", "--output", type=Path, default=Path("joined.xlsx"))
    return parser


def _merge(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if args.auto is not None:
        config.auto_threshold = args.auto
    if args.review is not None:
        config.review_threshold = args.review
    if args.one_per_source:
        config.one_per_source = True
    if args.keep_placeholders:
        config.placeholders = "keep"
    config.validate()
    result = merge_files(args.sources, config, decisions_from=args.decisions,
                         audit_sample=args.audit_sample, audit_seed=args.audit_seed)
    if args.no_lineage or not config.lineage:
        result.lineage = []
    write_workbook(result, args.output)

    multi = sum(len(m.members) > 1 for m in result.merged)
    print(f"Read {len(result.records)} rows from {len(args.sources)} files.")
    print(f"Merged records: {len(result.merged)} ({multi} built from 2 or more rows)")
    print(f"Review pairs:   {len(result.review)}")
    print(f"Conflicts kept: {len(result.conflicts)}")
    print(f"Unmatched:      {len(result.unmatched)}")
    if result.load.blanked:
        print(f"Placeholders:   {len(result.load.blanked)} filler contacts blanked")
    if args.decisions:
        applied = result.match.decisions_applied
        print(f"Decisions used: {applied['same']} same, {applied['different']} different")
    if result.audit:
        print(f"Audit sample:   {len(result.audit)} pairs to label")
    print(f"Wrote {args.output}")
    return 0


def _join(args: argparse.Namespace) -> int:
    result = join_files(args.left, args.right, args.on, args.right_on, args.expect)
    write_join_workbook(result, args.output)
    print(f"Joined rows: {len(result.joined)}")
    print(f"Left only:   {len(result.left_only)}")
    print(f"Right only:  {len(result.right_only)}")
    print(f"Blank keys:  {len(result.blank_keys)}")
    print(f"Near keys:   {len(result.near_keys)}")
    print(f"Wrote {args.output}")
    if result.violations:
        print(f"error: {result.violations} key(s) break the {args.expect} contract. "
              "See the Duplicate keys sheet before using Joined.", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = {"merge": lambda: [*args.sources, args.config, args.decisions],
             "audit": lambda: [args.workbook],
             "join": lambda: [args.left, args.right]}[args.command]()
    missing = [str(p) for p in paths if p is not None and not p.is_file()]
    if missing:
        print(f"error: file not found: {', '.join(missing)}", file=sys.stderr)
        return 2
    try:
        if args.command == "merge":
            return _merge(args)
        if args.command == "join":
            return _join(args)
        print(audit_report(read_audit(args.workbook)))
        return 0
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
