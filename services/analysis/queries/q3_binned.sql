SELECT
    CAST(rating_platform_count AS String) AS coverage,
    multiIf(
        least_reviews < {sparse}, '0_sparse(<20)',
        least_reviews < 100, '1_low(20-99)',
        least_reviews < 500, '2_mid(100-499)',
        '3_high(500+)'
    ) AS min_reviews_bucket,
    count() AS restaurants,
    round(avg(rating_range_5), 3) AS mean_range
FROM (
    SELECT
        rating_platform_count,
        rating_range_5,
        (ifNull(google_review_count, 0) + ifNull(tripadvisor_review_count, 0)
         + ifNull(thefork_review_count, 0)) AS total_reviews,
        arrayMin(arrayFilter(x -> x IS NOT NULL,
            [google_review_count, tripadvisor_review_count, thefork_review_count])) AS least_reviews
    FROM {INTEGRATED}
    WHERE rating_platform_count >= {min_platforms} AND rating_range_5 IS NOT NULL
)
WHERE least_reviews IS NOT NULL
GROUP BY coverage, min_reviews_bucket
ORDER BY coverage, min_reviews_bucket
