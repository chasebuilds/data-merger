"""Schema alignment: map each file's headers onto one canonical schema."""

from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz

from .normalize import squash

# Canonical column -> value kind used for type harmonization.
CANONICAL: dict[str, str] = {
    "first_name": "name",
    "last_name": "name",
    "email": "email",
    "phone": "phone",
    "company": "text",
    "street": "street",
    "city": "name",
    "state": "state",
    "postal_code": "postal",
    "balance": "money",
    "updated_at": "date",
}

# Headers that map to one cell holding several canonical columns.
COMPOSITE = ("full_name", "full_address")
IGNORE = "ignore"

SYNONYMS: dict[str, tuple[str, ...]] = {
    "first_name": ("first name", "fname", "first", "given name", "forename"),
    "last_name": ("last name", "lname", "last", "surname", "family name"),
    "full_name": (
        "name", "full name", "customer name", "contact name", "contact", "customer",
        "client name", "subscriber name", "account name",
    ),
    "email": (
        "email", "e mail", "email address", "e mail address", "contact email", "email addr",
        "mail", "primary email",
    ),
    "phone": (
        "phone", "phone number", "phone no", "tel", "telephone", "mobile", "cell",
        "cell phone", "mobile phone", "contact number", "phone 1",
    ),
    "company": (
        "company", "company name", "organization", "organisation", "org", "employer",
        "business", "business name", "account",
    ),
    "street": (
        "street", "street address", "address", "address 1", "address line 1",
        "billing address", "mailing address", "addr",
    ),
    "full_address": ("full address", "shipping address", "complete address"),
    "city": ("city", "town", "city name"),
    "state": ("state", "st", "province", "region", "state code"),
    "postal_code": ("postal code", "zip", "zip code", "zipcode", "postcode", "postal"),
    "balance": (
        "balance", "balance due", "amount due", "outstanding", "outstanding balance",
        "account balance", "amount owed", "open balance",
    ),
    "updated_at": (
        "updated at", "updated", "last updated", "last modified", "modified",
        "modified date", "last update", "date modified", "last activity",
    ),
}

FUZZY_CUTOFF = 86.0


@dataclass
class ColumnMapping:
    source_file: str
    header: str
    target: str  # canonical name, composite name, "extra:<header>" or "ignore"
    method: str  # synonym | fuzzy | config | unmapped
    score: float
    note: str = ""


def _best_target(header: str) -> tuple[str, str, float]:
    key = squash(header)
    if not key:
        return "", "unmapped", 0.0
    for target, names in SYNONYMS.items():
        if key in names or key.replace(" ", "") == target.replace("_", ""):
            return target, "synonym", 100.0
    best_target, best_score = "", 0.0
    for target, names in SYNONYMS.items():
        for name in names:
            # Short synonyms ("st", "org") match too many unrelated headers by chance.
            if len(name) < 4:
                continue
            score = max(fuzz.ratio(key, name), fuzz.token_sort_ratio(key, name))
            if score > best_score:
                best_target, best_score = target, score
    if best_score >= FUZZY_CUTOFF:
        return best_target, "fuzzy", round(best_score, 1)
    return "", "unmapped", round(best_score, 1)


def map_headers(
    source_file: str, headers: list[str], overrides: dict[str, str] | None = None
) -> list[ColumnMapping]:
    """Pick a target for every header. Config overrides win; duplicates lose to the best score."""
    overrides = {squash(k): v for k, v in (overrides or {}).items()}
    valid = set(CANONICAL) | set(COMPOSITE) | {IGNORE}
    mappings: list[ColumnMapping] = []
    for header in headers:
        forced = overrides.get(squash(header))
        if forced is not None:
            if forced not in valid:
                raise ValueError(
                    f"Config maps '{header}' in {source_file} to unknown column '{forced}'. "
                    f"Use one of: {', '.join(sorted(valid))}"
                )
            mappings.append(ColumnMapping(source_file, header, forced, "config", 100.0))
            continue
        target, method, score = _best_target(header)
        mappings.append(
            ColumnMapping(source_file, header, target or f"extra:{header}", method, score)
        )

    taken: dict[str, ColumnMapping] = {}
    rank = {"config": 3, "synonym": 2, "fuzzy": 1, "unmapped": 0}
    for mapping in mappings:
        if mapping.target == IGNORE or mapping.target.startswith("extra:"):
            continue
        current = taken.get(mapping.target)
        if current is None:
            taken[mapping.target] = mapping
            continue
        new_wins = (rank[mapping.method], mapping.score) > (rank[current.method], current.score)
        loser = current if new_wins else mapping
        if new_wins:
            taken[mapping.target] = mapping
        loser.note = f"also looked like {loser.target}, but '{taken[loser.target].header}' won"
        loser.target, loser.method = f"extra:{loser.header}", "unmapped"
    for mapping in mappings:
        if mapping.target.startswith("extra:") and not mapping.note:
            mapping.note = "no canonical match, carried through under its own name"
    return mappings
