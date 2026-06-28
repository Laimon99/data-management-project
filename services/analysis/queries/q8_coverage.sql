-- The integration win: cuisine coverage before (raw Tripadvisor/TheFork first label)
-- vs after (canonical bucket reconciled across all three platforms, Google included).
SELECT
    count() AS total,
    countIf(primary_cuisine != '') AS old_labelled,
    countIf(cuisine_primary NOT IN ('', 'Other')) AS canonical_labelled,
    round(100 * countIf(primary_cuisine != '') / count(), 1) AS pct_old,
    round(100 * countIf(cuisine_primary NOT IN ('', 'Other')) / count(), 1) AS pct_canonical,
    uniqExact(primary_cuisine) AS old_distinct_labels,
    uniqExactIf(cuisine_primary, cuisine_primary NOT IN ('', 'Other')) AS canonical_buckets
FROM {INTEGRATED}
