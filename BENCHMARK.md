# Benchmark

Written by `benchmark/run_benchmark.py` on 2026-11-21 from a real run.
No number on this page was typed by hand.

Command: `python -m benchmark.run_benchmark --seed 20261121 --sizes 1000 10000`
Python 3.14.3 on Windows, one process, default settings
(auto-merge at 0.88, review at 0.70).

## Result

| Measure | 2,898 source rows | 28,512 source rows |
|---|---:|---:|
| Source files | 5 | 5 |
| Real-world entities in the truth table | 1,000 | 10,000 |
| True matching pairs | 3,427 | 32,797 |
| Auto-merged pairs | 3,074 | 29,231 |
| **Auto-merge precision** (pairs) | **100.00%** | **100.00%** |
| **Auto-merge recall** (pairs) | **89.70%** | **89.13%** |
| **False merges** (wrong pairs auto-merged) | **0** | **0** |
| Merged records that mix two entities | 0 | 0 |
| True pairs sent to Review instead | 249 | 2,506 |
| True pairs missed with no flag | 104 | 1,060 |
| Review pairs for a human to check | 109 | 1,337 |
| Review pairs that are real matches | 104 | 1,134 |
| Pairs compared after blocking | 7,105 of 4,197,753 | 345,282 of 406,452,816 |
| Blocking recall (true pairs that were compared at all) | 99.65% | 99.71% |
| Run time: match and resolve | 0.4 s | 3.9 s |
| Run time: write workbook | 0.8 s | 7.3 s |

## How to read it

- **A pair** is two source rows. If three rows describe one customer, that is three pairs.
- **Precision** answers: of the pairs merged without asking, how many were right?
- **Recall** answers: of all pairs that really are the same entity, how many were merged
  without asking? The rest are either in the Review sheet or missed.
- **False merges are the costly error.** Two different customers glued into one record
  can send one person's invoice to another. In the larger run there were
  **0 false-merge pairs** across 29,231 auto-merged pairs,
  inside 0 merged record(s). Every merged record lists its source rows,
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

| Reason for the merge link | Links | Wrong links | Precision |
|---|---:|---:|---:|
| same email, names agree | 14,006 | 0 | 100.00% |
| same phone, names agree | 2,242 | 0 | 100.00% |
| name and address | 572 | 0 | 100.00% |
| name and company | 87 | 0 | 100.00% |
| same email and phone, last name differs | 1 | 0 | 100.00% |

Merges held back for a person in the larger run:
- the two groups hold different contact details: 64
- would chain conflicting records: 35

## The false merge that was found, and the rule added for it

Version 0.1.0 of this tool, on seed 20261120, auto-merged two different
people who had the same full name and the same employer. One row had no email and the
other had no phone, so no single pair of rows showed a contradiction. Their groups did:
different emails, different phones, different addresses.

Version 0.2.0 adds one rule. Before two groups are joined on a fuzzy link (name plus
address, or name plus company), the contact details of the whole groups are compared. If
both groups have emails and share none, and both have phones and share none, the join goes
to Review. For a name-plus-company link, one of the two is enough. Links made by a shared
email or phone are not affected.

The rule was written after seeing that failure, so seed 20261120 can no
longer count as unseen data. The main table above uses seed 20261121, which
was not looked at before the rule was fixed. Both are shown here with the rule off and on,
at 28,512 and 28,679 source rows:

| Seed | Guard | Precision | Recall | False-merge pairs | Mixed records | True pairs in Review |
|---|---|---:|---:|---:|---:|---:|
| 20261121 (unseen) | off | 100.00% | 89.51% | 0 | 0 | 2,381 |
| 20261121 (unseen) | on | 100.00% | 89.13% | 0 | 0 | 2,506 |
| 20261120 (seen) | off | 99.97% | 89.78% | 9 | 1 | 2,262 |
| 20261120 (seen) | on | 100.00% | 89.42% | 0 | 0 | 2,382 |

The cost of the rule is the recall it gives up: true pairs that used to merge on their own
and now wait in Review. The rule does not make false merges impossible. Two people with
the same name and employer, where the files hold no email or phone that differs, will
still be merged.

## Conflict resolution

Where sources disagreed about a value and at least one source row held the entity's
current value, the default rule (`most_recent`) was scored against the truth table:

- email: kept the current value in 1,243 of 1,409 disputed merges (88.22%)
- phone: kept the current value in 941 of 1,039 disputed merges (90.57%)

A source without a usable date cannot win on recency, so these numbers depend on how many
sources carry a last-updated column. Here four of five source schemas have one.

## What the test data looks like

`benchmark/generate.py` builds a truth table of people (seed 20261121), then writes each one
into a random subset of 5 source files with different headers and formats.
Each appearance can get a nickname, an initial, a typo, changed casing, a reformatted
phone, a missing email, phone, address or company, or a stale email, phone or address
from an older date. About 3 in 100 are entered twice in the same file.

About 1 in 10 entities is a deliberate look-alike of another one
(1,004 in the larger run): a household member with the same surname,
address and often phone, or a different person with the same full name. These exist to
give false merges a fair chance to happen.

The true entity id is never written to a source file. It lives in `truth.csv`, which only
the scorer reads.

## Limits of this benchmark

- The data is synthetic. Real exports have problems this generator does not model, and
  real results will differ. Scores on a client's files are unknown until they are checked.
- Matching thresholds were set while developing against seed 1. The main table comes
  from seed 20261121, which was not used for tuning, but both come from the same generator.
- Blocking recall counts true pairs the tool never compared. Those cannot be merged or
  sent to Review at any threshold.
- Names, cities and formats are United States style only.
- Run time is from one desktop PC and will vary by machine.
