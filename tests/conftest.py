from __future__ import annotations

import csv
from pathlib import Path

import pytest


@pytest.fixture
def write_csv(tmp_path: Path):
    def _write(name: str, headers: list[str], rows: list[list[object]]) -> Path:
        path = tmp_path / name
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(headers)
            writer.writerows(rows)
        return path

    return _write


@pytest.fixture
def three_sources(write_csv):
    """One customer in three files, one household member, one stranger."""
    crm = write_csv("crm.csv", ["First Name", "Last Name", "E-mail", "Phone", "Street", "ZIP",
                                "Last Modified"], [
        ["Robert", "Hale", "rhale@example.com", "(614) 555-0101", "12 Oak Street", "43201",
         "03/01/2026"],
        ["Dana", "Hale", "dana.hale@example.com", "(614) 555-0101", "12 Oak Street", "43201",
         "03/01/2026"],
    ])
    billing = write_csv("billing.csv", ["Customer Name", "Contact Email", "Tel", "Balance Due",
                                        "Last Updated"], [
        ["HALE, BOB", "RHale@Example.com", "614.555.0199", "$1,250.00", "2026-06-15"],
        ["Quinn, Avery", "avery@example.org", "303-555-0144", "(40.00)", "2026-01-02"],
    ])
    mailing = write_csv("mailing.csv", ["full_name", "email_address", "zip"], [
        ["Rob Hale", "rhale@example.com", "43201"],
    ])
    return [crm, billing, mailing]
