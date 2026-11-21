import csv
from pathlib import Path

import pytest

from benchmark.generate import SOURCES, generate
from benchmark.run_benchmark import report, result_table, score

ROOT = Path(__file__).resolve().parent.parent
EM_DASH = chr(0x2014)


def test_generator_is_seeded(tmp_path):
    generate(tmp_path / "a", entities=40, sources=3, seed=5)
    generate(tmp_path / "b", entities=40, sources=3, seed=5)
    generate(tmp_path / "c", entities=40, sources=3, seed=6)
    for name in ("crm_export.csv", "mailing_list.csv", "truth.csv"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()
    assert (tmp_path / "a" / "crm_export.csv").read_bytes() != (
        tmp_path / "c" / "crm_export.csv").read_bytes()


def test_generator_hides_the_entity_id_and_covers_every_row(tmp_path):
    made = generate(tmp_path, entities=60, sources=5, seed=3)
    assert len(made["paths"]) == 5
    for name, headers in SOURCES:
        assert not any("entity" in h.lower() or h.lower() == "id" for h in headers)
        if name.endswith(".csv"):
            assert "E0000" not in (tmp_path / name).read_text(encoding="utf-8")
    with open(tmp_path / "truth.csv", encoding="utf-8") as handle:
        truth = list(csv.DictReader(handle))
    assert len(truth) == len(made["truth"])
    assert {row["entity_id"] for row in truth} == set(made["entities"])


def test_generator_rejects_bad_source_count(tmp_path):
    with pytest.raises(ValueError):
        generate(tmp_path, sources=2)


def test_scorer_counts_add_up_and_report_has_no_placeholders(tmp_path):
    run = score(150, 4, 11, tmp_path)
    assert run["correct_pairs"] + run["false_pairs"] == run["predicted_pairs"]
    assert run["missed_in_review"] + run["missed_silent"] == run["missed"]
    assert run["correct_pairs"] + run["missed"] == run["true_pairs"]
    assert run["candidates"] < run["all_pairs"] / 10
    assert run["precision"] > 0.95
    text = report([run], 11)
    assert "False merges" in result_table([run])
    assert "{" not in text
    assert EM_DASH not in text


def test_repo_text_files_have_no_em_dash():
    skip = {".venv", ".git", ".ruff_cache", ".pytest_cache", "__pycache__", "data"}
    for path in ROOT.rglob("*"):
        if path.is_file() and path.suffix in {".py", ".md", ".toml", ".yml", ".csv", ".txt"} \
                and not skip & set(path.relative_to(ROOT).parts):
            assert EM_DASH not in path.read_text(encoding="utf-8"), path
