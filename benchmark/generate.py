"""Seeded generator: a truth table of people, split into messy overlapping source files.

The true entity id never appears in a source file. It is written to truth.csv, which only
the scorer reads.

    python -m benchmark.generate --entities 40 --sources 3 --seed 7 --out some_folder
"""

from __future__ import annotations

import argparse
import csv
import random
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path

from openpyxl import Workbook

FIRST = [
    "Robert", "William", "James", "Michael", "Elizabeth", "Katherine", "Jennifer", "Margaret",
    "Thomas", "Richard", "Charles", "Daniel", "Matthew", "Christopher", "Anthony", "Steven",
    "Joseph", "Patricia", "Susan", "Deborah", "Samuel", "Benjamin", "Nicholas", "Andrew",
    "Jonathan", "Gregory", "Timothy", "Kenneth", "Edward", "Rebecca", "Abigail", "Victoria",
    "Maria", "Linda", "Karen", "Nancy", "Laura", "Emily", "Hannah", "Olivia", "Sophia", "Grace",
    "Carlos", "Luis", "Diego", "Marcus", "Ethan", "Noah", "Liam", "Owen", "Henry", "Oscar",
    "Priya", "Anita", "Wei", "Mei", "Omar", "Leila", "Ivan", "Nina", "Paul", "Mark", "Eric",
    "Kevin", "Brian", "Jason", "Ryan", "Adam", "Sean", "Kyle", "Rachel", "Megan", "Amber",
    "Heather", "Tiffany", "Crystal", "Brenda", "Diane", "Julie", "Carol",
]
NICKS = {
    "Robert": ["Bob", "Rob"], "William": ["Bill", "Will"], "James": ["Jim"], "Michael": ["Mike"],
    "Elizabeth": ["Liz", "Beth"], "Katherine": ["Kate", "Kathy"], "Jennifer": ["Jen", "Jenny"],
    "Margaret": ["Maggie", "Peggy"], "Thomas": ["Tom"], "Richard": ["Rick", "Rich"],
    "Charles": ["Charlie", "Chuck"], "Daniel": ["Dan"], "Matthew": ["Matt"],
    "Christopher": ["Chris"], "Anthony": ["Tony"], "Steven": ["Steve"], "Joseph": ["Joe"],
    "Patricia": ["Pat", "Patty"], "Susan": ["Sue"], "Deborah": ["Deb", "Debbie"],
    "Samuel": ["Sam"], "Benjamin": ["Ben"], "Nicholas": ["Nick"], "Andrew": ["Andy"],
    "Jonathan": ["Jon"], "Gregory": ["Greg"], "Timothy": ["Tim"], "Kenneth": ["Ken"],
    "Edward": ["Ed"], "Rebecca": ["Becky"], "Abigail": ["Abby"], "Victoria": ["Vicky"],
}
LAST = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez",
    "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor",
    "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez",
    "Clark", "Ramirez", "Lewis", "Robinson", "Walker", "Young", "Allen", "King", "Wright",
    "Scott", "Torres", "Nguyen", "Hill", "Flores", "Green", "Adams", "Nelson", "Baker", "Hall",
    "Rivera", "Campbell", "Mitchell", "Carter", "Roberts", "Gomez", "Phillips", "Evans",
    "Turner", "Diaz", "Parker", "Cruz", "Edwards", "Collins", "Reyes", "Stewart", "Morris",
    "Morales", "Murphy", "Cook", "Rogers", "Gutierrez", "Ortiz", "Morgan", "Cooper", "Peterson",
    "Bailey", "Reed", "Kelly", "Howard", "Ramos", "Kim", "Cox", "Ward", "Richardson", "Watson",
    "Brooks", "Chavez", "Wood", "James", "Bennett", "Gray", "Mendoza", "Ruiz", "Hughes", "Price",
    "Alvarez", "Castillo", "Sanders", "Patel", "Myers", "Long", "Ross", "Foster", "Jimenez",
    "McDonald", "O'Brien", "Sullivan", "Fitzgerald", "Kowalski", "Petrov", "Schneider", "Okafor",
    "Tanaka", "Lindqvist", "Hoffman", "Abernathy", "Castellano", "Whitaker", "Delacroix",
]
STREETS = [
    "Main", "Oak", "Maple", "Cedar", "Elm", "Pine", "Walnut", "Washington", "Lake", "Hill",
    "Park", "Sunset", "Lincoln", "Jackson", "Church", "River", "Spring", "Highland", "Franklin",
    "Chestnut", "Willow", "Meadow", "Forest", "Birch", "Cherry", "Dogwood", "Hickory", "Madison",
    "Jefferson", "Adams", "Ridge", "Valley", "Prospect", "Summit", "Orchard", "Mill", "Bridge",
]
STREET_TYPES = [("Street", "St"), ("Avenue", "Ave"), ("Road", "Rd"), ("Drive", "Dr"),
                ("Lane", "Ln"), ("Court", "Ct"), ("Boulevard", "Blvd")]
CITIES = [
    ("Springfield", "Illinois", "IL", "627"), ("Columbus", "Ohio", "OH", "432"),
    ("Dayton", "Ohio", "OH", "454"), ("Madison", "Wisconsin", "WI", "537"),
    ("Austin", "Texas", "TX", "787"), ("Denver", "Colorado", "CO", "802"),
    ("Portland", "Oregon", "OR", "972"), ("Raleigh", "North Carolina", "NC", "276"),
    ("Tampa", "Florida", "FL", "336"), ("Boise", "Idaho", "ID", "837"),
    ("Albany", "New York", "NY", "122"), ("Boston", "Massachusetts", "MA", "021"),
    ("Tucson", "Arizona", "AZ", "857"), ("Omaha", "Nebraska", "NE", "681"),
    ("Richmond", "Virginia", "VA", "232"), ("Lexington", "Kentucky", "KY", "405"),
    ("Tulsa", "Oklahoma", "OK", "741"), ("Fresno", "California", "CA", "937"),
    ("Hartford", "Connecticut", "CT", "061"), ("Savannah", "Georgia", "GA", "314"),
]
COMPANY_A = ["Northwind", "Bluebird", "Ironwood", "Harbor", "Summit", "Cobalt", "Evergreen",
             "Lakeside", "Redstone", "Silverline", "Brightpath", "Keystone", "Pioneer", "Granite",
             "Clearwater", "Foxglove", "Maplewood", "Stonebridge", "Tidewater", "Copperfield"]
COMPANY_B = ["Supply", "Logistics", "Dental", "Consulting", "Hardware", "Bakery", "Roofing",
             "Design", "Plumbing", "Marketing", "Landscaping", "Realty", "Printing", "Fitness",
             "Accounting", "Auto Repair", "Catering", "Electric", "Pharmacy", "Outfitters"]
COMPANY_SUFFIX = ["Inc", "LLC", "Co", "Ltd", "Corp", "Group"]
DOMAINS = ["example.com", "example.org", "example.net", "mail.example", "post.example"]
TODAY = date(2026, 11, 1)


@dataclass
class Entity:
    entity_id: str
    first: str
    last: str
    email: str
    phone: str  # ten digits
    company: str
    number: str
    street: str
    street_type: tuple[str, str]
    unit: str
    city: tuple[str, str, str, str]
    zip_code: str
    balance: float
    updated: date
    kind: str = "plain"


def _phone(rng: random.Random) -> str:
    # Exchange 555 keeps every generated number fictional.
    return f"{rng.randint(201, 989)}555{rng.randint(0, 9999):04d}"


def _email(rng: random.Random, first: str, last: str, used: set[str]) -> str:
    f, la = first.lower(), last.lower().replace("'", "")
    while True:
        local = rng.choice([f"{f}.{la}", f"{f[0]}{la}", f"{f}{la[0]}", f"{f}_{la}", f"{la}.{f}"])
        if rng.random() < 0.6:
            local += str(rng.randint(1, 999))
        email = f"{local}@{rng.choice(DOMAINS)}"
        if email not in used:
            used.add(email)
            return email


def _address(rng: random.Random):
    city = rng.choice(CITIES)
    return (str(rng.randint(10, 9899)), rng.choice(STREETS), rng.choice(STREET_TYPES),
            rng.choice(["", "", "", f"Apt {rng.randint(1, 40)}", f"Suite {rng.randint(100, 900)}"]),
            city, city[3] + f"{rng.randint(0, 99):02d}")


def make_entities(count: int, rng: random.Random) -> list[Entity]:
    """Truth table. About 1 in 10 entities is a deliberate look-alike of another one."""
    entities: list[Entity] = []
    used: set[str] = set()
    household_names: dict[tuple[str, str, str], set[str]] = {}
    for index in range(count):
        first, last = rng.choice(FIRST), rng.choice(LAST)
        number, street, street_type, unit, city, zip_code = _address(rng)
        phone = _phone(rng)
        kind = "plain"
        roll = rng.random()
        if entities and roll < 0.06:
            # Household: same surname, same address, usually the same phone.
            base = rng.choice(entities)
            last, kind = base.last, "household"
            number, street, unit = base.number, base.street, base.unit
            street_type = base.street_type
            city, zip_code = base.city, base.zip_code
            # Two people with the same full name, address and phone cannot be told apart by
            # anyone, so a household never repeats a first name.
            taken = household_names.setdefault((base.number, base.street, base.zip_code),
                                               {base.first})
            first = rng.choice([n for n in FIRST if n not in taken])
            taken.add(first)
            if rng.random() < 0.7:
                phone = base.phone
        elif entities and roll < 0.09:
            # Same full name, different person, different city.
            base = rng.choice(entities)
            first, last, kind = base.first, base.last, "namesake"
        elif entities and roll < 0.10:
            # Same full name and ZIP, different street: the hardest look-alike.
            base = rng.choice(entities)
            first, last, kind = base.first, base.last, "namesake_same_zip"
            city, zip_code = base.city, base.zip_code
        company = f"{rng.choice(COMPANY_A)} {rng.choice(COMPANY_B)} {rng.choice(COMPANY_SUFFIX)}"
        entities.append(Entity(
            f"E{index + 1:06d}", first, last, _email(rng, first, last, used), phone, company,
            number, street, street_type, unit, city, zip_code,
            round(rng.uniform(0, 5000), 2), TODAY - timedelta(days=rng.randint(0, 120)), kind,
        ))
    return entities


def _typo(rng: random.Random, word: str) -> str:
    if len(word) < 5:
        return word
    i = rng.randint(1, len(word) - 2)
    choice = rng.random()
    if choice < 0.4:
        return word[:i] + word[i + 1] + word[i] + word[i + 2:]
    if choice < 0.7:
        return word[:i] + word[i + 1:]
    return word[:i] + rng.choice("aeiourstln") + word[i + 1:]


def _fmt_phone(rng: random.Random, digits: str) -> str:
    a, b, c = digits[:3], digits[3:6], digits[6:]
    return rng.choice([
        f"({a}) {b}-{c}", f"{a}-{b}-{c}", f"{a}.{b}.{c}", digits, f"+1 {a} {b} {c}",
        f"1-{a}-{b}-{c}", f"{a} {b} {c}",
    ])


def _fmt_date(rng: random.Random, value: date, style: str) -> str:
    if style == "us":
        return value.strftime("%m/%d/%Y")
    if style == "text":
        return value.strftime("%b %d, %Y")
    return value.isoformat()


def _street_line(rng: random.Random, e: Entity, drop_unit: bool = False) -> str:
    line = f"{e.number} {e.street} {rng.choice(e.street_type)}"
    if rng.random() < 0.15:
        line = line.upper()
    if e.unit and not drop_unit:
        unit = e.unit if rng.random() < 0.7 else e.unit.replace("Apt ", "#").replace("Suite", "Ste")
        line += f" {unit}" if rng.random() < 0.5 else f", {unit}"
    return line


def _company(rng: random.Random, name: str) -> str:
    base, _, suffix = name.rpartition(" ")
    return rng.choice([name, base, f"{base}, {suffix}.", name.upper(), f"{base} {suffix}"])


@dataclass
class Appearance:
    """One entity as one source row sees it, before that source's formatting is applied."""
    entity: Entity
    first: str
    last: str
    email: str
    phone: str
    has_address: bool
    as_of: date
    stale: set[str]


def _appear(rng: random.Random, e: Entity, old_emails: set[str]) -> tuple[Appearance, Entity]:
    """Apply typos, nicknames, missing fields and stale values to one appearance."""
    first, last, shown, stale = e.first, e.last, e, set()
    roll = rng.random()
    if roll < 0.18 and e.first in NICKS:
        first = rng.choice(NICKS[e.first])
    elif roll < 0.21:
        first = e.first[0] + "."
    elif roll < 0.25:
        first = _typo(rng, first)
    if rng.random() < 0.05:
        last = _typo(rng, last)
    if rng.random() < 0.10:
        first, last = first.upper(), last.upper()

    email = e.email
    if rng.random() < 0.08:
        email = _email(rng, e.first, e.last, old_emails)
        stale.add("email")
    elif rng.random() < 0.02:
        local, _, domain = email.partition("@")
        email = _typo(rng, local) + "@" + domain
    if rng.random() < 0.25:
        email = email.upper() if rng.random() < 0.3 else email.title()
    if rng.random() < 0.10:
        email = ""

    phone = e.phone
    if rng.random() < 0.06:
        phone = _phone(rng)
        stale.add("phone")
    if rng.random() < 0.20:
        phone = ""

    if rng.random() < 0.06:
        number, street, street_type, unit, city, zip_code = _address(rng)
        shown = replace(e, number=number, street=street, street_type=street_type, unit=unit,
                        city=city, zip_code=zip_code)
        stale.add("address")
    has_address = rng.random() > 0.12
    # A source holding an out-of-date value was last touched before the entity changed.
    as_of = e.updated - timedelta(days=rng.randint(200, 900)) if stale else (
        e.updated - timedelta(days=rng.choice([0, 0, 0, rng.randint(1, 60)])))
    return Appearance(shown, first, last, email, phone, has_address, as_of, stale), shown


SOURCES = [
    ("crm_export.csv", ["First Name", "Last Name", "E-mail", "Phone", "Company", "Street", "City",
                        "State", "ZIP", "Last Modified"]),
    ("billing_export.xlsx", ["Customer Name", "Contact Email", "Tel", "Billing Address", "City",
                             "ST", "Postal Code", "Balance Due", "Last Updated"]),
    ("mailing_list.csv", ["full_name", "email_address", "mobile", "zip", "subscribed_on"]),
    ("support_desk.csv", ["Contact", "Email Addr", "Phone Number", "Organization", "City",
                          "Updated", "Open Tickets"]),
    ("webshop_accounts.xlsx", ["fname", "lname", "e_mail", "phone_no", "Shipping Address",
                               "modified"]),
]


def _row(rng: random.Random, source: int, ap: Appearance) -> list[object]:
    e = ap.entity
    phone = _fmt_phone(rng, ap.phone) if ap.phone else ""
    street = _street_line(rng, e) if ap.has_address else ""
    company = _company(rng, e.company) if rng.random() > 0.25 else ""
    if source == 0:
        return [ap.first, ap.last, ap.email, phone, company, street,
                e.city[0] if street else "", (e.city[2] if rng.random() < 0.8 else e.city[1])
                if street else "", e.zip_code if street else "", _fmt_date(rng, ap.as_of, "us")]
    if source == 1:
        balance = f"${e.balance:,.2f}" if rng.random() < 0.7 else f"{e.balance:.2f}"
        return [f"{ap.last}, {ap.first}", ap.email, phone, street, e.city[0] if street else "",
                e.city[2] if street else "", e.zip_code if street else "", balance,
                _fmt_date(rng, ap.as_of, "iso")]
    if source == 2:
        # A mailing list always has an email; if this appearance lost it, fall back to the
        # entity's real one so the row stays a plausible mailing-list row.
        return [f"{ap.first} {ap.last}", ap.email or e.email, phone,
                e.zip_code if rng.random() < 0.8 else "",
                _fmt_date(rng, ap.as_of - timedelta(days=rng.randint(30, 900)), "us")]
    if source == 3:
        return [f"{ap.first} {ap.last}", ap.email, phone, company, e.city[0],
                _fmt_date(rng, ap.as_of, "text"), rng.randint(0, 4)]
    full = f"{_street_line(rng, e)}, {e.city[0]}, {e.city[2]} {e.zip_code}" if street else ""
    return [ap.first, ap.last, ap.email, phone, full, _fmt_date(rng, ap.as_of, "iso")]


def generate(out_dir: Path, entities: int = 200, sources: int = 4, seed: int = 7,
             presence: float = 0.55, write_truth: bool = True) -> dict[str, object]:
    """Write source files (and truth.csv) to out_dir. Returns paths and the truth mapping."""
    if not 3 <= sources <= len(SOURCES):
        raise ValueError(f"sources must be between 3 and {len(SOURCES)}")
    rng = random.Random(seed)
    people = make_entities(entities, rng)
    old_emails = {p.email for p in people}
    tables: list[list[list[object]]] = [[] for _ in range(sources)]
    truth: list[tuple[str, int, str, str]] = []
    current: dict[str, dict[str, bool]] = {}

    for person in people:
        chosen = [s for s in range(sources) if rng.random() < presence] or [rng.randrange(sources)]
        for source in chosen:
            # A few entities are entered twice in the same file.
            for _ in range(2 if rng.random() < 0.03 else 1):
                appearance, _ = _appear(rng, person, old_emails)
                row = _row(rng, source, appearance)
                tables[source].append(row)
                truth.append((SOURCES[source][0], len(tables[source]) + 1, person.entity_id,
                              ",".join(sorted(appearance.stale))))
                seen = current.setdefault(person.entity_id, {"email": False, "phone": False})
                seen["email"] |= bool(appearance.email) and "email" not in appearance.stale \
                    and appearance.email.lower() == person.email
                seen["phone"] |= bool(appearance.phone) and "phone" not in appearance.stale

    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for source in range(sources):
        name, headers = SOURCES[source]
        path = out_dir / name
        if name.endswith(".xlsx"):
            workbook = Workbook(write_only=True)
            sheet = workbook.create_sheet("Export")
            sheet.append(headers)
            for row in tables[source]:
                sheet.append(row)
            workbook.save(path)
        else:
            with open(path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(headers)
                writer.writerows(tables[source])
        paths.append(path)

    if write_truth:
        with open(out_dir / "truth.csv", "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["source_file", "source_row", "entity_id", "stale_fields"])
            writer.writerows(truth)
        with open(out_dir / "entities.csv", "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["entity_id", "kind", "first", "last", "email", "phone",
                             "current_email_in_sources", "current_phone_in_sources"])
            for p in people:
                seen = current.get(p.entity_id, {})
                writer.writerow([p.entity_id, p.kind, p.first, p.last, p.email, p.phone,
                                 int(seen.get("email", False)), int(seen.get("phone", False))])
    return {
        "paths": paths,
        "truth": {(f, r): e for f, r, e, _ in truth},
        "entities": {p.entity_id: p for p in people},
        "current": current,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--entities", type=int, default=200)
    parser.add_argument("--sources", type=int, default=4, help="3 to 5 source files")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=Path, default=Path("benchmark/data"))
    parser.add_argument("--no-truth", action="store_true", help="do not write truth.csv")
    args = parser.parse_args()
    made = generate(args.out, args.entities, args.sources, args.seed,
                    write_truth=not args.no_truth)
    print(f"Wrote {len(made['paths'])} source files to {args.out}")


if __name__ == "__main__":
    main()
