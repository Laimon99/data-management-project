SELECT * FROM (
    SELECT
        'google vs tripadvisor' AS pair,
        count() AS venues,
        round(avg(abs(google_rating_5 - tripadvisor_rating_5)), 3) AS mean_abs_diff,
        round(median(abs(google_rating_5 - tripadvisor_rating_5)), 3) AS median_abs_diff,
        round(100 * avg(abs(google_rating_5 - tripadvisor_rating_5) <= 0.5), 1) AS pct_within_0_5,
        round(100 * avg(abs(google_rating_5 - tripadvisor_rating_5) <= 1.0), 1) AS pct_within_1_0
    FROM {INTEGRATED}
    WHERE google_rating_5 IS NOT NULL AND tripadvisor_rating_5 IS NOT NULL
    UNION ALL
    SELECT
        'google vs thefork' AS pair,
        count() AS venues,
        round(avg(abs(google_rating_5 - thefork_rating_5)), 3) AS mean_abs_diff,
        round(median(abs(google_rating_5 - thefork_rating_5)), 3) AS median_abs_diff,
        round(100 * avg(abs(google_rating_5 - thefork_rating_5) <= 0.5), 1) AS pct_within_0_5,
        round(100 * avg(abs(google_rating_5 - thefork_rating_5) <= 1.0), 1) AS pct_within_1_0
    FROM {INTEGRATED}
    WHERE google_rating_5 IS NOT NULL AND thefork_rating_5 IS NOT NULL
    UNION ALL
    SELECT
        'tripadvisor vs thefork' AS pair,
        count() AS venues,
        round(avg(abs(tripadvisor_rating_5 - thefork_rating_5)), 3) AS mean_abs_diff,
        round(median(abs(tripadvisor_rating_5 - thefork_rating_5)), 3) AS median_abs_diff,
        round(100 * avg(abs(tripadvisor_rating_5 - thefork_rating_5) <= 0.5), 1) AS pct_within_0_5,
        round(100 * avg(abs(tripadvisor_rating_5 - thefork_rating_5) <= 1.0), 1) AS pct_within_1_0
    FROM {INTEGRATED}
    WHERE tripadvisor_rating_5 IS NOT NULL AND thefork_rating_5 IS NOT NULL
) ORDER BY pair
