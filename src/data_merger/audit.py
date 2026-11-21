"""Measure match quality on a real job from a labeled sample.

Benchmark numbers come from generated data and do not transfer to a client's files. The
Audit sheet holds a random sample of merges; once a person labels it, this module turns
the labels into precision per match reason, with an interval that shows how much a small
sample can be trusted.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from openpyxl import load_workbook

from .workbook import AUDIT_LABEL_HEADER

_SAME = {"same", "s", "yes", "y"}
_DIFFERENT = {"different", "d", "diff", "no", "n"}


@dataclass
class Stratum:
    name: str
    size: int  # links of this kind in the whole run
    sampled: int
    labeled: int
    same: int

    @property
    def share_same(self) -> float | None:
        return self.same / self.labeled if self.labeled else None

    @property
    def interval(self) -> tuple[float, float] | None:
        return wilson(self.same, self.labeled) if self.labeled else None


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval. Unlike the plain formula it behaves at 0% and 100%."""
    p = successes / n
    centre = p + z * z / (2 * n)
    spread = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    denom = 1 + z * z / n
    return max(0.0, (centre - spread) / denom), min(1.0, (centre + spread) / denom)


def read_audit(path: str | Path) -> list[Stratum]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        if "Audit" not in workbook.sheetnames:
            raise ValueError(
                f"{Path(path).name} has no Audit sheet. Rerun the merge with --audit-sample 30."
            )
        rows = list(workbook["Audit"].iter_rows(values_only=True))
    finally:
        workbook.close()
    header = [str(h or "") for h in rows[0]]
    name_col, size_col = header.index("stratum"), header.index("stratum_size")
    label_col = header.index(AUDIT_LABEL_HEADER)
    strata: dict[str, Stratum] = {}
    for row in rows[1:]:
        name = str(row[name_col])
        stratum = strata.setdefault(name, Stratum(name, int(float(str(row[size_col]))), 0, 0, 0))
        stratum.sampled += 1
        label = str(row[label_col] or "").strip().lower()
        if label in _SAME | _DIFFERENT:
            stratum.labeled += 1
            stratum.same += label in _SAME
    return list(strata.values())


def audit_report(strata: list[Stratum]) -> str:
    lines = ["Match quality from the labeled Audit sample", ""]
    merged = [s for s in strata if s.name.startswith("merged:")]
    for stratum in strata:
        kind = "correct merges" if stratum.name.startswith("merged:") else "real matches left out"
        lines.append(f"{stratum.name}")
        lines.append(f"  links of this kind in the run: {stratum.size}, sampled: "
                     f"{stratum.sampled}, labeled: {stratum.labeled}")
        if stratum.interval is not None and stratum.share_same is not None:
            low, high = stratum.interval
            lines.append(f"  {kind}: {stratum.same} of {stratum.labeled} "
                         f"({100 * stratum.share_same:.1f}%, 95% interval "
                         f"{100 * low:.1f}% to {100 * high:.1f}%)")
        else:
            lines.append("  not labeled yet")
    done = [s for s in merged if s.labeled]
    if done and len(done) == len(merged):
        total = sum(s.size for s in merged)
        estimate = sum(s.size * s.same / s.labeled for s in done) / total
        lines += ["", f"Estimated share of all {total} merge links that are correct: "
                      f"{100 * estimate:.1f}% (each reason weighted by how often it was used)."]
    elif merged:
        lines += ["", "No overall estimate: label at least one row for every merge reason."]
    lines += ["", "A link is one pair of rows that joined two groups. The near-miss stratum only "
                  "covers pairs that were compared and scored just under the review band; "
                  "matches the tool never compared are not in this sample."]
    return "\n".join(lines)
