SELECT
    price_tier,
    count() AS restaurants,
    round(avgIf(google_rating_5, google_rating_5 IS NOT NULL), 3) AS google_rating,
    round(avgIf(tripadvisor_rating_5, tripadvisor_rating_5 IS NOT NULL), 3) AS ta_rating,
    round(avgIf(thefork_rating_5, thefork_rating_5 IS NOT NULL), 3) AS tf_rating,
    round(avgIf(rating_avg_5, rating_avg_5 IS NOT NULL), 3) AS mean_rating,
    round(avgIf(rating_range_5, rating_platform_count >= {min_platforms} AND rating_range_5 IS NOT NULL), 3) AS mean_range
FROM {INTEGRATED}
WHERE price_tier IS NOT NULL
GROUP BY price_tier
ORDER BY price_tier
