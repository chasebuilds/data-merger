"""Score data-merger against generated truth and write BENCHMARK.md from the real run.

    python -m benchmark.run_benchmark

Nothing in BENCHMARK.md is typed by hand. The same run also refreshes the result block
in README.md between the benchmark markers.
"""

from __future__ import annotations

import argparse
import platform
import re
import tempfile
import time
from collections import defaultdict
from datetime import date
from itertools import combinations
from pathlib import Path

from benchmark.generate import generate
from data_merger import Config, merge_files, write_workbook
from data_merger import normalize as nz

ROOT = Path(__file__).resolve().parent.parent
MARK_START, MARK_END = "<!-- benchmark:start -->", "<!-- benchmark:end -->"


def score(entities: int, sources: int, seed: int, work: Path,
          config: Config | None = None, write: bool = True) -> dict[str, object]:
    made = generate(work, entities, sources, seed)
    truth: dict[tuple[str, int], str] = made["truth"]
    people = made["entities"]

    started = time.perf_counter()
    result = merge_files(made["paths"], config or Config())
    merge_seconds = time.perf_counter() - started
    started = time.perf_counter()
    if write:
        write_workbook(result, work / "merged.xlsx")
    write_seconds = time.perf_counter() - started

    by_entity: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for key, entity_id in truth.items():
        by_entity[entity_id].append(key)
    true_pairs = {frozenset(p) for rows in by_entity.values() for p in combinations(rows, 2)}

    predicted: set[frozenset] = set()
    mixed_records = 0
    cluster_of: dict[tuple[str, int], str] = {}
    for row in result.merged:
        keys = [(m.source_file, m.source_row) for m in row.members]
        for key in keys:
            cluster_of[key] = row.merged_id
        predicted.update(frozenset(p) for p in combinations(keys, 2))
        mixed_records += len({truth[k] for k in keys}) > 1

    correct = predicted & true_pairs
    false_pairs = predicted - true_pairs
    missed = true_pairs - predicted

    by_idx = {r.idx: (r.source_file, r.source_row) for r in result.records}
    review_links = set()
    review_true = 0
    for pair in result.review:
        a, b = by_idx[pair.a], by_idx[pair.b]
        review_links.add(frozenset((cluster_of[a], cluster_of[b])))
        review_true += truth[a] == truth[b]
    missed_in_review = sum(
        frozenset(cluster_of[k] for k in pair) in review_links for pair in missed
    )

    # When sources disagreed and one of them held the current value, did the merge keep it?
    kept = {"email": [0, 0], "phone": [0, 0]}
    disputed = {(c.merged_id, c.column) for c in result.conflicts}
    for row in result.merged:
        owners = {truth[(m.source_file, m.source_row)] for m in row.members}
        if len(owners) != 1:
            continue
        person = people[owners.pop()]
        for column, want in (("email", person.email), ("phone", person.phone)):
            if (row.merged_id, column) not in disputed:
                continue
            got = [nz.phone_digits(str(m.values.get(column, ""))) if column == "phone"
                   else str(m.values.get(column, "")) for m in row.members]
            if want not in got:
                continue
            final = str(row.values.get(column, ""))
            final = nz.phone_digits(final) if column == "phone" else final
            kept[column][1] += 1
            kept[column][0] += final == want

    # Blocking recall: a true pair that was never compared can never be found.
    compared_true = sum(
        truth[by_idx[a]] == truth[by_idx[b]] for a, b in result.match.compared
    )
    # Precision by the reason a link was made. A link is the pair that joined two groups.
    by_basis: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for link in result.match.links:
        tally = by_basis[link.basis]
        tally[0] += 1
        tally[1] += truth[by_idx[link.a]] != truth[by_idx[link.b]]

    return {
        "seed": seed,
        "blocking_recall": compared_true / len(true_pairs) if true_pairs else 1.0,
        "by_basis": dict(by_basis),
        "held_back": dict(result.match.held_back),
        "entities": entities,
        "sources": sources,
        "rows": len(result.records),
        "merged": len(result.merged),
        "true_pairs": len(true_pairs),
        "predicted_pairs": len(predicted),
        "correct_pairs": len(correct),
        "false_pairs": len(false_pairs),
        "mixed_records": mixed_records,
        "precision": len(correct) / len(predicted) if predicted else 1.0,
        "recall": len(correct) / len(true_pairs) if true_pairs else 1.0,
        "missed": len(missed),
        "missed_in_review": missed_in_review,
        "missed_silent": len(missed) - missed_in_review,
        "review_pairs": len(result.review),
        "review_true": review_true,
        "candidates": result.match.candidate_pairs,
        "all_pairs": len(result.records) * (len(result.records) - 1) // 2,
        "conflicts": len(result.conflicts),
        "kept": kept,
        "merge_seconds": merge_seconds,
        "write_seconds": write_seconds,
        "lookalikes": sum(p.kind != "plain" for p in people.values()),
    }


def _pct(value: float) -> str:
    return f"{100 * value:.2f}%"


def result_table(runs: list[dict[str, object]]) -> str:
    def line(label: str, fn) -> str:
        return f"| {label} | " + " | ".join(str(fn(r)) for r in runs) + " |"

    head = "| Measure | " + " | ".join(f"{r['rows']:,} source rows" for r in runs) + " |"
    return "\n".join([
        head,
        "|---|" + "---:|" * len(runs),
        line("Source files", lambda r: r["sources"]),
        line("Real-world entities in the truth table", lambda r: f"{r['entities']:,}"),
        line("True matching pairs", lambda r: f"{r['true_pairs']:,}"),
        line("Auto-merged pairs", lambda r: f"{r['predicted_pairs']:,}"),
        line("**Auto-merge precision** (pairs)", lambda r: f"**{_pct(r['precision'])}**"),
        line("**Auto-merge recall** (pairs)", lambda r: f"**{_pct(r['recall'])}**"),
        line("**False merges** (wrong pairs auto-merged)", lambda r: f"**{r['false_pairs']:,}**"),
        line("Merged records that mix two entities", lambda r: f"{r['mixed_records']:,}"),
        line("True pairs sent to Review instead", lambda r: f"{r['missed_in_review']:,}"),
        line("True pairs missed with no flag", lambda r: f"{r['missed_silent']:,}"),
        line("Review pairs for a human to check", lambda r: f"{r['review_pairs']:,}"),
        line("Review pairs that are real matches", lambda r: f"{r['review_true']:,}"),
        line("Pairs compared after blocking",
             lambda r: f"{r['candidates']:,} of {r['all_pairs']:,}"),
        line("Blocking recall (true pairs that were compared at all)",
             lambda r: _pct(r["blocking_recall"])),
        line("Run time: match and resolve", lambda r: f"{r['merge_seconds']:.1f} s"),
        line("Run time: write workbook", lambda r: f"{r['write_seconds']:.1f} s"),
    ])


def basis_table(run: dict[str, object]) -> str:
    rows = sorted(run["by_basis"].items(), key=lambda item: -item[1][0])
    lines = ["| Reason for the merge link | Links | Wrong links | Precision |",
             "|---|---:|---:|---:|"]
    for basis, (links, wrong) in rows:
        lines.append(f"| {basis} | {links:,} | {wrong:,} | {_pct((links - wrong) / links)} |")
    return "\n".join(lines)


def guard_table(pairs: list[tuple[str, dict[str, object], dict[str, object]]]) -> str:
    lines = [
        "| Seed | Guard | Precision | Recall | False-merge pairs | Mixed records | "
        "True pairs in Review |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for label, off, on in pairs:
        for name, run in (("off", off), ("on", on)):
            lines.append(
                f"| {label} | {name} | {_pct(run['precision'])} | {_pct(run['recall'])} | "
                f"{run['false_pairs']:,} | {run['mixed_records']:,} | "
                f"{run['missed_in_review']:,} |"
            )
    return "\n".join(lines)


def guard_section(pairs: list[tuple[str, dict[str, object], dict[str, object]]]) -> str:
    if not pairs:
        return ""
    return f"""
## The false merge that was found, and the rule added for it

Version 0.1.0 of this tool, on seed {pairs[-1][1]['seed']}, auto-merged two different
people who had the same full name and the same employer. One row had no email and the
other had no phone, so no single pair of rows showed a contradiction. Their groups did:
different emails, different phones, different addresses.

Version 0.2.0 adds one rule. Before two groups are joined on a fuzzy link (name plus
address, or name plus company), the contact details of the whole groups are compared. If
both groups have emails and share none, and both have phones and share none, the join goes
to Review. For a name-plus-company link, one of the two is enough. Links made by a shared
email or phone are not affected.

The rule was written after seeing that failure, so seed {pairs[-1][1]['seed']} can no
longer count as unseen data. The main table above uses seed {pairs[0][1]['seed']}, which
was not looked at before the rule was fixed. Both are shown here with the rule off and on,
at {pairs[0][1]['rows']:,} and {pairs[-1][1]['rows']:,} source rows:

{guard_table(pairs)}

The cost of the rule is the recall it gives up: true pairs that used to merge on their own
and now wait in Review. The rule does not make false merges impossible. Two people with
the same name and employer, where the files hold no email or phone that differs, will
still be merged.
"""


def report(runs: list[dict[str, object]], seed: int,
           guard_pairs: list[tuple[str, dict[str, object], dict[str, object]]] | None = None,
           ) -> str:
    big = runs[-1]
    kept_lines = []
    for column in ("email", "phone"):
        good = sum(r["kept"][column][0] for r in runs)
        total = sum(r["kept"][column][1] for r in runs)
        kept_lines.append(
            f"- {column}: kept the current value in {good:,} of {total:,} disputed merges"
            + (f" ({_pct(good / total)})" if total else "")
        )
    sizes = " ".join(str(r["entities"]) for r in runs)
    return f"""# Benchmark

Written by `benchmark/run_benchmark.py` on {date.today().isoformat()} from a real run.
No number on this page was typed by hand.

Command: `python -m benchmark.run_benchmark --seed {seed} --sizes {sizes}`
Python {platform.python_version()} on {platform.system()}, one process, default settings
(auto-merge at 0.88, review at 0.70).

## Result

{result_table(runs)}

## How to read it

- **A pair** is two source rows. If three rows describe one customer, that is three pairs.
- **Precision** answers: of the pairs merged without asking, how many were right?
- **Recall** answers: of all pairs that really are the same entity, how many were merged
  without asking? The rest are either in the Review sheet or missed.
- **False merges are the costly error.** Two different customers glued into one record
  can send one person's invoice to another. In the larger run there were
  **{big['false_pairs']:,} false-merge pairs** across {big['predicted_pairs']:,} auto-merged pairs,
  inside {big['mixed_records']:,} merged record(s). Every merged record lists its source rows,
  so a false merge can be found and split by hand, but nothing in the workbook marks it as wrong.
  A count of zero on one generated data set is not a rate of zero. A different seed of the
  same generator did produce a false merge; see the section on it below.
- **Review pairs** are counted per pair of merged records, so one review row can settle
  several true pairs at once. That is why "true pairs sent to Review" is larger than
  "review pairs that are real matches".
- **Missed with no flag** pairs stay as separate records in `Merged` and are listed in
  `Unmatched`. They are duplicates left in the output, not lost data.

## By reason for the merge

From the larger run. A blended precision figure hides which kind of evidence is weak, so
each reason is scored on its own. A link is the one pair of rows that joined two groups.

{basis_table(big)}

Merges held back for a person in the larger run:
{chr(10).join(f"- {reason}: {count:,}" for reason, count in sorted(big['held_back'].items()))}
{guard_section(guard_pairs or [])}
## Conflict resolution

Where sources disagreed about a value and at least one source row held the entity's
current value, the default rule (`most_recent`) was scored against the truth table:

{chr(10).join(kept_lines)}

A source without a usable date cannot win on recency, so these numbers depend on how many
sources carry a last-updated column. Here four of five source schemas have one.

## What the test data looks like

`benchmark/generate.py` builds a truth table of people (seed {seed}), then writes each one
into a random subset of {big['sources']} source files with different headers and formats.
Each appearance can get a nickname, an initial, a typo, changed casing, a reformatted
phone, a missing email, phone, address or company, or a stale email, phone or address
from an older date. About 3 in 100 are entered twice in the same file.

About 1 in 10 entities is a deliberate look-alike of another one
({big['lookalikes']:,} in the larger run): a household member with the same surname,
address and often phone, or a different person with the same full name. These exist to
give false merges a fair chance to happen.

The true entity id is never written to a source file. It lives in `truth.csv`, which only
the scorer reads.

## Limits of this benchmark

- The data is synthetic. Real exports have problems this generator does not model, and
  real results will differ. Scores on a client's files are unknown until they are checked.
- Matching thresholds were set while developing against seed 1. The main table comes
  from seed {seed}, which was not used for tuning, but both come from the same generator.
- Blocking recall counts true pairs the tool never compared. Those cannot be merged or
  sent to Review at any threshold.
- Names, cities and formats are United States style only.
- Run time is from one desktop PC and will vary by machine.
"""


def update_readme(table: str) -> bool:
    readme = ROOT / "README.md"
    if not readme.exists():
        return False
    text = readme.read_text(encoding="utf-8")
    if MARK_START not in text or MARK_END not in text:
        return False
    block = f"{MARK_START}\n{table}\n{MARK_END}"
    text = re.sub(re.escape(MARK_START) + r".*?" + re.escape(MARK_END), lambda _: block, text,
                  flags=re.S)
    readme.write_text(text, encoding="utf-8", newline="\n")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the data-merger benchmark.")
    parser.add_argument("--seed", type=int, default=20261121)
    parser.add_argument("--seen-seed", type=int, default=20261120,
                        help="seed whose failure led to the contact-detail guard")
    parser.add_argument("--sizes", type=int, nargs="+", default=[1000, 10000],
                        help="entity counts to run")
    parser.add_argument("--sources", type=int, default=5)
    parser.add_argument("--no-write", action="store_true", help="print only, change no files")
    args = parser.parse_args()

    runs = []
    for size in args.sizes:
        with tempfile.TemporaryDirectory() as work:
            runs.append(score(size, args.sources, args.seed, Path(work)))
        print(f"{size} entities done: {runs[-1]['rows']} rows, "
              f"{runs[-1]['false_pairs']} false-merge pairs")
    table = result_table(runs)
    print(table)
    guard_pairs = []
    for label, seed in (("unseen", args.seed), ("seen", args.seen_seed)):
        with tempfile.TemporaryDirectory() as work:
            off = score(args.sizes[-1], args.sources, seed, Path(work),
                        Config(strong_key_guard=False), write=False)
        if seed == args.seed:
            on = runs[-1]
        else:
            with tempfile.TemporaryDirectory() as work:
                on = score(args.sizes[-1], args.sources, seed, Path(work), write=False)
        guard_pairs.append((f"{seed} ({label})", off, on))
    print(guard_table(guard_pairs))
    print(basis_table(runs[-1]))
    if args.no_write:
        return
    (ROOT / "BENCHMARK.md").write_text(report(runs, args.seed, guard_pairs), encoding="utf-8",
                                       newline="\n")
    print("Wrote BENCHMARK.md" + (" and refreshed README.md" if update_readme(table) else ""))


if __name__ == "__main__":
    main()
