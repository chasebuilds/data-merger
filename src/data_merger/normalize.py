"""Type harmonization: turn each source's formats into one comparable form.

Every function returns "" for empty input and never raises on bad input:
a value that cannot be parsed is returned trimmed and reported by `normalize_value`.
"""

from __future__ import annotations

import re
from datetime import date, datetime

_WS = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")

NICKNAMES = {
    "abby": "abigail", "al": "albert", "alex": "alexander", "andy": "andrew",
    "angie": "angela", "barb": "barbara", "becky": "rebecca", "ben": "benjamin",
    "beth": "elizabeth", "bill": "william", "billy": "william", "bob": "robert",
    "bobby": "robert", "cathy": "catherine", "charlie": "charles", "chris": "christopher",
    "chuck": "charles", "cindy": "cynthia", "dan": "daniel", "danny": "daniel",
    "dave": "david", "deb": "deborah", "debbie": "deborah", "don": "donald",
    "doug": "douglas", "ed": "edward", "eddie": "edward", "fred": "frederick",
    "greg": "gregory", "jeff": "jeffrey", "jen": "jennifer", "jenny": "jennifer",
    "jim": "james", "jimmy": "james", "joe": "joseph", "joey": "joseph",
    "jon": "jonathan", "josh": "joshua", "kate": "katherine", "kathy": "katherine",
    "katie": "katherine", "ken": "kenneth", "kim": "kimberly", "larry": "lawrence",
    "liz": "elizabeth", "maggie": "margaret", "matt": "matthew", "meg": "margaret",
    "mike": "michael", "nick": "nicholas", "pam": "pamela", "pat": "patricia",
    "patty": "patricia", "peggy": "margaret", "pete": "peter", "rich": "richard",
    "rick": "richard", "rob": "robert", "ron": "ronald", "sam": "samuel",
    "sandy": "sandra", "steve": "steven", "stephen": "steven", "sue": "susan",
    "ted": "theodore", "tim": "timothy", "tom": "thomas", "tommy": "thomas",
    "tony": "anthony", "vicky": "victoria", "will": "william", "zach": "zachary",
}

STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
    "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "west virginia": "WV", "wisconsin": "WI",
    "wyoming": "WY", "district of columbia": "DC",
}

_STREET_ABBR = {
    "street": "st", "avenue": "ave", "av": "ave", "road": "rd", "drive": "dr",
    "boulevard": "blvd", "lane": "ln", "court": "ct", "place": "pl", "highway": "hwy",
    "parkway": "pkwy", "circle": "cir", "terrace": "ter", "north": "n", "south": "s",
    "east": "e", "west": "w", "apartment": "apt", "unit": "apt", "suite": "apt",
    "ste": "apt", "no": "apt",
}

_COMPANY_NOISE = {
    "inc", "incorporated", "llc", "ltd", "limited", "corp", "corporation", "co",
    "company", "the", "and", "plc", "group", "llp", "lp",
}

_TITLES = {"mr", "mrs", "ms", "miss", "dr", "prof"}
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}
_COMPASS = {"NE", "NW", "SE", "SW", "PO"}
_PARTICLES = {"van", "von", "de", "del", "della", "la", "le", "da", "di", "st", "mac"}

_DATE_FORMATS_US = (
    "%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%d-%b-%Y", "%d %b %Y",
    "%b %d, %Y", "%B %d, %Y", "%d %B %Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
    "%m/%d/%Y %H:%M", "%Y%m%d",
)
_DATE_FORMATS_DAYFIRST = tuple(
    f.replace("%m/%d", "%d/%m").replace("%m-%d-%Y", "%d-%m-%Y") for f in _DATE_FORMATS_US
)


def cell_to_str(value: object) -> str:
    """Raw cell (csv string or Excel object) to a trimmed string."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == datetime.min.time() else str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        # Excel stores ZIP codes and phone numbers as floats: 2134.0, not "02134".
        return str(int(value))
    return _WS.sub(" ", str(value)).strip()


def squash(text: str) -> str:
    """Lowercase, punctuation to spaces, single spaces. Used for headers and match keys."""
    return _WS.sub(" ", _NON_ALNUM.sub(" ", text.lower())).strip()


def norm_email(value: str) -> str:
    return value.strip().lower().removeprefix("mailto:")


def phone_digits(value: str) -> str:
    """Ten-digit match key, or all digits if the number is not a 10-digit US number."""
    main = re.sub(r"(?i)\s*(ext\.?|x)\s*\d+\s*$", "", value)
    digits = re.sub(r"\D", "", main)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def norm_phone(value: str) -> str:
    digits = phone_digits(value)
    if len(digits) != 10:
        return value.strip()
    ext = re.search(r"(?i)(?:ext\.?|x)\s*(\d+)\s*$", value)
    return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}" + (f" x{ext.group(1)}" if ext else "")


def parse_date(value: str, dayfirst: bool = False) -> date | None:
    text = value.strip()
    if not text:
        return None
    for fmt in _DATE_FORMATS_DAYFIRST if dayfirst else _DATE_FORMATS_US:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def norm_date(value: str, dayfirst: bool = False) -> str:
    parsed = parse_date(value, dayfirst)
    return parsed.isoformat() if parsed else value.strip()


def parse_money(value: str) -> float | None:
    text = value.strip()
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")") or text.startswith("-")
    cleaned = re.sub(r"(?i)usd|[$,\s()+-]", "", text)
    try:
        amount = round(float(cleaned), 2)
    except ValueError:
        return None
    return -amount if negative else amount


def _title_word(word: str) -> str:
    if word.startswith("mc") and len(word) > 2:
        return "Mc" + word[2:].capitalize()
    for sep in ("-", "'"):
        if sep in word:
            return sep.join(part.capitalize() for part in word.split(sep))
    return word.capitalize()


def norm_name(value: str) -> str:
    text = _WS.sub(" ", value).strip()
    # Mixed case is assumed deliberate (McDonald, DeShawn); only fix ALL CAPS and all lower.
    if text.isupper() or text.islower():
        return " ".join(_title_word(w) for w in text.lower().split(" "))
    return text


def norm_street(value: str) -> str:
    text = _WS.sub(" ", value).strip()
    if not (text.isupper() or text.islower()):
        return text
    return " ".join(
        w.upper() if w.upper() in _COMPASS else _title_word(w) for w in text.lower().split(" ")
    )


def split_full_name(value: str) -> tuple[str, str]:
    """Split one name cell into (first, last). Handles "Last, First" and titles."""
    text = _WS.sub(" ", value).strip()
    if not text:
        return "", ""
    if "," in text:
        last, _, first = text.partition(",")
        first_tokens = [t for t in first.split() if squash(t) not in _SUFFIXES | _TITLES]
        return " ".join(first_tokens), last.strip()
    tokens = [t for t in text.split(" ") if squash(t) not in _TITLES | _SUFFIXES]
    if len(tokens) < 2:
        return (tokens[0] if tokens else ""), ""
    cut = len(tokens) - 1
    while cut > 1 and tokens[cut - 1].lower() in _PARTICLES:
        cut -= 1
    return " ".join(tokens[:cut]), " ".join(tokens[cut:])


def norm_state(value: str) -> str:
    text = value.strip()
    return STATES.get(text.lower(), text.upper() if len(text) <= 3 else text)


def norm_postal(value: str) -> str:
    text = value.strip()
    if text.isdigit() and len(text) < 5:
        return text.zfill(5)
    match = re.fullmatch(r"(\d{5})[- ]?(\d{4})", text)
    return f"{match.group(1)}-{match.group(2)}" if match else text


def split_full_address(value: str) -> dict[str, str]:
    """ "12 Oak St, Dayton, OH 45402" to parts. Anything unexpected stays in street."""
    parts = [p.strip() for p in value.split(",") if p.strip()]
    if len(parts) >= 3:
        tail = re.fullmatch(r"(.+?)\s+(\d{5}(?:-\d{4})?)", parts[-1])
        if tail:
            return {
                "street": ", ".join(parts[:-2]),
                "city": parts[-2],
                "state": tail.group(1),
                "postal_code": tail.group(2),
            }
    return {"street": value.strip()}


def first_name_key(value: str) -> str:
    tokens = squash(value).split(" ")
    token = tokens[0] if tokens else ""
    return NICKNAMES.get(token, token)


def last_name_key(value: str) -> str:
    return squash(value).replace(" ", "")


def street_key(value: str) -> str:
    return " ".join(_STREET_ABBR.get(t, t) for t in squash(value).split(" ") if t)


def house_number(value: str) -> str:
    match = re.match(r"\s*(\d+)", value)
    return match.group(1) if match else ""


def company_key(value: str) -> str:
    return " ".join(t for t in squash(value).split(" ") if t and t not in _COMPANY_NOISE)


def normalize_value(kind: str, value: str, dayfirst: bool = False) -> tuple[object, bool]:
    """Normalize one value by field kind. Returns (value, parsed_ok)."""
    if not value:
        return "", True
    if kind == "email":
        email = norm_email(value)
        return email, bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email))
    if kind == "phone":
        return norm_phone(value), len(phone_digits(value)) == 10
    if kind == "date":
        return norm_date(value, dayfirst), parse_date(value, dayfirst) is not None
    if kind == "money":
        amount = parse_money(value)
        return (amount, True) if amount is not None else (value, False)
    if kind == "name":
        return norm_name(value), True
    if kind == "street":
        return norm_street(value), True
    if kind == "state":
        return norm_state(value), True
    if kind == "postal":
        return norm_postal(value), True
    return _WS.sub(" ", value).strip(), True
