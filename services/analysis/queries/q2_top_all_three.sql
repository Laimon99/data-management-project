SELECT
    canonical_name,
    canonical_city,
    google_rating_5,
    tripadvisor_rating_5,
    thefork_rating_5,
    round(rating_range_5, 2) AS rating_range_5
FROM {INTEGRATED}
WHERE has_all_three_platforms = 1 AND rating_range_5 IS NOT NULL
ORDER BY rating_range_5 DESC
LIMIT {top_n}
