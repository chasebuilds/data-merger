-- Example queries against the database written by:
--   data-merger merge a.csv b.xlsx c.csv -o merged.xlsx --sqlite merged.db
-- Run one with:  sqlite3 merged.db < docs/queries.sql  (or paste a single query)
--
-- records has one column per merged field (first_name, email, phone, ...), so queries that
-- name a field assume the source files had it. The other tables have a fixed shape.
-- Each query starts with a "-- name:" line; tests/test_queries.py runs every one.

-- name: records_built_from_3_or_more_rows
-- Merged records that combined three or more source rows, and which files they came from.
SELECT r.record_id,
       r.first_name || ' ' || r.last_name           AS name,
       r.source_count,
       COUNT(DISTINCT s.source_file)                AS files,
       GROUP_CONCAT(s.source_file || ':' || s.source_row, '; ') AS source_rows,
       r.match_score
FROM records r
JOIN sources s ON s.record_id = r.record_id
WHERE r.source_count >= 3
GROUP BY r.record_id
ORDER BY r.source_count DESC, r.record_id;

-- name: fields_with_conflicts
-- Which fields disagree most often across merged rows, and which rule settled them.
SELECT c.field,
       c.rule,
       COUNT(*)                    AS conflicts,
       COUNT(DISTINCT c.record_id) AS records_affected
FROM conflicts c
GROUP BY c.field, c.rule
ORDER BY conflicts DESC, c.field;

-- name: unmatched_rows_by_source_file
-- Rows that matched nothing, per file, as a share of the rows read from that file.
SELECT f.file_name,
       f.rows_read,
       COUNT(r.record_id)                                   AS unmatched_rows,
       ROUND(100.0 * COUNT(r.record_id) / f.rows_read, 1)   AS unmatched_pct
FROM source_files f
LEFT JOIN sources s ON s.source_file = f.file_name
LEFT JOIN records r ON r.record_id = s.record_id AND r.source_count = 1
GROUP BY f.file_name
ORDER BY unmatched_pct DESC;

-- name: file_overlap
-- For each pair of files, how many merged records contain rows from both.
WITH record_files AS (
    SELECT DISTINCT record_id, source_file FROM sources
)
SELECT a.source_file AS file_a,
       b.source_file AS file_b,
       COUNT(*)      AS shared_records
FROM record_files a
JOIN record_files b ON b.record_id = a.record_id AND a.source_file < b.source_file
GROUP BY a.source_file, b.source_file
ORDER BY shared_records DESC;

-- name: winning_source_per_field
-- Which file supplied the kept value for each field, ranked within the field.
WITH wins AS (
    SELECT l.field, s.source_file, COUNT(*) AS values_kept
    FROM lineage l
    JOIN sources s ON s.source_id = l.source_id
    GROUP BY l.field, s.source_file
)
SELECT field,
       source_file,
       values_kept,
       RANK() OVER (PARTITION BY field ORDER BY values_kept DESC) AS rank_in_field
FROM wins
ORDER BY field, rank_in_field, source_file;

-- name: conflict_detail_with_rows
-- Every losing value next to the kept one, with the exact file and row of each.
SELECT c.record_id,
       c.field,
       c.kept_value,
       ks.source_file || ':' || ks.source_row AS kept_from,
       c.lost_value,
       ls.source_file || ':' || ls.source_row AS lost_from,
       c.rule
FROM conflicts c
JOIN sources ks          ON ks.source_id = c.kept_source_id
JOIN conflict_losers cl  ON cl.conflict_id = c.conflict_id
JOIN sources ls          ON ls.source_id = cl.source_id
ORDER BY c.record_id, c.field;

-- name: review_queue
-- Pairs waiting for a person, strongest first, with both records side by side.
SELECT p.pair_id,
       p.match_score,
       p.why,
       a.record_id AS record_a, a.first_name || ' ' || a.last_name AS name_a, a.email AS email_a,
       b.record_id AS record_b, b.first_name || ' ' || b.last_name AS name_b, b.email AS email_b
FROM review_pairs p
JOIN records a ON a.record_id = p.record_a
JOIN records b ON b.record_id = p.record_b
WHERE p.decision IS NULL
ORDER BY p.match_score DESC;

-- name: single_source_values_on_merged_records
-- Values on multi-row records that only one row supports: worth a look before a mail-out.
SELECT l.record_id,
       l.field,
       l.value,
       s.source_file || ':' || s.source_row AS taken_from,
       r.source_count
FROM lineage l
JOIN records r ON r.record_id = l.record_id
JOIN sources s ON s.source_id = l.source_id
WHERE r.source_count >= 2
  AND l.agreeing_rows = 1
  AND l.field IN ('email', 'phone', 'street')
ORDER BY l.record_id, l.field;
