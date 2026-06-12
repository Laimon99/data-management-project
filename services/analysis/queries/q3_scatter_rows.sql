SELECT
    CAST(rating_platform_count AS String) AS coverage,
    rating_range_5,
    least_reviews
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
WHERE least_reviews IS NOT NULL AND least_reviews > 0
