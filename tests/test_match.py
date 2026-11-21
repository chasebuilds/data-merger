from data_merger.config import Config
from data_merger.match import block_keys, candidate_pairs, match_records, score_pair
from data_merger.records import Record, _set_keys


def rec(idx=0, **values) -> Record:
    record = Record(idx, f"f{idx}.csv", 2, dict(values))
    _set_keys(record)
    return record


BOB = dict(first_name="Robert", last_name="Hale", email="rhale@example.com",
           phone="(614) 555-0101", street="12 Oak Street", postal_code="43201")


def test_same_email_and_nickname_is_auto():
    score, why = score_pair(rec(0, **BOB), rec(1, first_name="Bob", last_name="Hale",
                                               email="rhale@example.com"))
    assert score >= 0.88
    assert "email" in why


def test_same_email_different_first_name_goes_to_review():
    score, _ = score_pair(rec(0, **BOB), rec(1, first_name="Dana", last_name="Hale",
                                             email="rhale@example.com"))
    assert 0.70 <= score < 0.88


def test_same_phone_and_name_is_auto_even_with_a_stale_email():
    other = dict(BOB, email="bob.old@example.org", street="", postal_code="")
    assert score_pair(rec(0, **BOB), rec(1, **other))[0] >= 0.88


def test_household_sharing_phone_and_address_is_not_a_match():
    dana = dict(BOB, first_name="Dana", email="dana@example.com")
    assert score_pair(rec(0, **BOB), rec(1, **dana))[0] < 0.70


def test_initial_with_shared_phone_is_review_not_auto():
    initial = dict(first_name="R.", last_name="Hale", phone="614-555-0101")
    score, why = score_pair(rec(0, **BOB), rec(1, **initial))
    assert 0.70 <= score < 0.88
    assert "initial" in why


def test_typo_in_name_with_same_address_is_auto():
    typo = dict(first_name="Robert", last_name="Hael", street="12 Oak St", postal_code="43201")
    score, why = score_pair(rec(0, **BOB), rec(1, **typo))
    assert score >= 0.88
    assert why == "name and address"


def test_same_name_different_city_is_no_match():
    other = dict(first_name="Robert", last_name="Hale", email="rob@example.net",
                 phone="303-555-0188", street="900 Pine Ave", postal_code="80202")
    assert score_pair(rec(0, **BOB), rec(1, **other))[0] < 0.70


def test_same_name_and_zip_only_is_review():
    other = dict(first_name="Robert", last_name="Hale", postal_code="43201")
    assert 0.70 <= score_pair(rec(0, **BOB), rec(1, **other))[0] < 0.88


def test_name_and_company_auto_unless_a_contact_detail_disagrees():
    a = dict(first_name="Ana", last_name="Ruiz", company="Acme Supply Inc")
    b = dict(first_name="Ana", last_name="Ruiz", company="ACME SUPPLY")
    assert score_pair(rec(0, **a), rec(1, **b))[0] >= 0.88
    a["email"], b["email"] = "ana@example.com", "aruiz77@example.org"
    assert 0.70 <= score_pair(rec(0, **a), rec(1, **b))[0] < 0.88


def test_blocking_skips_unrelated_pairs_and_oversized_blocks():
    surnames = ["Hale", "Quinn", "Ruiz", "Okafor", "Tanaka", "Petrov", "Lindqvist", "Cho"]
    people = [rec(i, first_name="Sam", last_name=name, email=f"p{i}@example.com")
              for i, name in enumerate(surnames)]
    pairs, skipped = candidate_pairs(people, 400)
    assert pairs == set()
    assert skipped == []

    shared = [rec(i, first_name=f"N{i}", email="info@example.com") for i in range(12)]
    pairs, skipped = candidate_pairs(shared, 10)
    assert pairs == set()
    assert skipped == [("e:info@example.com", 12)]
    assert "e:info@example.com" in block_keys(shared[0])


def test_clusters_bands_and_within_file_duplicates():
    records = [
        rec(0, **BOB),
        rec(1, first_name="Bob", last_name="Hale", email="rhale@example.com"),
        rec(2, first_name="Rob", last_name="Hale", phone="6145550101"),
        rec(3, first_name="Robert", last_name="Hale", postal_code="43201"),
        rec(4, first_name="Avery", last_name="Quinn", email="avery@example.org"),
    ]
    result = match_records(records, Config())
    assert [0, 1, 2] in result.clusters
    assert [4] in result.clusters
    assert result.auto_pairs == 3
    assert len(result.review) == 1
    assert result.review[0].b == 3
    merged_index = result.clusters.index([0, 1, 2])
    assert result.cluster_scores[merged_index] >= 0.88
    assert result.cluster_scores[result.clusters.index([4])] is None


def test_merge_is_held_back_when_it_would_chain_two_different_people():
    records = [
        rec(0, first_name="Carlos", last_name="James", email="carlos@example.com"),
        rec(1, first_name="Carles", last_name="James", email="carlos@example.com",
            phone="5415550125"),
        rec(2, first_name="Charles", last_name="James", phone="5415550125"),
    ]
    result = match_records(records, Config())
    assert [0, 1] in result.clusters
    assert [2] in result.clusters
    assert any("held back" in pair.basis for pair in result.review)
