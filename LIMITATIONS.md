# Limitations

What data-merger does not do, or does poorly. Read this before trusting a merge.

## Matching

- **It can merge two different people.** The benchmark measures how often on synthetic data (see `BENCHMARK.md`, which also documents a false merge an earlier version made and the rule added after it). The benchmark does not predict the rate on real files; use `--audit-sample` and `data-merger audit` to measure it on the job. A wrong merge is not flagged anywhere; the only defence is the `source_rows` column, which shows exactly which rows were combined so a wrong merge can be split by hand.
- **Same name, same address, same phone.** A parent and child with the same name at one address (Sr. and Jr.) look like one person. Suffixes such as Jr and Sr are stripped from single-column names, not used to tell people apart.
- **Same name at the same company** with no email or phone to contradict it is auto-merged. In a large company that can be two people. The contact-detail guard only helps when the files hold an email or phone for both people.
- **Common names get no extra caution.** "John Smith" at one address is scored the same as a rare name. Rarer names are stronger evidence, and the scoring does not use that.
- **The audit sample measures precision, not recall.** It samples merges that were made and pairs that scored just under the review band. Matches the tool never compared (no shared blocking key) are not in the sample, so missed matches can only be estimated loosely.
- **No shared evidence means no match.** If two rows for one person share only the name (for example an old email in one file, no phone, no address), they stay separate and appear in `Unmatched`. The tool does not match on name alone, because common names would be merged wrongly.
- **Initials are not enough.** "R. Hale" with the same phone as "Robert Hale" goes to `Review`, not auto-merge, because it could be a relative.
- **Short first names with a typo** ("Amy" typed as "Any") fall below the similarity cutoff and are not matched by name.
- **Swapped fields are not detected.** A first name typed in the last-name column will not match.
- **Shared values are skipped when very common.** If more than 400 rows share one email or phone (a switchboard number, a placeholder like `none@none.com`), that key is not used for matching. The skipped keys are listed in `Summary`.
- **Review pairs are one per pair of merged records**, the strongest one. Weaker candidate pairs between the same two records are not listed separately.
- **Review decisions are matched by file name and row number.** `--decisions` applies an answer only if both rows still exist at the same row numbers. If a source file was re-exported with rows in a different order, answers can attach to the wrong rows; rerun the review in that case.
- **The output workbook is not a valid input.** Its first sheet is `Read me`. To merge a result with another file, save the `Merged` sheet as its own file first.

## Data types and formats

- **United States conventions.** Phone numbers are treated as 10-digit US numbers; anything else is kept as typed and not matched on. States are US states. ZIP codes are US ZIP codes. Month comes before day unless `dayfirst = true` is set in the config, and that setting applies to every file in the run.
- **Dates with two-digit years, or text like "last spring"**, may not parse. Unparsed values are kept as typed and listed in `Summary`. A row with no parsed date cannot win a `most_recent` decision.
- **`most_recent` needs a date column.** A file with no last-updated column loses every recency decision to files that have one, and ties fall back to source priority (the order the files were given).
- **Money is one currency.** Symbols are stripped; nothing is converted. European formatting (`1.234,56`) is not handled.
- **Single-line addresses** are split only in the form `street, city, ST 12345`. Anything else stays whole in the street column.
- **Names.** Middle names are kept with the first name. Non-Latin scripts are not transliterated, and accented letters are not treated as equal to unaccented ones.
- **Extra columns** (headers with no canonical match) are carried through as text with no type cleanup.

## Schema alignment

- The canonical schema is fixed: people and contacts (name, email, phone, address, company). Product lists, SKUs, transactions and lists of companies with no contact person are not fuzzy-merged well. If those share an ID column, use `data-merger join`; if not, they need custom rules, which means code changes, not config.
- The nickname table (Bob for Robert) and the sound-alike surname key (Soundex) are English-centric. Names from other languages get fewer candidate comparisons and no nickname help. Name order is assumed to be given name then family name.
- Fuzzy header matching can be wrong on unusual headers. Every mapping is shown in the `Mapping` sheet and can be overridden in the config; check that sheet first.
- Only the first sheet of an Excel file is read (other sheets are named in `Summary`), and the first row must be the header. Merged cells, title rows above the header, multi-row headers and hidden rows are not detected. Formulas are read as their last saved value; a file never opened in Excel after a formula was written has none.
- IDs and ZIP codes that Excel already stored as numbers have lost their leading zeros before this tool sees them. ZIP codes are padded back to five digits; other IDs are not, and `join` lists them under `Near keys` instead of guessing.
- Text files are read as UTF-8, and as Windows-1252 if that fails. The second is a guess, stated in `Summary`. Other encodings (UTF-16, Shift-JIS) are not handled. The separator is picked from the header line: comma, semicolon, tab or pipe.
- Two source files cannot have the same file name, because lineage refers to files by name.

## Scale and files

- Everything is held in memory. The benchmark covers about 28,000 source rows; much larger inputs are untested.
- The `Lineage` sheet is left out, with a note in `Summary`, if it would exceed Excel's row limit. `--no-lineage` skips it on purpose.
- Legacy `.xls` and password-protected workbooks are not supported.
- `join` works on two files and one key column. Composite keys and joins across three or more files are not supported.
- No model or outside service is used. Matching is fixed rules and string similarity, so it will not understand context a person would ("this is the same shop under a new name").
