SELECT * FROM (
    SELECT
        'google - tripadvisor' AS pair,
        count() AS venues,
        round(avg(google_rating_5 - tripadvisor_rating_5), 3) AS mean_signed_diff
    FROM {INTEGRATED}
    WHERE google_rating_5 IS NOT NULL AND tripadvisor_rating_5 IS NOT NULL
    UNION ALL
    SELECT
        'google - thefork' AS pair,
        count() AS venues,
        round(avg(google_rating_5 - thefork_rating_5), 3) AS mean_signed_diff
    FROM {INTEGRATED}
    WHERE google_rating_5 IS NOT NULL AND thefork_rating_5 IS NOT NULL
    UNION ALL
    SELECT
        'tripadvisor - thefork' AS pair,
        count() AS venues,
        round(avg(tripadvisor_rating_5 - thefork_rating_5), 3) AS mean_signed_diff
    FROM {INTEGRATED}
    WHERE tripadvisor_rating_5 IS NOT NULL AND thefork_rating_5 IS NOT NULL
) ORDER BY pair
