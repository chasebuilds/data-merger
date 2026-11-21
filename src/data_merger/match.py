"""Record matching: blocking, pair scoring, and clustering into three bands."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from rapidfuzz import fuzz
from rapidfuzz.distance import DamerauLevenshtein, Levenshtein

from .config import Config
from .records import Record

# First or last names at least this alike count as the same name with a typo.
NAME_OK = 0.75


@dataclass
class PairScore:
    a: int
    b: int
    score: float
    basis: str


@dataclass
class MatchResult:
    clusters: list[list[int]]
    cluster_scores: list[float | None]  # weakest link that joined the cluster
    cluster_basis: list[str]
    review: list[PairScore]
    candidate_pairs: int
    auto_pairs: int
    skipped_blocks: list[tuple[str, int]] = field(default_factory=list)
    links: list[PairScore] = field(default_factory=list)  # the pairs that joined groups
    near_misses: list[PairScore] = field(default_factory=list)  # just under the review band
    held_back: dict[str, int] = field(default_factory=dict)
    compared: set[tuple[int, int]] = field(default_factory=set)
    decisions_applied: dict[str, int] = field(default_factory=dict)


def _soundex(name: str) -> str:
    codes = {c: d for d, letters in enumerate(
        ("bfpv", "cgjkqsxz", "dt", "l", "mn", "r"), start=1) for c in letters}
    out, prev = name[:1], codes.get(name[:1])
    for ch in name[1:]:
        code = codes.get(ch)
        if code and code != prev:
            out += str(code)
        if ch not in "hw":
            prev = code
    return (out + "000")[:4]


def block_keys(r: Record) -> list[str]:
    """Cheap keys; two records are compared only if they share at least one."""
    keys = []
    if r.email:
        keys.append("e:" + r.email)
    if r.phone:
        keys.append("p:" + r.phone)
    if r.last:
        keys.append(f"n:{_soundex(r.last)}:{r.first[:1]}")
        if r.zip5:
            keys.append(f"z:{r.zip5}:{r.last[:3]}")
    if r.house and r.zip5:
        keys.append(f"a:{r.zip5}:{r.house}")
    if r.company and r.first:
        keys.append(f"c:{r.company[:10]}:{r.first[:1]}")
    return keys


def candidate_pairs(
    records: list[Record], max_block_size: int
) -> tuple[set[tuple[int, int]], list[tuple[str, int]]]:
    blocks: dict[str, list[int]] = defaultdict(list)
    for record in records:
        for key in block_keys(record):
            blocks[key].append(record.idx)
    pairs: set[tuple[int, int]] = set()
    skipped: list[tuple[str, int]] = []
    for key, members in blocks.items():
        if len(members) < 2:
            continue
        # A huge block means the key is not selective (a shared switchboard number, a
        # placeholder email). Comparing all of it would be quadratic, so it is reported instead.
        if len(members) > max_block_size:
            skipped.append((key, len(members)))
            continue
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                pairs.add((a, b))
    return pairs, skipped


def _first_sim(a: str, b: str) -> float | None:
    if not a or not b:
        return None
    if a == b:
        return 1.0
    if len(a) == 1 or len(b) == 1:
        return 0.8 if a[0] == b[0] else 0.0
    return DamerauLevenshtein.normalized_similarity(a, b)


def _last_sim(a: str, b: str) -> float | None:
    if not a or not b:
        return None
    return 1.0 if a == b else DamerauLevenshtein.normalized_similarity(a, b)


def _address_sim(a: Record, b: Record) -> float:
    if not a.street or not b.street:
        # Only a ZIP on one side: weak support, enough for review but never for auto-merge.
        return 0.5 if a.zip5 and a.zip5 == b.zip5 else 0.0
    sim = max(fuzz.ratio(a.street, b.street), 0.95 * fuzz.token_set_ratio(a.street, b.street)) / 100
    if a.house and b.house and a.house != b.house:
        sim = min(sim, 0.4)
    if a.zip5 and b.zip5 and a.zip5 != b.zip5 and not (a.city and a.city == b.city):
        sim *= 0.5
    # A different street is no support at all; it is not "a bit like" the same address.
    return sim if sim >= 0.7 else 0.0


def names_clash(a: Record, b: Record) -> bool:
    """Both first names are spelled out and do not agree: likely two different people."""
    if len(a.first) < 2 or len(b.first) < 2:
        return False
    sim = _first_sim(a.first, b.first)
    return sim is not None and sim < NAME_OK


def score_pair(a: Record, b: Record) -> tuple[float, str]:
    """Score 0..1 that two records are the same real-world entity, plus the reason."""
    first = _first_sim(a.first, b.first)
    last = _last_sim(a.last, b.last)
    has_name = first is not None or last is not None
    first_ok = first is None or first >= NAME_OK
    # "M. Flores" fits both Maria and Margaret Flores, so an initial never confirms a person.
    initial_only = bool(a.first and b.first) and min(len(a.first), len(b.first)) == 1
    last_ok = last is None or last >= NAME_OK
    email_eq = bool(a.email) and a.email == b.email
    email_diff = bool(a.email and b.email) and not email_eq
    phone_eq = bool(a.phone) and a.phone == b.phone
    phone_diff = bool(a.phone and b.phone) and not phone_eq

    if email_eq:
        if not has_name:
            return 0.97, "same email"
        if first_ok and last_ok:
            return 0.99, "same email, names agree"
        if first_ok and phone_eq:
            return 0.92, "same email and phone, last name differs"
        if first_ok:
            return 0.85, "same email, last name differs"
        return 0.72, "same email, first name differs"

    if phone_eq:
        if not has_name:
            return 0.80, "same phone, no name to confirm"
        if first is not None and last is not None and first_ok and last_ok:
            if initial_only:
                return 0.80, "same phone and surname, first name is only an initial"
            return (0.93 if email_diff else 0.95), "same phone, names agree"
        if first is not None and first < 0.5:
            # A shared phone with a different first name is a household or an office.
            return 0.55, "same phone, different first name"
        return 0.74, "same phone, names partly agree"

    if first is None and last is None:
        return 0.0, "no shared evidence"
    if first is not None and last is not None:
        name = 0.4 * first + 0.6 * last
    else:
        name = 0.8 * (first if first is not None else last)

    address = _address_sim(a, b)
    company = fuzz.token_sort_ratio(a.company, b.company) / 100 if a.company and b.company else 0.0
    if company < 0.85:
        company = 0.0
    email_near = email_diff and Levenshtein.distance(a.email, b.email, score_cutoff=1) <= 1
    support, basis = max(
        (address, "name and address"),
        (0.95 * company, "name and company"),
        (0.6 if email_near else 0.0, "name and near-identical email"),
    )
    if support == 0.0:
        return 0.0, "name only"
    score = 0.55 * name + 0.45 * support
    if email_near:
        score += 0.05
    elif email_diff and phone_diff:
        score -= 0.12
    elif email_diff or phone_diff:
        score -= 0.04
    if basis == "name and company" and (email_diff or phone_diff) and not email_near:
        # Two people with one name at one company do exist. With a contact detail that
        # disagrees and nothing else in common, a person decides.
        score = min(score, 0.85)
    if first is None or first < NAME_OK:
        # Same surname at the same address with a different first name is a relative.
        score = min(score, 0.65)
    elif initial_only:
        score = min(score, 0.80)
    return round(max(0.0, min(score, 0.98)), 4), basis


class _UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))
        self.members: dict[int, list[int]] = {}

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def group(self, root: int) -> list[int]:
        return self.members.get(root, [root])

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        merged = self.group(ra) + self.group(rb)
        self.parent[rb] = ra
        self.members.pop(rb, None)
        self.members[ra] = merged


HUMAN_SAME = "human decision: same"
# How far under the review threshold a pair still counts as a near miss worth sampling.
NEAR_MISS_BAND = 0.15


def _keys_contradict(left: list[Record], right: list[Record], basis: str) -> bool:
    """Do two groups, linked only by a fuzzy match, hold contact details that disagree?

    One row often lacks the email or phone that would expose a wrong match. The group it
    already belongs to may have them, so the test is made on the groups, not the two rows.
    """
    def disagree(attr: str) -> bool:
        a = {getattr(r, attr) for r in left} - {""}
        b = {getattr(r, attr) for r in right} - {""}
        return bool(a and b) and not a & b

    email, phone = disagree("email"), disagree("phone")
    if basis.startswith("name and company"):
        return email or phone
    return email and phone


def match_records(
    records: list[Record], config: Config,
    decisions: dict[tuple[int, int], str] | None = None,
) -> MatchResult:
    pairs, skipped = candidate_pairs(records, config.max_block_size)
    decisions = {(min(a, b), max(a, b)): verdict for (a, b), verdict in (decisions or {}).items()}
    forbidden = {pair for pair, verdict in decisions.items() if verdict == "different"}
    scored: dict[tuple[int, int], PairScore] = {}
    near: list[PairScore] = []
    for a, b in pairs:
        score, basis = score_pair(records[a], records[b])
        if score >= config.review_threshold:
            scored[(a, b)] = PairScore(a, b, score, basis)
        elif score >= config.review_threshold - NEAR_MISS_BAND:
            near.append(PairScore(a, b, score, basis))

    uf = _UnionFind(len(records))
    weakest: dict[int, PairScore] = {}
    links: list[PairScore] = []
    demoted: list[PairScore] = []
    held: dict[str, int] = defaultdict(int)

    def join(pair: PairScore) -> None:
        ra, rb = uf.find(pair.a), uf.find(pair.b)
        link = min((weakest.get(ra), weakest.get(rb), pair),
                   key=lambda p: p.score if p else 2.0)
        uf.union(pair.a, pair.b)
        weakest.pop(rb, None)
        weakest[uf.find(pair.a)] = link
        links.append(pair)

    def blocked(pair: PairScore, left: list[int], right: list[int]) -> str:
        """Reason a join must wait for a person, or "" if it may go ahead."""
        if any((min(x, y), max(x, y)) in forbidden for x in left for y in right):
            return "a reviewer marked these as different"
        if len(left) + len(right) > config.max_cluster_size:
            return f"would make a group of more than {config.max_cluster_size} rows"
        if config.one_per_source and {records[x].source_file for x in left} & {
                records[y].source_file for y in right}:
            return "would put two rows from one file in one record"
        # Chained merges can glue two different people together through a third record.
        if any(names_clash(records[x], records[y]) for x in left for y in right):
            return "would chain conflicting records"
        if config.strong_key_guard and pair.basis.startswith("name and") and _keys_contradict(
                [records[x] for x in left], [records[y] for y in right], pair.basis):
            return "the two groups hold different contact details"
        return ""

    applied = {"same": 0, "different": len(forbidden)}
    for (a, b), verdict in sorted(decisions.items()):
        if verdict == "same" and uf.find(a) != uf.find(b):
            join(PairScore(a, b, 1.0, HUMAN_SAME))
            applied["same"] += 1

    auto = sorted(
        (p for p in scored.values() if p.score >= config.auto_threshold),
        key=lambda p: (-p.score, p.a, p.b),
    )
    for pair in auto:
        ra, rb = uf.find(pair.a), uf.find(pair.b)
        if ra == rb:
            continue
        reason = blocked(pair, uf.group(ra), uf.group(rb))
        if reason:
            held[reason] += 1
            demoted.append(PairScore(pair.a, pair.b, pair.score,
                                     f"{pair.basis}; held back, {reason}"))
            continue
        join(pair)

    grouped: dict[int, list[int]] = defaultdict(list)
    for record in records:
        grouped[uf.find(record.idx)].append(record.idx)
    roots = sorted(grouped, key=lambda r: min(grouped[r]))
    clusters = [sorted(grouped[r]) for r in roots]
    scores = [weakest[r].score if r in weakest else None for r in roots]
    basis = [weakest[r].basis if r in weakest else "" for r in roots]

    # One review row per pair of merged records: the strongest candidate between them.
    # A pair a reviewer already ruled on is not asked again.
    decided = {(uf.find(a), uf.find(b)) for a, b in forbidden}
    decided |= {(b, a) for a, b in decided}
    best: dict[tuple[int, int], PairScore] = {}
    middle = [p for p in scored.values() if p.score < config.auto_threshold] + demoted
    for pair in middle:
        ra, rb = uf.find(pair.a), uf.find(pair.b)
        if ra == rb or (ra, rb) in decided:
            continue
        key = (min(ra, rb), max(ra, rb))
        if key not in best or pair.score > best[key].score:
            best[key] = pair
    review = sorted(best.values(), key=lambda p: (-p.score, p.a, p.b))
    near = sorted((p for p in near if uf.find(p.a) != uf.find(p.b)),
                  key=lambda p: (-p.score, p.a, p.b))
    auto_pairs = sum(len(c) * (len(c) - 1) // 2 for c in clusters)
    return MatchResult(clusters, scores, basis, review, len(pairs), auto_pairs, skipped,
                       links, near, dict(held), pairs, applied)
