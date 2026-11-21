"""Conflict resolution: pick one value per column and keep every losing value."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date

from . import normalize as nz
from .config import Config
from .records import Record

ADDRESS_GROUP = ("street", "city", "state", "postal_code")


@dataclass
class Conflict:
    merged_id: str
    column: str
    kept_value: object
    kept_source: str
    lost_value: object
    lost_sources: str
    rule: str


@dataclass
class Lineage:
    merged_id: str
    column: str
    value: object
    source_file: str
    source_row: int
    agreeing_rows: int


def _compare_key(column: str, value: object) -> str:
    """Two values with the same key are the same fact written differently, not a conflict."""
    text = str(value)
    if column == "street":
        return nz.street_key(text)
    if column == "company":
        return nz.company_key(text)
    if column == "phone":
        return nz.phone_digits(text)
    if column == "postal_code":
        return text[:5]
    if column == "balance" and isinstance(value, float):
        return f"{value:.2f}"
    return nz.squash(text) if column != "email" else text


def _pick(candidates: list[Record], column: str, rule: str, priority: dict[str, int]) -> Record:
    def order(r: Record) -> tuple[int, int]:
        return (priority.get(r.source_file, len(priority)), r.idx)

    if rule == "most_recent":
        return min(candidates, key=lambda r: (-(r.updated or date.min).toordinal(), *order(r)))
    if rule == "most_common":
        def vote(r: Record) -> str:
            value = r.values[column]
            return nz.first_name_key(str(value)) if column == "first_name" else _compare_key(
                column, value)

        votes = Counter(vote(r) for r in candidates)
        return min(candidates,
                   key=lambda r: (-votes[vote(r)], -len(str(r.values[column])), *order(r)))
    if rule == "most_complete":
        return min(candidates, key=lambda r: (-len(str(r.values[column])), *order(r)))
    return min(candidates, key=order)


def resolve_cluster(
    merged_id: str, members: list[Record], columns: list[str], config: Config,
    priority: dict[str, int],
) -> tuple[dict[str, object], list[Conflict], list[Lineage]]:
    merged: dict[str, object] = {}
    conflicts: list[Conflict] = []
    lineage: list[Lineage] = []
    address_winner: Record | None = None

    for column in columns:
        candidates = [r for r in members if r.values.get(column) not in ("", None)]
        if not candidates:
            merged[column] = ""
            continue
        rule = config.rule_for(column)
        if column == "updated_at":
            winner = max(candidates, key=lambda r: (r.updated or date.min, -r.idx))
            rule = "most_recent"
        elif column in ADDRESS_GROUP:
            # An address is one fact. Taking the street from one source and the city from
            # another would invent an address nobody ever had, so the parts travel together.
            if address_winner is None:
                with_street = [r for r in members if r.values.get("street")]
                lead = with_street or candidates
                address_winner = _pick(lead, "street" if with_street else column,
                                       config.rule_for("street"), priority)
            same_place = [
                r for r in candidates
                if r is address_winner or (r.street and r.street == address_winner.street)
                or not address_winner.street
            ]
            if address_winner in candidates:
                winner = address_winner
            elif same_place:
                winner = _pick(same_place, column, rule, priority)
            else:
                merged[column] = ""
                continue
            rule = config.rule_for("street")
        else:
            winner = _pick(candidates, column, rule, priority)

        value = winner.values[column]
        merged[column] = value
        kept_key = _compare_key(column, value)
        agreeing = [r for r in candidates if _compare_key(column, r.values[column]) == kept_key]
        lineage.append(Lineage(merged_id, column, value, winner.source_file, winner.source_row,
                               len(agreeing)))
        losers: dict[str, list[Record]] = {}
        # The merged date is simply the newest one; older dates are not a disagreement.
        for record in candidates if column != "updated_at" else []:
            key = _compare_key(column, record.values[column])
            if key != kept_key:
                losers.setdefault(key, []).append(record)
        for group in losers.values():
            conflicts.append(Conflict(
                merged_id, column, value, winner.ref, group[0].values[column],
                "; ".join(r.ref for r in group), rule,
            ))
    return merged, conflicts, lineage
